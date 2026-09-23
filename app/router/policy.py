"""Политика принятия решений поверх ответа LLM (пороги из README стартового кита).

confidence ≥ 0.75 → запуск сценария; 0.45–0.75 → SYS_UNCLEAR (один вопрос с двумя вариантами);
< 0.45 два раза подряд → оператор с контекстом. Несколько сценариев: сначала urgent, дальше по порядку упоминания.
"""

from ..catalog import catalog
from ..config import settings
from ..schemas import RouteDecision

SYSTEM_ACTIONS = {"SYS_OUT_OF_SCOPE": "out_of_scope", "SYS_GOODBYE": "goodbye", "SYS_UNCLEAR": "clarify"}


def apply(d: RouteDecision, active: str | None, low_streak: int) -> RouteDecision:
    """low_streak — сколько реплик подряд до этой роутер был неуверен (< clarify_threshold)."""
    if not d.scenarios:
        d.action, d.policy_note = "clarify", "LLM не вернула сценарий"
        return _maybe_handoff(d, low_streak)

    primary = d.primary
    if primary in SYSTEM_ACTIONS:
        d.action = SYSTEM_ACTIONS[primary]
        d.scenarios = d.scenarios[:1]
        d.policy_note = f"системное намерение {primary}"
        return d

    if d.is_continuation and active and primary == active:
        d.action, d.policy_note = "continue", "продолжение активного сценария, повторная маршрутизация не нужна"
        return d

    # Срочные сценарии вперёд, остальные — в порядке упоминания (sort стабильный).
    d.scenarios = [s for s in d.scenarios if s.scenario_id in catalog.scenarios]
    d.scenarios.sort(key=lambda s: catalog.priority(s.scenario_id) != "urgent")

    conf = d.confidence
    if conf >= settings.route_threshold:
        d.action, d.policy_note = "route", f"confidence {conf:.2f} ≥ {settings.route_threshold}"
    elif conf >= settings.clarify_threshold:
        d.action, d.policy_note = "clarify", f"confidence {conf:.2f} в зоне сомнения — переспрашиваем, а не угадываем"
        _alternatives_from_scenarios(d)
    else:
        d.action, d.policy_note = "clarify", f"confidence {conf:.2f} < {settings.clarify_threshold}"
        _alternatives_from_scenarios(d)
        d = _maybe_handoff(d, low_streak)
    return d


def _alternatives_from_scenarios(d: RouteDecision) -> None:
    """Для вопроса «вы хотите A или B?» нужны два лучших варианта."""
    ids = {a.scenario_id for a in d.alternatives}
    d.alternatives = [s for s in d.scenarios if s.scenario_id not in ids] + d.alternatives


def _maybe_handoff(d: RouteDecision, low_streak: int) -> RouteDecision:
    if low_streak >= 1:
        d.action = "handoff"
        d.policy_note += "; второй раз подряд — передаём оператору с контекстом"
    return d
