"""Проверка боем: ключ жив, кредиты есть, модель отвечает.

Запустите СРАЗУ как получите ключ. Лучше узнать о проблеме за 10 секунд,
чем на третьем часу хакатона.
"""

import time

import llm


def main():
    print("1. Ключ подхватился:", "да" if llm.os.environ.get("OPENAI_API_KEY") else "НЕТ")

    print("\n2. Доступные модели:")
    try:
        models = sorted(m.id for m in llm.client().models.list())
        for name in models:
            print("   ", name)
        print("   (всего {})".format(len(models)))
    except Exception as error:
        print("   не удалось получить список:", error)
        models = []

    if llm.MODEL not in models and models:
        print("\n   ВНИМАНИЕ: MODEL={} нет в списке. Впишите в .env одну из тех,"
              " что выше.".format(llm.MODEL))

    print("\n3. Тестовый вызов ({})...".format(llm.MODEL))
    started = time.time()
    answer = llm.ask("Ответь одним словом: работает?", use_cache=False)
    print("   ответ: {}".format(answer))
    print("   задержка: {:.1f}с".format(time.time() - started))

    print("\n4. Агент с инструментом:")
    import agent
    result, trace = agent.run("Посчитай 1250 * 0.12 и скажи, который час.")
    print("   ответ: {}".format(result))
    print("   вызовов инструментов: {}".format(len(trace)))

    print("\n5. Расход:\n" + llm.usage_report())
    print("\nВсё готово. Можно работать.")


if __name__ == "__main__":
    main()
