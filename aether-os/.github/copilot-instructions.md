# AetheerAI — An AI Master!! — Copilot Workspace Instructions

## Project Overview

This is **AetheerAI — An AI Master!!** — a modular AI Operating System written in Python 3.10+.
It manages AI agents like processes in an operating system.

## Architecture

```
User → AetherKernel → Agents → Tools → Result
```

**Core modules and their responsibilities:**

| Module | Path | Purpose |
|--------|------|---------|
| `AetherKernel` | `core/aether_kernel.py` | Central controller; boots all subsystems |
| `WorkflowEngine` | `core/workflow_engine.py` | Single-agent execution, multi-agent pipelines, task decomposition |
| `BaseAgent` | `agents/base_agent.py` | Foundation class: profile, skills, tools, versioning, performance |
| `AgentFactory` | `factory/agent_factory.py` | Creates agents from 8 presets or custom config dicts |
| `AgentRegistry` | `registry/agent_registry.py` | In-memory + JSON-persisted agent store |
| `SkillEngine` | `skills/skill_engine.py` | Upgrades agent skills, tracks performance, bumps versions |
| `AIAdapter` | `ai/ai_adapter.py` | Unified interface: OpenAI, Claude, Gemini, Ollama, HuggingFace |
| `ToolManager` | `tools/tool_manager.py` | Registers and dispatches tools (`web_search`, `file_writer`, `code_runner`) |
| `MemoryManager` | `memory/memory_manager.py` | Key-value store with JSON persistence and list-append |
| `CommandInterface` | `cli/command_interface.py` | Full interactive REPL for the OS |

## Coding Conventions

- **Python 3.10+** — use `match/case`, `X | Y` union types, `list[str]` generics (not `List[str]`)
- **`from __future__ import annotations`** at the top of every module
- **Type hints** on all public method signatures
- **Docstrings** on all public classes and methods
- **`logging`** module for all diagnostic output — never use `print()` in library code
- **No hardcoded API keys** — always read from environment variables or `.env`
- Tool functions (`web_search`, `file_writer`, `code_runner`) are plain callables: `fn(input: str) -> str`
- Agent config can be loaded from **JSON or YAML** via `AgentFactory.create_from_config()`

## Adding a New Tool

1. Create `tools/<tool_name>.py` with a function `def <tool_name>(input: str, ...) -> str`
2. Register it in `tools/tool_manager.py` inside `_register_builtins()`
3. Add the tool name string to any relevant presets in `factory/agent_factory.py` (`AGENT_PRESETS`)

## Adding a New Agent Preset

In `factory/agent_factory.py`, add an entry to `AGENT_PRESETS`:
```python
"my_agent": {
    "role": "My Agent Role",
    "tools": ["web_search", "file_writer"],
    "skills": ["skill_a", "skill_b"],
}
```

## Adding a New AI Provider

In `ai/ai_adapter.py`:
1. Add the provider name to `SUPPORTED_PROVIDERS`
2. Add a `_default_model()` entry
3. Implement `_chat_<provider>(self, messages, **kwargs) -> str`
4. Add the dispatch entry in `chat()`

## Key Patterns

```python
# Bootstrap without API key (for testing)
from ai.ai_adapter import AIAdapter
from registry.agent_registry import AgentRegistry
from tools.tool_manager import ToolManager
from skills.skill_engine import SkillEngine
from factory.agent_factory import AgentFactory

reg = AgentRegistry(persist=False)
tm  = ToolManager()
se  = SkillEngine(registry=reg)
fac = AgentFactory(registry=reg, tool_manager=tm, ai_adapter=ai)

# Create an agent
agent = fac.create("research_agent")

# Upgrade it
result = se.upgrade("research_agent")

# Run it
output = workflow_engine.execute(agent=agent, task="Summarize AI trends in 2026")
```

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Add your GitHub token to .env (get it at https://github.com/settings/tokens)
# GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Launch — defaults to claude-sonnet-4-6 via GitHub Models
python main.py

# Your Copilot Pro models (switch anytime from the aether> prompt):
#
#   switch_ai github claude-sonnet-4-6      (1x)  ← default, best balance
#   switch_ai github claude-opus-4-6        (3x)  most powerful
#   switch_ai github claude-haiku-4-5       (0.33x) fastest
#   switch_ai github claude-opus-4-5        (3x)
#   switch_ai github claude-sonnet-4        (1x)
#   switch_ai github gemini-3-pro           (1x, Preview)
#   switch_ai github gpt-5.4                (1x)
#   switch_ai github gpt-5.3-codex          (1x)

# Or pass model at startup:
python main.py --provider github --model claude-opus-4-6
python main.py --provider github --model gpt-5.4

# Launch with local Ollama (no token needed)
python main.py --provider ollama --model llama3

# Run full integration test suite
python test_aether.py
```

## File Naming

- New tools → `tools/<name>.py`, function named exactly `<name>`
- New agents → add preset to `factory/agent_factory.py`
- Agent output files → written to `agent_output/` by `file_writer`
- Persisted registry → `registry/registry_store.json`
- Persisted memory → `memory/memory_store.json`
