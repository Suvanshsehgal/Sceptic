"""
Seeded-bug evaluation for the Sceptic pipeline.

Audits every file listed in evaluation/seeded_bugs/manifest.json with the real AuditService (Fact-Checker,
Blind-Tester in the sandbox, Security-Guard) and reports:
- catch rate: seeded bugs where the expected agent reports a MEDIUM-or-higher finding
- false-positive rate: clean controls where any agent reports a MEDIUM-or-higher finding

Usage (from the repository root):
    python evaluation/run_seeded_eval.py
Blind-Tester uses the sandbox selected by SCEPTIC_SANDBOX (default: docker). Results are written to
evaluation/results/seeded_bugs_<UTC timestamp>.json and evaluation/results/seeded_bugs_latest.json.
"""
import os
import sys
import json
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in [ROOT, os.path.join(ROOT, "worker"), os.path.join(ROOT, "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))

from audit_service import AuditService  # noqa: E402

MIN_REPORTED_SEVERITY = {"CRITICAL", "HIGH", "MEDIUM"}
DATASET_DIR = os.path.join(HERE, "seeded_bugs")
RESULTS_DIR = os.path.join(HERE, "results")


def is_reported(finding: dict) -> bool:
    return (finding.get("severity") or "").upper() in MIN_REPORTED_SEVERITY


def evaluate_case(service: AuditService, case: dict) -> dict:
    path = os.path.join(DATASET_DIR, case["file"])
    report = service.audit_path(path)
    findings = report.get("findings", [])
    reported = [f for f in findings if is_reported(f)]

    if case["kind"] == "bug":
        matching = [f for f in reported if f.get("agent_name") == case["expected_agent"]]
        if case["expected_agent"] == "Blind-Tester":
            # A specification bug is caught only when a generated test fails an assertion.
            # Crashes (TypeError, ZeroDivisionError) are not evidence about the specification.
            matching = [f for f in matching if "AssertionError" in str(f.get("evidence", ""))]
        caught = bool(matching)
        evidence = matching[0] if matching else None
    else:
        caught = False
        evidence = None

    false_positive = case["kind"] == "clean" and bool(reported)
    return {
        "file": case["file"],
        "kind": case["kind"],
        "category": case["category"],
        "expected_agent": case["expected_agent"],
        "caught": caught,
        "false_positive": false_positive,
        "trust_score": report.get("trust_score"),
        "recommendation": report.get("recommendation"),
        "agent_statuses": report.get("agent_statuses"),
        "reported_findings": [
            {"agent": f.get("agent_name"), "severity": f.get("severity"), "title": f.get("title")}
            for f in reported
        ],
        "evidence": (
            {"title": evidence.get("title"), "severity": evidence.get("severity"), "detail": str(evidence.get("evidence"))[:300]}
            if evidence else None
        ),
    }


def summarize(results: list) -> dict:
    bugs = [r for r in results if r["kind"] == "bug"]
    clean = [r for r in results if r["kind"] == "clean"]
    by_category = defaultdict(lambda: {"seeded": 0, "caught": 0})
    for r in bugs:
        by_category[r["category"]]["seeded"] += 1
        by_category[r["category"]]["caught"] += int(r["caught"])
    caught = sum(r["caught"] for r in bugs)
    fps = sum(r["false_positive"] for r in clean)
    return {
        "seeded_bugs": len(bugs),
        "caught": caught,
        "catch_rate": round(caught / len(bugs), 3) if bugs else None,
        "clean_controls": len(clean),
        "false_positives": fps,
        "false_positive_rate": round(fps / len(clean), 3) if clean else None,
        "by_category": {k: {**v, "catch_rate": round(v["caught"] / v["seeded"], 3)} for k, v in by_category.items()},
    }


def main() -> int:
    with open(os.path.join(DATASET_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    service = AuditService()
    results = []
    for case in manifest["cases"]:
        print(f"auditing {case['file']} ...", flush=True)
        results.append(evaluate_case(service, case))

    summary = summarize(results)
    output = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "sandbox_mode": os.getenv("SCEPTIC_SANDBOX", "docker"),
        "groq_enabled": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "summary": summary,
        "results": results,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RESULTS_DIR, f"seeded_bugs_{stamp}.json")
    for target in (path, os.path.join(RESULTS_DIR, "seeded_bugs_latest.json")):
        with open(target, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

    print()
    print(f"{'case':<42}{'kind':<7}{'result':<22}{'agents reporting MEDIUM+'}")
    for r in results:
        if r["kind"] == "bug":
            verdict = "CAUGHT" if r["caught"] else "MISSED"
        else:
            verdict = "FALSE POSITIVE" if r["false_positive"] else "clean"
        agents = ", ".join(sorted({f["agent"] for f in r["reported_findings"]})) or "-"
        print(f"{r['file']:<42}{r['kind']:<7}{verdict:<22}{agents}")
    print()
    print(json.dumps(summary, indent=2))
    print(f"\nWritten: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
