"""
Phase D: ADK <-> CrewAI interoperability over the official A2A protocol (a2a-sdk).

- The Rollback Advisor is a CrewAI agent. It is served as an A2A agent (agent card plus JSON-RPC message/send) by the
  a2a-sdk server, mounted in the backend at ADVISOR_PATH.
- The Triage agent is an ADK agent. It reaches the advisor with ADK's RemoteA2aAgent, which is the protocol client.
  Nothing in this path is a private call between two Python objects: the ADK side and the CrewAI side only meet
  through the A2A wire protocol.

Authority: the advisor only recommends. It never executes anything. The deterministic RollbackAgent (five safety
checks, rollback lock, health and commit verification) remains the only code that can roll a deployment back. The
triage result says so explicitly with rollback_executed=False.

Trust: a message from another agent is untrusted text. It is checked by the same input guardrail as user text before
the advisor acts on it, and an advisor reply is validated as JSON before the triage agent uses it.
"""
import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, Optional

from crewai import Agent
from crewai.tools import tool
from fastapi import FastAPI
from google.genai import types

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message, Part, Role

from google.adk.a2a.agent import RemoteA2aAgent
from google.adk.runners import InMemoryRunner

WORKER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker"))
if WORKER_DIR not in sys.path:
    sys.path.insert(0, WORKER_DIR)
import guardrails  # noqa: E402

logger = logging.getLogger("sceptic.a2a_interop")

ADVISOR_PATH = "/a2a-interop/advisor"
APP_NAME = "sceptic_triage"
USER_ID = "sceptic-triage"
PROTOCOL_VERSION = "1.0"


def public_base_url() -> str:
    return os.getenv("SCEPTIC_SELF_URL", "http://localhost:8000").rstrip("/")


# ---------------------------------------------------------------- the CrewAI advisor (deterministic)

def advise(probe: Dict[str, Any]) -> Dict[str, Any]:
    """Recommendation from a Watchdog probe. Pure function: the same probe always gives the same advice."""
    findings = probe.get("findings") or []
    verdict = probe.get("verdict")
    severe = [
        f for f in findings
        if str(f.get("severity", "")).upper() in ("CRITICAL", "HIGH")
        and f.get("finding_type") not in ("UNRESOLVED", "METRIC_UNAVAILABLE")
    ]
    if verdict == "FAIL" and severe:
        recommendation = "ROLLBACK_CANDIDATE"
        reason = "Runtime verdict is FAIL with severe findings: " + ", ".join(f["finding_type"] for f in severe)
    elif verdict == "UNRESOLVED":
        recommendation = "INVESTIGATE"
        reason = "Some runtime data is missing, so the verdict cannot be trusted either way."
    else:
        recommendation = "NO_ACTION"
        reason = "No severe runtime findings."
    return {
        "recommendation": recommendation,
        "rollback_candidate": recommendation == "ROLLBACK_CANDIDATE",
        "reason": reason,
        "basis": [f["finding_type"] for f in severe],
        "authority": "Advisory only. The RollbackAgent safety checks decide, and this advice executes nothing.",
    }


@tool("Rollback Advice")
def rollback_advice_tool(probe_json: str) -> str:
    """Returns deterministic rollback advice for a Watchdog probe given as a JSON object. Advisory only."""
    try:
        probe = json.loads(probe_json)
    except (TypeError, ValueError):
        return json.dumps({"error": "probe is not valid JSON"})
    if not isinstance(probe, dict):
        return json.dumps({"error": "probe must be a JSON object"})
    return json.dumps(advise(probe))


rollback_advisor_agent = Agent(
    role="Rollback Advisor",
    goal="Recommend whether a deployment looks like a rollback candidate, using only the deterministic advice tool.",
    backstory=(
        "You advise on post-deployment runtime evidence. You never guess: you call the Rollback Advice tool and report "
        "its result. You have no power to roll anything back."
    ),
    tools=[rollback_advice_tool],
    verbose=False,
    allow_delegation=False,
)


