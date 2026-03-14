# Autonomous AI Factory - Implementation PR Plan

## Objective
Transition AetheerAI from a powerful toolkit into an autonomous, self-improving AI factory with strong governance, reliability, and measurable quality gains.

## Program Outcomes
1. Safe autonomy: autonomous operations are policy-governed and auditable.
2. Reliable autonomy: async workflows run without deadlocks or brittle fallbacks.
3. Self-improvement: system proposes, validates, and applies improvements with test gates.
4. Factory pipeline: generated systems are built, verified, and packaged continuously.

## Delivery Strategy
Use an incremental 6-PR sequence with strict acceptance gates per PR.

## Current Status
1. PR-1 Governance Core: In progress (baseline implemented: policy engine, opaque approval token, append-only audit logger, ToolManager wiring, tests).
2. PR-2 Async Safety Runtime: In progress (implemented: async HITL callback contract, timeout/cancellation/max_parallel controls, integration tests).
3. PR-3 Export/Build Hardening: In progress (implemented: path traversal mitigations and provider-fallback fixes in runtime templates; regression tests added).
4. PR-4 Exporter/Compiler Service: In progress (implemented: core/exporter.py and core/compiler.py service facades, kernel delegation with compatibility fallbacks, tests).
5. PR-5 Template Registry: In progress (implemented: core/template_registry.py, external templates, kernel template rendering with safe fallback).
6. PR-6 Self-Improvement Loop: In progress (implemented: eval runner, failure clustering, self-improvement coordinator, kernel self_improve_once entrypoint, tests).

---

## PR-1: Governance Core (Policy + Approval Tokens + Audit)

### Scope
- Add policy engine module for tool/action authorization.
- Replace implicit approval bypasses with signed/opaque approval tickets.
- Add append-only audit log for every guarded action.

### Files/Modules (target)
- `aether-os/security/policy_engine.py` (new)
- `aether-os/security/approval_gate.py` (extend)
- `aether-os/tools/tool_manager.py` (wire policy + ticket validation)
- `aether-os/memory/audit_log.jsonl` (new runtime artifact)

### Acceptance Criteria
- All guarded tool calls require policy allow + valid approval context.
- No user-provided kwargs can bypass approval checks.
- Every guarded call produces an audit entry with timestamp, agent, tool, decision, and reason.

### Tests
- Unit: deny-by-default policy behavior.
- Unit: forged bypass flags/tokens are rejected.
- Unit: audit entries are written exactly once per decision.

---

## PR-2: Async Safety + HITL Non-Blocking Runtime

### Scope
- Ensure ApprovalGate never blocks active asyncio loops with `input()`.
- Introduce async-safe approval callback contract.
- Add bounded concurrency controls and timeout/cancellation semantics.

### Files/Modules (target)
- `aether-os/security/approval_gate.py`
- `aether-os/core/workflow_engine.py`
- `aether-os/core/aether_kernel.py`

### Acceptance Criteria
- Async pipeline with HITL enabled does not hang event loop.
- Rejected approvals fail fast and propagate structured error.
- Concurrent workflows remain isolated and responsive under load.

### Tests
- Integration: `run_pipeline_async` with guarded tools and mocked approvals.
- Integration: cancellation/timeout behavior in parallel subtasks.

---

## PR-3: Export/Build Hardening + Provider-Aware Defaults

### Scope
- Fully sanitize all path-derived names for export/build artifacts.
- Enforce base-directory containment for all generated writes.
- Remove provider-incompatible hardcoded model fallbacks.

### Files/Modules (target)
- `aether-os/core/aether_kernel.py`
- `aether-os/main.py`

### Acceptance Criteria
- Inputs like `../../x` never escape approved output roots.
- Exported agent/system boot succeeds with provider-specific model defaults.
- `.env` mutation preserves existing formatting conventions safely.

### Tests
- Unit: path traversal payload corpus against export/build entry points.
- Integration: exported runner with each provider (`github/openai/claude/gemini/ollama`).

---

## PR-4: Extract Exporter/Compiler Service (Kernel Decomposition)

### Scope
- Move export/build code generation out of `AetherKernel` into dedicated services.
- Introduce interfaces for orchestrator, exporter, compiler.
- Keep behavior stable while reducing kernel responsibility.

### Files/Modules (target)
- `aether-os/core/exporter.py` (new)
- `aether-os/core/compiler.py` (new)
- `aether-os/core/aether_kernel.py` (thin coordinator)

### Acceptance Criteria
- `AetherKernel` no longer owns inline template generation logic.
- Existing CLI/API commands preserve outputs and signatures.
- Cyclomatic complexity and file length of kernel reduce materially.

### Tests
- Snapshot tests of generated files before/after refactor.
- Contract tests for kernel public methods.

---

## PR-5: Template Registry + Versioned Build Recipes

### Scope
- Move inline HTML/Docker/batch/python templates into versioned template files.
- Add template rendering pipeline with schema validation.
- Introduce template compatibility matrix (provider/tooling/runtime).

### Files/Modules (target)
- `aether-os/templates/**` (new)
- `aether-os/core/template_registry.py` (new)
- `aether-os/core/exporter.py`

### Acceptance Criteria
- No large embedded template strings remain in kernel/service code.
- Template rendering is deterministic and testable.
- Template version is included in export manifests.

### Tests
- Snapshot tests per template version.
- Schema validation tests for template variables.

---

## PR-6: Self-Improvement Loop + Quality Gates

### Scope
- Add benchmark harness for generated agents/apps.
- Add reflector that clusters failures and proposes minimal patches.
- Add auto-PR generation only when all quality gates pass.

### Files/Modules (target)
- `aether-os/evals/benchmark_runner.py` (new)
- `aether-os/evals/failure_clustering.py` (new)
- `aether-os/core/self_improve.py` (new)
- `.github/workflows/security-hardening-ci.yml` (extend)

### Acceptance Criteria
- System can run benchmark -> detect regression -> propose patch.
- Patch is blocked unless lint/tests/security gates pass.
- Improvement metadata is stored for trend analysis.

### Tests
- Integration: simulated regression triggers patch proposal pipeline.
- Integration: failed gates block auto-merge behavior.

---

## CI/CD Quality Gates (Required for all PRs)
1. Python unit tests pass.
2. TOURS lint/typecheck/tests pass.
3. Security tests pass (approval bypass, path traversal, SSRF).
4. Export snapshot tests pass (where applicable).
5. No new critical diagnostics.

## Metrics to Track (Program-Level)
1. Autonomous completion rate (non-destructive workflows).
2. Guardrail violation count and severity.
3. Mean time to build/export runnable artifact.
4. Regression rate across benchmark suite.
5. Cost per successful autonomous task.

## Migration Sequence (Low Risk)
1. Ship governance and async safety first (PR-1/PR-2).
2. Harden export/build boundaries and defaults (PR-3).
3. Refactor architecture behind stable interfaces (PR-4).
4. Externalize templates and add versioning (PR-5).
5. Enable self-improvement loop with strict CI gates (PR-6).

## Rollback Plan
- Each PR is independently revertible.
- Keep feature flags for policy enforcement and self-improve pipeline.
- Preserve previous export path behind compatibility mode until PR-5 stabilizes.

## Definition of Done (Program)
- Governance, reliability, and factory pipeline features are active by default.
- System can autonomously produce runnable outputs with policy-safe execution.
- Self-improvement loop proposes changes with measurable quality uplift and no gate regressions.
