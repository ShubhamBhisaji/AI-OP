---
description: "Create a new AetherAi-A Master AI agent type. Use when: new agent, create agent, add agent preset, build agent"
---

Create a new AetherAi-A Master AI agent preset called `${agentName}`.

## Requirements

1. **Add the preset** to `factory/agent_factory.py` inside `AGENT_PRESETS`:
```python
"${agentName}": {
    "role": "${agentRole}",
    "tools": [/* list relevant tool names */],
    "skills": [/* list 3-5 specific skill strings */],
}
```

2. **Add upgrade skills** to `skills/skill_engine.py` inside `_UPGRADE_MAP`:
   - Add a keyword from the role name mapped to a list of advanced skills unlocked on upgrade

3. **Verify tools exist** — all tool names in the preset must be registered in `tools/tool_manager.py`. If a required tool does not exist, create it using the `create-tool` prompt or scaffold a placeholder.

4. **Test it** — add a test in `test_aether.py`:
   ```python
   agent = fac.create("${agentName}")
   assert agent.role == "${agentRole}"
   upgrade = se.upgrade("${agentName}")
   assert len(upgrade["skills_added"]) > 0
   ```

Follow the conventions in `.github/copilot-instructions.md`. Use `from __future__ import annotations` and type hints on all methods.
