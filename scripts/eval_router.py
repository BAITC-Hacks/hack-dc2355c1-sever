"""Прогон dev_utterances.json через наш роутер + эталонный evaluate.py из стартового кита.

    python -m scripts.eval_router                  # каскад, как в продукте
    python -m scripts.eval_router --mode strong    # только OpenAI
    python -m scripts.eval_router --mode fast      # только NVIDIA
    python -m scripts.eval_router --limit 20 -c 4

Каждая реплика прогоняется как первая в диалоге (без истории), через ту же политику,
что и в продукте: неуверенный ответ превращается в SYS_UNCLEAR.
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time

from app.config import ROOT, settings
from app import normalize
from app.backend import TODAY
from app.router import cascade, policy
from app.tracing import Stopwatch

DATA = settings.data_dir


async def run_one(u: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        sw = Stopwatch()
        try:
            raw, path, _, full = await cascade.raw_route(u["text"], [], None, sw, normalize.extract(u["text"], TODAY))
            decided_ms = sw.total()
            if full:
                await full
        except Exception as e:
            return {"id": u["id"], "pred": [], "raw": [], "path": "error", "ms": sw.total(), "error": str(e)[:200]}
        if raw is None:
            return {"id": u["id"], "pred": [], "raw": [], "path": "error", "ms": sw.total()}
        raw_ids = [s.scenario_id for s in raw.scenarios]
        d = policy.apply(raw.model_copy(deep=True), None, 0)
        return {
            "id": u["id"], "pred": d.predicted_ids(), "raw": raw_ids, "path": path, "ms": decided_ms, "full_ms": sw.total(),
            "conf": raw.confidence, "lang": raw.language, "reply_lang": raw.reply_language,
        }


def evaluate(preds: dict, name: str, utts: list[dict]) -> None:
    out = ROOT / ".cache" / f"predictions_{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(preds, ensure_ascii=False, indent=1), encoding="utf-8")
    dev = ROOT / ".cache" / "dev_subset.json"  # при --limit эталонный скрипт видит только прогнанные реплики
    dev.write_text(json.dumps({"utterances": utts}, ensure_ascii=False), encoding="utf-8")
    print(f"\n===== {name}: {out.relative_to(ROOT)} =====")
    subprocess.run([sys.executable, str(DATA / "evaluate.py"), str(out), str(dev)], check=False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cascade", "strong", "fast"], default="cascade")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-c", "--concurrency", type=int, default=8)
    args = ap.parse_args()

    if args.mode == "strong":
        settings.use_fast_path = False
    elif args.mode == "fast":
        settings.fast_confidence_threshold = 0.0  # никогда не эскалировать
        settings.openai_api_key = ""  # только NVIDIA

    utts = json.loads((DATA / "dev_utterances.json").read_text(encoding="utf-8"))["utterances"]
    if args.limit:
        utts = utts[: args.limit]

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    results = await asyncio.gather(*(run_one(u, sem) for u in utts))
    wall = time.perf_counter() - t0

    evaluate({r["id"]: r["raw"] for r in results}, f"{args.mode}_raw", utts)
    evaluate({r["id"]: r["pred"] for r in results}, f"{args.mode}_policy", utts)

    by_id = {u["id"]: u for u in utts}
    lat = [r["ms"] for r in results if r["path"] != "error"]
    paths: dict[str, int] = {}
    for r in results:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    lang_ok = sum(
        r.get("reply_lang") == ("kk" if by_id[r["id"]]["lang"] == "kk" else "ru")
        for r in results if by_id[r["id"]]["lang"] != "mixed"
    )
    n_lang = sum(by_id[r["id"]]["lang"] != "mixed" for r in results)

    print(f"\n===== latency / paths ({len(results)} реплик, {wall:.1f} с wall, concurrency {args.concurrency}) =====")
    if lat:
        lat.sort()
        print(f"router ms: p50={statistics.median(lat):.0f}  p95={lat[int(len(lat) * 0.95) - 1]:.0f}  max={lat[-1]:.0f}")
    print("paths:", paths)
    print(f"reply_language совпал с языком реплики (без mixed): {lang_ok}/{n_lang}")
    errors = [r for r in results if r.get("error")]
    for r in errors[:5]:
        print("ERROR", r["id"], r["error"])


if __name__ == "__main__":
    asyncio.run(main())
