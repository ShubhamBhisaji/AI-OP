"""Exporter service facade for agent/system export operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.aether_kernel import AetherKernel


class ExporterService:
    """
    Thin export orchestration layer.

    This service intentionally delegates to kernel implementation methods for
    backward compatibility while we progressively migrate template/codegen
    responsibilities out of AetherKernel.
    """

    def __init__(self, kernel: "AetherKernel") -> None:
        self._kernel = kernel

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def _base_export_agent(self, name: str) -> dict:
        import shutil

        agent = self._kernel.registry.get(name)
        if agent is None:
            return {"error": f"Agent '{name}' not found."}

        if agent.profile.get("is_subagent") or agent.profile.get("is_exportable") is False:
            system = agent.profile.get("system", "an AI System")
            return {
                "error": (
                    f"Agent '{name}' is an internal sub-agent of '{system}' "
                    f"and cannot be exported individually. "
                    f"Use export_system to export the whole system."
                )
            }

        project_root = Path(__file__).parent.parent
        exports_root = (project_root / "exports").resolve()
        export_dir = self._kernel._safe_child_path(exports_root, name, fallback="agent")
        export_dir.mkdir(parents=True, exist_ok=True)

        files_written: list[str] = []
        self._write(export_dir / "agent_profile.json", json.dumps(agent.to_dict(), indent=2))
        files_written.append("agent_profile.json")

        dirs_to_copy = ["agents", "ai", "core", "factory", "memory", "registry", "skills", "tools", "cli"]
        for d in dirs_to_copy:
            src = project_root / d
            dst = export_dir / d
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                files_written.append(f"{d}/")

        blank_env = (
            "# AetheerAI — An AI Master!! Agent — AI Configuration\n"
            "# Run python run_agent.py to configure interactively (first launch)\n\n"
            "AETHER_DEFAULT_PROVIDER=\n"
            "AETHER_DEFAULT_MODEL=\n\n"
            "# Paste your key for the provider you choose:\n"
            "GITHUB_TOKEN=\n"
            "OPENAI_API_KEY=\n"
            "GEMINI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
        )
        self._write(export_dir / ".env", blank_env)
        self._write(export_dir / ".env.example", blank_env)
        files_written.extend([".env", ".env.example"])

        agent_tools = agent.profile.get("tools", [])
        self._write(export_dir / "requirements.txt", self._kernel._build_requirements(agent_tools))
        files_written.append("requirements.txt")

        try:
            rendered_index = self._kernel.template_registry.render(
                "agent_index.html.tpl",
                {"agent_name": name, "agent_role": agent.role},
            )
        except Exception:
            rendered_index = f"<html><body><h1>{name}</h1><p>{agent.role}</p></body></html>"
        self._write(export_dir / "index.html", rendered_index)
        files_written.append("index.html")

        return {"output_dir": str(export_dir), "files": files_written, "error": None}

    def _base_export_system(self, system_name: str, agent_names: list[str]) -> dict:
        import shutil

        missing = [n for n in agent_names if self._kernel.registry.get(n) is None]
        if missing:
            return {"error": f"Agents not found: {', '.join(missing)}"}

        agents = [self._kernel.registry.get(n) for n in agent_names]
        project_root = Path(__file__).parent.parent
        exports_root = (project_root / "exports").resolve()
        sys_dir = self._kernel._safe_child_path(exports_root, system_name, fallback="system")
        sys_dir.mkdir(parents=True, exist_ok=True)

        dirs_to_copy = ["agents", "ai", "core", "factory", "memory", "registry", "skills", "tools", "cli"]
        for d in dirs_to_copy:
            src = project_root / d
            dst = sys_dir / d
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)

        blank_env = (
            f"# {system_name} — AI System Configuration\n"
            "# Run python run_system.py to configure interactively (first launch)\n\n"
            "AETHER_DEFAULT_PROVIDER=\n"
            "AETHER_DEFAULT_MODEL=\n\n"
            "# Paste your key for the provider you choose:\n"
            "GITHUB_TOKEN=\n"
            "OPENAI_API_KEY=\n"
            "GEMINI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
        )
        self._write(sys_dir / ".env", blank_env)
        self._write(sys_dir / ".env.example", blank_env)

        agents_dir = sys_dir / "agent_profiles"
        agents_dir.mkdir(exist_ok=True)
        for agent in agents:
            safe_agent_file = self._kernel._safe_fs_component(agent.name, fallback="agent") + ".json"
            self._write(agents_dir / safe_agent_file, json.dumps(agent.to_dict(), indent=2))

        all_tools: list[str] = []
        for a in agents:
            all_tools.extend(a.profile.get("tools", []))
        self._write(sys_dir / "requirements.txt", self._kernel._build_requirements(all_tools))

        return {"output_dir": str(sys_dir), "agents": agent_names, "error": None}

    def _write_export_manifest(self, out_dir: Path, scope: str, template_versions: dict[str, str]) -> None:
        payload = {
            "manifest_schema_version": "1.0.0",
            "scope": scope,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "template_versions": template_versions,
        }
        (out_dir / "export_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _externalize_agent_templates(self, export_dir: Path, name: str) -> dict[str, str]:
        agent = self._kernel.registry.get(name)
        if agent is None:
            return {}

        template_versions: dict[str, str] = {}
        reg = self._kernel.template_registry

        run_text = reg.render_tokens(
            "export_agent_run_agent.py.tpl",
            {
                "AGENT_NAME": name,
                "AGENT_ROLE": agent.role,
                "AGENT_SKILLS": ", ".join(agent.profile.get("skills", [])),
            },
        )
        self._write(export_dir / "run_agent.py", run_text)
        template_versions["export_agent_run_agent.py.tpl"] = reg.version("export_agent_run_agent.py.tpl")

        server_text = reg.render_tokens(
            "export_agent_server.py.tpl",
            {
                "AGENT_NAME": name,
                "AGENT_ROLE": agent.role,
            },
        )
        self._write(export_dir / "server.py", server_text)
        template_versions["export_agent_server.py.tpl"] = reg.version("export_agent_server.py.tpl")

        safe_name = name.replace(" ", "-")
        agent_tokens = {
            "AGENT_NAME": name,
            "AGENT_ROLE": agent.role,
            "AGENT_SKILLS": ", ".join(agent.profile.get("skills", [])),
            "AGENT_TOOLS": ", ".join(agent.profile.get("tools", [])),
            "AGENT_VERSION": str(agent.profile.get("version", "1.0.0")),
            "SAFE_NAME": safe_name,
        }

        agent_file_map = {
            "export_agent_launch_agent.bat.tpl": "launch_agent.bat",
            "export_agent_readme.md.tpl": "README.md",
            "export_agent_build_exe.bat.tpl": "build_exe.bat",
            "export_agent_build_exe.sh.tpl": "build_exe.sh",
            "export_agent_gui_launcher.py.tpl": "gui_launcher.py",
            "export_agent_build_ui_exe.bat.tpl": "build_ui_exe.bat",
            "export_agent_agent_app.py.tpl": "agent_app.py",
            "export_agent_start_agent.bat.tpl": "Start_Agent.bat",
            "export_agent_Dockerfile.tpl": "Dockerfile",
            "export_agent_dockerignore.tpl": ".dockerignore",
        }
        for tpl_name, out_name in agent_file_map.items():
            rendered = reg.render_tokens(tpl_name, agent_tokens)
            self._write(export_dir / out_name, rendered)
            template_versions[tpl_name] = reg.version(tpl_name)

        return template_versions

    def _externalize_system_templates(
        self,
        sys_dir: Path,
        system_name: str,
        agent_names: list[str],
    ) -> dict[str, str]:
        agents = [self._kernel.registry.get(n) for n in agent_names]
        agent_roles = {a.name: a.role for a in agents if a is not None}

        reg = self._kernel.template_registry
        run_text = reg.render_tokens(
            "export_system_run_system.py.tpl",
            {
                "SYSTEM_NAME": system_name,
                "AGENT_LIST_REPR": repr(agent_names),
                "AGENT_ROLES_REPR": repr(agent_roles),
            },
        )
        self._write(sys_dir / "run_system.py", run_text)

        template_versions = {
            "export_system_run_system.py.tpl": reg.version("export_system_run_system.py.tpl"),
        }

        system_text = reg.render_tokens(
            "export_system_launch_system.bat.tpl",
            {"SYSTEM_NAME": system_name},
        )
        self._write(sys_dir / "launch_system.bat", system_text)
        template_versions["export_system_launch_system.bat.tpl"] = reg.version(
            "export_system_launch_system.bat.tpl"
        )

        rows = []
        for agent_name in agent_names:
            role = agent_roles.get(agent_name, "")
            row = f"| {agent_name} | {role} | launch_{agent_name}.bat |"
            rows.append(row)

            launch_text = reg.render_tokens(
                "export_system_launch_agent_shortcut.bat.tpl",
                {"AGENT_NAME": agent_name, "AGENT_ROLE": role},
            )
            self._write(sys_dir / f"launch_{agent_name}.bat", launch_text)
        template_versions["export_system_launch_agent_shortcut.bat.tpl"] = reg.version(
            "export_system_launch_agent_shortcut.bat.tpl"
        )

        readme_text = reg.render_tokens(
            "export_system_readme.md.tpl",
            {
                "SYSTEM_NAME": system_name,
                "AGENT_COUNT": str(len(agent_names)),
                "AGENT_TABLE": "\n".join(rows),
            },
        )
        self._write(sys_dir / "README.md", readme_text)
        template_versions["export_system_readme.md.tpl"] = reg.version("export_system_readme.md.tpl")

        return template_versions

    def export_agent(self, name: str) -> dict:
        result = self._base_export_agent(name)
        if result.get("error"):
            return result

        out_dir = Path(result["output_dir"])
        template_versions: dict[str, str] = {}
        try:
            template_versions = self._externalize_agent_templates(out_dir, name)
        except Exception:
            # Keep backward-compatible inline templates if externalization fails.
            template_versions = {}

        self._write_export_manifest(out_dir, "agent", template_versions)
        return result

    def export_system(self, system_name: str, agent_names: list[str]) -> dict:
        result = self._base_export_system(system_name, agent_names)
        if result.get("error"):
            return result

        out_dir = Path(result["output_dir"])
        template_versions: dict[str, str] = {}
        try:
            template_versions = self._externalize_system_templates(out_dir, system_name, agent_names)
        except Exception:
            template_versions = {}

        self._write_export_manifest(out_dir, "system", template_versions)
        return result
