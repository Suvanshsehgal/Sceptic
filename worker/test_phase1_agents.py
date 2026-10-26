import json

from crewai import Agent

import mcp_client
from mcp_client import get_mcp_client
import mcp_server
from crewai_wrapper import fact_checker_agent, run_fact_checker
from crewai_blind_tester import blind_tester_agent, run_blind_tester
from crewai_security_guard import security_guard_agent, run_security_guard
from crewai_reporter import reporter_agent
from orchestrator import AuditOrchestrator
from blind_tester import SpecificationMetadata


def test_all_agents_are_crewai_agents_with_one_tool_each():
    for agent, role in [
        (fact_checker_agent, "Fact-Checker"),
        (blind_tester_agent, "Blind-Tester"),
        (security_guard_agent, "Security-Guard"),
        (reporter_agent, "Reporter"),
    ]:
        assert isinstance(agent, Agent)
        assert agent.role == role
        assert len(agent.tools) == 1


def test_mcp_server_exposes_the_deterministic_tools():
    names = set(mcp_server.mcp._tool_manager._tools.keys())
    assert {"verify_api_usage", "scan_security", "run_blind_tests", "post_github_comment"} <= names


def test_fact_checker_tool_goes_through_mcp_and_flags_hallucinated_api(monkeypatch):
    calls = []
    original = mcp_client.SceptiMCPClient.call_tool

    def recording_call(self, name, arguments, timeout=600):
        calls.append(name)
        return original(self, name, arguments, timeout)

    monkeypatch.setattr(mcp_client.SceptiMCPClient, "call_tool", recording_call)
    findings = run_fact_checker("import os\nos.path.joinn('a', 'b')\n", file_path="x.py")
    assert calls == ["verify_api_usage"]
    assert any(f["title"] == "Non-existent API" for f in findings)


def test_orchestrator_invokes_each_agent_tool_through_mcp(monkeypatch):
    calls = []
    original = mcp_client.SceptiMCPClient.call_tool

    def recording_call(self, name, arguments, timeout=600):
        calls.append(name)
        return original(self, name, arguments, timeout)

    monkeypatch.setattr(mcp_client.SceptiMCPClient, "call_tool", recording_call)
    spec = SpecificationMetadata(
        function_name="add",
        docstring="Adds two numbers.",
        specification="Returns the sum of a and b.",
    )
    report = AuditOrchestrator().run_pipeline("def add(a, b):\n    return a + b\n", spec, file_path="add.py")
    assert {"verify_api_usage", "run_blind_tests", "scan_security"} <= set(calls)
    assert report["recommendation"] in ("APPROVE", "REQUEST_CHANGES", "BLOCK")


def test_comment_tool_dry_runs_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = json.loads(mcp_server.post_github_comment("owner/repo", 3, "hello"))
    assert out["posted"] is False
    assert out["dry_run"] is True


def test_comment_tool_rejects_malformed_repository(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-be-used")
    out = json.loads(mcp_server.post_github_comment("not a repo; rm -rf", 3, "hello"))
    assert out["posted"] is False
    assert "owner/name" in out["error"]


def test_reporter_agent_dry_run_round_trip(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from crewai_reporter import post_pr_summary
    out = post_pr_summary("owner/repo", 5, "summary")
    assert out["dry_run"] is True
