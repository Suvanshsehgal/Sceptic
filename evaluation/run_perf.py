"""
Performance, time and cost evaluation (Phase E).

Audits every file in evaluation/seeded_bugs/manifest.json with the real AuditService, and reports:
- wall time per audit (p50, p95, mean) and per agent (mean, p95), measured around the real agent calls
- LLM calls and tokens per audit, read from the always-on usage meter in worker/llm_client.py
- cost per audit and per 1,000 audits, from the token counts and a per-million-token price

Two modes:
  --mode full                LLM agents on (needs GROQ_API_KEY; uses daily quota)
  --mode deterministic       no LLM key: Fact-Checker, Security scanners, Leak-Hunter and Purana-Saman only

Blind-Tester needs the Docker sandbox. Without Docker it fails closed in a few milliseconds, and that is what the
timing shows, so it is reported as "unavailable", not as a measured agent cost.

Prices are not read from the network. Pass --price-input and --price-output in USD per million tokens. The values in
the results file come from the command line, so they are auditable.

    python evaluation/run_perf.py --mode deterministic
    python evaluation/run_perf.py --mode full --price-input 0.15 --price-output 0.60 --repeats 1
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in [ROOT, os.path.join(ROOT, "worker"), os.path.join(ROOT, "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

DATASET_DIR = os.path.join(HERE, "seeded_bugs")
RESULTS_DIR = os.path.join(HERE, "results")


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


class AgentTimer:
    """Wraps the real agent entry points so that each call is timed. Thread-safe: target agents run in a pool."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self.samples = defaultdict(list)     # agent -> [seconds]
        self.errors = defaultdict(int)

    def wrap(self, agent, fn):
        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception:
                with self._lock:
                    self.errors[agent] += 1
                raise
            else:
                # Agents report an unavailable dependency (for example no Docker sandbox) as an ERROR finding.
                # That is an error for timing purposes too, so it is counted.
                if isinstance(result, list) and any(
                    isinstance(f, dict) and str(f.get("status") or "").upper() == "ERROR" for f in result
                ):
                    with self._lock:
                        self.errors[agent] += 1
                return result
            finally:
                with self._lock:
                    self.samples[agent].append(time.perf_counter() - start)
        return timed

    def install(self):
        import audit_service
        import orchestrator
        audit_service.run_leak_hunter = self.wrap("Leak-Hunter", audit_service.run_leak_hunter)
        audit_service.run_purana_saman = self.wrap("Purana-Saman", audit_service.run_purana_saman)
        audit_service.run_jhooti_docstring = self.wrap("Jhooti-Docstring", audit_service.run_jhooti_docstring)
        orchestrator.run_fact_checker = self.wrap("Fact-Checker", orchestrator.run_fact_checker)
        orchestrator.run_security_guard = self.wrap("Security-Guard", orchestrator.run_security_guard)
        orchestrator.run_blind_tester = self.wrap("Blind-Tester", orchestrator.run_blind_tester)

    def snapshot(self):
        with self._lock:
            return {agent: list(values) for agent, values in self.samples.items()}


