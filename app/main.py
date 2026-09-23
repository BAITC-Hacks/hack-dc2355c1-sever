"""FastAPI: экран клиента, панель супервизора, WebSocket-сессии, REST для eval."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import tracing
from .catalog import catalog
from .config import settings
from .orchestrator import Session
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
    page = STATIC / "ui" / "index.html"
    return FileResponse(page if page.exists() else STATIC / "index.html")


@app.get("/supervisor")
def supervisor_page():
    page = STATIC / "ui" / "index.html"
    return FileResponse(page if page.exists() else STATIC / "supervisor.html")


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
    text: str = Field(min_length=1, pattern=r"\S")
    session_id: str | None = None


@app.post("/api/chat")
async def chat(body: ChatIn):
    """Текстовый канал без голоса — для eval-скриптов и отладки."""
    session = sessions.get(body.session_id or "") or Session(body.session_id)
    sessions[session.id] = session
    sw = Stopwatch()
    trace = await session.handle_text(body.text, sw)
    return await session.finish(trace, sw)


@app.get("/api/sessions/{session_id}/handoff")
def handoff(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, f"Сессия {session_id} не найдена")
    return sessions[session_id].handoff_summary()


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    """Протокол: JSON {"type":"text","text":...} или бинарное аудио одной реплики.
    Ответ: transcript → bot_partial (предложения по мере генерации) → tts_start → mp3-чанки → trace → tts_end → final."""
    await ws.accept()
    session = Session()
    sessions[session.id] = session
    await ws.send_json({"type": "session", "session_id": session.id, "tts": tts.provider()})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            try:
                await _session_turn(ws, session, msg)
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception as e:  # сбой одной реплики (API недоступен и т.п.) не должен рвать разговор
                await ws.send_json({"type": "error", "message": f"Не удалось обработать реплику: {e}"})
    except WebSocketDisconnect:
        pass


async def _session_turn(ws: WebSocket, session: Session, msg: dict) -> None:
    """Одна реплика клиента: STT (если аудио) → роутер → исполнитель → озвучка → трассировка."""
    sw = Stopwatch()
    if msg.get("bytes"):
        try:
            with sw.stage("stt"):
                text, provider = await stt.transcribe(msg["bytes"])
        except Exception as e:
            await ws.send_json({"type": "error", "message": str(e)})
            return
        sw.note("stt_provider", provider)
        await ws.send_json({"type": "transcript", "text": text})
        if not text:
            return
    else:
        try:
            data = json.loads(msg.get("text") or "{}")
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": 'Ожидается JSON {"type":"text","text":"..."} или бинарное аудио'})
            return
        text = (data.get("text") or "").strip() if isinstance(data, dict) else ""
        if not text:
            return

    speaker = _Speaker(ws, sw)
    trace = await session.handle_text(text, sw, on_text=speaker.say)
    if not speaker.used:  # системная реплика без генерации — озвучиваем целиком (до trace: клиент рисует один пузырь)
        await speaker.say(trace.bot_text)
    await ws.send_json({"type": "trace", "trace": trace.model_dump()})
    await speaker.close()

    trace = await session.finish(trace, sw)
    await ws.send_json({"type": "final", "trace": trace.model_dump()})


class _Speaker:
    """Конвейер озвучки: предложения ответа ставятся в очередь по мере генерации,
    отдельная задача синтезирует их по порядку и сразу шлёт mp3-чанки клиенту."""

    def __init__(self, ws: WebSocket, sw: Stopwatch) -> None:
        self.ws, self.sw = ws, sw
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.used = False
        self.task: asyncio.Task | None = None

    async def say(self, sentence: str) -> None:
        if not sentence:
            return
        self.used = True
        if self.task is None:
            self.task = asyncio.create_task(self._run())
        await self.ws.send_json({"type": "bot_partial", "text": sentence})
        await self.queue.put(sentence)

    async def _run(self) -> None:
        started = False
        while (sentence := await self.queue.get()) is not None:
            stream = tts.synthesize(sentence)
            if stream is None:  # браузерный TTS — клиент озвучит текст сам
                continue
            try:
                async for chunk in stream:
                    if not started:
                        await self.ws.send_json({"type": "tts_start"})
                        self.sw.stages["end_to_audio"] = self.sw.total()
                        started = True
                    await self.ws.send_bytes(chunk)
            except Exception as e:
                await self.ws.send_json({"type": "error", "message": f"TTS: {e}"})
        if started:
            await self.ws.send_json({"type": "tts_end"})

    async def close(self) -> None:
        if self.task:
            await self.queue.put(None)
            await self.task


@app.websocket("/ws/supervisor")
async def ws_supervisor(ws: WebSocket):
    await ws.accept()
    tracing.hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        tracing.hub.clients.discard(ws)
