# Sceptic: agentic AI notes (phase 1 evaluation)

Everything below comes from the code. Where something is not built yet, it says so.

## 1. Agents used

Seven agents do the verification. Each is a CrewAI `Agent` (or a plain class for the Synthesizer).

| Agent | Code location | What it does |
|---|---|---|
| Fact-Checker | `worker/crewai_wrapper.py:53`, logic in `worker/fact_checker.py` and `worker/compiler_verifier.py` | Checks that every API call in the code exists, using the AST (Python), `tsc` (JS/TS), or `javac` (Java) |
| Blind-Tester | `worker/crewai_blind_tester.py:43`, logic in `worker/blind_tester.py` | An LLM writes tests from the docstring/spec only, then runs them in the Docker sandbox |
| Security-Guard | `worker/crewai_security_guard.py:38`, logic in `worker/security_guard.py` | Bandit and Semgrep scans, then an LLM adds context to each finding |
| Leak-Hunter | `worker/crewai_extra_agents.py:44`, logic in `worker/leak_hunter.py` | Secret scanning with gitleaks; secrets are redacted in the output |
| Purana-Saman | `worker/crewai_extra_agents.py:53`, logic in `worker/dependency_audit.py` | Dependency CVEs via pip-audit, npm audit, and osv-scanner |
| Jhooti-Docstring | `worker/crewai_extra_agents.py:62`, logic in `worker/docstring_judge.py` | An LLM checks whether each docstring matches what the code does |
| Reporter | `worker/crewai_reporter.py:33` | Writes the summary posted as a pull request comment |
| Synthesizer | `worker/synthesizer.py` (plain Python, not a CrewAI agent) | Combines all findings into the trust score and verdict |

After deployment, three more agents run on the backend: **Watchdog** (`backend/watchdog.py`), **Gatekeeper** (`backend/gatekeeper.py`), and **Rollback** (`backend/rollback_agent.py`). These are not CrewAI agents.

## 2. Input and output of each agent, and where results are saved

Every agent returns a list of **findings**. Each finding is a dict with `agent_name`, `severity`, `status`, `title`, `description`, `file_path`, `evidence`, and `recommendation`.

| Agent | Input | Output |
|---|---|---|
| Fact-Checker | `source_code`, `file_path`, `language` | Findings with status INVALID, UNRESOLVED, or VALID |
| Blind-Tester | Spec only (function name, docstring, language) for the LLM. The implementation is used only to run the tests | PASS, FAIL (Specification Violation), or ERROR (could not be collected) |
| Security-Guard | `source_code`, `file_path` | Scanner findings plus an LLM context note |
| Leak-Hunter | A file or folder path | Secret findings with the secret redacted |
| Purana-Saman | A folder path (finds manifests such as `requirements.txt` and `package-lock.json`) | Vulnerable-package findings |
| Jhooti-Docstring | `source_code`, `file_path` | LOW findings for docstring mismatches |
| Synthesizer | All findings from the agents above | `trust_score`, `recommendation`, `severity_breakdown`, `summary` |

**Where the results are saved:**
- **Worker path (web and webhook audits):** `worker/celery_app.py`, function `execute_audit_pipeline` (line 64). It saves the run to the `audit_runs` table (`status`, `trust_score`, `summary`, and `progress` as JSON). Each finding is saved as a row in the `agent_findings` table (line 131), linked to the run by `audit_run_id`.
- **CLI path:** the report is printed to the terminal, or printed as JSON with `--json`. It is saved to the backend only if you are logged in with an active project (`cli/main.py`, `execute_audit_flow`).
- **Models:** `backend/models.py`. `AuditRun` is at line 274, and `AgentFinding` is at line 314.

## 3. MCP, CrewAI, and ADK

