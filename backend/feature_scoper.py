"""
Sceptic Feature Architecture & Feasibility Scoper.
Evaluates proposed software features using Groq LLM (openai/gpt-oss-120b)
with dynamic fallback when API keys are not provided.
"""
import os
import json
import logging
import re
from typing import Dict, Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sceptic.feature_scoper")

GROQ_API_BASE = "https://api.groq.com/openai/v1"
PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = "llama-3.3-70b-versatile"


async def evaluate_feature_proposal(
    feature_description: str,
    project_name: str,
    project_description: Optional[str] = None,
    repository_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates a feature proposal against project context using Groq LLM (openai/gpt-oss-120b),
    returning dynamic feasibility, complexity, risk, and confidence scores along with
    an architectural assessment and a 4-phase implementation plan.
    """
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

    if groq_api_key:
        try:
            result = await _call_groq_llm(
                feature_description=feature_description,
                project_name=project_name,
                project_description=project_description,
                repository_url=repository_url,
                api_key=groq_api_key,
                model=PRIMARY_MODEL
            )
            if result:
                return result
        except Exception as e:
            logger.warning(f"Groq primary model {PRIMARY_MODEL} call failed: {e}. Attempting fallback...")
            try:
                result = await _call_groq_llm(
                    feature_description=feature_description,
                    project_name=project_name,
                    project_description=project_description,
                    repository_url=repository_url,
                    api_key=groq_api_key,
                    model=FALLBACK_MODEL
                )
                if result:
                    return result
            except Exception as e_fallback:
                logger.error(f"Groq fallback model also failed: {e_fallback}. Falling back to dynamic heuristic engine.")

    # Fallback: Dynamic semantic heuristic evaluation
    return _dynamic_heuristic_analysis(
        feature_description=feature_description,
        project_name=project_name,
        has_groq_key=bool(groq_api_key)
    )


async def _call_groq_llm(
    feature_description: str,
    project_name: str,
    project_description: Optional[str],
    repository_url: Optional[str],
    api_key: str,
    model: str
) -> Optional[Dict[str, Any]]:
    """Calls Groq API with structured JSON output instructions."""
    system_prompt = (
        "You are the Sceptic Lead Systems Architect and Verification Engine. "
        "Evaluate proposed software features against modern software architecture, security, and maintainability standards.\n"
        "You must analyze the technical feasibility, architectural complexity, security/regression risk, and confidence.\n"
        "Respond ONLY with valid, parseable JSON conforming to this schema:\n"
        "{\n"
        '  "feasibility_score": <float between 0.0 and 100.0>,\n'
        '  "complexity_score": <float between 0.0 and 100.0>,\n'
        '  "risk_score": <float between 0.0 and 100.0>,\n'
        '  "confidence_score": <float between 0.0 and 100.0>,\n'
        '  "analysis": "<detailed architectural assessment explaining subsystem impacts, database changes, security implications, and design trade-offs>",\n'
        '  "implementation_plan": "<step-by-step numbered roadmap covering domain models, backend APIs, frontend/CLI wiring, and unit/regression tests>"\n'
        "}"
    )

    user_prompt = (
        f"Project Name: {project_name}\n"
        f"Repository: {repository_url or 'N/A'}\n"
        f"Project Context: {project_description or 'General full-stack system'}\n"
        f"Proposed Feature Requirement: {feature_description}\n\n"
        "Perform a thorough architectural scoping and risk analysis for this feature."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{GROQ_API_BASE}/chat/completions",
            headers=headers,
            json=payload
        )

        if resp.status_code != 200:
            logger.warning(f"Groq API returned status {resp.status_code}: {resp.text}")
            return None

        data = resp.json()
        raw_content = data["choices"][0]["message"]["content"].strip()

        # Clean code fence if wrapped
        if raw_content.startswith("```"):
            raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content)
            raw_content = re.sub(r"\s*```$", "", raw_content)

        parsed = json.loads(raw_content)

        feasibility = float(max(0.0, min(100.0, parsed.get("feasibility_score", 85.0))))
        complexity = float(max(0.0, min(100.0, parsed.get("complexity_score", 50.0))))
        risk = float(max(0.0, min(100.0, parsed.get("risk_score", 20.0))))
        confidence = float(max(0.0, min(100.0, parsed.get("confidence_score", 90.0))))

        analysis = parsed.get("analysis", "").strip()
        implementation_plan = parsed.get("implementation_plan", "").strip()

        return {
            "feasibility_score": round(feasibility, 1),
            "complexity_score": round(complexity, 1),
            "risk_score": round(risk, 1),
            "confidence_score": round(confidence, 1),
            "analysis": analysis,
            "implementation_plan": implementation_plan,
            "engine": f"Groq ({model})"
        }


def _dynamic_heuristic_analysis(
    feature_description: str,
    project_name: str,
    has_groq_key: bool
) -> Dict[str, Any]:
    """
    Intelligent semantic heuristic engine that analyzes the proposal keywords,
    domain scope, security surface, and technical complexity dynamically.
    Used when GROQ_API_KEY is not set or during API outages.
    """
    desc_lower = feature_description.lower()
    words = desc_lower.split()
    word_count = len(words)

    # 1. Domain category detection
    has_auth = any(k in desc_lower for k in ["auth", "oauth", "jwt", "login", "password", "session", "permission", "rbac", "token"])
    has_db = any(k in desc_lower for k in ["database", "postgres", "sql", "migration", "table", "schema", "redis", "cache", "model"])
    has_sec = any(k in desc_lower for k in ["crypto", "encryption", "firewall", "sandbox", "vulnerability", "audit", "security", "sanitize"])
    has_api = any(k in desc_lower for k in ["api", "rest", "endpoint", "webhook", "http", "graphql", "route", "grpc"])
    has_ui = any(k in desc_lower for k in ["ui", "frontend", "component", "page", "react", "css", "tailwind", "modal", "button", "view"])
    has_ai = any(k in desc_lower for k in ["ai", "llm", "agent", "groq", "gpt", "model", "prompt", "ast", "verify"])
    has_infra = any(k in desc_lower for k in ["docker", "k8s", "kubernetes", "deploy", "celery", "queue", "worker", "stream", "pipeline"])

    # 2. Dynamic scoring calculation
    base_feasibility = 92.0
    base_complexity = 35.0
    base_risk = 15.0
    base_confidence = 88.0

    # Adjust for scope length
    if word_count > 15:
        base_complexity += 8.0
        base_confidence += 4.0
    elif word_count < 4:
        base_confidence -= 10.0
        base_feasibility -= 5.0

    # Category-specific weighting
    if has_auth:
        base_complexity += 15.0
        base_risk += 25.0
        base_feasibility -= 4.0
    if has_sec:
        base_complexity += 18.0
        base_risk += 30.0
        base_feasibility -= 6.0
    if has_db:
        base_complexity += 12.0
        base_risk += 10.0
    if has_infra:
        base_complexity += 20.0
        base_risk += 18.0
        base_feasibility -= 8.0
    if has_ai:
        base_complexity += 14.0
        base_risk += 12.0
    if has_ui:
        base_feasibility += 5.0
        base_complexity += 8.0
    if has_api:
        base_complexity += 10.0

    feasibility = float(max(15.0, min(99.0, base_feasibility)))
    complexity = float(max(10.0, min(95.0, base_complexity)))
    risk = float(max(5.0, min(95.0, base_risk)))
    confidence = float(max(40.0, min(98.0, base_confidence)))

    # 3. Dynamic architectural assessment
    domains = []
    if has_auth: domains.append("Authentication & Identity")
    if has_sec: domains.append("Security & Cryptographic Guardrails")
    if has_db: domains.append("Persistence & State Migration")
    if has_api: domains.append("Public / Internal API Contracts")
    if has_infra: domains.append("Distributed Infrastructure")
    if has_ai: domains.append("AI / Verification Engine")
    if has_ui: domains.append("User Interface Presentation")

    domain_summary = ", ".join(domains) if domains else "Core Domain Logic"

    groq_note = (
        "[Notice: Evaluated via Sceptic Semantic Engine. Set GROQ_API_KEY in .env to enable Groq openai/gpt-oss-120b.]"
        if not has_groq_key else
        "[Notice: Groq inference temporarily unavailable; evaluated via Sceptic Semantic Engine.]"
    )

    analysis_text = (
        f"{groq_note}\n\n"
        f"Feature proposal '{feature_description}' evaluated for project '{project_name}'.\n"
        f"Impacted Subsystems: {domain_summary}.\n"
        f"• Architectural Alignment: The proposal demonstrates {feasibility:.0f}% structural feasibility against current services.\n"
        f"• Attack Surface & Security: Modeled at {risk:.0f}% risk. "
        + ("Requires rigorous CSRF, token entropy, and privilege isolation checks." if has_auth or has_sec else "Standard validation checks and input sanitization required.")
    )

    # 4. Tailored 4-phase implementation plan
    p1 = "1. Domain Modeling: Define data structures and schema definitions for " + feature_description + "."
    if has_db:
        p1 += " Generate and verify Alembic database migrations."
    
    p2 = "2. Backend Services: Implement service logic and API endpoints."
    if has_auth:
        p2 += " Implement secure token issuance and permission middleware."
    elif has_api:
        p2 += " Register REST endpoints with Pydantic contract validation."

    p3 = "3. Client & Presentation: Wire CLI handlers with Rich output and connect frontend dashboard views."
    if has_ui:
        p3 += " Design interactive React components with loading and error boundaries."

    p4 = "4. Verification & Testing: Author unit tests, integration test suites, and regression checks."
    if has_sec or has_auth:
        p4 += " Run automated security audits and token boundary test cases."

    plan_text = f"{p1}\n{p2}\n{p3}\n{p4}"

    return {
        "feasibility_score": round(feasibility, 1),
        "complexity_score": round(complexity, 1),
        "risk_score": round(risk, 1),
        "confidence_score": round(confidence, 1),
        "analysis": analysis_text,
        "implementation_plan": plan_text,
        "engine": "Semantic Heuristic Engine"
    }