# ---------------------------------------------------------------- A2A server side (serves the CrewAI agent)

class RollbackAdvisorExecutor(AgentExecutor):
    """Runs the CrewAI advisor for each A2A message and returns its reply as one agent message."""

    async def execute(self, context, event_queue) -> None:
        text = context.get_user_input()
        verdict = guardrails.check_and_log(text, "text", "a2a.advisor")
        if verdict.allowed:
            reply = rollback_advice_tool.run(text)
        else:
            reply = json.dumps({"error": "message rejected by input guardrail", "reasons": verdict.reasons})
        await event_queue.enqueue_event(Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_AGENT,
            parts=[Part(text=reply)],
        ))

    async def cancel(self, context, event_queue) -> None:
        raise RuntimeError("cancellation is not supported by the rollback advisor")


def advisor_card(base_url: Optional[str] = None) -> AgentCard:
    base = (base_url or public_base_url()).rstrip("/")
    return AgentCard(
        name="Sceptic Rollback Advisor",
        description="CrewAI agent that recommends whether a deployment is a rollback candidate. Advisory only.",
        version="1.0.0",
        # The trailing slash matters: the JSON-RPC route is registered at "/" inside the mount. Without it the server
        # answers the POST with a 307 redirect, which the A2A client does not follow.
        supported_interfaces=[AgentInterface(
            url=f"{base}{ADVISOR_PATH}/", protocol_binding="JSONRPC", protocol_version=PROTOCOL_VERSION,
        )],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[AgentSkill(
            id="advise_rollback",
            name="Advise on rollback",
            description="Input: a Watchdog probe as a JSON object. Output: recommendation, basis and reason as JSON.",
            tags=["rollback", "runtime"],
        )],
    )


def build_advisor_app(base_url: Optional[str] = None) -> FastAPI:
    """A FastAPI app that serves the advisor over A2A: agent card at /.well-known/agent-card.json, JSON-RPC at /."""
    card = advisor_card(base_url)
    handler = DefaultRequestHandler(
        agent_executor=RollbackAdvisorExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = FastAPI(title="Sceptic Rollback Advisor (A2A)")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, "/"),
    )
    return app


# ---------------------------------------------------------------- ADK client side (the triage agent)

async def ask_rollback_advisor(probe: Dict[str, Any], base_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Sends the probe to the advisor through ADK's A2A client and parses the reply. Never raises: an unreachable or
    malformed reply is returned as an error, and the deterministic verdict is unaffected.
    """
    card_url = f"{(base_url or public_base_url()).rstrip('/')}{ADVISOR_PATH}/.well-known/agent-card.json"
    try:
        remote = RemoteA2aAgent(name="rollback_advisor", agent_card=card_url)
        runner = InMemoryRunner(agent=remote, app_name=APP_NAME)
        session = await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
        message = types.Content(role="user", parts=[types.Part(text=json.dumps(probe))])
        reply = ""
        async for event in runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts if not getattr(p, "thought", False))
        if not reply.strip():
            return {"advice": None, "card": card_url, "error": "advisor returned an empty reply"}
        advice = json.loads(reply)
        if not isinstance(advice, dict) or "recommendation" not in advice:
            return {"advice": None, "card": card_url, "error": "advisor reply has no recommendation"}
        return {"advice": advice, "card": card_url, "error": None}
    except Exception as exc:  # the advisor is advisory: its failure is reported, not raised
        logger.warning(f"rollback advisor unavailable: {type(exc).__name__}: {exc}")
        return {"advice": None, "card": card_url, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def triage(probe: Dict[str, Any], base_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Triage for one probe: the deterministic verdict, the advisor's recommendation over A2A, and an explicit statement
    that nothing was executed. Rollback itself stays with the RollbackAgent.
    """
    advisor = await ask_rollback_advisor(probe, base_url)
    return {
        "verdict": probe.get("verdict"),
        "advisor": advisor,
        "rollback_executed": False,
        "authority": "RollbackAgent safety checks (not this triage) decide whether any rollback runs.",
    }
