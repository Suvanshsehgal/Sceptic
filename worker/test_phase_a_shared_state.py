"""
Phase A: shared audit state (AuditContext) and the structured AuditReport.

These tests do not call an LLM, Docker or any scanner. The agents are replaced with fixed findings.
"""
import inspect
import json
import os
import sys
import tempfile
import threading

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))

import audit_service
from audit_models import (
    AuditContext, AuditReport, VERIFICATION_AGENTS, render_markdown, validate_finding,
)
from audit_service import AuditService
from blind_tester import SpecificationMetadata
from crewai_blind_tester import run_blind_tester
from orchestrator import AuditOrchestrator
from synthesizer import ReportSynthesizer, TrustScoreCalculator


def finding(agent, severity="INFO", status="VALID", title="t", **extra):
    return {"agent_name": agent, "severity": severity, "status": status, "title": title, **extra}


# ---------- validate_finding ----------

def test_validate_finding_accepts_well_formed_finding():
    assert validate_finding(finding("Fact-Checker", "HIGH", line_number=3)) == []


@pytest.mark.parametrize("bad, expected", [
    ("not a dict", "expected an object"),
    ({"severity": "HIGH", "title": "x"}, "missing agent_name"),
    ({"agent_name": "A", "severity": "SEVERE", "title": "x"}, "unknown severity"),
    ({"agent_name": "A", "severity": "HIGH"}, "missing title"),
    ({"agent_name": "A", "severity": "HIGH", "title": "x", "line_number": "3"}, "line_number"),
    ({"agent_name": "A", "severity": "HIGH", "title": "x", "line_number": True}, "line_number"),
])
def test_validate_finding_reports_problems(bad, expected):
    assert any(expected in problem for problem in validate_finding(bad))


# ---------- AuditContext ----------

def test_context_keeps_findings_in_call_order_and_groups_by_agent():
    ctx = AuditContext()
    ctx.record([finding("Fact-Checker", title="a")], "Fact-Checker")
    ctx.record([finding("Security-Guard", title="b"), finding("Security-Guard", title="c")], "Security-Guard")
    assert [f["title"] for f in ctx.all_findings] == ["a", "b", "c"]
    assert [f["title"] for f in ctx.findings_by("Security-Guard")] == ["b", "c"]


def test_context_never_alters_or_drops_a_finding():
    original = finding("Fact-Checker", "HIGH", contextual_analysis="extra", line_number="3")
    snapshot = dict(original)
    ctx = AuditContext()
    ctx.record([original], "Fact-Checker")
    assert ctx.all_findings[0] is original
    assert original == snapshot
    assert any(e.event == "schema_warning" for e in ctx.events)


def test_error_finding_marks_its_own_agent_partial_failure():
    ctx = AuditContext()
    ctx.record([finding("Security-Guard", "MEDIUM", "ERROR", "scanner crashed")], "Security-Guard")
    assert ctx.agent_statuses["Security-Guard"] == "PARTIAL_FAILURE"
    assert ctx.agent_statuses["Fact-Checker"] == "OK"


def test_source_agent_is_the_fallback_owner():
    ctx = AuditContext()
    ctx.record([{"severity": "LOW", "status": "ERROR", "title": "x"}], "Leak-Hunter")
    assert ctx.agent_statuses["Leak-Hunter"] == "PARTIAL_FAILURE"
    assert len(ctx.findings_by("Leak-Hunter")) == 1


def test_non_dict_finding_is_skipped_with_a_warning_and_does_not_crash_scoring():
    ctx = AuditContext()
    ctx.record(["oops", finding("Fact-Checker", "HIGH")], "Fact-Checker")
    assert len(ctx.all_findings) == 1
    assert ctx.agent_statuses["Fact-Checker"] == "PARTIAL_FAILURE"
    report = ReportSynthesizer().build_report(ctx)
    assert report.trust_score == 80


def test_record_failure_adds_error_finding_and_marks_agent():
    ctx = AuditContext()
    ctx.record_failure("Synthesizer", "Audit Pipeline Failure", "boom", file_path="a.py")
    assert ctx.agent_statuses["Synthesizer"] == "PARTIAL_FAILURE"
    assert ctx.all_findings[0]["status"] == "ERROR"
    assert any(e.event == "failed" for e in ctx.events)


def test_context_is_safe_to_write_from_many_threads():
    ctx = AuditContext()

    def work(n):
        for i in range(50):
            ctx.record([finding("Blind-Tester", title=f"{n}-{i}")], "Blind-Tester")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ctx.all_findings) == 400
    assert len(ctx.findings_by("Blind-Tester")) == 400


# ---------- AuditReport / Synthesizer ----------

