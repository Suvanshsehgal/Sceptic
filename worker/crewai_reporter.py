"""
Reporter as a CrewAI agent.

Posts the audit summary back to the pull request through the MCP tool post_github_comment.
Without GITHUB_TOKEN the tool is a dry run and nothing is posted.
"""
import json
from typing import Any, Dict

from crewai import Agent
from crewai.tools import tool

from mcp_client import get_mcp_client


@tool("GitHub Pull Request Commenter")
def github_comment_tool(payload_json: str) -> str:
    """
    Posts a comment on a GitHub pull request.
    Accepts a JSON string with keys: 'repository' (owner/name), 'pr_number' (int), 'body' (str).
    """
    try:
        data = json.loads(payload_json)
        return get_mcp_client().call_tool("post_github_comment", {
            "repository": data["repository"],
            "pr_number": int(data["pr_number"]),
            "body": data["body"],
        })
    except Exception as e:
        return json.dumps({"posted": False, "error": str(e)})


reporter_agent = Agent(
    role="Reporter",
    goal="Publish the verification summary to the pull request so reviewers see the verdict.",
    backstory="You publish verification results exactly as produced by the verification agents.",
    tools=[github_comment_tool],
    verbose=False,
    allow_delegation=False,
)


def post_pr_summary(repository: str, pr_number: int, body: str) -> Dict[str, Any]:
    """Runs the reporter's tool and returns the posting result."""
    payload = json.dumps({"repository": repository, "pr_number": pr_number, "body": body})
    return json.loads(github_comment_tool.run(payload))
