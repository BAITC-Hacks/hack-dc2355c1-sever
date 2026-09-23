"""Каталог сценариев, слоты, действия, база знаний и mock backend из стартового кита."""

import json
from typing import Any

from .config import settings


def _read(name: str) -> Any:
    path = settings.data_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class Catalog:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        raw = _read("scenarios.json")
        self.meta: dict = raw.get("meta", {})
        self.scenarios: dict[str, dict] = {s["scenario_id"]: s for s in raw.get("scenarios", [])}
        self.system_intents: dict[str, dict] = {s["id"]: s for s in raw.get("system_intents", [])}
        self.slots: dict[str, dict] = {s["name"]: s for s in _read("slots.json").get("slots", [])}
        self.actions: dict = _read("actions.json")
        self.knowledge_base: dict = _read("knowledge_base.json")
        self.mock_backend: dict = _read("mock_backend.json")

    @property
    def as_of_date(self) -> str:
        return self.meta.get("as_of_date", "2026-10-01")

    def known(self, sid: str | None) -> bool:
        return bool(sid) and (sid in self.scenarios or sid in self.system_intents)

    def title(self, sid: str) -> str:
        return self.scenarios.get(sid, {}).get("name", sid)

    def priority(self, sid: str) -> str:
        return self.scenarios.get(sid, {}).get("priority", "normal")

    def card(self, sid: str, n_examples: int = 2) -> str:
        """Компактная карточка сценария для промпта роутера."""
        sc = self.scenarios[sid]
        lines = [f"{sid} [{sc['domain']}/{sc['category']}, {sc['priority']}] {sc['name']}: {sc['description']}"]
        slots = sc.get("slots", {})
        names = [f"{n}*" for n in slots.get("required", [])] + slots.get("optional", [])
        if names:
            lines.append("  слоты: " + ", ".join(names))
        for rule in sc.get("not_this_if", []):
            lines.append(f"  - НЕ он, если {rule['condition']} → {rule['use_instead']}")
        ex = sc.get("examples", {})
        samples = ex.get("ru", [])[:n_examples] + ex.get("kk", [])[:n_examples]
        if samples:
            lines.append("  примеры: " + " | ".join(samples))
        return "\n".join(lines)

    def system_cards(self) -> str:
        return "\n".join(f"{sid}: {s['description']}" for sid, s in self.system_intents.items())

    def embed_text(self, sid: str) -> str:
        return self.card(sid, n_examples=10)

    def save(self, scenarios: list[dict]) -> None:
        raw = _read("scenarios.json")
        raw["scenarios"] = scenarios
        (settings.data_dir / "scenarios.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.reload()


catalog = Catalog()
