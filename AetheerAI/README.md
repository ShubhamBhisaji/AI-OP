```
  ___         _   _                     _    ___
 / _ \       | | | |                   / \  |_ _|
/ /_\ \  ___ | |_| |__   ___  ___ _ __/ _ \  | |
|  _  | / _ \| __| '_ \ / _ \/ _ \ '__/ ___ \ | |
| | | ||  __/| |_| | | |  __/  __/ | / /   \_\|___|
\_| |_/ \___| \__|_| |_|\___|\___|_|/_/   (v2.0)
```

<div align="center">

**An AI Master — Autonomous Multi-Agent AI Operating System**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B?style=flat-square)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

An autonomous, multi-agent AI Operating System written in Python 3.10+.  
It manages AI agents the way an OS manages processes — with scheduling, security, memory, tools, and self-improvement built in.

> **Most AI today is Reactive** — it waits for you.  
> **AetheerAI is Proactive** — it builds systems that work *for* you.  
> It is the difference between a tool you hold in your hand and an engine that runs in the background.

## Purpose (Clear and Practical)

AetheerAI is built to run autonomous business and engineering workflows from one goal.

Primary output:
- You provide one goal (example: build a feature, run weekly analytics, generate a market brief).
- AetheerAI plans tasks, assigns specialist agents, executes with guardrails, and returns deliverables.

Primary use-cases:
- Product delivery automation: plan and generate feature code, docs, and deployment artifacts.
- Repeated operations: scheduled multi-step pipelines for research, reporting, and notifications.
- Governed AI execution: approval gates, permission levels, and audit logs for risky actions.

## Quick Start

Run one command:

python main.py

This starts the FastAPI server at http://localhost:8000 and docs at http://localhost:8000/docs.

Frontend UI is available at:
- http://localhost:8000/

Core API endpoints exposed immediately:
- POST /predict
- GET /status

Quick API checks:

curl -X GET http://localhost:8000/status

curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hello"}'

---

## Table of Contents

