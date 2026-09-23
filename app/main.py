"""FastAPI: экран клиента, панель супервизора, WebSocket-сессии, REST для eval."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import tracing
from .catalog import catalog
from .config import settings
from .orchestrator import Session, finish
from .providers import llm, stt, tts
from .router import candidates
from .tracing import Stopwatch

STATIC = Path(__file__).resolve().parent.parent / "static"
sessions: dict[str, Session] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await candidates.warmup()
    yield


app = FastAPI(title="Voice Router", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def client_page():
    return FileResponse(STATIC / "index.html")


@app.get("/supervisor")
def supervisor_page():
    return FileResponse(STATIC / "supervisor.html")


@app.get("/api/health")
def health():
    return {
        "scenarios": len(catalog.scenarios),
        "openai": llm.available("openai"),
        "nvidia": llm.available("nvidia"),
        "elevenlabs": bool(settings.elevenlabs_api_key),
        "tts": tts.provider(),
    }


@app.get("/api/scenarios")
def list_scenarios():
    return list(catalog.scenarios.values())


@app.put("/api/scenarios")
def save_scenarios(scenarios: list[dict]):
    catalog.save(scenarios)
    return {"scenarios": len(catalog.scenarios)}


@app.get("/api/traces")
def traces(limit: int = 200):
    return tracing.recent(limit)


@app.get("/api/stats")
def stats():
    return tracing.stats()


class ChatIn(BaseModel):
    text: str
    session_id: str | None = None


@app.post("/api/chat")
async def chat(body: ChatIn):
    """Текстовый канал без голоса — для eval-скриптов и отладки."""
    session = sessions.get(body.session_id or "") or Session(body.session_id)
    sessions[session.id] = session
    sw = Stopwatch()
    trace = await session.handle_text(body.text, sw)
    return finish(trace, sw)


@app.get("/api/sessions/{session_id}/handoff")
def handoff(session_id: str):
    return sessions[session_id].handoff_summary()


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    """Протокол: JSON {"type":"text","text":...} или бинарное аудио одной реплики.
    Ответ: transcript → trace → tts_start → бинарные mp3-чанки → tts_end → timing."""
    await ws.accept()
    session = Session()
    sessions[session.id] = session
    await ws.send_json({"type": "session", "session_id": session.id, "tts": tts.provider()})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            sw = Stopwatch()
            if msg.get("bytes"):
                try:
                    with sw.stage("stt"):
                        text, provider = await stt.transcribe(msg["bytes"])
                except Exception as e:
                    await ws.send_json({"type": "error", "message": str(e)})
                    continue
                sw.note("stt_provider", provider)
                await ws.send_json({"type": "transcript", "text": text})
                if not text:
                    continue
            else:
                data = json.loads(msg.get("text") or "{}")
                text = (data.get("text") or "").strip()
                if not text:
                    continue

            trace = await session.handle_text(text, sw)
            await ws.send_json({"type": "trace", "trace": trace.model_dump()})

            stream = tts.synthesize(trace.bot_text)
            if stream is not None:
                await ws.send_json({"type": "tts_start"})
                first = True
                try:
                    async for chunk in stream:
                        if first:
                            sw.stages["tts_first_byte"] = round(sw.total() - sum(v for k, v in sw.stages.items()), 1)
                            sw.stages["end_to_audio"] = sw.total()
                            first = False
                        await ws.send_bytes(chunk)
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"TTS: {e}"})
                await ws.send_json({"type": "tts_end"})

            trace = finish(trace, sw)
            await ws.send_json({"type": "timing", "stages_ms": trace.stages_ms})
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/supervisor")
async def ws_supervisor(ws: WebSocket):
    await ws.accept()
    tracing.hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        tracing.hub.clients.discard(ws)
