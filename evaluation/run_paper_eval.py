"""
Repeated audits of the seeded benchmark for the research paper.

Audits every file in evaluation/seeded_bugs/manifest.json (12 seeded defects, 15 clean files) with the real
AuditService, REPEATS times, and stores every agent's findings, timing and model usage. Ablations and baselines
are computed from these records by analyze_paper_eval.py, so each configuration sees exactly the same runs.

    python evaluation/run_paper_eval.py --mode full --repeats 3 --pace 15
    python evaluation/run_paper_eval.py --mode deterministic --repeats 3

--mode full            LLM agents on (Blind-Tester test generation, Security-Guard triage, docstring judge)
--mode deterministic   no model key: template tests, scanners and the signature check only
--pace N               seconds to wait between audits, to stay under the provider's tokens-per-minute limit

Blind-Tester runs in the Docker sandbox (SCEPTIC_SANDBOX=docker, the default), so Docker must be running.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in [ROOT, os.path.join(ROOT, "worker"), os.path.join(ROOT, "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

DATASET = os.path.join(HERE, "seeded_bugs")
RESULTS = os.path.join(HERE, "results")


def compact(findings):
    out = []
    for f in findings:
        evidence = str(f.get("evidence", ""))
        out.append({
            "agent": f.get("agent_name"),
            "severity": (f.get("severity") or "INFO").upper(),
            "status": (f.get("status") or "").upper(),
            "title": str(f.get("title", ""))[:120],
            "assertion_error": "AssertionError" in evidence,
        })
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "deterministic"), required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pace", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if args.mode == "deterministic":
        os.environ["GROQ_API_KEY"] = ""   # empty, not removed: load_dotenv would restore a removed key
    elif not os.getenv("GROQ_API_KEY"):
        raise SystemExit("--mode full needs GROQ_API_KEY")

    import audit_service
    from llm_client import METER
    from mcp_client import get_mcp_client

    def usage_now():
        local = METER.totals()
        remote = json.loads(get_mcp_client().call_tool("llm_usage", {}))
        return {k: local[k] + remote.get(k, 0) for k in local}

    with open(os.path.join(DATASET, "manifest.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"][: args.limit or None]

    service = audit_service.AuditService()
    runs = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            before = usage_now()
            started = time.perf_counter()
            report = service.audit_report(os.path.join(DATASET, case["file"]))
            seconds = time.perf_counter() - started
            after = usage_now()
            runs.append({
                "repeat": repeat,
                "file": case["file"],
                "kind": case["kind"],
                "category": case["category"],
                "expected_agent": case["expected_agent"],
                "seconds": round(seconds, 3),
                "trust_score": report.trust_score,
                "recommendation": report.recommendation,
                "agent_statuses": report.agent_statuses,
                "llm_calls": after["calls"] - before["calls"],
                "llm_failed": after["failed"] - before["failed"],
                "input_tokens": after["input_tokens"] - before["input_tokens"],
                "output_tokens": after["output_tokens"] - before["output_tokens"],
                "findings": compact(report.findings),
            })
            print(f"r{repeat} {case['file']:<40} {seconds:6.1f}s score={report.trust_score:<3} "
                  f"llm={runs[-1]['llm_calls']} failed={runs[-1]['llm_failed']}", flush=True)
            if args.pace:
                time.sleep(args.pace)

    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, f"paper_eval_{args.mode}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "mode": args.mode,
            "repeats": args.repeats,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "sandbox": os.getenv("SCEPTIC_SANDBOX", "docker"),
            "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "runs": runs,
        }, f, indent=1)
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
