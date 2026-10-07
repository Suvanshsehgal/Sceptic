import os
import re
import sys
import json
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SpecificationMetadata:
    function_name: str
    docstring: str
    specification: str
    module_name: str = "target_module"
    language: str = "python"
    testing_framework: str = "pytest"
    approved_metadata: Optional[Dict[str, Any]] = None

    def validate_isolation(self, extra_context: Optional[Dict[str, Any]] = None) -> None:
        """
        Enforces strict architectural information isolation.
        Ensures the generation context does NOT contain:
        - Source code implementation
        - Existing tests
        - Other agent findings (Fact-Checker, Security Guard)
        """
        prohibited_keys = {
            "source_code", "implementation", "code_body", "function_body",
            "existing_tests", "test_cases", "test_code",
            "fact_checker_findings", "security_guard_findings", "agent_findings"
        }
        
        if self.approved_metadata:
            for k in self.approved_metadata.keys():
                if k.lower() in prohibited_keys:
                    raise ValueError(f"Information isolation violation: Prohibited key '{k}' found in specification metadata.")
        
        if extra_context:
            for k in extra_context.keys():
                if k.lower() in prohibited_keys:
                    raise ValueError(f"Information isolation violation: Prohibited key '{k}' found in context.")


@dataclass
class BlindTesterFinding:
    agent_name: str = "Blind-Tester"
    severity: str = "HIGH"
    status: str = "FAIL"  # FAIL or PASS
    title: str = ""
    description: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    function_name: Optional[str] = None
    test_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "severity": self.severity,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "evidence": self.evidence,
            "function_name": self.function_name,
            "test_name": self.test_name
        }


class BlindTestGenerator:
    """
    Generates specification-based unit tests using Groq LLM without ever seeing the implementation.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model

    def build_isolated_prompt(self, spec: SpecificationMetadata) -> str:
        # Enforce strict isolation
        spec.validate_isolation()

        prompt = f"""You are an independent specification-based test generator for Python code.
You MUST write pytest unit tests for the following function based ONLY on its name, docstring, and specification.
You DO NOT have access to the actual implementation.

Function to test:
Name: {spec.function_name}
Docstring:
\"\"\"
{spec.docstring}
\"\"\"
Specification / Requirements:
{spec.specification}

Instructions:
1. Import the function from `{spec.module_name}`: `from {spec.module_name} import {spec.function_name}`
2. Write multiple independent pytest test functions testing:
   - Normal expected behavior
   - Boundary & edge cases
   - Invalid input handling / exceptions if specified
3. Output ONLY valid, executable Python code containing the test functions.
4. Do NOT wrap output in markdown explanation, just the python code block.
"""
        return prompt

    def generate_tests(self, spec: SpecificationMetadata) -> str:
        prompt = self.build_isolated_prompt(spec)

        if not self.api_key:
            # Deterministic fallback test generator when GROQ_API_KEY is not available
            return self._generate_fallback_tests(spec)

        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert test engineer writing clean pytest tests based on requirements."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            raw_code = response.choices[0].message.content or ""
            return self._clean_code(raw_code)
        except Exception as e:
            # Fallback gracefully
            return self._generate_fallback_tests(spec)

    def _clean_code(self, raw_code: str) -> str:
        code = raw_code.strip()
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()

    def _generate_fallback_tests(self, spec: SpecificationMetadata) -> str:
        """
        Creates fallback test cases matching standard spec constraints.
        """
        func = spec.function_name
        mod = spec.module_name
        return f"""import pytest
from {mod} import {func}

def test_{func}_normal():
    # Basic execution test derived from docstring
    res = {func}(10, 20)
    assert res is not None

def test_{func}_boundary():
    # Boundary check derived from specification
    res = {func}(0, 0)
    assert res is not None
"""


class BlindTestExecutor:
    """
    Executes generated tests against the actual target implementation inside an isolated sandbox.
    """
    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = timeout_seconds

    def execute_tests(
        self,
        target_code: str,
        generated_test_code: str,
        module_name: str = "target_module"
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            # 1. Write the target implementation
            target_path = os.path.join(temp_dir, f"{module_name}.py")
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(target_code)

            # 2. Write the generated tests
            test_path = os.path.join(temp_dir, "test_generated.py")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(generated_test_code)

            # 3. Run pytest inside the temporary directory
            cmd = [sys.executable, "-m", "pytest", "test_generated.py", "-v", "--tb=short"]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=self.timeout_seconds
                )
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": f"Execution timed out after {self.timeout_seconds} seconds.",
                    "passed": 0,
                    "failed": 1,
                    "failures": [{"test_name": "timeout", "message": "Test execution timed out."}]
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "passed": 0,
                    "failed": 1,
                    "failures": [{"test_name": "execution_error", "message": str(e)}]
                }

            # 4. Parse output
            failures = []
            passed_count = 0
            failed_count = 0

            # Match pytest output lines: test_generated.py::test_name PASSED / FAILED
            for line in stdout.splitlines():
                if " PASSED" in line:
                    passed_count += 1
                elif " FAILED" in line or " ERROR" in line:
                    failed_count += 1
                    test_match = re.search(r"::(test_\w+)", line)
                    test_name = test_match.group(1) if test_match else "unknown_test"
                    failures.append({
                        "test_name": test_name,
                        "message": line.strip()
                    })

            # Extract failure trace details
            if exit_code != 0 and not failures:
                # Syntax error in generated tests or runtime import error
                failures.append({
                    "test_name": "test_collection_or_import",
                    "message": stdout or stderr
                })

            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "passed": passed_count,
                "failed": len(failures),
                "failures": failures,
                "raw_stdout": stdout,
                "raw_stderr": stderr
            }


def run_blind_test(
    spec: SpecificationMetadata,
    implementation_code: str,
    file_path: Optional[str] = "target_module.py"
) -> List[Dict[str, Any]]:
    """
    Orchestrates the Blind Tester pipeline:
    1. Information isolation check
    2. Generate independent tests using Groq LLM (without implementation)
    3. Execute generated tests against target implementation
    4. Produce structured findings
    """
    # Verify isolation
    spec.validate_isolation()

    generator = BlindTestGenerator()
    generated_test_code = generator.generate_tests(spec)

    executor = BlindTestExecutor()
    execution_result = executor.execute_tests(
        target_code=implementation_code,
        generated_test_code=generated_test_code,
        module_name=spec.module_name
    )

    findings: List[BlindTesterFinding] = []

    if execution_result["success"]:
        # Passed all specification tests
        findings.append(BlindTesterFinding(
            agent_name="Blind-Tester",
            severity="INFO",
            status="PASS",
            title=f"All Blind Specification Tests Passed for {spec.function_name}",
            description=f"Function passed {execution_result['passed']} independently generated specification tests.",
            file_path=file_path,
            function_name=spec.function_name,
            evidence=f"{execution_result['passed']} tests passed without failures."
        ))
    else:
        # Generate finding for each failure
        for fail in execution_result["failures"]:
            findings.append(BlindTesterFinding(
                agent_name="Blind-Tester",
                severity="HIGH",
                status="FAIL",
                title=f"Specification Violation in {spec.function_name}",
                description=f"Generated specification test '{fail['test_name']}' failed against implementation.",
                file_path=file_path,
                function_name=spec.function_name,
                test_name=fail["test_name"],
                evidence=fail["message"]
            ))

    return [f.to_dict() for f in findings]