def test_report_score_and_verdict_come_only_from_trust_calculator():
    ctx = AuditContext()
    ctx.record([finding("Security-Guard", "CRITICAL", "INVALID", "RCE")], "Security-Guard")
    ctx.record([finding("Blind-Tester", "HIGH", "FAIL", "spec")], "Blind-Tester")
    report = ReportSynthesizer().build_report(ctx)
    expected = TrustScoreCalculator.calculate(ctx.all_findings)
    assert report.trust_score == expected["trust_score"] == 45
    assert report.recommendation == expected["recommendation"] == "BLOCK"
    assert report.severity_breakdown == expected["severity_breakdown"]


def test_report_model_rejects_out_of_range_score_and_unknown_verdict():
    with pytest.raises(ValidationError):
        AuditReport(trust_score=101, recommendation="APPROVE")
    with pytest.raises(ValidationError):
        AuditReport(trust_score=50, recommendation="MAYBE")


def test_report_to_dict_is_json_safe_and_keeps_both_finding_keys():
    ctx = AuditContext(target_path="x")
    ctx.record([finding("Fact-Checker", "HIGH", "INVALID", "bad api")], "Fact-Checker", "a.py")
    data = ReportSynthesizer().build_report(ctx).to_dict()
    json.dumps(data)
    assert data["findings"] == data["all_findings"]
    assert data["total_findings"] == 1
    assert set(VERIFICATION_AGENTS) == set(data["agent_contributions"])
    assert data["execution_log"][-1]["event"] == "completed"


def test_three_agent_synthesize_keeps_its_original_keys_and_summary():
    out = ReportSynthesizer().synthesize(
        [finding("Fact-Checker")], [finding("Blind-Tester")], [finding("Security-Guard")]
    )
    for key in ("trust_score", "recommendation", "summary", "severity_breakdown",
                "agent_contributions", "total_findings", "all_findings"):
        assert key in out
    assert set(out["agent_contributions"]) == {"Fact-Checker", "Blind-Tester", "Security-Guard"}
    assert out["trust_score"] == 100 and out["recommendation"] == "APPROVE"
    assert "Audit completed with Trust Score: 100/100" in out["summary"]


def test_pipeline_report_has_shared_context_log():
    class Stub(AuditOrchestrator):
        def run_file_checks(self, *args, **kwargs):
            return {"fact_checker": [finding("Fact-Checker")], "security_guard": [finding("Security-Guard", "LOW")]}

        def run_spec_checks(self, *args, **kwargs):
            return [finding("Blind-Tester", "HIGH", "FAIL", "spec")]

    spec = SpecificationMetadata(function_name="f", docstring="d", specification="s")
    report = Stub().run_pipeline("def f(): pass", spec, file_path="t.py")
    assert report["agent_contributions"] == {"Fact-Checker": 1, "Blind-Tester": 1, "Security-Guard": 1}
    assert report["files_scanned"] == ["t.py"]
    assert {e["agent"] for e in report["execution_log"]} >= {"Fact-Checker", "Security-Guard", "Blind-Tester"}


# ---------- Blind-Tester isolation is preserved ----------

def test_blind_tester_cannot_receive_the_shared_context():
    params = inspect.signature(run_blind_tester).parameters
    assert not any("ctx" in name or "context" in name or "findings" in name for name in params)
    leaked = SpecificationMetadata(
        function_name="f", docstring="d", specification="s", approved_metadata={"fact_checker_findings": "x"}
    )
    with pytest.raises(ValueError):
        leaked.validate_isolation()


# ---------- AuditService end to end with stubbed agents ----------

def _stub_agents(monkeypatch, service, spec_findings=None, file_checks=None):
    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: [])
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    monkeypatch.setattr(
        service.orchestrator, "run_file_checks",
        lambda source, path, lang, *a, **k: file_checks or {"fact_checker": [], "security_guard": []},
    )
    monkeypatch.setattr(
        service.orchestrator, "run_spec_checks", lambda source, spec, path, *a, **k: list(spec_findings or [])
    )


def test_audit_service_returns_dict_and_model_with_same_content(monkeypatch):
    service = AuditService()
    _stub_agents(monkeypatch, service, spec_findings=[finding("Blind-Tester", "HIGH", "FAIL", "spec")])
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "m.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    '''Doubles.'''\n    return x * 2\n")
        model = service.audit_report(target)
        as_dict = service.audit_path(target)
    assert isinstance(model, AuditReport)
    assert as_dict["trust_score"] == model.trust_score == 80
    assert as_dict["files_scanned"] == ["m.py"]
    assert as_dict["agent_contributions"]["Blind-Tester"] == 1
    assert as_dict["findings"] == as_dict["all_findings"]
    assert as_dict["summary"].startswith("Audit completed across 1 file(s).")


