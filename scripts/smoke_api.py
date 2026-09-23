"""Смоук-тест API против запущенного сервера.

    python -m scripts.smoke_api                          # http://localhost:8000
    python -m scripts.smoke_api https://<railway-домен>  # задеплоенная версия

Проверяет страницы, REST, WebSocket клиента (текст и аудио), WebSocket супервизора и граничные случаи.
Каталог сценариев не изменяет (PUT проверяется отправкой того же каталога).
"""

import asyncio
import json
import sys
import time

import httpx
import websockets

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
WS = BASE.replace("https://", "wss://").replace("http://", "ws://")
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"{'✓' if ok else '✗'} {name}{' — ' + detail if detail else ''}")


async def ws_turn(ws, payload) -> dict:
    """Одна реплика по /ws/session: собирает все сообщения до final."""
    t0 = time.perf_counter()
    out = {"types": [], "audio_bytes": 0, "first_audio_ms": None, "partials": [], "errors": []}
    await ws.send(payload)
    while True:
        m = await asyncio.wait_for(ws.recv(), timeout=60)
        if isinstance(m, bytes):
            out["audio_bytes"] += len(m)
            out["first_audio_ms"] = out["first_audio_ms"] or (time.perf_counter() - t0) * 1000
            continue
        m = json.loads(m)
        out["types"].append(m["type"])
        if m["type"] == "bot_partial":
            out["partials"].append(m["text"])
        if m["type"] == "transcript":
            out["transcript"] = m["text"]
        if m["type"] == "error":
            out["errors"].append(m["message"])
        if m["type"] == "trace":
            out["trace"] = m["trace"]
        if m["type"] == "final":
            out["final"] = m["trace"]
            return out
        if m["type"] == "error" and "transcript" not in out and "trace" not in out:
            return out  # ошибка STT — реплика завершена без ответа


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as http:
        # --- страницы и статика
        for path in ("/", "/supervisor", "/static/js/client.js", "/static/js/common.js", "/static/css/app.css"):
            r = await http.get(path)
            check(r.status_code == 200, f"GET {path}", str(r.status_code))

        # --- health
        r = await http.get("/api/health")
        h = r.json()
        check(r.status_code == 200 and h.get("scenarios") == 40 and h.get("openai"), "GET /api/health", json.dumps(h))

        # --- каталог
        r = await http.get("/api/scenarios")
        scenarios = r.json()
        check(r.status_code == 200 and len(scenarios) == 40 and scenarios[0].get("scenario_id") == "SC01",
              "GET /api/scenarios", f"{len(scenarios)} сценариев")
        r = await http.put("/api/scenarios", json=scenarios)
        check(r.status_code == 200 and r.json().get("scenarios") == 40, "PUT /api/scenarios (тот же каталог)", r.text[:80])
        r = await http.put("/api/scenarios", json={"not": "a list"})
        check(r.status_code == 422, "PUT /api/scenarios с неверным телом → 422", str(r.status_code))

        # --- текстовый канал
        t0 = time.perf_counter()
        r = await http.post("/api/chat", json={"text": "Где ваш офис в Астане?"})
        t = r.json()
        check(r.status_code == 200 and t["decision"]["scenarios"][0]["scenario_id"] == "SC33" and "Mangilik" in json.dumps(t["actions"]),
              "POST /api/chat: офис в Астане → SC33 + get_offices", f"{(time.perf_counter() - t0) * 1000:.0f} мс · {t['bot_text'][:70]}")
        sid = t["session_id"]
        for key in ("session_id", "turn", "user_text", "bot_text", "decision", "path", "stages_ms", "actions",
                    "active_scenario", "topic_queue", "client_id", "handoff_queue", "ts"):
            if key not in t:
                check(False, f"трассировка: поле {key}")
        check(all(k in t for k in ("decision", "stages_ms", "actions")), "трассировка: все поля контракта на месте")

        r = await http.post("/api/chat", json={"text": "Спасибо, до свидания", "session_id": sid})
        check(r.status_code == 200 and r.json()["decision"]["action"] == "goodbye" and r.json()["session_id"] == sid,
              "POST /api/chat: та же сессия, прощание → goodbye")
        r = await http.post("/api/chat", json={"text": "   "})
        check(r.status_code == 422, "POST /api/chat с пустым текстом → 422", str(r.status_code))
        r = await http.post("/api/chat", json={})
        check(r.status_code == 422, "POST /api/chat без text → 422", str(r.status_code))

        # --- резюме для оператора
        r = await http.get(f"/api/sessions/{sid}/handoff")
        check(r.status_code == 200 and len(r.json().get("transcript", [])) == 4, "GET /api/sessions/{id}/handoff", f"{len(r.json().get('transcript', []))} реплик")
        r = await http.get("/api/sessions/nope-404/handoff")
        check(r.status_code == 404, "GET /api/sessions/{неизвестный}/handoff → 404", str(r.status_code))

        # --- трассировки и статистика
        r = await http.get("/api/traces?limit=5")
        check(r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 2, "GET /api/traces", f"{len(r.json())} шт.")
        r = await http.get("/api/stats")
        st = r.json()
        check(r.status_code == 200 and st.get("turns", 0) >= 2 and "by_scenario" in st, "GET /api/stats",
              f"turns={st.get('turns')} router_p50={st.get('router_ms_p50')}")

    # --- WebSocket супервизора + клиента
    async with websockets.connect(f"{WS}/ws/supervisor") as sup, websockets.connect(f"{WS}/ws/session", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        check(hello.get("type") == "session" and hello.get("session_id"), "WS /ws/session: приветствие", json.dumps(hello))

        turn = await ws_turn(ws, json.dumps({"type": "text", "text": "Мне звонили от вашего имени и просили код из смс", "speak": True}))
        order_ok = turn["types"].index("trace") < turn["types"].index("final")
        check("final" in turn and turn["final"]["decision"]["scenarios"][0]["scenario_id"] == "SC38" and order_ok,
              "WS текст: мошенничество → SC38, trace раньше final")
        check(bool(turn["partials"]), "WS: bot_partial приходят по мере генерации", f"{len(turn['partials'])} предложений")
        if hello.get("tts") != "browser":
            check(turn["audio_bytes"] > 1000 and "tts_start" in turn["types"] and "tts_end" in turn["types"],
                  "WS: звук потоком (tts_start → mp3 → tts_end)",
                  f"{turn['audio_bytes']} байт, первый звук через {turn['first_audio_ms']:.0f} мс")
            check("end_to_audio" in turn["final"]["stages_ms"], "WS: end_to_audio в stages_ms",
                  f"{turn['final']['stages_ms'].get('end_to_audio')} мс")
        try:
            pushed = json.loads(await asyncio.wait_for(sup.recv(), timeout=10))
            check(pushed.get("user_text", "").startswith("Мне звонили"), "WS /ws/supervisor: трассировка пришла в реальном времени")
        except asyncio.TimeoutError:
            check(False, "WS /ws/supervisor: трассировка не пришла за 10 с")

        # пустой текст и мусор — сервер отвечает ошибкой, но соединение не закрывает
        await ws.send(json.dumps({"type": "text", "text": "   "}))
        await ws.send("не json")
        err = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        check(err.get("type") == "error" and "JSON" in err.get("message", ""), "WS: не-JSON → понятная ошибка", err.get("message", ""))
        turn = await ws_turn(ws, json.dumps({"type": "text", "text": "Можно у вас взять кредит?"}))
        check("final" in turn and turn["final"]["decision"]["action"] == "out_of_scope",
              "WS: после пустого текста и не-JSON соединение живо, вне тематики → out_of_scope")
        check(turn["audio_bytes"] == 0 and "tts_start" not in turn["types"] and turn["partials"],
              "WS: текстом спросили — ответ только текстом, без звука", f"{turn['audio_bytes']} байт звука")

        # аудио: синтезируем фразу через TTS сервера не можем — отправляем mp3 из предыдущего ответа
        audio = await _tts_sample()
        if audio:
            turn = await ws_turn(ws, audio)
            got = turn.get("transcript")
            check(got is not None or bool(turn["errors"]), "WS аудио: сервер распознал или вернул ошибку, не упал",
                  f"transcript={got!r} errors={turn['errors'][:1]}")
        else:
            check(True, "WS аудио: пропущено (TTS на сервере — browser)")

    failed = [r for r in results if not r[0]]
    print(f"\nИтог: {len(results) - len(failed)}/{len(results)} проверок прошли")
    if failed:
        sys.exit(1)


async def _tts_sample() -> bytes | None:
    """Короткая фраза голосом: берём звук ответа на «спасибо, до свидания» (ответ — готовый шаблон кита)."""
    async with websockets.connect(f"{WS}/ws/session", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        if hello.get("tts") == "browser":
            return None
        chunks = []
        await ws.send(json.dumps({"type": "text", "text": "Спасибо, до свидания", "speak": True}))
        while True:
            m = await asyncio.wait_for(ws.recv(), timeout=60)
            if isinstance(m, bytes):
                chunks.append(m)
            elif json.loads(m)["type"] == "final":
                return b"".join(chunks) or None


if __name__ == "__main__":
    asyncio.run(main())
