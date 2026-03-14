"""Template registry for exported artifact rendering."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class TemplateRegistry:
    TEMPLATE_METADATA: dict[str, dict[str, Any]] = {
        "agent_index.html.tpl": {
            "version": "1.0.0",
            "required_keys": ["agent_name", "agent_role"],
        },
        "build_application_prompt.txt.tpl": {
            "version": "1.0.0",
            "required_keys": ["app_name"],
        },
        "export_agent_run_agent.py.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "AGENT_ROLE", "AGENT_SKILLS"],
        },
        "export_agent_server.py.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "AGENT_ROLE"],
        },
        "export_system_run_system.py.tpl": {
            "version": "1.0.0",
            "required_tokens": ["SYSTEM_NAME", "AGENT_LIST_REPR", "AGENT_ROLES_REPR"],
        },
        "export_agent_launch_agent.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME"],
        },
        "export_agent_readme.md.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "AGENT_ROLE", "AGENT_SKILLS", "AGENT_TOOLS", "AGENT_VERSION"],
        },
        "export_agent_build_exe.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "SAFE_NAME"],
        },
        "export_agent_build_exe.sh.tpl": {
            "version": "1.0.0",
            "required_tokens": ["SAFE_NAME"],
        },
        "export_agent_gui_launcher.py.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME"],
        },
        "export_agent_build_ui_exe.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "SAFE_NAME"],
        },
        "export_agent_agent_app.py.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME"],
        },
        "export_agent_start_agent.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME"],
        },
        "export_agent_Dockerfile.tpl": {
            "version": "1.0.0",
            "required_tokens": [],
        },
        "export_agent_dockerignore.tpl": {
            "version": "1.0.0",
            "required_tokens": [],
        },
        "export_system_launch_system.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["SYSTEM_NAME"],
        },
        "export_system_launch_agent_shortcut.bat.tpl": {
            "version": "1.0.0",
            "required_tokens": ["AGENT_NAME", "AGENT_ROLE"],
        },
        "export_system_readme.md.tpl": {
            "version": "1.0.0",
            "required_tokens": ["SYSTEM_NAME", "AGENT_COUNT", "AGENT_TABLE"],
        },
    }

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

    def version(self, name: str) -> str:
        meta = self.TEMPLATE_METADATA.get(name, {})
        return str(meta.get("version", "unknown"))

    def validate_format_data(self, name: str, data: dict[str, Any]) -> None:
        meta = self.TEMPLATE_METADATA.get(name, {})
        required = meta.get("required_keys", [])
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing template keys for '{name}': {', '.join(missing)}")

    def validate_token_data(self, name: str, data: dict[str, Any]) -> None:
        meta = self.TEMPLATE_METADATA.get(name, {})
        required = meta.get("required_tokens", [])
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing template tokens for '{name}': {', '.join(missing)}")

    def render(self, name: str, data: dict[str, Any]) -> str:
        self.validate_format_data(name, data)
        tpl = self.load(name)
        return tpl.format(**data)

    def render_tokens(self, name: str, data: dict[str, Any]) -> str:
        self.validate_token_data(name, data)
        tpl = self.load(name)
        for key, value in data.items():
            tpl = tpl.replace(f"__{key}__", str(value))

        unresolved = sorted(set(re.findall(r"__([A-Z0-9_]+)__", tpl)))
        if unresolved:
            raise ValueError(
                f"Unresolved template tokens in '{name}': {', '.join(unresolved)}"
            )
        return tpl
