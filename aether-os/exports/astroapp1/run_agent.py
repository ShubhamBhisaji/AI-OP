"""
Standalone runner for agent: astroapp1
Role: astrology
Skills: 

Usage:
    python run_agent.py
    python run_agent.py --task "your task here"
    python run_agent.py --provider ollama --model llama3.2:1b
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from cli.agent_window import run_agent_window

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default=None)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="llama3.2:1b")
    args = parser.parse_args()
    run_agent_window("astroapp1", args.provider, args.model)

if __name__ == "__main__":
    main()