1. [What is AetheerAI?](#what-is-aetheerai)
2. [Use Cases — What Problem Does It Solve?](#use-cases--what-problem-does-it-solve)
3. [Screenshots & Demo](#screenshots--demo)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [How to Run](#how-to-run)
8. [Usage & Input / Output](#usage--input--output)
9. [Architecture](#architecture)
10. [AI Providers](#ai-providers)
11. [Key Features](#key-features)
12. [Security](#security)
13. [Tools (45+)](#tools-45)
14. [Self-Improvement Loop](#self-improvement-loop)
15. [Project Layout](#project-layout)
16. [Running Tests](#running-tests)
17. [Contributing](#contributing)
18. [License](#license)

---

## What is AetheerAI?

### 1. The "Project Manager" — *for Business Owners*

Imagine you are the CEO of a company. You don't have time to write every email, code every feature, or talk to every customer.

- **The Master (AetheerAI):** This is your **Project Manager**. You tell it the goal (e.g., *"Launch a new product"*).
- **The Sub-Agents:** The Project Manager "hires" a Designer, a Coder, and a Marketer.
- **The Result:** AetheerAI doesn't just "chat" — it **builds the team**, gives them instructions, and makes sure they work together until the job is done.

---

### 2. The "Digital Assembly Line" — *for Engineers*

In the old world (2024), AI was a single craftsman making one thing at a time. In 2026, AetheerAI is the **Factory Owner**.

It builds a **Digital Assembly Line** where:
- one agent grabs raw data,
- another agent cleans it,
- a third agent analyzes it,
- and a fourth agent sends it to your Slack or Gmail.

If one "machine" (agent) breaks, the Master AI **fixes it or replaces it instantly** without stopping the whole line.

---

### 3. The "Smart City" Traffic System — *for Non-Techies*

Think of all your apps (Slack, GitHub, Salesforce, Notion) as **buildings in a city**. AetheerAI is the **Traffic Control Center**.

- It creates **Autonomous Vehicles** (Agents) that know how to navigate between these buildings.
- One agent goes to the "GitHub Building" to get code, drives it to the "Slack Building" to notify the team, and then parks the results in the "Google Drive Building."
- AetheerAI ensures there are **no crashes** and that every agent is on the most efficient route.

---

### 4. The "Orchestra" vs. the "Soloist" — *for Investors*

A standard AI is a **solo pianist** — it can play a great song, but it's just one person.

**AetheerAI is the Conductor.**

- The Conductor doesn't play an instrument; it **leads a Symphony of Agents**.
- The "Strings" (Research Agents), the "Brass" (Execution Agents), and the "Percussion" (Security Agents) all play together in perfect sync to create a complex masterpiece.

| Audience | Best Metaphor |
|---|---|
| Business Owners | The "Project Manager" — focus on delegation |
| Engineers | The "Digital Assembly Line" — focus on workflow |
| Non-Techies | The "Smart City" — focus on movement and apps |
| Investors | The "Orchestra" — focus on the beauty of coordination |

---

## Use Cases — What Problem Does It Solve?

### The core problem

Every AI tool available today — ChatGPT, Copilot, Gemini — is a **single-turn assistant**.  
You ask one question, it answers, and then it **forgets everything** and waits for you to ask again.

This means **you** are still the project manager. You still have to:
- break the goal into steps,
- copy output from one tool to another,
- notice when something fails and retry it,
- keep track of what has and hasn't been done.

**AetheerAI removes you from that loop entirely.**  
You give it a goal. It plans, assigns, executes, monitors, and delivers — by itself.

---

### Real-world problems it solves

#### Problem 1 — "I need a full feature, not a code snippet"

> *"Write me a user authentication system with JWT, a login endpoint, password hashing, and a Dockerfile."*

| Without AetheerAI | With AetheerAI |
|---|---|
| Prompt ChatGPT for the route → copy → prompt for JWT → copy → prompt for Docker → copy → fix conflicts manually | One `orchestrate` command. CEO agent plans 4 tasks, assigns them to DeveloperAgent, monitors, and saves all files to `workspace/`. |

---

#### Problem 2 — "Research takes hours before I can even start building"

> *"Before building, I need to know the best practices, the competitor landscape, and what tech stack to use."*

| Without AetheerAI | With AetheerAI |
|---|---|
| Open 10 browser tabs, read docs, take notes, summarise manually | ResearchAgent runs web searches in parallel, fact-checks sources, and delivers a structured report — while DeveloperAgent is already starting the scaffold in the background. |

---

#### Problem 3 — "I run the same multi-step workflow every week"

> *"Every Monday: pull last week's sales CSV, clean it, analyse trends, write a summary, email it to the team."*

| Without AetheerAI | With AetheerAI |
|---|---|
| Open spreadsheet, run scripts, write summary, manually send email — 2 hours every week | Define the pipeline once. `run_pipeline dataTeam "run weekly sales report"` — runs in under 2 minutes, unattended. |

---

#### Problem 4 — "I'm a solo founder — I can't afford five specialists"

> *"I need a researcher, a developer, a marketer, an ops engineer, and a support agent — but I'm one person."*

| Without AetheerAI | With AetheerAI |
|---|---|
| Juggle every role yourself, context-switch constantly, burn out | Spin up a full team of specialist agents in seconds. Delegate like a CEO. Each agent has the right tools and the right permissions. |

---

#### Problem 5 — "AI ideas that break in production due to zero safety controls"

> *"I gave an AI access to my file system and it deleted the wrong folder."*

| Without AetheerAI | With AetheerAI |
|---|---|
| No guardrails — model can call any tool, write anywhere, run any command | Every destructive tool (`file_writer`, `code_runner`, `terminal`) requires explicit human approval via `ApprovalGate`. RBAC enforces per-agent permission levels. Full audit trail in `memory/audit_log.jsonl`. |

---

### Who is it for?

| Persona | Pain point solved |
|---|---|
| **Solo founders / indie hackers** | Replace a whole team with a managed agent crew |
| **Software engineers** | Automate repetitive multi-step workflows (CI tasks, code review, doc generation) |
| **Data analysts** | Build pipelines that fetch, clean, analyse, and report — unattended |
| **Marketing teams** | Research → write → publish content pipelines |
| **DevOps / SRE teams** | Self-healing automation that detects failure and retries or re-routes |
| **Researchers** | Multi-source web research, fact-checking, and structured report generation |
| **Enterprises** | Governed, audited, budget-capped AI execution with RBAC and approval gates |

---

### What it is NOT

- **Not a chatbot** — it does not wait for you to type the next message.
- **Not a single-model wrapper** — it orchestrates *multiple* agents with *different* roles, tools, and permissions.
- **Not a no-code toy** — it is a Python framework with a full REST API, security layer, and plugin tool system.
- **Not vendor-locked** — swap between OpenAI, Claude, Gemini, Ollama, or GitHub Models with one config change.

---

## Screenshots & Demo

### Streamlit Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  🤖 AetheerAI — Dashboard                          [v2.0]       │
├───────────────────┬─────────────────────────────────────────────┤
│  AGENTS           │  Goal Submission                            │
│  ─────────────    │  ─────────────────────────────────────────  │
│  ✅ ceo_agent     │  Goal: Build a SaaS landing page            │
│  ✅ dev_agent     │  Provider: openai  Model: gpt-4o            │
│  ✅ research_bot  │  Budget cap: $5.00 │ Timeout: 300s          │
│  ✅ marketer      │                                             │
│  ✅ ops_agent     │  [▶  Run Goal]                              │
│                   │                                             │
│  [+ New Agent]    │  Progress ──────────────── 4/5 tasks ✅     │
│  [📋 Teams]       │  ╰─ ResearchAgent  → Done ✅               │
│  [🔧 Tools]       │  ╰─ DeveloperAgent → Done ✅               │
│                   │  ╰─ MarketingAgent → Done ✅               │
│                   │  ╰─ OperationsAgent→ Running ⏳            │
└───────────────────┴─────────────────────────────────────────────┘
```

### CLI Interactive Mode

```
$ python main.py

  █████╗ ███████╗████████╗██╗  ██╗███████╗███████╗██████╗
 ██╔══██╗██╔════╝╚══██╔══╝██║  ██║██╔════╝██╔════╝██╔══██╗
 ███████║█████╗     ██║   ███████║█████╗  █████╗  ██████╔╝
 ██╔══██║██╔══╝     ██║   ██╔══██║██╔══╝  ██╔══╝  ██╔══██╗
 ██║  ██║███████╗   ██║   ██║  ██║███████╗███████╗██║  ██║
 ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝
                    Autonomous AI Operating System  v2.0

Provider: openai  |  Model: gpt-4o  |  Agents: 3 loaded
──────────────────────────────────────────────────────────────
AETHEERAI> orchestrate "build a REST API for user auth"

  [CEO]  Planning goal…  4 tasks created
  [DEV]  Writing auth routes...    ✅  api/auth.py  (0.8 s)
  [DEV]  Writing JWT middleware...  ✅  api/jwt.py   (1.1 s)
  [OPS]  Writing Dockerfile...      ✅  Dockerfile   (0.4 s)
  [CEO]  Delivering summary...      ✅

  ✅  Goal completed — 4/4 tasks (cost: $0.03, 4.2 s)
```

### FastAPI Interactive Docs

```
  http://localhost:8000/docs

  ┌─────────────────────────────────────────────────────────┐
  │  AetheerAI REST API  v2.0  — Interactive Docs           │
  ├─────────────────────────────────────────────────────────┤
  │  POST  /api/goals          Submit a high-level goal     │
  │  GET   /api/goals          List goals + status          │
  │  POST  /api/projects       Run goal via CEO agent       │
  │  GET   /api/projects/{id}  Get results & task breakdown │
  │  POST  /api/agents         Create a custom agent        │
  │  GET   /api/system/status  Runtime health check         │
  └─────────────────────────────────────────────────────────┘
```

### Multi-Agent Pipeline Output

```
$ python examples/build_website.py

  [CEO]       Decomposing goal into 5 tasks…
  [RESEARCH]  Fetching SaaS landing page best practices  ✅  (2.1 s)
  [DEVELOPER] Writing index.html + styles.css            ✅  (3.5 s)
  [MARKETER]  Writing hero copy & CTA text               ✅  (1.2 s)
  [OPS]       Saving files to workspace/                 ✅  (0.1 s)
  [CEO]       Synthesising final report…                 ✅

  ─────────────────────────────────────────────
  ✅  Completed — 5/5 tasks  │  cost $0.07  │  8.2 s
  📁  Output saved to:  workspace/
      ├── index.html
      ├── styles.css
      └── copy.md
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.10 + | 3.11+ recommended |
| **pip** | latest | `python -m pip install --upgrade pip` |
| **Docker Desktop** | any recent | Required only for sandboxed `code_runner` tool |
| **Git** | any | For cloning the repo |
| **OS** | Windows 10+, macOS 12+, Ubuntu 20.04+ | Windows one-click launcher included |

**At least one AI provider credential is required** — choose any free option:

| Provider | Cost | How to get |
|---|---|---|
| GitHub Models | **Free** | [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes needed |
| OpenAI | Pay-per-use | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Anthropic Claude | Pay-per-use | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | Free tier | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| Ollama (local) | **Free** | [ollama.com/download](https://ollama.com/download) |

---

## Installation

### Option A — Windows One-Click (Recommended for Windows users)

```bat
:: 1. Clone or download the repository
git clone https://github.com/your-org/AetheerAI.git
cd AetheerAI

:: 2. Double-click or run:
launchers\Start_AetheerAi.bat
```

This script installs dependencies, creates a `.env` interactively, and opens the Streamlit dashboard automatically.

---

### Option B — Manual Installation (All platforms)

**Step 1 — Clone the repository**

```bash
git clone https://github.com/your-org/AetheerAI.git
cd AetheerAI
```

**Step 2 — Create and activate a virtual environment** *(recommended)*

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

**Step 3 — Install Python dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 4 — Install optional extras** *(pick what you need)*

```bash
# Semantic / RAG memory search (recommended)
pip install chromadb

# Linux only — ChromaDB sqlite3 fix
pip install pysqlite3-binary

# For the Playwright browser tool
playwright install chromium
```

**Step 5 — Copy and edit the environment file**

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Then open `.env` in any text editor and fill in your credentials (see [Configuration](#configuration)).

**Step 6 — Verify the install**

```bash
python main.py
# Expected: FastAPI server starts on http://localhost:8000
```

---

### Option C — PyInstaller Executable (Windows, no Python required)

```bash
# Build a standalone .exe
python build_pyinstaller.py

# Or use the batch builder:
launchers\build_setup_exe.bat
```

The installer is created in `installer/` and can be distributed to machines without Python.

---

## Configuration

All settings live in a single `.env` file at the project root.

```ini
# .env — minimum required settings

# ── AI Provider ──────────────────────────────────────────────────
AI_PROVIDER=github           # github | openai | anthropic | gemini | ollama
AI_MODEL=gpt-4o              # Model name for the chosen provider

# ── API Keys (set only the one you use) ──────────────────────────
GITHUB_TOKEN=ghp_...         # Free — github.com/settings/tokens (no scopes needed)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
# HUGGINGFACE_API_KEY=hf_...

# ── Budget & Safety Caps ──────────────────────────────────────────
MAX_COST_USD=5.0             # Stop execution if estimated cost exceeds this
MAX_RUNTIME_SECONDS=300      # Hard timeout for any single goal run

# ── Security ─────────────────────────────────────────────────────
AETHER_AUTO_APPROVE=false    # false = require human approval for destructive tools
AETHER_HEADLESS=false        # true = auto-reject all guarded tool calls (for CI)

# ── Offline / Local Mode ──────────────────────────────────────────
# AETHEER_OFFLINE_PROVIDER=ollama
# AETHEER_OFFLINE_MODEL=llama3
```

> **Tip:** You can set API keys interactively at any time from the CLI:
> ```
> AETHEERAI> add_api
> ```

---

## How to Run

Use the canonical entrypoint:

python main.py

What this does:
- Starts the API server.
- Uses environment settings from .env.
- Opens all endpoints through http://localhost:8000/docs.

Advanced alternatives (optional):
- Streamlit dashboard: python launcher.py
- Direct uvicorn: uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

---

## Usage & Input / Output

### Input formats

| Interface | Input type | Example |
|---|---|---|
| CLI | Free-text command | `orchestrate "build a REST API for auth"` |
| Streamlit GUI | Text field in browser | Type your goal and click **Run Goal** |
| REST API | JSON body (POST) | `{"goal": "Write a competitor analysis report"}` |
| Python API | String argument | `ceo.run("Analyse Q1 sales data")` |

### Output formats

| Output | Where it appears | Format |
|---|---|---|
| Agent responses | Terminal / GUI panel | Plain text / Markdown |
| Written files | `workspace/` directory | `.py`, `.html`, `.md`, `.json`, etc. |
| API responses | HTTP JSON | `{"goal_id": "…", "status": "completed", "summary": "…"}` |
| Audit log | `memory/audit_log.jsonl` | Append-only JSONL |
| Task report | Returned object | `result.final_summary`, `result.completed_tasks` |

### CLI command reference

```
Agent management
  create_agent <name> <role>       Create a new agent
  list_agents                      List all registered agents
  agent_info <name>                Show agent details
  upgrade_agent <name>             AI-powered skill upgrade
  open_agent <name>                Open agent in a dedicated terminal window

Multi-agent workflows
  orchestrate "<goal>"             CEO decomposes and runs a full goal
  run_pipeline <team> "<goal>"     Sequential pipeline across a named team
  broadcast "<message>"            Send the same task to all agents
  vote "<question>"                Majority-vote between agents
  best_of "<task>"                 Run N agents, return the best result
  agent_debate <a> <b> "<topic>"   Head-to-head structured debate

AI systems
  create_ai_system                 Wizard designs a full agent roster
  ai_system_task <sys> "<task>"    Run a task on a named system

Provider switching
  switch_ai github                 Switch to GitHub Models (free)
  switch_ai openai gpt-4o          Switch provider + model at runtime
  add_api                          Interactive API key manager

Build & export
  build_application <name>         AI-powered app scaffold
  export_agent <name>              Standalone runnable folder
  export_system <sys> <agents>     Multi-agent bundle with Docker + launchers
```

### REST API — key endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/goals` | Submit a high-level goal |
| `GET`  | `/api/goals/{id}` | Monitor goal end-to-end |
| `GET`  | `/api/goals/{id}/tasks` | Task-level progress |
| `POST` | `/api/projects` | Submit goal → CEO runs it |
| `GET`  | `/api/projects/{id}` | Results + task breakdown |
| `POST` | `/api/agents` | Create a custom agent |
| `POST` | `/api/collaborations` | Multi-round collaboration session |
| `GET`  | `/api/system/status` | Runtime health check |
| `POST` | `/api/chat` | Direct AI chat (no CEO planning) |
| `GET`  | `/api/health` | Health check |

**Example — submit a project via curl:**

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My SaaS Landing Page",
    "goal": "Build a professional landing page for TaskFlow",
    "collaboration_mode": true,
    "offline_local_mode": false,
    "background": false
  }'
```

**Example response:**

```json
{
  "project_id": "proj_abc123",
  "status": "completed",
  "completed_tasks": 5,
  "total_tasks": 5,
  "cost_usd": 0.07,
  "runtime_seconds": 8.2,
  "summary": "Landing page built and saved to workspace/...",
  "files": ["workspace/index.html", "workspace/styles.css", "workspace/copy.md"]
}
```

---

## Architecture

```
User / CLI
    │
    ▼
AetheerAiKernel          ← Central boot & orchestration
    ├── AIAdapter         ← Unified LLM interface (litellm)
    ├── WorkflowEngine    ← Task execution, HITL checkpoints, async
    ├── Orchestrator      ← pipeline / broadcast / vote / debate / best-of
    ├── TeamManager       ← Named agent teams
    ├── AgentRegistry     ← Agent CRUD + JSON persistence
    ├── ToolManager       ← 45+ tools, RBAC enforcement
    ├── MemoryManager     ← Namespaced KV store + ChromaDB vector search
    ├── SkillEngine       ← Tiered skill catalogs, AI-driven upgrades
    └── Security layer
            ├── PolicyEngine   ← tool authorisation (deny-by-default)
            ├── ApprovalGate   ← HITL gate for destructive/high-risk tools
            └── AuditLogger    ← Append-only JSONL audit trail
```

---

## AI Providers

| Provider | Model examples | Requirements |
|---|---|---|
| **GitHub Models** (free) | `gpt-4o`, `Llama-3-70b` | GitHub account — no billing |
| **OpenAI** | `gpt-4o`, `gpt-4-turbo` | `OPENAI_API_KEY` |
| **Anthropic Claude** | `claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |
| **Google Gemini** | `gemini-1.5-pro` | `GEMINI_API_KEY` |
| **Ollama** (local) | any pulled model | Docker or native |
| **HuggingFace** | Inference API models | `HUGGINGFACE_API_KEY` |

Switch providers at runtime:
```
AETHEERAI> switch_ai github
AETHEERAI> switch_ai openai gpt-4o
```

Set API keys interactively:
```
AETHEERAI> add_api
```

---

## Key Features

### Agent management
```
create_agent ResearchBot "Research Specialist"
list_agents
agent_info ResearchBot
upgrade_agent ResearchBot
open_agent ResearchBot          # dedicated terminal window
```

### Multi-agent workflows
```
create_team myTeam agent1,agent2,agent3
run_pipeline myTeam "analyse Q1 sales data"
broadcast "summarise today's news"
vote "should we use PostgreSQL or MongoDB?"
best_of "write a product description for our SaaS"
agent_debate agent1 agent2 "is Python better than Rust?"
orchestrate "build a REST API for user auth"
```

### AI Systems
```
create_ai_system                         # wizard designs a full agent roster
ai_system_task MySystem "run Q2 report"
```

### Build & export
```
build_application my-app               # AI-powered app scaffold
export_agent ResearchBot               # standalone runnable folder
export_system MyAI agent1,agent2       # multi-agent bundle w/ Docker + launchers
```

---

## Security

- **RBAC levels 0–3** — each agent has a `permission_level`; tools require a minimum level  
- **ApprovalGate** — destructive tools (`file_writer`, `email_tool`) and high-risk tools (`code_runner`, `terminal_tool`, AWS/GCP/K8s) require explicit operator approval  
- **Audit log** — every guarded tool call is written to `memory/audit_log.jsonl` (append-only)  
- **Memory isolation** — agents operate in private namespaces; cannot read each other's memory  
- **Path traversal hardened** — agent names sanitised; all export paths confined to base directory  
- **Docker sandbox** — `code_runner` executes code in an isolated container (network-none, ro-fs, memory capped). Execution is blocked if Docker is unavailable.

---

## Tools (45+)

| Category | Tools |
|---|---|
| Utilities | calculator, datetime, hash, base64, regex, text_analyzer, json, markdown, url, template, diff, system_info |
| Web | web_search, http_client, browser, web_scraper_pro |
| Files | file_reader, file_writer, directory_scanner, local_file, csv, pdf |
| Dev | code_runner *(Docker required)*, terminal, code_analyzer, code_search, linter, formatter, github, playwright |
| AI / Media | vision, image_gen, speech |
| Communication | email, slack_discord |
| Cloud / Infra | aws_gcp, kubernetes, sql_db |
| Multi-agent | agent_ping |

---

## Self-Improvement Loop

1. `EvalRunner` runs benchmark cases against an agent with a configurable timeout  
2. `FailureClustering` groups failures by error type  
3. `SelfImproveCoordinator` proposes patches, optionally gated by a quality threshold  

---

## Project Layout

```
AI-OP/
├── app/                 Runtime entry wrappers (CLI, dashboard, server)
├── src/                 Canonical package namespace (src-layout)
├── models/              Data pipelines, configs, and trained artifacts
├── api/                 Top-level API entry point (`api.server:app`)
├── ui/                  Mirror copy of the packaged UI (synced from `AetheerAI/ui/`)
├── main.py              Unified root entry point
└── AetheerAI/           Legacy implementation modules (kept for compatibility)
```

The runtime remains backward-compatible: the `AetheerAI/` implementation stays
intact while clean top-level architecture is exposed at repository root.

## UI Source Of Truth

- The deployed built-in web UI is served from `AetheerAI/ui/`.
- Treat `AetheerAI/ui/index.html`, `AetheerAI/ui/styles.css`, and `AetheerAI/ui/app.js` as the only hand-edited UI files.
- The top-level `ui/` folder is a mirror copy kept for compatibility and should be refreshed with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_ui.ps1
```

- Do not make primary UI changes in the top-level `ui/` folder; rerun the sync script after editing `AetheerAI/ui/`.
- VS Code workspace automation:

**Available Workspace Commands** (after installing `ryuta46.multi-command` extension):

| Command | Action | Use Case |
|---------|--------|----------|
| `multiCommand.syncUiMirrorAndOpenScm` | Sync + open Source Control view | Review git diff and staged changes |
| `multiCommand.syncUiMirrorAndOpenProblems` | Sync + open Problems panel | Check lint/build errors after sync |

- Optional user keybinding snippets for `keybindings.json`:

```json
[
  {
    "key": "ctrl+alt+u",
    "command": "extension.multiCommand.execute",
    "args": {
      "command": "multiCommand.syncUiMirrorAndOpenScm"
    }
  },
  {
    "key": "ctrl+alt+shift+u",
    "command": "extension.multiCommand.execute",
    "args": {
      "command": "multiCommand.syncUiMirrorAndOpenProblems"
    }
  }
]
```

---

## Running Tests

```bash
pytest AetheerAI/tests/ -v

# With coverage
pytest AetheerAI/tests/ -v --tb=short --cov=AetheerAI

# Run a specific test file
pytest AetheerAI/tests/test_orchestrator.py -v
```

---

## Contributing

Contributions are welcome! Here is the workflow:

1. **Fork** the repository and create a new branch:
   ```bash
   git checkout -b feature/my-new-agent
   ```

2. **Make your changes** — follow the existing patterns in `agents/` or `tools/`.

3. **Add or update tests** in `tests/` for your changes.

4. **Run the test suite** to make sure nothing is broken:
   ```bash
   pytest AetheerAI/tests/ -v
   ```

5. **Open a Pull Request** with a clear description of what was added or fixed.

### Adding a new specialist agent

```python
# agents/my_agent.py
from agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    def __init__(self, name, tool_manager, ai_adapter):
        super().__init__(
            name=name,
            role="My Specialist",
            tools=["web_search", "file_writer"],
            permission_level=1,
            tool_manager=tool_manager,
            ai_adapter=ai_adapter,
        )
```

### Adding a new tool

```python
# tools/my_tool.py
from tools.tool_manager import register_tool

@register_tool(name="my_tool", risk="LOW", min_permission=1)
def my_tool(input_text: str) -> str:
    """One-line description of what the tool does."""
    return f"Processed: {input_text}"
```

### Reporting bugs

Open a GitHub Issue with:
- Python version (`python --version`)
- OS and version
- Full error traceback
- Minimal reproduction steps

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built with Python 3.10+ &nbsp;|&nbsp; Powered by litellm &nbsp;|&nbsp; AetheerAI v2.0
</div>
