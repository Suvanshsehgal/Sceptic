"""
Guardrail evaluation: measures the input guard on evaluation/guardrail_cases.json.

Reports the block rate on attacks (higher is better) and the false-block rate on benign text (lower is better),
with every miss listed so the weak spots are visible. Results are written to evaluation/results/guardrail_latest.json.

    python evaluation/run_guardrail_eval.py
"""
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "worker"))

import guardrails  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass


def run(cases_path: str = os.path.join(HERE, "guardrail_cases.json"), use_classifier: bool = False) -> dict:
    """Scores one case file. Use guardrail_cases_heldout.json for the unbiased figure (patterns were tuned on the first)."""
    with open(cases_path, encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    rows = []
    started = time.perf_counter()
    for case in cases:
        verdict = guardrails.inspect_input(case["text"], case["kind"], use_classifier=use_classifier)
        blocked = not verdict.allowed
        expected_block = case["expect"] == "block"
        rows.append({
            "id": case["id"], "category": case["category"], "expect": case["expect"],
            "blocked": blocked, "correct": blocked == expected_block, "reasons": verdict.reasons,
        })
    elapsed_ms = (time.perf_counter() - started) * 1000
    classifier_status = "not requested"
    if use_classifier:
        classifier_status = "ok" if not guardrails._classifier_state["unavailable_reason"] else (
            "unavailable: " + guardrails._classifier_state["unavailable_reason"])

    attacks = [r for r in rows if r["expect"] == "block"]
    benign = [r for r in rows if r["expect"] == "allow"]
    caught = sum(1 for r in attacks if r["blocked"])
    false_blocks = sum(1 for r in benign if r["blocked"])
    by_category = {}
    for cat in sorted({r["category"] for r in attacks}):
        group = [r for r in attacks if r["category"] == cat]
        by_category[cat] = {"caught": sum(1 for r in group if r["blocked"]), "total": len(group)}

    return {
        "attacks": len(attacks),
        "attacks_blocked": caught,
        "block_rate": round(caught / len(attacks), 3) if attacks else None,
        "benign": len(benign),
        "benign_blocked": false_blocks,
        "false_block_rate": round(false_blocks / len(benign), 3) if benign else None,
        "by_category": by_category,
        "missed_attacks": [r["id"] for r in attacks if not r["blocked"]],
        "false_blocks": [r["id"] for r in benign if r["blocked"]],
        "mean_check_ms": round(elapsed_ms / max(1, len(rows)), 3),
        "classifier_status": classifier_status,
        "rows": rows,
    }


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Measures the Sceptic input guardrail on a labelled case file.")
    parser.add_argument("--cases", default=os.path.join(HERE, "guardrail_cases.json"))
    parser.add_argument("--classifier", action="store_true", help="also run the Prompt Guard 2 stage (needs GROQ_API_KEY)")
    parser.add_argument("--out", default=os.path.join(HERE, "results", "guardrail_latest.json"))
    args = parser.parse_args(argv)
    result = run(args.cases, use_classifier=args.classifier)
    result["stages"] = "patterns+classifier" if args.classifier else "patterns"
    result["cases_file"] = os.path.basename(args.cases)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"stages:            {result['stages']} on {result['cases_file']}")
    print(f"classifier:        {result['classifier_status']}")
    print(f"attacks blocked:   {result['attacks_blocked']}/{result['attacks']} ({result['block_rate']:.0%})")
    print(f"benign blocked:    {result['benign_blocked']}/{result['benign']} ({result['false_block_rate']:.0%})")
    print(f"missed attacks:    {result['missed_attacks'] or 'none'}")
    print(f"false blocks:      {result['false_blocks'] or 'none'}")
    print(f"mean check time:   {result['mean_check_ms']} ms per input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
