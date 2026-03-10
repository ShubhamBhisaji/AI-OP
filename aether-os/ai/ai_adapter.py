"""
AIAdapter — Abstraction layer for multiple AI providers.
Supports OpenAI, Anthropic Claude, Google Gemini, Ollama, and HuggingFace.
Switch providers by changing the `provider` argument at init time.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("openai", "claude", "gemini", "ollama", "huggingface")


class AIAdapter:
    """
    Unified interface to multiple AI model providers.

    Usage:
        adapter = AIAdapter(provider="openai", model="gpt-4o")
        response = adapter.chat([{"role": "user", "content": "Hello!"}])
    """

    def __init__(self, provider: str = "openai", model: str | None = None):
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
            "openai": "gpt-4o",
            "claude": "claude-3-5-sonnet-20241022",
            "gemini": "gemini-1.5-pro",
            "ollama": "llama3",
            "huggingface": "mistralai/Mistral-7B-Instruct-v0.2",
        }
        return defaults.get(provider, "unknown")
