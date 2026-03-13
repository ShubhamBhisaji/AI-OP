"""
app.py — AetheerAI — An AI Master!! Dashboard (Streamlit GUI)

Run with:  python -m streamlit run app.py
Or use:    Start_AetheerAI.bat
"""

from __future__ import annotations

import asyncio
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
    page_title="AetheerAI — An AI Master!!",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — website-style design ────────────────────────────────────
st.markdown("""
<style>
/* ── Hide Streamlit chrome ─────────────────────────────────────────── */
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }
div[data-testid="stStatusWidget"] { display: none; }

/* ── Fixed top navigation bar ─────────────────────────────────────── */
.top-navbar {
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 54px;
    z-index: 9999;
    background: #060d19;
    border-bottom: 1px solid #1a2d47;
    display: flex;
    align-items: center;
    padding: 0 28px;
    gap: 14px;
}
.top-navbar-logo { font-size: 22px; line-height: 1; }
.top-navbar-title {
    font-size: 16px; font-weight: 700;
    color: #eef2ff; letter-spacing: -0.3px;
}
.top-navbar-sub {
    font-size: 11px; color: #2d4a6a; font-weight: 500;
    border-left: 1px solid #1a2d47; padding-left: 14px; margin-left: 4px;
}
.top-navbar-badge {
    margin-left: auto;
    font-size: 11px; color: #22d3ee;
    background: rgba(6,182,212,0.1);
    border: 1px solid rgba(6,182,212,0.25);
    padding: 3px 12px; border-radius: 20px; font-weight: 600;
}

/* ── Push content below fixed header ─────────────────────────────── */
[data-testid="stAppViewContainer"] { padding-top: 54px !important; background: #0c1525; }
[data-testid="stMain"] { background: #0c1525; }
[data-testid="stSidebar"] {
    top: 54px !important;
    height: calc(100vh - 54px) !important;
    background: #07111e !important;
    border-right: 1px solid #1a2d47 !important;
}
[data-testid="stSidebarContent"] { padding: 0 !important; }

/* ── Sidebar brand block ──────────────────────────────────────────── */
.sidebar-brand {
    padding: 18px 18px 14px;
    border-bottom: 1px solid #1a2d47;
    margin-bottom: 4px;
}
.sidebar-brand-title {
    font-size: 17px; font-weight: 700;
    color: #eef2ff; line-height: 1.2; letter-spacing: -0.3px;
}
.sidebar-brand-sub { font-size: 11px; color: #2d4a6a; font-weight: 500; margin-top: 2px; }

/* ── Sidebar section labels ───────────────────────────────────────── */
.nav-section-label {
    font-size: 10px; font-weight: 700;
    letter-spacing: 1.2px; color: #2d4a6a;
    padding: 12px 18px 3px; text-transform: uppercase;
}

/* ── Nav radio — styled as nav links ──────────────────────────────── */
[data-testid="stSidebar"] input[type="radio"] { display: none !important; }
[data-testid="stSidebar"] .stRadio > label { display: none !important; }
[data-testid="stSidebar"] .stRadio > div {
    display: flex; flex-direction: column;
    gap: 1px; padding: 2px 10px;
}
[data-testid="stSidebar"] .stRadio label {
    display: flex !important; align-items: center;
    padding: 9px 14px !important;
    border-radius: 7px !important;
    color: #6b88a3 !important;
    font-size: 13.5px !important; font-weight: 500 !important;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    border-left: 3px solid transparent !important;
    margin: 1px 0;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(59,130,246,0.08) !important;
    color: #93c5fd !important;
}
[data-testid="stSidebar"] .stRadio label[data-selected="true"],
[data-testid="stSidebar"] .stRadio label[aria-checked="true"] {
    background: rgba(59,130,246,0.13) !important;
    color: #60a5fa !important;
    border-left-color: #3b82f6 !important;
}

/* ── Agent chip ───────────────────────────────────────────────────── */
.agent-chip {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 14px; border-radius: 6px;
    background: #0a1828; border: 1px solid #1a2d47;
    margin: 2px 0; font-size: 12px; color: #6b88a3;
}

/* ── Content area ─────────────────────────────────────────────────── */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
    max-width: 1100px;
}

/* ── Typography ───────────────────────────────────────────────────── */
h1 { font-size: 26px !important; font-weight: 700 !important; color: #eef2ff !important; margin-bottom: 4px !important; }
h2 { color: #c7d8f0 !important; font-weight: 600 !important; }
h3 { color: #8fa7c0 !important; }
p, li { color: #7a95b0; }

/* ── Buttons ──────────────────────────────────────────────────────── */
.stButton > button {
    border-radius: 7px !important; font-weight: 600 !important;
    font-size: 13px !important; transition: all 0.18s !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #4338ca 100%) !important;
    border: none !important; color: #fff !important;
    box-shadow: 0 2px 10px rgba(59,130,246,0.2) !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%) !important;
    box-shadow: 0 4px 20px rgba(59,130,246,0.35) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="secondary"] {
    background: #0d1b2e !important; border: 1px solid #1e3452 !important; color: #6b88a3 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #3b82f6 !important; color: #93c5fd !important; background: #0a1626 !important;
}

/* ── Inputs ───────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: 7px !important; background: #0a1626 !important;
    border: 1px solid #1e3452 !important; color: #e2e8f0 !important; font-size: 14px !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #3b82f6 !important; box-shadow: 0 0 0 2px rgba(59,130,246,0.15) !important;
}
[data-testid="stSelectbox"] > div > div {
    background: #0a1626 !important; border: 1px solid #1e3452 !important;
    border-radius: 7px !important; color: #e2e8f0 !important;
}

/* ── Expanders ────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #09131f !important; border: 1px solid #1a2d47 !important; border-radius: 10px !important;
}

/* ── Chat ─────────────────────────────────────────────────────────── */
.stChatMessage {
    background: #09131f !important; border: 1px solid #1a2d47 !important; border-radius: 12px !important;
}

/* ── Progress ─────────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #2563eb, #7c3aed) !important; border-radius: 4px !important;
}

/* ── Dividers ─────────────────────────────────────────────────────── */
hr { border-color: #1a2d47 !important; }

/* ── Alert boxes ──────────────────────────────────────────────────── */
[data-testid="stInfo"]    { background: rgba(59,130,246,0.07) !important; border: 1px solid rgba(59,130,246,0.18) !important; border-radius: 8px !important; }
[data-testid="stSuccess"] { background: rgba(16,185,129,0.07) !important; border: 1px solid rgba(16,185,129,0.18) !important; border-radius: 8px !important; }
[data-testid="stWarning"] { background: rgba(245,158,11,0.07)  !important; border: 1px solid rgba(245,158,11,0.18)  !important; border-radius: 8px !important; }
[data-testid="stError"]   { background: rgba(239,68,68,0.07)   !important; border: 1px solid rgba(239,68,68,0.18)   !important; border-radius: 8px !important; }

/* ── Dataframe ────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden; }

/* ── Code blocks ──────────────────────────────────────────────────── */
.stCode, pre { background: #060e1b !important; border: 1px solid #1a2d47 !important; border-radius: 7px !important; }
</style>
""", unsafe_allow_html=True)

