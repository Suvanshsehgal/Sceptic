"""
Sandboxed execution for Blind-Tester.

Generated tests and the audited implementation are untrusted code, so they run inside a
network-isolated container instead of on the host.

The sandbox image (worker/sandbox/Dockerfile) has four runners: pytest (Python), Jest (JavaScript and TypeScript),
and javac with the JUnit 5 console launcher (Java). The command that runs in the container is chosen by
language_test_runners.py. This module only starts the container.

Modes (selected with SCEPTIC_SANDBOX):
- docker (default): run the command in the sceptic-sandbox image with no network, a read-only code mount,
  a tmpfs /tmp, no capabilities, a non-root user, and memory/CPU/PID limits. If Docker is unavailable
  the run fails closed: the caller reports it and nothing is executed on the host.
- local-unsafe: run Python tests on the host in a temporary directory. Only for the test suite and local
  debugging. It must never be used for untrusted code. Other languages are refused in this mode.
"""
import os
import sys
import uuid
import shutil
import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("sceptic.sandbox")

SANDBOX_IMAGE = os.getenv("SCEPTIC_SANDBOX_IMAGE", "sceptic-sandbox:latest")
# Node and the JVM need more memory than pytest; 512 MB is the default for all runners.
SANDBOX_MEMORY = os.getenv("SCEPTIC_SANDBOX_MEMORY", "512m")
SANDBOX_CPUS = os.getenv("SCEPTIC_SANDBOX_CPUS", "1")
SANDBOX_PIDS_LIMIT = os.getenv("SCEPTIC_SANDBOX_PIDS_LIMIT", "256")
SANDBOX_BUILD_HINT = "docker build -t sceptic-sandbox:latest -f worker/sandbox/Dockerfile worker"

PYTHON_COMMAND = ["python", "-m", "pytest", "test_generated.py", "-v", "--tb=short", "-p", "no:cacheprovider"]


class SandboxUnavailable(RuntimeError):
    """The configured sandbox cannot run, so the untrusted code was not executed."""


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _sandbox_mode() -> str:
    return os.getenv("SCEPTIC_SANDBOX", "docker").strip().lower()


class DockerSandboxRunner:
    """Runs a test command inside a locked-down container."""

    def __init__(self, image: str = SANDBOX_IMAGE):
        self.image = image

    def check_available(self) -> None:
        if shutil.which("docker") is None:
            raise SandboxUnavailable("Docker CLI not found; Blind-Tester cannot run untrusted code without a sandbox.")
        try:
            probe = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SandboxUnavailable(f"Docker is not responding: {e}")
        if probe.returncode != 0:
            raise SandboxUnavailable(f"Sandbox image '{self.image}' not found. Build it with: {SANDBOX_BUILD_HINT}")

    def build_command(self, workdir: str, container_name: str, command: List[str]) -> List[str]:
        return [
            "docker", "run", "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=128m,mode=1777",
            "--memory", SANDBOX_MEMORY,
            "--memory-swap", SANDBOX_MEMORY,
            "--cpus", SANDBOX_CPUS,
            "--pids-limit", SANDBOX_PIDS_LIMIT,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "TMPDIR=/tmp",
            "--env", "HOME=/tmp",
            "--mount", f"type=bind,source={os.path.abspath(workdir)},target=/work,readonly",
            "--workdir", "/work",
            self.image,
            *command,
        ]

    def run_command(self, workdir: str, command: List[str], timeout_seconds: int) -> SandboxResult:
        self.check_available()
        container_name = f"sceptic-sandbox-{uuid.uuid4().hex[:12]}"
        cmd = self.build_command(workdir, container_name, command)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            return SandboxResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, stdin=subprocess.DEVNULL)
            return SandboxResult(-1, "", "", timed_out=True)

    def run_pytest(self, workdir: str, test_file: str, timeout_seconds: int) -> SandboxResult:
        """Kept for existing callers: runs pytest on one test file."""
        command = [part if part != "test_generated.py" else test_file for part in PYTHON_COMMAND]
        return self.run_command(workdir, command, timeout_seconds)


class LocalUnsafeRunner:
    """Host execution. Used only when SCEPTIC_SANDBOX=local-unsafe, for Python tests only."""

    def run_pytest(self, workdir: str, test_file: str, timeout_seconds: int) -> SandboxResult:
        logger.warning("Blind-Tester is running generated tests on the host (SCEPTIC_SANDBOX=local-unsafe).")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"],
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            return SandboxResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            return SandboxResult(-1, "", "", timed_out=True)

    def run_command(self, workdir: str, command: List[str], timeout_seconds: int) -> SandboxResult:
        raise SandboxUnavailable(
            "SCEPTIC_SANDBOX=local-unsafe supports Python tests only. Use the docker sandbox for JavaScript, TypeScript, and Java."
        )


def get_sandbox_runner(mode: Optional[str] = None):
    """Returns the runner for the configured mode. Unknown modes fail closed."""
    selected = (mode or _sandbox_mode()).strip().lower()
    if selected == "docker":
        return DockerSandboxRunner()
    if selected == "local-unsafe":
        return LocalUnsafeRunner()
    raise SandboxUnavailable(f"Unknown SCEPTIC_SANDBOX mode '{selected}'. Use 'docker' or 'local-unsafe'.")
