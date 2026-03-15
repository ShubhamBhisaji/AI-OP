"""
AIAdapter — litellm-backed abstraction layer for multiple AI providers.
Supports GitHub Models (free with GitHub account), OpenAI, Claude, Gemini, Ollama, HuggingFace.
Switch providers by changing the `provider` argument at init time.

LiteLLM handles streaming, structured outputs, retries, and rate limiting uniformly
across all providers — no manual urllib or per-SDK HTTP plumbing needed.

Quickest start (no paid API key needed):
    1. Go to https://github.com/settings/tokens → Generate new token (classic)
       No special scopes needed — just click Generate.
    2. Set GITHUB_TOKEN=<your_token> in your .env file
    3. Run: python main.py --provider github
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _litellm():
    """Lazy import of litellm — avoids import-time failure when not installed."""
    try:
        import litellm as _ll  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "litellm is required to make AI calls.\n"
            "Install it with: pip install litellm"
        ) from exc
    return _ll

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
        # Limit concurrent AI requests to 3 — prevents HTTP 429 rate-limit blowouts
        # when many async subtasks launch simultaneously (Bug 1 fix)
        self._semaphore = asyncio.Semaphore(3)
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
        Rate-limited to 3 concurrent requests via _semaphore to prevent 429 errors
        when asyncio.gather() fans out many subtasks simultaneously (Bug 1 fix).
        (Fix 2 — Asynchronous Execution)
        """
        loop = asyncio.get_event_loop()
        async with self._semaphore:
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
    # litellm core call + token tracking
    # ------------------------------------------------------------------

    def _call(self, model: str, messages: list[dict], **kwargs) -> str:
        """Route a completion request through litellm and capture token usage."""
        litellm = _litellm()
        litellm.suppress_debug_info = True
        litellm.drop_params = True
        response = litellm.completion(model=model, messages=messages, **kwargs)
        usage = getattr(response, "usage", None)
        if usage:
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", pt + ct) or (pt + ct))
            self.usage = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}
            self._session_usage["prompt_tokens"] += pt
            self._session_usage["completion_tokens"] += ct
            self._session_usage["total_tokens"] += tt
            if tt:
                logger.info(
                    "Token usage — prompt: %d, completion: %d, total: %d (session: %d)",
                    pt, ct, tt, self._session_usage["total_tokens"],
                )
        return response.choices[0].message.content or ""

    # Kept for internal fallback iteration only
    _GITHUB_FALLBACK_MODELS: list[str] = [
        "gpt-4.1", "gpt-5-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini",
    ]

    # placeholder so the old deletion boundary is easy to find
    def _openai_compat_chat(self, *_a, **_kw):  # type: ignore[override]
        raise NotImplementedError("_openai_compat_chat replaced by litellm backends")  # noqa

    _GITHUB_FALLBACKS: list[str] = []  # kept to avoid AttributeError on any stale references

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _chat_github(self, messages: list[dict], **kwargs) -> str:
        """GitHub Models — free AI via GitHub PAT. litellm routes as openai-compatible."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN not set.\n"
                "Get a free token at https://github.com/settings/tokens\n"
                "Then add GITHUB_TOKEN=<token> to your .env file."
            )
        litellm = _litellm()
        # Walk the fallback list; on unknown-model errors try the next candidate.
        tried: set[str] = set()
        for model_name in dict.fromkeys([self.model] + self._GITHUB_FALLBACK_MODELS):
            tried.add(model_name)
            try:
                result = self._call(
                    model=f"openai/{model_name}",
                    messages=messages,
                    base_url=_GITHUB_MODELS_ENDPOINT,
                    api_key=token,
                    num_retries=3,
                    **kwargs,
                )
                if model_name != self.model:
                    logger.info(
                        "GitHub Models: '%s' unavailable, switched to '%s'",
                        self.model, model_name,
                    )
                    self.model = model_name
                return result
            except (litellm.BadRequestError, litellm.NotFoundError) as exc:
                msg = str(exc).lower()
                if any(k in msg for k in ("unknown_model", "model_not_found", "not found", "invalid model")):
                    continue  # try next fallback
                raise RuntimeError(f"GitHub Models error: {exc}") from exc
        raise RuntimeError(
            f"GitHub Models: all models exhausted (tried: {', '.join(tried)})"
        )

    def _chat_openai(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY environment variable not set.")
        return self._call(
            model=self.model,
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **kwargs,
        )

    def _chat_claude(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set.")
        # litellm auto-detects Anthropic from the "claude-" prefix; add it if missing
        model = self.model if self.model.startswith("claude") else f"anthropic/{self.model}"
        return self._call(
            model=model,
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **kwargs,
        )

    def _chat_gemini(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not set.\n"
                "Get a free key at https://aistudio.google.com/apikey\n"
                "Then add GEMINI_API_KEY=<key> to your .env file."
            )
        model = self.model if self.model.startswith("gemini/") else f"gemini/{self.model}"
        return self._call(
            model=model,
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **kwargs,
        )

    def _chat_ollama(self, messages: list[dict], **kwargs) -> str:
        model = self.model if self.model.startswith("ollama/") else f"ollama/{self.model}"
        return self._call(model=model, messages=messages, **kwargs)

    def _chat_huggingface(self, messages: list[dict], **kwargs) -> str:
        api_key = os.environ.get("HF_API_KEY")
        model = (
            self.model if self.model.startswith("huggingface/")
            else f"huggingface/{self.model}"
        )
        return self._call(model=model, messages=messages, api_key=api_key, **kwargs)

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
