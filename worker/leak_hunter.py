"""
Leak-Hunter: secret scanning with Gitleaks.

Runs `gitleaks dir` over a directory. Secret values are never stored or returned: each finding keeps only
the first four characters followed by a redaction marker. A missing or failing scanner is reported as a HIGH
ERROR finding, so an unscanned tree cannot be approved.
"""
import os
import json
import shutil
import logging
import tempfile
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger("sceptic.leak_hunter")

GITLEAKS_TIMEOUT_SECONDS = 300


def redact(value: str) -> str:
    if not value:
        return ""
    return f"{value[:4]}...[redacted]"


def _error_finding(reason: str) -> Dict[str, Any]:
    return {
        "agent_name": "Leak-Hunter",
        "severity": "HIGH",
        "status": "ERROR",
        "title": "Leak-Hunter could not scan for secrets",
        "description": reason,
        "file_path": None,
        "line_number": None,
        "evidence": {"scanner": "gitleaks"},
        "recommendation": "Install gitleaks (https://github.com/gitleaks/gitleaks) and re-run the audit.",
    }


def _finding_from_leak(item: Dict[str, Any], root: str) -> Dict[str, Any]:
    file_path = item.get("File") or ""
    try:
        # os.path.join keeps absolute paths as they are, so this works for relative and absolute File values.
        file_path = os.path.relpath(os.path.join(root, file_path), root)
    except ValueError:
        pass
    rule = item.get("RuleID") or "secret"
    return {
        "agent_name": "Leak-Hunter",
        "severity": "HIGH",
        "status": "OPEN",
        "title": f"[GITLEAKS] {rule} in {file_path}",
        "description": f"Possible {item.get('Description') or rule} committed to the source tree.",
        "file_path": file_path,
        "line_number": item.get("StartLine"),
        "evidence": {"rule": rule, "match": redact(item.get("Secret") or item.get("Match") or "")},
        "recommendation": "Rotate the credential and move it to a secret store. Remove it from git history.",
    }


def scan_secrets(path: str) -> List[Dict[str, Any]]:
    """Scans a file or directory for secrets and returns Sceptic findings."""
    root = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    binary = shutil.which("gitleaks")
    if binary is None:
        return [_error_finding("gitleaks is not installed on this host.")]

    with tempfile.TemporaryDirectory() as tmp:
        report_path = os.path.join(tmp, "gitleaks.json")
        target = os.path.abspath(path)
        cmd = [
            binary, "dir", target,
            "--report-format", "json",
            "--report-path", report_path,
            "--no-banner",
            "--exit-code", "0",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=GITLEAKS_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired:
            return [_error_finding(f"gitleaks timed out after {GITLEAKS_TIMEOUT_SECONDS} seconds.")]
        except OSError as e:
            return [_error_finding(f"gitleaks could not start: {e}")]

        if proc.returncode != 0:
            return [_error_finding(f"gitleaks exited with code {proc.returncode}: {(proc.stderr or '').strip()[-300:]}")]

        leaks: List[Dict[str, Any]] = []
        if os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as f:
                content = f.read().strip()
            leaks = json.loads(content) if content else []

    return [_finding_from_leak(item, root) for item in leaks]