def run(mode: str, repeats: int, price_in, price_out, cases_limit=None) -> dict:
    if mode == "deterministic":
        # Set to empty, not removed: the audit's imports call load_dotenv(), which would restore a removed key from .env.
        # load_dotenv does not override a variable that already exists, so an empty value stays empty.
        os.environ["GROQ_API_KEY"] = ""
    elif not os.getenv("GROQ_API_KEY"):
        raise SystemExit("--mode full needs GROQ_API_KEY in the environment or .env")

    import audit_service
    from llm_client import METER
    from audit_models import VERIFICATION_AGENTS  # noqa: F401  (import check)

    timer = AgentTimer()
    timer.install()
    service = audit_service.AuditService()

    with open(os.path.join(DATASET_DIR, "manifest.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"][: cases_limit or None]

    from mcp_client import get_mcp_client

    def usage_now():
        """LLM usage across both processes: this one (the classifier, the docstring judge) and the MCP tool server,
        where the agent LLM calls actually run."""
        local = METER.totals()
        remote = json.loads(get_mcp_client().call_tool("llm_usage", {}))
        return {key: local[key] + remote.get(key, 0) for key in local}

    audits = []
    started_all = time.perf_counter()
    for repeat in range(repeats):
        for case in cases:
            path = os.path.join(DATASET_DIR, case["file"])
            before = usage_now()
            before_agents = {k: len(v) for k, v in timer.snapshot().items()}
            t0 = time.perf_counter()
            report = service.audit_report(path)
            wall = time.perf_counter() - t0
            after = usage_now()
            after_agents = timer.snapshot()
            per_agent = {}
            for agent, values in after_agents.items():
                new = values[before_agents.get(agent, 0):]
                if new:
                    per_agent[agent] = round(sum(new), 4)
            in_tokens = after["input_tokens"] - before["input_tokens"]
            out_tokens = after["output_tokens"] - before["output_tokens"]
            audits.append({
                "file": case["file"], "kind": case["kind"], "repeat": repeat,
                "wall_seconds": round(wall, 4),
                "trust_score": report.trust_score,
                "recommendation": report.recommendation,
                "findings": report.total_findings,
                "incomplete": len(report.incomplete_reasons),
                "llm_calls": after["calls"] - before["calls"],
                "llm_failed_calls": after["failed"] - before["failed"],
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "agent_seconds": per_agent,
            })
            print(f"  {case['file']:<40} {wall:7.2f}s  score={report.trust_score:<3} "
                  f"llm_calls={audits[-1]['llm_calls']}", flush=True)
    total_wall = time.perf_counter() - started_all

    walls = [a["wall_seconds"] for a in audits]
    n = len(audits)
    total_in = sum(a["input_tokens"] for a in audits)
    total_out = sum(a["output_tokens"] for a in audits)
    cost_per_audit = None
    if price_in is not None and price_out is not None and n:
        cost_per_audit = (total_in * price_in + total_out * price_out) / 1_000_000 / n

    agent_stats = {}
    for agent, values in timer.snapshot().items():
        agent_stats[agent] = {
            "calls": len(values),
            "errors": timer.errors.get(agent, 0),
            "mean_seconds": round(statistics.fmean(values), 4),
            "p95_seconds": round(percentile(values, 95), 4),
        }
    unavailable = [agent for agent, stats in agent_stats.items() if stats["errors"] and stats["errors"] == stats["calls"]]

    return {
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases),
        "repeats": repeats,
        "audits": n,
        "wall_seconds": {
            "total": round(total_wall, 2),
            "p50": round(percentile(walls, 50), 3),
            "p95": round(percentile(walls, 95), 3),
            "mean": round(statistics.fmean(walls), 3),
            "max": round(max(walls), 3),
        },
        "agents": agent_stats,
        "agents_unavailable_in_this_run": unavailable,
        "llm": {
            "calls_total": sum(a["llm_calls"] for a in audits),
            "failed_total": sum(a["llm_failed_calls"] for a in audits),
            "calls_per_audit": round(sum(a["llm_calls"] for a in audits) / n, 2) if n else None,
            "input_tokens_total": total_in,
            "output_tokens_total": total_out,
            "input_tokens_per_audit": round(total_in / n, 1) if n else None,
            "output_tokens_per_audit": round(total_out / n, 1) if n else None,
        },
        "cost": {
            "price_input_per_million_usd": price_in,
            "price_output_per_million_usd": price_out,
            "cost_per_audit_usd": round(cost_per_audit, 6) if cost_per_audit is not None else None,
            "cost_per_1000_audits_usd": round(cost_per_audit * 1000, 2) if cost_per_audit is not None else None,
        },
        "audits_detail": audits,
    }


def markdown(result: dict) -> str:
    w = result["wall_seconds"]
    lines = [
        f"## Performance run: {result['mode']} mode",
        "",
        f"- Audits: {result['audits']} ({result['cases']} files x {result['repeats']} repeat(s))",
        f"- Wall time per audit: p50 {w['p50']} s, p95 {w['p95']} s, mean {w['mean']} s, max {w['max']} s",
        f"- Total run time: {w['total']} s",
        f"- LLM calls per audit: {result['llm']['calls_per_audit']} (failed in total: {result['llm']['failed_total']})",
        f"- Tokens per audit: {result['llm']['input_tokens_per_audit']} in, {result['llm']['output_tokens_per_audit']} out",
    ]
    c = result["cost"]
    if c["cost_per_audit_usd"] is not None:
        lines.append(
            f"- Cost per audit: ${c['cost_per_audit_usd']:.6f} "
            f"(${c['price_input_per_million_usd']}/M in, ${c['price_output_per_million_usd']}/M out); "
            f"per 1,000 audits: ${c['cost_per_1000_audits_usd']:.2f}"
        )
    else:
        lines.append("- Cost per audit: not computed (pass --price-input and --price-output)")
    lines += ["", "| Agent | Calls | Errors | Mean s | p95 s |", "| --- | --- | --- | --- | --- |"]
    for agent, s in sorted(result["agents"].items()):
        lines.append(f"| {agent} | {s['calls']} | {s['errors']} | {s['mean_seconds']} | {s['p95_seconds']} |")
    if result["agents_unavailable_in_this_run"]:
        lines.append("")
        lines.append("Unavailable in this run (every call failed): " + ", ".join(result["agents_unavailable_in_this_run"]))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Performance, time and cost evaluation of the Sceptic audit.")
    parser.add_argument("--mode", choices=("full", "deterministic"), default="deterministic")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="audit only the first N manifest files")
    parser.add_argument("--price-input", type=float, default=None, help="USD per 1M input tokens")
    parser.add_argument("--price-output", type=float, default=None, help="USD per 1M output tokens")
    args = parser.parse_args(argv)

    print(f"mode={args.mode} repeats={args.repeats}", flush=True)
    result = run(args.mode, args.repeats, args.price_input, args.price_output, args.limit)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"perf_{args.mode}_latest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print()
    print(markdown(result))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
