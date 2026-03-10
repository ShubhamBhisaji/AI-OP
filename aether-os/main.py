"""
main.py — Entry point for the Aether AI Operating System.

Usage:
    python main.py                        # Interactive CLI mode
    python main.py --provider claude      # Use Claude as the AI backend
    python main.py --provider ollama --model llama3   # Use local Ollama
"""

from __future__ import annotations

import argparse
import sys
import os

# Make sure the project root is on the path so all module imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.aether_kernel import AetherKernel
from cli.command_interface import CommandInterface


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="Aether AI Operating System",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "claude", "gemini", "ollama", "huggingface"],
        help="AI provider to use (default: openai)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (uses provider default if not specified)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    kernel = AetherKernel(ai_provider=args.provider, model=args.model)
    cli = CommandInterface(kernel=kernel)
    cli.run()


if __name__ == "__main__":
    main()
