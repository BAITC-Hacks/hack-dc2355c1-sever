"""Репетиция проверки жюри: реплики из rehearsal_set.json через весь конвейер (роутер → политика → исполнитель).

    python -m scripts.rehearsal

Для каждой реплики: сценарий против ожидаемого, язык ответа, время до первого предложения ответа
(без TTS; с TTS добавляется ~0.4 с), вызванные действия и сам ответ.
"""

import asyncio
import json
import statistics
import time
from pathlib import Path

from app import backend
from app.orchestrator import Session
from app.tracing import Stopwatch

SET = Path(__file__).with_name("rehearsal_set.json")


async def run_item(item: dict) -> dict:
    session = Session(f"rehearsal-{item['id']}")
    for i, text in enumerate(item["turns"]):
        first: list[float] = []
        t0 = time.perf_counter()

        async def on_text(_: str) -> None:
            if not first:
                first.append((time.perf_counter() - t0) * 1000)

        sw = Stopwatch()
        trace = await session.handle_text(text, sw, on_text=on_text)
        trace = await session.finish(trace, sw)
        if not first:  # системная реплика без генерации — ответ готов сразу после роутера
            first.append(sw.stages.get("router_strong", 0) + sw.stages.get("router_fast", 0))
    d = trace.decision
    got = d.predicted_ids() if d.action != "continue" else [d.primary]
    want_lang = "kk" if item["lang"] == "kk" else None
    return {
        "id": item["id"], "kind": item["kind"], "expected": item["expected"], "got": got,
        "primary_ok": bool(got) and got[0] == item["expected"][0], "full_ok": set(got) == set(item["expected"]),
        "lang_ok": want_lang is None or d.reply_language == want_lang, "first_ms": first[0],
        "actions": [a["name"] + (":" + a["mode"] if a.get("mode") else "") for a in trace.actions],
        "reply": trace.bot_text, "parallel": "parallel_executor" in trace.stages_ms,
    }


async def main() -> None:
    backend.backend.reset()
    items = json.loads(SET.read_text(encoding="utf-8"))["items"]
    results = [await run_item(it) for it in items]
    for r in results:
        mark = "✓" if r["primary_ok"] else "✗"
        print(f"{mark} {r['id']} [{r['kind']}] expected={r['expected']} got={r['got']}"
              f"{'' if r['full_ok'] else ' (не все темы)'}{'' if r['lang_ok'] else ' (язык ответа!)'}")
        print(f"    {r['first_ms']:.0f} мс до ответа{' · параллельно' if r['parallel'] else ''} · действия: {', '.join(r['actions']) or '—'}")
        print(f"    {r['reply']}")
    n = len(results)
    print(f"\nОсновной сценарий: {sum(r['primary_ok'] for r in results)}/{n} · все темы: {sum(r['full_ok'] for r in results)}/{n}"
          f" · язык: {sum(r['lang_ok'] for r in results)}/{n}")
    print(f"До первого предложения: медиана {statistics.median(r['first_ms'] for r in results):.0f} мс (+~400 мс TTS до звука)")


if __name__ == "__main__":
    asyncio.run(main())
