import os
import sys
import json
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from llm_client import make_groq_client, llm_blocked, note_llm_error

@dataclass
class SecurityFinding:
    agent_name: str = "Security-Guard"
    severity: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    title: str = ""
    description: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    scanner: str = "unknown"  # "semgrep" or "bandit"
    rule_id: str = "unknown"
    contextual_analysis: Optional[str] = None
    status: Optional[str] = None  # "ERROR" when the scanner could not finish; reported, but not counted as a defect

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "evidence": self.evidence,
            "scanner": self.scanner,
            "rule_id": self.rule_id,
            "contextual_analysis": self.contextual_analysis,
            "status": self.status
        }


class BanditScanner:
    """
    Executes Bandit static analysis on Python code and normalizes findings.
    """
    def scan_code(self, source_code: str, file_name: str = "target.py") -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            # file_name may carry a directory (e.g. "backend/app.py"); the temp copy only needs its base name.
            file_path = os.path.join(temp_dir, os.path.basename(file_name))
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(source_code)

            try:
                import shutil
                bandit_bin = shutil.which("bandit")
                if not bandit_bin:
                    # Check in virtual environment Scripts folder
                    scripts_dir = os.path.dirname(sys.executable)
                    candidate = os.path.join(scripts_dir, "bandit.exe" if os.name == "nt" else "bandit")
                    if os.path.exists(candidate):
                        bandit_bin = candidate
                    else:
                        bandit_bin = "bandit"

                cmd = [bandit_bin, "-f", "json", "-q", file_path]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=30
                )
                # Bandit exits with 0 (no issues) or 1 (issues found). Both produce valid JSON output.
                output = proc.stdout.strip()
                if not output:
                    return findings

                data = json.loads(output)
                results = data.get("results", [])

                for item in results:
                    raw_severity = item.get("issue_severity", "MEDIUM").upper()
                    # Normalize severity
                    severity = "HIGH" if raw_severity == "HIGH" else ("MEDIUM" if raw_severity == "MEDIUM" else "LOW")
                    test_id = item.get("test_id", "B000")
                    test_name = item.get("test_name", "bandit_issue")
                    line_num = item.get("line_number")
                    issue_text = item.get("issue_text", "")
                    code_snippet = item.get("code", "").strip()

                    finding = SecurityFinding(
                        agent_name="Security-Guard",
                        severity=severity,
                        title=f"[BANDIT] {test_id} ({test_name}): {issue_text}",
                        description=issue_text,
                        file_path=file_name,
                        line_number=line_num,
                        evidence=f"Line {line_num}: {code_snippet}",
                        scanner="bandit",
                        rule_id=test_id
                    )
                    findings.append(finding)
            except subprocess.TimeoutExpired:
                # HIGH, not INFO: a scanner that did not finish must not leave the code looking clean.
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="HIGH",
                    status="ERROR",
                    title="[BANDIT] Scanner did not complete (timeout)",
                    description="Bandit security analysis timed out, so the file was not fully scanned.",
                    file_path=file_name,
                    scanner="bandit",
                    rule_id="TIMEOUT"
                ))
            except Exception as e:
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="HIGH",
                    status="ERROR",
                    title="[BANDIT] Scanner did not run",
                    description=f"Error running Bandit: {str(e)}",
                    file_path=file_name,
                    scanner="bandit",
                    rule_id="ERROR"
                ))

        return findings


WORKER_DIR_FOR_RULES = os.path.dirname(os.path.abspath(__file__))
# Semgrep can be slow on machines with restricted networks, so the limit is configurable.
SEMGREP_TIMEOUT_SECONDS = int(os.getenv("SEMGREP_TIMEOUT_SECONDS", "300"))


def _semgrep_env() -> Dict[str, str]:
    """Turns off Semgrep's version check and metrics upload, so scans run offline and deterministically."""
    env = dict(os.environ)
    env["SEMGREP_SEND_METRICS"] = "off"
    env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
    return env
