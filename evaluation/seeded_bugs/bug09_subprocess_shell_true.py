import subprocess


def run_tool(cmd):
    """Runs a helper command and returns its exit code."""
    return subprocess.run(cmd, shell=True).returncode
