"""Каталог сценариев, база знаний и mock backend.

Формат файлов стартового кита заранее неизвестен, поэтому загрузчик терпимый:
принимает список или {"scenarios": [...]}, id ищет в нескольких полях.
Если data/scenarios.json нет — берётся data/sample/.
"""

import json
from pathlib import Path
from typing import Any

from .config import settings

ID_KEYS = ("id", "scenario_id", "code", "name")
TEXT_KEYS = ("title", "name", "purpose", "description", "назначение")


def _read(name: str) -> Any:
    for base in (settings.data_dir, settings.data_dir / "sample"):
        path = base / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def _as_list(raw: Any, key: str) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get(key, list(raw.values()) if all(isinstance(v, dict) for v in raw.values()) else [])
    return list(raw)


class Catalog:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.scenarios: dict[str, dict] = {}
        for sc in _as_list(_read("scenarios.json"), "scenarios"):
            sid = next((str(sc[k]) for k in ID_KEYS if sc.get(k)), None)
            if sid:
                self.scenarios[sid] = sc
        self.knowledge_base = _read("knowledge_base.json") or {}
        self.mock_backend = _read("mock_backend.json") or {}

    def title(self, sid: str) -> str:
        sc = self.scenarios.get(sid, {})
        return next((str(sc[k]) for k in ("title", "name") if sc.get(k)), sid)

    def card(self, sid: str) -> str:
        """Компактное описание сценария для промпта роутера."""
        sc = self.scenarios[sid]
        fields = {k: v for k, v in sc.items() if k not in ID_KEYS and k not in ("responses", "response_examples")}
        return f"### {sid}\n" + json.dumps(fields, ensure_ascii=False)

    def embed_text(self, sid: str) -> str:
        sc = self.scenarios[sid]
        return json.dumps({k: v for k, v in sc.items() if k not in ("responses", "response_examples")}, ensure_ascii=False)

    def is_irreversible(self, sid: str) -> bool:
        return bool(self.scenarios.get(sid, {}).get("irreversible"))

    def save(self, scenarios: list[dict]) -> None:
        path: Path = settings.data_dir / "scenarios.json"
        path.write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")
        self.reload()


catalog = Catalog()
