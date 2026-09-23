"""LLM-слой выбора сценария: каталог + состояние диалога → RouteDecision.

Каталог целиком лежит в system-промпте (статичный префикс → prompt caching у провайдера).
Если включено сужение кандидатов (TOP_K_CANDIDATES > 0), карточки кандидатов идут в user-часть.
"""

import asyncio
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
2. Несколько просьб в одной реплике → несколько сценариев в s, В ПОРЯДКЕ УПОМИНАНИЯ. Не добавляй сценарий, о котором клиент не просил, но и не теряй вторую просьбу (жалоба, вопрос об оплате, документах и т.п.).
3. Реплика не про услуги Saqta (кредиты, погода, работа, страхование жизни) → s=[["SYS_OUT_OF_SCOPE",1.0]].
4. Непонятно, чего хочет клиент (только тема или вступление без просьбы: «я по поводу страховки», «хотел кое-что спросить») → s=[["SYS_UNCLEAR",1.0]], в alt — 2 наиболее вероятных сценария, clarify — один короткий вопрос с этими двумя вариантами на языке ответа.
5. Клиент прощается или просто благодарит без новой просьбы («спасибо», «отлично, спасибо», «рақмет», «жоқ, рақмет», «больше ничего») → SYS_GOODBYE, даже если есть активный сценарий.
6. Реплика — ответ на вопрос робота в активном сценарии (номер телефона, дата, «да/нет», адрес) → cont=true, s=[[активный сценарий, confidence]].
7. Клиент сменил тему → новая тема, cont=false. Если в реплике есть и ответ на вопрос робота, и новая просьба — s содержит только новую просьбу.
8. Робот предложил другую услугу («проверю ваш полис?»), клиент согласился («да, проверьте») → это сценарий предложенной услуги, cont=false.
9. Не включай активный сценарий в s, если клиент в этой реплике о нём не спрашивает.
10. confidence — честная оценка 0..1. Сомневаешься между двумя — снижай confidence и укажи второй в alt. Не угадывай.
11. slots — ВСЕ значения, которые можно вывести из реплики, под именами слотов из карточки сценария (* — обязательный): включая описательные (incident_description, cancel_reason, complaint_text, fraud_details — коротко своими словами), относительные даты («вчера», «три дня назад», «үш күн бұрын» → YYYY-MM-DD от сегодняшней даты), город/регион, тип авто. Телефон +77XXXXXXXXX, числа цифрами.
12. lang — язык реплики (ru|kk|mixed); reply — язык ответа: язык, на котором клиент говорит больше; если клиент говорит по-казахски (даже с русскими терминами вроде ОГПО, КАСКО) — kk.

Верни только JSON строго в этом порядке ключей (решение первым, обоснование последним):
{{"lang":"ru","reply":"ru","s":[["SC..",0.9]],"alt":[["SC..",0.3]],"cont":false,"slots":{{}},"clarify":null,"why":"1-2 предложения по-русски: логика выбора для супервизора"}}
s — сценарии [id, confidence] в порядке упоминания; alt — до 3 следующих по вероятности сценариев, не входящих в s."""


@lru_cache(maxsize=1)
def _system_full() -> str:
    cards = "\n".join(catalog.card(sid) for sid in catalog.scenarios)
    return (
        INSTRUCTIONS.format(today=catalog.as_of_date)
        + f"\n\n## Каталог сценариев\n{cards}\n\n## Системные намерения\n{catalog.system_cards()}"
    )


def _system_short() -> str:
    return INSTRUCTIONS.format(today=catalog.as_of_date) + f"\n\n## Системные намерения\n{catalog.system_cards()}"


def build_user_prompt(
    text: str, history: list[Turn], active: str | None, candidates: list[str] | None, triage: dict | None = None
) -> str:
    parts = []
    if candidates:
        parts.append("## Кандидаты\n" + "\n".join(catalog.card(sid) for sid in candidates))
    dialog = "\n".join(f"{'клиент' if t.role == 'user' else 'робот'}: {t.text}" for t in history)
    parts.append(f"## Диалог\n{dialog or '(начало разговора)'}")
    parts.append(f"## Активный сценарий\n{f'{active} — {catalog.title(active)}' if active else 'нет'}")
    parts.append(f"## Новая реплика клиента\n{text}")
    if triage and (triage.get("ids") or triage.get("text") != text):
        parts.append(f"## Нормализация чисел (кодом, надёжнее твоей)\n{triage['text']}\nидентификаторы: {triage.get('ids') or 'нет'}")
    return "\n\n".join(parts)


def _clean(hits: list[ScenarioHit]) -> list[ScenarioHit]:
    seen, out = set(), []
    for h in hits:
        if catalog.known(h.scenario_id) and h.scenario_id not in seen:
            seen.add(h.scenario_id)
            out.append(h)
    return out


def _hits(pairs) -> list[ScenarioHit]:
    out = []
    for p in pairs or []:
        if isinstance(p, (list, tuple)) and p:
            out.append(ScenarioHit(scenario_id=str(p[0]), confidence=float(p[1]) if len(p) > 1 else 0.0))
        elif isinstance(p, dict) and p.get("scenario_id"):
            out.append(ScenarioHit.model_validate(p))
        elif isinstance(p, str):
            out.append(ScenarioHit(scenario_id=p))
    return out


def parse(raw: dict) -> RouteDecision:
    lang = raw.get("lang") if raw.get("lang") in ("ru", "kk", "mixed") else "ru"
    reply = raw.get("reply") if raw.get("reply") in ("ru", "kk") else ("kk" if lang == "kk" else "ru")
    d = RouteDecision(
        scenarios=_hits(raw.get("s")),
        alternatives=_hits(raw.get("alt")),
        language=lang,
        reply_language=reply,
        slots=raw.get("slots") or {},
        is_continuation=bool(raw.get("cont")),
        clarify_question=raw.get("clarify") or None,
        reasoning=raw.get("why") or "",
    )
    unknown = [h.scenario_id for h in d.scenarios if not catalog.known(h.scenario_id)]
    if unknown:
        d.policy_note = f"модель вернула неизвестные id {unknown} — отброшены"
    d.scenarios = _clean(d.scenarios)
    primary_ids = {h.scenario_id for h in d.scenarios}
    d.alternatives = [a for a in _clean(d.alternatives) if a.scenario_id not in primary_ids][:3]
    return d


async def decide(
    provider: str, text: str, history: list[Turn], active: str | None, candidates: list[str] | None = None,
    triage: dict | None = None,
) -> tuple[RouteDecision, "asyncio.Task[dict]"]:
    """Возвращает решение сразу после того, как модель его выдала (поток),
    и задачу с полным JSON — обоснование догенерируется параллельно с ответом клиенту."""
    system = _system_short() if candidates else _system_full()
    head, full = await llm.chat_json_stream(
        provider, system, build_user_prompt(text, history, active, candidates, triage), split_key='"why"'
    )
    return parse(head), full
