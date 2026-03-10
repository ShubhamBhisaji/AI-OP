---
applyTo: "ai/ai_adapter.py"
---

## Rules for AIAdapter

- `SUPPORTED_PROVIDERS` is the single source of truth for valid provider names
- Every provider implementation must:
  1. Wrap the SDK import in `try/except ImportError` with a clear `pip install ...` message
  2. Read the API key from `os.environ` — raise `EnvironmentError` if missing
  3. Return the assistant reply as a plain `str` — never return `None`
- The `chat()` dispatch dict must stay in sync with `SUPPORTED_PROVIDERS`
- The `_default_model()` static method must have an entry for every provider
- `switch()` must validate the provider name against `SUPPORTED_PROVIDERS` before mutating state
