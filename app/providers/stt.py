"""Распознавание речи: ElevenLabs Scribe, fallback OpenAI Whisper.

Этап 1 — пакетное распознавание готовой записи. Realtime-стрим Scribe — этап 4.
"""

import httpx

from ..config import settings
from . import llm

LANG_MAP = {"kaz": "kk", "kk": "kk", "rus": "ru", "ru": "ru"}


async def _elevenlabs(audio: bytes, mime: str) -> tuple[str, str | None]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            data={"model_id": settings.elevenlabs_stt_model},
            files={"file": ("speech.webm", audio, mime)},
        )
        resp.raise_for_status()
        body = resp.json()
    return body.get("text", "").strip(), LANG_MAP.get(body.get("language_code", ""))


async def _openai(audio: bytes, mime: str) -> tuple[str, str | None]:
    resp = await llm._client("openai").audio.transcriptions.create(
        model="whisper-1", file=("speech.webm", audio, mime)
    )
    return resp.text.strip(), None


async def transcribe(audio: bytes, mime: str = "audio/webm") -> tuple[str, str]:
    """Возвращает (текст, провайдер)."""
    order = ["elevenlabs", "openai"] if settings.stt_provider == "elevenlabs" else ["openai", "elevenlabs"]
    last_error: Exception | None = None
    for name in order:
        if name == "elevenlabs" and not settings.elevenlabs_api_key:
            continue
        if name == "openai" and not settings.openai_api_key:
            continue
        try:
            text, _ = await (_elevenlabs if name == "elevenlabs" else _openai)(audio, mime)
            return text, name
        except Exception as e:
            last_error = e
    raise RuntimeError(f"STT недоступен: {last_error}")
