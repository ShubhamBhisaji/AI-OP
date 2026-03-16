# Aether Architecture

Aether is an AI Operating System that manages agents like processes.

## Core Principles

- The **kernel** controls agents.
- **Agents** perform tasks.
- **Tools** extend capabilities.
- The **skill engine** improves agents.
- The **AI adapter** connects multiple AI models.

## Component Relationships

```
┌─────────────────────────────────────────────────────────┐
│                     AetherKernel                        │
│   (Central controller — orchestrates all components)    │
└───────────┬────────────────────────┬────────────────────┘
            │                        │
     ┌──────▼──────┐         ┌───────▼──────┐
     │AgentFactory │         │WorkflowEngine│
     │  (creates   │         │  (manages    │
     │   agents)   │         │  pipelines)  │
     └──────┬──────┘         └───────┬──────┘
            │                        │
     ┌──────▼──────┐         ┌───────▼──────┐
     │AgentRegistry│         │ TaskExecutor │
     │  (tracks &  │         │  (runs tasks │
     │  stores)    │         │  for agents) │
     └─────────────┘         └──────────────┘

     ┌─────────────┐         ┌──────────────┐
     │ SkillEngine │         │  ToolManager │
     │  (upgrades  │         │  (registers  │
     │   agents)   │         │   tools)     │
     └─────────────┘         └──────────────┘

     ┌─────────────┐         ┌──────────────┐
     │  AIAdapter  │         │MemoryManager │
     │ (OpenAI /   │         │ (persistent  │
     │ Claude /    │         │  & session   │
     │ Gemini /    │         │  memory)     │
     │ Ollama...)  │         └──────────────┘
     └─────────────┘
```

## Data Flow

```
User Input
    │
    ▼
AetherKernel  ──►  AIAdapter  ──►  AI Model (OpenAI / Claude / Gemini / Local)
    │
    ▼
WorkflowEngine  ──►  TaskExecutor
    │
    ▼
AgentRegistry  ──►  BaseAgent (role + tools + skills)
    │
    ▼
ToolManager  ──►  Tools (web_search, file_writer, API calls...)
    │
    ▼
MemoryManager  ──►  Store results + agent state
    │
    ▼
Result → User
```

## Autonomous Factory Mode (Production Baseline)

Autonomous Factory mode adds policy-governed execution and feedback loops on
top of the base orchestration model.

### Execution Path

```
User Prompt
  │
  ▼
WorkflowEngine
  │
  ▼
ToolManager.call(...)
  │
  ├─► PolicyEngine.evaluate_tool_call(...)
  │      ├─ deny: stop + audit
  │      └─ allow: continue
  │
  ├─► ApprovalGate.request(...) for guarded tools
  │
  └─► Tool Execution
      │
      ▼
     Result
```

### Build/Export Path

`AetherKernel` is now a thin coordinator that delegates:

- `build_application(...)` -> `CompilerService` -> kernel build implementation
- `export_agent(...)` / `export_system(...)` -> `ExporterService` -> kernel export implementation
- template rendering uses `TemplateRegistry` with external template files

### Self-Improvement Path

```
Eval Cases
  │
  ▼
SelfImproveCoordinator
  │
  ├─► EvalRunner (timeouts, bounds, truncation)
  ├─► Failure Clustering
  └─► Recommendations
      │
      ▼
Redacted summary persisted in MemoryManager
```

### Security Invariants

- Unknown tools are denied by default.
- Guarded tools require explicit approval.
- Code execution requires Docker sandbox (no host fallback).
- Export/build output paths are sanitized and constrained to approved roots.

## Agent Lifecycle

```
1. CREATE   AgentFactory builds agent with role, tools, prompt
2. REGISTER AgentRegistry stores the agent profile
3. ASSIGN   WorkflowEngine assigns tasks to the agent
4. EXECUTE  TaskExecutor runs the agent against tools + AI
5. IMPROVE  SkillEngine upgrades the agent based on performance
6. PERSIST  MemoryManager saves state and version history
```

## AI Provider Abstraction

```python
# AIAdapter switches seamlessly between providers
AIAdapter → OpenAI GPT-4
AIAdapter → Anthropic Claude
AIAdapter → Google Gemini
AIAdapter → Ollama (local)
AIAdapter → HuggingFace models
```

## Agent Profile Schema

```yaml
agent_profile:
  id: "research_agent_001"
  role: "Research Agent"
  version: "1.0.0"
  tools:
    - web_search
    - file_writer
  skills:
    - summarization
    - fact_checking
  performance:
    tasks_completed: 0
    success_rate: 0.0
  history: []
```

## Technology Stack

- **Runtime:** Python 3.10+
- **AI Frameworks:** LangChain, CrewAI, LangGraph
- **AI Providers:** OpenAI, Anthropic, Google, Ollama, HuggingFace
- **Config Format:** JSON / YAML
- **Interface:** CLI (`command_interface.py`) + extensible to API/UI
