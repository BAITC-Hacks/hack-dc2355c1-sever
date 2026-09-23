"""Обёртка над OpenAI API: кэш на диск, ретраи, учёт токенов.

Зачем: при отладке один и тот же запрос уходит в API десятки раз.
Кэш экономит и деньги, и время (повторный вызов возвращается мгновенно).
"""

import hashlib
import json
import os
import pathlib
import random
import sys
import time

from openai import OpenAI

ROOT = pathlib.Path(__file__).parent
CACHE_DIR = ROOT / ".cache"
USAGE_FILE = ROOT / ".usage.json"


def _load_env():
    """Читаем .env без внешних зависимостей."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

MODEL = os.environ.get("MODEL", "gpt-5-mini")
MODEL_SMART = os.environ.get("MODEL_SMART", MODEL)
CACHE_ENABLED = os.environ.get("CACHE", "1") != "0"

_client = None


def client():
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            sys.exit("Нет OPENAI_API_KEY. Скопируйте .env.example в .env и вставьте ключ.")
        _client = OpenAI(api_key=key)
    return _client


def _cache_key(payload):
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _track_usage(model, usage):
    """Копим токены по моделям в .usage.json, чтобы видеть расход."""
    if usage is None:
        return
    stats = {}
    if USAGE_FILE.exists():
        try:
            stats = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stats = {}
    row = stats.setdefault(model, {"calls": 0, "in": 0, "out": 0})
    row["calls"] += 1
    row["in"] += getattr(usage, "prompt_tokens", 0) or 0
    row["out"] += getattr(usage, "completion_tokens", 0) or 0
    USAGE_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def usage_report():
    if not USAGE_FILE.exists():
        return "Расход пока нулевой."
    stats = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    lines = []
    for model, row in sorted(stats.items()):
        lines.append("{}: {} вызовов, {} вход / {} выход токенов".format(
            model, row["calls"], row["in"], row["out"]))
    return "\n".join(lines)


def _status(error):
    return getattr(error, "status_code", None) or getattr(
        getattr(error, "response", None), "status_code", None)


def _unsupported_param(error):
    """Если модель не приняла параметр - достаём его имя из ответа API."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        name = body.get("error", {}).get("param")
        if name:
            return name
    match = re.search(r"Unsupported (?:value|parameter): '([^']+)'", str(error))
    return match.group(1) if match else None


def chat(messages, model=None, tools=None, temperature=None, use_cache=None, **kwargs):
    """Вызов модели с кэшем и ретраями. Возвращает объект message."""
    model = model or MODEL
    use_cache = CACHE_ENABLED if use_cache is None else use_cache

    payload = {"model": model, "messages": messages, "tools": tools,
               "temperature": temperature, **kwargs}
    # temperature=None означает "не передавать": часть моделей принимает
    # только значение по умолчанию и падает с 400 на любом другом.

    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / (_cache_key(payload) + ".json")
    if use_cache and cache_file.exists():
        from openai.types.chat import ChatCompletionMessage
        return ChatCompletionMessage.model_validate_json(
            cache_file.read_text(encoding="utf-8"))

    request = {k: v for k, v in payload.items() if v is not None}

    last_error = None
    for attempt in range(5):
        try:
            response = client().chat.completions.create(**request)
            message = response.choices[0].message
            _track_usage(model, getattr(response, "usage", None))
            if use_cache:
                cache_file.write_text(message.model_dump_json(), encoding="utf-8")
            return message
        except Exception as error:
            last_error = error
            status = _status(error)

            # 400: модель не приняла параметр. Выкидываем его и пробуем снова -
            # но только один раз на параметр, иначе зациклимся.
            if status == 400:
                param = _unsupported_param(error)
                if param and param in request:
                    print("  [llm] модель {} не поддерживает {} - убираю".format(
                        model, param), file=sys.stderr)
                    request.pop(param)
                    continue
                raise RuntimeError(
                    "Запрос отклонён (400). Повторять бесполезно: {}".format(error))

            # Ключ, права, несуществующая модель - ретрай не поможет.
            if status in (401, 403, 404):
                raise RuntimeError(
                    "Ошибка {}: {}\nПроверьте ключ в .env и имя модели "
                    "(smoke_test.py покажет доступные).".format(status, error))

            # 429 и 5xx - это как раз то, что лечится паузой.
            wait = (2 ** attempt) + random.random()
            print("  [llm] попытка {} не удалась ({}), жду {:.1f}с".format(
                attempt + 1, type(error).__name__, wait), file=sys.stderr)
            time.sleep(wait)

    raise RuntimeError("API не ответил после 5 попыток: {}".format(last_error))


def ask(prompt, system=None, **kwargs):
    """Самый короткий путь: строка на вход, строка на выход."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, **kwargs).content
