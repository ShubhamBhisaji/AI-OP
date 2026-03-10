---
applyTo: "tools/*.py"
---

## Rules for Aether OS tool files

- The file must export exactly **one public function** named after the file (e.g. `tools/web_search.py` exports `web_search`)
- Signature: `def tool_name(input: str, ...) -> str`
- **Never raise exceptions** — catch all errors and return `"Error: <description>"` strings
- **Input validation first**: reject empty strings, non-string types, or obviously dangerous inputs (path traversal `../`, absolute paths `/`, shell metacharacters)
- All network calls must set a **timeout** (10s max)
- All subprocess calls must use `subprocess.run([...], capture_output=True, ...)` — never `shell=True`
- After writing the tool, register it in `tools/tool_manager.py > _register_builtins()`
