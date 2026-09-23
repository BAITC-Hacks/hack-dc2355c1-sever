"""Исполнитель сценария: LLM с вызовом инструментов (действия из actions.json) → ответ клиенту.

Роутер уже выбрал сценарий; исполнитель доводит его до конца: идентифицирует клиента,
спрашивает недостающие слоты по одному, вызывает действия, отвечает по данным.

Гарантии в коде, а не в промпте:
- доступны только действия активного сценария (+ служебные);
- необратимое действие можно выполнить (execute) только после preview на прошлой реплике —
  иначе вызов принудительно превращается в preview;
- суммы/номера считает backend, LLM их только озвучивает.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import backend
from .catalog import catalog
from .config import settings
from .providers import llm

SERVICE_ACTIONS = ["find_client", "get_policies", "kb_lookup", "transfer_to_operator", "send_sms"]
MAX_ROUNDS = 5

RULES = """Ты — голосовой оператор контакт-центра страховой компании Saqta Insurance. Сегодня {today}.
Ты ведёшь сценарий, который уже выбран. Отвечай на языке: {lang_name}.

Правила общения:
- Строго 1–2 коротких предложения (до 35 слов) на весь ответ. Только один вопрос за раз. Это голос — никаких списков, переносов строк, markdown и эмодзи.
- Сначала покажи понимание, затем действуй. В страховых случаях и жалобах — эмпатия; в срочных — спокойно и быстро, сначала безопасность.
- Числа и суммы произноси словами («тридцать восемь тысяч тенге», «отыз сегіз мың теңге»), даты — словами («четырнадцатого февраля»).
- При повторе персональных данных маскируй их: почта r***@mail.example, телефон +7 7** *** ** 07.
- Говори только факты из результатов действий и базы знаний. Нет данных — так и скажи и предложи оператора. Никогда не придумывай суммы, номера, адреса, сроки.
- На вопрос «Вы робот?» отвечай честно.