**MCP (Model Context Protocol)**
- Server: `worker/mcp_server.py`. It uses `FastMCP("sceptic-tools")` and exposes seven tools: `verify_api_usage`, `scan_security`, `run_blind_tests`, `post_github_comment`, `scan_secrets`, `audit_dependencies`, and `judge_docstrings`.
- Client: `worker/mcp_client.py`. It starts the server over stdio, using `StdioServerParameters`.
- Use: the CrewAI tool wrappers call `get_mcp_client().call_tool(...)`. For example, `crewai_wrapper.py:50` calls `verify_api_usage`.
- External tools: Semgrep, Bandit, gitleaks, pip-audit, npm audit, osv-scanner, `tsc`, and `javac` are called through MCP.

**CrewAI**
- Each agent is a `crewai.Agent` with a role, a goal, and a backstory. Each one has a `@tool` function, for example `crewai_wrapper.py:42`.
- `Agent`, `Task`, `Crew`, and `Process` are imported in `crewai_wrapper.py`, `crewai_blind_tester.py`, and `crewai_security_guard.py`.
- The main pipeline calls the deterministic tools directly. The full CrewAI `Crew` run (`analyze_with_crewai` in `crewai_wrapper.py`) is optional and needs an LLM.

**ADK (Google Agent Development Kit, google-adk 2.13.0)**
- `backend/adk_agents.py`: the Watchdog narrator and the report Q&A are `LlmAgent`s, backed by Groq through LiteLLM. Both carry the guardrail callbacks from `worker/guardrails.py` (model and tool, before and after).
- `backend/a2a_interop.py`: the Triage side reaches the advisor through ADK's `RemoteA2aAgent`, the ADK A2A client.

**A2A (agent-to-agent protocol)**
- Official protocol via the `a2a-sdk` (1.3.1). The CrewAI Rollback Advisor is served as an A2A agent: agent card at `/a2a-interop/advisor/.well-known/agent-card.json`, JSON-RPC `message/send` at `/a2a-interop/advisor/`. The ADK triage agent calls it over that wire protocol.
- Interoperability is therefore ADK (client, `RemoteA2aAgent`) to CrewAI (server, `Agent` with a deterministic tool), with no shared Python objects between them.
- The earlier in-house subset (`backend/a2a_subset.py`, formerly `a2a.py`) still carries the Watchdog to Rollback chain. It is not the protocol the interop uses.
- Authority stays deterministic. The advisor only recommends, and `rollback_executed` is always false in the triage result. The RollbackAgent safety checks decide any rollback. Automatic rollback from the Watchdog is opt-in (`SCEPTIC_A2A_AUTO_ROLLBACK=true`).

## 4. Orchestration and where it is implemented

There are three layers.

1. **`worker/audit_service.py`, `AuditService.audit_path` (line 51).** This is the top level. It finds the files, runs the per-file loop, starts Leak-Hunter and Purana-Saman in a background thread pool (`ThreadPoolExecutor`), calls the Synthesizer, and returns the report.
2. **`worker/orchestrator.py`, `AuditOrchestrator`.**
   - `run_file_checks` (line 50) runs Fact-Checker and Security-Guard once per file.
   - `run_spec_checks` (line 106) runs Blind-Tester once per function.
   - `run_pipeline` (line 152) combines both and calls the Synthesizer.
   - Pattern: **fan-out and fan-in**. Independent agents run separately, and their findings are gathered for the Synthesizer.
3. **`worker/celery_app.py`, `execute_audit_pipeline` (line 64).** This runs the audit as a background job from a Redis queue. It updates progress and saves the results.

Entry points: `cli/main.py` (`execute_audit_flow`), and `backend/main.py` (`create_cli_audit` and the GitHub webhook), which queue the job for Celery.

## 5. Other agentic AI points

