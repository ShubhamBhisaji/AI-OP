"""
AIAdapter — Abstraction layer for multiple AI providers.
Supports GitHub Models (free with GitHub account), OpenAI, Claude, Gemini, Ollama, HuggingFace.
Switch providers by changing the `provider` argument at init time.

Quickest start (no paid API key needed):
    1. Go to https://github.com/settings/tokens → Generate new token (classic)
       No special scopes needed — just click Generate.
    2. Set GITHUB_TOKEN=<your_token> in your .env file
    3. Run: python main.py --provider github
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("github", "openai", "claude", "gemini", "ollama", "huggingface")

# GitHub Models REST endpoint (models.inference.ai.azure.com)
# Works with any GitHub PAT — free tier, no Copilot subscription needed.
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Confirmed working model IDs on the GitHub Models REST API (tested March 2026)
# NOTE: The GitHub Copilot Chat models (Claude, GPT-5.x, Gemini) listed at
# docs.github.com/en/copilot/reference/ai-models/model-comparison are only
# available through the Copilot Chat interface (VS Code etc.), NOT the REST API.
_GITHUB_MODELS = [
    # Free on all plans (multiplier: 0) — confirmed via REST API
    "gpt-4.1",          # best general-purpose, default
    "gpt-5-mini",       # GPT-5 mini — free tier, fast
    "gpt-4o",           # reliable baseline
    "gpt-4o-mini",      # fastest / cheapest
    "gpt-4.1-mini",     # lighter gpt-4.1 variant
]


class AIAdapter:
    """
    Unified interface to multiple AI model providers.

    Usage:
        adapter = AIAdapter(provider="openai", model="gpt-4o")
        response = adapter.chat([{"role": "user", "content": "Hello!"}])

    Token tracking (Fix 4)
    ----------------------
    After every OpenAI-compatible call, token usage is captured and stored
    on the instance.  Access via `adapter.usage` or `adapter.total_tokens`.
    Running totals are also accumulated across all calls in the session.
    """

    def __init__(self, provider: str = "github", model: str | None = None):
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{provider}'. Choose from: {SUPPORTED_PROVIDERS}"
            )
        self.provider = provider
        self.model = model or self._default_model(provider)
        # ── Token tracking (Fix 4) ────────────────────────────────────
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._session_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        logger.info("AIAdapter initialized: provider=%s model=%s", self.provider, self.model)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Send a list of messages to the configured AI provider and return
        the assistant's reply as a plain string.
        """
        dispatch = {
            "github": self._chat_github,
            "openai": self._chat_openai,
            "claude": self._chat_claude,
            "gemini": self._chat_gemini,
            "ollama": self._chat_ollama,
            "huggingface": self._chat_huggingface,
        }
        return dispatch[self.provider](messages, **kwargs)

    async def async_chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Async wrapper for chat() — runs the blocking call in a thread pool
        so the asyncio event loop is never blocked by a slow network request.
        (Fix 2 — Asynchronous Execution)
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.chat(messages, **kwargs))

    def switch(self, provider: str, model: str | None = None) -> None:
        """Hot-swap to a different AI provider without recreating the adapter."""
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        self.provider = provider
        self.model = model or self._default_model(provider)
        logger.info("AIAdapter switched: provider=%s model=%s", self.provider, self.model)

    # ------------------------------------------------------------------
    # Shared OpenAI-compatible REST helper (no SDK)
    # ------------------------------------------------------------------

    def _openai_compat_chat(
        self,
        endpoint: str,
        api_key: str,
        messages: list[dict],
        **kwargs,
    ) -> str:
        """POST to any OpenAI-compatible /chat/completions endpoint using stdlib urllib.
        Auto-retries with gpt-4o if the configured model is not available on the endpoint.
        """
        import json as _json
        import urllib.request
        import urllib.error

        # GitHub Models fallback order — confirmed working with standard PAT
        _GITHUB_FALLBACKS = [
            "gpt-4.1",      # best general-purpose, free tier
            "gpt-5-mini",   # GPT-5 mini, free tier
            "gpt-4o",       # reliable baseline
            "gpt-4o-mini",  # lightest option
            "gpt-4.1-mini",
        ]

        def _do_request(model_name: str) -> str:
            payload: dict = {"model": model_name, "messages": messages}
            for k, v in kwargs.items():
                if k == "stream":
                    continue
                payload[k] = v
            body = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = _json.loads(resp.read().decode("utf-8"))

            # ── Fix 4: capture token usage ────────────────────────────
            raw_usage = data.get("usage") or {}
            pt  = int(raw_usage.get("prompt_tokens",     0))
            ct  = int(raw_usage.get("completion_tokens", 0))
            tt  = int(raw_usage.get("total_tokens",      pt + ct))
            self.usage = {
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": tt,
            }
            self._session_usage["prompt_tokens"]     += pt
            self._session_usage["completion_tokens"] += ct
            self._session_usage["total_tokens"]      += tt
            if tt:
                logger.info(
                    "Token usage — prompt: %d, completion: %d, total: %d "
                    "(session total: %d)",
                    pt, ct, tt, self._session_usage["total_tokens"],
                )

            return data["choices"][0]["message"]["content"] or ""

        # First attempt with the currently configured model
        import time as _time
        _MAX_RATE_RETRIES = 3
        _rate_attempt = 0

        while True:
            try:
                return _do_request(self.model)
            except urllib.error.HTTPError as exc:
                try:
                    detail = _json.loads(exc.read().decode("utf-8"))
                except Exception:
                    detail = {}
                err_code = detail.get("error", {}).get("code", "")
                err_msg  = detail.get("error", {}).get("message", str(exc))

                # Auto-wait and retry on 429 rate limit (up to 3 times)
                if exc.code == 429:
                    _rate_attempt += 1
                    if _rate_attempt <= _MAX_RATE_RETRIES:
                        # Try to read Retry-After header, else default 65s
                        _wait = 65
                        try:
                            _wait = int(exc.headers.get("Retry-After", 65)) + 2
                        except Exception:
                            pass
                        print(f"\n  ⏳ Rate limit hit — waiting {_wait}s before retry "
                              f"({_rate_attempt}/{_MAX_RATE_RETRIES})...")
                        _time.sleep(_wait)
                        continue  # retry the while loop
                    raise RuntimeError(
                        f"API error (429): {err_msg} — rate limit persists after "
                        f"{_MAX_RATE_RETRIES} retries."
                    ) from exc

                # If model not found, walk the fallback list and retry
                if exc.code == 400 and err_code == "unknown_model":
                    tried = {self.model}
                    for fallback in _GITHUB_FALLBACKS:
                        if fallback in tried:
                            continue
                        tried.add(fallback)
                        try:
                            result = _do_request(fallback)
                            # Persist the working model so future calls use it directly
                            import logging as _log
                            _log.getLogger(__name__).info(
                                "Model '%s' not available, switched to '%s'",
                                self.model, fallback
                            )
                            self.model = fallback
                            return result
                        except urllib.error.HTTPError:
                            continue
                    raise RuntimeError(
                        f"API error ({exc.code}): {err_msg} "
                        f"(tried: {', '.join(tried)})"
                    ) from exc

                raise RuntimeError(f"API error ({exc.code}): {err_msg}") from exc
            except Exception as exc:
                raise RuntimeError(f"API error: {exc}") from exc

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _chat_github(self, messages: list[dict], **kwargs) -> str:
        """
        GitHub Models — free AI access using a GitHub Personal Access Token.
        Uses stdlib urllib — no openai SDK required.
        Get your free token at: https://github.com/settings/tokens
        """
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN not set.\n"
                "Get a free token at https://github.com/settings/tokens\n"
                "Then add GITHUB_TOKEN=<token> to your .env file."
            )
        return self._openai_compat_chat(
            endpoint=f"{_GITHUB_MODELS_ENDPOINT}/chat/completions",
            api_key=token,
            messages=messages,
            **kwargs,
        )

    def _chat_openai(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY environment variable not set.")
        return self._openai_compat_chat(
            endpoint="https://api.openai.com/v1/chat/completions",
            api_key=api_key,
            messages=messages,
            **kwargs,
        )

    def _chat_claude(self, messages: list[dict], **kwargs) -> str:
        try:
            import anthropic  # type: ignore
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set.")
        client = anthropic.Anthropic(api_key=api_key)
        # Anthropic separates system from user messages
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_messages = [m for m in messages if m["role"] != "system"]
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_msg,
            messages=user_messages,
            **kwargs,
        )
        return response.content[0].text if response.content else ""

    def _chat_gemini(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not set.\n"
                "Get a free key at https://aistudio.google.com/apikey\n"
                "Then add GEMINI_API_KEY=<key> to your .env file."
            )

        # Convert messages → Gemini REST format
        # {"contents": [{"role": "user"|"model", "parts": [{"text": "..."}]}]}
        contents = []
        system_instruction: str | None = None
        for m in messages:
            role = m["role"]
            if role == "system":
                system_instruction = m["content"]
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": m["content"]}]})

        payload: dict = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        # Direct REST API using stdlib urllib — no extra packages needed.
        # POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=KEY
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )

        import json as _json
        import urllib.request
        import urllib.error

        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as exc:
            try:
                detail = _json.loads(exc.read().decode("utf-8"))
                msg = detail.get("error", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise RuntimeError(f"Gemini API error ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

    def _chat_ollama(self, messages: list[dict], **kwargs) -> str:
        try:
            import ollama  # type: ignore
        except ImportError:
            raise ImportError("Install ollama: pip install ollama")
        response = ollama.chat(model=self.model, messages=messages)
        return response["message"]["content"] or ""

    def _chat_huggingface(self, messages: list[dict], **kwargs) -> str:
        try:
            from huggingface_hub import InferenceClient  # type: ignore
        except ImportError:
            raise ImportError("Install huggingface-hub: pip install huggingface-hub")
        api_key = os.environ.get("HF_API_KEY")
        client = InferenceClient(model=self.model, token=api_key)
        prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        result = client.text_generation(prompt, max_new_tokens=1024)
        return result or ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        """Running total of tokens consumed in this session."""
        return self._session_usage["total_tokens"]

    def session_usage_summary(self) -> dict[str, int]:
        """Return a copy of the accumulated token counts for this session."""
        return dict(self._session_usage)

    def reset_session_usage(self) -> None:
        """Reset the session token counters to zero."""
        self._session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    @staticmethod
    def _default_model(provider: str) -> str:
        defaults = {
            "github": "gpt-4.1",              # best free-tier model on GitHub Models REST API
            "openai": "gpt-4o",
            "claude": "claude-sonnet-4.6",
            "gemini": "gemini-2.5-flash-lite",
            "ollama": "qwen2.5-coder:7b",    # top-rated local model for agentic coding
            "huggingface": "mistralai/Mistral-7B-Instruct-v0.2",
        }
        return defaults.get(provider, "unknown")

    # Recommended Ollama models (shown in setup wizards)
    OLLAMA_RECOMMENDED = [
        ("qwen2.5-coder:7b",       "Qwen2.5-Coder 7B   — best for code/agents (8GB VRAM)"),
        ("qwen2.5-coder:14b",      "Qwen2.5-Coder 14B  — higher quality (12GB VRAM)"),
        ("qwen2.5-coder:32b",      "Qwen2.5-Coder 32B  — top code quality (20GB+ VRAM)"),
        ("deepseek-coder-v2:16b",  "DeepSeek-Coder-V2 16B — Python/JS/agents (16GB VRAM)"),
        ("qwen3:30b",              "Qwen3 30B  — 128k ctx, advanced tool calling (20GB+ VRAM)"),
        ("minimax-m2",             "MiniMax-M2 — 1M context, state-of-art agentic (high VRAM)"),
        ("llama3.3:70b",           "Llama 3.3 70B — general purpose, 128k ctx (40GB+ VRAM)"),
        ("wizardlm2:7b",           "WizardLM2 7B — fast, low-resource (8GB VRAM)"),
        ("llama3.2:3b",            "Llama 3.2 3B  — ultra-fast, minimal hardware (4GB VRAM)"),
    ]
