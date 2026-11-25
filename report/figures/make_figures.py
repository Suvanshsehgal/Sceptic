"""
Regenerates every figure used in main.tex as a vector PDF (and a PNG preview).

    python make_figures.py

Needs only matplotlib. All numbers in the results chart come from the saved evaluation files in
evaluation/results/ (see the comments next to each value).
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon

HERE = os.path.dirname(os.path.abspath(__file__))

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

INK = "#1b1b1b"
LINE = "#3a3a3a"
FILL = "#ffffff"
SOFT = "#eef1f6"
GOOD = "#e3f1e6"
WARN = "#fbf0d6"
BAD = "#f7e0e0"
NOTE = "#f4f4f4"


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig, ax


def box(ax, x, y, w, h, text, fc=FILL, fs=7.6, bold=False, ec=LINE, ls="-", lw=1.0, rounded=True):
    style = "round,pad=0.0,rounding_size=1.2" if rounded else "square,pad=0"
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style, fc=fc, ec=ec, lw=lw, ls=ls))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", linespacing=1.25)
    return (x, y, w, h)


def diamond(ax, cx, cy, w, h, text, fc=SOFT, fs=7.2):
    ax.add_patch(Polygon([(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
                         closed=True, fc=fc, ec=LINE, lw=1.0))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color=INK, linespacing=1.2)


def arrow(ax, p, q, label=None, lpos=0.5, dx=0, dy=0, rad=0.0, ls="-", fs=6.8, color=LINE):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=9, lw=1.0, color=color,
                                 connectionstyle=f"arc3,rad={rad}", linestyle=ls, shrinkA=0, shrinkB=0))
    if label:
        mx = p[0] + (q[0] - p[0]) * lpos + dx
        my = p[1] + (q[1] - p[1]) * lpos + dy
        ax.text(mx, my, label, fontsize=fs, ha="center", va="center", color=INK,
                bbox=dict(fc="white", ec="none", pad=0.8))


def line(ax, pts, ls="-", color=LINE):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=1.0, ls=ls, solid_capstyle="butt")


def save(fig, name):
    fig.savefig(os.path.join(HERE, name + ".pdf"))
    fig.savefig(os.path.join(HERE, name + ".png"), dpi=130)
    plt.close(fig)
    print("wrote", name)


# ------------------------------------------------------------------ Figure 1: architecture
def architecture():
    fig, ax = canvas(7.2, 5.4)

    # band A: entry points, API, state, worker
    ax.text(9.5, 97.5, "Entry points", fontsize=8, fontweight="bold", ha="center")
    box(ax, 1, 82, 17, 11, "Git host\nPR webhook\n(HMAC-signed)", fs=7)
    box(ax, 1, 68, 17, 10, "CLI\n(Typer, Rich)", fs=7)
    box(ax, 1, 54, 17, 10, "Web dashboard\n(React, Vite)", fs=7)

    ax.text(36.5, 97.5, "Backend API", fontsize=8, fontweight="bold", ha="center")
    box(ax, 24, 56, 25, 37, "FastAPI\n\nJWT login, projects,\naudits, deployments,\nSSE progress,\nsigned webhooks", fc=SOFT, fs=7)

    ax.text(61.5, 97.5, "State", fontsize=8, fontweight="bold", ha="center")
    box(ax, 54, 78, 15, 15, "PostgreSQL\n(Alembic\nmigrations)", fs=7)
    box(ax, 54, 56, 15, 15, "Redis\n(Celery broker)", fs=7)

    ax.text(86.5, 97.5, "Celery worker", fontsize=8, fontweight="bold", ha="center")
    box(ax, 74, 56, 25, 37, "", fc=NOTE, ls="--", lw=0.8)
    box(ax, 77, 79, 19, 10, "Audit\norchestrator", fs=7)
    box(ax, 77, 60, 19, 10, "MCP tool server\n(stdio)", fs=7, fc=SOFT)
    arrow(ax, (86.5, 79), (86.5, 70))

    arrow(ax, (18, 87.5), (24, 85))
    arrow(ax, (18, 73), (24, 73))
    arrow(ax, (18, 59), (24, 62))
    arrow(ax, (49, 85), (54, 85))
    arrow(ax, (49, 63), (54, 63))
    arrow(ax, (69, 63), (74, 63))
    ax.text(71.5, 67.2, "tasks", fontsize=6.3, ha="center")

    # band B: post-deployment agents, alerts, tools
    box(ax, 24, 30, 25, 20, "Post-deployment agents\n\nWatchdog\nGatekeeper\nRollback", fc=SOFT, fs=7.2)
    arrow(ax, (36.5, 56), (36.5, 50))
    box(ax, 1, 32, 17, 16, "Alert channels\nSlack, Discord\n(HTTPS only)", fs=7)
    arrow(ax, (24, 40), (18, 40))

    box(ax, 52, 10, 47, 40, "", fc=NOTE, ls="--", lw=0.8)
    ax.text(75.5, 46.5, "Tools and services used by the worker", fontsize=8, fontweight="bold", ha="center")
    box(ax, 55, 29, 20, 12, "Docker sandbox\nno network,\nread-only", fc=WARN, fs=6.8)
    box(ax, 77, 29, 20, 12, "Scanners: Semgrep,\nBandit, Gitleaks,\npip-audit, OSV", fs=6.6)
    box(ax, 55, 13, 20, 12, "LLM provider\n(Groq)", fs=7)
    box(ax, 77, 13, 20, 12, "Langfuse\n(agent traces)", fs=7)
    arrow(ax, (86.5, 56), (86.5, 50))

    # band C: observed runtime
    ax.text(36, 24, "Observed runtime", fontsize=8, fontweight="bold", ha="center")
    box(ax, 6, 1, 22, 15, "Target service\n/health /version\n/metrics", fc=GOOD, fs=7)
    box(ax, 32, 1, 18, 15, "Prometheus\n(5 s scrape)", fs=7)
    box(ax, 54, 1, 16, 8, "Grafana", fs=7)
    arrow(ax, (29, 30), (17, 16), "probe", lpos=0.5, dx=-3, fs=6.4)
    arrow(ax, (44, 30), (41, 16), "PromQL", lpos=0.45, dx=5, fs=6.4)
    arrow(ax, (32, 8.5), (28, 8.5))
    ax.text(30, 4.2, "scrape", fontsize=6.4, ha="center")
    arrow(ax, (50, 5), (54, 5))
    save(fig, "architecture")


# ------------------------------------------------------------------ Figure 2: lifecycle mapping
def lifecycle():
    fig, ax = canvas(7.2, 4.2)
    w, h = 21.5, 34
    xs = [1.5, 26.5, 51.5, 76.5]
    top, bottom = 58, 8
    stages_top = [
        ("1. Plan", "Feature Scoper\nfeasibility, complexity\nand risk scores"),
        ("2. Code", "PR webhook, idempotent\nper repo, PR and commit\nCODEOWNERS on workflows"),
        ("3. Build", "Pinned, checksum-checked\nimages, immutable\ncommit-SHA tags (GHCR)"),
        ("4. Verify", "Fact-Checker, Blind-Tester,\nSecurity-Guard, Leak-Hunter,\nPurana-Saman, Jhooti-Docstring"),
    ]
    stages_bottom = [
        ("8. Recover", "Rollback Agent\nfive pre-flight checks,\nper-project lock"),
        ("7. Monitor", "Watchdog (health, error\nrate, p95) and Gatekeeper\n(commit, version, drift)"),
        ("6. Deploy", "Compose stack, deployment\nrecord, /health and\n/version verification"),
        ("5. Release gate", "Trust score 0-100\nAPPROVE | REQUEST_CHANGES\n| BLOCK, named override"),
    ]
    for i, (t, d) in enumerate(stages_top):
        box(ax, xs[i], top, w, h, "", fc=SOFT if i < 3 else GOOD)
        ax.text(xs[i] + w / 2, top + h - 5, t, fontsize=8.6, fontweight="bold", ha="center")
        ax.text(xs[i] + w / 2, top + h / 2 - 3, d, fontsize=6.9, ha="center", va="center", linespacing=1.3)
    for i, (t, d) in enumerate(stages_bottom):
        x = xs[i]
        box(ax, x, bottom, w, h, "", fc=SOFT if i > 0 else BAD)
        ax.text(x + w / 2, bottom + h - 5, t, fontsize=8.6, fontweight="bold", ha="center")
        ax.text(x + w / 2, bottom + h / 2 - 3, d, fontsize=6.9, ha="center", va="center", linespacing=1.3)
    for i in range(3):
        arrow(ax, (xs[i] + w, top + h / 2), (xs[i + 1], top + h / 2))
    for i in range(3):
        arrow(ax, (xs[i + 1], bottom + h / 2), (xs[i] + w, bottom + h / 2))
    arrow(ax, (xs[3] + w / 2, top), (xs[3] + w / 2, bottom + h))
    arrow(ax, (xs[0] + w / 2, bottom + h), (xs[0] + w / 2, top), "findings and rollback\nrecords feed the next plan", lpos=0.5, dx=0, fs=6.4)
    ax.text(50, 3, "Prometheus and Grafana observe stages 6 to 8. Langfuse traces the agents in stages 1 and 4.",
            fontsize=7, ha="center", style="italic")
    save(fig, "lifecycle")


# ------------------------------------------------------------------ Figure 3: pre-deployment audit
def audit_workflow():
    fig, ax = canvas(7.0, 6.4)
    box(ax, 30, 92, 40, 7, "Source: PR webhook, CLI path or CI step")
    box(ax, 27, 80, 46, 8, "File discovery, language detection\nand specification extraction")
    arrow(ax, (50, 92), (50, 88))
    # fan out region
    box(ax, 6, 40, 88, 36, "", fc=NOTE, ls="--", lw=0.8)
    ax.text(50, 73, "Fan-out: independent verification agents (no agent sees another agent's findings)",
            fontsize=7.6, fontweight="bold", ha="center")
    arrow(ax, (50, 80), (50, 76))
    row_y = [57, 44]
    names = [
        ("Fact-Checker", "API existence and\nsignatures (AST, tsc, javac)", FILL),
        ("Security-Guard", "Semgrep and Bandit,\nthen LLM triage", FILL),
        ("Blind-Tester", "tests from the docstring only,\nrun in the Docker sandbox", WARN),
        ("Leak-Hunter", "committed secrets\n(Gitleaks, redacted)", FILL),
        ("Purana-Saman", "dependency CVEs (pip-audit,\nnpm audit, OSV-Scanner)", FILL),
        ("Jhooti-Docstring", "docstring vs behaviour\n(LLM judge)", FILL),
    ]
    for i, (n, d, fc) in enumerate(names):
        r, c = divmod(i, 3)
        x = 9 + c * 28.5
        y = row_y[r]
        box(ax, x, y, 26, 11, "", fc=fc)
        ax.text(x + 13, y + 8, n, fontsize=7.8, fontweight="bold", ha="center")
        ax.text(x + 13, y + 3.6, d, fontsize=6.5, ha="center", va="center", linespacing=1.25)
    arrow(ax, (50, 40), (50, 35))
    box(ax, 22, 27, 56, 8, "Shared AuditContext: findings, agent statuses, execution log", fc=SOFT)
    arrow(ax, (50, 27), (50, 22))
    box(ax, 14, 13, 72, 9, "Synthesizer: score = 100 - sum of severity penalties (35, 20, 10, 3),\nunverified checks share one capped penalty (15)", fc=SOFT, fs=7.2)
    # outcomes
    outs = [
        (3, "APPROVE\nscore 85-100\ndeploy may proceed", GOOD),
        (36, "REQUEST_CHANGES\nscore 65-84\nfix, then re-audit", WARN),
        (69, "BLOCK\nscore 0-64\nno deployment", BAD),
    ]
    for x, t, fc in outs:
        box(ax, x, 1, 28, 8.5, t, fc=fc, fs=7)
        arrow(ax, (x + 14, 13), (x + 14, 9.5))
    ax.text(50, 11, "", fontsize=6)
    save(fig, "audit_workflow")


# ------------------------------------------------------------------ Figure 4: deploy and recover
def deploy_recover():
    fig, ax = canvas(7.2, 5.2)
    # row 1: deploy
    ax.text(50, 98, "Release and verification", fontsize=8, fontweight="bold", ha="center")
    diamond(ax, 11, 82, 20, 20, "Verdict\nAPPROVE?")
    box(ax, 25, 75, 19, 14, "Register deployment\nstatus DEPLOYING")
    box(ax, 47, 75, 17, 14, "Poll /health and\n/version until timeout", fs=7.2)
    diamond(ax, 79, 82, 22, 20, "healthy and\ncommit matches?")
    box(ax, 91, 75, 8.5, 14, "ACTIVE", fc=GOOD, fs=7)
    box(ax, 66, 54, 26, 11, "FAILED (recorded,\nno automatic rollback)", fc=BAD, fs=7)
    box(ax, 0.5, 54, 24, 14, "Blocked. Override needs\na named approver and a\nreason of 10+ characters", fc=BAD, fs=6.8)
    arrow(ax, (21, 82), (25, 82), "yes", dy=3)
    arrow(ax, (44, 82), (47, 82))
    arrow(ax, (64, 82), (66, 82))
    arrow(ax, (88, 82), (91, 82), "yes", dy=-4.5, dx=-0.5)
    arrow(ax, (11, 72), (11, 68), "no", dx=3)
    arrow(ax, (77, 72), (77, 65), "no", dx=3)

    # row 2: monitor and recover
    ax.text(50, 44, "Runtime protection", fontsize=8, fontweight="bold", ha="center")
    box(ax, 80, 22, 19, 16, "Watchdog: health,\nerror rate, p95\nGatekeeper: commit,\nversion, drift", fs=6.8, fc=SOFT)
    arrow(ax, (95, 75), (95, 38))
    diamond(ax, 62, 30, 22, 16, "finding\nFAIL?")
    arrow(ax, (80, 30), (73, 30))
    ax.text(62, 17, "no: keep polling", fontsize=6.6, ha="center", style="italic")
    diamond(ax, 36, 30, 26, 20, "five pre-flight\nchecks pass?")
    arrow(ax, (51, 30), (49, 30), "yes", dy=4, lpos=0.0, dx=-1)
    box(ax, 1, 21, 20, 18, "Take project lock,\nrun ROLLBACK_COMMAND,\nverify /health and\ncommit SHA", fs=6.8, fc=SOFT)
    arrow(ax, (23, 30), (21, 30))
    box(ax, 14, 2, 16, 10, "SUCCESS:\nprior version ACTIVE", fc=GOOD, fs=6.8)
    box(ax, 33, 2, 16, 10, "ABORTED:\nnothing changed", fc=WARN, fs=6.8)
    arrow(ax, (11, 21), (22, 12))
    arrow(ax, (36, 20), (41, 12), "no", dx=-3.5, dy=0.5)
    ax.text(70, 11, "If the post-rollback check fails, the record is FAILED\nand the incident is escalated to a person.",
            fontsize=6.6, ha="left", va="center", style="italic")
    save(fig, "deploy_recover")


# ------------------------------------------------------------------ Figure 5: measured results
def results():
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.5))
    fig.subplots_adjust(left=0.07, right=0.99, top=0.87, bottom=0.24, wspace=0.55)
    dark, mid, light = "#2f3b4d", "#7d8da6", "#c9d1de"

    # (a) detection by category: evaluation/results/seeded_bugs_latest.json
    ax = axes[0]
    cats = ["Hallucinated\nAPI", "Spec\nmismatch", "Security"]
    caught = [4, 1, 4]
    total = [4, 3, 5]
    ax.bar(range(3), total, color=light, edgecolor=LINE, lw=0.8, label="seeded")
    ax.bar(range(3), caught, color=dark, edgecolor=LINE, lw=0.8, label="caught")
    for i, (c, t) in enumerate(zip(caught, total)):
        ax.text(i, t + 0.12, f"{c}/{t}", ha="center", fontsize=7.5)
    ax.set_xticks(range(3))
    ax.set_xticklabels(cats, fontsize=7)
    ax.set_ylim(0, 7.6)
    ax.set_ylabel("seeded bugs", fontsize=7.5)
    ax.set_title("(a) Gate detection", fontsize=8.2)
    ax.legend(fontsize=6.5, frameon=False, loc="upper right", ncol=2)

    # (b) guardrails, held-out: guardrail_heldout_patterns.json, guardrail_heldout_classifier.json
    ax = axes[1]
    labels = ["Patterns\nonly", "Patterns +\nclassifier"]
    blocked = [33.3, 86.7]
    falseb = [10.0, 10.0]
    xs = [0, 1]
    ax.bar([x - 0.18 for x in xs], blocked, width=0.34, color=dark, edgecolor=LINE, lw=0.8, label="attacks blocked")
    ax.bar([x + 0.18 for x in xs], falseb, width=0.34, color=mid, edgecolor=LINE, lw=0.8, label="benign blocked")
    for x, b, f in zip(xs, blocked, falseb):
        ax.text(x - 0.18, b + 2, f"{b:.0f}%", ha="center", fontsize=7)
        ax.text(x + 0.18, f + 2, f"{f:.0f}%", ha="center", fontsize=7)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylim(0, 112)
    ax.set_ylabel("held-out inputs (%)", fontsize=7.5)
    ax.set_title("(b) Input guardrail", fontsize=8.2)
    ax.legend(fontsize=6.3, frameon=False, loc="upper left")

    # (c) audit wall time: perf_deterministic_latest.json (27 audits), perf_full_latest.json (8 audits)
    ax = axes[2]
    labels = ["No LLM\n(27 audits)", "With LLM\n(8 audits)"]
    p50 = [4.797, 8.84]
    p95 = [4.954, 11.102]
    ax.bar([x - 0.18 for x in xs], p50, width=0.34, color=dark, edgecolor=LINE, lw=0.8, label="median")
    ax.bar([x + 0.18 for x in xs], p95, width=0.34, color=mid, edgecolor=LINE, lw=0.8, label="95th percentile")
    for x, a, b in zip(xs, p50, p95):
        ax.text(x - 0.18, a + 0.25, f"{a:.1f}", ha="center", fontsize=7)
        ax.text(x + 0.18, b + 0.25, f"{b:.1f}", ha="center", fontsize=7)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylim(0, 14.5)
    ax.set_ylabel("seconds per audit", fontsize=7.5)
    ax.set_title("(c) Audit time", fontsize=8.2)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")

    for a in axes:
        a.spines["top"].set_visible(False)
        a.spines["right"].set_visible(False)
        a.tick_params(axis="y", labelsize=7)
    save(fig, "results")


def results_paper():
    """Fig: catch rate and false-positive rate (mean and sample SD over 3 repeats) per configuration.
    Reads evaluation/results/paper_summary.json, written by evaluation/analyze_paper_eval.py."""
    import json
    path = os.path.join(HERE, "..", "..", "evaluation", "results", "paper_summary.json")
    summary = json.load(open(path, encoding="utf-8"))
    rows = {}
    rows.update(summary["baselines"])
    rows.update(summary["configs"])
    order = ["Build only", "Bandit only", "Sceptic, no language model", "three core agents only",
             "without Fact-Checker", "without Blind-Tester", "without Security-Guard", "Sceptic (all six agents)"]
    labels = {"Build only": "Build only (baseline)", "Bandit only": "Bandit only (baseline)",
              "Sceptic, no language model": "Sceptic, no model",
              "three core agents only": "Three core agents",
              "without Fact-Checker": "All, minus Fact-Checker", "without Blind-Tester": "All, minus Blind-Tester",
              "without Security-Guard": "All, minus Security-Guard", "Sceptic (all six agents)": "Sceptic, all six agents"}
    order = [k for k in order if k in rows]
    dark, mid = "#2f3b4d", "#7d8da6"

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    fig.subplots_adjust(left=0.27, right=0.985, top=0.88, bottom=0.17, wspace=0.08)
    ys = list(range(len(order)))[::-1]
    for ax, key, title, color in ((axes[0], "catch", "(a) Seeded defects caught (%)", dark),
                                  (axes[1], "fp", "(b) Clean files flagged (%)", mid)):
        means = [rows[k][f"{key}_mean"] for k in order]
        sds = [rows[k][f"{key}_sd"] for k in order]
        ax.barh(ys, means, xerr=sds, color=color, edgecolor=LINE, lw=0.8, height=0.62,
                error_kw=dict(ecolor="#111111", lw=0.9, capsize=2.5))
        for y, m, s in zip(ys, means, sds):
            ax.text(min(m + s + 2.5, 104), y, f"{m:.0f}" if s == 0 else f"{m:.0f}±{s:.0f}", va="center", fontsize=6.6)
        ax.set_xlim(0, 118)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xlabel("percent of files (mean ± SD, 3 repeats)", fontsize=7)
        ax.set_title(title, fontsize=8.2)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="x", labelsize=7)
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([labels[k] for k in order], fontsize=7)
    save(fig, "results")


def cost_paper():
    """Fig: (a) audit time by mode, (b) guardrail stages on the held-out set."""
    import json
    path = os.path.join(HERE, "..", "..", "evaluation", "results", "paper_summary.json")
    summary = json.load(open(path, encoding="utf-8"))
    cfg = summary["configs"]
    dark, mid = "#2f3b4d", "#7d8da6"
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.5))
    fig.subplots_adjust(left=0.08, right=0.99, top=0.87, bottom=0.25, wspace=0.34)

    ax = axes[0]
    names = [("Sceptic, no language model", "No model"), ("Sceptic (all six agents)", "With model")]
    names = [(k, l) for k, l in names if k in cfg]
    ms = [cfg[k]["seconds_mean"] for k, _ in names]
    sd = [cfg[k]["seconds_sd"] for k, _ in names]
    ax.bar(range(len(names)), ms, yerr=sd, color=[mid, dark][: len(names)], edgecolor=LINE, lw=0.8, width=0.5,
           error_kw=dict(ecolor="#111111", lw=0.9, capsize=3))
    for i, (m, s) in enumerate(zip(ms, sd)):
        ax.text(i, m + s + 0.4, f"{m:.1f} ± {s:.1f}", ha="center", fontsize=7)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([l for _, l in names], fontsize=7.5)
    ax.set_ylabel("seconds per audit", fontsize=7.5)
    ax.set_ylim(0, max(ms) * 1.5)
    ax.set_title("(a) Audit time (mean ± SD, 3 repeats)", fontsize=8.2)

    ax = axes[1]
    labels = ["Patterns only", "Patterns + classifier"]
    blocked = [33.3, 86.7]     # evaluation/results/guardrail_heldout_patterns.json, guardrail_heldout_classifier.json
    falseb = [10.0, 10.0]
    xs = [0, 1]
    ax.bar([x - 0.18 for x in xs], blocked, width=0.34, color=dark, edgecolor=LINE, lw=0.8, label="attacks blocked")
    ax.bar([x + 0.18 for x in xs], falseb, width=0.34, color=mid, edgecolor=LINE, lw=0.8, label="benign blocked")
    for x, b, f in zip(xs, blocked, falseb):
        ax.text(x - 0.18, b + 2, f"{b:.0f}", ha="center", fontsize=7)
        ax.text(x + 0.18, f + 2, f"{f:.0f}", ha="center", fontsize=7)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylim(0, 118)
    ax.set_ylabel("percent of held-out inputs", fontsize=7.5)
    ax.set_title("(b) Input guardrail ablation", fontsize=8.2)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")
    for a in axes:
        a.spines["top"].set_visible(False)
        a.spines["right"].set_visible(False)
        a.tick_params(axis="y", labelsize=7)
    save(fig, "cost")


if __name__ == "__main__":
    architecture()
    lifecycle()
    audit_workflow()
    deploy_recover()
    results_paper()
    cost_paper()
