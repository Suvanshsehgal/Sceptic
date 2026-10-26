# Sceptic Guardrails

This page lists the rules Sceptic enforces, where each rule lives in the code, and the rules that are not yet in place. Each enforced rule has a test named in brackets.

## 1. Verdict policy: BLOCK fails the check, a named person can override

| Verdict | Trust Score | Deployment gate (`scripts/deploy.py`) |
|---|---|---|
| APPROVE | 85–100 | Deployment proceeds |
| REQUEST_CHANGES | 65–84 | Deployment stops unless overridden |
| BLOCK | 0–64 | Deployment stops unless overridden |
| (missing) | — | Deployment stops (fail closed) |

- **No verdict means no deployment.** A missing or unknown recommendation is treated as unverified. [`backend/test_phase1_hardening.py::test_missing_verdict_blocks_deployment`]
- **Override requires a named approver and a reason.** Both `--override-by` and a reason of at least 10 characters are required. Without them the deployment stays blocked and the result says the override was rejected. [`test_override_without_approver_or_short_reason_is_rejected`]
- **Overrides are recorded.** A successful override appears in the deployment result as `gate_override` with the approver, the reason, and the verdict that was overridden. [`test_override_with_approver_and_reason_is_recorded`]
- **In CI** the verdict comes from `sceptic audit target_service --json`. The override reason is a `workflow_dispatch` input, and the approver is the GitHub actor who triggered the run.
- **Not yet in place:** the override is not restricted to an admin role. Any user who can run the workflow can override. That is the RBAC item in Phase 3. Overrides are also not stored in the database yet, so they are visible only in the workflow log.

## 2. Sandboxing for generated and audited code

Blind-Tester writes generated tests and the audited implementation to a temporary folder and runs them in a container built from `worker/sandbox/Dockerfile`. Each run uses:

- `--network none`: no network access.
- `--read-only` with the code mounted read-only at `/work`, and a 64 MB tmpfs at `/tmp`.
- `--cap-drop ALL` and `--security-opt no-new-privileges`.
- A non-root user (`65534:65534`).
- Limits of 256 MB memory (no swap), 1 CPU, and 128 processes. Execution is capped by `timeout`, and a timed-out container is removed with `docker rm -f`.

[`worker/test_sandbox_runner.py::test_live_container_has_no_network_and_read_only_code_mount`, `test_live_timeout_kills_container`]

- **Fail closed.** If Docker or the sandbox image is unavailable, nothing runs on the host. Blind-Tester reports a HIGH finding (`sandbox unavailable`), so the verdict cannot be APPROVE. [`test_blind_tester_reports_unavailable_sandbox_without_running_code`]
- **Host execution exists only as an explicit mode.** `SCEPTIC_SANDBOX=local-unsafe` runs generated tests on the host. The test suite uses this mode through the root `conftest.py`. Production must not set it.
- **Not yet in place:** the Fact-Checker imports modules named in the audited code inside the tool server process ([worker/languages/python_adapter.py](../worker/languages/python_adapter.py)). Importing a module can run its top-level code, so this step is not sandboxed. Moving it into the sandbox is planned.

## 2b. Languages and the sandbox runners

Blind-Tester runs generated tests for four languages. All of them run in the same sandbox image, with the same isolation flags:

| Language | Test runner | Fact-Checker (API checks) | Security rules |
|---|---|---|---|
| Python | pytest | Python AST and runtime inspection | Bandit and Semgrep (`semgrep_rules.yaml`) |
| JavaScript | Jest | tsc with checkJs, using the project's `node_modules` | Semgrep (`semgrep_rules_js.yaml`) |
| TypeScript | Jest with ts-jest | tsc, using the project's `node_modules` | Semgrep (`semgrep_rules_js.yaml`) |
| Java | JUnit 5 with javac | javac, using the Maven classpath when it resolves offline | Semgrep (`semgrep_rules_java.yaml`) |

- **Compilers never run the audited code.** tsc and javac only read and type-check the source.
- **Compiler results replace the list-based checks** for these languages. The list-based checks run only when a compiler is missing.
- **Scanner timeouts and errors are HIGH findings**, so a scan that did not finish cannot leave a verdict looking clean.
- **Runner versions are pinned** in `worker/tools/js/package-lock.json` (Jest 29.7.0, ts-jest 29.2.5, TypeScript 5.6.3) and in the sandbox Dockerfile (JUnit 1.11.4, verified by SHA-256).
- **Local host mode supports Python only.** `SCEPTIC_SANDBOX=local-unsafe` refuses JavaScript, TypeScript, and Java.

## 3. Tool boundary

The CrewAI agents do not import the scanners directly. Their tools call the Sceptic MCP server ([worker/mcp_server.py](../worker/mcp_server.py)), which exposes `verify_api_usage`, `scan_security`, `run_blind_tests`, and `post_github_comment`. The verdict comes from the deterministic tools, not from an LLM. The LLM is used only for optional triage and test generation.

- `post_github_comment` is a dry run unless `GITHUB_TOKEN` is set, and it rejects repository names that are not `owner/name`. [`test_comment_tool_dry_runs_without_token`, `test_comment_tool_rejects_malformed_repository`]

