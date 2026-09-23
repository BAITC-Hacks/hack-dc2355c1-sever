"""Распознавание речи: ElevenLabs Scribe, fallback OpenAI Whisper.

Этап 1 — пакетное распознавание готовой записи. Realtime-стрим Scribe — этап 4.
"""

import httpx

from ..config import settings
from . import llm

LANG_MAP = {"kaz": "kk", "kk": "kk", "rus": "ru", "ru": "ru"}


def sniff(audio: bytes) -> tuple[str, str]:
    """Формат записи по сигнатуре: Chrome/Firefox пишут webm/ogg, Safari — mp4."""
    if audio[:4] == b"\x1aE\xdf\xa3":
        return "speech.webm", "audio/webm"
    if audio[4:8] == b"ftyp":
        return "speech.mp4", "audio/mp4"
    if audio[:4] == b"OggS":
        return "speech.ogg", "audio/ogg"
    if audio[:4] == b"RIFF":
        return "speech.wav", "audio/wav"
    if audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "speech.mp3", "audio/mpeg"
    return "speech.webm", "audio/webm"


async def _elevenlabs(audio: bytes, mime: str) -> tuple[str, str | None]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            data={"model_id": settings.elevenlabs_stt_model},
            files={"file": (sniff(audio)[0], audio, sniff(audio)[1])},
        )
        resp.raise_for_status()
        body = resp.json()
    return body.get("text", "").strip(), LANG_MAP.get(body.get("language_code", ""))


# Подсказка для OpenAI STT: без неё казахская речь уходит в латиницу или русскую транслитерацию.
OPENAI_PROMPT = (
    "Звонок в контакт-центр страховой компании Saqta Insurance, Казахстан. Клиент говорит по-русски, по-казахски "
    "или смешивает оба языка в одной фразе. Пиши казахские слова казахской кириллицей (ә, і, ң, ғ, ү, ұ, қ, ө, һ), "
    "русские — русской. Термины: ОГПО, КАСКО, ДМС, полис, франшиза."
)
_disabled: set[str] = set()  # провайдеры, у ключа которых нет прав на STT — не тратим на них запрос каждую реплику


async def _openai(audio: bytes, mime: str) -> tuple[str, str | None]:
    resp = await llm._client("openai").audio.transcriptions.create(
        model=settings.openai_stt_model, file=(sniff(audio)[0], audio, sniff(audio)[1]), prompt=OPENAI_PROMPT
    )
    return resp.text.strip(), None


async def transcribe(audio: bytes, mime: str = "audio/webm") -> tuple[str, str]:
    """Возвращает (текст, провайдер)."""
    order = ["elevenlabs", "openai"] if settings.stt_provider == "elevenlabs" else ["openai", "elevenlabs"]
    last_error: Exception | None = None
    for name in order:
        if name in _disabled:
            continue
        if name == "elevenlabs" and not settings.elevenlabs_api_key:
            continue
        if name == "openai" and not settings.openai_api_key:
            continue
        try:
            text, _ = await (_elevenlabs if name == "elevenlabs" else _openai)(audio, mime)
            return text, name
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code in (401, 403):  # нет прав у ключа — до перезапуска не пробуем
                _disabled.add(name)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"STT недоступен: {last_error}")
