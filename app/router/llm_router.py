"""LLM-слой выбора сценария: каталог + состояние диалога → RouteDecision.

Каталог целиком лежит в system-промпте (статичный префикс → prompt caching у провайдера).
Если включено сужение кандидатов (TOP_K_CANDIDATES > 0), карточки кандидатов идут в user-часть.
"""

from functools import lru_cache

from ..catalog import catalog
from ..providers import llm
from ..schemas import RouteDecision, ScenarioHit, Turn

INSTRUCTIONS = """Ты — слой маршрутизации голосового робота контакт-центра страховой компании Saqta Insurance.
Клиент говорит по-русски, по-казахски или смешивает языки в одной фразе. Текст получен из распознавания речи и может содержать ошибки — понимай смысл, а не слова.
Сегодня {today}.

Задача: определить, какие сценарии нужны клиенту, опираясь на смысл и контекст диалога.
Правила:
1. Внимательно применяй правила «НЕ он, если … → другой сценарий». Одно слово («авария», «выплата») может означать разные сценарии.
2. Несколько просьб в одной реплике → несколько сценариев в scenarios, В ПОРЯДКЕ УПОМИНАНИЯ. Не добавляй сценарий, о котором клиент не просил.
3. Реплика не про услуги Saqta (кредиты, погода, работа, страхование жизни) → scenarios=[{{"scenario_id":"SYS_OUT_OF_SCOPE"}}].
4. Непонятно, чего хочет клиент (только тема без просьбы: «я по поводу страховки», «вопрос с машиной») → scenarios=[{{"scenario_id":"SYS_UNCLEAR"}}], а в alternatives — 2 наиболее вероятных сценария, clarify_question — один короткий вопрос с этими двумя вариантами на языке ответа.
5. Клиент прощается → SYS_GOODBYE.
6. Реплика — ответ на вопрос робота в активном сценарии (номер телефона, дата, «да/нет», адрес) → is_continuation=true, scenarios=[активный сценарий].
7. Клиент сменил тему → новая тема, is_continuation=false.
8. confidence — честная оценка 0..1. Сомневаешься между двумя — снижай confidence и укажи второй в alternatives. Не угадывай.
9. slots — значения из реплики, нормализованные: телефон +77XXXXXXXXX, даты YYYY-MM-DD относительно сегодняшней даты, числа цифрами.
10. language — язык реплики (ru|kk|mixed); reply_language — преобладающий язык клиента (ru|kk).

Верни только JSON:
{{"scenarios":[{{"scenario_id":"SC..","confidence":0.0,"reason":"коротко почему"}}],
 "alternatives":[{{"scenario_id":"SC..","confidence":0.0,"reason":"..."}}],
 "language":"ru","reply_language":"ru","slots":{{}},"is_continuation":false,
 "clarify_question":null,"reasoning":"1-2 предложения по-русски: логика выбора для супервизора"}}
alternatives — до 3 следующих по вероятности сценариев, не входящих в scenarios."""


@lru_cache(maxsize=1)
def _system_full() -> str:
    cards = "\n".join(catalog.card(sid) for sid in catalog.scenarios)
    return (
        INSTRUCTIONS.format(today=catalog.as_of_date)
        + f"\n\n## Каталог сценариев\n{cards}\n\n## Системные намерения\n{catalog.system_cards()}"
    )


def _system_short() -> str:
    return INSTRUCTIONS.format(today=catalog.as_of_date) + f"\n\n## Системные намерения\n{catalog.system_cards()}"


def build_user_prompt(text: str, history: list[Turn], active: str | None, candidates: list[str] | None) -> str:
    parts = []
    if candidates:
        parts.append("## Кандидаты\n" + "\n".join(catalog.card(sid) for sid in candidates))
    dialog = "\n".join(f"{'клиент' if t.role == 'user' else 'робот'}: {t.text}" for t in history)
    parts.append(f"## Диалог\n{dialog or '(начало разговора)'}")
    parts.append(f"## Активный сценарий\n{f'{active} — {catalog.title(active)}' if active else 'нет'}")
    parts.append(f"## Новая реплика клиента\n{text}")
    return "\n\n".join(parts)


def _clean(hits: list[ScenarioHit]) -> list[ScenarioHit]:
    seen, out = set(), []
    for h in hits:
        if catalog.known(h.scenario_id) and h.scenario_id not in seen:
            seen.add(h.scenario_id)
            out.append(h)
    return out


async def decide(
    provider: str, text: str, history: list[Turn], active: str | None, candidates: list[str] | None = None
) -> RouteDecision:
    system = _system_short() if candidates else _system_full()
    raw = await llm.chat_json(provider, system, build_user_prompt(text, history, active, candidates))
    d = RouteDecision.model_validate({k: v for k, v in raw.items() if k not in ("action", "policy_note")})
    unknown = [h.scenario_id for h in d.scenarios if not catalog.known(h.scenario_id)]
    if unknown:
        d.reasoning = f"Модель вернула неизвестные id {unknown} — отброшены. " + d.reasoning
    d.scenarios = _clean(d.scenarios)
    primary_ids = {h.scenario_id for h in d.scenarios}
    d.alternatives = [a for a in _clean(d.alternatives) if a.scenario_id not in primary_ids][:3]
    return d
