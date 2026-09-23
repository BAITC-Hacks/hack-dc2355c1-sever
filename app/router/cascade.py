"""Гибридный каскад: кандидаты → быстрая LLM (NVIDIA) → сильная LLM (OpenAI)."""

from ..config import settings
from ..providers import llm
from ..schemas import RouteDecision, Turn
from ..tracing import Stopwatch
from . import candidates, llm_router


def _needs_escalation(d: RouteDecision) -> bool:
    return (
        d.action != "route"
        or d.confidence < settings.fast_confidence_threshold
        or d.language == "mixed"
        or d.secondary_scenario_id is not None
    )


async def route(text: str, history: list[Turn], active: str | None, sw: Stopwatch) -> tuple[RouteDecision, str, list[str]]:
    with sw.stage("candidates"):
        cands = await candidates.top_k(text, must_include=[active] if active else None)

    path = []
    decision: RouteDecision | None = None

    if llm.available("nvidia"):
        try:
            with sw.stage("router_fast"):
                decision = await llm_router.decide("nvidia", text, history, active, cands)
            path.append("fast")
        except Exception as e:  # быстрый путь не должен ронять разговор
            sw.note("router_fast_error", str(e)[:200])

    if (decision is None or _needs_escalation(decision)) and llm.available("openai"):
        with sw.stage("router_strong"):
            decision = await llm_router.decide("openai", text, history, active, cands)
        path.append("strong")

    if decision is None:
        return RouteDecision(action="handoff", reasoning="LLM недоступна — передаю оператору."), "error", cands

    if decision.action == "route" and decision.confidence < settings.clarify_threshold:
        decision.action = "clarify"
        decision.reasoning += f" (confidence {decision.confidence:.2f} ниже порога — переспрашиваем, а не угадываем)"
    return decision, "->".join(path), cands
