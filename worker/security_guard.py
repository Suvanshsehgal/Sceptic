import os
import sys
import json
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

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
            "contextual_analysis": self.contextual_analysis
        }


class BanditScanner:
    """
    Executes Bandit static analysis on Python code and normalizes findings.
    """
    def scan_code(self, source_code: str, file_name: str = "target.py") -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            file_path = os.path.join(temp_dir, file_name)
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
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="INFO",
                    title="[BANDIT] Scanner Timeout",
                    description="Bandit security analysis timed out.",
                    file_path=file_name,
                    scanner="bandit",
                    rule_id="TIMEOUT"
                ))
            except Exception as e:
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="INFO",
                    title="[BANDIT] Scanner Execution Error",
                    description=f"Error running Bandit: {str(e)}",
                    file_path=file_name,
                    scanner="bandit",
                    rule_id="ERROR"
                ))

        return findings


class SemgrepScanner:
    """
    Executes Semgrep static analysis on Python code and normalizes findings.
    """
    def __init__(self, rules_path: Optional[str] = None):
        if rules_path:
            self.rules_path = rules_path
        else:
            default_path = os.path.join(os.path.dirname(__file__), "semgrep_rules.yaml")
            self.rules_path = default_path if os.path.exists(default_path) else "auto"

    def scan_code(self, source_code: str, file_name: str = "target.py") -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            file_path = os.path.join(temp_dir, file_name)
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

                cmd = [semgrep_bin, "scan", "--config", self.rules_path, "--json", "--no-git-ignore", file_path]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=20
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
                    severity="INFO",
                    title="[SEMGREP] Scanner Timeout",
                    description="Semgrep security analysis timed out.",
                    file_path=file_name,
                    scanner="semgrep",
                    rule_id="TIMEOUT"
                ))
            except Exception as e:
                # Handle scanner failure gracefully without crashing
                findings.append(SecurityFinding(
                    agent_name="Security-Guard",
                    severity="INFO",
                    title="[SEMGREP] Scanner Execution Error",
                    description=f"Error running Semgrep: {str(e)}",
                    file_path=file_name,
                    scanner="semgrep",
                    rule_id="ERROR"
                ))

        return findings


class GroqContextualAnalyzer:
    """
    Provides contextual analysis over deterministic scanner findings using Groq.
    Does NOT replace scanner evidence; provides true-positive validation and exploit assessment.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
        self.model = model

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

        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)

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
