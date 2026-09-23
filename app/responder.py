"""Текст ответа клиенту по решению роутера.

Ответ собирается из шаблонов сценария — без генерации LLM, чтобы не тратить
задержку. Данные mock_backend/KB подключаются на этапе 6 плана.
"""

from .catalog import catalog
from .schemas import RouteDecision

GENERIC = {
    "ru": "Понял, вопрос по теме «{title}». Сейчас помогу.",
    "kk": "Түсіндім, «{title}» бойынша сұрақ. Қазір көмектесемін.",
}
CLARIFY = {
    "ru": "Уточните, пожалуйста, что именно вам нужно?",
    "kk": "Нақтылаңызшы, сізге не керек?",
}
HANDOFF = {
    "ru": "Соединяю вас с оператором и передаю суть разговора, повторять не придётся.",
    "kk": "Сізді операторға қосамын, әңгіменің мәнін жеткіземін.",
}
CONFIRM = {
    "ru": " Перед выполнением я попрошу вашего подтверждения.",
    "kk": " Орындамас бұрын растауыңызды сұраймын.",
}
QUEUED = {
    "ru": " Про «{title}» тоже помню — вернёмся к этому следом.",
    "kk": " «{title}» туралы да есімде — кейін оған ораламыз.",
}


def _lang(d: RouteDecision) -> str:
    return "kk" if d.language == "kk" else "ru"


def build_reply(d: RouteDecision, queued: str | None = None) -> str:
    lang = _lang(d)
    if d.action == "handoff":
        return HANDOFF[lang]
    if d.action == "clarify":
        return d.clarify_question or CLARIFY[lang]

    sc = catalog.scenarios[d.scenario_id]
    responses = sc.get("responses") or {}
    if isinstance(responses, dict):
        text = responses.get(lang) or responses.get("ru") or next(iter(responses.values()), None)
    elif isinstance(responses, list) and responses:
        text = str(responses[0])
    else:
        text = None
    text = text or GENERIC[lang].format(title=catalog.title(d.scenario_id))

    if catalog.is_irreversible(d.scenario_id):
        text += CONFIRM[lang]
    if queued:
        text += QUEUED[lang].format(title=catalog.title(queued))
    return text
