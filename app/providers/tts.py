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


def provider() -> str:
    if settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key:
        return "elevenlabs"
    if settings.tts_provider in ("elevenlabs", "openai") and settings.openai_api_key:
        return "openai"
    return "browser"


def synthesize(text: str) -> AsyncIterator[bytes] | None:
    name = provider()
    if name == "elevenlabs":
        return _elevenlabs(text)
    if name == "openai":
        return _openai(text)
    return None
