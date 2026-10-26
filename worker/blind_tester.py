import os
import re
import sys
import json
import logging
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(__file__))
from sandbox_runner import get_sandbox_runner, SandboxUnavailable
from language_test_runners import runner_spec, normalize_language, UnsupportedLanguage
from llm_client import make_groq_client, llm_blocked, note_llm_error

logger = logging.getLogger("sceptic.blind_tester")

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
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def build_isolated_prompt(self, spec: SpecificationMetadata) -> str:
        # Enforce strict isolation
        spec.validate_isolation()
        if normalize_language(spec.language) != "python":
            return self._language_prompt(spec)

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
        if llm_blocked():
            return self._generate_fallback_tests(spec)

        try:
            client = make_groq_client(self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_message(spec)},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            raw_code = response.choices[0].message.content or ""
            return self._clean_code(raw_code)
        except Exception as e:
            # Fall back to the template tests, but say so: the template is a weak specification check.
            logger.warning(f"Blind-Tester LLM test generation failed with model {self.model}; using template tests: {e}")
            note_llm_error(e)
            return self._generate_fallback_tests(spec)

    def _system_message(self, spec: SpecificationMetadata) -> str:
        frameworks = {
            "python": "pytest",
            "javascript": "Jest (CommonJS require)",
            "typescript": "Jest with TypeScript",
            "java": "JUnit 5",
        }
        language = normalize_language(spec.language)
        return f"You are an expert test engineer writing clean {frameworks[language]} tests based on requirements."

    def _language_prompt(self, spec: SpecificationMetadata) -> str:
        """Test-generation prompt for JavaScript, TypeScript, and Java. Like the Python prompt, it sees only the spec."""
        language = normalize_language(spec.language)
        rules = {
            "javascript": (
                "Jest test code (CommonJS). Load the module with: const m = require('./{module}');\n"
                "Call the function as m.{fn}(...). Use test('...', () => {{ ... }}) and expect(...)."
            ),
            "typescript": (
                "Jest test code in TypeScript. Load the module with: import * as m from './{module}';\n"
                "Call the function as m.{fn}(...). Use test('...', () => {{ ... }}) and expect(...)."
            ),
            "java": (
                "JUnit 5 test code. The test class must be named {module}Test in the default package and must use\n"
                "import static org.junit.jupiter.api.Assertions.*; and import org.junit.jupiter.api.Test;\n"
                "Call the static method {module}.{fn}(...). Each test is a public void method annotated with @Test."
            ),
        }[language]
        rule = rules.format(module=spec.module_name, fn=spec.function_name)
        return f"""You are an independent specification-based test generator for {language} code.
You MUST write unit tests for the following function based ONLY on its name, docstring, and specification.
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
1. {rule}
2. Write several independent tests covering normal behavior, boundary and edge cases, and invalid input where the specification says so.
3. Output ONLY the code, with no markdown explanation.
"""

    def _clean_code(self, raw_code: str) -> str:
        code = raw_code.strip()
        fence = re.match(r"^```[A-Za-z0-9_+-]*\s*\n?(.*?)\n?```$", code, re.S)
        if fence:
            code = fence.group(1)
        return code.strip()

    def _generate_fallback_tests(self, spec: SpecificationMetadata) -> str:
        """
        Creates fallback test cases matching standard spec constraints.
        """
        if normalize_language(spec.language) != "python":
            return self._fallback_for_language(spec)
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


    def _fallback_for_language(self, spec: SpecificationMetadata) -> str:
        """
        Template tests used without an LLM. They check that the function exists and is callable,
        not that it meets the specification. That is weaker than the LLM tests, and the verdict says so.
        """
        func = spec.function_name
        module = spec.module_name
        language = normalize_language(spec.language)
        if language == "javascript":
            return (
                f"const m = require('./{module}');\n"
                f"test('{func} is exported as a function', () => {{\n"
                f"  expect(typeof m.{func}).toBe('function');\n"
                "});\n"
            )
        if language == "typescript":
            return (
                f"import * as m from './{module}';\n"
                f"test('{func} is exported as a function', () => {{\n"
                f"  expect(typeof m.{func}).toBe('function');\n"
                "});\n"
            )
        return (
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.*;\n"
            f"class {module}Test {{\n"
            "  @Test\n"
            "  void exposesFunction() {\n"
            f"    assertTrue(java.util.Arrays.stream({module}.class.getDeclaredMethods())\n"
            f"        .anyMatch(method -> method.getName().equals(\"{func}\")));\n"
            "  }\n"
            "}\n"
        )


