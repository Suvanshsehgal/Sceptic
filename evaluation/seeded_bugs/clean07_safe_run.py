import subprocess


def git_branch(repo_path):
    """Returns the current git branch name of a repository, using an argument list and no shell."""
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()
