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
from core.aetheerai_kernel import AetheerAiKernel
from core.workflow_engine import WorkflowFeedback, HITLAction

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
