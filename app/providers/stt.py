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
            # Без подсказки Scribe принимает казахский за турецкий/украинский; с «kaz» русский распознаёт так же хорошо.
            data={"model_id": settings.elevenlabs_stt_model, "language_code": settings.elevenlabs_stt_language},
            files={"file": (sniff(audio)[0], audio, sniff(audio)[1])},
        )
        resp.raise_for_status()
        body = resp.json()
    return body.get("text", "").strip(), LANG_MAP.get(body.get("language_code", ""))


# Подсказка для OpenAI STT: без неё казахская речь уходит в латиницу, турецкий или арабское письмо.
OPENAI_PROMPT = (
    "Звонок в контакт-центр страховой компании Saqta Insurance, Казахстан. Клиент говорит ТОЛЬКО по-русски или "
    "по-казахски, иногда смешивая оба языка в одной фразе. Других языков нет. Пиши казахские слова казахской "
    "кириллицей (ә, і, ң, ғ, ү, ұ, қ, ө, һ), русские — русской. Никогда не используй латиницу для слов, арабское "
    "или другое письмо. Термины: ОГПО, КАСКО, ДМС, полис, франшиза."
)
_disabled: set[str] = set()  # провайдеры, у ключа которых нет прав на STT — не тратим на них запрос каждую реплику
MIN_CYRILLIC = 0.4  # доля кириллицы среди букв; ниже — распознано не как русский/казахский


async def _openai(audio: bytes, mime: str) -> tuple[str, str | None]:
    resp = await llm._client("openai").audio.transcriptions.create(
        model=settings.openai_stt_model, file=(sniff(audio)[0], audio, sniff(audio)[1]), prompt=OPENAI_PROMPT
    )
    return resp.text.strip(), None


def cyrillic_share(text: str) -> float:
    """Доля кириллических букв. Латиница в госномерах и кодах полиса («482KMA02») погоды не делает."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum("\u0400" <= c <= "\u04ff" for c in letters) / len(letters)


async def transcribe(audio: bytes, mime: str = "audio/webm") -> tuple[str, str]:
    """Возвращает (текст, провайдер). Поддерживаются только русский и казахский: если основной провайдер
    вернул не кириллицу (арабское письмо, турецкая латиница), пробуем следующий и берём самый кириллический вариант."""
    order = ["elevenlabs", "openai"] if settings.stt_provider == "elevenlabs" else ["openai", "elevenlabs"]
    last_error: Exception | None = None
    best: tuple[float, str, str] | None = None
    for name in order:
        if name in _disabled:
            continue
        if name == "elevenlabs" and not settings.elevenlabs_api_key:
            continue
        if name == "openai" and not settings.openai_api_key:
            continue
        try:
            text, _ = await (_elevenlabs if name == "elevenlabs" else _openai)(audio, mime)
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code in (401, 403):  # нет прав у ключа — до перезапуска не пробуем
                _disabled.add(name)
            continue
        except Exception as e:
            last_error = e
            continue
        share = cyrillic_share(text)
        if share >= MIN_CYRILLIC:
            return text, name if best is None else f"{name} (повтор: {best[2]} дал не кириллицу)"
        if best is None or share > best[0]:
            best = (share, text, name)
    if best:
        return best[1], f"{best[2]} (низкая доля кириллицы)"
    raise RuntimeError(f"STT недоступен: {last_error}")
