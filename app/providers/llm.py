"""Единый клиент для OpenAI-совместимых API (OpenAI и NVIDIA NIM)."""

import asyncio
import json
import re

from openai import AsyncOpenAI

from ..config import settings

_clients: dict[str, AsyncOpenAI] = {}


def _client(name: str) -> AsyncOpenAI:
    if name not in _clients:
        if name == "nvidia":
            _clients[name] = AsyncOpenAI(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)
        else:
            _clients[name] = AsyncOpenAI(api_key=settings.openai_api_key)
    return _clients[name]


def available(name: str) -> bool:
    return bool(settings.nvidia_api_key if name == "nvidia" else settings.openai_api_key)


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


async def chat_json(provider: str, system: str, user: str) -> dict:
    """Вызов модели с ответом строго в JSON."""
    model = settings.nvidia_model if provider == "nvidia" else settings.openai_model
    kwargs = {"temperature": 0} if provider == "nvidia" else {}
    resp = await _client(provider).chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        **kwargs,
    )
    return _extract_json(resp.choices[0].message.content or "{}")


def _close_prefix(buf: str, split_key: str) -> dict | None:
    """JSON-префикс до split_key → валидный объект (закрываем скобку)."""
    idx = buf.find(split_key)
    if idx < 0:
        return None
    head = buf[:idx].rstrip().rstrip(",") + "}"
    try:
        return json.loads(head)
    except json.JSONDecodeError:
        return None


async def chat_json_stream(provider: str, system: str, user: str, split_key: str) -> tuple[dict, "asyncio.Task[dict]"]:
    """Потоковый вызов: возвращает решение, как только модель дописала всё до split_key,
    и задачу, которая дочитывает поток и отдаёт полный JSON (обоснование для супервизора)."""
    model = settings.nvidia_model if provider == "nvidia" else settings.openai_model
    kwargs = {"temperature": 0} if provider == "nvidia" else {}
    stream = await _client(provider).chat.completions.create(
        model=model,
        stream=True,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        **kwargs,
    )
    head: asyncio.Future[dict] = asyncio.get_running_loop().create_future()

    async def consume() -> dict:
        buf = ""
        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if not delta:
                    continue
                buf += delta
                if not head.done():
                    parsed = _close_prefix(buf, split_key)
                    if parsed is not None:
                        head.set_result(parsed)
            full = _extract_json(buf or "{}")
        except Exception as e:
            if not head.done():
                head.set_exception(e)
            raise
        if not head.done():
            head.set_result(full)
        return full

    task = asyncio.create_task(consume())
    return await head, task


async def embed(texts: list[str]) -> list[list[float]]:
    resp = await _client("openai").embeddings.create(model=settings.openai_embed_model, input=texts)
    return [d.embedding for d in resp.data]
