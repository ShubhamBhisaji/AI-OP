---
description: "Create a new AetheerAI — An AI Master!! tool. Use when: adding a tool, new tool, create tool, build tool for agent"
---

Create a new AetheerAI — An AI Master!! tool called `${toolName}`.

## Requirements

1. Create the file `tools/${toolName}.py` with:
   - A module docstring explaining what the tool does
   - A single public function `def ${toolName}(input: str, ...) -> str` that agents can call
   - Input validation (reject empty/non-string inputs)
   - `try/except` for all external calls (network, filesystem, subprocess)
   - A clear string return value — either the result or an `"Error: ..."` message
   - `logging` for diagnostics (no `print()`)
   - Security guards against path traversal, shell injection, or SSRF as appropriate

2. Register it in `tools/tool_manager.py`:
   - Import the function inside `_register_builtins()`
   - Call `self.register("${toolName}", ${toolName})`

3. Add `"${toolName}"` to any relevant agent presets in `factory/agent_factory.py > AGENT_PRESETS`

4. Add a test case for it in `test_aether.py` following the existing pattern (direct function call, assert result is a string, test the error path)

Follow the conventions in `.github/copilot-instructions.md`.
