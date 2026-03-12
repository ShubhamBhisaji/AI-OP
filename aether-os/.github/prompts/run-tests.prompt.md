---
description: "Run and fix AetheerAI — An AI Master!! tests. Use when: run tests, fix tests, test failing, debug test, something broken"
---

Run the AetheerAI — An AI Master!! full integration test suite and fix any failures.

## Steps

1. **Run the tests**:
   ```bash
   python test_aether.py
   ```

2. **For each failure**, read the relevant source file and:
   - Identify whether it's an import error, logic error, or assertion failure
   - Fix the root cause in the source — do NOT change assertions to make tests pass artificially
   - Re-run after each fix to verify

3. **Common failure patterns** in this project:
   - New tool added to a preset but not registered in `ToolManager._register_builtins()` → register it
   - `AgentRegistry` count assertion failing → update the count in the test for newly added presets
   - `SkillEngine._UPGRADE_MAP` missing a keyword for a new agent role → add the keyword mapping
   - Import error from a new module → check `sys.path` includes the workspace root

4. After all tests pass (exit code 0), confirm with a summary of what was fixed.

Follow the conventions in `.github/copilot-instructions.md`.