## 4. Authentication and access

- **Mock login is disabled in production** (`ENVIRONMENT=production`) and can be turned off with `ALLOW_MOCK_LOGIN=false`. [`test_mock_login_is_disabled_in_production`]
- **Google accounts cannot be taken over with a password.** Registering with the email of a Google-created account is rejected. [`test_register_cannot_take_over_google_account`]
- **Audits are visible only to their owner.** `GET /audits` and `GET /audits/{id}` require login and only return audits for the caller's projects. [`test_audits_require_authentication`, `test_audits_of_other_users_are_hidden`]
- **Not yet in place:** no roles (Admin, Developer, Viewer). Every logged-in user has the same rights. Phase 3.

## 5. Webhooks

- **HMAC signature.** When `GITHUB_WEBHOOK_SECRET` is set, the `X-Hub-Signature-256` header must match an HMAC-SHA256 of the raw body. A missing or wrong signature returns 401. [`test_webhook_rejects_unsigned_requests_when_secret_set`, `test_webhook_rejects_wrong_signature`, `test_webhook_accepts_valid_signature`]
- **Secret required in production.** Without a secret, a production webhook returns 503. [`test_webhook_requires_secret_in_production`]
- **Only a signed webhook can choose a project.** A `project_id` in an unsigned body is ignored.
- **Idempotency.** A repeated delivery for the same repository, PR number, and commit does not start a second audit. (Existing behavior, covered by `worker/test_phase5_orchestration.py`.)
- **Not yet in place:** rate limiting per repository and per IP. Phase 3.

## 6. Rollback safety

- **A rollback switches a service only through the configured command.** `ROLLBACK_COMMAND` runs without a shell, with placeholders for the target commit and image. Without it, the rollback is recorded as FAILED and nothing is switched. [`test_rollback_without_executor_is_recorded_failed_not_success`, `test_default_executor_runs_configured_command_with_placeholders`]
- **Success requires verification.** The target's `/health` and `/version` must match the expected commit before the deployment is marked ROLLED_BACK. (Existing behavior.)
- **One rollback per project at a time.** The project row is locked (`SELECT ... FOR UPDATE` on PostgreSQL) while the rollback lock is checked and acquired. [`backend/rollback_agent.py` `evaluate_and_execute`]
- **Crashed rollbacks do not block forever.** An `IN_PROGRESS` rollback older than `ROLLBACK_LOCK_TIMEOUT_SECONDS` (default 900) is marked FAILED and no longer holds the lock. [`test_stale_rollback_lock_does_not_block_new_rollbacks`, `test_fresh_rollback_lock_still_blocks`]
- **Not yet in place:** the status endpoint `PATCH /deployments/{id}/status` still lets the owner set `ACTIVE` directly. It is needed by `deploy.py`, so restricting it belongs with RBAC (Phase 3).

## 7. Rate limits and idempotency: summary

| Control | Status |
|---|---|
| Webhook HMAC signature | Enforced |
| Webhook idempotency (repository + PR + commit) | Enforced |
| Rollback single-flight lock per project | Enforced, with stale-lock expiry |
| Deployment idempotency key | Not yet in place |
| Webhook and API rate limits | Not yet in place (Phase 3) |

## 8. Phase 2 controls

- **Workflow changes need approval.** The Gatekeeper lists changes to `.github/workflows/*` between the previous and the deployed commit. Unless the deployed commit is in `WORKFLOW_APPROVED_COMMITS`, each change is a HIGH finding and a drift event, and the Gatekeeper reports FAIL. The check runs only when `GATEKEEPER_REPO_PATH` is set and the deployment is linked to its previous deployment. [`backend/test_phase2_features.py`, `test_gatekeeper_flags_unapproved_workflow_change`]. `.github/CODEOWNERS` requires review of workflow files.
- **Alerts never change outcomes.** A Watchdog FAIL and a completed rollback (SUCCESS or FAILED) are sent to Slack and Discord when `ALERT_SLACK_WEBHOOK_URL` or `ALERT_DISCORD_WEBHOOK_URL` is set. Only HTTPS URLs are used. Delivery errors are logged and ignored. Alerts have no cooldown yet, so a flapping Watchdog can send repeated messages.
- **Secrets are never printed.** Leak-Hunter stores only the first four characters of a secret followed by `[redacted]`. [`worker/test_phase2_agents.py::test_leak_hunter_finds_secret_and_never_returns_its_value`]
- **Missing scanners fail closed.** Leak-Hunter (gitleaks), Purana-Saman (pip-audit, npm audit), and the docstring check report HIGH ERROR findings when they cannot run, or when a dependency database is unreachable. An empty report is never read as "no vulnerabilities". [`test_dependency_audit_reports_unreachable_database`]
- **Live progress uses a token in the URL.** `EventSource` cannot send headers, so the stream endpoint accepts `?token=`. The token can end up in proxy and access logs. Treat those logs as sensitive, or move to a cookie or a short-lived stream ticket before production.
- **Live metrics are not stored.** `GET /deployments/{id}/live` reads the target and Prometheus on each call. Only `POST .../watchdog/check` records a snapshot.
