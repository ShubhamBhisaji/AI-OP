from __future__ import annotations

import json
import os
import sys

import streamlit as st

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core.aether_kernel import AetherKernel
from core.env_loader import load_env

load_env(os.path.join(_ROOT, ".env"))

with open(os.path.join(_ROOT, "agent_profile.json"), encoding="utf-8") as f:
    profile = json.load(f)

provider = os.environ.get("AETHER_DEFAULT_PROVIDER", "github")
model = os.environ.get("AETHER_DEFAULT_MODEL", "").strip() or None
kernel = AetherKernel(ai_provider=provider, model=model)
agent = kernel.factory.create(
    name=profile["name"],
    role=profile["role"],
    tools=profile.get("tools", []),
    skills=profile.get("skills", []),
    permission_level=profile.get("permission_level", 1),
)
kernel.registry.register(agent)

st.title("__AGENT_NAME__")
query = st.text_input("Task")
if st.button("Run") and query.strip():
    out = kernel.workflow_engine.execute(agent, query)
    st.write(out)
