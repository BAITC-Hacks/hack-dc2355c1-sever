"""Агентный цикл: модель сама решает, какие инструменты вызвать.

Это то, что отличает "мы прикрутили GPT" от "наш агент делает работу".
Цикл: модель -> просит инструмент -> выполняем -> отдаём результат -> повтор.
"""

import json
import sys

import llm
import tools

SYSTEM_PROMPT = """Ты — агент-помощник. У тебя есть инструменты.
Правила:
- Нужны факты или расчёты — вызывай инструмент, не выдумывай.
- Задача из нескольких шагов — вызывай инструменты по очереди.
- Когда данных достаточно, дай короткий ответ по-русски."""

MAX_STEPS = 8


def run(task, system=SYSTEM_PROMPT, verbose=True, history=None):
    """Прогнать задачу через агента. Возвращает (ответ, лог шагов)."""
    messages = list(history) if history else [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": task})
    trace = []

    for step in range(MAX_STEPS):
        message = llm.chat(messages, tools=tools.SCHEMAS)
        messages.append(message.model_dump(exclude_none=True))

        calls = message.tool_calls or []
        if not calls:
            return message.content, trace

        for call in calls:
            name = call.function.name
            arguments = call.function.arguments
            result = tools.run(name, arguments)
            trace.append({"step": step + 1, "tool": name,
                          "args": arguments, "result": result})
            if verbose:
                print("  -> {}({}) = {}".format(name, arguments, result))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": result})

    return "Не уложился в {} шагов.".format(MAX_STEPS), trace


def main():
    if len(sys.argv) > 1:
        answer, _ = run(" ".join(sys.argv[1:]))
        print("\n" + answer)
        return

    print("Агент готов. Инструменты: {}".format(", ".join(tools.REGISTRY)))
    print("Пустая строка — выход.\n")
    while True:
        try:
            task = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not task:
            break
        answer, _ = run(task)
        print("Агент: {}\n".format(answer))
    print("\n" + llm.usage_report())


if __name__ == "__main__":
    main()
