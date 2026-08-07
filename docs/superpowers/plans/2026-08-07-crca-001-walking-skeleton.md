# CRCA-001 Manifest-to-Run Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can submit a valid versioned Task Manifest through the CLI, create one auditable Diagnosis Run through Diagnosis Application Service, and receive a deterministic terminal summary plus ordinary-file run artifacts without GPU, network, Docker, or a real model.

**Architecture:** Keep CLI as an adapter over one application service. Pydantic models define public input/output contracts, FakeModelProvider supplies the deterministic external-model boundary, and a file-backed RunStore owns ADR-0008 persistence. The application service orchestrates these collaborators but does not implement the later lifecycle state machine or ReAct loop.

**Tech Stack:** Python 3.10, Pydantic 2.x, standard-library argparse/pathlib/json/uuid, pytest, ruff, mypy, setuptools build backend.

## Global Constraints

- Diagnosis Application Service is the only highest application/test seam.
- Task Manifest is versioned and structurally includes task ID, repository ID, base snapshot, Faulty Commit, CI log, registered test command ID, Docker image, read/write scopes, and tool-call limit.
- Each Diagnosis Run uses an independent directory with Manifest snapshot, JSONL events, and JSON Root Cause Report.
- Large-content storage, database persistence, content addressing, deduplication, replay, and crash recovery are excluded.
- CLI is non-interactive and serial; no HTTP API or background execution.
- FakeModelProvider must make default tests deterministic and require no GPU, network, Docker, or real model service.
- Do not implement a lifecycle state machine, ReAct, Hypothesis/Evidence/Experiment behavior, any of the five real tools, RAG, Docker execution, patching, or Validation.
- Use canonical terms from `CONTEXT.md`; do not fabricate a Root Cause Candidate in the walking skeleton.
- Invalid Manifest input fails before Diagnosis Run creation and returns a structured machine-readable error.

---

### Task 1: CRCA-001 Manifest-to-Run vertical slice

**Files:**
- Create: `pyproject.toml` — package metadata, runtime/dev dependencies, CLI entry point, pytest/ruff/mypy configuration.
- Modify: `.gitignore` — ignore virtualenv, caches, coverage, build output, and local run output while preserving existing planning ignores.
- Create: `src/coderca/__init__.py` — package version export only.
- Create: `src/coderca/contracts.py` — Pydantic Task Manifest, run result, report, event, artifact, and structured CLI error contracts.
- Create: `src/coderca/model_provider.py` — narrow ModelProvider protocol and deterministic FakeModelProvider.
- Create: `src/coderca/run_store.py` — independent run-directory creation and JSON/JSONL persistence.
- Create: `src/coderca/application.py` — DiagnosisApplicationService orchestration and public `start_diagnosis` seam.
- Create: `src/coderca/cli.py` — argparse adapter and structured stdout/stderr behavior.
- Create: `tests/conftest.py` — valid Task Manifest fixture/data builder.
- Create: `tests/test_application.py` — public application-service vertical and uniqueness tests.
- Create: `tests/test_cli.py` — success and invalid-input adapter tests.
- Modify if necessary: `README.md` — only the minimum local install/test/CLI invocation needed to use this implemented slice; do not advertise future capabilities as implemented.

