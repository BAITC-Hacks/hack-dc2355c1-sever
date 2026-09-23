"""Сессия диалога: история, активный сценарий, стек отложенных тем, слоты."""

import asyncio
import json
import time
import uuid
from typing import Any

from . import backend, executor, normalize
from .config import settings
from .responder import build_reply
from .catalog import catalog
from .providers import llm
from .router import cascade
from .schemas import Trace, Turn
from .tracing import Stopwatch, record


class Session:
    def __init__(self, session_id: str | None = None) -> None:
        self.id = session_id or uuid.uuid4().hex[:8]
        self.history: list[Turn] = []
        self.active: str | None = None
        self.topic_queue: list[str] = []
        self.slots: dict[str, Any] = {}
        self.low_streak = 0
        self.client: dict | None = None  # результат find_client
        self.previews: dict[str, dict] = {}  # необратимые действия, озвученные клиенту и ждущие «да»
        self._why_tasks: dict[int, asyncio.Task | None] = {}

    async def handle_text(self, text: str, sw: Stopwatch | None = None) -> Trace:
        sw = sw or Stopwatch()
        history = self.history[-settings.history_turns * 2 :]
        with sw.stage("triage"):
            triage = normalize.extract(text)
        d, path, cands, why_task = await cascade.route(text, history, self.active, self.low_streak, sw, triage)

        self.low_streak = self.low_streak + 1 if d.action == "clarify" and d.confidence < settings.clarify_threshold else 0
        # Идентификаторы, собранные кодом, надёжнее LLM — перекрывают её значения.
        d.slots.update(triage["ids"])
        self.slots.update(d.slots)

        queued = False
        if d.action == "route":
            new_active = d.primary
            rest = [s.scenario_id for s in d.scenarios[1:]]
            # Прерванную тему кладём в стек, чтобы вернуться к ней после новой.
            if self.active and self.active != new_active and self.active not in rest:
                rest.append(self.active)
            for sid in rest:
                if sid != new_active and sid not in self.topic_queue:
                    self.topic_queue.append(sid)
                    queued = True
            if new_active in self.topic_queue:
                self.topic_queue.remove(new_active)
            self.active = new_active
        elif d.action in ("handoff", "goodbye"):
            self.active = None

        actions: list[dict] = []
        handoff_queue = None
        with sw.stage("response"):
            reply = build_reply(d, queued=queued and len(d.scenarios) > 1)
            if d.action in ("route", "continue") and self.active in catalog.scenarios and llm.available("openai"):
                try:
                    res = await executor.run(
                        self.active, d.reply_language, text, self._llm_history(), self.client,
                        self.slots, [q for q in self.topic_queue if q != self.active], self.previews, d.slots,
                    )
                    reply, actions, handoff_queue = res.reply or reply, res.actions, res.handoff_queue
                    self.client, self.previews = res.client, res.previews
                    if res.completed:
                        self.active = self.topic_queue.pop(0) if self.topic_queue else None
                    if handoff_queue:
                        self.active = None
                except Exception as e:  # исполнитель не должен ронять разговор — остаётся стартовая реплика
                    sw.note("executor_error", str(e)[:300])
            elif d.action == "handoff":
                out = backend.call("transfer_to_operator", {"queue": "operator_general", "summary": self._summary_text()})
                actions, handoff_queue = [{"name": "transfer_to_operator", "args": {"queue": "operator_general"}, "result": out}], "operator_general"

        self.history.append(Turn(role="user", text=text, scenario_id=d.primary))
        self.history.append(Turn(role="bot", text=reply, meta=_actions_note(actions)))

        trace = Trace(
            session_id=self.id,
            turn=len(self.history) // 2,
            user_text=text,
            bot_text=reply,
            decision=d,
            path=path,
            candidates=cands,
            stages_ms=sw.stages,
            active_scenario=self.active,
            topic_queue=list(self.topic_queue),
            actions=actions,
            client_id=(self.client or {}).get("client_id"),
            handoff_queue=handoff_queue,
            ts=time.time(),
        )
        self._why_tasks[id(trace)] = why_task
        return trace

    def _llm_history(self) -> list[dict]:
        """История для исполнителя: к репликам бота добавлены итоги его действий (номера, суммы)."""
        return [{"role": "user" if t.role == "user" else "assistant",
                 "content": t.text + (f"\n[служебно, клиенту не озвучено: {t.meta}]" if t.meta else "")}
                for t in self.history[-settings.history_turns * 2 :]]

    def _summary_text(self) -> str:
        last = " | ".join(t.text for t in self.history[-4:] if t.role == "user")
        who = (self.client or {}).get("full_name", "клиент не идентифицирован")
        return f"{who}; тема: {self.active or '—'}; отложено: {self.topic_queue}; слоты: {self.slots}; последние реплики: {last}"

    def handoff_summary(self) -> dict:
        """Контекст для оператора при передаче."""
        return {
            "session_id": self.id,
            "active_scenario": self.active,
            "pending_topics": self.topic_queue,
            "client": self.client,
            "slots": self.slots,
            "transcript": [t.model_dump() for t in self.history],
        }

    async def finish(self, trace: Trace, sw: Stopwatch) -> Trace:
        """Дожидаемся обоснования роутера (генерировалось параллельно с ответом) и пишем трассу."""
        trace.stages_ms = dict(sw.stages)
        trace.stages_ms["total"] = sw.total()
        task = self._why_tasks.pop(id(trace), None)
        if task:
            try:
                full = await asyncio.wait_for(task, timeout=10)
                trace.decision.reasoning = full.get("why") or trace.decision.reasoning
            except Exception:
                pass
        record(trace)
        return trace


def _actions_note(actions: list[dict]) -> str | None:
    parts = []
    for a in actions:
        res = a.get("result")
        if res is None:
            continue
        brief = json.dumps(res, ensure_ascii=False, default=str)
        parts.append(f"{a['name']}{':' + a['mode'] if a.get('mode') else ''} → {brief[:300]}")
    return "; ".join(parts) or None
