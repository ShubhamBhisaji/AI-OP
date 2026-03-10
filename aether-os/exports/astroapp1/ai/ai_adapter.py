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

# GitHub Models endpoint — free with any GitHub account, higher limits with Copilot Pro
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Models available via GitHub token (Copilot Pro — as shown in VS Code model picker)
_GITHUB_MODELS = [
    # OpenAI
    "gpt-5.4",
    "gpt-5.3-codex",
    # Anthropic
    "claude-opus-4-6",
    "claude-sonnet-4-6",        # default — best balance of speed & quality
    "claude-opus-4-5",
    "claude-sonnet-4",
    "claude-haiku-4-5",
    # Google
    "gemini-3-pro",
]


class AIAdapter:
    """
    Unified interface to multiple AI model providers.

    Usage:
        adapter = AIAdapter(provider="openai", model="gpt-4o")
        response = adapter.chat([{"role": "user", "content": "Hello!"}])
    """

    def __init__(self, provider: str = "github", model: str | None = None):
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{provider}'. Choose from: {SUPPORTED_PROVIDERS}"
            )
        self.provider = provider
        self.model = model or self._default_model(provider)
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

    def switch(self, provider: str, model: str | None = None) -> None:
        """Hot-swap to a different AI provider without recreating the adapter."""
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        self.provider = provider
        self.model = model or self._default_model(provider)
        logger.info("AIAdapter switched: provider=%s model=%s", self.provider, self.model)

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _chat_github(self, messages: list[dict], **kwargs) -> str:
        """
        GitHub Models — free AI access using a GitHub Personal Access Token.
        Supports: gpt-4o, gpt-4o-mini, Meta-Llama-3.1-70B-Instruct,
                  Phi-3.5-MoE-instruct, Mistral-large, Cohere-command-r+, and more.
        Get your free token at: https://github.com/settings/tokens
        """
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            raise ImportError("Install openai: pip install openai")
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN not set.\n"
                "Get a free token at https://github.com/settings/tokens\n"
                "Then add GITHUB_TOKEN=<token> to your .env file."
            )
        client = OpenAI(
            base_url=_GITHUB_MODELS_ENDPOINT,
            api_key=token,
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def _chat_openai(self, messages: list[dict], **kwargs) -> str:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            raise ImportError("Install openai: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY environment variable not set.")
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

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
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError:
            raise ImportError("Install google-generativeai: pip install google-generativeai")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.model)
        # Flatten messages to a single prompt for simplicity
        prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        response = model.generate_content(prompt)
        return response.text or ""

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

    @staticmethod
    def _default_model(provider: str) -> str:
        defaults = {
            "github": "claude-sonnet-4-6",   # best balance — 1x rate, Copilot Pro
            "openai": "gpt-4o",
            "claude": "claude-sonnet-4-6",
            "gemini": "gemini-1.5-pro",
            "ollama": "llama3",
            "huggingface": "mistralai/Mistral-7B-Instruct-v0.2",
        }
        return defaults.get(provider, "unknown")
