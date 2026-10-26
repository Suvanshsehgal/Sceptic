"""
Workflow change guard for the Deployment Gatekeeper.

A change to .github/workflows/* can alter how code is built, tested, and deployed, so it needs an explicit approval.
The guard lists the workflow files changed between the previously deployed commit and the deployed commit.
If the deployed commit is not in WORKFLOW_APPROVED_COMMITS, each changed workflow file is reported.

Configuration:
- GATEKEEPER_REPO_PATH: local clone of the repository (the guard is skipped when unset)
- WORKFLOW_APPROVED_COMMITS: comma-separated commit SHAs that a maintainer approved for workflow changes
"""
import os
import re
import subprocess
from typing import List, Set

WORKFLOW_PREFIX = ".github/workflows/"
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


def approved_commits_from_env() -> Set[str]:
    raw = os.getenv("WORKFLOW_APPROVED_COMMITS", "")
    return {c.strip().lower() for c in raw.split(",") if SHA_PATTERN.match(c.strip())}


def changed_files(repo_path: str, base_sha: str, head_sha: str) -> List[str]:
    """Returns the files changed between base_sha and head_sha. Raises RuntimeError on git failure."""
    if not (SHA_PATTERN.match(base_sha or "") and SHA_PATTERN.match(head_sha or "")):
        raise RuntimeError("commit identifiers must be hexadecimal SHAs")
    proc = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-only", f"{base_sha}..{head_sha}"],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {proc.stderr.strip()[:300]}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def unapproved_workflow_changes(
    repo_path: str,
    base_sha: str,
    head_sha: str,
    approved: Set[str],
) -> List[str]:
    """Returns the workflow files changed without approval. An approved deployed commit has no unapproved changes."""
    head = head_sha.lower()
    # Approved entries may be abbreviated SHAs (7+ characters), so match by prefix.
    if any(len(a) >= 7 and head.startswith(a.lower()) for a in approved):
        return []
    return [
        path for path in changed_files(repo_path, base_sha, head_sha)
        if path.replace("\\", "/").startswith(WORKFLOW_PREFIX)
    ]
