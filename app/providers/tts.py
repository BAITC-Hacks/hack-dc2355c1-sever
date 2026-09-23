"""Синтез речи: ElevenLabs (стрим), fallback OpenAI TTS, иначе — браузерный speechSynthesis."""

from collections.abc import AsyncIterator

import httpx

from ..config import settings
from . import llm


async def _elevenlabs(text: str) -> AsyncIterator[bytes]:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream"
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
            url,
            params={"output_format": "mp3_44100_64", "optimize_streaming_latency": 3},
            headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"text": text, "model_id": settings.elevenlabs_tts_model},
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk


async def _openai(text: str) -> AsyncIterator[bytes]:
    resp = await llm._client("openai").audio.speech.create(model="tts-1", voice="alloy", input=text, response_format="mp3")
    yield resp.content


_disabled: set[str] = set()  # у ключа нет прав на TTS (401/403) — до перезапуска не пробуем


def provider() -> str:
    if settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key and "elevenlabs" not in _disabled:
        return "elevenlabs"
    if settings.tts_provider in ("elevenlabs", "openai") and settings.openai_api_key:
        return "openai"
    return "browser"


async def _with_fallback(text: str) -> AsyncIterator[bytes]:
    """ElevenLabs, а если он упал до первого байта (ключ без прав, лимит, сеть) — OpenAI TTS: бот не замолкает."""
    started = False
    try:
        async for chunk in _elevenlabs(text):
            started = True
            yield chunk
        return
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            _disabled.add("elevenlabs")
        if started or not settings.openai_api_key:
            raise
    except Exception:
        if started or not settings.openai_api_key:
            raise
    async for chunk in _openai(text):
        yield chunk


def synthesize(text: str) -> AsyncIterator[bytes] | None:
    name = provider()
    if name == "elevenlabs":
        return _with_fallback(text)
    if name == "openai":
        return _openai(text)
    return None
