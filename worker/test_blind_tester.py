import pytest
from blind_tester import (
    SpecificationMetadata,
    BlindTestGenerator,
    BlindTestExecutor,
    run_blind_test
)

def test_specification_produces_generated_tests():
    spec = SpecificationMetadata(
        function_name="calculate_discount",
        docstring="Calculates discount given price and percentage.\nReturns price - (price * (percentage / 100)).",
        specification="Price must be non-negative float. Percentage must be between 0 and 100."
    )
    generator = BlindTestGenerator()
    test_code = generator.generate_tests(spec)
    assert "def test_" in test_code
    assert "calculate_discount" in test_code

def test_correct_implementation_passes():
    spec = SpecificationMetadata(
        function_name="add_numbers",
        docstring="Adds two numbers a and b and returns their sum.",
        specification="Must return an integer or float sum."
    )
    impl_code = """
def add_numbers(a, b):
    return a + b
"""
    results = run_blind_test(spec, impl_code)
    assert len(results) > 0
    assert results[0]["status"] == "PASS"
    assert "Passed" in results[0]["title"]

def test_incorrect_implementation_causes_failure():
    spec = SpecificationMetadata(
        function_name="add_numbers",
        docstring="Adds two numbers a and b and returns their sum.",
        specification="Returns a + b."
    )
    # Buggy implementation returning product instead of sum
    impl_code = """
def add_numbers(a, b):
    return a * b
"""
    # Write a test that asserts add_numbers(10, 20) == 30
    executor = BlindTestExecutor()
    custom_test = """
import pytest
from target_module import add_numbers

def test_add_numbers_correctness():
    assert add_numbers(10, 20) == 30
"""
    exec_result = executor.execute_tests(impl_code, custom_test)
    assert exec_result["success"] is False
    assert exec_result["failed"] == 1
    assert "test_add_numbers_correctness" in exec_result["failures"][0]["test_name"]

def test_boundary_edge_behavior_can_be_tested():
    spec = SpecificationMetadata(
        function_name="clamp",
        docstring="Clamps val between min_val and max_val.",
        specification="If val < min_val return min_val; if val > max_val return max_val; else val."
    )
    impl_code = """
def clamp(val, min_val, max_val):
    if val < min_val:
        return min_val
    if val > max_val:
        return max_val
    return val
"""
    test_code = """
from target_module import clamp

def test_clamp_boundaries():
    assert clamp(5, 10, 20) == 10
    assert clamp(25, 10, 20) == 20
    assert clamp(15, 10, 20) == 15
"""
    executor = BlindTestExecutor()
    res = executor.execute_tests(impl_code, test_code)
    assert res["success"] is True
    assert res["passed"] == 1

def test_generated_test_execution_returns_structured_results():
    spec = SpecificationMetadata(
        function_name="multiply",
        docstring="Returns multiplication of x and y.",
        specification="Multiplies two numbers."
    )
    impl_code = """
def multiply(x, y):
    return x * y
"""
    findings = run_blind_test(spec, impl_code)
    assert isinstance(findings, list)
    assert len(findings) > 0
    f = findings[0]
    assert "agent_name" in f
    assert f["agent_name"] == "Blind-Tester"
    assert "severity" in f
    assert "title" in f
    assert "status" in f

# =======================================================
# INFORMATION ISOLATION TESTS
# =======================================================

def test_information_isolation_source_code_rejected():
    """
    Test 6: The implementation is NOT present in the LLM generation context.
    If source code or implementation is passed in metadata, validate_isolation must raise an error.
    """
    spec = SpecificationMetadata(
        function_name="secret_function",
        docstring="Docstring only.",
        specification="Do something.",
        approved_metadata={"source_code": "def secret_function(): return 42"}
    )
    with pytest.raises(ValueError, match="Information isolation violation"):
        spec.validate_isolation()

    with pytest.raises(ValueError, match="Information isolation violation"):
        generator = BlindTestGenerator()
        generator.build_isolated_prompt(spec)

def test_information_isolation_existing_tests_rejected():
    """
    Test 7: Existing tests are NOT passed to the generation LLM.
    """
    spec = SpecificationMetadata(
        function_name="secret_function",
        docstring="Docstring only.",
        specification="Do something.",
        approved_metadata={"existing_tests": "def test_secret(): assert True"}
    )
    with pytest.raises(ValueError, match="Information isolation violation"):
        spec.validate_isolation()

def test_information_isolation_other_agent_findings_rejected():
    """
    Test 8: Fact-Checker and Security Guard findings are NOT passed to the generation LLM.
    """
    spec = SpecificationMetadata(
        function_name="secret_function",
        docstring="Docstring only.",
        specification="Do something.",
        approved_metadata={
            "fact_checker_findings": [{"title": "API mismatch"}],
            "security_guard_findings": [{"title": "Injection vulnerability"}]
        }
    )
    with pytest.raises(ValueError, match="Information isolation violation"):
        spec.validate_isolation()