def test_audit_service_rewrites_absolute_paths_before_recording(monkeypatch):
    service = AuditService()

    def checks(source, path, lang, *a, **k):
        return {"fact_checker": [finding("Fact-Checker", "HIGH", "INVALID", "bad", file_path=path)],
                "security_guard": []}

    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: [])
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    monkeypatch.setattr(service.orchestrator, "run_file_checks", checks)
    monkeypatch.setattr(service.orchestrator, "run_spec_checks", lambda *a, **k: [])
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "m.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    return x * 2\n")
        report = service.audit_path(target)
    assert report["findings"][0]["file_path"] == "m.py"


def test_audit_service_survives_a_crashing_agent_and_reports_it(monkeypatch):
    service = AuditService()
    _stub_agents(monkeypatch, service)

    def boom(*args, **kwargs):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(service.orchestrator, "run_file_checks", boom)
    monkeypatch.setattr("audit_service.run_jhooti_docstring", boom)
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "m.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    return x * 2\n")
        report = service.audit_path(target)
    assert report["agent_statuses"]["Synthesizer"] == "PARTIAL_FAILURE"
    assert report["agent_statuses"]["Jhooti-Docstring"] == "PARTIAL_FAILURE"
    assert any(f["title"] == "Audit Pipeline Failure" for f in report["findings"])
    assert report["recommendation"] != "APPROVE"


def test_unreadable_file_is_reported_and_marks_security_guard(monkeypatch):
    service = AuditService()
    _stub_agents(monkeypatch, service)
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "bad.py")
        with open(target, "wb") as f:
            f.write(b"\xff\xfe\x00 not utf-8 \x80\x81")
        report = service.audit_path(target)
    assert any(f["title"] == "File Read Error" for f in report["findings"])
    assert report["agent_statuses"]["Security-Guard"] == "PARTIAL_FAILURE"


# ---------- Markdown output (the Reporter's input) ----------

def test_markdown_lists_most_severe_findings_first_and_escapes_pipes():
    report = {
        "recommendation": "BLOCK", "trust_score": 40, "summary": "S",
        "agent_contributions": {"Fact-Checker": 2}, "agent_statuses": {"Fact-Checker": "OK"},
        "severity_breakdown": {"CRITICAL": 1, "LOW": 1},
        "findings": [
            finding("Fact-Checker", "LOW", title="minor"),
            finding("Security-Guard", "CRITICAL", title="a | b", file_path="x.py", line_number=7),
        ],
    }
    md = render_markdown(report)
    assert md.startswith("**Sceptic verdict: BLOCK** (Trust Score 40/100)")
    assert md.index("a \\| b") < md.index("minor")
    assert "x.py:7" in md


def test_markdown_truncates_and_handles_no_findings():
    many = {"recommendation": "APPROVE", "trust_score": 90,
            "findings": [finding("Fact-Checker", title=f"f{i}") for i in range(25)]}
    assert "5 more finding(s) not shown" in render_markdown(many, max_findings=20)
    assert "No findings." in render_markdown({"recommendation": "APPROVE", "trust_score": 100, "findings": []})


def test_celery_pr_comment_body_is_the_markdown_report(monkeypatch):
    import celery_app

    posted = {}
    monkeypatch.setattr(celery_app, "post_pr_summary", lambda repo, number, body: posted.update(
        repo=repo, number=number, body=body) or {"posted": True})
    report = ReportSynthesizer().synthesize([finding("Fact-Checker", "HIGH", "INVALID", "bad api")], [], [])
    celery_app._post_pr_summary({"repository": "o/r", "pr_number": 3}, report)
    assert posted["repo"] == "o/r" and posted["number"] == 3
    assert posted["body"].startswith("**Sceptic verdict: REQUEST_CHANGES**")
    assert "bad api" in posted["body"]


# ---------- An unaudited file must never be approved ----------

def test_incomplete_audit_withholds_approve_even_with_a_high_score():
    ctx = AuditContext()
    ctx.record([finding("Fact-Checker")], "Fact-Checker")
    ctx.record_failure("Synthesizer", "Audit Pipeline Failure", "boom", file_path="a.py")
    report = ReportSynthesizer().build_report(ctx)
    assert report.trust_score >= 85
    assert report.recommendation == "REQUEST_CHANGES"
    assert report.incomplete_reasons and "Audit Pipeline Failure" in report.incomplete_reasons[0]
    assert any("APPROVE withheld" in line for line in report.deductions_detail)


def test_complete_audit_can_still_approve():
    ctx = AuditContext()
    ctx.record([finding("Fact-Checker")], "Fact-Checker")
    ctx.record([finding("Leak-Hunter", "MEDIUM", "ERROR", "gitleaks missing")], "Leak-Hunter")
    report = ReportSynthesizer().build_report(ctx)
    assert report.recommendation == "APPROVE"          # a missing tool keeps its capped penalty
    assert report.incomplete_reasons == []
