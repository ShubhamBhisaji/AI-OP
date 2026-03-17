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

from core.env_loader import load_env, check_env_file
from utils.log_config import setup_logging as _setup_logging
_setup_logging()  # initialise structured logging before any module imports

from core.aetheerai_kernel import AetheerAiKernel
from core.workflow_engine import WorkflowFeedback, HITLAction
from core.trace_bus import TraceBus

# ── Page config — must be first Streamlit call ───────────────────────────
st.set_page_config(
    page_title="AetheerAI Workspace",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — premium workspace design ────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Hide Streamlit chrome ─────────────────────────────────────────── */
#MainMenu, footer { visibility: hidden; }
header { visibility: hidden; }
[data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }
div[data-testid="stStatusWidget"] { display: none; }

/* ── Main app background ───────────────────────────────────────────── */
.stApp {
    background-color: #FCFCFD;
}

/* ── Sidebar ─────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: rgba(245, 245, 247, 0.8) !important;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-right: 1px solid rgba(226, 232, 240, 0.6) !important;
}
[data-testid="stSidebarContent"] { padding: 0 !important; }

/* ── Sidebar brand block ──────────────────────────────────────────── */
.sidebar-brand {
    padding: 20px 18px 16px;
    border-bottom: 1px solid #f1f5f9;
    margin-bottom: 4px;
}
.sidebar-brand-title {
    font-size: 14px; font-weight: 700;
    color: #0f172a; line-height: 1.3;
}
.sidebar-brand-sub { font-size: 10px; color: #94a3b8; font-weight: 500; margin-top: 3px; }

/* ── Sidebar section labels ───────────────────────────────────────── */
.nav-section-label {
    font-size: 10px; font-weight: 700;
    letter-spacing: 1.2px; color: #94a3b8;
    padding: 14px 18px 4px; text-transform: uppercase;
}

/* ── Nav radio — styled as nav links ──────────────────────────────── */
[data-testid="stSidebar"] input[type="radio"] { display: none !important; }
[data-testid="stSidebar"] .stRadio > label { display: none !important; }
[data-testid="stSidebar"] .stRadio > div {
    display: flex; flex-direction: column;
    gap: 2px; padding: 2px 12px;
}
[data-testid="stSidebar"] .stRadio label {
    display: flex !important; align-items: center;
    padding: 9px 14px !important;
    border-radius: 8px !important;
    color: #64748b !important;
    font-size: 13.5px !important; font-weight: 500 !important;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    border: 1px solid transparent !important;
    margin: 1px 0;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(255,255,255,0.7) !important;
    color: #0f172a !important;
}
[data-testid="stSidebar"] .stRadio label[data-selected="true"],
[data-testid="stSidebar"] .stRadio label[aria-checked="true"] {
    background: rgba(255,255,255,0.9) !important;
    color: #1d4ed8 !important;
    font-weight: 600 !important;
}

/* ── Agent chip ───────────────────────────────────────────────────── */
.agent-chip {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 14px; border-radius: 6px;
    background: rgba(255,255,255,0.6); border: 1px solid rgba(226,232,240,0.7);
    margin: 2px 0; font-size: 12px; color: #64748b;
}

/* ── Content area ─────────────────────────────────────────────────── */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
    max-width: 1100px;
}

/* ── Premium heading classes ──────────────────────────────────────── */
.premium-title {
    text-align: center;
    color: #0f172a;
    font-weight: 900;
    font-size: 2.5rem;
    letter-spacing: -0.025em;
    margin-top: 2rem;
    margin-bottom: 0.5rem;
    line-height: 1.15;
}
.premium-subtitle {
    text-align: center;
    color: #64748b;
    font-weight: 500;
    font-size: 1rem;
    margin-bottom: 3rem;
}

/* ── Typography ───────────────────────────────────────────────────── */
h1 { font-size: 26px !important; font-weight: 800 !important; color: #0f172a !important; margin-bottom: 4px !important; }
h2 { color: #1e293b !important; font-weight: 700 !important; }
h3 { color: #334155 !important; }
p, li { color: #64748b; }

/* ── Buttons ──────────────────────────────────────────────────────── */
.stButton > button {
    border-radius: 8px !important; font-weight: 600 !important;
    font-size: 13px !important; transition: all 0.18s !important;
}
.stButton > button[kind="primary"] {
    background: #2563eb !important;
    border: none !important; color: #fff !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.2) !important;
}
.stButton > button[kind="primary"]:hover {
    background: #1d4ed8 !important;
    box-shadow: 0 4px 16px rgba(37,99,235,0.3) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="secondary"] {
    background: rgba(255,255,255,0.8) !important; border: 1px solid #e2e8f0 !important; color: #475569 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #3b82f6 !important; color: #2563eb !important; background: #eff6ff !important;
}

/* ── Inputs ───────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: 10px !important; background: #ffffff !important;
    border: 1px solid #e2e8f0 !important; color: #0f172a !important; font-size: 14px !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #3b82f6 !important; box-shadow: 0 0 0 2px rgba(59,130,246,0.12) !important;
}
.stTextInput > div > div > input::placeholder,
.stTextArea > div > div > textarea::placeholder { color: #94a3b8 !important; }
[data-testid="stSelectbox"] > div > div {
    background: #ffffff !important; border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important; color: #0f172a !important;
}

/* ── Expanders ────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 12px !important;
}

/* ── Chat ─────────────────────────────────────────────────────────── */
.stChatMessage {
    background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 14px !important;
    color: #0f172a !important;
}
[data-testid="stChatMessage"] p { color: #374151 !important; }
[data-testid="stChatInputContainer"] > div {
    background: #ffffff !important; border: 1px solid #e2e8f0 !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06) !important;
}
[data-testid="stChatInputContainer"] textarea {
    background: transparent !important; color: #0f172a !important;
}
[data-testid="stChatInputContainer"] textarea::placeholder { color: #94a3b8 !important; }

/* ── Suggestion cards ─────────────────────────────────────────────── */
.suggestion-card {
    background: #ffffff; border: 1.5px solid #e2e8f0; border-radius: 16px;
    padding: 16px 18px; transition: all 0.2s; cursor: pointer;
}
.suggestion-card:hover { border-color: #3b82f6; box-shadow: 0 6px 20px rgba(0,0,0,0.07); }
.suggestion-card h4 { font-size: 13px; font-weight: 600; color: #1e293b; margin: 0 0 4px; }
.suggestion-card p  { font-size: 11.5px; color: #94a3b8; margin: 0; }

/* ── Progress ─────────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #2563eb, #7c3aed) !important; border-radius: 4px !important;
}

/* ── Dividers ─────────────────────────────────────────────────────── */
hr { border-color: #e2e8f0 !important; }

/* ── Alert boxes ──────────────────────────────────────────────────── */
[data-testid="stInfo"]    { background: rgba(59,130,246,0.05)  !important; border: 1px solid rgba(59,130,246,0.15)  !important; border-radius: 8px !important; }
[data-testid="stSuccess"] { background: rgba(16,185,129,0.05)  !important; border: 1px solid rgba(16,185,129,0.15)  !important; border-radius: 8px !important; }
[data-testid="stWarning"] { background: rgba(245,158,11,0.05)  !important; border: 1px solid rgba(245,158,11,0.15)  !important; border-radius: 8px !important; }
[data-testid="stError"]   { background: rgba(239,68,68,0.05)   !important; border: 1px solid rgba(239,68,68,0.15)   !important; border-radius: 8px !important; }

/* ── Dataframe ────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden; border: 1px solid #e2e8f0 !important; }

/* ── Tabs ─────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tab"] { color: #64748b !important; font-weight: 500 !important; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #2563eb !important; border-bottom-color: #2563eb !important; }

/* ── Code blocks ──────────────────────────────────────────────────── */
.stCode, pre { background: #f8fafc !important; border: 1px solid #e2e8f0 !important; border-radius: 8px !important; }
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
_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aetheerai_icon.svg")
if os.path.exists(_icon_path):
    with open(_icon_path, "rb") as _if:
        st.markdown(
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{_b64.b64encode(_if.read()).decode()}">',
            unsafe_allow_html=True,
        )


# ── Boot OS kernel — one isolated instance per browser session ───────────
# Bug 4 fix: @st.cache_resource is a GLOBAL shared cache (all browser tabs
# and users see the same kernel instance, leaking agents/memory between
# sessions).  st.session_state is scoped to a single browser tab so every
# session gets its own independent AetheerAiKernel.
if "kernel" not in st.session_state:
    load_env()
    check_env_file()
    _provider = os.environ.get("AI_PROVIDER", "github")
    _model    = os.environ.get("AI_MODEL", "gpt-4.1")
    _k = AetheerAiKernel(ai_provider=_provider, model=_model)
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
    # ── Brand block ───────────────────────────────────────────────────
    st.markdown("### ✨ AetheerAI\n**WORKSPACE**")
    st.markdown("---")

    # ── Navigation ────────────────────────────────────────────────────
    st.markdown('<p style="font-size: 0.75rem; color: #94a3b8; font-weight: 700; letter-spacing: 0.1em;">MAIN MENU</p>', unsafe_allow_html=True)

    page = st.radio("nav", [
        "💬 Task Executor",
        "🏭 Agent Factory",
        "👥 System Orchestrator",
        "🎓 Train AI",
        "⚙️ Settings & Export",
        "🛡️ Governance",
        "🔗 Interoperability",
        "🧠 Memory OS",
        "🔥 Self-Healer",
        "⚖️ Priority Controller",
        "⏱️ Checkpointing",
        "🐝 Swarm Bus",
        "🔨 Tool Synthesizer",
        "🖥️ Computer Use",
        "🗄️ Zero-Copy Data",
        "🔴 Red-Team Security",
        "📡 Assembly Line",
        "🧭 Model Router",
        "🚦 Aetheer Gateway",
        "🧠 Dual-Process",
        "💰 FinOps",
        "🔬 Semantic Cleaner",
        "🎛️ Control Plane",
        "👤 Human Supervisor",
        "🔐 Federated Learning",
        "🚨 Proactive Concierge",
        "🎭 Personality Engine",
    ], label_visibility="collapsed")

    st.markdown("---")

    # ── Registered Agents ─────────────────────────────────────────────
    st.markdown('<p style="font-size: 0.75rem; color: #94a3b8; font-weight: 700; letter-spacing: 0.1em;">ACTIVE AGENTS</p>', unsafe_allow_html=True)
    names = _agent_names()
    if names:
        for n in names:
            st.markdown(f'<div class="agent-chip">🤖 <span>{n}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:11.5px;color:#94a3b8;padding:4px 2px 6px;">No agents — use Agent Factory</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── Provider info ─────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:11px;color:#94a3b8;padding:2px 0 6px;">'
        f'AI &nbsp;<span style="color:#2563eb;font-weight:600;">{kernel.ai_adapter.provider}</span>'
        f' &nbsp;/&nbsp; <span style="color:#7c3aed;font-weight:600;">{kernel.ai_adapter.model}</span></div>',
        unsafe_allow_html=True,
    )

    # ── Stop button ───────────────────────────────────────────────────
    if st.button("⏹ Stop AetheerAI", use_container_width=True, type="secondary"):
        st.warning("Shutting down AetheerAI... You can close this tab.")
        st.toast("AetheerAI stopped.", icon="⏹")
        import time as _t; _t.sleep(1)
        import os as _os; _os._exit(0)

    # ── Bottom user profile strip ─────────────────────────────────────
    st.markdown("""
    <div style='display: flex; align-items: center; gap: 10px; padding: 10px; background: white; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 2px rgba(0,0,0,0.05); margin-top: 8px;'>
        <div style='width: 32px; height: 32px; border-radius: 50%; background: #f1f5f9; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #334155; font-size: 12px;'>TB</div>
        <div>
            <div style='font-size: 14px; font-weight: 700; color: #0f172a;'>Tecbunny</div>
            <div style='font-size: 10px; font-weight: 600; color: #10b981; text-transform: uppercase;'>🟢 Pro Tier</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# 1. TASK EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════
if page == "💬 Task Executor":
    # ── Hero heading (only when chat is empty) ────────────────────────
    history_key_check = f"chat_{_agent_names()[0] if _agent_names() else 'none'}"
    _chat_is_empty = not bool(st.session_state.get(history_key_check))

    if _chat_is_empty:
        st.markdown("<div class='premium-title'>What's next on the agenda?</div>", unsafe_allow_html=True)
        st.markdown("<div class='premium-subtitle'>Deploy autonomous agents to execute complex workflows, generate assets, or analyze data in real-time.</div>", unsafe_allow_html=True)

    names = _agent_names()
    if not names:
        st.warning("No agents found. Go to **Agent Factory** to create one first.")
        st.stop()

    # ── Agent selector — centered pill style ──────────────────────────
    _col_l, _col_c, _col_r = st.columns([1, 2, 1])
    with _col_c:
        selected_agent = st.selectbox("🤖 Agent", names, key="exec_agent_sel", label_visibility="collapsed")

    # Per-agent chat history stored in session state
    history_key = f"chat_{selected_agent}"
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    # ── Suggestion cards (empty state) ───────────────────────────────
    if not st.session_state[history_key]:
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        _s1, _s2 = st.columns(2)
        _suggestion_prompt = None
        with _s1:
            st.markdown('<div class="suggestion-card"><h4>Build a landing page</h4><p>For a new tech startup with a modern design...</p></div>', unsafe_allow_html=True)
            if st.button("Try this →", key="sug1", use_container_width=True, type="secondary"):
                _suggestion_prompt = "Build a landing page for my new tech startup"
        with _s2:
            st.markdown('<div class="suggestion-card"><h4>Analyze Q3 Data</h4><p>Focus on user retention and conversion metrics...</p></div>', unsafe_allow_html=True)
            if st.button("Try this →", key="sug2", use_container_width=True, type="secondary"):
                _suggestion_prompt = "Analyze the Q3 user retention data and highlight key trends"
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        if _suggestion_prompt:
            st.session_state[history_key].append({"role": "user", "content": _suggestion_prompt})
            with st.spinner(f"⚡ {selected_agent} is working..."):
                try:
                    _a = kernel.registry.get(selected_agent)
                    _res = _run_agent_sync(_a, _suggestion_prompt)
                except Exception as _exc:
                    _res = f"**Error:** {_exc}"
            st.session_state[history_key].append({"role": "assistant", "content": str(_res)})
            st.rerun()

    # Show previous messages
    for msg in st.session_state[history_key]:
        _av = "✨" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=_av):
            st.markdown(msg["content"])

    if prompt := st.chat_input(f"Assign a task to {selected_agent}..."):
        st.session_state[history_key].append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="✨"):
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


# ═══════════════════════════════════════════════════════════════════════════
# 6. GOVERNANCE — Intent Manifest & Kill-Switch
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🛡️ Governance":
    st.header("🛡️ Intent Manifest & Kill-Switch Governance")
    st.caption("Define per-agent security boundaries. Violations raise a ManifestViolation and halt execution immediately.")

    from security.intent_manifest import IntentManifest, ManifestViolation

    tab_reg, tab_active, tab_log = st.tabs(["📋 Register Manifest", "🗂️ Active Manifests", "🚨 Violation Log"])

    # ── Tab 1: Register Manifest ──────────────────────────────────────
    with tab_reg:
        st.subheader("Register a Manifest for an Agent")

        agent_names_gov = _agent_names()
        if not agent_names_gov:
            st.info("No agents found. Create an agent in the Agent Factory first.")
        else:
            gov_agent = st.selectbox("Select Agent", agent_names_gov, key="gov_agent_sel")

            st.markdown("**Preset Policies**")
            c1, c2, c3, c4 = st.columns(4)
            preset_chosen = None
            with c1:
                if st.button("🔒 Read-Only", use_container_width=True):
                    preset_chosen = IntentManifest.read_only()
            with c2:
                if st.button("🌐 No Network", use_container_width=True):
                    preset_chosen = IntentManifest.no_network()
            with c3:
                if st.button("👑 Admin", use_container_width=True):
                    preset_chosen = IntentManifest.admin()
            with c4:
                if st.button("💻 Sandboxed Coder", use_container_width=True):
                    preset_chosen = IntentManifest.sandboxed_coder()

            if preset_chosen is not None:
                kernel.register_manifest(gov_agent, preset_chosen)
                st.success(f"Manifest **{preset_chosen.description}** registered for **{gov_agent}**.")

            st.markdown("---")
            st.markdown("**Custom Policy**")

            _all_tools = list(kernel.tool_manager._tools.keys()) if hasattr(kernel.tool_manager, "_tools") else []
            allowed_tools = st.multiselect("Allowed Tools (empty = allow all)", _all_tools, key="gov_allowed_tools")
            denied_tools  = st.multiselect("Denied Tools (always blocked)",  _all_tools, key="gov_denied_tools")
            network_ok    = st.toggle("Allow network operations", value=True, key="gov_network")
            max_calls     = st.slider("Max tool calls per task", 0, 200, 50, key="gov_max_calls")
            desc          = st.text_input("Policy description", value="Custom policy", key="gov_desc")

            if st.button("✅ Register Custom Manifest", type="primary"):
                m = IntentManifest(
                    allowed_tools=set(allowed_tools),
                    denied_tools=set(denied_tools),
                    network_allowed=network_ok,
                    max_tool_calls=max_calls,
                    description=desc,
                )
                kernel.register_manifest(gov_agent, m)
                st.success(f"Custom manifest registered for **{gov_agent}**.")

            if st.button("🗑️ Remove Manifest", type="secondary"):
                kernel.remove_manifest(gov_agent)
                st.success(f"Manifest removed for **{gov_agent}**.")

    # ── Tab 2: Active Manifests ───────────────────────────────────────
    with tab_active:
        st.subheader("Active Agent Manifests")
        manifests = kernel.list_manifests()
        if not manifests:
            st.info("No manifests registered yet.")
        else:
            for agent_name, m in manifests.items():
                with st.expander(f"🤖 **{agent_name}** — {m.get('description', '')}"):
                    st.json(m)

    # ── Tab 3: Violation Log ──────────────────────────────────────────
    with tab_log:
        st.subheader("Manifest Violation Log")
        import json as _json_gov
        _audit_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "audit_log.jsonl")
        if not os.path.exists(_audit_path):
            st.info("No audit log found yet. Violations will be recorded here once they occur.")
        else:
            violations = []
            with open(_audit_path, "r", encoding="utf-8") as _af:
                for line in _af:
                    try:
                        entry = _json_gov.loads(line.strip())
                        if "manifest" in entry.get("event", "").lower() or "violation" in entry.get("event", "").lower():
                            violations.append(entry)
                    except Exception:
                        pass
            if violations:
                st.dataframe(violations, use_container_width=True)
            else:
                st.success("No manifest violations recorded.")

        if st.button("🔄 Reset All Agent Call Counts"):
            for an in _agent_names():
                kernel.reset_agent_call_count(an)
            st.success("All call counts reset.")


# ═══════════════════════════════════════════════════════════════════════════
# 7. INTEROPERABILITY — MCP & A2A
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔗 Interoperability":
    st.header("🔗 MCP & A2A Interoperability Hub")
    st.caption("Connect AetheerAI to external MCP servers and Google A2A agents, or expose its capabilities to them.")

    tab_mcp, tab_a2a, tab_servers, tab_status = st.tabs(
        ["🔌 Connect MCP", "🤝 Connect A2A", "🖥️ Start Servers", "📊 Status"]
    )

    # ── Tab 1: Connect MCP ────────────────────────────────────────────
    with tab_mcp:
        st.subheader("Connect to External MCP Server")
        mcp_url = st.text_input("MCP Server URL", placeholder="http://localhost:8765", key="iop_mcp_url")
        mcp_ns  = st.text_input("Tool Namespace (optional prefix)", placeholder="external_", key="iop_mcp_ns")
        if st.button("🔌 Connect MCP Server", type="primary"):
            if not mcp_url:
                st.warning("Please enter a server URL.")
            else:
                try:
                    tools = kernel.connect_mcp_server(mcp_url, namespace=mcp_ns or "")
                    st.success(f"Connected! Discovered **{len(tools)}** tools from {mcp_url}.")
                    if tools:
                        st.json(list(tools.keys()))
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")

    # ── Tab 2: Connect A2A ────────────────────────────────────────────
    with tab_a2a:
        st.subheader("Connect to A2A Agent")
        a2a_url = st.text_input("Agent Base URL", placeholder="http://localhost:8766", key="iop_a2a_url")
        if st.button("🤝 Fetch Agent Card", type="primary"):
            if not a2a_url:
                st.warning("Please enter an agent URL.")
            else:
                try:
                    client = kernel.connect_a2a_agent(a2a_url)
                    st.success(f"Agent card fetched from {a2a_url}.")
                    if client and hasattr(client, "agent_card") and client.agent_card:
                        st.json(client.agent_card)
                except Exception as exc:
                    st.error(f"Failed: {exc}")

        st.markdown("---")
        st.subheader("Delegate Task to A2A Agent")
        delegate_url  = st.text_input("Agent URL", placeholder="http://localhost:8766", key="iop_delegate_url")
        delegate_task = st.text_area("Task", placeholder="Summarise the quarterly report...", key="iop_delegate_task")
        if st.button("🚀 Delegate Task", type="primary"):
            if not delegate_url or not delegate_task:
                st.warning("Enter both URL and task.")
            else:
                try:
                    result = kernel.delegate_to_agent(delegate_url, delegate_task)
                    st.success("Task delegated successfully.")
                    st.write(result)
                except Exception as exc:
                    st.error(f"Delegation failed: {exc}")

    # ── Tab 3: Start Servers ──────────────────────────────────────────
    with tab_servers:
        st.subheader("Expose AetheerAI as MCP Server")
        mcs_host = st.text_input("Host", value="0.0.0.0", key="iop_mcs_host")
        mcs_port = st.number_input("Port", value=8765, min_value=1024, max_value=65535, key="iop_mcs_port")
        if st.button("▶️ Start MCP Server", type="primary"):
            try:
                kernel.start_mcp_server(host=mcs_host, port=int(mcs_port))
                st.success(f"MCP server started on {mcs_host}:{mcs_port}")
            except Exception as exc:
                st.error(f"Failed: {exc}")

        st.markdown("---")
        st.subheader("Expose AetheerAI as A2A Server")
        a2as_host  = st.text_input("Host", value="0.0.0.0", key="iop_a2as_host")
        a2as_port  = st.number_input("Port", value=8766, min_value=1024, max_value=65535, key="iop_a2as_port")
        a2as_agent = st.selectbox("Route tasks to agent", ["(first registered)"] + _agent_names(), key="iop_a2as_agent")
        if st.button("▶️ Start A2A Server", type="primary"):
            target = None if a2as_agent == "(first registered)" else a2as_agent
            try:
                kernel.start_a2a_server(host=a2as_host, port=int(a2as_port), agent_name=target)
                st.success(f"A2A server started on {a2as_host}:{a2as_port}")
            except Exception as exc:
                st.error(f"Failed: {exc}")

    # ── Tab 4: Status ─────────────────────────────────────────────────
    with tab_status:
        st.subheader("Interoperability Status")
        if st.button("🔄 Refresh Status"):
            st.rerun()
        try:
            status = kernel.interop_status()
            col1, col2 = st.columns(2)
            with col1:
                st.metric("MCP Connections", status.get("mcp_connections", 0))
                st.metric("A2A Connections", status.get("a2a_connections", 0))
            with col2:
                st.metric("MCP Server Running", "✅" if status.get("mcp_server_running") else "❌")
                st.metric("A2A Server Running", "✅" if status.get("a2a_server_running") else "❌")
            with st.expander("Full Status JSON"):
                st.json(status)
        except Exception as exc:
            st.error(f"Could not fetch status: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# 8. MEMORY OS — Three-Tier Memory Browser
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🧠 Memory OS":
    st.header("🧠 Three-Tier Memory OS")
    st.caption("Core (volatile) → Recall (LRU disk cache) → Archival (ChromaDB semantic store). Reads auto-promote hits to Core.")

    tab_write, tab_read, tab_search, tab_consolidate, tab_summary = st.tabs(
        ["✍️ Remember", "🔍 Recall", "🔎 Search", "♻️ Consolidate", "📊 Summary"]
    )

    # ── Tab 1: Remember ───────────────────────────────────────────────
    with tab_write:
        st.subheader("Store a Memory")
        mem_key   = st.text_input("Key", placeholder="project:goals", key="mem_key")
        mem_value = st.text_area("Value", placeholder="Build the best agentic OS...", key="mem_val")
        mem_tier  = st.radio("Tier", ["core", "recall", "archival"], horizontal=True, key="mem_tier")
        if st.button("💾 Remember", type="primary"):
            if not mem_key or not mem_value:
                st.warning("Key and value are required.")
            else:
                try:
                    kernel.remember(mem_key, mem_value, tier=mem_tier)
                    st.success(f"Stored **{mem_key}** in **{mem_tier}** tier.")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    # ── Tab 2: Recall ─────────────────────────────────────────────────
    with tab_read:
        st.subheader("Retrieve a Memory")
        recall_key = st.text_input("Key", placeholder="project:goals", key="recall_key")
        if st.button("🔍 Retrieve", type="primary"):
            if not recall_key:
                st.warning("Enter a key.")
            else:
                try:
                    val = kernel.retrieve(recall_key)
                    if val is None:
                        st.info(f"No memory found for key **{recall_key}**.")
                    else:
                        st.success("Found:")
                        st.write(val)
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    # ── Tab 3: Search ─────────────────────────────────────────────────
    with tab_search:
        st.subheader("Semantic Memory Search")
        search_query = st.text_input("Search query", placeholder="quarterly revenue goals", key="mem_search_q")
        search_n     = st.slider("Max results", 1, 20, 5, key="mem_search_n")
        if st.button("🔎 Search", type="primary"):
            if not search_query:
                st.warning("Enter a search query.")
            else:
                try:
                    results = kernel.memory_search(search_query, n_results=search_n)
                    if not results:
                        st.info("No results found.")
                    else:
                        for i, r in enumerate(results, 1):
                            with st.expander(f"Result {i}"):
                                st.write(r)
                except Exception as exc:
                    st.error(f"Search failed: {exc}")

    # ── Tab 4: Consolidate ────────────────────────────────────────────
    with tab_consolidate:
        st.subheader("Consolidate Memory Tiers")
        st.info("Flushing Core → Recall persists hot in-memory keys to disk. Flushing Recall → Archival moves cached entries into ChromaDB for semantic search.")
        flush_c2r = st.toggle("Flush Core → Recall", value=True, key="mem_c2r")
        flush_r2a = st.toggle("Flush Recall → Archival", value=False, key="mem_r2a")
        if st.button("♻️ Consolidate Now", type="primary"):
            try:
                kernel.consolidate_memory(flush_core_to_recall=flush_c2r, flush_recall_to_archival=flush_r2a)
                st.success("Consolidation complete.")
            except Exception as exc:
                st.error(f"Consolidation failed: {exc}")

    # ── Tab 5: Summary ────────────────────────────────────────────────
    with tab_summary:
        st.subheader("Memory Tier Summary")
        if st.button("🔄 Refresh"):
            st.rerun()
        try:
            summary = kernel.memory_summary()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Core Entries",     summary.get("core_entries", 0))
            c2.metric("Recall Entries",   summary.get("recall_entries", 0))
            c3.metric("Recall Capacity",  summary.get("recall_capacity", 0))
            c4.metric("Archival DB",      "✅" if summary.get("archival_available") else "❌")
            with st.expander("Full JSON"):
                st.json(summary)
        except Exception as exc:
            st.error(f"Could not fetch memory summary: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# 9. SELF-HEALER — Autonomous Self-Healing Debugger
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔥 Self-Healer":
    st.header("🔥 Autonomous Self-Healing Debugger")
    st.caption("When agents fail after all self-correction retries, the Self-Healer diagnoses the root cause via the Master AI and generates a patched task automatically.")

    # ── Controls ──────────────────────────────────────────────────────
    st.subheader("Controls")
    healing_enabled = st.toggle(
        "Enable Self-Healing",
        value=(kernel.self_healer is not None),
        key="sh_enabled",
    )
    max_cycles = st.slider("Max Healing Cycles", 1, 5, 2, key="sh_max_cycles")

    if st.button("💾 Apply Settings", type="primary"):
        kernel.set_self_healing(enabled=healing_enabled, max_cycles=max_cycles)
        st.success(f"Self-healing {'enabled' if healing_enabled else 'disabled'} with max {max_cycles} cycle(s).")

    # ── Status ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Current Status")
    _sh = kernel.self_healer
    if _sh is None:
        st.warning("Self-Healer is **disabled**. Toggle above and apply settings to enable.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Status", "✅ Active")
        c2.metric("Max Cycles", _sh.max_healing_cycles)

    # ── Healing Log ───────────────────────────────────────────────────
    st.divider()
    st.subheader("Healing Log")
    if st.button("🔄 Refresh Log"):
        st.rerun()

    _sh_active = kernel.self_healer
    if _sh_active is not None and hasattr(_sh_active, "_history"):
        history = _sh_active._history
        if not history:
            st.info("No healing sessions recorded yet.")
        else:
            total_healed = sum(1 for r in history.values() if r.healed)
            total_failed = len(history) - total_healed
            h1, h2, h3 = st.columns(3)
            h1.metric("Total Sessions", len(history))
            h2.metric("Healed", total_healed)
            h3.metric("Failed", total_failed)

            for task_id, record in list(history.items())[-20:]:
                icon = "✅" if record.healed else "❌"
                with st.expander(f"{icon} Task: {task_id[:60]}..."):
                    st.markdown(f"**Agent:** {record.agent_name}")
                    st.markdown(f"**Healed:** {record.healed} | **Cycles used:** {record.cycles_used}")
                    for i, cycle in enumerate(record.cycles, 1):
                        st.markdown(f"**Cycle {i}:**")
                        st.markdown(f"- Root Cause: {cycle.get('root_cause', 'N/A')}")
                        st.markdown(f"- Patch: {cycle.get('patch_instructions', 'N/A')}")
                        st.markdown(f"- Outcome: {cycle.get('outcome', 'N/A')}")
    else:
        st.info("Enable Self-Healing and run some agents to see healing history here.")


# ═══════════════════════════════════════════════════════════════════════════
# 10. PRIORITY CONTROLLER — Agent Constitution & Conflict Resolution
# ═══════════════════════════════════════════════════════════════════════════
elif page == "⚖️ Priority Controller":
    st.header("⚖️ Global Priority Controller & Agent Constitution")
    st.caption(
        "Define business rules (the 'Constitution') that govern every agent action. "
        "Conflicts between agents are resolved automatically by priority rank and the Master AI."
    )
    from core.priority_controller import ConstitutionRule, ActionOutcome

    tab_rules, tab_ctx, tab_eval, tab_conflict, tab_history = st.tabs([
        "📜 Rules", "🌐 Context", "🔍 Evaluate Action", "⚔️ Resolve Conflict", "📊 History"
    ])

    # ── Tab 1: Rules ──────────────────────────────────────────────────
    with tab_rules:
        st.subheader("Constitution Rules")
        st.markdown("**Add Preset Rule**")
        pc1, pc2, pc3, pc4 = st.columns(4)
        with pc1:
            if st.button("🔒 Uptime > Cost", use_container_width=True):
                kernel.add_constitution_rule(ConstitutionRule.uptime_over_cost())
                st.success("Rule added: uptime_over_cost")
        with pc2:
            if st.button("🛡️ Security First", use_container_width=True):
                kernel.add_constitution_rule(ConstitutionRule.security_first())
                st.success("Rule added: security_first")
        with pc3:
            if st.button("💰 Billing Approval", use_container_width=True):
                kernel.add_constitution_rule(ConstitutionRule.human_approval_for_billing())
                st.success("Rule added: human_approval_for_billing")
        with pc4:
            if st.button("💾 No Delete w/o Backup", use_container_width=True):
                kernel.add_constitution_rule(ConstitutionRule.no_data_deletion_without_backup())
                st.success("Rule added: no_data_deletion_without_backup")

        st.markdown("---")
        st.markdown("**Custom Rule**")
        r_name      = st.text_input("Rule name (snake_case)", key="cr_name")
        r_text      = st.text_area("Rule text (plain English)", key="cr_text")
        r_priority  = st.slider("Priority (0=lowest, 99=highest)", 0, 99, 50, key="cr_prio")
        r_contexts  = st.text_input("Active contexts (comma-separated, empty=always)", key="cr_ctx")
        r_outcome   = st.selectbox("Violation outcome", ["block", "warn", "escalate", "allow"], key="cr_out")
        if st.button("➕ Add Custom Rule", type="primary"):
            if not r_name or not r_text:
                st.warning("Name and rule text are required.")
            else:
                from core.priority_controller import ActionOutcome as _AO
                contexts = {c.strip() for c in r_contexts.split(",") if c.strip()}
                rule = ConstitutionRule(
                    name=r_name.strip(),
                    rule_text=r_text.strip(),
                    priority=r_priority,
                    active_contexts=contexts,
                    default_outcome=_AO(r_outcome),
                )
                kernel.add_constitution_rule(rule)
                st.success(f"Rule **{r_name}** added.")

        st.markdown("---")
        st.markdown("**Active Rules**")
        rules = kernel.constitution_rules()
        if not rules:
            st.info("No rules in the Constitution yet.")
        else:
            for r in rules:
                with st.expander(f"[{r['priority']:3d}] {r['name']} — {r.get('default_outcome','')}"):
                    st.write(r["rule_text"])
                    if r["active_contexts"]:
                        st.caption(f"Active in: {', '.join(r['active_contexts'])}")
                    if st.button(f"🗑️ Remove {r['name']}", key=f"del_rule_{r['name']}"):
                        kernel.remove_constitution_rule(r["name"])
                        st.rerun()

    # ── Tab 2: Context ────────────────────────────────────────────────
    with tab_ctx:
        st.subheader("Operational Context")
        stats = kernel.constitution_stats()
        st.metric("Current Context", stats.get("current_context", "default"))
        new_ctx = st.text_input("Set new context", placeholder="product_launch / cost_saving / incident_response", key="ctx_input")
        if st.button("🌐 Switch Context", type="primary"):
            if new_ctx.strip():
                kernel.set_constitution_context(new_ctx.strip())
                st.success(f"Context → **{new_ctx.strip()}**")
            else:
                st.warning("Enter a context name.")
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Evaluations", stats.get("total_evaluations", 0))
        c2.metric("Active Rules", stats.get("active_rules", 0))
        c3.metric("Blocked Actions", stats.get("by_outcome", {}).get("block", 0))

    # ── Tab 3: Evaluate Action ────────────────────────────────────────
    with tab_eval:
        st.subheader("Evaluate a Proposed Action")
        ev_agent  = st.selectbox("Agent", _agent_names() or ["(none)"], key="ev_agent")
        ev_action = st.text_area("Describe the action the agent wants to take", key="ev_action")
        if st.button("⚖️ Evaluate", type="primary"):
            if not ev_action.strip():
                st.warning("Describe the action.")
            else:
                with st.spinner("Consulting the Constitution..."):
                    try:
                        decision = kernel.evaluate_action(ev_agent, ev_action.strip())
                        outcome  = decision.get("outcome", "warn")
                        if outcome == "allow":
                            st.success(f"✅ **ALLOWED** — {decision.get('reasoning', '')}")
                        elif outcome == "warn":
                            st.warning(f"⚠️ **WARNED** — {decision.get('reasoning', '')}")
                        elif outcome == "block":
                            st.error(f"🚫 **BLOCKED** — {decision.get('reasoning', '')}")
                        else:
                            st.info(f"⏫ **ESCALATE** — {decision.get('reasoning', '')}")
                        if decision.get("violated_rule"):
                            st.caption(f"Violated rule: **{decision['violated_rule']}**")
                    except Exception as exc:
                        st.error(f"Evaluation failed: {exc}")

    # ── Tab 4: Resolve Conflict ───────────────────────────────────────
    with tab_conflict:
        st.subheader("Resolve Agent Conflict")
        agents_list = _agent_names()
        col_a, col_b = st.columns(2)
        with col_a:
            conf_a = st.selectbox("Agent A", agents_list or ["(none)"], key="conf_a")
            act_a  = st.text_area("Agent A wants to...", key="act_a")
        with col_b:
            conf_b = st.selectbox("Agent B", agents_list or ["(none)"], key="conf_b")
            act_b  = st.text_area("Agent B wants to...", key="act_b")
        if st.button("⚔️ Resolve Conflict", type="primary"):
            if not act_a.strip() or not act_b.strip():
                st.warning("Describe both actions.")
            else:
                with st.spinner("The Constitution deliberates..."):
                    try:
                        res = kernel.resolve_agent_conflict(conf_a, act_a.strip(), conf_b, act_b.strip())
                        st.success(f"🏆 **Winner:** {res['winner']}")
                        st.error(f"🚫 **Blocked:** {res['loser']} — _{res['losing_action'][:120]}_")
                        st.info(f"**Reasoning:** {res['reasoning']}")
                    except Exception as exc:
                        st.error(f"Conflict resolution failed: {exc}")

    # ── Tab 5: History ────────────────────────────────────────────────
    with tab_history:
        st.subheader("Evaluation History")
        if st.button("🔄 Refresh"):
            st.rerun()
        history = kernel.constitution_history(limit=100)
        if not history:
            st.info("No evaluations yet.")
        else:
            import pandas as _pd_pc
            df = _pd_pc.DataFrame(history)
            st.dataframe(df[["agent_name", "outcome", "violated_rule", "reasoning"]].head(50), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 11. STATE CHECKPOINTING — Time-Travel Debugging
# ═══════════════════════════════════════════════════════════════════════════
elif page == "⏱️ Checkpointing":
    st.header("⏱️ Time-Travel Debugging & State Checkpointing")
    st.caption(
        "Every pipeline step is saved as a checkpoint. Rewind to any prior step, "
        "edit the task, and resume — no more restarting from Step 1 after a Step 10 failure."
    )

    tab_sessions, tab_rewind, tab_branch = st.tabs(["📂 Sessions", "⏪ Rewind", "🍴 Branch"])

    # ── Tab 1: Sessions ───────────────────────────────────────────────
    with tab_sessions:
        st.subheader("Checkpoint Sessions")
        if st.button("🆕 Start New Session"):
            sid = kernel.new_checkpoint_session()
            st.success(f"New session started: `{sid[:8]}…`")
            st.rerun()

        sessions = kernel.list_checkpoint_sessions()
        if not sessions:
            st.info("No checkpoint sessions yet. Run a pipeline to create one.")
        else:
            sel_session = st.selectbox("Select session", sessions, key="cp_sess_sel")
            summary = kernel.checkpoint_session_summary(sel_session)
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Steps", summary.get("steps", 0))
            c2.metric("Latest Step", summary.get("latest_step") or "—")
            c3.metric("Latest Agent", summary.get("latest_agent") or "—")

            cps = kernel.list_checkpoints(sel_session)
            if cps:
                for cp in cps:
                    with st.expander(f"Step {cp['step']} — {cp['agent_name']} — {cp['checkpoint_id'][:8]}…"):
                        st.markdown(f"**Task:** {cp['task'][:300]}")
                        st.markdown(f"**Result:** {cp['result'][:300]}")
                        st.caption(f"ID: `{cp['checkpoint_id']}`")

            if st.button(f"🗑️ Delete session {sel_session[:8]}…", type="secondary"):
                n = kernel.delete_checkpoint_session(sel_session)
                st.success(f"Deleted {n} checkpoint(s).")
                st.rerun()

    # ── Tab 2: Rewind ─────────────────────────────────────────────────
    with tab_rewind:
        st.subheader("Rewind to a Checkpoint")
        rw_id = st.text_input("Checkpoint ID (full UUID)", key="rw_id")
        rw_task = st.text_area("Revised task (leave empty to use original)", key="rw_task")
        if st.button("⏪ Rewind", type="primary"):
            if not rw_id.strip():
                st.warning("Enter a checkpoint ID.")
            else:
                try:
                    cp = kernel.rewind_to_checkpoint(
                        rw_id.strip(),
                        revised_task=rw_task.strip() or None,
                    )
                    st.success(f"Rewound to step {cp['step']} | agent: {cp['agent_name']}")
                    st.markdown("**Restored task:**")
                    st.code(cp["task"], language="text")
                    st.info("Copy the task and run it via the Task Executor to resume from this point.")
                except KeyError as exc:
                    st.error(f"Checkpoint not found: {exc}")
                except Exception as exc:
                    st.error(f"Rewind failed: {exc}")

    # ── Tab 3: Branch ─────────────────────────────────────────────────
    with tab_branch:
        st.subheader("Branch from a Checkpoint")
        br_id = st.text_input("Checkpoint ID to branch from", key="br_id")
        if st.button("🍴 Create Branch", type="primary"):
            if not br_id.strip():
                st.warning("Enter a checkpoint ID.")
            else:
                try:
                    new_session = kernel.branch_from_checkpoint(br_id.strip())
                    st.success(f"Branch created! New session: `{new_session[:8]}…`")
                    st.info("Run your pipeline in the new session to explore an alternate path.")
                except KeyError as exc:
                    st.error(f"Checkpoint not found: {exc}")
                except Exception as exc:
                    st.error(f"Branch failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# 12. SWARM INTELLIGENCE — P2P Agent Bus
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🐝 Swarm Bus":
    st.header("🐝 Swarm Intelligence — P2P Agent Bus")
    st.caption(
        "Agents communicate directly with each other via the Swarm Bus, "
        "reducing Master AI load. Broadcast needs, find volunteers, "
        "and route tasks peer-to-peer."
    )

    tab_caps, tab_broadcast, tab_volunteer, tab_inbox, tab_status = st.tabs([
        "🧩 Capabilities", "📢 Broadcast", "🙋 Request Help", "📬 Inbox", "📊 Stats"
    ])

    # ── Tab 1: Register Capabilities ─────────────────────────────────
    with tab_caps:
        st.subheader("Register Agent Capabilities")
        sw_agent = st.selectbox("Agent", _agent_names() or ["(none)"], key="sw_agent")
        sw_topics = st.text_input("Topics (comma-separated)", placeholder="code_review,debugging,testing", key="sw_topics")
        sw_desc   = st.text_input("Description", placeholder="Senior code reviewer", key="sw_desc")
        sw_prio   = st.slider("Priority (higher = preferred volunteer)", 1, 100, 50, key="sw_prio")
        if st.button("✅ Register", type="primary"):
            topics = [t.strip() for t in sw_topics.split(",") if t.strip()]
            if not topics:
                st.warning("Enter at least one topic.")
            else:
                kernel.swarm_register(sw_agent, topics, description=sw_desc, priority=sw_prio)
                st.success(f"**{sw_agent}** registered for: {topics}")

        st.divider()
        st.subheader("Current Capabilities")
        caps = kernel.swarm_capabilities()
        if not caps:
            st.info("No agent capabilities registered yet.")
        else:
            for agent, topics in caps.items():
                st.markdown(f"**{agent}**: {', '.join(topics)}")

    # ── Tab 2: Broadcast ──────────────────────────────────────────────
    with tab_broadcast:
        st.subheader("Broadcast to a Topic")
        bc_topic   = st.text_input("Topic", placeholder="project_update", key="bc_topic")
        bc_payload = st.text_area("Message payload", key="bc_payload")
        bc_sender  = st.selectbox("Sender", _agent_names() or ["(none)"], key="bc_sender")
        if st.button("📢 Broadcast", type="primary"):
            if not bc_topic.strip() or not bc_payload.strip():
                st.warning("Topic and payload required.")
            else:
                received = kernel.swarm_broadcast(bc_topic.strip(), bc_payload.strip(), bc_sender)
                st.success(f"Message delivered to {len(received)} agent(s): {received}")

    # ── Tab 3: Request Help (Volunteer) ──────────────────────────────
    with tab_volunteer:
        st.subheader("Request Help from a Volunteer")
        vh_topic   = st.text_input("Capability topic needed", placeholder="code_review", key="vh_topic")
        vh_payload = st.text_area("Task payload for the volunteer", key="vh_payload")
        vh_sender  = st.selectbox("Requesting agent", _agent_names() or ["(none)"], key="vh_sender")
        if st.button("🙋 Request Help", type="primary"):
            if not vh_topic.strip() or not vh_payload.strip():
                st.warning("Topic and payload required.")
            else:
                with st.spinner("Finding volunteer..."):
                    result = kernel.swarm_request_help(vh_topic.strip(), vh_payload.strip(), vh_sender)
                    if result["resolved"]:
                        st.success(f"🙋 Volunteer found: **{result['volunteer']}**")
                        st.info(f"Message delivered to {result['volunteer']}'s inbox.")
                    else:
                        st.warning(f"No volunteer available for topic **{vh_topic.strip()}**.")

    # ── Tab 4: Read Inbox ─────────────────────────────────────────────
    with tab_inbox:
        st.subheader("Read Agent Inbox")
        inbox_agent = st.selectbox("Agent", _agent_names() or ["(none)"], key="inbox_agent")
        if st.button("📬 Read Messages", type="primary"):
            msgs = kernel.swarm_get_messages(inbox_agent, unread_only=True)
            if not msgs:
                st.info(f"No unread messages for **{inbox_agent}**.")
            else:
                for m in msgs:
                    with st.expander(f"[{m['topic']}] from {m['sender']} — {m['message_id'][:8]}…"):
                        st.write(m["payload"])

    # ── Tab 5: Stats ──────────────────────────────────────────────────
    with tab_status:
        st.subheader("Swarm Bus Statistics")
        if st.button("🔄 Refresh"):
            st.rerun()
        stats = kernel.swarm_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("Registered Agents", stats.get("registered_agents", 0))
        c2.metric("Topics", stats.get("topics", 0))
        c3.metric("Total Messages", stats.get("total_messages", 0))
        pending = stats.get("pending_inboxes", {})
        if pending:
            st.markdown("**Unread messages per agent:**")
            for agent, count in pending.items():
                st.markdown(f"- **{agent}**: {count} unread")


# ═══════════════════════════════════════════════════════════════════════════
# 13. TOOL SYNTHESIZER — JIT Tool Creation
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔨 Tool Synthesizer":
    st.header("🔨 Just-in-Time Tool Synthesis")
    st.caption(
        "Give the Master AI an API documentation snippet and it will write a Python "
        "tool function, validate it for security, and register it live — "
        "no deployment required."
    )

    tab_synth, tab_list, tab_source = st.tabs(["⚗️ Synthesize", "📋 Synthesized Tools", "🔍 View Source"])

    # ── Tab 1: Synthesize ─────────────────────────────────────────────
    with tab_synth:
        st.subheader("Generate a New Tool")
        ts_name = st.text_input(
            "Tool name (snake_case)", placeholder="stripe_charge_tool", key="ts_name"
        )
        ts_desc = st.text_input(
            "Description", placeholder="Create a Stripe payment charge", key="ts_desc"
        )
        ts_doc = st.text_area(
            "API Documentation",
            placeholder="Paste API docs, cURL examples, or OpenAPI YAML here…",
            height=250,
            key="ts_doc",
        )
        st.info(
            "Security note: Generated code is AST-validated before execution. "
            "Only stdlib imports allowed (json, urllib, re, datetime, base64)."
        )
        if st.button("⚗️ Synthesize Tool", type="primary"):
            if not ts_name.strip() or not ts_doc.strip():
                st.warning("Tool name and API documentation are required.")
            else:
                with st.spinner(f"Synthesizing **{ts_name.strip()}**…"):
                    try:
                        result = kernel.synthesize_tool(
                            name=ts_name.strip(),
                            api_doc=ts_doc.strip(),
                            description=ts_desc.strip(),
                        )
                        st.success(
                            f"✅ Tool **{result['name']}** synthesized and registered! "
                            f"All agents can now use it."
                        )
                        st.json(result)
                    except Exception as exc:
                        st.error(f"Synthesis failed: {exc}")

    # ── Tab 2: List Synthesized Tools ─────────────────────────────────
    with tab_list:
        st.subheader("All Synthesized Tools")
        if st.button("🔄 Refresh"):
            st.rerun()
        tools = kernel.list_synthesized_tools()
        if not tools:
            st.info("No tools synthesized yet.")
        else:
            for t in tools:
                with st.expander(f"🔧 **{t['name']}** — {t['description'][:80]}"):
                    st.caption(f"API doc: {t['api_doc_snippet'][:200]}")
                    if st.button(f"🗑️ Delete {t['name']}", key=f"del_tool_{t['name']}"):
                        kernel.delete_synthesized_tool(t["name"])
                        st.success(f"Deleted **{t['name']}**.")
                        st.rerun()

    # ── Tab 3: View Source ────────────────────────────────────────────
    with tab_source:
        st.subheader("View Synthesized Tool Source Code")
        tools = kernel.list_synthesized_tools()
        if not tools:
            st.info("No synthesized tools to inspect.")
        else:
            src_sel = st.selectbox("Select tool", [t["name"] for t in tools], key="src_sel")
            source  = kernel.get_synthesized_tool_source(src_sel)
            if source:
                st.code(source, language="python")
            else:
                st.warning("Source not found.")


# ═══════════════════════════════════════════════════════════════════════════
# 14. COMPUTER USE — Multi-Modal GUI Navigation
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🖥️ Computer Use":
    st.header("🖥️ Multi-Modal Computer Use")
    st.caption(
        "Give AetheerAI eyes and hands. It captures the screen, uses AI vision to "
        "understand it, and controls the mouse/keyboard to achieve your goal — "
        "integrating with any legacy app that has no API."
    )

    tab_nav, tab_screen, tab_config, tab_log = st.tabs([
        "🎯 Navigate", "📸 Screenshot", "⚙️ Configuration", "📋 Action Log"
    ])

    # ── Tab 1: Navigate ───────────────────────────────────────────────
    with tab_nav:
        st.subheader("Autonomous Navigation")
        cu_status = kernel.computer_status()
        mode_badge = "🔵 DRY RUN" if cu_status.get("dry_run") else "🟢 LIVE"
        st.markdown(f"**Mode:** {mode_badge}")

        cu_goal  = st.text_area(
            "Goal",
            placeholder="Open Notepad and type 'Hello from AetheerAI'",
            key="cu_goal",
        )
        cu_steps = st.slider("Max steps", 1, 30, 10, key="cu_steps")

        if not cu_status.get("dry_run"):
            st.warning(
                "⚠️ **LIVE MODE**: AetheerAI will control your mouse and keyboard. "
                "Make sure the correct app window is visible. "
                "Press **ESC** in the terminal to abort pyautogui at any time."
            )

        if st.button("🎯 Start Navigation", type="primary"):
            if not cu_goal.strip():
                st.warning("Enter a goal.")
            else:
                with st.spinner(f"Navigating toward: _{cu_goal.strip()[:80]}_"):
                    try:
                        result = kernel.computer_navigate(cu_goal.strip(), max_steps=cu_steps)
                        if result["achieved"]:
                            st.success(
                                f"✅ Goal achieved in **{result['steps_taken']}** step(s) "
                                f"({result['elapsed_secs']:.1f}s)"
                            )
                        else:
                            st.warning(
                                f"Goal not achieved within {cu_steps} steps. "
                                f"Last screen state: {result['final_result'][:200]}"
                            )

                        if "action_log" in st.session_state:
                            st.session_state["cu_action_log"] = result["action_log"]
                        else:
                            st.session_state["cu_action_log"] = result["action_log"]

                        with st.expander("Action Log"):
                            for entry in result["action_log"]:
                                icon = "✅" if entry.get("success") else "❌"
                                st.markdown(
                                    f"{icon} **Step {entry.get('step','')}** "
                                    f"— {entry.get('action_type','')} "
                                    f"— _{entry.get('reasoning','')}_"
                                )
                    except Exception as exc:
                        st.error(f"Navigation failed: {exc}")

    # ── Tab 2: Screenshot ─────────────────────────────────────────────
    with tab_screen:
        st.subheader("Live Screenshot & AI Description")
        if st.button("📸 Capture Screen", type="primary"):
            with st.spinner("Capturing..."):
                img_b64 = kernel.computer_screenshot()
                desc    = kernel.computer_describe_screen()
            if img_b64:
                import base64 as _b64_cu
                st.image(
                    f"data:image/png;base64,{img_b64}",
                    caption="Current screen",
                    use_container_width=True,
                )
            else:
                st.info("Screen capture unavailable. Install `mss` or `Pillow` for live screenshots.")
            st.markdown("**AI Description:**")
            st.write(desc)

    # ── Tab 3: Configuration ──────────────────────────────────────────
    with tab_config:
        st.subheader("Computer Use Configuration")
        cu_s = kernel.computer_status()

        c1, c2, c3 = st.columns(3)
        c1.metric("Screen", f"{cu_s.get('screen_width','?')} × {cu_s.get('screen_height','?')}")
        c2.metric("pyautogui", "✅" if cu_s.get("pyautogui_ok") else "❌ not installed")
        c3.metric("mss", "✅" if cu_s.get("mss_ok") else "❌ not installed")

        new_dry    = st.toggle("Dry Run (plan only, no real input)", value=cu_s.get("dry_run", True), key="cu_dry")
        new_steps  = st.slider("Default max steps", 1, 50, cu_s.get("max_steps", 15), key="cu_max_steps")
        new_approv = st.toggle("Require approval before each action", value=cu_s.get("require_approval", False), key="cu_approv")

        if st.button("💾 Apply Config", type="primary"):
            updated = kernel.computer_configure(
                dry_run=new_dry,
                max_steps=new_steps,
                require_approval=new_approv,
            )
            st.success("Configuration updated.")
            st.json(updated)

        if not cu_s.get("pyautogui_ok") or not cu_s.get("mss_ok"):
            st.warning(
                "Some optional dependencies are missing. "
                "To enable live control:\n"
                "```\npip install mss pyautogui Pillow\n```"
            )

    # ── Tab 4: Action Log ─────────────────────────────────────────────
    with tab_log:
        st.subheader("Last Navigation Action Log")
        log = st.session_state.get("cu_action_log", [])
        if not log:
            st.info("Run a navigation task to see the action log here.")
        else:
            for entry in log:
                icon = "✅" if entry.get("success") else "❌"
                st.markdown(
                    f"{icon} **Step {entry.get('step','')}** | "
                    f"`{entry.get('action_type','')}` "
                    f"at ({entry.get('x','?')}, {entry.get('y','?')}) "
                    f"— _{entry.get('reasoning','')}_"
                )

# ═══════════════════════════════════════════════════════════════════════════
# 15. ZERO-COPY DATA
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🗄️ Zero-Copy Data":
    st.title("🗄️ Zero-Copy Data Connectors")
    st.caption(
        "Sub-agents query live data sources at execution time — "
        "no stale vector-store copies, up to 40% fewer data errors."
    )

    tab_reg, tab_query, tab_list = st.tabs(["➕ Register Connector", "🔎 Live Query", "📋 Connectors"])

    # ── Tab 1: Register ───────────────────────────────────────────────
    with tab_reg:
        st.subheader("Register a Live Data Connector")
        kind = st.selectbox("Connector type", ["sql", "rest", "file", "bigquery", "salesforce"])
        conn_name = st.text_input("Connector name", placeholder="e.g. orders_db")

        if kind == "sql":
            conn_str = st.text_input(
                "Connection string",
                placeholder="postgresql://user:pass@host/db  or  sqlite:///data.db",
            )
            max_rows = st.number_input("Max rows returned", min_value=1, max_value=50_000, value=5_000)
            kwargs = {"connection_string": conn_str, "max_rows": int(max_rows)}

        elif kind == "rest":
            base_url = st.text_input("Base URL", placeholder="https://api.example.com")
            response_key = st.text_input("Response key (dot-path, optional)", placeholder="data.items")
            raw_headers = st.text_area("Headers (JSON)", height=80, placeholder='{"Authorization": "Bearer TOKEN"}')
            try:
                headers = __import__("json").loads(raw_headers) if raw_headers.strip() else {}
            except Exception:
                headers = {}
                st.warning("Headers JSON is invalid — using empty headers.")
            kwargs = {"base_url": base_url, "headers": headers, "response_key": response_key or None}

        elif kind == "file":
            file_path = st.text_input("Absolute file path", placeholder="C:/data/orders.csv")
            kwargs = {"file_path": file_path}

        elif kind == "bigquery":
            bq_project = st.text_input("GCP Project ID")
            bq_creds = st.text_input("Service account JSON path (blank = ADC)")
            kwargs = {"project": bq_project, "credentials_path": bq_creds or None}

        elif kind == "salesforce":
            sf_user = st.text_input("Username")
            sf_pass = st.text_input("Password", type="password")
            sf_token = st.text_input("Security token", type="password")
            sf_domain = st.selectbox("Domain", ["login", "test"])
            kwargs = {"username": sf_user, "password": sf_pass, "security_token": sf_token, "domain": sf_domain}

        c1, c2 = st.columns(2)
        if c1.button("✅ Register & Test", type="primary", use_container_width=True):
            if not conn_name.strip():
                st.error("Please enter a connector name.")
            else:
                try:
                    result = kernel.zc_register(conn_name.strip(), kind, **kwargs)
                    test = kernel.zc_test(conn_name.strip())
                    ok = test.get(conn_name.strip(), {}).get("ok", False)
                    msg = test.get(conn_name.strip(), {}).get("message", "")
                    if ok:
                        st.success(f"✅ Connector **{conn_name}** registered and connected. {msg}")
                    else:
                        st.warning(f"⚠ Connector registered but connection test failed: {msg}")
                except Exception as exc:
                    st.error(f"Registration error: {exc}")

        if c2.button("🗑 Unregister", use_container_width=True):
            if conn_name.strip():
                removed = kernel.zc_unregister(conn_name.strip())
                st.success("Removed." if removed else "Connector not found.")

    # ── Tab 2: Live Query ─────────────────────────────────────────────
    with tab_query:
        st.subheader("Execute a Live Query")
        connectors = kernel.zc_list()
        if not connectors:
            st.info("No connectors registered yet. Add one in the **Register** tab.")
        else:
            conn_options = [c["name"] for c in connectors]
            selected = st.selectbox("Connector", conn_options)
            statement = st.text_area(
                "Query / statement",
                height=100,
                placeholder="SELECT * FROM orders WHERE status = 'open' LIMIT 50",
            )
            raw_params = st.text_input("Parameters (JSON)", placeholder='{"status": "open"}')
            try:
                params = __import__("json").loads(raw_params) if raw_params.strip() else None
            except Exception:
                params = None
                st.warning("Parameters JSON is invalid — ignoring.")

            if st.button("▶ Run Live Query", type="primary"):
                try:
                    rows = kernel.zc_query(selected, statement, params)
                    st.success(f"{len(rows)} rows returned (live, zero-copy).")
                    if rows:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(rows), use_container_width=True)
                except Exception as exc:
                    st.error(f"Query error: {exc}")

    # ── Tab 3: Connectors list ────────────────────────────────────────
    with tab_list:
        st.subheader("Registered Connectors")
        rows_list = kernel.zc_list()
        if not rows_list:
            st.info("No connectors registered.")
        else:
            for c in rows_list:
                with st.expander(f"🔌 **{c['name']}** — {c.get('kind','?').upper()}"):
                    st.json(c)
            if st.button("🧪 Test All Connectors"):
                results = kernel.zc_test()
                for name, res in results.items():
                    icon = "✅" if res.get("ok") else "❌"
                    st.write(f"{icon} **{name}**: {res.get('message')}")


# ═══════════════════════════════════════════════════════════════════════════
# 16. RED-TEAM SECURITY
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔴 Red-Team Security":
    st.title("🔴 Autonomous Red-Team Security")
    st.caption(
        "Spawn an adversarial sub-agent to probe new integrations for "
        "prompt injection, data exfiltration, privilege escalation, and "
        "other enterprise attack vectors — before any system goes live."
    )

    tab_run, tab_attacks, tab_history = st.tabs(["🚨 Run Red-Team", "⚔ Attack Library", "📜 History"])

    # ── Tab 1: Run ────────────────────────────────────────────────────
    with tab_run:
        st.subheader("Launch Adversarial Test")
        target_desc = st.text_area(
            "Target system description",
            height=120,
            placeholder=(
                "e.g. An email-processing agent that reads inbound emails, "
                "extracts order data, and writes it to a Salesforce CRM system."
            ),
        )
        extra_ctx = st.text_area(
            "Extra context (optional — agent instructions, system prompt, etc.)",
            height=80,
        )

        all_attacks = kernel.red_team_list_attacks()
        attack_names = {a["id"]: a["name"] for a in all_attacks}
        selected_attacks = st.multiselect(
            "Attack scenarios to run (empty = all)",
            options=list(attack_names.keys()),
            format_func=lambda k: attack_names[k],
        )

        col1, col2 = st.columns([3, 1])
        run_btn = col1.button("🔴 Run Red-Team Evaluation", type="primary", use_container_width=True)

        if run_btn:
            if not target_desc.strip():
                st.error("Please describe the target system.")
            else:
                with st.spinner("Red-Teamer agent is probing the system..."):
                    try:
                        loop = asyncio.new_event_loop()
                        report = loop.run_until_complete(
                            asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: kernel.red_team_run_report(
                                    target_desc,
                                    attack_ids=selected_attacks or None,
                                    extra_context=extra_ctx,
                                ),
                            )
                        )
                        loop.close()
                    except Exception:
                        report = kernel.red_team_run_report(
                            target_desc,
                            attack_ids=selected_attacks or None,
                            extra_context=extra_ctx,
                        )

                    st.session_state["rt_last_report"] = report

                    sev_color = {
                        "PASS": "🟢", "LOW": "🟡", "MEDIUM": "🟠",
                        "HIGH": "🔴", "CRITICAL": "🚨",
                    }.get(report.severity, "⚪")
                    if report.passed:
                        st.success(f"{sev_color} All tests passed — no vulnerabilities found.")
                    else:
                        vuln_count = sum(1 for f in report.findings if f.vulnerable)
                        st.error(
                            f"{sev_color} **{vuln_count} vulnerabilities** detected "
                            f"| Severity: **{report.severity}** "
                            f"| Duration: {report.duration_s}s"
                        )

        report = st.session_state.get("rt_last_report")
        if report:
            st.markdown("---")
            st.subheader("Security Report")
            st.markdown(report.to_markdown())

            dl_data = report.to_markdown()
            st.download_button(
                "⬇ Download Report (Markdown)",
                data=dl_data,
                file_name=f"red_team_report_{int(report.started_at)}.md",
                mime="text/markdown",
            )

    # ── Tab 2: Attack Library ─────────────────────────────────────────
    with tab_attacks:
        st.subheader("Built-in Attack Scenarios")
        for attack in all_attacks:
            with st.expander(f"⚔ **{attack['name']}**  `{attack['id']}`"):
                st.write(attack["description"])

    # ── Tab 3: History ────────────────────────────────────────────────
    with tab_history:
        st.subheader("Red-Team Audit Log")
        st.info("Red-team events are logged to the Governance Audit Log.")
        if st.button("📋 View Audit Log"):
            st.switch_page = None  # placeholder — direct users to Governance page
            st.info("Navigate to **🛡️ Governance** → Audit Log to see red-team events.")


# ═══════════════════════════════════════════════════════════════════════════
# 17. ASSEMBLY LINE (Live Trace Graph)
# ═══════════════════════════════════════════════════════════════════════════
elif page == "📡 Assembly Line":
    import time as _time
    import json as _json

    st.title("📡 Assembly Line — Live Trace Graph")
    st.caption(
        "Watch agents collaborate in real time. "
        "See exactly which agent is working, which tool it called, "
        "and where any bottleneck is — the Human-in-the-Loop observability layer."
    )

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])
    auto_refresh = col_ctrl1.toggle("🔄 Auto-refresh", value=False, key="trace_auto_refresh")
    if col_ctrl2.button("🗑 Clear Trace", use_container_width=True):
        kernel.trace_clear()
        st.success("Trace buffer cleared.")
    refresh_rate = col_ctrl3.slider("Refresh interval (s)", 1, 10, 3, key="trace_interval")

    # ── Stats strip ───────────────────────────────────────────────────
    stats = kernel.trace_stats()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Events", stats["total_events"])
    m2.metric("Active Agents", len(stats.get("agents", {})))
    m3.metric("Tool Calls", sum(stats.get("tools_called", {}).values()))
    m4.metric("Errors", stats["total_errors"])

    st.markdown("---")

    # ── Flowchart (SVG / HTML) ────────────────────────────────────────
    graph = kernel.trace_graph()
    nodes = graph["nodes"]
    edges = graph["edges"]

    STATUS_COLORS = {
        "running": "#2563eb",
        "success": "#16a34a",
        "error": "#dc2626",
        "waiting": "#94a3b8",
    }
    NODE_SHAPES = {"agent": "🤖", "tool": "🔧"}

    if not nodes:
        st.info("No trace events yet. Run a task or pipeline to see the Assembly Line come alive.")
    else:
        # Build a lightweight HTML/CSS flowchart using SVG foreignObject
        node_html = ""
        for i, n in enumerate(nodes):
            color = STATUS_COLORS.get(n.get("status", "waiting"), "#94a3b8")
            icon = NODE_SHAPES.get(n.get("type", "agent"), "📦")
            x = 60 + (i % 5) * 190
            y = 40 + (i // 5) * 110
            node_html += f"""
            <g transform="translate({x},{y})">
              <rect rx="10" ry="10" width="160" height="60"
                    fill="{color}22" stroke="{color}" stroke-width="2"/>
              <text x="80" y="20" text-anchor="middle" font-size="18">{icon}</text>
              <text x="80" y="40" text-anchor="middle" font-size="11"
                    font-family="Inter,sans-serif" fill="#1e293b"
                    font-weight="600">{n['label'][:22]}</text>
              <text x="80" y="55" text-anchor="middle" font-size="9"
                    fill="{color}" font-family="Inter,sans-serif">{n.get('status','').upper()}</text>
            </g>"""

        # Build edge lines (simplified — connect by index for now)
        edge_lines = ""
        node_positions = {}
        for i, n in enumerate(nodes):
            node_positions[n["id"]] = (60 + (i % 5) * 190 + 80, 40 + (i // 5) * 110 + 30)

        for e in edges:
            src = node_positions.get(e["from"])
            dst = node_positions.get(e["to"])
            if src and dst:
                edge_lines += (
                    f'<line x1="{src[0]}" y1="{src[1]}" x2="{dst[0]}" y2="{dst[1]}" '
                    f'stroke="#cbd5e1" stroke-width="1.5" marker-end="url(#arrow)"/>'
                )

        total_rows = max(1, (len(nodes) + 4) // 5)
        svg_h = 40 + total_rows * 110 + 40
        svg = f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{svg_h}"
             viewBox="0 0 1000 {svg_h}" style="background:#f8fafc;border-radius:12px;border:1px solid #e2e8f0;">
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8"
                    refX="6" refY="3" orient="auto">
              <path d="M0,0 L0,6 L9,3 z" fill="#94a3b8"/>
            </marker>
          </defs>
          {edge_lines}
          {node_html}
        </svg>"""
        st.markdown(svg, unsafe_allow_html=True)

    st.markdown("---")

    # ── Event table ───────────────────────────────────────────────────
    st.subheader("Recent Events")
    events = kernel.trace_latest(100)
    if not events:
        st.info("No events in buffer.")
    else:
        import pandas as pd
        df = pd.DataFrame(events)[
            ["event_id", "event_type", "agent_name", "tool_name", "target_agent",
             "status", "duration_ms", "task"]
        ].rename(columns={
            "event_id": "ID", "event_type": "Type", "agent_name": "Agent",
            "tool_name": "Tool", "target_agent": "→ Agent",
            "status": "Status", "duration_ms": "ms", "task": "Task",
        })
        st.dataframe(df, use_container_width=True, height=320)

    # ── Auto-refresh ──────────────────────────────────────────────────
    if auto_refresh:
        _time.sleep(refresh_rate)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# 18. MODEL ROUTER
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🧭 Model Router":
    st.title("🧭 Intelligent Model Router")
    st.caption(
        "Not all tasks need a premium brain. The router matches task complexity "
        "to the most cost-effective model — reducing costs while maintaining quality."
    )

    tab_route, tab_table, tab_history = st.tabs(["🎯 Route a Task", "📊 Routing Table", "📜 History"])

    # ── Tab 1: Route ──────────────────────────────────────────────────
    with tab_route:
        st.subheader("Evaluate Task Complexity & Select Model")
        task_input = st.text_area(
            "Task description",
            height=120,
            placeholder="Describe the task you want the AI to perform...",
        )
        c1, c2 = st.columns(2)
        use_ai = c1.toggle("Use AI scoring (more accurate, ~50 tokens)", value=False)
        force_complexity = c2.selectbox(
            "Force complexity override (optional)",
            ["", "SIMPLE", "MODERATE", "COMPLEX"],
        )
        apply_model = st.toggle(
            "Apply selected model to the AI adapter immediately",
            value=False,
        )

        if st.button("🧭 Analyse & Route", type="primary"):
            if not task_input.strip():
                st.error("Please enter a task description.")
            else:
                with st.spinner("Analysing complexity..."):
                    decision = kernel.route_model(
                        task_input,
                        use_ai_scoring=use_ai,
                        apply=apply_model,
                        force_complexity=force_complexity or None,
                    )

                COMPLEXITY_COLORS = {
                    "SIMPLE": "🟢", "MODERATE": "🟡", "COMPLEX": "🔴",
                }
                COST_TIER_ICONS = {
                    "free-local": "🖥️ Free (Local)",
                    "cheap-cloud": "💸 Cheap Cloud",
                    "premium-cloud": "💎 Premium Cloud",
                }
                cx = decision["complexity"]
                c_icon = COMPLEXITY_COLORS.get(cx, "⚪")
                cost_label = COST_TIER_ICONS.get(decision["cost_tier"], decision["cost_tier"])

                st.markdown(f"""
<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:12px;padding:20px;margin:12px 0;">
  <div style="font-size:22px;font-weight:700;color:#0f172a;">
    {c_icon} {cx} Task
  </div>
  <div style="font-size:14px;color:#475569;margin-top:6px;">
    <strong>Provider:</strong> {decision['provider']} &nbsp;|&nbsp;
    <strong>Model:</strong> {decision['model']} &nbsp;|&nbsp;
    <strong>Cost tier:</strong> {cost_label}
  </div>
  <div style="font-size:13px;color:#64748b;margin-top:8px;">
    <em>{decision['reason']}</em>
  </div>
  <div style="font-size:11px;color:#94a3b8;margin-top:6px;">
    Scored by: {decision['scored_by']}
  </div>
</div>
""", unsafe_allow_html=True)

                if apply_model:
                    st.success(
                        f"✅ AI adapter switched to **{decision['provider']} / {decision['model']}**"
                    )

    # ── Tab 2: Routing Table ──────────────────────────────────────────
    with tab_table:
        st.subheader("Routing Table")
        st.caption("Model priority list per complexity tier. First available provider wins.")
        from core.model_router import _ROUTING_TABLE
        for tier, candidates in _ROUTING_TABLE.items():
            color = {"SIMPLE": "🟢", "MODERATE": "🟡", "COMPLEX": "🔴"}.get(tier, "⚪")
            with st.expander(f"{color} **{tier}**", expanded=True):
                rows = [
                    {"Priority": i + 1, "Provider": p, "Model": m}
                    for i, (p, m) in enumerate(candidates)
                ]
                import pandas as pd
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Tab 3: History ────────────────────────────────────────────────
    with tab_history:
        st.subheader("Routing Decision History")
        history = kernel.route_model_history()
        if not history:
            st.info("No routing decisions recorded yet. Route a task to see history here.")
        else:
            agg_stats = kernel.route_model_stats()
            s1, s2, s3 = st.columns(3)
            s1.metric("Total Routed", agg_stats["total_routed"])
            s2.metric("By Complexity", str(agg_stats["by_complexity"]))
            s3.metric("Unique Models", len(agg_stats["by_model"]))

            import pandas as pd
            df_hist = pd.DataFrame(history)
            st.dataframe(df_hist, use_container_width=True, height=320)

# ═══════════════════════════════════════════════════════════════════════════
# 19. AETHEER GATEWAY
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🚦 Aetheer Gateway":
    st.title("🚦 Aetheer Gateway — Rate-Limiting Agent Proxy")
    st.caption(
        "Prevent agent-triggered API floods. Register destinations with token-bucket "
        "rate limits, send rate-controlled requests, and monitor live traffic metrics."
    )

    tab_reg, tab_send, tab_metrics = st.tabs(
        ["📋 Destinations", "📤 Send Request", "📊 Metrics"]
    )

    with tab_reg:
        st.subheader("Registered Destinations")
        destinations = kernel.gateway_list()
        if not destinations:
            st.info("No gateway destinations registered yet.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(destinations), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Register New Destination")
        with st.form("gw_register_form"):
            c1, c2 = st.columns(2)
            gw_name = c1.text_input("Destination Name", placeholder="my-api")
            gw_url  = c2.text_input("Base URL", placeholder="https://api.example.com")
            c3, c4, c5 = st.columns(3)
            gw_rate  = c3.number_input("Rate (req/s)", min_value=0.1, max_value=100.0, value=5.0, step=0.5)
            gw_burst = c4.number_input("Burst Size", min_value=1, max_value=200, value=10, step=1)
            gw_batch = c5.number_input("Batch Size", min_value=1, max_value=50, value=1, step=1)
            if st.form_submit_button("➕ Register", type="primary"):
                if not gw_name.strip() or not gw_url.strip():
                    st.error("Name and URL are required.")
                else:
                    kernel.gateway_register(
                        name=gw_name.strip(),
                        base_url=gw_url.strip(),
                        rate=float(gw_rate),
                        burst=int(gw_burst),
                        batch_size=int(gw_batch),
                    )
                    st.success(f"✅ Destination **{gw_name}** registered at `{gw_url}`.")
                    st.rerun()

    with tab_send:
        st.subheader("Send Rate-Limited Request")
        destinations = kernel.gateway_list()
        dest_names = [d["name"] for d in destinations] if destinations else []
        if not dest_names:
            st.warning("Register a destination first.")
        else:
            with st.form("gw_send_form"):
                c1, c2 = st.columns(2)
                send_dest   = c1.selectbox("Destination", dest_names)
                send_method = c2.selectbox("Method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
                send_path   = st.text_input("Path", value="/")
                send_body   = st.text_area("Request Body (JSON)", height=120, placeholder="{}")
                if st.form_submit_button("🚀 Send", type="primary"):
                    import json as _json
                    body = None
                    if send_body.strip():
                        try:
                            body = _json.loads(send_body)
                        except Exception:
                            st.error("Invalid JSON body.")
                            st.stop()
                    with st.spinner("Sending (rate-limited)..."):
                        resp = kernel.gateway_send(
                            destination=send_dest,
                            path=send_path,
                            method=send_method,
                            body=body,
                        )
                    color = "green" if resp["ok"] else "red"
                    st.markdown(
                        f'<span style="color:{color};font-weight:700;">HTTP {resp["status"]}</span>',
                        unsafe_allow_html=True,
                    )
                    st.code(resp["text"][:2000], language="json")

    with tab_metrics:
        st.subheader("Live Traffic Metrics")
        metrics = kernel.gateway_metrics()
        if not metrics:
            st.info("No metrics yet. Send some requests first.")
        else:
            for dest, m in metrics.items():
                with st.expander(f"📡 **{dest}**", expanded=True):
                    cols = st.columns(5)
                    cols[0].metric("Sent", m.get("sent", 0))
                    cols[1].metric("Queued Now", m.get("queued", 0))
                    cols[2].metric("Retried", m.get("retried", 0))
                    cols[3].metric("Errors", m.get("errors", 0))
                    cols[4].metric("Avg Latency (ms)", f"{m.get('avg_latency_ms', 0):.0f}")

# ═══════════════════════════════════════════════════════════════════════════
# 20. DUAL-PROCESS ENGINE
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🧠 Dual-Process":
    st.title("🧠 Dual-Process Thinking — System 1 & System 2")
    st.caption(
        "**System 1** is a fast, frozen cheap model for rapid execution. "
        "**System 2** is the Curator Agent — it studies error patterns and "
        "writes permanent lessons to Long-Term Memory, making the system smarter over time."
    )

    tab_s1, tab_s2, tab_stats, tab_lessons = st.tabs(
        ["⚡ System 1 Run", "🧐 System 2 Reflect", "📊 Stats", "📚 Lessons"]
    )

    with tab_s1:
        st.subheader("Run a Task Through System 1 (Fast)")
        with st.form("s1_form"):
            s1_agent = st.text_input("Agent Name", value="GeneralAgent")
            s1_task  = st.text_area("Task", height=130, placeholder="Summarise this document...")
            c1, c2  = st.columns(2)
            s1_type = c1.selectbox("Task Type", ["general", "summarise", "classify", "extract", "qa", "code"])
            s1_sys  = c2.text_input("System Prompt (optional)", placeholder="You are a helpful AI.")
            if st.form_submit_button("⚡ Execute via System 1", type="primary"):
                if not s1_task.strip():
                    st.error("Enter a task.")
                else:
                    with st.spinner("Running S1 (fast model)..."):
                        result = kernel.s1_run(
                            agent_name=s1_agent,
                            task=s1_task,
                            task_type=s1_type,
                            system_prompt=s1_sys,
                        )
                    status = "✅ Success" if result["success"] else "❌ Failed"
                    st.markdown(f"**Status:** {status} &nbsp;|&nbsp; **Model:** `{result['model_used']}` &nbsp;|&nbsp; **Duration:** {result['duration_ms']:.0f}ms")
                    if result["error"]:
                        st.error(result["error"])
                    else:
                        st.markdown("**Result:**")
                        st.markdown(result["result"])

    with tab_s2:
        st.subheader("Run System 2 Curator Reflection")
        st.info(
            "The Curator Agent reviews System 1 errors and distils permanent "
            "lessons. It only runs when enough samples exist (default ≥ 5)."
        )
        with st.form("s2_form"):
            s2_agent = st.text_input("Agent to Reflect On", value="GeneralAgent")
            s2_force = st.toggle("Force reflection even if error rate is low", value=False)
            if st.form_submit_button("🧐 Run System 2 Curator", type="primary"):
                with st.spinner("Curator Agent reflecting..."):
                    report = kernel.s2_reflect(agent_name=s2_agent, force=s2_force)
                if not report["reflected"]:
                    st.warning(f"Reflection skipped: {report['reason']}")
                else:
                    st.success("✅ Reflection complete!")
                    st.metric("Error Rate", f"{report['error_rate']:.1%}")
                    st.markdown("**Pattern Summary:**")
                    st.info(report["pattern_summary"])
                    if report["lessons"]:
                        st.markdown("**Lessons Learned:**")
                        for lesson in report["lessons"]:
                            st.markdown(f"- {lesson}")
                    if report["updated_instructions"]:
                        st.markdown("**Updated Instructions Suggested:**")
                        st.code(report["updated_instructions"])

        st.markdown("---")
        if st.button("🔄 Reflect All Agents"):
            with st.spinner("Running S2 for all agents..."):
                all_reports = kernel.s2_reflect_all()
            if not all_reports:
                st.info("No agents have enough S1 samples for reflection.")
            else:
                for r in all_reports:
                    st.markdown(f"**{r['agent']}** — error rate: `{r['error_rate']:.1%}` — lessons: {len(r['lessons'])}")

    with tab_stats:
        st.subheader("System 1 Outcome Statistics")
        stats = kernel.dual_process_stats()
        if not stats or stats.get("total", 0) == 0:
            st.info("No System 1 runs recorded yet.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Runs", stats.get("total", 0))
            c2.metric("Success Rate", f"{stats.get('success_rate', 0):.1%}")
            c3.metric("Avg Duration", f"{stats.get('avg_duration_ms', 0):.0f}ms")

            by_type = stats.get("by_task_type", {})
            if by_type:
                import pandas as pd
                df = pd.DataFrame(
                    [{"Task Type": k, "Count": v} for k, v in by_type.items()]
                )
                st.bar_chart(df.set_index("Task Type"))

    with tab_lessons:
        st.subheader("Stored S2 Lessons by Agent")
        q_agent = st.text_input("Agent name", value="GeneralAgent", key="lessons_agent")
        if st.button("📚 Load Lessons"):
            lessons = kernel.dual_process_lessons(q_agent)
            if not lessons:
                st.info(f"No lessons stored for **{q_agent}** yet.")
            else:
                for i, lesson in enumerate(lessons, 1):
                    st.markdown(f"{i}. {lesson}")

# ═══════════════════════════════════════════════════════════════════════════
# 21. FINOPS CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════
elif page == "💰 FinOps":
    st.title("💰 FinOps — Cost-Aware AI Orchestration")
    st.caption(
        "Know the price before you run. Get cost quotes, track live spend, "
        "swap models to stay within budget, and see exactly where every dollar goes."
    )

    tab_quote, tab_status, tab_ledger, tab_breakdown = st.tabs(
        ["💵 Cost Quote", "📊 Spend Status", "📒 Ledger", "🔍 Breakdown"]
    )

    with tab_quote:
        st.subheader("Project Cost Quote")
        with st.form("finops_quote_form"):
            c1, c2 = st.columns(2)
            q_tasks  = c1.number_input("Number of Tasks", min_value=1, max_value=10000, value=10, step=1)
            q_agents = c2.number_input("Number of Agents", min_value=1, max_value=100, value=1, step=1)
            cost_table = kernel.finops_model_cost_table()
            model_list = list(cost_table.keys())
            q_model = st.selectbox("Model", model_list, index=0 if model_list else 0)
            c3, c4 = st.columns(2)
            q_tpt    = c3.number_input("Tokens per Task (0 = default)", min_value=0, max_value=200000, value=0, step=500)
            q_budget = c4.number_input("Budget Override USD (0 = use global)", min_value=0.0, value=0.0, step=0.5, format="%.2f")
            if st.form_submit_button("💵 Get Quote", type="primary"):
                quote = kernel.finops_quote(
                    tasks=int(q_tasks),
                    agents=int(q_agents),
                    model=q_model,
                    tokens_per_task=int(q_tpt) if q_tpt > 0 else None,
                    budget_override=float(q_budget) if q_budget > 0 else None,
                )
                bg = "#dcfce7" if quote["within_budget"] else "#fee2e2"
                icon = "✅" if quote["within_budget"] else "⚠️"
                st.markdown(f"""
<div style="background:{bg};border-radius:12px;padding:20px;margin:12px 0;">
  <div style="font-size:20px;font-weight:700;">{icon} Estimated Cost: ${quote['total_usd']:.4f} USD</div>
  <div style="font-size:14px;margin-top:6px;">
    Model: <code>{quote['model']}</code> &nbsp;|&nbsp;
    Tokens: ~{quote['token_estimate']:,}
  </div>
</div>
""", unsafe_allow_html=True)
                if quote.get("optimised_model"):
                    st.info(
                        f"💡 Cheaper alternative: **{quote['optimised_model']}** "
                        f"≈ ${quote['optimised_cost_usd']:.4f} USD"
                    )
                if quote.get("breakdown"):
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(quote["breakdown"]),
                        use_container_width=True,
                        hide_index=True,
                    )

    with tab_status:
        st.subheader("Live Spend vs Budget")
        status = kernel.finops_status()
        c1, c2, c3 = st.columns(3)
        c1.metric("Used (USD)", f"${status['used_usd']:.4f}")
        c2.metric("Budget (USD)", f"${status['budget_usd']:.2f}" if status['budget_usd'] > 0 else "Unlimited")
        c3.metric("Remaining", f"${status['remaining_usd']:.4f}" if status['budget_usd'] > 0 else "—")

        if status["budget_usd"] > 0:
            pct = min(status.get("percent_used", 0), 1.0)
            bar_color = "#ef4444" if pct >= 1.0 else "#f59e0b" if pct >= 0.8 else "#22c55e"
            st.markdown(
                f'<div style="background:#e2e8f0;border-radius:8px;height:18px;width:100%;">'
                f'<div style="background:{bar_color};border-radius:8px;height:18px;'
                f'width:{pct*100:.1f}%;transition:width 0.5s;"></div></div>'
                f'<div style="font-size:12px;color:#64748b;margin-top:4px;">'
                f'{pct*100:.1f}% of budget used</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")
        st.subheader("Set Monthly Budget")
        new_budget = st.number_input(
            "Monthly budget (USD) — set to 0 for unlimited",
            min_value=0.0, value=float(status["budget_usd"]), step=1.0, format="%.2f"
        )
        if st.button("💾 Save Budget"):
            kernel.finops_set_budget(new_budget)
            st.success(f"Budget set to ${new_budget:.2f}/month.")
            st.rerun()

    with tab_ledger:
        st.subheader("Spend Ledger")
        limit = st.slider("Show last N records", 10, 200, 50)
        records = kernel.finops_ledger(limit=limit)
        if not records:
            st.info("No spend recorded yet.")
        else:
            import pandas as pd
            df_l = pd.DataFrame(records)
            st.dataframe(df_l, use_container_width=True, height=400)
            total = sum(r["cost_usd"] for r in records)
            st.metric("Total shown", f"${total:.4f}")

    with tab_breakdown:
        st.subheader("Spend Breakdown")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**By Agent**")
            by_agent = kernel.finops_spend_by_agent()
            if not by_agent:
                st.info("No data yet.")
            else:
                import pandas as pd
                df_a = pd.DataFrame(
                    [{"Agent": k, "Spent (USD)": round(v, 4)} for k, v in by_agent.items()]
                ).sort_values("Spent (USD)", ascending=False)
                st.dataframe(df_a, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**By Model**")
            by_model = kernel.finops_spend_by_model()
            if not by_model:
                st.info("No data yet.")
            else:
                import pandas as pd
                df_m = pd.DataFrame(
                    [{"Model": k, "Spent (USD)": round(v, 4)} for k, v in by_model.items()]
                ).sort_values("Spent (USD)", ascending=False)
                st.dataframe(df_m, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Model Pricing Reference")
        cost_table = kernel.finops_model_cost_table()
        import pandas as pd
        df_ct = pd.DataFrame(
            [
                {
                    "Model": m,
                    "Input $/M tokens": v["input_per_m"],
                    "Output $/M tokens": v["output_per_m"],
                }
                for m, v in cost_table.items()
            ]
        )
        st.dataframe(df_ct, use_container_width=True, height=400, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════
# 22. SEMANTIC CLEANER
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔬 Semantic Cleaner":
    st.title("🔬 Semantic Pre-Processor — Unstructured Data → Clean JSON")
    st.caption(
        "Feed messy PDFs, Zoom transcripts, screenshots, raw HTML, or CSV into "
        "this pre-processor before any agent sees it. Output is clean, structured "
        "JSON + Markdown that agents can reason about accurately."
    )

    tab_clean, tab_batch, tab_types = st.tabs(
        ["🧹 Clean Document", "📦 Batch Clean", "📋 Supported Types"]
    )

    with tab_clean:
        st.subheader("Clean a Single Document")
        col1, col2 = st.columns([2, 1])
        raw_input = col1.text_area(
            "Paste raw content here",
            height=280,
            placeholder="Paste PDF text, transcript, HTML, email, CSV...",
        )
        content_hint = col2.selectbox(
            "Content Type",
            ["auto", "pdf", "transcript", "screenshot", "html", "email", "csv", "json", "text"],
        )
        extra_instr = col2.text_input(
            "Extra instructions (optional)",
            placeholder="Focus on financial figures",
        )

        if st.button("🔬 Clean & Structure", type="primary"):
            if not raw_input.strip():
                st.error("Please paste some content to clean.")
            else:
                with st.spinner("AI pre-processing..."):
                    result = kernel.semantic_clean(
                        raw=raw_input,
                        hint=content_hint,
                        extra_instructions=extra_instr,
                    )

                # Quality badge
                qs = result["quality_score"]
                q_color = "#22c55e" if qs >= 0.7 else "#f59e0b" if qs >= 0.4 else "#ef4444"
                ready_label = "✅ Ready for Agent" if result["ready_for_agent"] else "⚠️ Needs Review"
                st.markdown(
                    f'<div style="display:inline-flex;gap:16px;background:#f8fafc;'
                    f'border-radius:8px;padding:10px 16px;margin-bottom:12px;">'
                    f'<span style="color:{q_color};font-weight:700;">'
                    f'Quality: {qs:.0%}</span>'
                    f'<span>{ready_label}</span>'
                    f'<span style="color:#64748b;">Type: {result["content_type"]}</span>'
                    f'<span style="color:#64748b;">⏱ {result["processing_ms"]:.0f}ms</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if result["warnings"]:
                    for w in result["warnings"]:
                        st.warning(w)

                tab_json, tab_md, tab_agent = st.tabs(
                    ["📋 Structured JSON", "📝 Clean Markdown", "🤖 Agent Input"]
                )
                with tab_json:
                    import json as _json
                    st.code(
                        _json.dumps(result["structured"], indent=2),
                        language="json",
                    )
                with tab_md:
                    st.markdown(result["markdown"])
                with tab_agent:
                    st.caption("This is the exact string to pass to your agent:")
                    st.code(result["agent_input"], language="markdown")

    with tab_batch:
        st.subheader("Batch Clean Multiple Documents")
        st.info(
            "Enter one document per section. Use the '+' button to add more. "
            "All documents are cleaned in sequence."
        )

        if "batch_items" not in st.session_state:
            st.session_state.batch_items = [{"raw": "", "hint": "auto", "extra": ""}]

        for i, item in enumerate(st.session_state.batch_items):
            with st.expander(f"Document {i + 1}", expanded=(i == 0)):
                item["raw"]  = st.text_area(f"Content {i+1}", value=item["raw"], height=120, key=f"b_raw_{i}")
                item["hint"] = st.selectbox(
                    f"Type {i+1}",
                    ["auto", "pdf", "transcript", "html", "email", "csv", "json", "text"],
                    key=f"b_hint_{i}",
                )
                item["extra"] = st.text_input(f"Extra instructions {i+1}", value=item.get("extra", ""), key=f"b_extra_{i}")

        col_add, col_run = st.columns([1, 3])
        if col_add.button("➕ Add Document"):
            st.session_state.batch_items.append({"raw": "", "hint": "auto", "extra": ""})
            st.rerun()

        if col_run.button("🔬 Clean All", type="primary"):
            items_to_clean = [
                {"raw": it["raw"], "hint": it["hint"], "extra_instructions": it.get("extra", "")}
                for it in st.session_state.batch_items
                if it["raw"].strip()
            ]
            if not items_to_clean:
                st.error("No content to clean.")
            else:
                with st.spinner(f"Cleaning {len(items_to_clean)} document(s)..."):
                    batch_results = kernel.semantic_clean_batch(items_to_clean)

                import pandas as pd
                summary = pd.DataFrame([
                    {
                        "#": i + 1,
                        "Type": r["content_type"],
                        "Quality": f"{r['quality_score']:.0%}",
                        "Ready?": "✅" if r["ready_for_agent"] else "⚠️",
                        "Original Chars": r["original_length"],
                        "Markdown Chars": r["markdown_length"],
                        "ms": r["processing_ms"],
                        "Warnings": "; ".join(r["warnings"]) if r["warnings"] else "",
                    }
                    for i, r in enumerate(batch_results)
                ])
                st.dataframe(summary, use_container_width=True, hide_index=True)

    with tab_types:
        st.subheader("Supported Content Types")
        types_info = [
            {"Type": "pdf",        "Description": "PDF text (extracted by pdfplumber/pypdf2)", "Outputs": "title, sections, tables, key-values, action items"},
            {"Type": "transcript", "Description": "Meeting/call/Zoom transcript",               "Outputs": "participants, topics, decisions, action items"},
            {"Type": "screenshot", "Description": "OCR text from screenshots",                  "Outputs": "screen type, text blocks, UI elements, numbers"},
            {"Type": "html",       "Description": "Raw HTML / web page source",                 "Outputs": "title, clean Markdown body, headings, links"},
            {"Type": "email",      "Description": "Email thread or single message",             "Outputs": "subject, from/to, body, sentiment, action items"},
            {"Type": "csv",        "Description": "CSV data (possibly malformed)",              "Outputs": "headers, schema, sample rows, row count"},
            {"Type": "json",       "Description": "Malformed or unvalidated JSON",              "Outputs": "fixed JSON, list of corrections made"},
            {"Type": "text",       "Description": "Any raw/unstructured plain text",            "Outputs": "clean text, key points, entities, summary"},
            {"Type": "auto",       "Description": "Heuristic auto-detection (default)",         "Outputs": "depends on detected type"},
        ]
        import pandas as pd
        st.dataframe(
            pd.DataFrame(types_info),
            use_container_width=True,
            hide_index=True,
        )

# ═══════════════════════════════════════════════════════════════════════════
# 23. CONTROL PLANE
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🎛️ Control Plane":
    st.title("🎛️ Agentic Control Plane — Multi-Agent Orchestration")
    st.caption(
        "The Supreme Court for your agent fleet. Register agents with their goals, "
        "detect conflicting strategies, and let the Master AI issue binding resolutions "
        "based on your core business KPIs."
    )

    tab_board, tab_agents, tab_conflicts, tab_mediate, tab_escalations, tab_collab = st.tabs(
        ["📊 Status Board", "🤖 Agents", "⚡ Conflicts", "⚖️ Mediate", "📋 Escalations", "🔗 Collab Graph"]
    )

    with tab_board:
        board = kernel.cp_status_board()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Agents", board["agents_registered"])
        c2.metric("Conflicts", board["total_conflicts_detected"])
        c3.metric("Unresolved", board["unresolved_conflicts"])
        c4.metric("Open Tickets", board["open_escalations"])
        c5.metric("Resolutions", board["resolutions_issued"])
        if board["high_priority_agents"]:
            st.warning(f"⚠️ High-priority agents: {', '.join(board['high_priority_agents'])}")
        if board["departments"]:
            st.info(f"Departments managed: {', '.join(board['departments'])}")

        st.markdown("---")
        st.subheader("Resolution History")
        history = kernel.cp_resolution_history()
        if not history:
            st.info("No resolutions issued yet.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)

    with tab_agents:
        st.subheader("Registered Agents")
        agents = kernel.cp_list_agents()
        if not agents:
            st.info("No agents registered. Use the form below.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(agents), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Register Agent")
        with st.form("cp_agent_form"):
            c1, c2, c3 = st.columns(3)
            ag_name   = c1.text_input("Agent Name", placeholder="EfficiencyAgent")
            ag_dept   = c2.text_input("Department", placeholder="finance")
            ag_pri    = c3.slider("Priority (1=critical, 10=low)", 1, 10, 5)
            ag_goals  = st.text_area("Goals (one per line)", placeholder="reduce cost by 20%\nminimise API calls")
            ag_kpis   = st.text_area("KPIs (one per line)", placeholder="cost_per_unit\napi_latency_ms")
            ag_dep_on = st.text_input("Depends On (comma-separated agent names, optional)", "")
            if st.form_submit_button("➕ Register Agent", type="primary"):
                if not ag_name.strip():
                    st.error("Agent name is required.")
                else:
                    kernel.cp_register_agent(
                        agent_name  = ag_name.strip(),
                        goals       = [g.strip() for g in ag_goals.strip().splitlines() if g.strip()],
                        kpis        = [k.strip() for k in ag_kpis.strip().splitlines() if k.strip()],
                        priority    = ag_pri,
                        department  = ag_dept.strip() or "general",
                        depends_on  = [x.strip() for x in ag_dep_on.split(",") if x.strip()] or None,
                    )
                    st.success(f"✅ Agent **{ag_name}** registered.")
                    st.rerun()

    with tab_conflicts:
        st.subheader("Open Conflicts")
        if st.button("🔍 Detect Conflicts Now", type="primary"):
            new_c = kernel.cp_detect_conflicts()
            if not new_c:
                st.success("No new conflicts detected.")
            else:
                st.warning(f"⚠️ {len(new_c)} new conflict(s) detected.")
                st.rerun()

        conflicts = kernel.cp_open_conflicts()
        if not conflicts:
            st.info("No unresolved conflicts.")
        else:
            for c in conflicts:
                sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(c["severity"], "⚪")
                with st.expander(f"{sev_icon} [{c['conflict_id']}] {c['description']}", expanded=True):
                    st.markdown(f"**Agents:** {', '.join(c['agents'])}")
                    for ag, goals in c["goals"].items():
                        st.markdown(f"- **{ag}**: {', '.join(goals)}")

    with tab_mediate:
        st.subheader("Supreme Court Mediation")
        st.caption("Select a conflict and configure your business KPIs. The Master AI will issue a binding resolution.")
        conflicts = kernel.cp_open_conflicts()
        if not conflicts:
            st.info("No conflicts to mediate. Detect conflicts first.")
        else:
            conf_options = {f"[{c['conflict_id']}] {c['description'][:60]}": c["conflict_id"] for c in conflicts}
            selected = st.selectbox("Select conflict", list(conf_options.keys()))
            c1, c2 = st.columns(2)
            bkpi_primary   = c1.text_input("Primary Business KPI", value="net_profit")
            bkpi_secondary = c2.text_input("Secondary KPI", value="customer_satisfaction")
            extra_kpis_raw = st.text_input("More KPIs (comma-separated)", "")
            if st.button("⚖️ Issue Resolution", type="primary"):
                bkpis = {"primary": bkpi_primary, "secondary": bkpi_secondary}
                if extra_kpis_raw.strip():
                    for pair in extra_kpis_raw.split(","):
                        parts = pair.split(":", 1)
                        if len(parts) == 2:
                            bkpis[parts[0].strip()] = parts[1].strip()
                with st.spinner("Consulting Supreme Court AI..."):
                    res = kernel.cp_mediate(conf_options[selected], business_kpis=bkpis)
                st.success("✅ Resolution issued!")
                st.markdown(f"**Winning KPI:** `{res['winning_kpi']}`")
                st.info(res["verdict"])
                st.markdown("**Reasoning:**")
                st.markdown(res["reasoning"])
                if res["recommended_actions"]:
                    st.markdown("**Recommended Actions:**")
                    for a in res["recommended_actions"]:
                        st.markdown(f"- {a}")
                if res["override_map"]:
                    st.markdown("**Agent Directives:**")
                    for ag, directive in res["override_map"].items():
                        st.markdown(f"- **{ag}**: {directive}")

    with tab_escalations:
        st.subheader("Escalation Tickets")
        tickets = kernel.cp_open_escalations()
        if not tickets:
            st.info("No open escalations.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(tickets), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Create Escalation")
        with st.form("cp_escalate_form"):
            c1, c2 = st.columns(2)
            esc_agent  = c1.text_input("Agent Name", placeholder="BillingAgent")
            esc_sev    = c2.selectbox("Severity", ["low", "medium", "high", "critical"])
            esc_issue  = st.text_input("Issue", placeholder="Attempted to execute >$10k payment")
            esc_ctx    = st.text_area("Context", height=80)
            if st.form_submit_button("🚨 Escalate", type="primary"):
                t = kernel.cp_escalate(esc_agent.strip(), esc_issue.strip(), esc_ctx.strip(), esc_sev)
                st.success(f"Ticket `{t['ticket_id']}` created.")

    with tab_collab:
        st.subheader("Agent Collaboration Graph (Dependencies)")
        matrix = kernel.cp_collaboration_matrix()
        if not matrix:
            st.info("No dependency edges registered yet. Use 'Depends On' when registering agents.")
        else:
            import pandas as pd
            edges = [{"Agent": a, "Depends On": dep} for a, deps in matrix.items() for dep in deps]
            st.dataframe(pd.DataFrame(edges), use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════
# 24. HUMAN SUPERVISOR
# ═══════════════════════════════════════════════════════════════════════════
elif page == "👤 Human Supervisor":
    st.title("👤 Human-Supervisor Mode — Adaptive Delegation")
    st.caption(
        "Track every approval, detect where *you* are the bottleneck, "
        "and let the AI suggest policy upgrades that hand recurring decisions "
        "to trusted agents — permanently."
    )

    tab_style, tab_record, tab_bottlenecks, tab_policy, tab_events = st.tabs(
        ["🧠 My Style", "✍️ Record Approval", "⚠️ Bottlenecks", "📜 Policies", "📋 Events"]
    )

    with tab_style:
        st.subheader("Your Management Style Analysis")
        report = kernel.hs_management_report()
        if report["total_events"] == 0:
            st.info("Record some approval events to see your management style analysis.")
        else:
            style_colors = {
                "Liberator": "#22c55e", "Delegator": "#3b82f6",
                "Balanced": "#f59e0b", "Hands-On": "#ef4444",
            }
            color = style_colors.get(report["style_label"], "#64748b")
            st.markdown(
                f'<div style="background:{color}22;border:2px solid {color};border-radius:12px;padding:20px;">'
                f'<div style="font-size:24px;font-weight:700;color:{color};">🧠 {report["style_label"]}</div>'
                f'<div style="font-size:14px;margin-top:6px;">{report["style_description"]}</div></div>',
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("Autonomy Score", f"{report['autonomy_score']:.0%}")
            c2.metric("Avg Wait per Approval", f"{report['avg_wait_s']:.0f}s")
            c3.metric("Total Events", report["total_events"])
            if report["bottleneck_categories"]:
                st.warning(f"⚠️ Bottlenecks in: {', '.join(report['bottleneck_categories'])}")
            st.info(f"💡 {report['recommended_next_step']}")

    with tab_record:
        st.subheader("Record an Approval Event")
        with st.form("hs_record_form"):
            c1, c2 = st.columns(2)
            hr_agent    = c1.text_input("Agent Name", placeholder="BillingAgent")
            hr_action   = c2.text_input("Action", placeholder="send_invoice")
            c3, c4      = st.columns(2)
            hr_category = c3.text_input("Category", placeholder="finance")
            hr_wait     = c4.number_input("Time You Took to Decide (seconds)", min_value=0, max_value=86400, value=60, step=5)
            hr_approved = st.toggle("You approved it", value=True)
            hr_auto     = st.toggle("This was auto-approved (no human review)", value=False)
            if st.form_submit_button("✅ Record", type="primary"):
                ev = kernel.hs_record_approval(
                    agent_name   = hr_agent.strip(),
                    action       = hr_action.strip(),
                    category     = hr_category.strip() or "general",
                    wait_ms      = hr_wait * 1000,
                    approved     = hr_approved,
                    auto_approved= hr_auto,
                )
                st.success(f"Recorded event `{ev['event_id']}` in category `{ev['category']}`.")

    with tab_bottlenecks:
        st.subheader("Bottleneck Analysis")
        bottlenecks = kernel.hs_detect_bottlenecks()
        if not bottlenecks:
            st.success("✅ No bottlenecks detected. Your delegation is healthy.")
        else:
            for b in bottlenecks:
                score = b["bottleneck_score"]
                color = "#ef4444" if score > 0.7 else "#f59e0b" if score > 0.4 else "#3b82f6"
                with st.expander(f"⚠️ **{b['category']}** — score {score:.0%}", expanded=True):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Events", b["event_count"])
                    c2.metric("Avg Wait", f"{b['avg_wait_s']:.0f}s")
                    c3.metric("Approval Rate", f"{b['approval_rate']:.0%}")
                    if b["suggestion"]:
                        st.info(f"💡 {b['suggestion']}")
                    if st.button(f"🤖 Get AI Policy Suggestion for '{b['category']}'", key=f"hs_sug_{b['category']}"):
                        with st.spinner("AI generating policy update..."):
                            upd = kernel.hs_suggest_policy(b["category"])
                        if upd:
                            st.success(f"**Suggested:** Upgrade `{b['category']}` from {upd['old_level']} → **{upd['new_level']}**")
                            st.markdown(f"**Reasoning:** {upd['reasoning']}")
                            if upd["conditions"]:
                                st.markdown("**Conditions still required:**")
                                for cond in upd["conditions"]:
                                    st.markdown(f"- {cond}")
                            if st.button(f"✅ Apply this policy", key=f"hs_apply_{b['category']}"):
                                kernel.hs_apply_policy(b["category"], upd["new_level"])
                                st.success(f"Policy applied — {b['category']} is now **{upd['new_level']}**.")
                                st.rerun()

    with tab_policy:
        st.subheader("Delegation Levels")
        levels = kernel.hs_delegation_levels()
        if not levels:
            st.info("No custom policies set. All categories default to MANUAL.")
        else:
            import pandas as pd
            df_lev = pd.DataFrame([{"Category": k, "Level": v} for k, v in levels.items()])
            st.dataframe(df_lev, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Manually Set Delegation Level")
        with st.form("hs_policy_form"):
            c1, c2 = st.columns(2)
            pol_cat   = c1.text_input("Category", placeholder="finance")
            pol_level = c2.selectbox("New Delegation Level", ["MANUAL", "SUPERVISED", "AUTONOMOUS"])
            if st.form_submit_button("💾 Set Policy"):
                kernel.hs_apply_policy(pol_cat.strip(), pol_level)
                st.success(f"**{pol_cat}** set to **{pol_level}**.")
                st.rerun()

    with tab_events:
        st.subheader("Recent Approval Events")
        events = kernel.hs_recent_events(limit=50)
        if not events:
            st.info("No events recorded yet.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(events), use_container_width=True, height=400, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════
# 25. FEDERATED LEARNING
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🔐 Federated Learning":
    st.title("🔐 Federated Privacy-Preserving Learning")
    st.caption(
        "Agents get smarter by sharing *insights*, never *data*. "
        "Each department distils local workflow learnings into privacy-safe summaries. "
        "The Global Model merges these summaries without a single raw record leaving its node."
    )

    tab_nodes, tab_record_fl, tab_distil, tab_global, tab_query, tab_audit = st.tabs(
        ["🌐 Nodes", "📝 Record Workflow", "⚗️ Distil", "🌍 Global Model", "🔍 Query", "🛡️ Privacy Audit"]
    )

    with tab_nodes:
        st.subheader("Federated Nodes")
        nodes = kernel.fl_node_stats()
        if not nodes:
            st.info("No nodes yet. Record some workflows to create department nodes.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(nodes), use_container_width=True, hide_index=True)

    with tab_record_fl:
        st.subheader("Record a Workflow Outcome (Stays Local)")
        with st.form("fl_record_form"):
            c1, c2 = st.columns(2)
            fl_dept     = c1.text_input("Department ID", placeholder="engineering")
            fl_wf_type  = c2.text_input("Workflow Type", placeholder="code-review")
            c3, c4      = st.columns(2)
            fl_success  = c3.toggle("Workflow succeeded", value=True)
            fl_dur      = c4.number_input("Duration (ms)", min_value=0.0, value=1500.0, step=100.0)
            fl_tags_raw = st.text_input("Tags (comma-separated)", placeholder="fast, automated, ci")
            if st.form_submit_button("📝 Record", type="primary"):
                tags = [t.strip() for t in fl_tags_raw.split(",") if t.strip()]
                rec = kernel.fl_record_workflow(
                    dept_id=fl_dept.strip() or "default",
                    workflow_type=fl_wf_type.strip() or "general",
                    success=fl_success,
                    duration_ms=fl_dur,
                    tags=tags,
                )
                st.success(f"Record `{rec['record_id']}` added to node **{rec['dept_id']}** — raw data stays local.")

    with tab_distil:
        st.subheader("Distil Insights (Clears Raw Records)")
        nodes = kernel.fl_node_stats()
        dept_names = [n["dept_id"] for n in nodes] if nodes else []
        if not dept_names:
            st.info("No department nodes yet.")
        else:
            dist_dept = st.selectbox("Select Department", dept_names)
            selected_node = next((n for n in nodes if n["dept_id"] == dist_dept), None)
            if selected_node:
                st.metric("Pending Records", selected_node["pending_records"])
                st.caption("Distillation requires ≥5 records per workflow type.")
            if st.button("⚗️ Distil Insights Now", type="primary"):
                with st.spinner("Extracting patterns (no raw data leaves the node)..."):
                    insights = kernel.fl_distil_insights(dist_dept)
                if not insights:
                    st.warning("Not enough records to distil (need ≥5 per workflow type).")
                else:
                    st.success(f"✅ {len(insights)} insight(s) distilled. Raw records cleared.")
                    for ins in insights:
                        with st.expander(f"📊 {ins['workflow_type']} — {ins['success_rate']:.0%} success"):
                            c1, c2 = st.columns(2)
                            c1.metric("Sample Size", ins["sample_size"])
                            c2.metric("Avg Duration", f"{ins['avg_duration_ms']:.0f}ms")
                            st.markdown("**Best Practices Extracted:**")
                            for p in ins["best_practices"]:
                                st.markdown(f"- {p}")

    with tab_global:
        st.subheader("Global Federated Model")
        if st.button("🌍 Aggregate Global Model Now", type="primary"):
            with st.spinner("Merging insights across all nodes (no raw data)..."):
                kernel.fl_aggregate()
            st.success("✅ Global model updated.")
            st.rerun()

        model = kernel.fl_global_model()
        if not model:
            st.info("No global model yet. Distil some insights and click Aggregate.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Model Version", model["model_version"])
            c2.metric("Workflow Types", len(model["workflow_types"]))
            c3.metric("Contributing Nodes", len(model["contributing_nodes"]))
            st.markdown(f"**Nodes:** {', '.join(model['contributing_nodes'])}")

            for wf, rate in model["avg_success_rates"].items():
                bar_color = "#22c55e" if rate >= 0.8 else "#f59e0b" if rate >= 0.6 else "#ef4444"
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:12px;margin:6px 0;">'
                    f'<span style="width:180px;font-size:13px;">{wf}</span>'
                    f'<div style="flex:1;background:#e2e8f0;border-radius:6px;height:14px;">'
                    f'<div style="background:{bar_color};border-radius:6px;height:14px;width:{rate*100:.0f}%;"></div>'
                    f'</div>'
                    f'<span style="font-size:12px;color:#64748b;">{rate:.0%}</span></div>',
                    unsafe_allow_html=True,
                )

    with tab_query:
        st.subheader("Query Best Practices")
        q_wf = st.text_input("Workflow Type", placeholder="code-review")
        if st.button("🔍 Get Best Practices"):
            practices = kernel.fl_best_practices(q_wf.strip())
            if not practices:
                st.info("No practices found for that workflow type. Build the global model first.")
            else:
                st.success(f"✅ {len(practices)} best practice(s) found:")
                for p in practices:
                    st.markdown(f"- {p}")

    with tab_audit:
        st.subheader("Privacy Audit Log")
        st.info("Every entry must show `raw_data_shared = False` — verified automatically.")
        audit = kernel.fl_privacy_audit()
        if not audit:
            st.info("No audit entries yet.")
        else:
            import pandas as pd
            df_audit = pd.DataFrame(audit)
            # Highlight any privacy violations (there should be none)
            if any(e["raw_data_shared"] for e in audit):
                st.error("🚨 PRIVACY VIOLATION DETECTED — raw data was shared!")
            else:
                st.success("✅ All entries verified: no raw data shared.")
            st.dataframe(df_audit, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════
# 26. PROACTIVE CONCIERGE
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🚨 Proactive Concierge":
    st.title("🚨 Proactive Concierge — Event-Driven AI")
    st.caption(
        "Stop waiting for prompts. Define monitoring rules across your connected apps. "
        "When a metric crosses a threshold, the Concierge automatically spawns a "
        "War Room of agents to investigate and present a solution before you check your email."
    )

    tab_rules, tab_signal, tab_warrooms, tab_history = st.tabs(
        ["📏 Rules", "📡 Feed Signal", "🔴 War Rooms", "📊 History"]
    )

    with tab_rules:
        st.subheader("Monitoring Rules")
        rules = kernel.concierge_rules()
        if not rules:
            st.info("No rules yet. Add one below.")
        else:
            for r in rules:
                sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(r["severity"], "⚪")
                status_icon = "✅" if r["enabled"] else "⏸️"
                with st.expander(f"{sev_icon} {status_icon} **{r['name']}** — `{r['source']}/{r['metric']}` {r['comparison']} {r['threshold']}", expanded=False):
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**Agents:** {', '.join(r['agent_roles'])}")
                    c2.markdown(f"**Triggers:** {r['trigger_count']} &nbsp;|&nbsp; **Cooldown:** {r['cooldown_s']}s")

        st.markdown("---")
        st.subheader("Add Monitoring Rule")
        with st.form("concierge_rule_form"):
            c1, c2 = st.columns(2)
            r_name   = c1.text_input("Rule Name", placeholder="Sales Drop Alert")
            r_source = c2.text_input("Source", placeholder="crm")
            c3, c4   = st.columns(2)
            r_metric = c3.text_input("Metric", placeholder="daily_revenue")
            r_comp   = c4.selectbox("Comparison", ["pct_drop", "pct_rise", "lt", "gt", "lte", "gte"])
            c5, c6   = st.columns(2)
            r_thresh = c5.number_input("Threshold (use decimal for %, e.g. 0.10 = 10%)", min_value=0.0, value=0.10, step=0.01, format="%.3f")
            r_sev    = c6.selectbox("Severity", ["critical", "high", "medium", "low"])
            r_roles  = st.text_input("Agent Roles (comma-separated)", value="AnalystAgent, ReportingAgent")
            r_cool   = st.number_input("Cooldown (seconds)", min_value=0, value=300, step=30)
            if st.form_submit_button("➕ Add Rule", type="primary"):
                roles = [x.strip() for x in r_roles.split(",") if x.strip()]
                rule = kernel.concierge_add_rule(
                    name=r_name.strip(),
                    source=r_source.strip(),
                    metric=r_metric.strip(),
                    threshold=float(r_thresh),
                    comparison=r_comp,
                    agent_roles=roles,
                    severity=r_sev,
                    cooldown_s=float(r_cool),
                )
                st.success(f"✅ Rule `{rule['rule_id']}` added: **{r_name}**")
                st.rerun()

    with tab_signal:
        st.subheader("Feed a Live Signal")
        st.info("Simulate or pipeline a metric reading. If any rule matches, a War Room is spawned automatically.")
        with st.form("concierge_signal_form"):
            c1, c2 = st.columns(2)
            sig_source = c1.text_input("Source", placeholder="crm")
            sig_metric = c2.text_input("Metric", placeholder="daily_revenue")
            c3, c4     = st.columns(2)
            sig_value  = c3.number_input("Current Value", value=8500.0, step=100.0)
            sig_prev   = c4.number_input("Previous Value (optional, 0 = skip)", value=0.0, step=100.0)
            sig_ctx    = st.text_area("Context JSON (optional)", height=80, placeholder='{"period": "2026-03-17"}')
            if st.form_submit_button("📡 Feed Signal", type="primary"):
                import json as _json
                ctx = {}
                if sig_ctx.strip():
                    try:
                        ctx = _json.loads(sig_ctx)
                    except Exception:
                        st.warning("Context JSON is invalid — ignoring.")
                prev = float(sig_prev) if sig_prev != 0.0 else None
                spawned = kernel.concierge_feed_signal(sig_source, sig_metric, sig_value, prev, ctx)
                if not spawned:
                    st.info("Signal received. No rules triggered.")
                else:
                    st.warning(f"⚠️ {len(spawned)} War Room(s) spawned!")
                    for wr in spawned:
                        st.markdown(f"- 🔴 **{wr['name']}** (`{wr['war_room_id']}`)")
                    st.rerun()

    with tab_warrooms:
        st.subheader("Active War Rooms")
        stats = kernel.concierge_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rules Active", stats["rules_active"])
        c2.metric("Signals Received", stats["signals_received"])
        c3.metric("War Rooms Active", stats["war_rooms_active"])
        c4.metric("Resolved", stats["war_rooms_resolved"])

        war_rooms = kernel.concierge_active_war_rooms()
        if not war_rooms:
            st.info("No active War Rooms. Feed a signal to trigger one.")
        else:
            for wr in war_rooms:
                status_icon = {"spawned": "🔴", "investigating": "🟡", "resolved": "✅"}.get(wr["status"], "⚪")
                with st.expander(f"{status_icon} **{wr['name']}** — {wr['status']}", expanded=True):
                    st.markdown(f"**Rule:** {wr['trigger_rule']} &nbsp;|&nbsp; **Agents:** {', '.join(wr['agents'])}")
                    if wr["summary"]:
                        st.info(wr["summary"])
                    if wr["recommended_actions"]:
                        st.markdown("**Recommended Actions:**")
                        for a in wr["recommended_actions"]:
                            st.markdown(f"- {a}")
                    if wr["status"] == "spawned":
                        if st.button(f"🔍 Investigate Now", key=f"investigate_{wr['war_room_id']}", type="primary"):
                            with st.spinner("War Room agents investigating..."):
                                result = kernel.concierge_investigate(wr["war_room_id"])
                            st.success("Investigation complete!")
                            if result.get("findings"):
                                for f in result["findings"]:
                                    sev_c = {"critical": "#ef4444", "high": "#f97316", "medium": "#fbbf24", "low": "#22c55e"}.get(f["severity"], "#64748b")
                                    st.markdown(
                                        f'<div style="border-left:4px solid {sev_c};padding:8px 12px;margin:6px 0;">'
                                        f'<strong>{f["agent"]}</strong>: {f["finding"]}</div>',
                                        unsafe_allow_html=True,
                                    )
                            st.rerun()

    with tab_history:
        st.subheader("Signal History")
        limit = st.slider("Show last N signals", 10, 200, 50)
        history = kernel.concierge_signal_history(limit=limit)
        if not history:
            st.info("No signals received yet.")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame(history), use_container_width=True, height=320, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════
# 27. PERSONALITY ENGINE
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🎭 Personality Engine":
    st.title("🎭 Personality Engine — Human-AI Style Matching")
    st.caption(
        "AI-human teams perform better when their communication styles align. "
        "Detect the user's personality profile from their messages, assign tailored "
        "styles to agents, and watch responses transform — executives get bullet metrics, "
        "creatives get collaborative energy, engineers get raw depth."
    )

    tab_detect, tab_assign, tab_style, tab_preview, tab_stats = st.tabs(
        ["🔍 Detect Profile", "🎨 Assign Styles", "📋 Profile Catalog", "✍️ Style Preview", "📊 Stats"]
    )

    with tab_detect:
        st.subheader("Detect Your Personality Profile")
        messages_input = st.text_area(
            "Paste recent messages or prompts (one per line)",
            height=180,
            placeholder="Show me the Q3 P&L\nWhat's our EBITDA vs last quarter?\nNeed the board summary by 8am",
        )
        use_ai_detect = st.toggle("Use AI for richer analysis (~50 tokens)", value=False)
        if st.button("🔍 Detect Profile", type="primary"):
            msgs = [m.strip() for m in messages_input.strip().splitlines() if m.strip()]
            if not msgs:
                st.error("Enter some sample messages.")
            else:
                with st.spinner("Analysing communication style..."):
                    result = kernel.pe_detect_profile(msgs, use_ai=use_ai_detect)

                profile_colors = {
                    "EXECUTIVE": "#7c3aed", "CREATIVE": "#ec4899",
                    "TECHNICAL": "#0ea5e9", "ANALYTICAL": "#f97316",
                    "COLLABORATIVE": "#22c55e",
                }
                color = profile_colors.get(result["profile"], "#64748b")
                st.markdown(
                    f'<div style="background:{color}22;border:2px solid {color};border-radius:12px;padding:20px;">'
                    f'<div style="font-size:22px;font-weight:700;color:{color};">🎭 {result["profile"]}</div>'
                    f'<div style="font-size:14px;margin-top:6px;">{result["reasoning"]}</div>'
                    f'<div style="font-size:12px;color:#64748b;margin-top:4px;">Confidence: {result["confidence"]:.0%} &nbsp;|&nbsp; '
                    f'Signals: {", ".join(result["signal_words"][:5]) or "general pattern"}</div></div>',
                    unsafe_allow_html=True,
                )

    with tab_assign:
        st.subheader("Assign Communication Style to an Agent")
        with st.form("pe_assign_form"):
            c1, c2 = st.columns(2)
            pe_agent   = c1.text_input("Agent Name", placeholder="ReportingAgent")
            pe_profile = c2.selectbox("Profile", kernel.pe_profiles(), format_func=lambda d: d["profile"])
            profile_name = pe_profile["profile"] if isinstance(pe_profile, dict) else pe_profile
            if st.form_submit_button("🎨 Assign Style", type="primary"):
                kernel.pe_set_style(pe_agent.strip(), profile_name)
                st.success(f"✅ **{pe_agent}** now uses **{profile_name}** style.")

        st.markdown("---")
        st.subheader("Current Agent Styles")
        styles = kernel.pe_agent_styles()
        if not styles:
            st.info("No styles assigned yet.")
        else:
            import pandas as pd
            st.dataframe(
                pd.DataFrame([{"Agent": k, "Profile": v} for k, v in styles.items()]),
                use_container_width=True, hide_index=True,
            )

    with tab_style:
        st.subheader("Profile Catalog")
        profiles = kernel.pe_profiles()
        import pandas as pd
        df_profiles = pd.DataFrame(profiles)
        st.dataframe(df_profiles, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Profile Comparison")
        for p in profiles:
            colors = {
                "EXECUTIVE": "#7c3aed", "CREATIVE": "#ec4899",
                "TECHNICAL": "#0ea5e9", "ANALYTICAL": "#f97316",
                "COLLABORATIVE": "#22c55e",
            }
            c = colors.get(p["profile"], "#64748b")
            st.markdown(
                f'<div style="border-left:4px solid {c};padding:8px 14px;margin:8px 0;">'
                f'<strong style="color:{c};">{p["profile"]}</strong><br>'
                f'<span style="font-size:13px;">Tone: {p["tone"]} &nbsp;|&nbsp; Verbosity: {p["verbosity"]} '
                f'&nbsp;|&nbsp; Format: {p["format"]}</span></div>',
                unsafe_allow_html=True,
            )

    with tab_preview:
        st.subheader("Live Style Preview — See the Transformation")
        with st.form("pe_preview_form"):
            raw_resp = st.text_area(
                "Raw response to style",
                height=180,
                placeholder="Our Q3 revenue was $2.4M representing a 12% quarter-over-quarter increase. The primary driver was the enterprise tier growing by 34% following the product launch in July. Customer acquisition cost decreased from $320 to $285. Net retention is at 118% indicating strong expansion revenue from existing accounts.",
            )
            c1, c2 = st.columns(2)
            preview_agent   = c1.text_input("Agent Name (for style lookup)", value="PreviewAgent")
            preview_profile = c2.selectbox(
                "Force Profile (overrides agent style)",
                ["", "EXECUTIVE", "CREATIVE", "TECHNICAL", "ANALYTICAL", "COLLABORATIVE"]
            )
            preview_ctx = st.text_input("Context", placeholder="quarterly business review")
            if st.form_submit_button("✍️ Style It", type="primary"):
                if not raw_resp.strip():
                    st.error("Enter a response to style.")
                else:
                    with st.spinner("Adapting communication style..."):
                        result = kernel.pe_style_response(
                            agent_name    = preview_agent,
                            response      = raw_resp,
                            context       = preview_ctx,
                            force_profile = preview_profile or None,
                        )

                    col_orig, col_styled = st.columns(2)
                    with col_orig:
                        st.markdown("**📄 Original**")
                        st.markdown(
                            f'<div style="background:#f8fafc;border-radius:8px;padding:14px;font-size:13px;">{result["original"]}</div>',
                            unsafe_allow_html=True,
                        )
                    with col_styled:
                        profile_colors = {
                            "EXECUTIVE": "#7c3aed", "CREATIVE": "#ec4899",
                            "TECHNICAL": "#0ea5e9", "ANALYTICAL": "#f97316",
                            "COLLABORATIVE": "#22c55e",
                        }
                        c = profile_colors.get(result["profile"], "#64748b")
                        st.markdown(f'**✨ Styled ({result["profile"]})**')
                        st.markdown(
                            f'<div style="background:{c}11;border:1px solid {c}44;border-radius:8px;padding:14px;font-size:13px;">{result["styled"]}</div>',
                            unsafe_allow_html=True,
                        )
                    if result["transformations"]:
                        st.caption(f"Transformations: {', '.join(result['transformations'])} — ⏱ {result['processing_ms']:.0f}ms")

    with tab_stats:
        st.subheader("Styling Statistics")
        stats = kernel.pe_styling_stats()
        if stats.get("total", 0) == 0:
            st.info("No responses styled yet. Use the Preview tab to try it.")
        else:
            c1, c2 = st.columns(2)
            c1.metric("Total Styled", stats["total"])
            c2.metric("Avg Processing", f"{stats.get('avg_processing_ms', 0):.0f}ms")
            by_profile = stats.get("by_profile", {})
            if by_profile:
                import pandas as pd
                st.bar_chart(pd.Series(by_profile, name="Styled Responses"))