SEMGREP_PACKS = {
    ".py": "semgrep_rules.yaml",
    ".js": "semgrep_rules_js.yaml",
    ".jsx": "semgrep_rules_js.yaml",
    ".mjs": "semgrep_rules_js.yaml",
    ".cjs": "semgrep_rules_js.yaml",
    ".ts": "semgrep_rules_js.yaml",
    ".tsx": "semgrep_rules_js.yaml",
    ".java": "semgrep_rules_java.yaml",
}


def rules_for_file(file_name: str) -> str:
    """Semgrep rule pack for a file's language. Files of other types fall back to the Python pack."""
    pack = SEMGREP_PACKS.get(os.path.splitext(file_name or "")[1].lower(), "semgrep_rules.yaml")
    path = os.path.join(WORKER_DIR_FOR_RULES, pack)
    return path if os.path.exists(path) else "auto"


class SemgrepScanner:
    """
    Executes Semgrep static analysis and normalizes findings. The rule pack depends on the file's language.
    """
    def __init__(self, rules_path: Optional[str] = None):
        # An explicit rules_path overrides the per-language packs chosen by rules_for_file().
        self.rules_path = rules_path

    def scan_code(self, source_code: str, file_name: str = "target.py") -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            file_path = os.path.join(temp_dir, os.path.basename(file_name))
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(source_code)

            try:
                import shutil
                semgrep_bin = shutil.which("semgrep")
                if not semgrep_bin:
                    scripts_dir = os.path.dirname(sys.executable)
                    candidate = os.path.join(scripts_dir, "semgrep.exe" if os.name == "nt" else "semgrep")
                    if os.path.exists(candidate):
                        semgrep_bin = candidate
                    else:
                        semgrep_bin = "semgrep"

                config = self.rules_path or rules_for_file(file_name)
                cmd = [semgrep_bin, "scan", "--config", config, "--json", "--no-git-ignore", file_path]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=SEMGREP_TIMEOUT_SECONDS,
                    env=_semgrep_env(),
                )
                output = proc.stdout.strip()

                if not output:
                    return findings

                # Locate JSON payload in stdout (Semgrep on Windows prints banners before JSON)
                json_start = output.find('{"')
                if json_start == -1:
                    json_start = output.find('{')

                if json_start != -1:
                    json_str = output[json_start:]
                    data = json.loads(json_str)
                    results = data.get("results", [])

                    for item in results:
                        check_id = item.get("check_id", "semgrep_rule")
                        start = item.get("start", {})
                        line_num = start.get("line")
                        extra = item.get("extra", {})
                        message = extra.get("message", "")
                        raw_severity = extra.get("severity", "WARNING").upper()

                        if raw_severity == "ERROR":
                            severity = "HIGH"
                        elif raw_severity == "WARNING":
                            severity = "MEDIUM"
                        else:
                            severity = "LOW"

                        lines_snippet = extra.get("lines", "").strip()

                        finding = SecurityFinding(
                            agent_name="Security-Guard",
                            severity=severity,
                            title=f"[SEMGREP] {check_id}: {message[:80]}",
                            description=message,
                            file_path=file_name,
                            line_number=line_num,
                            evidence=f"Line {line_num}: {lines_snippet}",
                            scanner="semgrep",
                            rule_id=check_id
                        )
                        findings.append(finding)
            except subprocess.TimeoutExpired:
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="HIGH",
                    status="ERROR",
                    title="[SEMGREP] Scanner did not complete (timeout)",
                    description="Semgrep security analysis timed out, so the file was not fully scanned.",
                    file_path=file_name,
                    scanner="semgrep",
                    rule_id="TIMEOUT"
                ))
            except Exception as e:
                # Handle scanner failure gracefully without crashing
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="HIGH",
                    status="ERROR",
                    title="[SEMGREP] Scanner did not run",
                    description=f"Error running Semgrep: {str(e)}",
                    file_path=file_name,
                    scanner="semgrep",
                    rule_id="ERROR"
                ))

        return findings


