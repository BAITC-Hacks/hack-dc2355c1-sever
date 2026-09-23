"""Гибридный каскад: быстрая LLM (NVIDIA) → при сомнении сильная LLM (OpenAI) → политика."""

import asyncio

from ..config import settings
from ..providers import llm
from ..schemas import RouteDecision, Turn
from ..tracing import Stopwatch
from . import candidates, llm_router, policy


def _needs_escalation(d: RouteDecision) -> bool:
    return (
        d.confidence < settings.fast_confidence_threshold
        or d.language == "mixed"
        or len(d.scenarios) > 1
        or d.primary == "SYS_UNCLEAR"
    )


async def raw_route(
    text: str, history: list[Turn], active: str | None, sw: Stopwatch, triage: dict | None = None
) -> tuple[RouteDecision | None, str, list[str], "asyncio.Task[dict] | None"]:
    """Ответ LLM без политики (нужен и для eval, и для диалога).
    Последний элемент — задача, дочитывающая обоснование (why) после того, как решение уже принято."""
    cands: list[str] = []
    if settings.top_k_candidates:
        with sw.stage("candidates"):
            cands = await candidates.top_k(text, must_include=[active] if active else None)

    path: list[str] = []
    decision: RouteDecision | None = None
    full: asyncio.Task[dict] | None = None

    if settings.use_fast_path and llm.available("nvidia"):
        try:
            with sw.stage("router_fast"):
                decision, full = await llm_router.decide("nvidia", text, history, active, cands or None, triage)
            path.append("fast")
        except Exception as e:  # быстрый путь не должен ронять разговор
            sw.note("router_fast_error", str(e)[:200])

    if (decision is None or _needs_escalation(decision)) and llm.available("openai"):
        if full:
            full.cancel()
        with sw.stage("router_strong"):
            decision, full = await llm_router.decide("openai", text, history, active, cands or None, triage)
        path.append("strong")

    return decision, "->".join(path) or "error", cands, full


async def route(
    text: str, history: list[Turn], active: str | None, low_streak: int, sw: Stopwatch, triage: dict | None = None
) -> tuple[RouteDecision, str, list[str], "asyncio.Task[dict] | None"]:
    decision, path, cands, full = await raw_route(text, history, active, sw, triage)
    if decision is None:
        return RouteDecision(action="handoff", reasoning="LLM недоступна — передаю оператору."), "error", cands, None
    with sw.stage("policy"):
        decision = policy.apply(decision, active, low_streak)
    return decision, path, cands, full
