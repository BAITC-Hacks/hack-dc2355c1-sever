from typing import Any, Literal

from pydantic import BaseModel, Field

Action = Literal["route", "continue", "clarify", "handoff", "out_of_scope", "goodbye"]


class ScenarioHit(BaseModel):
    scenario_id: str
    confidence: float = 0.0
    reason: str = ""


class RouteDecision(BaseModel):
    """Structured output LLM-роутера (формат из README стартового кита) + решение политики."""

    scenarios: list[ScenarioHit] = Field(default_factory=list)  # в порядке упоминания
    alternatives: list[ScenarioHit] = Field(default_factory=list)
    language: Literal["ru", "kk", "mixed"] = "ru"
    reply_language: Literal["ru", "kk"] = "ru"
    slots: dict[str, Any] = Field(default_factory=dict)
    is_continuation: bool = False
    clarify_question: str | None = None
    reasoning: str = ""
    # Заполняет политика принятия решений, не LLM:
    action: Action = "route"
    policy_note: str = ""

    @property
    def primary(self) -> str | None:
        return self.scenarios[0].scenario_id if self.scenarios else None

    @property
    def confidence(self) -> float:
        return self.scenarios[0].confidence if self.scenarios else 0.0

    def predicted_ids(self) -> list[str]:
        """То, что уходит в predictions.json для evaluate.py."""
        if self.action == "clarify":
            return ["SYS_UNCLEAR"]
        if self.action == "out_of_scope":
            return ["SYS_OUT_OF_SCOPE"]
        return [s.scenario_id for s in self.scenarios]


class Turn(BaseModel):
    role: Literal["user", "bot"]
    text: str
    scenario_id: str | None = None
    meta: str | None = None  # итоги действий бота (для контекста исполнителя)


class Trace(BaseModel):
    session_id: str
    turn: int
    user_text: str
    bot_text: str
    decision: RouteDecision
    path: str  # fast | strong | fast->strong | error
    candidates: list[str] = Field(default_factory=list)
    stages_ms: dict[str, float] = Field(default_factory=dict)
    active_scenario: str | None = None
    topic_queue: list[str] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    client_id: str | None = None
    handoff_queue: str | None = None
    ts: float = 0.0
