"""Текст ответа клиенту по решению роутера.

Сейчас — стартовые реплики сценариев из каталога (responses.*.opening), без генерации LLM.
Этап 6 плана: генерация, ограниченная сценарием, слотами, результатами действий и базой знаний.
"""

from .catalog import catalog
from .schemas import RouteDecision

HANDOFF = {
    "ru": "Соединяю со специалистом и передаю суть разговора — повторять не придётся.",
    "kk": "Маманға қосамын, әңгіменің мәнін жеткіземін — қайталаудың қажеті жоқ.",
}
CONTINUE = {"ru": "Принято.", "kk": "Қабылдадым."}
QUEUED = {
    "ru": " Про второй вопрос тоже помню — вернёмся к нему следом.",
    "kk": " Екінші сұрағыңыз да есімде — кейін оған ораламыз.",
}


def _system(sid: str, lang: str) -> str:
    return catalog.system_intents[sid]["response"][lang]


def _clarify(d: RouteDecision, lang: str) -> str:
    if d.clarify_question:
        return d.clarify_question
    opts = [catalog.title(a.scenario_id) for a in d.alternatives[:2]]
    if len(opts) == 2:
        return _system("SYS_UNCLEAR", lang).format(option_a=opts[0], option_b=opts[1])
    return "Уточните, пожалуйста, чем я могу помочь?" if lang == "ru" else "Нақтылаңызшы, немен көмектесе аламын?"


def build_reply(d: RouteDecision, queued: bool = False) -> str:
    lang = d.reply_language
    if d.action == "handoff":
        return HANDOFF[lang]
    if d.action == "clarify":
        return _clarify(d, lang)
    if d.action == "out_of_scope":
        return _system("SYS_OUT_OF_SCOPE", lang)
    if d.action == "goodbye":
        return _system("SYS_GOODBYE", lang)
    if d.action == "continue":
        return CONTINUE[lang]

    responses = catalog.scenarios[d.primary].get("responses", {})
    text = responses.get(lang, responses.get("ru", {})).get("opening") or CONTINUE[lang]
    return text + (QUEUED[lang] if queued else "")
