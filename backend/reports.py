"""
Phase 2: Markdown incident reports and safe Markdown sources for the LLM.

- render_incident_report(): turns a Watchdog probe result into a Markdown report.
- write_incident_report(): saves a report into reports/.
- read_source(): reads a .md file, but only from the allowlisted folders (docs/runbooks/ and reports/).
  Names are validated, and resolved paths must stay inside those folders, so traversal such as
  '../secrets.md' or absolute paths are rejected.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
RUNBOOKS_DIR = REPO_ROOT / "docs" / "runbooks"
ALLOWED_SOURCE_DIRS = (RUNBOOKS_DIR, REPORTS_DIR)

MAX_SOURCE_BYTES = 64 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,80}\.md$")


class SourceError(ValueError):
    """Raised when a requested Markdown source is not allowed or cannot be read."""


def render_incident_report(
    *,
    deployment_label: str,
    probe: Dict[str, Any],
    summary: str,
    llm_used: bool,
    generated_at: Optional[datetime] = None,
) -> str:
    """Render a Watchdog probe result and its summary as a Markdown incident report."""
    when = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")

    def fmt(value: Any, pct: bool = False, seconds: bool = False) -> str:
        if value is None:
            return "not available"
        if pct:
            return f"{value:.2%}"
        if seconds:
            return f"{value:.3f}s"
        return str(value)

    lines = [
        f"# Incident report: {deployment_label}",
        "",
        f"- Generated: {when}",
        f"- Verdict: **{probe.get('verdict', 'UNKNOWN')}**",
        f"- Health: {probe.get('health_status', 'unknown')}",
        f"- Summary written by: {'Groq LLM (ADK agent)' if llm_used else 'deterministic fallback'}",
        "",
        "## Runtime metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Requests | {fmt(probe.get('request_count'))} |",
        f"| 5xx errors | {fmt(probe.get('error_count'))} |",
        f"| Error rate | {fmt(probe.get('error_rate'), pct=True)} |",
        f"| Average latency | {fmt(probe.get('latency_avg_seconds'), seconds=True)} |",
        f"| p95 latency | {fmt(probe.get('latency_p95_seconds'), seconds=True)} |",
        "",
        "## Findings",
        "",
    ]
    findings = probe.get("findings") or []
    if not findings:
        lines.append("No findings.")
    for finding in findings:
        lines.append(
            f"- **{finding.get('finding_type')}** ({finding.get('severity')}): {finding.get('description')}"
        )
    lines += ["", "## Summary", "", summary.strip(), ""]
    return "\n".join(lines)


def write_incident_report(name: str, markdown: str, directory: Path = REPORTS_DIR) -> Path:
    """Save a report under reports/ (or another directory, for tests) and return its path."""
    if not _SAFE_NAME.match(name):
        raise SourceError(f"invalid report name: {name!r}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(markdown, encoding="utf-8")
    return path


def resolve_source(name: str, directories: Sequence[Path] = ALLOWED_SOURCE_DIRS) -> Path:
    """Validate a Markdown source name and return its path. Raises SourceError if it is not allowed."""
    if not isinstance(name, str) or not _SAFE_NAME.match(name):
        raise SourceError("source name must be a plain .md file name such as 'high_error_rate.md'")
    for directory in directories:
        candidate = (directory / name).resolve()
        if candidate.parent == directory.resolve() and candidate.is_file():
            return candidate
    raise SourceError(f"source not found in allowed folders: {name}")


def read_source(name: str, directories: Sequence[Path] = ALLOWED_SOURCE_DIRS) -> str:
    """Read an allowed Markdown source. Oversized files are rejected rather than truncated silently."""
    path = resolve_source(name, directories)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise SourceError(f"source too large (over {MAX_SOURCE_BYTES} bytes): {name}")
    return path.read_text(encoding="utf-8")


def read_markdown_source(name: str) -> Dict[str, Any]:
    """
    ADK tool: read a runbook or incident report by file name.
    Returns {"name", "content"} on success, or {"error"} when the source is not allowed or missing.
    """
    try:
        return {"name": name, "content": read_source(name)}
    except SourceError as exc:
        return {"error": str(exc)}
