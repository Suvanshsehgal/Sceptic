"""
Phase 3: A2A (agent-to-agent) messaging between Sceptic's post-deployment agents.

This is an A2A-compatible subset, written in-house rather than with the official a2a-sdk:
- Agent cards at  <base>/a2a/<agent>/.well-known/agent.json  (name, description, url, skills).
- JSON-RPC 2.0 method "message/send" at POST <base>/a2a/<agent>.
- A message carries one "data" part with a JSON object; the reply is one "data" part with the result.
- Calls are authenticated with the caller's own bearer token, so an agent can act only for a user who could
  already do the same action through the REST API.

Not implemented: streaming, task lifecycle objects, push notifications, and the full A2A spec.
"""
import os
from typing import Any, Dict, Optional

import httpx

JSONRPC_VERSION = "2.0"
METHOD_MESSAGE_SEND = "message/send"
SELF_BASE_URL = os.getenv("SCEPTIC_SELF_URL", "http://localhost:8000").rstrip("/")
A2A_TIMEOUT_SECONDS = float(os.getenv("SCEPTIC_A2A_TIMEOUT_SECONDS", "60"))


class A2AError(RuntimeError):
    """Raised when an A2A call fails or the peer returns a JSON-RPC error."""


AGENT_CARDS: Dict[str, Dict[str, Any]] = {
    "watchdog": {
        "name": "Sceptic Pipeline Watchdog",
        "description": "Checks a deployment's runtime health and metrics; asks the Rollback agent to act on failures.",
        "version": "1.0.0",
        "path": "/a2a/watchdog",
        "skills": [{
            "id": "check_deployment",
            "name": "Check deployment runtime",
            "description": "Input: {deployment_id}. Output: watchdog result and optional rollback result.",
        }],
    },
    "rollback": {
        "name": "Sceptic Rollback Agent",
        "description": "Evaluates the five pre-flight safety checks and rolls back only when all pass.",
        "version": "1.0.0",
        "path": "/a2a/rollback",
        "skills": [{
            "id": "request_rollback",
            "name": "Request rollback",
            "description": "Input: {deployment_id, reason, trigger_source}. Output: rollback execution result.",
        }],
    },
}


def agent_card(agent: str, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Return the public agent card for an agent. Raises KeyError for unknown agents."""
    card = dict(AGENT_CARDS[agent])
    base = (base_url or SELF_BASE_URL).rstrip("/")
    card["url"] = f"{base}{card['path']}"
    card["capabilities"] = {"streaming": False, "pushNotifications": False}
    card["authentication"] = {"schemes": ["Bearer"]}
    return card


def make_request(payload: Dict[str, Any], request_id: str = "1") -> Dict[str, Any]:
    """Build a JSON-RPC message/send request carrying one data part."""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": METHOD_MESSAGE_SEND,
        "params": {"message": {"role": "user", "parts": [{"kind": "data", "data": payload}]}},
    }


def read_request(body: Any) -> Dict[str, Any]:
    """Validate an incoming JSON-RPC message/send request and return its data payload."""
    if not isinstance(body, dict) or body.get("jsonrpc") != JSONRPC_VERSION:
        raise A2AError("request is not JSON-RPC 2.0")
    if body.get("method") != METHOD_MESSAGE_SEND:
        raise A2AError(f"unsupported method: {body.get('method')}")
    try:
        parts = body["params"]["message"]["parts"]
    except (KeyError, TypeError):
        raise A2AError("missing params.message.parts")
    data_parts = [p for p in parts if isinstance(p, dict) and p.get("kind") == "data"]
    if len(data_parts) != 1 or not isinstance(data_parts[0].get("data"), dict):
        raise A2AError("message must contain exactly one data part with a JSON object")
    return data_parts[0]["data"]


def make_response(request_id: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Build the JSON-RPC success reply carrying one data part."""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": {"kind": "message", "role": "agent", "parts": [{"kind": "data", "data": data}]},
    }


def response_data(body: Any) -> Dict[str, Any]:
    """Extract the data object from a JSON-RPC reply, raising A2AError on a protocol error."""
    if not isinstance(body, dict):
        raise A2AError("reply is not a JSON object")
    if "error" in body:
        error = body["error"] or {}
        raise A2AError(f"peer error {error.get('code')}: {error.get('message')}")
    try:
        return body["result"]["parts"][0]["data"]
    except (KeyError, IndexError, TypeError):
        raise A2AError("reply has no data part")


async def send_message(agent_url: str, payload: Dict[str, Any], authorization: Optional[str]) -> Dict[str, Any]:
    """Send a message to another agent and return its data reply. Uses the caller's bearer token."""
    headers = {"Authorization": authorization} if authorization else {}
    async with httpx.AsyncClient(timeout=A2A_TIMEOUT_SECONDS) as client:
        resp = await client.post(agent_url, json=make_request(payload), headers=headers)
    if resp.status_code != 200:
        raise A2AError(f"peer returned HTTP {resp.status_code} from {agent_url}")
    return response_data(resp.json())
