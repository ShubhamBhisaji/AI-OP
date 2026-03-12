"""
app.py — AetherAi Master Dashboard (Streamlit GUI)

Run with:  python -m streamlit run app.py
Or use:    Start_AetherAi.bat
"""

from __future__ import annotations

import os
import sys

# Make sure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from core.env_loader import load_env
from core.aether_kernel import AetherKernel
from core.workflow_engine import WorkflowFeedback, HITLAction

# ── Page config — must be first Streamlit call ───────────────────────────
st.set_page_config(
    page_title="AetherAi Master",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — dark, polished feel ─────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background: #0e1117; }
    .stChatMessage { border-radius: 12px; }
    .stTextInput > div > div > input { border-radius: 8px; }
    .stTextArea > div > div > textarea { border-radius: 8px; }
    div[data-testid="stStatusWidget"] { display: none; }
</style>
""", unsafe_allow_html=True)


# ── Boot the OS kernel (cached — runs only once per session) ─────────────
@st.cache_resource(show_spinner="Booting AetherAi-A Master AI kernel...")
def boot_os() -> AetherKernel:
    load_env()
    # Read provider / model from env, fall back to github / gpt-4.1
    provider = os.environ.get("AI_PROVIDER", "github")
    model = os.environ.get("AI_MODEL", "gpt-4.1")
    kernel = AetherKernel(ai_provider=provider, model=model)
    # Auto-approve HITL in GUI mode so execute() never blocks on console input
    kernel.set_hitl(
        enabled=True,
        callback=lambda cp: WorkflowFeedback(action=HITLAction.APPROVE),
    )
    return kernel


kernel = boot_os()


def _agent_names() -> list[str]:
    return kernel.list_agents()


# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ AetherAi Master")
    st.caption("Advanced AI Operating System")
    st.divider()

    page = st.radio("Navigation", [
        "💬 Task Executor",
        "🏭 Agent Factory",
        "👥 System Orchestrator",
        "⚙️ Settings & Export",
    ])

    st.divider()
    st.subheader("Registered Agents")
    names = _agent_names()
    if names:
        for n in names:
            st.text(f"🤖 {n}")
    else:
        st.caption("No agents yet — use Agent Factory.")

    # Live provider chip
    st.divider()
    st.caption(f"**AI:** `{kernel.ai_adapter.provider}` / `{kernel.ai_adapter.model}`")


# ═══════════════════════════════════════════════════════════════════════════
# 1. TASK EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════
if page == "💬 Task Executor":
    st.header("💬 Task Executor")
    st.markdown("Chat with an agent — it handles your task and replies in real time.")

    names = _agent_names()
    if not names:
        st.warning("No agents found. Go to **Agent Factory** to create one first.")
        st.stop()

    selected_agent = st.selectbox("Agent", names, key="exec_agent_sel")

    # Per-agent chat history stored in session state
    history_key = f"chat_{selected_agent}"
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    # Show previous messages
    for msg in st.session_state[history_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input(f"Give {selected_agent} a task..."):
        st.session_state[history_key].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner(f"⚡ {selected_agent} is working..."):
                try:
                    agent_obj = kernel.registry.get(selected_agent)
                    result = kernel.workflow_engine.execute(agent_obj, prompt)
                    result_str = str(result)
                except Exception as exc:
                    result_str = f"**Error:** {exc}"
            st.markdown(result_str)
            st.session_state[history_key].append({"role": "assistant", "content": result_str})

    # Clear chat button
    if st.session_state.get(history_key):
        if st.button("🗑️ Clear chat", key="clear_chat"):
            st.session_state[history_key] = []
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# 2. AGENT FACTORY
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🏭 Agent Factory":
    st.header("🏭 Agent Factory")
    st.markdown(
        "Describe the role of the agent you want. "
        "AetherAi will automatically research, provision, and register it."
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        agent_name = st.text_input("Agent Name", placeholder="e.g. CodeBot, ResearchPro")
    with col2:
        agent_role = st.text_area(
            "Role & Responsibilities",
            placeholder="An expert software engineer who writes Python scripts and reviews code...",
            height=120,
        )

    if st.button("🔨 Build Agent", type="primary", disabled=not (agent_name and agent_role)):
        existing = _agent_names()
        if agent_name in existing:
            st.error(f"An agent named **{agent_name}** already exists. Choose a different name.")
        else:
            progress_bar = st.progress(0, text="Starting...")

            def _prog(step: int, total: int, msg: str) -> None:
                progress_bar.progress(int(step / total * 100), text=msg)

            try:
                with st.spinner(f"Building **{agent_name}**..."):
                    kernel.build_agent(agent_name, agent_role, progress=_prog)
                progress_bar.progress(100, text="Done!")
                st.success(f"✅ Agent **{agent_name}** built and registered successfully!")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to build agent: {exc}")

    # Show existing agents in a table
    st.divider()
    st.subheader("Registered Agents")
    names = _agent_names()
    if names:
        rows = []
        for n in names:
            a = kernel.registry.get(n)
            rows.append({
                "Name": n,
                "Role": a.role if a else "—",
                "Version": a.profile.get("version", "v1") if a else "—",
                "Skills": len(a.profile.get("skills", [])) if a else 0,
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No agents yet.")


# ═══════════════════════════════════════════════════════════════════════════
# 3. SYSTEM ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════
elif page == "👥 System Orchestrator":
    st.header("👥 System Orchestrator")
    st.markdown(
        "Build an entire multi-agent team from a single description. "
        "AetherAi designs the agent roster, writes each system prompt, and registers them all."
    )

    sys_col1, sys_col2 = st.columns([1, 2])
    with sys_col1:
        system_name = st.text_input("System Name", placeholder="e.g. NewsletterSystem")
    with sys_col2:
        system_desc = st.text_area(
            "System Description",
            placeholder="Build me a newsletter system with a Researcher who gathers stories and a Publisher who formats and sends them.",
            height=120,
        )

    if st.button("🏗️ Generate System", type="primary", disabled=not (system_name and system_desc)):
        sys_progress = st.progress(0, text="Starting system design...")

        def _sys_prog(step: int, total: int, msg: str) -> None:
            sys_progress.progress(int(step / total * 100), text=msg)

        try:
            with st.spinner(f"Designing **{system_name}**..."):
                result = kernel.create_ai_system(system_name, system_desc, progress=_sys_prog)
            sys_progress.progress(100, text="Done!")
            if result.get("error"):
                st.error(f"System error: {result['error']}")
            else:
                agents_built = result.get("agents", [])
                st.success(f"✅ System **{system_name}** created with {len(agents_built)} agent(s)!")
                st.json(result)
                st.rerun()
        except Exception as exc:
            st.error(f"Failed to build system: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# 4. SETTINGS & EXPORT
# ═══════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Settings & Export":
    st.header("⚙️ Settings & Export")

    # ── Live AI switch ────────────────────────────────────────────────
    st.subheader("Switch AI Provider")
    providers = ["github", "openai", "claude", "gemini", "ollama", "huggingface"]
    new_provider = st.selectbox("Provider", providers, index=providers.index(kernel.ai_adapter.provider) if kernel.ai_adapter.provider in providers else 0)
    new_model = st.text_input("Model", value=kernel.ai_adapter.model)
    if st.button("Apply AI Change"):
        try:
            kernel.ai_adapter.switch(new_provider, new_model or None)
            kernel.workflow_engine.ai_adapter = kernel.ai_adapter
            st.success(f"Switched to **{new_provider}** / **{kernel.ai_adapter.model}**")
            st.rerun()
        except Exception as exc:
            st.error(f"Switch failed: {exc}")

    st.divider()

    # ── Export ───────────────────────────────────────────────────────
    st.subheader("Export Agent Deployment Package")
    st.markdown(
        "Exports a standalone FastAPI server, Dockerfile, GUI launcher, "
        "and PyInstaller scripts into `exports/<AgentName>/`."
    )
    names = _agent_names()
    if names:
        export_agent = st.selectbox("Agent to Export", names, key="export_sel")
        if st.button("📦 Export", type="primary"):
            with st.spinner(f"Exporting **{export_agent}**..."):
                try:
                    info = kernel.export_agent(export_agent)
                    st.success(f"✅ Exported to `{info.get('path', 'exports/' + export_agent)}`")
                    st.json(info)
                except Exception as exc:
                    st.error(f"Export error: {exc}")
    else:
        st.info("No agents available to export.")

    st.divider()

    # ── Delete agent ─────────────────────────────────────────────────
    st.subheader("Delete Agent")
    names = _agent_names()
    if names:
        del_agent = st.selectbox("Agent to Delete", names, key="del_sel")
        if st.button("🗑️ Delete", type="secondary"):
            try:
                kernel.registry.remove(del_agent)
                st.success(f"Deleted **{del_agent}**.")
                st.rerun()
            except Exception as exc:
                st.error(f"Delete failed: {exc}")
    else:
        st.info("No agents to delete.")
