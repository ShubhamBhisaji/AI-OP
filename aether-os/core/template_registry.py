"""Template registry for exported artifact rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class TemplateRegistry:
    def __init__(self, templates_dir: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        self.templates_dir = templates_dir or (root / "templates")

    def path_for(self, name: str) -> Path:
        return (self.templates_dir / name).resolve()

    def load(self, name: str) -> str:
        p = self.path_for(name)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Template '{name}' not found at {p}")
        return p.read_text(encoding="utf-8")

    def render(self, name: str, data: dict[str, Any]) -> str:
        tpl = self.load(name)
        return tpl.format(**data)
