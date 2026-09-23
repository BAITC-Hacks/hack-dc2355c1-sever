"""LLM-слой выбора сценария: промпт из каталога + контекст диалога → RouteDecision."""

import json

from ..catalog import catalog
from ..providers import llm
from ..schemas import RouteDecision, Turn

SYSTEM = """Ты — слой маршрутизации голосового робота контакт-центра страховой компании.
Клиент говорит на русском, казахском или смешивает их в одной фразе. Текст получен из распознавания речи и может содержать ошибки.

Твоя задача — выбрать ОДИН сценарий из списка кандидатов, опираясь на смысл и контекст диалога, а не на совпадение слов.
Правила:
- Учитывай границы сценариев (поле boundaries): запрос на стыке двух сценариев решай по тому, чего клиент хочет добиться.
- Если в реплике две темы — scenario_id = главная (срочная) тема, secondary_scenario_id = вторая.
- Если клиент сменил тему — выбирай новую тему, а не активный сценарий.
- Если реплика — ответ на вопрос робота (номер полиса, «да», адрес) — оставайся в активном сценарии.
- Если неясно, что нужно клиенту — action="clarify" и короткий уточняющий вопрос на языке клиента.
- Если клиент явно просит человека или ситуация вне каталога — action="handoff".
- confidence честно от 0 до 1. Не угадывай: при сомнении снижай confidence.
- Извлеки параметры из реплики в params (номер полиса, даты, суммы, адрес).

Верни только JSON:
{"action": "route|clarify|handoff", "scenario_id": "...", "confidence": 0.0,
 "reasoning": "1-2 предложения по-русски: почему этот сценарий",
 "alternatives": [{"scenario_id": "...", "confidence": 0.0, "why": "..."}],
 "params": {}, "secondary_scenario_id": null, "language": "ru|kk|mixed", "clarify_question": null}
alternatives — до 3 следующих по вероятности сценариев."""


def build_user_prompt(text: str, history: list[Turn], active: str | None, candidates: list[str]) -> str:
    cards = "\n".join(catalog.card(sid) for sid in candidates)
    dialog = "\n".join(f"{t.role}: {t.text}" + (f"  [{t.scenario_id}]" if t.scenario_id else "") for t in history)
    return (
        f"## Кандидаты\n{cards}\n\n"
        f"## Диалог (последние реплики)\n{dialog or '(начало разговора)'}\n\n"
        f"## Активный сценарий\n{active or 'нет'}\n\n"
        f"## Новая реплика клиента\n{text}"
    )


async def decide(provider: str, text: str, history: list[Turn], active: str | None, candidates: list[str]) -> RouteDecision:
    raw = await llm.chat_json(provider, SYSTEM, build_user_prompt(text, history, active, candidates))
    decision = RouteDecision.model_validate(raw)
    if decision.action == "route" and decision.scenario_id not in catalog.scenarios:
        # Модель вернула несуществующий id — не угадываем, а переспрашиваем.
        decision.reasoning = f"Модель вернула неизвестный сценарий {json.dumps(decision.scenario_id)}. " + decision.reasoning
        decision.action, decision.confidence = "clarify", 0.0
    decision.alternatives = [a for a in decision.alternatives if a.scenario_id in catalog.scenarios][:3]
    if decision.secondary_scenario_id not in catalog.scenarios:
        decision.secondary_scenario_id = None
    return decision
