"""Проигрывает реплики клиента из dialogs_sample.json через полный конвейер (роутер → политика → исполнитель).

    python -m scripts.run_dialogs            # все 10 диалогов
    python -m scripts.run_dialogs D02 D07    # выбранные

Сравнивает сценарии каждой реплики с разметкой и печатает, какие действия вызвал бот
рядом с эталонными. Ответы бота не обязаны совпадать с эталоном дословно.
"""

import asyncio
import json
import sys

from app import backend
from app.config import settings
from app.orchestrator import Session
from app.tracing import Stopwatch


def _fmt_actions(items: list[dict]) -> str:
    return ", ".join(f"{a['name']}{':' + a['mode'] if a.get('mode') else ''}" for a in items) or "—"


async def run_dialog(dlg: dict) -> tuple[int, int]:
    backend.backend.reset()
    session = Session(f"demo-{dlg['dialog_id']}")
    turns = dlg["turns"]
    hit = total = 0
    print(f"\n### {dlg['dialog_id']} {dlg['title']}  {dlg['tags']}")
    for i, turn in enumerate(turns):
        if "scenarios" not in turn:
            continue
        sw = Stopwatch()
        trace = await session.handle_text(turn["text"], sw)
        trace = await session.finish(trace, sw)
        got = trace.decision.predicted_ids() if trace.decision.action != "continue" else [trace.decision.primary]
        exp = turn["scenarios"]
        ok = bool(got) and got[0] == exp[0]
        hit, total = hit + ok, total + 1
        ref = turns[i + 1] if i + 1 < len(turns) and "scenarios" not in turns[i + 1] else {}
        print(f"  C: {turn['text']}")
        print(f"     {'✓' if ok else '✗'} expected={exp} got={got} ({trace.decision.action}, {trace.path})  "
              f"router={trace.stages_ms.get('router_strong', trace.stages_ms.get('router_fast', 0)):.0f}мс "
              f"ответ={trace.stages_ms.get('response', 0):.0f}мс")
        print(f"  B: {trace.bot_text}")
        print(f"     действия: {_fmt_actions(trace.actions)}   | эталон: {_fmt_actions(ref.get('actions', []))}")
        for a in trace.actions:
            if a.get("guard") or a.get("blocked") or "error" in (a.get("result") or {}):
                print(f"     ! {a['name']}: {a.get('guard') or a.get('result')}")
    return hit, total


async def main() -> None:
    data = json.loads((settings.data_dir / "dialogs_sample.json").read_text(encoding="utf-8"))
    dialogs = data["dialogs"] if isinstance(data, dict) else data
    wanted = set(sys.argv[1:])
    hit = total = 0
    for dlg in dialogs:
        if wanted and dlg["dialog_id"] not in wanted:
            continue
        h, t = await run_dialog(dlg)
        hit, total = hit + h, total + t
    print(f"\nОсновной сценарий по репликам: {hit}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