# ── AetheerAI SVG icon ─ unique gradient IDs per placement ────────────────
_NAV_SVG = ('<svg width="30" height="30" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg"'
            ' style="flex-shrink:0;border-radius:8px">'
            '<defs>'
            '<linearGradient id="nb-bg" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#18181B"/><stop offset="100%" stop-color="#27272A"/>'
            '</linearGradient>'
            '<linearGradient id="nb-inf" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#F43F5E"/><stop offset="100%" stop-color="#8B5CF6"/>'
            '</linearGradient>'
            '</defs>'
            '<rect width="256" height="256" rx="64" fill="url(#nb-bg)"/>'
            '<path d="M 64 128 C 30 128 30 180 64 180 C 100 180 156 76 192 76 C 226 76 226 128 192 128'
            ' C 156 128 100 232 64 232 C 30 232 30 180 64 180"'
            ' fill="none" stroke="url(#nb-inf)" stroke-width="16" stroke-linecap="round"/>'
            '<path d="M 128 40 L 70 170 M 128 40 L 186 170 M 90 130 L 166 130"'
            ' fill="none" stroke="#FFFFFF" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>')
_SB_SVG  = ('<svg width="36" height="36" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg"'
            ' style="flex-shrink:0;border-radius:9px">'
            '<defs>'
            '<linearGradient id="sb-bg" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#18181B"/><stop offset="100%" stop-color="#27272A"/>'
            '</linearGradient>'
            '<linearGradient id="sb-inf" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#F43F5E"/><stop offset="100%" stop-color="#8B5CF6"/>'
            '</linearGradient>'
            '</defs>'
            '<rect width="256" height="256" rx="64" fill="url(#sb-bg)"/>'
            '<path d="M 64 128 C 30 128 30 180 64 180 C 100 180 156 76 192 76 C 226 76 226 128 192 128'
            ' C 156 128 100 232 64 232 C 30 232 30 180 64 180"'
            ' fill="none" stroke="url(#sb-inf)" stroke-width="16" stroke-linecap="round"/>'
            '<path d="M 128 40 L 70 170 M 128 40 L 186 170 M 90 130 L 166 130"'
            ' fill="none" stroke="#FFFFFF" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>')

# ── Favicon ───────────────────────────────────────────────────────────────
import base64 as _b64
_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aether_icon.svg")
if os.path.exists(_icon_path):
    with open(_icon_path, "rb") as _if:
        st.markdown(
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{_b64.b64encode(_if.read()).decode()}">',
            unsafe_allow_html=True,
        )

# ── Fixed top navbar HTML ─────────────────────────────────────────────────
st.markdown(f"""
<div class="top-navbar">
    {_NAV_SVG}
    <span class="top-navbar-title">AetheerAI — An AI Master!!</span>
    <span class="top-navbar-sub">Advanced AI Operating System</span>
    <span class="top-navbar-badge">● ONLINE</span>
    <span style="font-size:10px;color:#1e3a5f;font-weight:500;margin-left:8px;letter-spacing:0.3px;">Created&nbsp;by&nbsp;<span style="color:#3b82f6;font-weight:700;">Tecbunny</span></span>
</div>
""", unsafe_allow_html=True)


# ── Boot OS kernel — one isolated instance per browser session ───────────
# Bug 4 fix: @st.cache_resource is a GLOBAL shared cache (all browser tabs
# and users see the same kernel instance, leaking agents/memory between
# sessions).  st.session_state is scoped to a single browser tab so every
# session gets its own independent AetherKernel.
if "kernel" not in st.session_state:
    load_env()
    _provider = os.environ.get("AI_PROVIDER", "github")
    _model    = os.environ.get("AI_MODEL", "gpt-4.1")
    _k = AetherKernel(ai_provider=_provider, model=_model)
    # Auto-approve HITL — never block on terminal input() in web UI
    _k.set_hitl(
        enabled=True,
        callback=lambda cp: WorkflowFeedback(action=HITLAction.APPROVE),
    )
    st.session_state.kernel = _k

kernel = st.session_state.kernel


def _agent_names() -> list[str]:
    return kernel.list_agents()


def _run_agent_sync(agent_obj, task: str) -> str:
    """
    Execute an agent task synchronously from Streamlit's thread.

    Bug 4 fix — Async event loop:
      Streamlit reruns the entire script on every user interaction. It may
      have its own event loop already set on this thread, which would cause
      asyncio.run() or get_event_loop().run_until_complete() to raise
      "This event loop is already running".
      The safe pattern: always create a *fresh* event loop, use it, then
      close it. This is isolated per-call and never conflicts.
    """
    loop = asyncio.new_event_loop()
    try:
        return str(loop.run_until_complete(
            kernel.workflow_engine.execute_async(agent_obj, task)
        ))
    finally:
        loop.close()


# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Brand / Logo block ────────────────────────────────────────────
    st.markdown(f"""
    <div class="sidebar-brand">
        <div style="display:flex;align-items:center;gap:10px;">
            {_SB_SVG}
            <div>
                <div class="sidebar-brand-title">AetheerAI — An AI Master!!</div>
                <div class="sidebar-brand-sub">by Tecbunny</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Navigation ────────────────────────────────────────────────────
    st.markdown('<div class="nav-section-label">Navigation</div>', unsafe_allow_html=True)

    page = st.radio("nav", [
        "💬 Task Executor",
        "🏭 Agent Factory",
        "👥 System Orchestrator",
        "🎓 Train AI",
        "⚙️ Settings & Export",
    ], label_visibility="collapsed")

    # ── Registered Agents ─────────────────────────────────────────────
    st.markdown('<div class="nav-section-label" style="margin-top:10px;">Agents</div>', unsafe_allow_html=True)
    names = _agent_names()
    if names:
        for n in names:
            st.markdown(f'<div class="agent-chip">🤖 <span>{n}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:11.5px;color:#2d4a6a;padding:4px 18px 6px;">No agents — use Agent Factory</div>', unsafe_allow_html=True)

    # ── Provider info ─────────────────────────────────────────────────
    st.divider()
    st.markdown(
        f'<div style="font-size:11px;color:#2d4a6a;padding:2px 4px 6px;">'
        f'AI &nbsp;<span style="color:#60a5fa;font-weight:600;">{kernel.ai_adapter.provider}</span>'
        f' &nbsp;/&nbsp; <span style="color:#a78bfa;font-weight:600;">{kernel.ai_adapter.model}</span></div>',
        unsafe_allow_html=True,
    )

    # ── Stop button ───────────────────────────────────────────────────
    if st.button("⏹ Stop AetheerAI", use_container_width=True, type="secondary"):
        st.warning("Shutting down AetheerAI... You can close this tab.")
        st.toast("AetheerAI stopped.", icon="⏹")
        import time as _t; _t.sleep(1)
        import os as _os; _os._exit(0)

    # ── Bottom credit ─────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:14px 0 6px;font-size:10px;
                color:#1a2d47;font-weight:500;letter-spacing:0.4px;">
        <span style="color:#3b82f6;font-weight:700;">AetheerAI</span>
        &nbsp;—&nbsp;Created&nbsp;by&nbsp;
        <span style="color:#a78bfa;font-weight:700;">Tecbunny</span>
    </div>
    """, unsafe_allow_html=True)


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
                    result = _run_agent_sync(agent_obj, prompt)
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
        "AetheerAI will automatically research, provision, and register it."
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

    # ── Advanced: manual tool override ──────────────────────────────
    _ALL_TOOLS = [
        # Utilities
        "calculator", "datetime_tool", "hash_tool", "base64_tool", "regex_tool",
        "text_analyzer", "json_tool", "markdown_tool", "url_tool", "template_tool", "diff_tool",
        # Research & web
        "web_search", "http_client", "browser_tool", "web_scraper_pro",
        # Files & data
        "file_reader", "file_writer", "directory_scanner", "csv_tool", "pdf_tool",
        "note_taker", "analytics_tool", "local_file_tool",
        # Code & dev
        "code_runner", "terminal_tool", "code_analyzer", "code_search", "linter_tool",
        "code_formatter", "github_tool", "sql_db_tool", "playwright_tool",
        # AI & media
        "vision_tool", "image_gen_tool", "speech_tool",
        # Communication
        "email_tool", "slack_discord_tool",
        # Cloud & infra
        "aws_gcp_tool", "kubernetes_tool",
        # Security
        "security_tool", "system_info",
        # Multi-agent
        "ping_agent",
    ]
    with st.expander("⚙️ Advanced — Override Tool Selection", expanded=False):
        st.caption(
            "By default AetheerAI auto-selects tools based on the role. "
            "Add tools here to **guarantee** they are always included."
        )
        _extra_tools = st.multiselect(
            "Always include these tools",
            options=_ALL_TOOLS,
            default=[],
            key="factory_extra_tools",
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
                    kernel.build_agent(
                        agent_name, agent_role, progress=_prog,
                        extra_tools=_extra_tools or None,
                    )
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

    _orch_tab1, _orch_tab2, _orch_tab3 = st.tabs([
        "🏗️ Build AI System",
        "🔄 Pipeline Run",
        "🗣️ Agent Debate",
    ])

    # ── Tab 1: Build AI System ─────────────────────────────────────────
    with _orch_tab1:
        st.subheader("🏗️ Build AI System")
        st.markdown(
            "Build an entire multi-agent team from a single description. "
            "AetheerAI designs the agent roster, writes each system prompt, "
            "and registers them all."
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

    # ── Tab 2: Pipeline Run ────────────────────────────────────────────
    with _orch_tab2:
        st.subheader("🔄 Pipeline Run")
        st.markdown(
            "Run a sequence of agents as a **relay race** — each agent's output "
            "becomes the next agent's input.  The pipeline uses conversational "
            "handoff messages so every agent knows who sent the work and why."
        )

        _pipe_names = _agent_names()
        if not _pipe_names:
            st.warning("No agents found. Create some in **Agent Factory** first.")
        else:
            _pipe_task = st.text_area(
                "Initial task",
                placeholder="e.g. Research the top 5 AI trends of 2026 and then write a blog post about them.",
                height=100,
                key="pipe_task",
            )
            st.caption("Drag agents into the order you want them to run:")
            _pipe_agents = st.multiselect(
                "Pipeline agents (in order)",
                options=_pipe_names,
                key="pipe_agents",
            )

            if st.button(
                "▶️ Run Pipeline",
                type="primary",
                disabled=not (_pipe_task and len(_pipe_agents) >= 1),
                key="pipe_run",
            ):
                import asyncio as _asyncio
                _pipe_steps = st.empty()
                try:
                    with st.spinner("Running pipeline..."):
                        _pipe_result = kernel.run_pipeline(_pipe_agents, _pipe_task)
                    st.success("✅ Pipeline complete!")
                    st.markdown("**Final output:**")
                    st.markdown(_pipe_result)
                except Exception as _e:
                    st.error(f"Pipeline error: {_e}")

    # ── Tab 3: Agent Debate ────────────────────────────────────────────
    with _orch_tab3:
        st.subheader("🗣️ Agent Debate")
        st.markdown(
            "Have two agents **argue or collaborate** on a topic for N rounds. "
            "Perfect for code review, decision analysis, creative brainstorming, "
            "or stress-testing an idea from multiple expert perspectives."
        )

        _debate_names = _agent_names()
        if len(_debate_names) < 2:
            st.warning("You need at least **2 registered agents** to run a debate. "
                       "Create more in **Agent Factory**.")
        else:
            _dcol1, _dcol2, _dcol3 = st.columns([1, 1, 1])
            with _dcol1:
                _d_agent1 = st.selectbox("Agent 1 (Proposer)", _debate_names, key="debate_a1")
            with _dcol2:
                _remaining = [n for n in _debate_names if n != _d_agent1]
                _d_agent2 = st.selectbox("Agent 2 (Challenger)", _remaining, key="debate_a2")
            with _dcol3:
                _d_rounds = st.number_input(
                    "Rounds each", min_value=1, max_value=6, value=2, step=1, key="debate_rounds"
                )

            _d_topic = st.text_area(
                "Debate topic / question",
                placeholder=(
                    "e.g. Should this PR use async/await or callbacks? "
                    "· Which Python web framework—FastAPI or Django—is better for this use-case? "
                    "· Is PostgreSQL or MongoDB the right database for this project?"
                ),
                height=90,
                key="debate_topic",
            )

            if st.button(
                "🗣️ Start Debate",
                type="primary",
                disabled=not _d_topic.strip(),
                key="debate_run",
            ):
                with st.spinner(
                    f"Running {int(_d_rounds)} round(s) between **{_d_agent1}** and **{_d_agent2}**..."
                ):
                    try:
                        _debate_result = kernel.agent_debate(
                            _d_agent1, _d_agent2, _d_topic.strip(), int(_d_rounds)
                        )
                    except Exception as _de:
                        st.error(f"Debate error: {_de}")
                        _debate_result = {}

                if _debate_result.get("error"):
                    st.error(_debate_result["error"])
                elif _debate_result:
                    st.success(
                        f"✅ Debate complete — "
                        f"{len(_debate_result.get('transcript', []))} turns total."
                    )
                    # Render transcript
                    st.markdown("---")
                    st.markdown(f"### 📜 Transcript: *{_d_topic.strip()}*")
                    _prev_round = 0
                    for _turn in _debate_result.get("transcript", []):
                        if _turn["round"] != _prev_round:
                            st.markdown(f"**— Round {_turn['round']} —**")
                            _prev_round = _turn["round"]
                        with st.chat_message("user" if _turn["agent"] == _d_agent1 else "assistant"):
                            st.markdown(f"**{_turn['agent']}**")
                            st.markdown(_turn["argument"])
                    # Render summary
                    st.markdown("---")
                    st.markdown("### 🏁 Debate Summary")
                    st.markdown(_debate_result.get("summary", ""))


# ═══════════════════════════════════════════════════════════════════════════
# 4. TRAIN AI
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🎓 Train AI":
    st.header("🎓 Train AI")
    st.markdown(
        "Shape how AetheerAI and individual agents think, respond, and behave. "
        "Instructions you write here are injected directly into every AI prompt."
    )

    tab_global, tab_agent = st.tabs(["🌐 AetheerAI System Instructions", "🤖 Agent Instructions"])

    # ── Tab 1: Global / System-level instructions ─────────────────────
    with tab_global:
        st.subheader("🌐 AetheerAI System Instructions")
        st.markdown(
            "These instructions are prepended to **every agent's prompt** across the entire system. "
            "Use them to set the overall personality, language style, output format rules, "
            "ethical guidelines, or any behaviour that should apply universally."
        )

        st.info(
            "**Examples:**\n"
            "- *Always reply in formal English. Never use slang.*\n"
            "- *Format all code in markdown code blocks with the language tag.*\n"
            "- *You are part of TechCorp's internal AI platform. Never mention competitor products.*\n"
            "- *Always end responses with a one-line summary prefixed with TL;DR:*"
        )

        # Load current value
        _cur_sys = kernel.memory.load("system_instructions", default="", namespace="global")

        _new_sys = st.text_area(
            "System-wide instructions",
            value=_cur_sys,
            height=280,
            placeholder="Enter instructions that apply to ALL agents in AetheerAI...",
            key="train_sys_instr",
        )

        col_save, col_clear = st.columns([1, 1])
        with col_save:
            if st.button("💾 Save System Instructions", type="primary", use_container_width=True):
                kernel.memory.save("system_instructions", _new_sys.strip(), namespace="global")
                st.success("✅ System instructions saved! All agents will use them immediately.")
        with col_clear:
            if st.button("🗑️ Clear System Instructions", use_container_width=True):
                kernel.memory.save("system_instructions", "", namespace="global")
                st.success("System instructions cleared.")
                st.rerun()

        if _cur_sys:
            st.divider()
            st.caption("**Currently active system instructions:**")
            st.code(_cur_sys, language="markdown")

    # ── Tab 2: Per-agent instructions ────────────────────────────────
    with tab_agent:
        st.subheader("🤖 Agent-Specific Instructions")
        st.markdown(
            "These instructions are added to a **specific agent's prompt only**. "
            "Use them to refine that agent's expertise, persona, output style, or constraints "
            "beyond its original role."
        )

        names = _agent_names()
        if not names:
            st.warning("No agents found. Create one in **Agent Factory** first.")
            st.stop()

        _sel = st.selectbox("Select agent to train", names, key="train_agent_sel")
        _agent_obj = kernel.registry.get(_sel)

        if _agent_obj:
            # Show current profile summary
            with st.expander("Current agent profile", expanded=False):
                st.markdown(f"**Role:** {_agent_obj.role}")
                st.markdown(f"**Version:** {_agent_obj.profile.get('version', 'v1')}")
                _skills = _agent_obj.profile.get('skills', [])
                st.markdown(f"**Skills ({len(_skills)}):** {', '.join(_skills[:15])}{'...' if len(_skills) > 15 else ''}")

            st.info(
                "**Examples:**\n"
                "- *Always write Python code using type hints and docstrings.*\n"
                "- *When building UIs, prefer React with Tailwind CSS.*\n"
                "- *Respond as a senior developer with 15 years of experience.*\n"
                "- *Never suggest paid third-party services — only open-source solutions.*"
            )

            _cur_instr = _agent_obj.profile.get("instructions", "")

            _new_instr = st.text_area(
                f"Instructions for {_sel}",
                value=_cur_instr,
                height=280,
                placeholder=f"Enter custom instructions for {_sel}...",
                key="train_agent_instr",
            )

            # Role override
            st.markdown("**Refine role description** *(optional — leave blank to keep current)*")
            _new_role = st.text_input(
                "Role",
                value=_agent_obj.role,
                key="train_agent_role",
            )

            col_a, col_b = st.columns([1, 1])
            with col_a:
                if st.button(f"💾 Save {_sel} Training", type="primary", use_container_width=True):
                    _agent_obj.profile["instructions"] = _new_instr.strip()
                    if _new_role.strip() and _new_role.strip() != _agent_obj.role:
                        _agent_obj.role = _new_role.strip()
                        _agent_obj.profile["role"] = _new_role.strip()
                    # Bump version so changes are trackable
                    _agent_obj.bump_version()
                    kernel.registry.register(_agent_obj)  # re-registers + saves to JSON
                    st.success(f"✅ {_sel} training saved (v{_agent_obj.profile.get('version')})! "
                               f"The agent will use these instructions from the next task.")
                    st.rerun()
            with col_b:
                if st.button(f"🗑️ Clear {_sel} Instructions", use_container_width=True):
                    _agent_obj.profile["instructions"] = ""
                    kernel.registry.register(_agent_obj)
                    st.success(f"Instructions cleared for {_sel}.")
                    st.rerun()

            # Preview final prompt
            st.divider()
            with st.expander("🔍 Preview — what the AI will actually see", expanded=False):
                _sys_preview = kernel.memory.load("system_instructions", default="", namespace="global")
                _preview_instr = _new_instr.strip()
                _preview_role = _new_role.strip() or _agent_obj.role
                _sys_block = f"\nGlobal System Instructions:\n{_sys_preview}\n" if _sys_preview else ""
                _instr_bl = f"\nInstructions:\n{_preview_instr}\n" if _preview_instr else ""
                _preview_prompt = (
                    f"You are a {_preview_role}.{_sys_block}{_instr_bl}\n"
                    f"Your skills: (agent skills here).\n"
                    f"Available tools: (agent tools here).\n\n"
                    f"Task:\n[user task goes here]"
                )
                st.code(_preview_prompt, language="markdown")


# ═══════════════════════════════════════════════════════════════════════════
# 5. SETTINGS & EXPORT
# ═══════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Settings & Export":
    st.header("⚙️ Settings & Export")

    import json as _json
    import urllib.request as _urllib_req
    import urllib.error as _urllib_err

    # ── Provider metadata ─────────────────────────────────────────────
    _KEY_MAP = {
        "github":       "GITHUB_TOKEN",
        "openai":       "OPENAI_API_KEY",
        "claude":       "ANTHROPIC_API_KEY",
        "gemini":       "GEMINI_API_KEY",
        "ollama":       None,
        "huggingface":  "HF_API_KEY",
    }
    _KEY_LABEL = {
        "github":      "GitHub Personal Access Token",
        "openai":      "OpenAI API Key",
        "claude":      "Anthropic API Key",
        "gemini":      "Google Gemini API Key",
        "ollama":      None,
        "huggingface": "HuggingFace API Token (optional)",
    }
    _KEY_HELP = {
        "github":      "Get a free token at https://github.com/settings/tokens — no special scopes needed.",
        "openai":      "Get your key at https://platform.openai.com/api-keys",
        "claude":      "Get your key at https://console.anthropic.com/",
        "gemini":      "Get a free key at https://aistudio.google.com/apikey",
        "ollama":      "",
        "huggingface": "Get your token at https://huggingface.co/settings/tokens",
    }
    _STATIC_MODELS = {
        "github":      ["gpt-4.1", "gpt-5-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"],
        "openai":      ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1", "o1-mini"],
        "claude":      ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-sonnet-20241022",
                        "claude-3-opus-20240229", "claude-3-haiku-20240307"],
        "gemini":      ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
        "ollama":      ["llama3.2", "llama3.1", "mistral", "gemma3", "phi4",
                        "deepseek-r1", "codellama", "qwen2.5"],
        "huggingface": ["mistralai/Mistral-7B-Instruct-v0.3",
                        "meta-llama/Meta-Llama-3-8B-Instruct", "HuggingFaceH4/zephyr-7b-beta"],
    }
    _DEFAULT_ENDPOINTS = {
        "github":      "https://models.inference.ai.azure.com",
        "openai":      "https://api.openai.com/v1",
        "ollama":      "http://localhost:11434",
        "huggingface": "https://api-inference.huggingface.co",
        "claude":      "https://api.anthropic.com",
        "gemini":      "https://generativelanguage.googleapis.com",
    }

    def _is_vertex_ai(ep: str) -> bool:
        return "aiplatform.googleapis.com" in ep

    def _extract_model_from_vertex_url(url: str) -> str:
        import re as _re
        m = _re.search(r"/models/([^/:?]+)", url)
        return m.group(1) if m else ""

    _VERTEX_MODELS = [
        "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro",
        "gemini-2.0-flash", "gemini-2.0-flash-lite",
        "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro",
    ]

    def _fetch_models_for(provider: str, api_key: str, endpoint: str = "") -> list[str]:
        """Try to fetch live model list from provider; fall back to static list on any error."""
        try:
            if provider == "openai":
                req = _urllib_req.Request(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                with _urllib_req.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                ids = sorted(
                    [m["id"] for m in data["data"] if "gpt" in m["id"] or m["id"].startswith("o")],
                    reverse=True,
                )
                return ids or _STATIC_MODELS["openai"]

            elif provider == "gemini":
                # Vertex AI endpoint — can't list without OAuth; return known Vertex models
                if _is_vertex_ai(endpoint):
                    # Extract model if embedded in custom endpoint URL
                    _from_url = _extract_model_from_vertex_url(endpoint)
                    if _from_url and _from_url not in _VERTEX_MODELS:
                        return [_from_url] + _VERTEX_MODELS
                    return _VERTEX_MODELS
                # AI Studio — fetch live list with API key
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                with _urllib_req.urlopen(url, timeout=8) as r:
                    data = _json.loads(r.read())
                ids = [
                    m["name"].split("/")[-1]
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                return ids or _STATIC_MODELS["gemini"]

            elif provider == "ollama":
                _base = (endpoint or "http://localhost:11434").rstrip("/")
                with _urllib_req.urlopen(f"{_base}/api/tags", timeout=5) as r:
                    data = _json.loads(r.read())
                return [m["name"] for m in data.get("models", [])] or _STATIC_MODELS["ollama"]

            elif provider == "github":
                _ep = (endpoint or "https://models.inference.ai.azure.com").rstrip("/")
                req = _urllib_req.Request(
                    f"{_ep}/models",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
                with _urllib_req.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                if isinstance(data, list):
                    ids = [m.get("id") or m.get("name", "") for m in data]
                else:
                    ids = [m.get("id", "") for m in data.get("data", [])]
                return [i for i in ids if i] or _STATIC_MODELS["github"]
        except Exception:
            pass
        return _STATIC_MODELS.get(provider, [])

    def _test_connection(provider: str, api_key: str, model: str, endpoint: str = "") -> tuple[bool, str]:
        """Send a tiny test message; return (success, human-readable result)."""
        _msg = [{"role": "user", "content": "Reply with exactly one word: OK"}]
        try:
            if provider == "ollama":
                _base = (endpoint or "http://localhost:11434").rstrip("/")
                payload = _json.dumps({"model": model, "messages": _msg, "stream": False}).encode()
                req = _urllib_req.Request(
                    f"{_base}/api/chat", data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with _urllib_req.urlopen(req, timeout=20) as r:
                    data = _json.loads(r.read())
                reply = data.get("message", {}).get("content", "").strip()
                return True, f"✅ Connected — model replied: *{reply[:80]}*"

            elif provider == "gemini":
                # ── Vertex AI endpoint (aiplatform.googleapis.com) ─────
                if _is_vertex_ai(endpoint):
                    # Build clean generateContent URL from the custom endpoint
                    # Strip any existing method suffix (:streamGenerateContent etc)
                    import re as _re
                    _base_ep = _re.sub(r':(streamGenerateContent|generateContent|streamRawPredict|rawPredict).*', '', endpoint).rstrip('/')
                    # If model is embedded in the URL, reuse it; otherwise append
                    if "/models/" in _base_ep:
                        _vertex_url = f"{_base_ep}:generateContent?key={api_key}"
                    else:
                        _vertex_url = f"{_base_ep}/models/{model}:generateContent?key={api_key}"
                    payload = _json.dumps({
                        "contents": [{"role": "user", "parts": [{"text": _msg[0]["content"]}]}]
                    }).encode()
                    req = _urllib_req.Request(_vertex_url, data=payload,
                                              headers={"Content-Type": "application/json"}, method="POST")
                    try:
                        with _urllib_req.urlopen(req, timeout=25) as r:
                            data = _json.loads(r.read())
                        reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        return True, f"✅ Vertex AI connected — model replied: *{reply[:80]}*"
                    except _urllib_err.HTTPError as _vexc:
                        _vcode = _vexc.code
                        try:
                            _vdet = _json.loads(_vexc.read().decode())
                            _verr = _vdet.get("error", {}).get("message", str(_vexc))
                        except Exception:
                            _verr = str(_vexc)
                        if _vcode == 401:
                            return False, (
                                f"❌ Vertex AI ({_vcode}): {_verr}\n\n"
                                "**Vertex AI requires OAuth2 — API keys won't work here.**\n\n"
                                "**Options:**\n"
                                "• Use the standard Gemini AI Studio endpoint instead: `https://generativelanguage.googleapis.com` "
                                "with an AI Studio key from https://aistudio.google.com/apikey\n"
                                "• Or use a Google Cloud service account and pass an OAuth2 access token\n"
                                "• Tip: Paste your curl command in **Auto-Configure via Ollama** above — "
                                "it will detect Vertex AI and explain what you need."
                            )
                        return False, f"❌ Vertex AI error ({_vcode}): {_verr}"

                # ── Standard AI Studio endpoint ────────────────────────
                _ep = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={api_key}"
                )
                payload = _json.dumps({
                    "contents": [{"role": "user", "parts": [{"text": _msg[0]["content"]}]}]
                }).encode()
                req = _urllib_req.Request(_ep, data=payload,
                                          headers={"Content-Type": "application/json"}, method="POST")
                with _urllib_req.urlopen(req, timeout=25) as r:
                    data = _json.loads(r.read())
                reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return True, f"✅ Connected — model replied: *{reply[:80]}*"

            elif provider == "claude":
                try:
                    import anthropic as _ant  # type: ignore
                except ImportError:
                    return False, "anthropic SDK not installed — run: `pip install anthropic`"
                client = _ant.Anthropic(api_key=api_key)
                resp = client.messages.create(
                    model=model, max_tokens=10,
                    messages=[{"role": "user", "content": _msg[0]["content"]}],
                )
                reply = resp.content[0].text.strip()
                return True, f"✅ Connected — model replied: *{reply[:80]}*"

            else:
                # GitHub / OpenAI / HuggingFace — OpenAI-compatible REST
                _ep_map = {
                    "github":      (endpoint or "https://models.inference.ai.azure.com").rstrip("/") + "/chat/completions",
                    "openai":      "https://api.openai.com/v1/chat/completions",
                    "huggingface": f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions",
                }
                _ep = _ep_map.get(provider, endpoint.rstrip("/") + "/chat/completions")
                payload = _json.dumps({"model": model, "messages": _msg, "max_tokens": 10}).encode()
                req = _urllib_req.Request(
                    _ep, data=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with _urllib_req.urlopen(req, timeout=25) as r:
                    data = _json.loads(r.read())
                reply = (data["choices"][0]["message"]["content"] or "").strip()
                return True, f"✅ Connected — model replied: *{reply[:80]}*"

        except _urllib_err.HTTPError as exc:
            try:
                detail = _json.loads(exc.read().decode())
                err = detail.get("error", {}).get("message", str(exc))
            except Exception:
                err = str(exc)
            return False, f"❌ API error ({exc.code}): {err}"
        except Exception as exc:
            return False, f"❌ {exc}"

    # ── Auto-Configure via Ollama ─────────────────────────────────────
    import shutil as _shutil, subprocess as _subp

    _ollama_running = False
    _ollama_local_models: list[str] = []
    try:
        _tags_raw = _subp.check_output(["ollama", "list"], text=True, stderr=_subp.STDOUT, timeout=5)
        _ollama_running = True
        _ollama_local_models = [
            l.split()[0] for l in _tags_raw.strip().splitlines()[1:] if l.strip()
        ]
    except Exception:
        pass

    with st.expander("🤖 Auto-Configure from API Docs / curl command", expanded=False):
        st.markdown(
            "Paste a **curl command**, **API documentation snippet**, or **JSON config** — "
            "Ollama will analyze it and auto-fill provider, endpoint, and model settings for you."
        )

        if not _shutil.which("ollama"):
            st.warning("⚠️ **Ollama is not installed.** This feature requires a local Ollama model to analyze your docs.")
            st.markdown("""
**Setup steps:**
1. [Download Ollama for Windows](https://ollama.com/download/windows) and install it
2. Open a terminal and run: `ollama pull llama3.2`
3. Restart this dashboard — auto-configure will be available
            """)
            st.link_button("⬇️ Install Ollama", "https://ollama.com/download/windows",
                           type="primary", use_container_width=False)

        elif not _ollama_running:
            st.warning("⚠️ **Ollama is installed but not running.** Start it from your taskbar or run `ollama serve` in a terminal.")

        elif not _ollama_local_models:
            st.info("📦 Ollama is running but no models are installed.\n\nRun: `ollama pull llama3.2` — then come back here.")

        else:
            st.success(f"✅ Ollama ready — {len(_ollama_local_models)} local model(s) available")

            _ac_model_sel = st.selectbox(
                "Analysis model", _ollama_local_models,
                help="Smaller models like llama3.2 or phi4 work fine for this.",
                key="ac_ollama_model",
            )
            _ac_docs = st.text_area(
                "Paste curl command / API docs / JSON config",
                height=170,
                placeholder=(
                    'curl "https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash-lite:generateContent?key=${API_KEY}" \\\n'
                    '  -X POST -H "Content-Type: application/json" \\\n'
                    '  -d \'{"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}\'\n\n'
                    '— or paste any API reference JSON, OpenAPI spec, or endpoint description'
                ),
                key="ac_docs_input",
            )

            if st.button("🔍 Analyze & Auto-Fill Settings", type="primary",
                         disabled=not (_ac_docs or "").strip(), key="ac_analyze"):
                with st.spinner(f"Ollama ({_ac_model_sel}) is reading your API docs..."):
                    _ac_prompt = (
                        "You are an API configuration expert. Analyze the following API documentation, "
                        "curl command, or config snippet and extract all relevant settings.\n\n"
                        "Return ONLY a raw JSON object — no markdown fences, no explanation, just JSON:\n"
                        "{\n"
                        '  "provider": "one of: github, openai, claude, gemini, ollama, huggingface, or custom",\n'
                        '  "endpoint": "base API URL, strip model name and method suffix (e.g. https://aiplatform.googleapis.com for Vertex, https://generativelanguage.googleapis.com for AI Studio)",\n'
                        '  "model": "model ID extracted from URL or docs",\n'
                        '  "auth_type": "one of: api_key_param (?key=), bearer (Authorization: Bearer), x-api-key, none",\n'
                        '  "env_var": "recommended env var name e.g. GEMINI_API_KEY",\n'
                        '  "requires_oauth": true or false,\n'
                        '  "notes": "1-2 sentence explanation — flag if OAuth2/service account is needed instead of a simple API key, and what the user should do"\n'
                        "}\n\nAPI DOCS:\n" + _ac_docs.strip()
                    )
                    try:
                        import urllib.request as _ur2, json as _uj2
                        _pl = _uj2.dumps({"model": _ac_model_sel,
                                          "messages": [{"role": "user", "content": _ac_prompt}],
                                          "stream": False}).encode()
                        _rq = _ur2.Request("http://localhost:11434/api/chat", data=_pl,
                                           headers={"Content-Type": "application/json"}, method="POST")
                        with _ur2.urlopen(_rq, timeout=90) as _rr:
                            _raw_resp = _uj2.loads(_rr.read())
                        _raw_txt = _raw_resp.get("message", {}).get("content", "").strip()
                        # Strip markdown code fences if model wrapped output
                        if "```" in _raw_txt:
                            _raw_txt = "\n".join(
                                ln for ln in _raw_txt.splitlines()
                                if not ln.strip().startswith("```")
                            )
                        _ac_cfg = _uj2.loads(_raw_txt)
                        st.session_state["ac_result"] = _ac_cfg
                    except Exception as _ae:
                        st.error(f"Analysis failed: {_ae}")
                        st.session_state.pop("ac_result", None)

            _ac_res = st.session_state.get("ac_result")
            if _ac_res:
                if _ac_res.get("requires_oauth"):
                    st.warning(
                        f"⚠️ **OAuth2 / Service Account Required**\n\n{_ac_res.get('notes', '')}\n\n"
                        "This endpoint does **not** accept simple API keys.\n\n"
                        "**Your options:**\n"
                        "• Switch to the standard AI Studio endpoint `https://generativelanguage.googleapis.com` "
                        "and get a free key at https://aistudio.google.com/apikey\n"
                        "• Or authenticate via `gcloud auth application-default login` and pass an OAuth2 access token"
                    )
                else:
                    st.info(f"💡 {_ac_res.get('notes', '')}")

                with st.expander("Extracted configuration", expanded=True):
                    st.json(_ac_res)

                if not _ac_res.get("requires_oauth"):
                    if st.button("✅ Apply This Config", type="primary", key="ac_apply"):
                        _ap = _ac_res.get("provider", "")
                        _aep = _ac_res.get("endpoint", "")
                        _amd = _ac_res.get("model", "")
                        # Store endpoint so it auto-fills the Advanced field
                        if _aep:
                            st.session_state[f"cfg_endpoint_{_ap}"] = _aep
                        # Inject model into the fetched list so it shows in dropdown
                        if _amd:
                            _amk = f"fetched_models_{_ap}"
                            _aex = st.session_state.get(_amk, _STATIC_MODELS.get(_ap, []))
                            if _amd not in _aex:
                                st.session_state[_amk] = [_amd] + _aex
                        st.success(
                            f"✅ Config applied — provider: **{_ap}** | model: **{_amd}**\n\n"
                            f"The fields below have been pre-filled. Enter your API key and run **Test Connection**."
                        )
                        st.rerun()

    st.divider()

    # ── AI Provider Configuration UI ──────────────────────────────────
    st.subheader("🔌 AI Provider Configuration")

    providers = ["github", "openai", "claude", "gemini", "ollama", "huggingface"]
    _cur_idx = providers.index(kernel.ai_adapter.provider) if kernel.ai_adapter.provider in providers else 0
    new_provider = st.selectbox("Provider", providers, index=_cur_idx, key="cfg_provider")

    # API key input
    _env_var   = _KEY_MAP[new_provider]
    _env_label = _KEY_LABEL[new_provider]
    _env_help  = _KEY_HELP[new_provider]
    _cur_key   = os.environ.get(_env_var, "") if _env_var else ""

    if _env_var:
        _new_key = st.text_input(
            _env_label,
            value=_cur_key,
            type="password",
            help=_env_help,
            key=f"cfg_key_{new_provider}",
            placeholder=f"Paste your {_env_label}...",
        )
    else:
        _new_key = ""
        st.info("🟢 Ollama requires no API key. Make sure the Ollama daemon is running (`ollama serve`).")

    # Custom endpoint (advanced)
    with st.expander("⚙️ Advanced — Custom Endpoint", expanded=False):
        _cfg_ep_key = f"cfg_endpoint_{new_provider}"
        _saved_ep = st.session_state.get(_cfg_ep_key, _DEFAULT_ENDPOINTS.get(new_provider, ""))
        custom_endpoint = st.text_input(
            "API Endpoint URL",
            value=_saved_ep,
            key=_cfg_ep_key,
            placeholder=_DEFAULT_ENDPOINTS.get(new_provider, "https://..."),
        )
        st.caption(
            "Change only if using a proxy, self-hosted model, or OpenAI-compatible server "
            "(LM Studio, vLLM, etc.)."
        )

    # ── Fetch Models + Test row ───────────────────────────────────────
    _models_key      = f"fetched_models_{new_provider}"
    _test_passed_key = f"test_passed_{new_provider}"
    _test_msg_key    = f"test_msg_{new_provider}"

    _fetch_col, _test_col = st.columns(2)
    with _fetch_col:
        if st.button("🔍 Fetch Available Models", use_container_width=True, key="cfg_fetch"):
            with st.spinner("Fetching models from provider..."):
                _fetched = _fetch_models_for(new_provider, _new_key or _cur_key, custom_endpoint)
            st.session_state[_models_key] = _fetched
            if _fetched != _STATIC_MODELS.get(new_provider, []):
                st.success(f"Fetched {len(_fetched)} live model(s) from {new_provider}")
            else:
                st.info(f"Using default model list — {len(_fetched)} model(s)")

    # Model selector
    _available_models = st.session_state.get(_models_key, _STATIC_MODELS.get(new_provider, []))
    _cur_model_val = (
        kernel.ai_adapter.model
        if kernel.ai_adapter.provider == new_provider
        else (_available_models[0] if _available_models else "")
    )
    _cur_model_idx = (
        _available_models.index(_cur_model_val)
        if _cur_model_val in _available_models else 0
    )

    if _available_models:
        new_model = st.selectbox(
            "Model", _available_models, index=_cur_model_idx, key="cfg_model"
        )
    else:
        new_model = st.text_input("Model", value=_cur_model_val, key="cfg_model_text")

    # Test connection
    with _test_col:
        if st.button("🧪 Test Connection", use_container_width=True, type="primary", key="cfg_test"):
            _key_to_use = _new_key or _cur_key
            if not _key_to_use and new_provider != "ollama":
                st.error(f"Enter your {_env_label} first.")
                st.session_state[_test_passed_key] = False
            else:
                with st.spinner(f"Testing {new_provider} / {new_model}..."):
                    _ok, _tmsg = _test_connection(new_provider, _key_to_use, new_model, custom_endpoint)
                st.session_state[_test_passed_key] = _ok
                st.session_state[_test_msg_key] = _tmsg

    # Show last test result inline
    _last_msg = st.session_state.get(_test_msg_key, "")
    if _last_msg:
        if st.session_state.get(_test_passed_key):
            st.success(_last_msg)
        else:
            st.error(_last_msg)

    # ── Apply ─────────────────────────────────────────────────────────
    _test_passed = st.session_state.get(_test_passed_key, False)
    if not _test_passed:
        st.caption("💡 Run **Test Connection** first — settings apply only after a successful test.")

    if st.button(
        "✅ Apply & Notify AetheerAI",
        type="primary",
        disabled=not _test_passed,
        key="cfg_apply",
    ):
        # 1. Persist API key to .env and current process env
        if _env_var and _new_key:
            os.environ[_env_var] = _new_key
            _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            _env_lines: list[str] = []
            if os.path.exists(_env_path):
                with open(_env_path, "r", encoding="utf-8") as _ef:
                    _env_lines = _ef.readlines()
            _found_key = False
            for _i, _ln in enumerate(_env_lines):
                if _ln.strip().startswith(f"{_env_var}=") or _ln.strip().startswith(f"{_env_var} ="):
                    _env_lines[_i] = f"{_env_var}={_new_key}\n"
                    _found_key = True
                    break
            if not _found_key:
                _env_lines.append(f"{_env_var}={_new_key}\n")
            with open(_env_path, "w", encoding="utf-8") as _ef:
                _ef.writelines(_env_lines)

        # 2. Switch kernel adapter
        kernel.ai_adapter.switch(new_provider, new_model or None)
        kernel.workflow_engine.ai_adapter = kernel.ai_adapter

        # 3. Propagate to any agent objects that carry their own adapter reference
        for _aname in _agent_names():
            _aobj = kernel.registry.get(_aname)
            if _aobj and hasattr(_aobj, "ai_adapter"):
                _aobj.ai_adapter = kernel.ai_adapter

        # 4. Record the change in system memory (agents see this context)
        _notif = (
            f"AI provider changed to {new_provider} / {kernel.ai_adapter.model}. "
            f"All future tasks will use this model."
        )
        kernel.memory.save("last_provider_change", _notif, namespace="global")

        st.success(
            f"✅ AetheerAI is now using **{new_provider}** / **{kernel.ai_adapter.model}**  \n"
            f"API key saved · All agents notified."
        )
        st.session_state[_test_passed_key] = False
        st.session_state[_test_msg_key] = ""
        st.rerun()

    # ── Broadcast setting change to all AI systems ────────────────────
    st.divider()
    with st.expander("📡 Notify AetheerAI / AI Systems — Broadcast a Setting Change", expanded=False):
        st.markdown(
            "Send a **system-wide notice** to all agents. "
            "Your message is injected into every agent's prompt so they are aware of the change."
        )
        st.caption(
            "**Examples:** *The internal API is now at `https://api.v2/`* · "
            "*Use PostgreSQL instead of SQLite* · *The production domain changed to `app.newdomain.com`*"
        )
        _broadcast_msg = st.text_area(
            "Announcement",
            height=90,
            placeholder="e.g. The internal API endpoint has moved to https://api.internal/v2. All agents must use this address.",
            key="cfg_broadcast_msg",
        )
        if st.button(
            "📢 Broadcast to All Agents",
            disabled=not (_broadcast_msg or "").strip(),
            key="cfg_broadcast",
        ):
            _bcast = _broadcast_msg.strip()
            kernel.memory.save("system_broadcast", _bcast, namespace="global")
            _existing_instr = kernel.memory.load("system_instructions", default="", namespace="global")
            _sep = "\n\n" if _existing_instr else ""
            kernel.memory.save(
                "system_instructions",
                f"{_existing_instr}{_sep}[SYSTEM NOTICE] {_bcast}",
                namespace="global",
            )
            _n = len(_agent_names())
            st.success(f"✅ Notice broadcast to {_n} agent(s). They will see it from the next task.")

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

    # ── Ollama — Local AI ─────────────────────────────────────────────
    st.subheader("🦙 Ollama — Local AI")
    st.markdown(
        "Run AI models **100% offline** on your own machine. "
        "No API key needed. Ollama manages model downloads automatically."
    )

    import shutil, subprocess as _sp

    _ollama_path = shutil.which("ollama")
    _ollama_installed = _ollama_path is not None

    if _ollama_installed:
        # ── Already installed — show status + model manager ──────────
        try:
            _ver = _sp.check_output(["ollama", "--version"], text=True,
                                    stderr=_sp.STDOUT, timeout=5).strip()
        except Exception:
            _ver = "installed"

        st.success(f"✅ Ollama is installed  (`{_ver}`)")

        # Check if the daemon is running
        try:
            _sp.check_output(["ollama", "list"], text=True,
                             stderr=_sp.STDOUT, timeout=5)
            _daemon_running = True
        except Exception:
            _daemon_running = False

        if not _daemon_running:
            st.warning(
                "⚠️ Ollama daemon is not running. "
                "Start it by opening **Ollama** from your Start Menu or taskbar, "
                "or run `ollama serve` in a terminal."
            )
        else:
            st.info("🟢 Ollama daemon is running and ready.")

        st.markdown("**Pull a new model** — browse all models at [ollama.com/library](https://ollama.com/library)")
        _popular = [
            "llama3.2", "llama3.1", "llama3", "llama2",
            "mistral", "mistral-nemo",
            "gemma3", "gemma2", "gemma",
            "phi4", "phi3", "phi3.5",
            "qwen2.5", "qwen2",
            "deepseek-r1", "deepseek-coder-v2",
            "codellama", "starcoder2",
            "neural-chat", "orca-mini",
            "custom (type below)",
        ]
        _sel_model = st.selectbox("Choose a model to pull", _popular, key="ollama_model_sel")
        _custom_model = ""
        if _sel_model == "custom (type below)":
            _custom_model = st.text_input("Custom model name", placeholder="e.g. llama3.2:70b")
        _pull_name = _custom_model.strip() if _sel_model == "custom (type below)" else _sel_model

        if st.button("⬇️ Pull Model", disabled=not _pull_name):
            with st.spinner(f"Pulling **{_pull_name}** — this may take a few minutes..."):
                try:
                    _result = _sp.run(
                        ["ollama", "pull", _pull_name],
                        capture_output=True, text=True, timeout=600,
                    )
                    if _result.returncode == 0:
                        st.success(f"✅ Model **{_pull_name}** is ready!")
                    else:
                        st.error(f"Pull failed:\n```\n{_result.stderr or _result.stdout}\n```")
                except _sp.TimeoutExpired:
                    st.warning("Pull is taking longer than 10 minutes — it may still be running in the background.")
                except Exception as _e:
                    st.error(f"Error: {_e}")

        st.markdown("**Installed models**")
        try:
            _list_out = _sp.check_output(["ollama", "list"], text=True,
                                         stderr=_sp.STDOUT, timeout=5)
            _lines = [l for l in _list_out.strip().splitlines() if l]
            if len(_lines) > 1:
                # Parse: NAME  ID  SIZE  MODIFIED
                _rows = []
                for _l in _lines[1:]:
                    _parts = _l.split()
                    _rows.append({
                        "Model": _parts[0] if len(_parts) > 0 else "",
                        "Size":  _parts[2] if len(_parts) > 2 else "",
                        "Modified": " ".join(_parts[3:]) if len(_parts) > 3 else "",
                    })
                st.dataframe(_rows, use_container_width=True, hide_index=True)

                # Use with AetheerAI
                st.markdown("**Use a local model with AetheerAI** — pick one below then click Switch.")
                _local_models = [r["Model"] for r in _rows]
                _chosen = st.selectbox("Local model", _local_models, key="ollama_use_sel")
                if st.button("🔁 Switch AetheerAI to this model"):
                    try:
                        kernel.ai_adapter.switch("ollama", _chosen)
                        kernel.workflow_engine.ai_adapter = kernel.ai_adapter
                        st.success(f"Now using **ollama / {_chosen}** — no API key needed!")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Switch failed: {_e}")
            else:
                st.info("No models installed yet. Pull one above.")
        except Exception:
            st.info("Start the Ollama daemon to see installed models.")

    else:
        # ── Not installed — show download instructions ────────────────
        st.warning("⚠️ Ollama is not installed on this machine.")

        st.markdown("""
**How to install Ollama:**

1. Click the download button below — it opens the official Ollama website
2. Download the **Windows** installer (`OllamaSetup.exe`)
3. Run the installer — it adds `ollama` to your PATH automatically
4. Restart this dashboard after installation

> **What is Ollama?**  
> Ollama lets you run powerful AI models like Llama 3, Mistral, Gemma, and DeepSeek
> fully offline on your own PC — no internet, no API key, no monthly fees.
        """)

        col_dl, col_gh = st.columns(2)
        with col_dl:
            st.link_button(
                "⬇️  Download Ollama for Windows",
                "https://ollama.com/download/windows",
                type="primary",
                use_container_width=True,
            )
        with col_gh:
            st.link_button(
                "📖  View Model Library",
                "https://ollama.com/library",
                use_container_width=True,
            )

        st.markdown("After installing, come back here and refresh to manage local models.")

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