**Interfaces:**
- `TaskManifest.model_validate_json(raw: str) -> TaskManifest` consumes the versioned JSON contract with fields `schema_version`, `task_id`, `repository_id`, `base_snapshot`, `faulty_commit`, `ci_log`, `test_command_id`, `docker_image`, `read_paths`, `write_paths`, and `tool_call_limit`. Use `schema_version: Literal["1"]`; non-empty strings for identifiers and inputs; non-empty `read_paths`; `write_paths` may be empty; `tool_call_limit` is an integer from 1 through 8; reject unknown fields.
- `ModelProvider.complete(manifest: TaskManifest) -> ModelCompletion` is the external-model boundary. `FakeModelProvider.complete` returns the same honest terminal summary for the same Manifest and performs no I/O.
- `RunStore(root: Path).create_run(run_id: str) -> RunArtifacts` creates `<root>/<run_id>/` and exposes `manifest.json`, `events.jsonl`, and `report.json` paths.
- `DiagnosisApplicationService(provider: ModelProvider, run_store: RunStore).start_diagnosis(manifest: TaskManifest) -> DiagnosisRunResult` is the sole highest application seam.
- `cli.main(argv: Sequence[str] | None = None) -> int` reads the Manifest, invokes the service once, prints one JSON success summary to stdout, or one JSON error object to stderr.
- `DiagnosisEvent` contains `sequence`, `event_type`, `run_id`, `task_id`, `stage`, and `message`; sequences start at 1 and increase in file order.
- Success summary and the minimal report use terminal `stage = "finalizing"`, `status = "completed"`, and `stop_reason = "fake_model_completed"`, plus `run_id`, `task_id`, an honest `summary`, and `run_directory` where applicable.
- Structured error shape is `{"error": {"code": <stable code>, "message": <human text>, "details": <JSON value>}}` and invalid Manifest exits with code 2.

- [x] **Step 1: Establish packaging and a focused failing application test**

Create `pyproject.toml` for package `coderca`, Python `>=3.10`, Pydantic `>=2.8,<3`, and optional `dev` dependencies for pytest, ruff, and mypy. Configure strict-enough ruff/mypy settings for `src/coderca` and `tests`. Add an application test that constructs a valid Manifest, calls `DiagnosisApplicationService.start_diagnosis`, and expects a terminal result plus three parseable run artifacts.

- [x] **Step 2: Run the focused application test and capture RED evidence**

Run: `python -m pytest tests/test_application.py -q`

Expected: FAIL because the `coderca` contracts/application interfaces do not exist yet. Record the command and relevant failure in the implementer report.

- [x] **Step 3: Implement contracts, FakeModelProvider, RunStore, and application seam minimally**

Implement only enough public contracts and orchestration to satisfy the application test. Use UUID-based unique Run IDs; write the normalized Manifest snapshot before terminal artifacts; write valid newline-delimited event objects; write a minimal honest report with no fabricated candidates. Use atomic-enough ordinary file writes for this single-process Ticket without adding recovery machinery.

- [x] **Step 4: Run the focused application test and capture GREEN evidence**

Run: `python -m pytest tests/test_application.py -q`

Expected: PASS with clean output.

- [x] **Step 5: Add the next failing behavior tests one vertical behavior at a time**

Add tests, each through a public seam, for: two calls create distinct directories; JSONL lines parse independently; normalized Manifest snapshot matches accepted input; CLI success summary exposes all required fields; invalid Manifest emits the stable structured error, exits 2, and creates no run directory. Run each focused test before implementation and record at least one representative additional RED result.

- [x] **Step 6: Implement the thin CLI and remaining minimal behavior**

Use standard-library argparse. Accept a positional Manifest path and `--runs-dir`. On success instantiate `DiagnosisApplicationService` with FakeModelProvider and RunStore, invoke it once, and print a JSON summary. Handle file/JSON/Manifest errors explicitly as structured JSON without broad exception swallowing. Do not duplicate orchestration in the CLI.

- [x] **Step 7: Complete focused verification and keep documentation honest**

Run the application and CLI test files repeatedly while iterating. If README usage is missing, document only environment setup, `coderca MANIFEST --runs-dir RUNS`, artifact names, and the FakeModelProvider limitation.

- [x] **Step 8: Run all gates**

Run exactly:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/coderca tests
python -m build
```

All commands must pass with clean output. If the `build` module is not present, add it to the dev extra instead of skipping the build gate.

- [x] **Step 9: Self-review against CRCA-001 and commit**

Verify each Acceptance Criterion, confirm no Out of Scope capability was added, and inspect `git diff --check`. Write the required report with RED/GREEN evidence and commit all Ticket work on the current branch with a message referencing Issue #2.
