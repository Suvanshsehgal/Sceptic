"""
Computes the paper's tables from the stored runs of run_paper_eval.py, plus two baselines.

Detection rule (the same for every configuration):
- a seeded defect is caught only when an agent RESPONSIBLE for its category reports a finding of MEDIUM or higher:
  Fact-Checker for non-existent APIs, Security-Guard or Leak-Hunter for security defects, and Blind-Tester for
  specification mismatches, where the finding must also be an assertion failure from a generated test;
- a clean file is a false positive when ANY included agent reports a finding of MEDIUM or higher.
The responsible-agent rule matters: the Blind-Tester's fallback tests fail on almost every file, so crediting any agent
would hand it detections it is not responsible for and make the ablation meaningless.

Configurations are agent subsets of the same runs (ablation). Baselines are run here:
- build only: the file byte-compiles (what a build gate checks);
- Bandit only: one security scanner, as many pipelines run it (Bandit severity MEDIUM or HIGH counts).

Every configuration is scored per repeat. The tables report the mean and the sample standard deviation over repeats.

    python evaluation/analyze_paper_eval.py
"""
import json
import os
import py_compile
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
DATASET = os.path.join(HERE, "seeded_bugs")
HIGH = {"CRITICAL", "HIGH", "MEDIUM"}
ALL_AGENTS = ["Fact-Checker", "Blind-Tester", "Security-Guard", "Leak-Hunter", "Purana-Saman", "Jhooti-Docstring"]


def load(mode):
    path = os.path.join(RESULTS, f"paper_eval_{mode}.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


RESPONSIBLE = {
    "hallucinated_api": {"Fact-Checker"},
    "security": {"Security-Guard", "Leak-Hunter"},
    "spec_mismatch": {"Blind-Tester"},
}


def hits(run, agents):
    out = []
    for f in run["findings"]:
        if f["agent"] not in agents or f["severity"] not in HIGH:
            continue
        if run["kind"] == "bug":
            if f["agent"] not in RESPONSIBLE[run["category"]]:
                continue
            if run["category"] == "spec_mismatch" and not f["assertion_error"]:
                continue
        out.append(f)
    return out


def score_config(data, agents):
    """Per-repeat catch and false-positive counts for an agent subset."""
    per_repeat = {}
    for run in data["runs"]:
        slot = per_repeat.setdefault(run["repeat"], {"caught": 0, "bugs": 0, "fp": 0, "clean": 0, "seconds": []})
        found = bool(hits(run, agents))
        if run["kind"] == "bug":
            slot["bugs"] += 1
            slot["caught"] += int(found)
        else:
            slot["clean"] += 1
            slot["fp"] += int(found)
        slot["seconds"].append(run["seconds"])
    return per_repeat


def mean_sd(values):
    values = list(values)
    return (statistics.fmean(values), statistics.stdev(values) if len(values) > 1 else 0.0)


def summarize(per_repeat):
    catch = [r["caught"] / r["bugs"] * 100 for r in per_repeat.values()]
    fp = [r["fp"] / r["clean"] * 100 for r in per_repeat.values()]
    secs = [statistics.fmean(r["seconds"]) for r in per_repeat.values()]
    c, fpm, t = mean_sd(catch), mean_sd(fp), mean_sd(secs)
    return {
        "repeats": len(per_repeat),
        "catch_mean": round(c[0], 1), "catch_sd": round(c[1], 1),
        "fp_mean": round(fpm[0], 1), "fp_sd": round(fpm[1], 1),
        "seconds_mean": round(t[0], 2), "seconds_sd": round(t[1], 2),
        "caught_per_repeat": [r["caught"] for r in per_repeat.values()],
        "fp_per_repeat": [r["fp"] for r in per_repeat.values()],
    }


def baselines(manifest):
    """Build-only and Bandit-only, run once per file. They are deterministic, so their spread over repeats is zero."""
    build_hit, bandit_hit = {}, {}
    for case in manifest:
        path = os.path.join(DATASET, case["file"])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                py_compile.compile(path, cfile=os.path.join(tmp, "x.pyc"), doraise=True)
            build_hit[case["file"]] = False
        except py_compile.PyCompileError:
            build_hit[case["file"]] = True
        proc = subprocess.run([sys.executable, "-m", "bandit", "-q", "-f", "json", path], capture_output=True, text=True)
        try:
            issues = json.loads(proc.stdout or "{}").get("results", [])
        except ValueError:
            issues = []
        bandit_hit[case["file"]] = any(i.get("issue_severity", "").upper() in ("MEDIUM", "HIGH") for i in issues)
    out = {}
    for name, table in (("Build only", build_hit), ("Bandit only", bandit_hit)):
        bugs = [c for c in manifest if c["kind"] == "bug"]
        clean = [c for c in manifest if c["kind"] == "clean"]
        # Build only can catch any category (a file that does not compile). Bandit only counts on security defects,
        # because it is a security scanner, and a static tool cannot confirm a specification mismatch.
        caught = sum(table[c["file"]] for c in bugs if name == "Build only" or c["category"] == "security")
        fp = sum(table[c["file"]] for c in clean)
        out[name] = {"caught": caught, "bugs": len(bugs), "fp": fp, "clean": len(clean),
                     "catch_mean": round(caught / len(bugs) * 100, 1), "catch_sd": 0.0,
                     "fp_mean": round(fp / len(clean) * 100, 1), "fp_sd": 0.0}
    return out


def main():
    manifest = json.load(open(os.path.join(DATASET, "manifest.json"), encoding="utf-8"))["cases"]
    full, det = load("full"), load("deterministic")
    summary = {"configs": {}, "baselines": baselines(manifest)}

    if full:
        configs = {
            "Sceptic (all six agents)": ALL_AGENTS,
            "without Fact-Checker": [a for a in ALL_AGENTS if a != "Fact-Checker"],
            "without Blind-Tester": [a for a in ALL_AGENTS if a != "Blind-Tester"],
            "without Security-Guard": [a for a in ALL_AGENTS if a != "Security-Guard"],
            "three core agents only": ["Fact-Checker", "Blind-Tester", "Security-Guard"],
        }
        for name, agents in configs.items():
            summary["configs"][name] = summarize(score_config(full, agents))
        summary["llm"] = {
            "calls_per_audit": round(statistics.fmean(r["llm_calls"] for r in full["runs"]), 2),
            "failed_calls_total": sum(r["llm_failed"] for r in full["runs"]),
            "input_tokens_per_audit": round(statistics.fmean(r["input_tokens"] for r in full["runs"]), 1),
            "output_tokens_per_audit": round(statistics.fmean(r["output_tokens"] for r in full["runs"]), 1),
        }
    if det:
        summary["configs"]["Sceptic, no language model"] = summarize(score_config(det, ALL_AGENTS))

    out = os.path.join(RESULTS, "paper_summary.json")
    json.dump(summary, open(out, "w", encoding="utf-8"), indent=1)
    print(f"{'configuration':<32}{'catch % (mean ± SD)':<24}{'false pos. % (mean ± SD)':<26}{'s/audit'}")
    for name, s in {**summary["baselines"], **summary["configs"]}.items():
        sec = f"{s['seconds_mean']} ± {s['seconds_sd']}" if "seconds_mean" in s else "-"
        print(f"{name:<32}{s['catch_mean']:>5} ± {s['catch_sd']:<14}{s['fp_mean']:>5} ± {s['fp_sd']:<17}{sec}")
    print("written:", out)


if __name__ == "__main__":
    main()
