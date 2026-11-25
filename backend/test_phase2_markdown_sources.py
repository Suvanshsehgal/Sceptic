"""
Phase 2 tests: Markdown incident reports and allowlisted Markdown sources for the LLM.

- Offline tests cover the path rules, report rendering, and the no-key fallback.
- The live test asks Groq a question about the runbook; it runs only when GROQ_API_KEY is set.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adk_agents  # noqa: E402
import reports  # noqa: E402
from reports import SourceError, read_markdown_source, read_source, resolve_source  # noqa: E402


@pytest.fixture
def dirs(tmp_path: Path):
    runbooks = tmp_path / "runbooks"
    report_dir = tmp_path / "reports"
    runbooks.mkdir()
    report_dir.mkdir()
    (runbooks / "rb.md").write_text("# Runbook\n\nCheck /health first.\n", encoding="utf-8")
    (report_dir / "incident.md").write_text("# Report\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("do not read", encoding="utf-8")
    return (runbooks, report_dir), tmp_path


@pytest.mark.parametrize("bad_name", [
    "../secret.md",
    "..\\secret.md",
    "sub/rb.md",
    "rb.txt",
    "rb",
    "",
    "/etc/passwd.md",
    "C:\\Windows\\win.md",
])
def test_unsafe_names_are_rejected(dirs, bad_name):
    allowed, _ = dirs
    with pytest.raises(SourceError):
        resolve_source(bad_name, allowed)


def test_file_outside_allowed_folders_is_not_readable(dirs):
    allowed, root = dirs
    with pytest.raises(SourceError):
        resolve_source("secret.md", allowed)  # exists, but not in an allowed folder


def test_allowed_runbook_is_readable(dirs):
    allowed, _ = dirs
    assert "Check /health first." in read_source("rb.md", allowed)


def test_repo_runbook_is_in_the_allowlist():
    content = read_source("high_error_rate.md")
    assert "HIGH_ERROR_RATE" in content


def test_oversized_source_is_rejected(dirs):
    allowed, _ = dirs
    (allowed[0] / "big.md").write_text("x" * (reports.MAX_SOURCE_BYTES + 1), encoding="utf-8")
    with pytest.raises(SourceError, match="too large"):
        read_source("big.md", allowed)


def test_tool_returns_error_instead_of_raising():
    result = read_markdown_source("../../etc/hosts")
    assert "error" in result and "content" not in result


def test_tool_returns_content_for_allowed_name():
    result = read_markdown_source("high_error_rate.md")
    assert result["name"] == "high_error_rate.md"
    assert "Runbook: high error rate" in result["content"]


def test_write_then_read_round_trip(dirs):
    allowed, _ = dirs
    path = reports.write_incident_report("run-1.md", "# Run 1\n", directory=allowed[1])
    assert path.read_text(encoding="utf-8") == "# Run 1\n"
    assert "# Run 1" in read_source("run-1.md", allowed)


def test_write_rejects_unsafe_report_name(dirs):
    allowed, _ = dirs
    with pytest.raises(SourceError):
        reports.write_incident_report("../escape.md", "x", directory=allowed[1])


def test_render_contains_verdict_metrics_and_findings():
    probe = {
        "verdict": "FAIL",
        "health_status": "healthy",
        "request_count": 100,
        "error_count": 40,
        "error_rate": 0.4,
        "latency_avg_seconds": None,
        "latency_p95_seconds": 0.2,
        "findings": [{"finding_type": "HIGH_ERROR_RATE", "severity": "HIGH", "description": "40% errors"}],
    }
    md = reports.render_incident_report(
        deployment_label="demo-site abc123",
        probe=probe,
        summary="Errors are high.",
        llm_used=False,
    )
    assert md.startswith("# Incident report: demo-site abc123")
    assert "**FAIL**" in md
    assert "| Error rate | 40.00% |" in md
    assert "| Average latency | not available |" in md
    assert "**HIGH_ERROR_RATE** (HIGH): 40% errors" in md
    assert "deterministic fallback" in md


def test_qa_agent_has_the_read_only_tool():
    agent = adk_agents.build_report_qa_agent()
    assert agent.name == "report_qa"
    assert read_markdown_source in agent.tools


@pytest.mark.asyncio
async def test_answer_without_key_returns_source_text(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = await adk_agents.answer_from_source("high_error_rate.md", "What is the first check?")
    assert result["llm_used"] is False
    assert "Runbook: high error rate" in result["content"]


@pytest.mark.asyncio
async def test_answer_rejects_disallowed_source(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    result = await adk_agents.answer_from_source("../reports.py", "anything")
    assert result["answer"] is None
    assert result["error"]


@pytest.mark.asyncio
async def test_answer_uses_llm_when_key_is_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    seen = {}

    async def fake_llm(agent, prompt):
        seen["prompt"] = prompt
        return "Check /health first (Recovery section)."

    monkeypatch.setattr(adk_agents, "_run_llm", fake_llm)
    result = await adk_agents.answer_from_source("high_error_rate.md", "What is the first check?")
    assert result["llm_used"] is True
    assert "Source file: high_error_rate.md" in seen["prompt"]
    assert result["answer"].startswith("Check /health")


@pytest.mark.asyncio
async def test_provider_error_falls_back_to_source_text(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    async def boom(agent, prompt):
        raise RuntimeError("429 rate limit reached")

    monkeypatch.setattr(adk_agents, "_run_llm", boom)
    result = await adk_agents.answer_from_source("high_error_rate.md", "q")
    assert result["llm_used"] is False
    assert "429" in result["fallback_reason"]
    assert "Runbook: high error rate" in result["content"]


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="live Groq test needs GROQ_API_KEY")
@pytest.mark.asyncio
async def test_live_groq_answers_from_runbook():
    result = await adk_agents.answer_from_source(
        "high_error_rate.md", "What should an operator check first when the error rate is high?"
    )
    assert result["llm_used"] is True, result["fallback_reason"]
    assert "health" in result["answer"].lower()
