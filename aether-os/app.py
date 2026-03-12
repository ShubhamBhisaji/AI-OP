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
        "🎓 Train AI",
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

    # ── Shutdown button ───────────────────────────────────────────────
    st.divider()
    if st.button("⏹ Stop AetherAi", use_container_width=True, type="secondary"):
        st.warning("Shutting down AetherAi... You can close this tab.")
        st.toast("AetherAi stopped.", icon="⏹")
        import time as _t; _t.sleep(1)
        import os as _os; _os._exit(0)


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
# 4. TRAIN AI
# ═══════════════════════════════════════════════════════════════════════════
elif page == "🎓 Train AI":
    st.header("🎓 Train AI")
    st.markdown(
        "Shape how AetherAi and individual agents think, respond, and behave. "
        "Instructions you write here are injected directly into every AI prompt."
    )

    tab_global, tab_agent = st.tabs(["🌐 AetherAi System Instructions", "🤖 Agent Instructions"])

    # ── Tab 1: Global / System-level instructions ─────────────────────
    with tab_global:
        st.subheader("🌐 AetherAi System Instructions")
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
            placeholder="Enter instructions that apply to ALL agents in AetherAi...",
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

                # Use with AetherAi
                st.markdown("**Use a local model with AetherAi** — pick one below then click Switch.")
                _local_models = [r["Model"] for r in _rows]
                _chosen = st.selectbox("Local model", _local_models, key="ollama_use_sel")
                if st.button("🔁 Switch AetherAi to this model"):
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
