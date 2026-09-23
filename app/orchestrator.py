"""Сессия диалога: история, активный сценарий, очередь отложенных тем."""

import time
import uuid

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
        self.clarify_streak = 0

    async def handle_text(self, text: str, sw: Stopwatch | None = None) -> Trace:
        sw = sw or Stopwatch()
        history = self.history[-settings.history_turns * 2 :]
        decision, path, cands = await cascade.route(text, history, self.active, sw)

        # Два переспроса подряд — не мучаем клиента, передаём оператору с контекстом.
        if decision.action == "clarify":
            self.clarify_streak += 1
            if self.clarify_streak >= 2:
                decision.action = "handoff"
                decision.reasoning += " Второй переспрос подряд — передаём оператору."
        else:
            self.clarify_streak = 0

        queued = None
        if decision.action == "route":
            if decision.scenario_id in self.topic_queue:
                self.topic_queue.remove(decision.scenario_id)
            sec = decision.secondary_scenario_id
            if sec and sec != decision.scenario_id and sec not in self.topic_queue:
                self.topic_queue.append(sec)
                queued = sec
            self.active = decision.scenario_id

        with sw.stage("response"):
            reply = build_reply(decision, queued)

        self.history.append(Turn(role="user", text=text, scenario_id=decision.scenario_id))
        self.history.append(Turn(role="bot", text=reply))

        return Trace(
            session_id=self.id,
            turn=len(self.history) // 2,
            user_text=text,
            bot_text=reply,
            decision=decision,
            path=path,
            candidates=cands,
            stages_ms=sw.stages,
            topic_queue=list(self.topic_queue),
            ts=time.time(),
        )

    def handoff_summary(self) -> dict:
        """Контекст для оператора при передаче."""
        return {
            "session_id": self.id,
            "active_scenario": self.active,
            "pending_topics": self.topic_queue,
            "transcript": [t.model_dump() for t in self.history],
        }


def finish(trace: Trace, sw: Stopwatch) -> Trace:
    trace.stages_ms = dict(sw.stages)
    trace.stages_ms["total"] = sw.total()
    record(trace)
    return trace
