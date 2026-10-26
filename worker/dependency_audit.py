"""
Purana-Saman: dependency vulnerability audit.

- Python: pip-audit over requirements.txt (python -m pip_audit).
- Node: npm audit over package-lock.json (--package-lock-only, so nothing is installed).

Both tools query online vulnerability databases. When a tool cannot run or cannot reach its database, the result
is a HIGH ERROR finding, so an unchecked dependency tree cannot be approved.
"""
import os
import sys
import json
import time
import shutil
import hashlib
import logging
import tempfile
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sceptic.dependency_audit")

AUDIT_TIMEOUT_SECONDS = 300
CACHE_TTL_SECONDS = 6 * 60 * 60
NPM_SEVERITY = {"critical": "CRITICAL", "high": "HIGH", "moderate": "MEDIUM", "low": "LOW", "info": "INFO"}


def _error_finding(scope: str, reason: str) -> Dict[str, Any]:
    return {
        "agent_name": "Purana-Saman",
        "severity": "HIGH",
        "status": "ERROR",
        "title": f"Purana-Saman could not audit {scope} dependencies",
        "description": reason,
        "file_path": None,
        "line_number": None,
        "evidence": {"scope": scope},
        "recommendation": "Make sure the audit tool can reach its vulnerability database, then re-run the audit.",
    }


def _run(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=AUDIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
    )


def _cache_path(requirements_path: str) -> Optional[str]:
    """Cache file for a requirements file's pip-audit result, keyed by its exact contents and the Python version."""
    ttl = int(os.getenv("SCEPTIC_DEP_AUDIT_CACHE_SECONDS", str(CACHE_TTL_SECONDS)) or 0)
    if ttl <= 0:
        return None
    try:
        with open(requirements_path, "rb") as f:
            digest = hashlib.sha256(f.read() + sys.version.encode()).hexdigest()
    except OSError:
        return None
    return os.path.join(tempfile.gettempdir(), "sceptic-cache", f"pip-audit-{digest}.json")


def audit_python(requirements_path: str) -> List[Dict[str, Any]]:
    """
    pip-audit resolves the whole dependency tree, which is the slowest part of an audit. A successful result is
    cached for SCEPTIC_DEP_AUDIT_CACHE_SECONDS (default 6 hours); errors are never cached.
    """
    cache_file = _cache_path(requirements_path)
    if cache_file and os.path.isfile(cache_file) and time.time() - os.path.getmtime(cache_file) < int(os.getenv("SCEPTIC_DEP_AUDIT_CACHE_SECONDS", CACHE_TTL_SECONDS)):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass  # unreadable cache entry: fall through and audit again

    findings = _audit_python_uncached(requirements_path)
    if cache_file and not any(f.get("status") == "ERROR" for f in findings):
        try:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(findings, f)
        except OSError as e:
            logger.debug(f"Could not write pip-audit cache: {e}")
    return findings


def _audit_python_uncached(requirements_path: str) -> List[Dict[str, Any]]:
    try:
        # pip-audit exits 1 when it finds vulnerabilities, so the exit code is not used to decide errors.
        proc = _run([sys.executable, "-m", "pip_audit", "-r", requirements_path, "-f", "json", "--progress-spinner", "off"])
    except (OSError, subprocess.TimeoutExpired) as e:
        return [_error_finding("Python", f"pip-audit could not run: {e}")]

    # Exit 0 means clean and exit 1 means vulnerabilities found. Anything else, or no report, is an error,
    # because an empty report must never read as "no vulnerabilities".
    if proc.returncode not in (0, 1) or not (proc.stdout or "").strip():
        return [_error_finding("Python", f"pip-audit did not return a report (exit {proc.returncode}): {(proc.stderr or '').strip()[-300:]}")]
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [_error_finding("Python", f"pip-audit output was not JSON: {(proc.stderr or '').strip()[-300:]}")]

    findings = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fixes = ", ".join(vuln.get("fix_versions") or []) or "no fixed version listed"
            findings.append({
                "agent_name": "Purana-Saman",
                "severity": "HIGH",
                "status": "OPEN",
                "title": f"[PIP-AUDIT] {dep.get('name')} {dep.get('version')} has {vuln.get('id')}",
                "description": (vuln.get("description") or "Known vulnerability.")[:500],
                "file_path": os.path.basename(requirements_path),
                "line_number": None,
                "evidence": {"package": dep.get("name"), "version": dep.get("version"), "id": vuln.get("id"), "fix_versions": fixes},
                "recommendation": f"Upgrade {dep.get('name')} to a fixed version ({fixes}).",
            })
    return findings


