"""
speech_tool — Transcribe audio files (speech-to-text) and synthesize speech (text-to-speech).

Requires:  pip install openai
Env vars:  OPENAI_API_KEY

Actions
-------
  transcribe  : Convert an audio file to text using OpenAI Whisper.
                Supports: mp3, mp4, mpeg, mpga, m4a, wav, webm (max 25 MB).
  translate   : Transcribe AND translate audio to English.
  speak       : Convert text to a spoken audio file using OpenAI TTS.
                Output saved to agent_output/audio/.

Whisper models:   whisper-1 (default, best accuracy)
TTS models:       tts-1 (fast), tts-1-hd (higher quality)
TTS voices:       alloy | echo | fable | onyx | nova | shimmer
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_AUDIO_DIR    = Path(__file__).parent.parent / "agent_output" / "audio"
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_MAX_FILE_MB  = 25
_ALLOWED_EXT  = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}


def speech_tool(
    action: str = "transcribe",
    audio_path: str = "",
    text: str = "",
    language: str = "",
    model: str = "",
    voice: str = "alloy",
    filename: str = "",
    response_format: str = "mp3",
) -> str:
    """
    Convert speech to text or text to speech using the OpenAI API.

    action          : transcribe | translate | speak
    audio_path      : Path to audio file for transcribe/translate (sandboxed).
    text            : Text to synthesize for 'speak'.
    language        : ISO 639-1 language code hint for 'transcribe' (e.g. 'en', 'es').
    model           : whisper-1 (default STT) | tts-1 | tts-1-hd (TTS).
    voice           : TTS voice: alloy | echo | fable | onyx | nova | shimmer.
    filename        : Output audio filename for 'speak' (no path, no extension).
    response_format : Audio format for 'speak': mp3 | opus | aac | flac | wav.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return (
            "Error: OPENAI_API_KEY is not set.\n"
            "Add OPENAI_API_KEY=<key> to your .env file."
        )

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return "Error: openai package not installed. Run: pip install openai"

    client = OpenAI(api_key=api_key)
    action = (action or "transcribe").strip().lower()

    # ── transcribe / translate ────────────────────────────────────────
    if action in ("transcribe", "translate"):
        if not audio_path:
            return f"Error: 'audio_path' is required for {action}."

        path = _safe_audio_path(audio_path)
        if path is None:
            return "❌ Security: audio_path is outside the project directory."
        if not path.exists():
            return f"Error: File not found — {path}"
        if path.suffix.lower() not in _ALLOWED_EXT:
            return (
                f"Error: Unsupported format '{path.suffix}'. "
                f"Use: {', '.join(sorted(_ALLOWED_EXT))}"
            )
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > _MAX_FILE_MB:
            return f"Error: File is {size_mb:.1f} MB — maximum is {_MAX_FILE_MB} MB."

        try:
            with open(path, "rb") as f:
                kwargs: dict = dict(
                    model=model or "whisper-1",
                    file=f,
                    response_format="text",
                )
                if language and action == "transcribe":
                    kwargs["language"] = language
                if action == "transcribe":
                    result = client.audio.transcriptions.create(**kwargs)
                else:
                    result = client.audio.translations.create(**kwargs)
            text_out = result if isinstance(result, str) else getattr(result, "text", str(result))
            return f"[{action.title()}]\n{text_out}"
        except Exception as exc:
            logger.error("speech_tool (%s): %s", action, exc)
            return f"Whisper error: {exc}"

    # ── speak (TTS) ──────────────────────────────────────────────────
    if action == "speak":
        if not text:
            return "Error: 'text' is required for 'speak'."
        if len(text) > 4096:
            return f"Error: text is {len(text)} chars — OpenAI TTS maximum is 4096."

        voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
        if voice not in voices:
            return f"Error: Unknown voice '{voice}'. Use: {', '.join(sorted(voices))}"

        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        import time
        fname = (filename or f"speech_{int(time.time())}").replace("/", "_").replace("\\", "_")
        ext   = response_format.lower().lstrip(".")
        if ext not in {"mp3", "opus", "aac", "flac", "wav"}:
            ext = "mp3"
        out = _AUDIO_DIR / f"{fname}.{ext}"

        try:
            response = client.audio.speech.create(
                model=model or "tts-1",
                voice=voice,                        # type: ignore[arg-type]
                input=text,
                response_format=ext,                # type: ignore[arg-type]
            )
            out.write_bytes(response.content)
            words = len(text.split())
            return (
                f"Audio saved: {out}\n"
                f"Voice: {voice}  |  Model: {model or 'tts-1'}  |  "
                f"~{words} words  |  Format: {ext}"
            )
        except Exception as exc:
            logger.error("speech_tool (speak): %s", exc)
            return f"TTS error: {exc}"

    return f"Unknown action '{action}'. Use: transcribe, translate, speak."


def _safe_audio_path(p: str) -> Path | None:
    path = Path(p)
    if not path.is_absolute():
        path = (_PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    pr = str(_PROJECT_ROOT)
    if str(path) == pr or str(path).startswith(pr + os.sep):
        return path
    return None
