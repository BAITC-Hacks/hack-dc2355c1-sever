"""Гибридный каскад: быстрая LLM (NVIDIA) → при сомнении сильная LLM (OpenAI) → политика."""

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


async def raw_route(text: str, history: list[Turn], active: str | None, sw: Stopwatch) -> tuple[RouteDecision | None, str, list[str]]:
    """Ответ LLM без политики (нужен и для eval, и для диалога)."""
    cands: list[str] = []
    if settings.top_k_candidates:
        with sw.stage("candidates"):
            cands = await candidates.top_k(text, must_include=[active] if active else None)

    path: list[str] = []
    decision: RouteDecision | None = None

    if settings.use_fast_path and llm.available("nvidia"):
        try:
            with sw.stage("router_fast"):
                decision = await llm_router.decide("nvidia", text, history, active, cands or None)
            path.append("fast")
        except Exception as e:  # быстрый путь не должен ронять разговор
            sw.note("router_fast_error", str(e)[:200])

    if (decision is None or _needs_escalation(decision)) and llm.available("openai"):
        with sw.stage("router_strong"):
            decision = await llm_router.decide("openai", text, history, active, cands or None)
        path.append("strong")

    return decision, "->".join(path) or "error", cands


async def route(
    text: str, history: list[Turn], active: str | None, low_streak: int, sw: Stopwatch
) -> tuple[RouteDecision, str, list[str]]:
    decision, path, cands = await raw_route(text, history, active, sw)
    if decision is None:
        return RouteDecision(action="handoff", reasoning="LLM недоступна — передаю оператору."), "error", cands
    with sw.stage("policy"):
        decision = policy.apply(decision, active, low_streak)
    return decision, path, cands
