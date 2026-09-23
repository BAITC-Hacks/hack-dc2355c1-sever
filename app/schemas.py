from typing import Any, Literal

from pydantic import BaseModel, Field


class Alternative(BaseModel):
    scenario_id: str
    confidence: float = 0.0
    why: str = ""


class RouteDecision(BaseModel):
    """Structured output LLM-роутера."""

    action: Literal["route", "clarify", "handoff"] = "route"
    scenario_id: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    alternatives: list[Alternative] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    secondary_scenario_id: str | None = None
    language: Literal["ru", "kk", "mixed"] = "ru"
    clarify_question: str | None = None


class Turn(BaseModel):
    role: Literal["user", "bot"]
    text: str
    scenario_id: str | None = None


class Trace(BaseModel):
    session_id: str
    turn: int
    user_text: str
    bot_text: str
    decision: RouteDecision
    path: str  # fast | strong | fast->strong | error
    candidates: list[str] = Field(default_factory=list)
    stages_ms: dict[str, float] = Field(default_factory=dict)
    topic_queue: list[str] = Field(default_factory=list)
    ts: float = 0.0