_UNSET = object()

class GroqContextualAnalyzer:
    """
    Provides contextual analysis over deterministic scanner findings using Groq.
    Does NOT replace scanner evidence; provides true-positive validation and exploit assessment.
    """
    def __init__(self, api_key: Any = _UNSET, model: Optional[str] = None):
        self.api_key = os.getenv("GROQ_API_KEY") if api_key is _UNSET else api_key
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def analyze_findings(
        self,
        source_code: str,
        findings: List[SecurityFinding]
    ) -> List[SecurityFinding]:
        if not findings:
            return findings

        if not self.api_key:
            for f in findings:
                f.contextual_analysis = "Deterministic finding verified. Contextual LLM analysis skipped (no GROQ_API_KEY)."
            return findings
        if llm_blocked():
            for f in findings:
                f.contextual_analysis = "Deterministic finding preserved. Contextual LLM analysis skipped: daily Groq quota reached."
            return findings

        try:
            client = make_groq_client(self.api_key)

            findings_summary = "\n".join([
                f"- Scanner: {f.scanner}, Rule: {f.rule_id}, Severity: {f.severity}, Line: {f.line_number}\n"
                f"  Evidence: {f.evidence}\n"
                f"  Description: {f.description}"
                for f in findings
            ])

            prompt = f"""You are a Principal Application Security Engineer reviewing static analysis findings.
The following code was scanned by deterministic security tools (Semgrep, Bandit):

```python
{source_code}
```

Scanner Findings:
{findings_summary}

Task:
For each finding, provide concise contextual analysis:
1. True Positive or False Positive in this code context?
2. Potential impact or exploit scenario.
3. Recommended remediation.

Provide an analysis for each finding clearly labeled by Rule/Scanner.
"""
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a concise, precise AppSec expert providing contextual validation on static analysis results."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )

            llm_text = response.choices[0].message.content or ""
            for f in findings:
                f.contextual_analysis = llm_text
        except Exception as e:
            # Graceful fallback: Never discard scanner evidence on LLM failure
            note_llm_error(e)
            for f in findings:
                f.contextual_analysis = f"Deterministic finding preserved. Contextual LLM analysis failed: {str(e)}"

        return findings


def run_security_scan(
    source_code: str,
    file_path: str = "target.py",
    run_llm_analysis: bool = True
) -> List[Dict[str, Any]]:
    """
    Orchestrates the hybrid deterministic + LLM security verification pipeline:
    Target Code -> Semgrep & Bandit -> Normalized Findings -> Groq Contextual Analysis -> Final Results
    """
    is_python = file_path.endswith(".py")
    combined_findings: List[SecurityFinding] = []

    if is_python:
        bandit_scanner = BanditScanner()
        bandit_findings = bandit_scanner.scan_code(source_code, file_name=file_path)
        combined_findings.extend(bandit_findings)

    semgrep_scanner = SemgrepScanner()
    semgrep_findings = semgrep_scanner.scan_code(source_code, file_name=file_path)
    combined_findings.extend(semgrep_findings)

    if not combined_findings:
        # Code passed static security analysis
        scanner_names = "Bandit or Semgrep" if is_python else "Semgrep"
        safe_finding = SecurityFinding(
            agent_name="Security-Guard",
            severity="INFO",
            title="Clean Security Scan",
            description=f"No security vulnerabilities detected by {scanner_names} static analysis.",
            file_path=file_path,
            evidence="Zero security findings from static scanners.",
            contextual_analysis="Target code passed deterministic security checks."
        )
        return [safe_finding.to_dict()]

    if run_llm_analysis:
        analyzer = GroqContextualAnalyzer()
        combined_findings = analyzer.analyze_findings(source_code, combined_findings)

    return [f.to_dict() for f in combined_findings]
