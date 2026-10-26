import os
import shutil
import socket
import tempfile
import subprocess

import pytest

from sandbox_runner import DockerSandboxRunner, SandboxUnavailable, get_sandbox_runner
from blind_tester import BlindTestExecutor, SpecificationMetadata, run_blind_test

WORKER_DIR = os.path.dirname(os.path.abspath(__file__))


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "image", "inspect", "sceptic-sandbox:latest"],
            capture_output=True, timeout=30, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


requires_sandbox_image = pytest.mark.skipif(
    not _docker_ready(),
    reason="Docker daemon or sceptic-sandbox:latest image not available",
)


def test_docker_command_has_isolation_flags():
    cmd = DockerSandboxRunner().build_command(
        "C:/tmp/work", "sceptic-sandbox-test", ["python", "-m", "pytest", "test_generated.py"]
    )
    joined = " ".join(cmd)
    assert cmd[:2] == ["docker", "run"]
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "--user 65534:65534" in joined
    assert "--memory 512m" in joined
    assert "--pids-limit 256" in joined
    assert cmd[-4:] == ["python", "-m", "pytest", "test_generated.py"]
    assert "type=bind" in joined and "readonly" in joined


def test_unknown_sandbox_mode_fails_closed():
    with pytest.raises(SandboxUnavailable):
        get_sandbox_runner("something-else")


def test_missing_docker_cli_fails_closed(monkeypatch):
    monkeypatch.setattr("sandbox_runner.shutil.which", lambda name: None)
    with pytest.raises(SandboxUnavailable):
        DockerSandboxRunner().check_available()


def test_blind_tester_reports_unavailable_sandbox_without_running_code(monkeypatch):
    """With the docker sandbox selected and Docker missing, nothing runs and the verdict cannot APPROVE."""
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    monkeypatch.setattr("sandbox_runner.shutil.which", lambda name: None)
    spec = SpecificationMetadata(function_name="add", docstring="Adds two numbers.", specification="Returns the sum.")
    findings = run_blind_test(spec, "def add(a, b):\n    return a + b\n")
    assert len(findings) == 1
    assert findings[0]["status"] == "ERROR"
    assert findings[0]["severity"] == "HIGH"
    assert "sandbox unavailable" in findings[0]["title"]


def test_executor_reports_unavailable_sandbox_flag(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    monkeypatch.setattr("sandbox_runner.shutil.which", lambda name: None)
    result = BlindTestExecutor().execute_tests("def f():\n    return 1\n", "def test_f():\n    assert True\n")
    assert result["success"] is False
    assert result["sandbox_unavailable"] is True


@requires_sandbox_image
def test_live_container_has_no_network_and_read_only_code_mount(monkeypatch):
    """Runs real code in the sandbox image and checks the isolation promises from the inside."""
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    generated = (
        "import socket, os\n"
        "def test_network_is_disabled():\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "    except OSError:\n"
        "        return\n"
        "    raise AssertionError('network reachable from sandbox')\n"
        "\n"
        "def test_workdir_is_read_only():\n"
        "    try:\n"
        "        open('/work/should_not_exist.txt', 'w').write('x')\n"
        "    except OSError:\n"
        "        return\n"
        "    raise AssertionError('workdir is writable')\n"
    )
    with tempfile.TemporaryDirectory(dir=WORKER_DIR) as tmp:
        with open(os.path.join(tmp, "test_isolation.py"), "w", encoding="utf-8") as f:
            f.write(generated)
        result = DockerSandboxRunner().run_pytest(tmp, "test_isolation.py", timeout_seconds=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@requires_sandbox_image
def test_live_timeout_kills_container(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    generated = "import time\ndef test_slow():\n    time.sleep(120)\n"
    with tempfile.TemporaryDirectory(dir=WORKER_DIR) as tmp:
        with open(os.path.join(tmp, "test_slow.py"), "w", encoding="utf-8") as f:
            f.write(generated)
        result = DockerSandboxRunner().run_pytest(tmp, "test_slow.py", timeout_seconds=15)
    assert result.timed_out is True