Как вести сценарий:
- Если сценарий требует идентификации, а клиент не найден — спроси телефон (или ИИН/номер полиса) и вызови find_client.
- Клиент идентифицирован (в том числе только что, в этой реплике) → сразу, в этом же ответе, находи его данные: get_policies(client_id), get_claim(client_id=...), check_payment(client_id) и т.п. НЕ спрашивай номер полиса или заявления, если его можно найти. Если полис по теме один — бери его.
- Город, почту, телефон бери из профиля клиента, если клиент не назвал другие — не спрашивай.
- Даты из «relative_dates» (посчитаны кодом от сегодняшней даты) используй как есть и называй именно их; сам даты не вычисляй.
- Сначала используй всё, что уже известно или выводится из разговора: «три дня назад», «үш күн бұрын» → дата относительно сегодня; «легковая» → vehicle_type=car; «в Алматы» → region=almaty; госномер 01/02 → регион. Спрашивай только то, чего действительно нет.
- Недостающие обязательные слоты спрашивай по одному (один вопрос в реплике), формулировками из подсказок ниже.
- Необратимые действия: когда все данные собраны — В ЭТОЙ ЖЕ реплике вызови действие с mode="preview", озвучь результат preview (суммы, номера, даты) и попроси явное «да». Никогда не проси подтверждение без preview.
- mode="execute" — только если клиент на этой реплике явно подтвердил («да», «иә», «растаймын», «оформляйте»). Если клиент отказался — ничего не выполняй.
- Ошибки действий: not_found/invalid_input — переспроси один раз, затем предложи другой идентификатор или оператора; policy_inactive/not_eligible/not_covered — объясни причину одной фразой и предложи ближайший вариант; service_unavailable — передай оператору.
- Пока идут действия, клиент уже слышит «Сейчас проверю» — не начинай итоговый ответ с этой фразы.
- Когда вопрос клиента по сценарию полностью решён — вызови complete_scenario.
- Если сценарий предусматривает передачу оператору (handoff) или ты не справляешься — вызови transfer_to_operator с нужной очередью и кратким резюме, и скажи клиенту, что специалист уже видит суть вопроса."""


@dataclass
class ExecResult:
    reply: str
    actions: list[dict] = field(default_factory=list)
    completed: bool = False
    handoff_queue: str | None = None
    client: dict | None = None
    previews: dict[str, dict] = field(default_factory=dict)  # действие → аргументы озвученного preview


def _action_meta(name: str) -> dict:
    return next((a for a in catalog.actions.get("actions", []) if a["name"] == name), {"name": name, "inputs": []})


def _kb_topics() -> str:
    kb = catalog.knowledge_base
    paths = []
    for k, v in kb.items():
        if k == "meta":
            continue
        paths.append(k)
        if isinstance(v, dict):
            paths += [f"{k}.{sub}" for sub in v]
    return ", ".join(paths)


def _tool(name: str) -> dict:
    meta = _action_meta(name)
    props: dict[str, Any] = {}
    for inp in meta.get("inputs", []):
        for part in inp.split("|"):
            slot = catalog.slots.get(part, {})
            props[part] = {"description": slot.get("description", part)}
            if slot.get("type") == "list" or part.endswith("_iin"):
                props[part]["type"] = "array"
                props[part]["items"] = {"type": "string"}
    if meta.get("irreversible"):
        props["mode"] = {"type": "string", "enum": ["preview", "execute"], "description": "preview — показать клиенту; execute — только после явного «да»"}
    desc = meta.get("description", name) + (" НЕОБРАТИМОЕ действие." if meta.get("irreversible") else "")
    outputs = meta.get("outputs")
    if outputs:
        desc += f" Возвращает: {', '.join(outputs)}."
    if name == "kb_lookup":
        desc += f" topic — путь в базе знаний, например payments.installments. Доступно: {_kb_topics()}"
    return {"type": "function", "function": {"name": name, "description": desc,
                                              "parameters": {"type": "object", "properties": props, "additionalProperties": True}}}


COMPLETE_TOOL = {"type": "function", "function": {
    "name": "complete_scenario", "description": "Вопрос клиента по текущему сценарию полностью решён.",
    "parameters": {"type": "object", "properties": {}}}}


def _slot_prompts(sc: dict, lang: str) -> str:
    lines = []
    for kind in ("required", "optional"):
        for name in sc.get("slots", {}).get(kind, []):
            slot = catalog.slots.get(name, {})
            prompt = slot.get("prompt", {}).get(lang, "")
            extra = f" формат {slot['pattern']}" if slot.get("pattern") else (f" значения {slot['values']}" if slot.get("values") else "")
            lines.append(f"- {name}{'*' if kind == 'required' else ''} ({slot.get('type', 'string')}{extra}): «{prompt}»")
    return "\n".join(lines)


def _system(sid: str, lang: str, client: dict | None, slots: dict, queue: list[str], previews: dict[str, dict], turn_slots: dict) -> str:
    sc = catalog.scenarios[sid]
    card = {k: sc.get(k) for k in ("scenario_id", "name", "description", "priority", "requires_identification",
                                    "actions", "requires_confirmation", "handoff")}
    style = sc.get("responses", {}).get(lang, {})
    parts = [
        RULES.format(today=catalog.as_of_date, lang_name="казахский" if lang == "kk" else "русский"),
        f"## Текущий сценарий\n{json.dumps(card, ensure_ascii=False)}",
        f"## Слоты (* — обязательный) и как о них спрашивать\n{_slot_prompts(sc, lang) or 'нет'}",
        f"## Стиль реплик сценария (образец, не скрипт)\n{json.dumps(style, ensure_ascii=False)}",
        f"## Клиент\n{json.dumps(client, ensure_ascii=False) if client else 'не идентифицирован'}",
        f"## Уже известные значения слотов (нормализованы, используй КАК ЕСТЬ, не переспрашивай и не переписывай)\n"
        f"{json.dumps(slots, ensure_ascii=False) if slots else 'нет'}",
        f"## Извлечено из текущей реплики клиента\n{json.dumps(turn_slots, ensure_ascii=False) if turn_slots else 'ничего'}",
    ]
    if previews:
        parts.append("## Ожидают подтверждения клиента (preview уже озвучен)\n"
                     + json.dumps(previews, ensure_ascii=False) + "\nЕсли клиент подтвердил — вызови это действие с mode=\"execute\".")
    if queue:
        names = ", ".join(f"{q} ({catalog.title(q)})" for q in queue)
        parts.append(f"## Отложенные темы клиента\n{names}\nКогда текущий вопрос решён — одной фразой предложи перейти к первой из них.")
    return "\n\n".join(parts)


# Пауза дольше секунды в голосе читается как сбой связи: пока выполняются действия, клиент слышит это.
FILLER = {"ru": "Сейчас проверю.", "kk": "Қазір тексеремін."}
SENTENCE_END = re.compile(r"(.+?[.!?…])(?:\s+|$)", re.S)
OnText = Callable[[str], Awaitable[None]] | None


async def _stream_round(messages: list[dict], tools: list[dict], on_text: OnText) -> tuple[str, list[dict]]:
    """Один вызов модели потоком: текст отдаём в on_text по предложениям (→ TTS сразу),
    вызовы инструментов собираем из дельт."""
    stream = await llm._client("openai").chat.completions.create(
        model=settings.executor_model, messages=messages, tools=tools, stream=True
    )
    content, pending = "", ""
    calls: dict[int, dict] = {}
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        for tc in delta.tool_calls or []:
            slot = calls.setdefault(tc.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            slot["id"] = tc.id or slot["id"]
            if tc.function and tc.function.name:
                slot["function"]["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                slot["function"]["arguments"] += tc.function.arguments
        if delta.content:
            content += delta.content
            pending += delta.content
            while on_text and (m := SENTENCE_END.match(pending)):
                await on_text(m.group(1).strip())
                pending = pending[m.end():]
    if on_text and pending.strip():
        await on_text(pending.strip())
    return content.strip(), [calls[i] for i in sorted(calls)]


async def run(
    sid: str, lang: str, user_text: str, history: list[dict], client: dict | None,
    slots: dict, queue: list[str], previews: dict[str, dict], turn_slots: dict | None = None,
    on_text: OnText = None, extra: list[str] | None = None, gate: "asyncio.Future[bool] | None" = None,
) -> ExecResult:
    """on_text получает готовые предложения ответа по мере генерации — их сразу озвучивает TTS.
    extra — вторые темы этой же реплики: их действия тоже доступны, ответ покрывает и их.
    gate — при параллельном запуске с роутером: действия, меняющие данные, ждут его подтверждения."""
    extra = [e for e in extra or [] if e in catalog.scenarios and e != sid]
    names = list(dict.fromkeys(
        [a for x in [sid, *extra] for a in catalog.scenarios[x].get("actions", [])] + SERVICE_ACTIONS))
    tools = [_tool(n) for n in names] + [COMPLETE_TOOL]
    system = _system(sid, lang, client, slots, queue, previews, turn_slots or {})
    if extra:
        system += "\n\n## В этой же реплике клиент спросил ещё о\n" + ", ".join(
            f"{e} ({catalog.title(e)})" for e in extra) + "\nОтветь и на это одной фразой, если хватает данных; иначе скажи, что вернёшься к этому."
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    result = ExecResult(reply="", client=client)
    new_previews: dict[str, dict] = {}
    spoken: list[str] = []

    for round_no in range(MAX_ROUNDS):
        content, calls = await _stream_round(messages, tools, on_text)
        if content:
            spoken.append(content)
        if not calls:
            break
        if round_no == 0 and not content and on_text and any(c["function"]["name"] != "complete_scenario" for c in calls):
            await on_text(FILLER[lang])
            spoken.append(FILLER[lang])
        messages.append({"role": "assistant", "content": content or None, "tool_calls": calls})
        for tc in calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if gate is not None and name not in backend.READ_ONLY and not (await gate):
                raise asyncio.CancelledError  # роутер решил иначе — ничего не меняем
            out = _execute(name, args, names, previews, new_previews, result)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(out, ensure_ascii=False, default=str)})
        if any(x != FILLER[lang] for x in spoken) and all(c["function"]["name"] == "complete_scenario" for c in calls):
            break  # ответ по существу уже прозвучал (заполнитель не в счёт), сценарий закрыт — лишний раунд не нужен
    else:
        fallback = "Минуту, передаю вопрос специалисту." if lang == "ru" else "Бір минут, сұрағыңызды маманға беремін."
        spoken.append(fallback)
        if on_text:
            await on_text(fallback)
        result.handoff_queue = "operator_general"

    result.reply = " ".join(spoken).strip()
    result.previews = new_previews
    return result


def _execute(name: str, args: dict, allowed: list[str], previews: dict[str, dict], new_previews: dict[str, dict], result: ExecResult) -> dict:
    if name == "complete_scenario":
        result.completed = True
        result.actions.append({"name": name})
        return {"ok": True}
    if name not in allowed:
        out = backend.Backend.err("invalid_input", f"Action {name} is not available in this scenario")
        result.actions.append({"name": name, "args": args, "result": out, "blocked": True})
        return out

    mode = args.pop("mode", "execute")
    note = None
    if name in backend.IRREVERSIBLE:
        if mode != "preview" and name not in previews:
            mode, note = "preview", "execute без предварительного preview заблокирован — выполнен preview"
        if mode == "preview":
            new_previews[name] = dict(args)
        else:
            # Выполняем ровно то, что клиент услышал и подтвердил: аргументы preview важнее новых.
            args = {**args, **previews[name]}
    else:
        mode = None

    out = backend.call(name, args, mode or "execute")
    if name == "find_client" and "error" not in out:
        result.client = out
    if name == "transfer_to_operator":
        result.handoff_queue = out.get("queue")
    entry = {"name": name, "args": args, "result": out}
    if mode:
        entry["mode"] = mode
    if note:
        entry["guard"] = note
        if "error" not in out:
            # Для модели это ошибка: иначе она иногда говорит клиенту «оформлено», хотя выполнен только preview.
            out = {"error": {"code": "confirmation_required",
                             "message": "Действие НЕ выполнено. Сначала озвучь клиенту эти данные и получи явное «да»."},
                   "preview": out}
            result.actions.append(entry)
            return out
    if mode == "preview" and "error" not in out:
        out = {**out, "status": "PREVIEW_NOT_EXECUTED",
               "note": "Действие ещё НЕ выполнено. Озвучь эти данные и попроси явное «да». Не говори «готово/оформлено»."}
    result.actions.append(entry)
    return out
