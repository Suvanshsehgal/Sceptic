"""
Shared audit state and the structured audit report (Pydantic).

AuditContext is the single state object for one audit. The service (or the orchestrator pipeline) writes every
agent's output into it as the agent finishes. The Synthesizer reads the findings from it to build the AuditReport,
and the Reporter reads the AuditReport to publish Markdown. The context also keeps an execution log, so a run can
be inspected afterwards.

Blind-Tester never reads from the context. Its isolation rule (it must not see the implementation or any other
agent's findings) is enforced by SpecificationMetadata.validate_isolation(), and this module does not weaken it.

Findings stay plain dicts: agents attach extra keys (for example `contextual_analysis` or `called_api`) and the
CLI, Celery task, API and tests all read them as dicts. validate_finding() checks the common fields and reports
problems as warnings in the execution log. It never changes or drops a finding.
"""
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

VERIFICATION_AGENTS = (
    "Fact-Checker", "Blind-Tester", "Security-Guard", "Leak-Hunter", "Purana-Saman", "Jhooti-Docstring",
)
STATUS_OK = "OK"
STATUS_PARTIAL_FAILURE = "PARTIAL_FAILURE"

Recommendation = Literal["APPROVE", "REQUEST_CHANGES", "BLOCK"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate_finding(finding: Any) -> List[str]:
    """Returns a list of problems with a finding's common fields. An empty list means it is well formed."""
    if not isinstance(finding, dict):
        return [f"finding is {type(finding).__name__}, expected an object"]
    problems: List[str] = []
    if not isinstance(finding.get("agent_name"), str) or not finding.get("agent_name"):
        problems.append("missing agent_name")
    severity = finding.get("severity")
    if not isinstance(severity, str) or severity.upper() not in _SEVERITY_RANK:
        problems.append(f"unknown severity {severity!r}")
    if not isinstance(finding.get("title"), str) or not finding.get("title"):
        problems.append("missing title")
    line = finding.get("line_number")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
        problems.append(f"line_number is {type(line).__name__}, expected int")
    return problems


class ContextEvent(BaseModel):
    """One entry of the execution log."""
    timestamp: datetime = Field(default_factory=_now)
    agent: str
    event: str
    detail: str = ""
    count: Optional[int] = None


class AuditContext(BaseModel):
    """State shared by all agents during one audit."""
    audit_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: Optional[str] = None
    target_path: str = ""
    files_scanned: List[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    agent_statuses: Dict[str, str] = Field(
        default_factory=lambda: {name: STATUS_OK for name in (*VERIFICATION_AGENTS, "Synthesizer")}
    )
    agent_outputs: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    all_findings: List[Dict[str, Any]] = Field(default_factory=list)
    events: List[ContextEvent] = Field(default_factory=list)
    # Reasons the audit could not cover all of the code (a crashed stage, an unreadable file).
    # While this is not empty the verdict can never be APPROVE.
    incomplete_reasons: List[str] = Field(default_factory=list)

    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def add_event(self, agent: str, event: str, detail: str = "", count: Optional[int] = None) -> None:
        with self._lock:
            self.events.append(ContextEvent(agent=agent, event=event, detail=detail, count=count))

    def record(self, findings: List[Dict[str, Any]], source_agent: Optional[str] = None,
               file_path: Optional[str] = None) -> None:
        """
        Stores an agent's findings, in call order. An ERROR finding marks its agent PARTIAL_FAILURE.
        The finding's own agent_name decides the owner; source_agent is the fallback.
        """
        batch = list(findings or [])
        with self._lock:
            for finding in batch:
                problems = validate_finding(finding)
                if not isinstance(finding, dict):
                    self.events.append(ContextEvent(
                        agent=source_agent or "unknown", event="schema_warning", detail="; ".join(problems)))
                    if source_agent in self.agent_statuses:
                        self.agent_statuses[source_agent] = STATUS_PARTIAL_FAILURE
                    continue
                owner = finding.get("agent_name")
                if owner not in self.agent_statuses:
                    owner = source_agent
                self.all_findings.append(finding)
                if owner:
                    self.agent_outputs.setdefault(owner, []).append(finding)
                if str(finding.get("status") or "").upper() == "ERROR" and owner in self.agent_statuses:
                    self.agent_statuses[owner] = STATUS_PARTIAL_FAILURE
                if problems:
                    self.events.append(ContextEvent(
                        agent=owner or "unknown", event="schema_warning",
                        detail=f"{finding.get('title') or '(no title)'}: " + "; ".join(problems)))
            if source_agent:
                self.events.append(ContextEvent(
                    agent=source_agent, event="completed", detail=file_path or "", count=len(batch)))

    def record_failure(self, agent: str, title: str, description: str, file_path: Optional[str] = None,
                       severity: str = "HIGH") -> Dict[str, Any]:
        """
        Records a failure that left code unaudited: an ERROR finding, the agent marked PARTIAL_FAILURE,
        and an incomplete-audit reason that withholds APPROVE.
        """
        finding = {
            "agent_name": agent,
            "severity": severity,
            "status": "ERROR",
            "title": title,
            "description": description,
            "file_path": file_path,
        }
        self.record([finding])
        with self._lock:
            self.incomplete_reasons.append(f"{title}: {description}"[:300])
        self.add_event(agent, "failed", detail=description[:200])
        return finding

    def mark_partial_failure(self, agent: str, detail: str = "") -> None:
        with self._lock:
            if agent in self.agent_statuses:
                self.agent_statuses[agent] = STATUS_PARTIAL_FAILURE
            self.events.append(ContextEvent(agent=agent, event="partial_failure", detail=detail[:200]))

    def findings_by(self, agent: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.agent_outputs.get(agent, []))


class AuditReport(BaseModel):
    """The structured result of an audit. to_dict() is what the CLI, Celery task and API consume."""
    audit_id: str = ""
    trace_id: Optional[str] = None
    target_path: str = ""
    files_scanned: List[str] = Field(default_factory=list)
    trust_score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    summary: str = ""
    severity_breakdown: Dict[str, int] = Field(default_factory=dict)
    agent_contributions: Dict[str, int] = Field(default_factory=dict)
    agent_statuses: Dict[str, str] = Field(default_factory=dict)
    deductions_detail: List[str] = Field(default_factory=list)
    incomplete_reasons: List[str] = Field(default_factory=list)
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    total_findings: int = 0
    duration_seconds: Optional[float] = None
    generated_at: datetime = Field(default_factory=_now)
    execution_log: List[ContextEvent] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict. `all_findings` is kept as an alias of `findings` for the Celery task."""
        data = self.model_dump(mode="json")
        data["all_findings"] = data["findings"]
        return data

    def to_markdown(self, max_findings: int = 20) -> str:
        return render_markdown(self.to_dict(), max_findings=max_findings)


def _cell(value: Any, limit: int = 90) -> str:
    text = " ".join(str(value if value is not None else "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(report: Dict[str, Any], max_findings: int = 20) -> str:
    """Renders an audit report dict as Markdown: verdict, per-agent table and the most severe findings."""
    findings = list(report.get("findings") or report.get("all_findings") or [])
    lines = [
        f"**Sceptic verdict: {report.get('recommendation')}** (Trust Score {report.get('trust_score')}/100)",
        "",
    ]
    if report.get("summary"):
        lines += [str(report["summary"]), ""]

    contributions = report.get("agent_contributions") or {}
    statuses = report.get("agent_statuses") or {}
    if contributions:
        lines += ["| Agent | Status | Findings |", "| --- | --- | --- |"]
        for agent, count in contributions.items():
            lines.append(f"| {_cell(agent)} | {_cell(statuses.get(agent, ''))} | {count} |")
        lines.append("")

    breakdown = report.get("severity_breakdown") or {}
    if breakdown:
        parts = [f"{name} {count}" for name, count in breakdown.items() if count]
        lines += ["Severity: " + (", ".join(parts) if parts else "none"), ""]

    if findings:
        def rank(finding: Dict[str, Any]) -> int:
            return _SEVERITY_RANK.get(str(finding.get("severity") or "INFO").upper(), len(SEVERITIES))

        shown = sorted(findings, key=rank)[:max_findings]
        lines += ["| Severity | Agent | Finding | Location |", "| --- | --- | --- | --- |"]
        for finding in shown:
            where = finding.get("file_path") or ""
            if finding.get("line_number") is not None:
                where = f"{where}:{finding['line_number']}"
            lines.append(
                f"| {_cell(finding.get('severity'))} | {_cell(finding.get('agent_name'))} | "
                f"{_cell(finding.get('title'))} | {_cell(where, 60)} |"
            )
        if len(findings) > len(shown):
            lines += ["", f"_{len(findings) - len(shown)} more finding(s) not shown._"]
    else:
        lines.append("No findings.")
    return "\n".join(lines).rstrip() + "\n"
