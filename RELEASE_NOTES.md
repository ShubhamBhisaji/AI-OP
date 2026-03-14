# Release Notes

## vNext (2026-03-14) - Autonomous Factory Baseline

### Release Summary
This release promotes Aether OS to a production-oriented Autonomous Factory baseline with policy-governed execution, stronger runtime hardening, service decomposition, and an initial self-improvement loop.

### Breaking Changes
- Code execution now requires Docker sandbox availability. Host fallback execution was removed for security.
- AI provider request plumbing now uses litellm and no longer uses manual urllib provider code paths.

### Security and Reliability
- Centralized policy checks are enforced for tool calls with deny-by-default behavior for unregistered tools.
- Guarded tool calls produce approval-gated decisions and audit entries.
- Path handling for export/build flows is sanitized and constrained to approved base directories.
- SSRF protections are applied in hardened network/scraping paths.
- Approval bypass handling uses internal opaque token flow instead of forgeable request flags.
- Async decomposition handling avoids dependency-graph stalls when subtasks fail.

### Autonomous Factory Mode
- New kernel entrypoint: self_improve_once(eval_cases).
- Eval runner now enforces per-case timeout, case-count limits, and output/error truncation.
- Self-improvement persistence stores redacted summaries only (no full prompt/output payload retention).

### Architecture and Codebase Updates
- Added ExporterService and CompilerService and delegated public kernel build/export paths.
- Added TemplateRegistry and externalized initial templates.
- Added eval and self-improvement primitives:
  - aether-os/core/eval_runner.py
  - aether-os/core/failure_clustering.py
  - aether-os/core/self_improve.py
  - aether-os/evals/benchmark_runner.py
  - aether-os/evals/failure_clustering.py

### Migration Steps
1. Ensure Docker Desktop is installed and running on hosts that use code_runner.
2. Install dependency updates, including litellm.
3. Validate provider keys and default model settings in environment configuration.
4. Review policy allow/deny overrides and guarded-tool expectations before broad rollout.
5. Keep HITL enabled for guarded workflows during initial production adoption.

### Verification Checklist
1. Run Python unit tests and verify all test suites pass.
2. Execute a guarded tool call and confirm policy and approval behavior.
3. Run an async workflow and confirm no dependency stall on failed subtasks.
4. Run build_application and verify output is generated under safe output roots.
5. Run self_improve_once and verify only redacted summary is persisted.
6. Run code_runner with and without Docker and verify secure fail-closed behavior.

### Validation Performed
- Simulated runtime trace validated Policy -> Workflow -> Compiler execution path using Python.
- Regression and contract tests were added for export/build hardening, async runtime behavior, service extraction/template rendering, and self-improvement timeout/redaction paths.

### Known Follow-Ups
- Continue template externalization for remaining embedded templates.
- Extend self-improvement pipeline with CI quality-gate-driven patch proposal flow.
- Add template schema validation and version stamping in manifests.
