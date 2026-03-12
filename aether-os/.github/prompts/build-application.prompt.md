---
description: "Build a complete application using Aether agents. Use when: build app, generate application, create project, scaffold application"
---

Build a complete `${appType}` application using the AetherAi-A Master AI agent team.

## Plan

Use the following AetherAi-A Master AI agents in a pipeline to produce a full working application:

1. **research_agent** — Research best practices, libraries, and architecture for a `${appType}`
2. **coding_agent** — Scaffold all source files, modules, and boilerplate
3. **automation_agent** — Write setup scripts, CI configuration, and Makefile/task runner
4. **marketing_agent** (optional) — Write a README.md with project description, badges, and usage guide

## Output

Generate every file via the `file_writer` tool, writing to `agent_output/${appType}/`:

- `main.py` or entry point
- All module files
- `requirements.txt`
- `README.md`
- `.env.example`
- Any config files (e.g. `pyproject.toml`, `Dockerfile`, `.github/workflows/ci.yml`)

## Requirements

- Follow Python 3.10+ best practices
- Include type hints and docstrings on all public functions
- Add basic error handling at system boundaries (user input, external APIs)
- Include a simple test file `test_${appType}.py`
- Do NOT use placeholder comments like `# TODO` — write real, working code

After generating all files, provide a brief summary of the architecture and how to run the app.
