---
applyTo: "**/*.py"
---

## Python coding rules for AetherAi-A Master AI

- Always include `from __future__ import annotations` as the first import
- Use `logging.getLogger(__name__)` — never `print()` in library files
- Type-hint all function parameters and return values using Python 3.10+ syntax (`list[str]`, `str | None`)
- Never hardcode API keys, tokens, or credentials — read from environment variables only
- For tool functions in `tools/`, the signature must be `def tool_name(input: str, ...) -> str` and must never raise — return `"Error: ..."` strings instead
- Agents are always looked up via `AgentRegistry.get()` before use; always handle the `None` case
- When adding a new class that needs external state, pass dependencies via `__init__` (dependency injection) — no global singletons

## Code generation

- Always use Python 3.10+ syntax
- Prefer `from __future__ import annotations` as the first import
- Use `logging` not `print()` in library code
- Follow the AetherAi-A Master AI module conventions defined in `.github/copilot-instructions.md`

## Test generation

- Write tests in the style of `test_aether.py`
- Use a `StubAI` subclass of `AIAdapter` to avoid real API calls
- Use `MemoryManager(persist=False)` and `AgentRegistry(persist=False)` in all tests
- Assert both the happy path and the error/edge-case path for every function tested
