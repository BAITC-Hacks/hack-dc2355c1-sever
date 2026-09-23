"""Сессия диалога: история, активный сценарий, стек отложенных тем, слоты."""

import time
import uuid
from typing import Any

from .config import settings
from .responder import build_reply
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

    async def handle_text(self, text: str, sw: Stopwatch | None = None) -> Trace:
        sw = sw or Stopwatch()
        history = self.history[-settings.history_turns * 2 :]
        d, path, cands = await cascade.route(text, history, self.active, self.low_streak, sw)

        self.low_streak = self.low_streak + 1 if d.action == "clarify" and d.confidence < settings.clarify_threshold else 0
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

        with sw.stage("response"):
            reply = build_reply(d, queued=queued and len(d.scenarios) > 1)

        self.history.append(Turn(role="user", text=text, scenario_id=d.primary))
        self.history.append(Turn(role="bot", text=reply))

        return Trace(
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
            ts=time.time(),
        )

    def handoff_summary(self) -> dict:
        """Контекст для оператора при передаче."""
        return {
            "session_id": self.id,
            "active_scenario": self.active,
            "pending_topics": self.topic_queue,
            "slots": self.slots,
            "transcript": [t.model_dump() for t in self.history],
        }


def finish(trace: Trace, sw: Stopwatch) -> Trace:
    trace.stages_ms = dict(sw.stages)
    trace.stages_ms["total"] = sw.total()
    record(trace)
    return trace