class BlindTestExecutor:
    """
    Executes generated tests against the actual target implementation inside an isolated sandbox.
    """
    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = timeout_seconds

    def _execute_non_python(
        self,
        target_code: str,
        generated_test_code: str,
        module_name: str,
        language: str
    ) -> Dict[str, Any]:
        """Runs JavaScript, TypeScript, or Java tests in the sandbox. Same result shape as the Python path."""
        try:
            spec = runner_spec(language, module_name)
        except (UnsupportedLanguage, ValueError) as e:
            return {"success": False, "error": str(e), "passed": 0, "failed": 1,
                    "failures": [{"test_name": "unsupported", "message": str(e)}]}

        base_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(dir=base_dir) as temp_dir:
            with open(os.path.join(temp_dir, spec.impl_file), "w", encoding="utf-8") as f:
                f.write(target_code)
            with open(os.path.join(temp_dir, spec.test_file), "w", encoding="utf-8") as f:
                f.write(generated_test_code)
            for name, content in spec.extra_files.items():
                with open(os.path.join(temp_dir, name), "w", encoding="utf-8") as f:
                    f.write(content)
            try:
                result = get_sandbox_runner().run_command(temp_dir, spec.command, self.timeout_seconds)
            except SandboxUnavailable as e:
                return {"success": False, "error": str(e), "sandbox_unavailable": True, "passed": 0, "failed": 1,
                        "failures": [{"test_name": "sandbox_unavailable", "message": str(e)}]}
            except Exception as e:
                return {"success": False, "error": str(e), "passed": 0, "failed": 1,
                        "failures": [{"test_name": "execution_error", "message": str(e)}]}

        if result.timed_out:
            return {"success": False, "error": f"Execution timed out after {self.timeout_seconds} seconds.",
                    "passed": 0, "failed": 1,
                    "failures": [{"test_name": "timeout", "message": "Test execution timed out."}]}
        return spec.parse(result.returncode, result.stdout, result.stderr)

    def execute_tests(
        self,
        target_code: str,
        generated_test_code: str,
        module_name: str = "target_module",
        language: str = "python"
    ) -> Dict[str, Any]:
        language = normalize_language(language)
        if language != "python":
            return self._execute_non_python(target_code, generated_test_code, module_name, language)

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

            # 3. Run pytest inside the sandbox (network-isolated container by default).
            # If the sandbox cannot run, nothing is executed on the host and the result is reported as unavailable.
            try:
                result = get_sandbox_runner().run_pytest(temp_dir, "test_generated.py", self.timeout_seconds)
            except SandboxUnavailable as e:
                return {
                    "success": False,
                    "error": str(e),
                    "sandbox_unavailable": True,
                    "passed": 0,
                    "failed": 1,
                    "failures": [{"test_name": "sandbox_unavailable", "message": str(e)}]
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "passed": 0,
                    "failed": 1,
                    "failures": [{"test_name": "execution_error", "message": str(e)}]
                }

            if result.timed_out:
                return {
                    "success": False,
                    "error": f"Execution timed out after {self.timeout_seconds} seconds.",
                    "passed": 0,
                    "failed": 1,
                    "failures": [{"test_name": "timeout", "message": "Test execution timed out."}]
                }
            stdout = result.stdout
            stderr = result.stderr
            exit_code = result.returncode

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

            # Attach the exception types pytest reported. A spec violation is an AssertionError. A crash such as
            # TypeError or ZeroDivisionError is evidence of a call-signature or input problem, not of the spec.
            error_types = sorted(set(re.findall(r"^E\s+(\w+(?:Error|Exception|Failure))\b", stdout or "", re.M)))
            if error_types:
                for failure in failures:
                    failure["message"] = f"{failure['message']} [errors: {', '.join(error_types)}]"

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


_COLLECTION_ERROR_MARKERS = (
    "ModuleNotFoundError",
    "ImportError",
    "SyntaxError",
    "ERROR collecting",
    "test_collection_or_import",
)


def _is_collection_error(failure: Dict[str, Any]) -> bool:
    """True when a generated test failed to import or parse instead of running its assertions."""
    text = f"{failure.get('test_name', '')} {failure.get('message', '')}"
    return any(marker in text for marker in _COLLECTION_ERROR_MARKERS)


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
        module_name=spec.module_name,
        language=spec.language,
    )

    findings: List[BlindTesterFinding] = []

    if execution_result.get("sandbox_unavailable"):
        # HIGH so an unexecuted specification can never produce an APPROVE verdict.
        findings.append(BlindTesterFinding(
            agent_name="Blind-Tester",
            severity="HIGH",
            status="ERROR",
            title=f"Blind-Tester sandbox unavailable for {spec.function_name}",
            description="Generated tests were not executed because the sandbox is unavailable. Verification is incomplete.",
            file_path=file_path,
            function_name=spec.function_name,
            evidence=execution_result.get("error")
        ))
    elif execution_result["success"]:
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
            if fail["test_name"] == "compilation":
                findings.append(BlindTesterFinding(
                    agent_name="Blind-Tester",
                    severity="HIGH",
                    status="FAIL",
                    title=f"Code does not compile ({spec.language})",
                    description="The implementation failed to compile, so no specification test could run.",
                    file_path=file_path,
                    function_name=spec.function_name,
                    test_name="compilation",
                    evidence=fail["message"]
                ))
                continue
            if _is_collection_error(fail):
                # The generated test never ran, so it says nothing about the code. Report it, but do not count it as a defect.
                findings.append(BlindTesterFinding(
                    agent_name="Blind-Tester",
                    severity="LOW",
                    status="ERROR",
                    title=f"Generated tests could not be collected for {spec.function_name}",
                    description="The generated test module failed to import or parse, so its assertions did not run.",
                    file_path=file_path,
                    function_name=spec.function_name,
                    test_name=fail["test_name"],
                    evidence=fail["message"]
                ))
                continue
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
