"""
AetherKernel — Central controller and orchestrator of the Aether AI OS.
Manages all subsystems: agents, workflows, tools, memory, and AI adapters.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent
from factory.agent_factory import AgentFactory
from registry.agent_registry import AgentRegistry
from skills.skill_engine import SkillEngine
from core.workflow_engine import WorkflowEngine
from tools.tool_manager import ToolManager
from ai.ai_adapter import AIAdapter
from memory.memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="[Aether] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class AetherKernel:
    """
    The central kernel of the Aether AI Operating System.
    All subsystems are initialized and coordinated here.
    """

    def __init__(self, ai_provider: str = "openai", model: str = "gpt-4o"):
        logger.info("Booting Aether OS kernel...")
        self.ai_adapter = AIAdapter(provider=ai_provider, model=model)
        self.memory = MemoryManager()
        self.registry = AgentRegistry()
        self.tool_manager = ToolManager()
        self.skill_engine = SkillEngine(registry=self.registry, ai_adapter=None)  # ai_adapter set below
        self.factory = AgentFactory(
            registry=self.registry,
            tool_manager=self.tool_manager,
            ai_adapter=self.ai_adapter,
        )
        self.workflow_engine = WorkflowEngine(
            registry=self.registry,
            ai_adapter=self.ai_adapter,
            memory=self.memory,
        )
        # Wire AI adapter into skill engine after creation
        self.skill_engine.ai_adapter = self.ai_adapter
        logger.info("Aether OS kernel ready.")

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def create_agent(self, name: str, role: str, tools: list[str] | None = None) -> BaseAgent:
        """Create a new agent and register it."""
        agent = self.factory.create(name=name, role=role, tools=tools or [])
        logger.info("Agent '%s' created with role: %s", name, role)
        return agent

    def upgrade_agent(self, name: str) -> None:
        """Upgrade the skills and prompt of an existing agent."""
        self.skill_engine.upgrade(name)
        logger.info("Agent '%s' upgraded.", name)

    def run_agent(self, name: str, task: str) -> Any:
        """Run a named agent on a given task."""
        agent = self.registry.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' not found in registry.")
        logger.info("Running agent '%s' on task: %s", name, task)
        result = self.workflow_engine.execute(agent=agent, task=task)
        self.memory.save(key=f"{name}:last_result", value=result)
        return result

    def list_agents(self) -> list[str]:
        """Return a list of all registered agent names."""
        return self.registry.list_names()

    def delete_agent(self, name: str) -> bool:
        """Remove an agent from the registry permanently."""
        removed = self.registry.remove(name)
        if removed:
            logger.info("Agent '%s' deleted.", name)
        return removed

    def export_agent(self, name: str) -> dict:
        """
        Export a self-contained runnable folder for the named agent under
        exports/<name>/.  Returns dict with 'output_dir', 'files', 'error'.
        """
        import json, shutil, textwrap
        from pathlib import Path

        agent = self.registry.get(name)
        if agent is None:
            return {"error": f"Agent '{name}' not found."}

        project_root = Path(__file__).parent.parent
        export_dir = project_root / "exports" / name
        export_dir.mkdir(parents=True, exist_ok=True)

        files_written: list[str] = []

        # ── 1. agent_profile.json ────────────────────────────────────────
        profile_path = export_dir / "agent_profile.json"
        profile_path.write_text(
            json.dumps(agent.to_dict(), indent=2), encoding="utf-8"
        )
        files_written.append("agent_profile.json")

        # ── 2. Copy core Python source files needed to run independently ─
        dirs_to_copy = ["agents", "ai", "core", "factory", "memory",
                        "registry", "skills", "tools", "cli"]
        for d in dirs_to_copy:
            src = project_root / d
            dst = export_dir / d
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                files_written.append(f"{d}/")

        # ── 3. .env.example (strip actual secrets) ───────────────────────
        env_src = project_root / ".env"
        env_example = export_dir / ".env.example"
        env_lines = []
        if env_src.exists():
            for line in env_src.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    key = line.split("=", 1)[0]
                    env_lines.append(f"{key}=your_value_here")
                else:
                    env_lines.append(line)
        env_example.write_text("\n".join(env_lines), encoding="utf-8")
        files_written.append(".env.example")

        # ── 4. requirements.txt ──────────────────────────────────────────
        req = export_dir / "requirements.txt"
        req.write_text(
            "openai\nanthropic\nollama\npython-dotenv\npyyaml\n",
            encoding="utf-8",
        )
        files_written.append("requirements.txt")

        # ── 5. run_agent.py — standalone entry point ─────────────────────
        run_py = export_dir / "run_agent.py"
        run_py.write_text(
            textwrap.dedent(f"""\
            \"\"\"
            Standalone runner for agent: {name}
            Role: {agent.role}
            Skills: {', '.join(agent.profile.get('skills', []))}

            Usage:
                python run_agent.py
                python run_agent.py --task "your task here"
                python run_agent.py --provider ollama --model llama3.2:1b
            \"\"\"
            from __future__ import annotations
            import argparse, os, sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            try:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
            except ImportError:
                pass

            from cli.agent_window import run_agent_window

            def main():
                parser = argparse.ArgumentParser()
                parser.add_argument("--task", default=None)
                parser.add_argument("--provider", default="ollama")
                parser.add_argument("--model", default="llama3.2:1b")
                args = parser.parse_args()
                run_agent_window("{name}", args.provider, args.model)

            if __name__ == "__main__":
                main()
            """),
            encoding="utf-8",
        )
        files_written.append("run_agent.py")

        # ── 6. launch_agent.bat ──────────────────────────────────────────
        bat = export_dir / "launch_agent.bat"
        bat.write_text(
            textwrap.dedent(f"""\
            @echo off
            title Aether Agent - {name}
            color 0B
            cd /d "%~dp0"
            set PY=
            if exist "%LOCALAPPDATA%\\Programs\\Python\\Python310\\python.exe" (
                set PY="%LOCALAPPDATA%\\Programs\\Python\\Python310\\python.exe"
                goto :run
            )
            where python >nul 2>&1
            if %errorlevel%==0 ( set PY=python & goto :run )
            echo Python not found. Install from https://www.python.org/downloads/
            pause & exit /b 1
            :run
            %PY% run_agent.py %*
            pause
            """),
            encoding="utf-8",
        )
        files_written.append("launch_agent.bat")

        # ── 7. README.md ─────────────────────────────────────────────────
        readme = export_dir / "README.md"
        readme.write_text(
            textwrap.dedent(f"""\
            # Aether Agent: {name}

            **Role:** {agent.role}
            **Skills:** {', '.join(agent.profile.get('skills', []))}
            **Tools:** {', '.join(agent.profile.get('tools', []))}
            **Version:** {agent.profile.get('version', '1.0.0')}

            ## Quick Start

            1. Copy `.env.example` to `.env` and fill in your API key
            2. Double-click `launch_agent.bat`  — OR —
            3. Run: `python run_agent.py`

            ### With a specific model:
            ```
            python run_agent.py --provider ollama --model llama3.2:1b
            python run_agent.py --provider github --model claude-sonnet-4-6
            ```

            ## Install dependencies
            ```
            pip install -r requirements.txt
            ```
            """),
            encoding="utf-8",
        )
        files_written.append("README.md")

        return {"output_dir": str(export_dir), "files": files_written, "error": None}

    # ------------------------------------------------------------------
    # Direct AI chat
    # ------------------------------------------------------------------

    def chat(self, message: str, history: list[dict] | None = None) -> str:
        """Send a message directly to the underlying AI model."""
        messages = history or []
        messages.append({"role": "user", "content": message})
        response = self.ai_adapter.chat(messages=messages)
        self.memory.append(key="chat_history", value={"role": "assistant", "content": response})
        return response

    # ------------------------------------------------------------------
    # Application builder
    # ------------------------------------------------------------------

    def build_application(self, app_name: str, progress=None) -> dict:
        """
        Ask the AI to generate a complete application, parse the response
        into individual files, write them to agent_output/<app_name>/,
        and return a summary dict with keys 'output_dir' and 'files'.

        Args:
            progress: optional callable(step, total, filename, status)
                      called after each file is written.
        """
        import os, re
        from pathlib import Path
        from tools.file_writer import file_writer

        logger.info("Building application: %s", app_name)

        prompt = (
            f"You are an expert software engineer.\n"
            f"Generate a complete, working '{app_name}' application.\n"
            f"Output EVERY file using EXACTLY this format — no extra commentary outside the blocks:\n\n"
            f"=== FILE: <relative/path/filename.ext> ===\n"
            f"<full file content here>\n"
            f"=== END FILE ===\n\n"
            f"Include: all source files, a requirements.txt (if Python), "
            f"a README.md explaining how to run it, and any config files needed.\n"
            f"Make the code complete and runnable — no placeholders."
        )

        messages = [{"role": "user", "content": prompt}]
        raw = self.ai_adapter.chat(messages=messages)

        # Parse === FILE: path === ... === END FILE === blocks
        pattern = re.compile(
            r"=== FILE:\s*(.+?)\s*===\n(.*?)\n=== END FILE ===",
            re.DOTALL,
        )
        matches = pattern.findall(raw)

        output_dir = str(Path(__file__).parent.parent / "agent_output" / app_name.replace(" ", "_"))
        files_written = []

        if matches:
            total = len(matches)
            for i, (rel_path, content) in enumerate(matches, start=1):
                rel_path = rel_path.strip()
                result = file_writer(
                    filename=os.path.join(app_name.replace(" ", "_"), rel_path),
                    content=content,
                )
                files_written.append((rel_path, result))
                if progress:
                    ok = "successfully" in result
                    progress(i, total, rel_path, ok)
        else:
            # Fallback: save the raw response as a single plan file
            result = file_writer(
                filename=os.path.join(app_name.replace(" ", "_"), "plan.md"),
                content=raw,
            )
            files_written.append(("plan.md", result))
            if progress:
                progress(1, 1, "plan.md", "successfully" in result)

        self.memory.save(key=f"build:{app_name}:files", value=[f for f, _ in files_written])
        return {"output_dir": output_dir, "files": files_written, "raw": raw}
