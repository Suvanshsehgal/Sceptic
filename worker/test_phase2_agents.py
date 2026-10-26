import os
import json
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import leak_hunter
import dependency_audit
import docstring_judge
import mcp_server
from crewai_extra_agents import leak_hunter_agent, purana_saman_agent, jhooti_docstring_agent
from audit_service import AuditService


@pytest.fixture(autouse=True)
def _no_dependency_audit_cache(monkeypatch):
    # Empty requirements files share one cache key, so a cached result from one test would leak into another.
    monkeypatch.setenv("SCEPTIC_DEP_AUDIT_CACHE_SECONDS", "0")


# A made-up key in the AWS access key format, so the scanner has something real to find.
FAKE_AWS_KEY = "AKIAZ7Q3XW2PLMN4RT5K"


def test_leak_hunter_reports_missing_scanner(monkeypatch):
    monkeypatch.setattr(leak_hunter.shutil, "which", lambda name: None)
    findings = leak_hunter.scan_secrets(".")
    assert len(findings) == 1
    assert findings[0]["agent_name"] == "Leak-Hunter"
    assert findings[0]["status"] == "ERROR"
    assert findings[0]["severity"] == "HIGH"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_leak_hunter_finds_secret_and_never_returns_its_value():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "config.py"), "w", encoding="utf-8") as f:
            f.write(f'AWS_KEY = "{FAKE_AWS_KEY}"\n')
        findings = leak_hunter.scan_secrets(tmp)

    leaks = [f for f in findings if f["status"] == "OPEN"]
    assert leaks, findings
    assert leaks[0]["file_path"] == "config.py"
    assert leaks[0]["line_number"] == 1
    serialized = json.dumps(findings)
    assert FAKE_AWS_KEY not in serialized
    assert leaks[0]["evidence"]["match"].endswith("[redacted]")


def test_redact_keeps_only_a_prefix():
    assert leak_hunter.redact("abcdefgh") == "abcd...[redacted]"
    assert leak_hunter.redact("") == ""


def test_dependency_audit_maps_pip_audit_vulnerabilities(monkeypatch):
    report = {"dependencies": [
        {"name": "requests", "version": "2.19.0", "vulns": [
            {"id": "PYSEC-2018-28", "fix_versions": ["2.20.0"], "description": "Credentials leak on redirect."}
        ]},
        {"name": "flask", "version": "3.0.0", "vulns": []},
    ]}
    monkeypatch.setattr(dependency_audit, "_run", lambda cmd, cwd=None: SimpleNamespace(stdout=json.dumps(report), stderr="", returncode=1))
    with tempfile.TemporaryDirectory() as tmp:
        req = os.path.join(tmp, "requirements.txt")
        open(req, "w").close()
        findings = dependency_audit.audit_python(req)
    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"
    assert "PYSEC-2018-28" in findings[0]["title"]
    assert "2.20.0" in findings[0]["recommendation"]


def test_dependency_audit_reports_unreachable_database(monkeypatch):
    monkeypatch.setattr(dependency_audit, "_run", lambda cmd, cwd=None: SimpleNamespace(stdout="", stderr="network down", returncode=1))
    with tempfile.TemporaryDirectory() as tmp:
        req = os.path.join(tmp, "requirements.txt")
        open(req, "w").close()
        findings = dependency_audit.audit_python(req)
    assert findings[0]["status"] == "ERROR"
    assert findings[0]["severity"] == "HIGH"


def test_node_audit_maps_npm_severities(monkeypatch):
    npm_report = {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "lodash": {"name": "lodash", "severity": "high", "isDirect": True, "range": "<4.17.21",
                       "via": [{"title": "Prototype Pollution"}], "fixAvailable": True},
            "minimist": {"name": "minimist", "severity": "moderate", "isDirect": False, "range": "<1.2.6",
                         "via": ["lodash"], "fixAvailable": False},
        },
    }
    monkeypatch.setattr(dependency_audit.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(dependency_audit, "_run", lambda cmd, cwd=None: SimpleNamespace(stdout=json.dumps(npm_report), stderr="", returncode=1))
    findings = dependency_audit.audit_node(".")
    by_name = {f["evidence"]["package"]: f for f in findings}
    assert by_name["lodash"]["severity"] == "HIGH"
    assert by_name["minimist"]["severity"] == "MEDIUM"
    assert "Prototype Pollution" in by_name["lodash"]["description"]


def test_dependency_audit_skips_directories_without_manifests():
    with tempfile.TemporaryDirectory() as tmp:
        assert dependency_audit.audit_dependencies(tmp) == []


class _FakeGroqResponse:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


def _fake_groq(content):
    class FakeCompletions:
        def create(self, **kwargs):
            FakeGroq.calls.append(kwargs)
            return _FakeGroqResponse(content)

    class FakeGroq:
        calls = []

        def __init__(self, api_key, **client_options):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    return FakeGroq


def test_docstring_judge_is_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    findings = docstring_judge.judge_docstrings("def f():\n    '''x'''\n", "f.py", api_key="")
    assert findings[0]["status"] == "SKIPPED"
    assert findings[0]["severity"] == "INFO"


def test_docstring_judge_reports_mismatch_as_low_and_makes_one_call(monkeypatch):
    content = json.dumps({"results": [
        {"function": "add", "verdict": "MISMATCH", "reason": "Docstring says sum, code multiplies."},
        {"function": "sub", "verdict": "OK", "reason": "Matches."},
    ]})
    fake = _fake_groq(content)
    monkeypatch.setattr("groq.Groq", fake)
    findings = docstring_judge.judge_docstrings("def add(a,b): return a*b", "m.py", api_key="k")
    assert len(findings) == 1
    assert findings[0]["severity"] == "LOW"
    assert "add" in findings[0]["title"]
    assert len(fake.calls) == 1


def test_docstring_judge_reports_llm_failure_as_error(monkeypatch):
    class Broken:
        def __init__(self, api_key, **client_options):
            raise RuntimeError("no network")

    monkeypatch.setattr("groq.Groq", Broken)
    findings = docstring_judge.judge_docstrings("def f():\n    pass\n", "f.py", api_key="k")
    assert findings[0]["status"] == "ERROR"


def test_mcp_server_exposes_phase2_tools():
    names = set(mcp_server.mcp._tool_manager._tools.keys())
    assert {"scan_secrets", "audit_dependencies", "judge_docstrings"} <= names


def test_phase2_agents_are_crewai_agents():
    for agent, role in [
        (leak_hunter_agent, "Leak-Hunter"),
        (purana_saman_agent, "Purana-Saman"),
        (jhooti_docstring_agent, "Jhooti-Docstring"),
    ]:
        assert agent.role == role
        assert len(agent.tools) == 1


def test_audit_service_reports_phase2_agents_in_contributions(monkeypatch):
    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: [])
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "ok.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    '''Returns x times two.'''\n    return x * 2\n")
        report = AuditService().audit_path(target)
    assert {"Leak-Hunter", "Purana-Saman", "Jhooti-Docstring"} <= set(report["agent_contributions"])
    assert report["agent_statuses"]["Leak-Hunter"] == "OK"


def test_audit_service_marks_failed_leak_scan_as_partial(monkeypatch):
    failure = [{"agent_name": "Leak-Hunter", "severity": "HIGH", "status": "ERROR", "title": "x"}]
    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: failure)
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "ok.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    '''Returns x times two.'''\n    return x * 2\n")
        report = AuditService().audit_path(target)
    assert report["agent_statuses"]["Leak-Hunter"] == "PARTIAL_FAILURE"
    assert report["recommendation"] != "APPROVE"
