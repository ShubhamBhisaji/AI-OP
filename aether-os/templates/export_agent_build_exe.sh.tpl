#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
NAME="__SAFE_NAME__"

pip install pyinstaller --quiet
pyinstaller --onefile --name "$NAME" --add-data "agent_profile.json:." --add-data ".env.example:." run_agent.py

echo "Build successful: dist/$NAME"
