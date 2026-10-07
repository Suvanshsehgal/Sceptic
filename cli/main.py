import os
import sys
import json
from pathlib import Path
from typing import Optional

# Ensure root and worker modules are available
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from audit_service import AuditService

app = typer.Typer(
    name="sceptic",
    help="Sceptic: Independent AI-Generated Code Verification System",
    add_completion=False,
    no_args_is_help=True
)
console = Console()

@app.callback()
def main_callback():
    """
    Sceptic CLI: Independent AI-generated code verification.
    """
    pass

EXIT_SUCCESS = 0
EXIT_AUDIT_FAILURE = 1
EXIT_CLI_ERROR = 2

@app.command(name="audit")
def audit(
    path: str = typer.Argument(
        ...,
        help="Path to source file or directory to audit."
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed findings and evidence."
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON results without Rich formatting."
    )
):
    """
    Run full in-process Sceptic code verification against a target file or project.
    """
    service = AuditService()

    if not json_output:
        header_text = Text()
        header_text.append("SCEPTIC ", style="bold cyan")
        header_text.append("Code Verification System - CLI\n", style="bold white")
        header_text.append("Independent AI-Generated Code Auditing", style="dim white")
        console.print(Panel(header_text, border_style="cyan"))
        console.print(f"[bold]Target:[/bold] [underline]{path}[/underline]\n")

    try:
        # Execute audit with live spinner progress
        if not json_output:
            with console.status("[bold green]Executing verification agents in-process...[/bold green]", spinner="dots") as status:
                def progress_cb(stage: str, msg: str):
                    status.update(f"[bold green]{msg}[/bold green]")

                report = service.audit_path(path, progress_callback=progress_cb)
        else:
            report = service.audit_path(path)

    except FileNotFoundError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Path Error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    except PermissionError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Permission Error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    except ValueError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Validation Error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    except Exception as e:
        if json_output:
            print(json.dumps({"error": f"Unexpected audit failure: {str(e)}", "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Execution Error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    # Output formatting
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        _display_rich_report(report, verbose)

    # Determine exit code based on Trust Score and Recommendation
    trust_score = report.get("trust_score", 0)
    recommendation = report.get("recommendation", "BLOCK")

    if recommendation == "APPROVE" and trust_score >= 85:
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        raise typer.Exit(code=EXIT_AUDIT_FAILURE)


def _display_rich_report(report: dict, verbose: bool):
    """
    Renders clean, developer-oriented Rich terminal tables and panels.
    """
    trust_score = report.get("trust_score", 0)
    recommendation = report.get("recommendation", "BLOCK")
    summary = report.get("summary", "")
    agent_statuses = report.get("agent_statuses", {})
    agent_contribs = report.get("agent_contributions", {})
    breakdown = report.get("severity_breakdown", {})
    findings = report.get("findings", [])

    # 1. Agent Execution Status Table
    agent_table = Table(title="Verification Agent Statuses", border_style="dim", show_lines=True)
    agent_table.add_column("Agent", style="bold")
    agent_table.add_column("Status", justify="center")
    agent_table.add_column("Findings Contributed", justify="right")

    for agent, status in agent_statuses.items():
        status_style = "[bold green]OK[/bold green]" if status == "OK" else "[bold yellow]PARTIAL_FAILURE[/bold yellow]"
        contrib = str(agent_contribs.get(agent, 0))
        agent_table.add_row(agent, status_style, contrib)

    console.print(agent_table)
    console.print()

    # 2. Findings Summary Table
    sev_table = Table(title="Severity Breakdown", border_style="dim")
    sev_table.add_column("CRITICAL", style="bold red", justify="center")
    sev_table.add_column("HIGH", style="red", justify="center")
    sev_table.add_column("MEDIUM", style="yellow", justify="center")
    sev_table.add_column("LOW", style="blue", justify="center")
    sev_table.add_column("UNRESOLVED", style="magenta", justify="center")

    sev_table.add_row(
        str(breakdown.get("CRITICAL", 0)),
        str(breakdown.get("HIGH", 0)),
        str(breakdown.get("MEDIUM", 0)),
        str(breakdown.get("LOW", 0)),
        str(breakdown.get("UNRESOLVED", 0))
    )
    console.print(sev_table)
    console.print()

    # 3. Important Findings Table
    if findings:
        findings_table = Table(title=f"Detailed Findings ({len(findings)} total)", border_style="dim", show_lines=True)
        findings_table.add_column("Severity", justify="center")
        findings_table.add_column("Agent", style="dim")
        findings_table.add_column("Title", style="bold")
        findings_table.add_column("File : Line")
        findings_table.add_column("Description")

        for f in findings:
            sev = (f.get("severity") or "INFO").upper()
            status = f.get("status", "")
            
            if sev == "CRITICAL":
                sev_styled = "[bold red]CRITICAL[/bold red]"
            elif sev == "HIGH":
                sev_styled = "[red]HIGH[/red]"
            elif sev == "MEDIUM":
                sev_styled = "[yellow]MEDIUM[/yellow]"
            elif sev == "LOW":
                sev_styled = "[blue]LOW[/blue]"
            else:
                sev_styled = f"[dim]{sev}[/dim]"

            loc = f"{f.get('file_path', 'unknown')}:{f.get('line_number') or '-'}"
            findings_table.add_row(
                sev_styled,
                f.get("agent_name", ""),
                f.get("title", ""),
                loc,
                f.get("description", "")
            )

        console.print(findings_table)
        console.print()

        if verbose:
            # Print evidence snippets
            console.print(Panel("[bold]Finding Evidence Snippets[/bold]", style="dim"))
            for i, f in enumerate(findings, 1):
                if f.get("evidence"):
                    console.print(f"[bold cyan]Finding #{i}:[/bold cyan] {f.get('title')}")
                    console.print(f"[dim]{f.get('evidence')}[/dim]\n")

    # 4. Final Trust Score & Verdict Panel
    if trust_score >= 85:
        score_style = "bold green"
        verdict_style = "green"
        verdict_icon = "PASS"
    elif trust_score >= 65:
        score_style = "bold yellow"
        verdict_style = "yellow"
        verdict_icon = "WARNING"
    else:
        score_style = "bold red"
        verdict_style = "red"
        verdict_icon = "FAIL"

    verdict_panel = Panel(
        f"[{score_style}]TRUST SCORE: {trust_score} / 100[/{score_style}]\n"
        f"[{score_style}]RECOMMENDATION: {recommendation} ({verdict_icon})[/{score_style}]\n\n"
        f"[dim]{summary}[/dim]",
        title="[bold]Verification Verdict[/bold]",
        border_style=verdict_style
    )
    console.print(verdict_panel)


if __name__ == "__main__":
    app()
