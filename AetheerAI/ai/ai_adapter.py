"""
AIAdapter — litellm-backed abstraction layer for multiple AI providers.
Supports GitHub Models (free with GitHub account), OpenAI, Claude, Gemini, and Ollama.
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
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


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

SUPPORTED_PROVIDERS = ("github", "openai", "claude", "gemini", "ollama")

# GitHub Models REST endpoint (models.inference.ai.azure.com)
# Works with any GitHub PAT — free tier, no Copilot subscription needed.
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

_PROVIDER_MODEL_ENV_KEYS: dict[str, str] = {
    "github": "GITHUB_MODEL",
    "openai": "OPENAI_MODEL",
    "claude": "ANTHROPIC_MODEL",
    "gemini": "GEMINI_MODEL",
    "ollama": "OLLAMA_MODEL",
}

_PROVIDER_API_BASE_ENV_KEYS: dict[str, str] = {
    "github": "GITHUB_MODELS_API_BASE",
    "openai": "OPENAI_API_BASE",
    "claude": "ANTHROPIC_API_BASE",
    "gemini": "GEMINI_API_BASE",
    "ollama": "OLLAMA_API_BASE",
}

# Confirmed working model IDs on the GitHub Models REST API (tested March 2026)
# NOTE: The GitHub Copilot Chat models (Claude, GPT-5.x, Gemini) listed at
# docs.github.com/en/copilot/reference/ai-models/model-comparison are only
# available through the Copilot Chat interface (VS Code etc.), NOT the REST API.
_GITHUB_MODELS = [
    # Free on all plans (multiplier: 0) — confirmed via REST API
    "gpt-4.1",          # best general-purpose, default
    "gpt-5-mini",       # GPT-5 mini — may not yet be available on REST API
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
        self.model = (model or "").strip() or self._default_model(provider)
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
        # ISSUE 7: optional EconomicGuardrails reference; set by the kernel
        # after both objects are constructed to avoid circular imports.
        self._guardrails: Any | None = None
        # WARNING-8: Limit concurrent AI requests — configurable via env var.
        # Default 10 keeps throughput high without hammering rate limits.
        # Override with AETHEERAI_ASYNC_CONCURRENCY=N to tune per deployment.
        self._semaphore = asyncio.Semaphore(
            int(os.environ.get("AETHEERAI_ASYNC_CONCURRENCY", "10"))
        )
        self._failover_enabled = _env_bool("AETHEERAI_PROVIDER_FAILOVER", True)
        self._failover_chain = self._load_failover_chain()
        self._failure_threshold = _env_int("AETHEERAI_PROVIDER_FAILURE_THRESHOLD", 2, minimum=1)
        self._failure_cooldown_seconds = _env_int(
            "AETHEERAI_PROVIDER_FAILURE_COOLDOWN_SECONDS", 45, minimum=1
        )
        self._provider_failures: dict[str, int] = {p: 0 for p in SUPPORTED_PROVIDERS}
        self._provider_open_until: dict[str, float] = {p: 0.0 for p in SUPPORTED_PROVIDERS}
        self._provider_lock = threading.Lock()
        logger.info("AIAdapter initialized: provider=%s model=%s", self.provider, self.model)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Send a list of messages to the configured AI provider and return
        the assistant's reply as a plain string.
        """
        # Pre-flight prompt injection scan (warn only, does not block).
        try:
            from security.prompt_scanner import scan_messages
            scan = scan_messages(messages)
            if not scan.safe:
                logger.warning(
                    "Prompt injection flags detected before LLM call: %s",
                    scan.flags,
                )
        except Exception:
            pass

        dispatch = {
            "github": self._chat_github,
            "openai": self._chat_openai,
            "claude": self._chat_claude,
            "gemini": self._chat_gemini,
            "ollama": self._chat_ollama,
        }
        request_id = uuid.uuid4().hex[:10]
        call_plan = self._build_provider_call_plan()
        errors: list[str] = []
        last_error: Exception | None = None

        for attempt, (provider, model_override) in enumerate(call_plan, start=1):
            if self._is_provider_circuit_open(provider):
                retry_after = self._retry_after_seconds(provider)
                logger.warning(
                    "AIAdapter circuit-open skip: request_id=%s provider=%s retry_after_s=%d",
                    request_id,
                    provider,
                    retry_after,
                )
                errors.append(f"{provider}: circuit-open ({retry_after}s)")
                continue

            started = time.monotonic()
            try:
                response = dispatch[provider](
                    messages,
                    model_override=model_override,
                    **kwargs,
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                self._mark_provider_success(provider)
                logger.info(
                    "AIAdapter request success: request_id=%s provider=%s model=%s attempt=%d/%d elapsed_ms=%d",
                    request_id,
                    provider,
                    model_override or (
                        self.model
                        if provider == self.provider
                        else self._default_model(provider)
                    ),
                    attempt,
                    len(call_plan),
                    elapsed_ms,
                )
                if provider != self.provider:
                    logger.warning(
                        "AIAdapter failover used: request_id=%s primary=%s fallback=%s",
                        request_id,
                        self.provider,
                        provider,
                    )
                return response
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = int((time.monotonic() - started) * 1000)
                self._mark_provider_failure(provider, exc)
                last_error = exc
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")
                logger.warning(
                    "AIAdapter request failed: request_id=%s provider=%s attempt=%d/%d elapsed_ms=%d error=%s",
                    request_id,
                    provider,
                    attempt,
                    len(call_plan),
                    elapsed_ms,
                    exc,
                )
                if not self._should_failover(exc):
                    logger.error(
                        "AIAdapter failover aborted: request_id=%s provider=%s reason=non-retryable",
                        request_id,
                        provider,
                    )
                    raise

        detail = " | ".join(errors) if errors else "no attempts"
        raise RuntimeError(
            f"AI providers unavailable for request {request_id}. Attempts: {detail}"
        ) from last_error

    async def async_chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Async wrapper for chat() — runs the blocking call in a thread pool
        so the asyncio event loop is never blocked by a slow network request.
        Rate-limited to 3 concurrent requests via _semaphore to prevent 429 errors
        when asyncio.gather() fans out many subtasks simultaneously (Bug 1 fix).
        (Fix 2 — Asynchronous Execution)
        """
        loop = asyncio.get_running_loop()
        async with self._semaphore:
            return await loop.run_in_executor(None, lambda: self.chat(messages, **kwargs))

    def switch(self, provider: str, model: str | None = None) -> None:
        """Hot-swap to a different AI provider without recreating the adapter."""
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        self.provider = provider
        self.model = (model or "").strip() or self._default_model(provider)
        logger.info("AIAdapter switched: provider=%s model=%s", self.provider, self.model)

    def provider_health(self) -> dict[str, dict[str, Any]]:
        """Return provider failure and circuit-breaker state for troubleshooting."""
        now = time.monotonic()
        with self._provider_lock:
            return {
                provider: {
                    "failures": self._provider_failures.get(provider, 0),
                    "circuit_open": self._provider_open_until.get(provider, 0.0) > now,
                    "retry_after_seconds": max(
                        0,
                        int(self._provider_open_until.get(provider, 0.0) - now),
                    ),
                }
                for provider in SUPPORTED_PROVIDERS
            }

    def _build_provider_call_plan(self) -> list[tuple[str, str | None]]:
        plan: list[tuple[str, str | None]] = [(self.provider, None)]
        if not self._failover_enabled:
            return plan

        for provider in self._failover_chain:
            if provider == self.provider:
                continue
            if provider not in SUPPORTED_PROVIDERS:
                continue
            if not self._provider_has_required_credentials(provider):
                continue
            plan.append((provider, self._default_model(provider)))

        return plan

    def _is_provider_circuit_open(self, provider: str) -> bool:
        with self._provider_lock:
            return self._provider_open_until.get(provider, 0.0) > time.monotonic()

    def _retry_after_seconds(self, provider: str) -> int:
        with self._provider_lock:
            return max(
                0,
                int(self._provider_open_until.get(provider, 0.0) - time.monotonic()),
            )

    def _mark_provider_success(self, provider: str) -> None:
        with self._provider_lock:
            self._provider_failures[provider] = 0
            self._provider_open_until[provider] = 0.0

    def _mark_provider_failure(self, provider: str, error: Exception) -> None:
        with self._provider_lock:
            failures = self._provider_failures.get(provider, 0) + 1
            self._provider_failures[provider] = failures
            if failures >= self._failure_threshold:
                self._provider_open_until[provider] = (
                    time.monotonic() + self._failure_cooldown_seconds
                )
                logger.warning(
                    "AIAdapter circuit opened: provider=%s failures=%d cooldown_s=%d reason=%s",
                    provider,
                    failures,
                    self._failure_cooldown_seconds,
                    error,
                )

    @staticmethod
    def _should_failover(exc: Exception) -> bool:
        if isinstance(exc, (TypeError, AttributeError, KeyError, AssertionError)):
            return False

        if isinstance(exc, (OSError, RuntimeError, ImportError, ConnectionError, TimeoutError)):
            return True

        name = type(exc).__name__.lower()
        return any(
            token in name
            for token in (
                "timeout",
                "rate",
                "api",
                "request",
                "network",
                "connection",
                "auth",
            )
        )

    @staticmethod
    def _provider_has_required_credentials(provider: str) -> bool:
        required_env = {
            "github": "GITHUB_TOKEN",
            "openai": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        env_name = required_env.get(provider)
        if not env_name:
            return True
        return bool((os.environ.get(env_name) or "").strip())

    @staticmethod
    def _load_failover_chain() -> tuple[str, ...]:
        default_chain = ("ollama", "github", "openai", "claude", "gemini")
        raw = (os.environ.get("AETHEERAI_PROVIDER_FAILOVER_CHAIN") or "").strip().lower()
        if not raw:
            return default_chain

        parsed = [p.strip() for p in raw.split(",") if p.strip()]
        cleaned = [p for p in parsed if p in SUPPORTED_PROVIDERS]
        unique = tuple(dict.fromkeys(cleaned))
        return unique or default_chain

    # ------------------------------------------------------------------
    # litellm core call + token tracking
    # ------------------------------------------------------------------

    _MAX_TOKENS_PER_CALL: int = max(1, int(os.getenv("AETHEER_MAX_TOKENS_PER_CALL", "16384") or "16384"))

    def _call(self, model: str, messages: list[dict], **kwargs) -> str:
        """Route a completion request through litellm and capture token usage."""
        litellm = _litellm()
        litellm.suppress_debug_info = True
        litellm.drop_params = True
        if "max_tokens" not in kwargs:
            kwargs["max_tokens"] = self._MAX_TOKENS_PER_CALL
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
            # ISSUE 7: feed token consumption into EconomicGuardrails
            if tt and self._guardrails is not None:
                try:
                    self._guardrails.record_usage(
                        category="api_call",
                        cost_usd=0.0,
                        tokens=tt,
                    )
                except Exception:  # never let budget accounting crash inference
                    pass
            if tt:
                logger.info(
                    "Token usage — prompt: %d, completion: %d, total: %d (session: %d)",
                    pt, ct, tt, self._session_usage["total_tokens"],
                )
        raw_content = response.choices[0].message.content or ""
        try:
            from security.output_redactor import redact_credentials
            return redact_credentials(raw_content)
        except Exception:
            return raw_content

    # Fallback model list iterated when the primary GitHub model returns an
    # "unknown model" error — tries each candidate in order until one succeeds.
    _GITHUB_FALLBACK_MODELS: list[str] = [
        "gpt-4.1", "gpt-5-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini",
    ]

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _chat_github(
        self,
        messages: list[dict],
        *,
        model_override: str | None = None,
        **kwargs,
    ) -> str:
        """GitHub Models — free AI via GitHub PAT. litellm routes as openai-compatible."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN not set.\n"
                "Get a free token at https://github.com/settings/tokens\n"
                "Then add GITHUB_TOKEN=<token> to your .env file."
            )
        litellm = _litellm()
        call_kwargs = dict(kwargs)
        call_kwargs.setdefault(
            "base_url",
            self._provider_api_base("github") or _GITHUB_MODELS_ENDPOINT,
        )
        # Walk the fallback list; on unknown-model errors try the next candidate.
        tried: set[str] = set()
        selected_model = (model_override or self.model).strip() or self._default_model("github")
        for model_name in dict.fromkeys([selected_model] + self._GITHUB_FALLBACK_MODELS):
            tried.add(model_name)
            try:
                result = self._call(
                    model=f"openai/{model_name}",
                    messages=messages,
                    api_key=token,
                    num_retries=3,
                    **call_kwargs,
                )
                if model_name != selected_model and model_override is None:
                    logger.info(
                        "GitHub Models: '%s' unavailable, switched to '%s'",
                        selected_model,
                        model_name,
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
        model_override = kwargs.pop("model_override", None)
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY environment variable not set.")
        call_kwargs = dict(kwargs)
        api_base = self._provider_api_base("openai")
        if api_base:
            call_kwargs.setdefault("api_base", api_base)
        return self._call(
            model=(model_override or self.model),
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **call_kwargs,
        )

    def _chat_claude(self, messages: list[dict], **kwargs) -> str:
        model_override = kwargs.pop("model_override", None)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set.")
        # litellm auto-detects Anthropic from the "claude-" prefix; add it if missing
        selected_model = model_override or self.model
        model = selected_model if selected_model.startswith("claude") else f"anthropic/{selected_model}"
        call_kwargs = dict(kwargs)
        api_base = self._provider_api_base("claude")
        if api_base:
            call_kwargs.setdefault("api_base", api_base)
        return self._call(
            model=model,
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **call_kwargs,
        )

    def _chat_gemini(self, messages: list[dict], **kwargs) -> str:
        model_override = kwargs.pop("model_override", None)
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not set.\n"
                "Get a free key at https://aistudio.google.com/apikey\n"
                "Then add GEMINI_API_KEY=<key> to your .env file."
            )
        selected_model = model_override or self.model
        model = (
            selected_model
            if selected_model.startswith("gemini/")
            else f"gemini/{selected_model}"
        )
        call_kwargs = dict(kwargs)
        api_base = self._provider_api_base("gemini")
        if api_base:
            call_kwargs.setdefault("api_base", api_base)
        return self._call(
            model=model,
            messages=messages,
            api_key=api_key,
            num_retries=3,
            **call_kwargs,
        )

    def _chat_ollama(self, messages: list[dict], **kwargs) -> str:
        model_override = kwargs.pop("model_override", None)
        selected_model = model_override or self.model
        model = selected_model if selected_model.startswith("ollama/") else f"ollama/{selected_model}"
        call_kwargs = dict(kwargs)
        api_base = self._provider_api_base("ollama")
        if api_base:
            call_kwargs.setdefault("api_base", api_base)
        return self._call(model=model, messages=messages, **call_kwargs)

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
    def _provider_api_base(provider: str) -> str | None:
        env_key = _PROVIDER_API_BASE_ENV_KEYS.get(provider)
        if not env_key:
            return None
        value = (os.environ.get(env_key) or "").strip()
        return value or None

    @staticmethod
    def _default_model(provider: str) -> str:
        env_key = _PROVIDER_MODEL_ENV_KEYS.get(provider)
        if env_key:
            env_model = (os.environ.get(env_key) or "").strip()
            if env_model:
                return env_model

        default_provider = (
            (os.environ.get("AETHEERAI_DEFAULT_PROVIDER") or "").strip().lower()
            or (os.environ.get("AI_PROVIDER") or "").strip().lower()
        )
        if provider == default_provider:
            shared_model = (
                (os.environ.get("AETHEERAI_DEFAULT_MODEL") or "").strip()
                or (os.environ.get("AI_MODEL") or "").strip()
            )
            if shared_model:
                return shared_model

        defaults = {
            "github": "gpt-4.1",              # best free-tier model on GitHub Models REST API
            "openai": "gpt-4o",
            "claude": "claude-sonnet-4.6",
            "gemini": "gemini-2.5-flash-lite",
            "ollama": "qwen2.5-coder:7b",    # top-rated local model for agentic coding
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


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE_VALUES


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; using default=%d",
            name,
            raw,
            default,
        )
        return max(minimum, default)
