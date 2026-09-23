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
        self.reply_language = "ru"
        self.client: dict | None = None  # результат find_client
        self.previews: dict[str, dict] = {}  # необратимые действия, озвученные клиенту и ждущие «да»
        self._why_tasks: dict[int, asyncio.Task | None] = {}

    async def handle_text(self, text: str, sw: Stopwatch | None = None, on_text=None) -> Trace:
        """on_text(sentence) — куда отдавать предложения ответа по мере генерации (TTS).
        Если ответ собран без генерации (системные реплики), вызывающий озвучивает trace.bot_text сам."""
        sw = sw or Stopwatch()
        history = self.history[-settings.history_turns * 2 :]
        with sw.stage("triage"):
            triage = normalize.extract(text)

        # Параллельный запуск: чаще всего реплика — продолжение активного сценария (ответ на вопрос бота),
        # поэтому исполнитель стартует одновременно с роутером. Его текст и действия, меняющие данные,
        # ждут решения роутера; если роутер выбрал другое — заготовка выбрасывается.
        spec = _Speculation(self, text, triage, on_text) if self._can_speculate() else None

        d, path, cands, why_task = await cascade.route(text, history, self.active, self.low_streak, sw, triage)
        prev_active = self.active
        # Язык ответа: реплика на казахском → kk; короткое «да/иә/верно» язык не переключает.
        if d.language == "kk":
            d.reply_language = "kk"
        elif len(text.split()) <= 3 and self.history:
            d.reply_language = self.reply_language

        self.low_streak = self.low_streak + 1 if d.action == "clarify" and d.confidence < settings.clarify_threshold else 0
        # Идентификаторы, собранные кодом, надёжнее LLM — перекрывают её значения.
        d.slots.update(triage["ids"])
        self.slots.update(d.slots)

        queued = False
        extra: list[str] = []
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
            extra = [s.scenario_id for s in d.scenarios[1:]]
        elif d.action == "continue":
            # Вторая тема внутри продолжения («да, запишите. А анализы бесплатно?») — не теряем.
            extra = [s.scenario_id for s in d.scenarios[1:] if s.scenario_id in catalog.scenarios]
            for sid in extra:
                if sid not in self.topic_queue:
                    self.topic_queue.append(sid)
        elif d.action in ("handoff", "goodbye"):
            self.active = None

        spec_hit = bool(spec) and d.action == "continue" and self.active == prev_active and not extra \
            and d.reply_language == self.reply_language
        if spec and not spec_hit:
            spec.cancel()
        self.reply_language = d.reply_language

        actions: list[dict] = []
        handoff_queue = None
        with sw.stage("response"):
            reply = build_reply(d, queued=queued and len(d.scenarios) > 1)
            if d.action in ("route", "continue") and self.active in catalog.scenarios and llm.available("openai"):
                try:
                    if spec_hit:
                        res = await spec.confirm()
                        sw.note("speculative", "hit")
                    else:
                        res = await executor.run(
                            self.active, d.reply_language, text, self._llm_history(), self.client,
                            self.slots, [q for q in self.topic_queue if q != self.active and q not in extra],
                            self.previews, d.slots, on_text=on_text, extra=extra,
                        )
                    reply, actions, handoff_queue = res.reply or reply, res.actions, res.handoff_queue
                    self.client, self.previews = res.client, res.previews
                    for sid in extra:  # вторую тему исполнитель уже закрыл в этом ответе
                        if sid in self.topic_queue:
                            self.topic_queue.remove(sid)
                    if res.completed:
                        self.active = self.topic_queue.pop(0) if self.topic_queue else None
                    if handoff_queue:
                        self.active = None
                except Exception as e:  # исполнитель не должен ронять разговор — остаётся стартовая реплика
                    sw.note("executor_error", str(e)[:300])
            elif d.action == "handoff":
                out = backend.call("transfer_to_operator", {"queue": "operator_general", "summary": self._summary_text()})
                actions, handoff_queue = [{"name": "transfer_to_operator", "args": {"queue": "operator_general"}, "result": out}], "operator_general"
        if spec_hit:
            sw.stages["parallel_executor"] = 1.0  # метка для трассировки: исполнитель шёл параллельно с роутером

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

    def _can_speculate(self) -> bool:
        return settings.speculative_executor and self.active in catalog.scenarios and llm.available("openai")

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


class _Speculation:
    """Исполнитель, запущенный до решения роутера в предположении «продолжение активного сценария»."""

    def __init__(self, session: "Session", text: str, triage: dict, on_text) -> None:
        loop = asyncio.get_running_loop()
        self.gate: asyncio.Future[bool] = loop.create_future()
        self.on_text, self.buffer, self.released = on_text, [], False
        slots = {**session.slots, **triage["ids"]}
        self.task = asyncio.create_task(executor.run(
            session.active, session.reply_language, text, session._llm_history(), session.client, slots,
            [q for q in session.topic_queue if q != session.active], session.previews, triage["ids"],
            on_text=self._say if on_text else None, gate=self.gate,
        ))
        self.task.add_done_callback(lambda t: t.cancelled() or t.exception())  # ошибка заготовки не шумит в логах

    async def _say(self, sentence: str) -> None:
        if self.released:
            await self.on_text(sentence)
        else:
            self.buffer.append(sentence)  # держим до решения роутера

    async def confirm(self) -> "executor.ExecResult":
        self.gate.set_result(True)
        while self.buffer:
            await self.on_text(self.buffer.pop(0))
        self.released = True
        return await self.task

    def cancel(self) -> None:
        if not self.gate.done():
            self.gate.set_result(False)
        self.task.cancel()


def _actions_note(actions: list[dict]) -> str | None:
    parts = []
    for a in actions:
        res = a.get("result")
        if res is None:
            continue
        brief = json.dumps(res, ensure_ascii=False, default=str)
        parts.append(f"{a['name']}{':' + a['mode'] if a.get('mode') else ''} → {brief[:300]}")
    return "; ".join(parts) or None