- **Context sharing.** One `AuditContext` (Pydantic, `worker/audit_models.py`) is the shared state of an audit. `AuditService` and `AuditOrchestrator.run_pipeline` write every agent's findings into it as the agent finishes. The Synthesizer reads the findings from it to build the report, and the Reporter publishes that report as Markdown. The context also keeps an execution log (agent, event, count, time) and per-agent status. The Blind-Tester never reads from it: its isolation rule (no implementation, no other agent's findings) is unchanged. Findings stay plain dicts, and `validate_finding()` records malformed ones as warnings without altering them.
- **Monitoring and callbacks.** `progress_callback` in `audit_service.py` drives the CLI spinner. `notify()` in `orchestrator.py` reports each agent as it finishes. `record_progress` in `celery_app.py` writes the progress JSON to the database, and the SSE stream reads it. Logging is done with `logger`.
- **Guardrails and validation.**
  - `validate_isolation()` in `blind_tester.py` rejects specs that contain the implementation.
  - `_parse_tool_input` in `crewai_wrapper.py` validates the tool input.
  - The sandbox has no network, a read-only filesystem, and a memory limit.
  - Secrets are redacted.
  - Webhooks are checked with HMAC-SHA256.
  - The deploy gate fails closed.
  - Owner checks guard every query.
  - Missing data is reported as UNRESOLVED, never as a pass.
- **Structured output.** The API uses Pydantic schemas (`backend/schemas.py`). The audit report is the `AuditReport` Pydantic model (score 0 to 100, verdict limited to APPROVE / REQUEST_CHANGES / BLOCK). It is delivered as JSON (`sceptic audit --json`), as Markdown with a per-agent table and the most severe findings (`--markdown`, and the pull request comment), and as the Rich terminal view. `AuditReport.to_dict()` keeps the dict shape the CLI, Celery task and database code already read.
- **Incomplete audits are not approved.** If a stage crashes or a source file cannot be read, the report lists it in `incomplete_reasons` and the verdict cannot be APPROVE, whatever the score. Tools that are only unavailable (for example a missing scanner) keep the existing capped penalty.
- **Observability (Langfuse, `worker/tracing.py`).** One trace per audit, with an agent span per agent, an MCP tool span per tool call (the tool runs in a separate process, and its spans join the trace through a `trace_context` argument), and a generation per Groq call with model, tokens and optional cost. The trace id is stored on `AuditRun.trace_id`, the API returns a `trace_url`, and the dashboard and CLI link to it. Off unless `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set. By default no source code, prompt or response leaves the process: spans carry sizes and hashes. Content is included only with `SCEPTIC_TRACE_CONTENT=true`, and then credentials are masked. The default mode was verified end to end: the audit trace reached an OTLP receiver with the right tree, and the audited source text was not in the export. Prometheus and Grafana still monitor only the target service.
- **Guardrails (`worker/guardrails.py`).** Input checks on untrusted text (docstrings, specs, questions, feature descriptions): size, control characters, prompt-injection patterns, abusive language, and a Groq-hosted Prompt Guard 2 classifier as a second stage. Output checks: every finding-producing MCP tool must return a valid list of findings, or the call fails. Measured results are in the Guardrail section below.
- **Evaluation.** Seeded-bug evaluation: 75% catch rate on 12 bugs across 3 runs (`evaluation/README.md`), recorded before Phase A through E. Performance and cost: see the Performance section below.
- **Evaluation.** Seeded-bug evaluation: 75% catch rate on 12 bugs across 3 runs (`evaluation/README.md`). Test suite: 229 passed, 1 skipped.

## 6. Requirements status

- **Shared state and structured output:** done (`AuditContext`, `AuditReport`).
- **Tool integration via MCP:** done (7 tools, stdio transport).
- **CrewAI and ADK:** both used. CrewAI agents run the pre-deploy checks and the advisor. ADK runs the narrator, the Q&A and the triage client.
- **A2A between ADK and CrewAI:** done with the official `a2a-sdk`.
- **Tracing (Langfuse):** done. Verified in default and content modes. The Langfuse hosted service itself was not exercised: the export was checked against a local OTLP receiver.
- **Guardrails and callbacks:** done, with measured rates (see below).
- **Performance, time and cost:** measured (see below).
- **Cloud deployment:** not done. The compose and CI/CD files exist, but nothing is running on a cloud platform.

Known limits are listed in the guardrail and performance sections, not hidden in these bullets.
