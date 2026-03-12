---
description: "Add a new AI provider to AetheerAI — An AI Master!! AIAdapter. Use when: new AI provider, add model, integrate LLM, add provider"
---

Add a new AI provider called `${providerName}` to the AetheerAI — An AI Master!! `AIAdapter`.

## Requirements

1. **`ai/ai_adapter.py`** — make these changes:
   - Add `"${providerName}"` to the `SUPPORTED_PROVIDERS` tuple
   - Add a default model entry in `_default_model()`:
     ```python
     "${providerName}": "${defaultModel}",
     ```
   - Implement the method:
     ```python
     def _chat_${providerName}(self, messages: list[dict], **kwargs) -> str:
     ```
     - Use `try/except ImportError` with a helpful pip install message
     - Read the API key from an environment variable (never hardcode)
     - Raise `EnvironmentError` if the key is missing
     - Return the assistant response as a plain `str`
   - Add the dispatch entry in `chat()`:
     ```python
     "${providerName}": self._chat_${providerName},
     ```

2. **`.env.example`** — add the new API key variable with a placeholder comment

3. **`requirements.txt`** — add the provider's Python package

4. **`test_aether.py`** — verify the adapter switches correctly:
   ```python
   ai.switch("${providerName}")
   assert ai.provider == "${providerName}"
   assert ai.model == "<expected_default>"
   ```

Follow the conventions in `.github/copilot-instructions.md`.
