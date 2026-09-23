"""Замеры по этапам, хранение трассировок в SQLite, трансляция в панель супервизора."""

import asyncio
import json
import sqlite3
import time
from contextlib import contextmanager

from fastapi import WebSocket

from .config import settings
from .schemas import Trace


class Stopwatch:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.stages: dict[str, float] = {}
        self.notes: dict[str, str] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round((time.perf_counter() - start) * 1000, 1)

    def note(self, key: str, value: str) -> None:
        self.notes[key] = value

    def total(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000, 1)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY, session_id TEXT, ts REAL, data TEXT)"
    )
    return conn


def save(trace: Trace) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO traces (session_id, ts, data) VALUES (?, ?, ?)",
            (trace.session_id, trace.ts, trace.model_dump_json()),
        )


def recent(limit: int = 200) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT data FROM traces ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def stats() -> dict:
    traces = recent(1000)
    n = len(traces) or 1
    actions = [t["decision"]["action"] for t in traces]
    router_ms = [t["stages_ms"].get("router_fast", 0) + t["stages_ms"].get("router_strong", 0) + t["stages_ms"].get("candidates", 0) for t in traces]
    by_scenario: dict[str, int] = {}
    for t in traces:
        sid = t["decision"].get("scenario_id") or t["decision"]["action"]
        by_scenario[sid] = by_scenario.get(sid, 0) + 1
    return {
        "turns": len(traces),
        "clarify_rate": actions.count("clarify") / n,
        "handoff_rate": actions.count("handoff") / n,
        "escalation_rate": sum("strong" in t["path"] and "fast" in t["path"] for t in traces) / n,
        "fast_only_rate": sum(t["path"] == "fast" for t in traces) / n,
        "router_ms_p50": _pct(router_ms, 0.5),
        "router_ms_p95": _pct(router_ms, 0.95),
        "low_confidence": sum(t["decision"]["confidence"] < settings.fast_confidence_threshold for t in traces),
        "by_scenario": dict(sorted(by_scenario.items(), key=lambda kv: -kv[1])),
    }


class SupervisorHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def publish(self, trace: Trace) -> None:
        payload = trace.model_dump_json()
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = SupervisorHub()


def record(trace: Trace) -> None:
    save(trace)
    asyncio.get_event_loop().create_task(hub.publish(trace))