def audit_node(project_dir: str) -> List[Dict[str, Any]]:
    npm = shutil.which("npm")
    if npm is None:
        return [_error_finding("Node", "npm is not installed on this host.")]
    try:
        proc = _run([npm, "audit", "--json", "--package-lock-only"], cwd=project_dir)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [_error_finding("Node", f"npm audit could not run: {e}")]

    if proc.returncode not in (0, 1) or not (proc.stdout or "").strip():
        return [_error_finding("Node", f"npm audit did not return a report (exit {proc.returncode}): {(proc.stderr or '').strip()[-300:]}")]
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [_error_finding("Node", f"npm audit output was not JSON: {(proc.stderr or '').strip()[-300:]}")]

    if "error" in data:
        summary = data["error"].get("summary") or data["error"].get("code") or "unknown error"
        return [_error_finding("Node", f"npm audit failed: {str(summary)[:300]}")]

    findings = []
    for name, info in (data.get("vulnerabilities") or {}).items():
        advisories = [v for v in info.get("via", []) if isinstance(v, dict)]
        titles = "; ".join(a.get("title", "") for a in advisories if a.get("title")) or "known vulnerability"
        fix = info.get("fixAvailable")
        fix_text = "a fix is available" if fix else "no automatic fix"
        findings.append({
            "agent_name": "Purana-Saman",
            "severity": NPM_SEVERITY.get((info.get("severity") or "").lower(), "MEDIUM"),
            "status": "OPEN",
            "title": f"[NPM-AUDIT] {name} ({info.get('range', '*')}) is vulnerable",
            "description": titles[:500],
            "file_path": "package-lock.json",
            "line_number": None,
            "evidence": {"package": name, "range": info.get("range"), "direct": info.get("isDirect"), "fix": fix},
            "recommendation": f"Upgrade or replace {name}; {fix_text}.",
        })
    return findings


OSV_SEVERITY_BY_CVSS = [(9.0, "CRITICAL"), (7.0, "HIGH"), (4.0, "MEDIUM"), (0.1, "LOW")]


def _osv_severity(vulnerability: Dict[str, Any], group_scores: Dict[str, Any]) -> str:
    label = str((vulnerability.get("database_specific") or {}).get("severity") or "").upper()
    if label in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        return label
    try:
        score = float(group_scores.get(vulnerability.get("id"), "") or "")
    except ValueError:
        return "HIGH"  # unknown severity is treated as HIGH, never as LOW
    for threshold, name in OSV_SEVERITY_BY_CVSS:
        if score >= threshold:
            return name
    return "LOW"


def audit_maven(project_dir: str) -> List[Dict[str, Any]]:
    """
    Maven and Gradle dependencies through osv-scanner (open source, Apache 2.0), which queries the OSV database.
    Reads pom.xml directly and gradle.lockfile when present.
    """
    # OSV_SCANNER_PATH lets deployments pin the binary; otherwise it is looked up on PATH.
    binary = os.getenv("OSV_SCANNER_PATH", "").strip() or shutil.which("osv-scanner")
    if not binary:
        return [_error_finding("Maven", "osv-scanner is not installed on this host.")]

    with tempfile.TemporaryDirectory() as tmp:
        out_file = os.path.join(tmp, "osv.json")
        try:
            proc = _run([binary, "scan", "source", "-f", "json", "--output-file", out_file, project_dir])
        except (OSError, subprocess.TimeoutExpired) as e:
            return [_error_finding("Maven", f"osv-scanner could not run: {e}")]
        # osv-scanner exits 0 when clean, 1 when vulnerabilities are found, and 128 when no packages are found.
        if proc.returncode == 128 and not os.path.exists(out_file):
            return []
        if proc.returncode not in (0, 1) or not os.path.exists(out_file):
            return [_error_finding("Maven", f"osv-scanner did not return a report (exit {proc.returncode}): {(proc.stderr or '').strip()[-300:]}")]
        with open(out_file, encoding="utf-8") as f:
            content = f.read().strip()
    try:
        data = json.loads(content) if content else {}
    except json.JSONDecodeError:
        return [_error_finding("Maven", "osv-scanner output was not JSON.")]

    findings: List[Dict[str, Any]] = []
    for result in data.get("results", []):
        source_path = (result.get("source") or {}).get("path", "")
        for package_entry in result.get("packages", []):
            package = package_entry.get("package") or {}
            name, version = package.get("name", "?"), package.get("version", "?")
            group_scores = {}
            for group in package_entry.get("groups", []):
                for alias in group.get("ids", []):
                    group_scores[alias] = group.get("max_severity", "")
            for vuln in package_entry.get("vulnerabilities", []):
                fixed = vuln.get("affected") or []
                findings.append({
                    "agent_name": "Purana-Saman",
                    "severity": _osv_severity(vuln, group_scores),
                    "status": "OPEN",
                    "title": f"[OSV] {name} {version} has {vuln.get('id')}",
                    "description": (vuln.get("summary") or "Known vulnerability in a Maven or Gradle dependency.")[:500],
                    "file_path": os.path.basename(source_path) or "pom.xml",
                    "line_number": None,
                    "evidence": {"package": name, "version": version, "ecosystem": package.get("ecosystem"),
                                 "id": vuln.get("id"), "aliases": vuln.get("aliases", [])[:5], "affected_ranges": len(fixed)},
                    "recommendation": f"Upgrade {name} to a version without {vuln.get('id')}.",
                })
    return findings


def audit_dependencies(path: str) -> List[Dict[str, Any]]:
    """Audits the dependency manifests found in a directory (or next to a file). Returns no findings if none exist."""
    root = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    findings: List[Dict[str, Any]] = []
    requirements = os.path.join(root, "requirements.txt")
    if os.path.isfile(requirements):
        findings.extend(audit_python(requirements))
    if os.path.isfile(os.path.join(root, "package.json")) and os.path.isfile(os.path.join(root, "package-lock.json")):
        findings.extend(audit_node(root))
    if os.path.isfile(os.path.join(root, "pom.xml")) or os.path.isfile(os.path.join(root, "gradle.lockfile")):
        findings.extend(audit_maven(root))
    return findings
