import os
import sys

# Ensure UTF-8 output encoding on Windows console
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import json
import shutil
import webbrowser
import subprocess
from pathlib import Path
from typing import Optional, List
import http.server
import socketserver
import threading
import urllib.parse

# Ensure root and worker modules are available
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

import typer
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
# This folder holds the CLI's own modules (config, auth_manager, theme). The installed `sceptic` command imports
# this file as a package, so make its folder importable explicitly.
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
if CLI_DIR not in sys.path:
    sys.path.insert(0, CLI_DIR)

from audit_service import AuditService

from config import CLIConfig
from auth_manager import AuthManager
import theme

app = typer.Typer(
    name="sceptic",
    help=(
        "[bold cyan]Sceptic[/bold cyan] verifies AI-generated code before it is merged or deployed.\n\n"
        "Run [bold]sceptic[/bold] with no arguments for the interactive menu. "
        "Use [bold]sceptic COMMAND --help[/bold] for details on any command."
    ),
    rich_markup_mode="rich",
    add_completion=False,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = theme.console
err_console = theme.err_console

EXIT_SUCCESS = 0
EXIT_AUDIT_FAILURE = 1
EXIT_CLI_ERROR = 2


def prompt_input(label: str, default: str = "") -> str:
    """
    Prompt user using standard Python input() so that every character typed
    is completely visible and echoed on the terminal screen in plain text.
    """
    if default:
        console.print(f"[bold cyan]{label}[/bold cyan] [dim][{default}][/dim]: ", end="")
    else:
        console.print(f"[bold cyan]{label}[/bold cyan]: ", end="")
    try:
        val = input().strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        console.print()
        raise


def _version_callback(value: bool) -> None:
    if value:
        theme.console.print(f"{theme.APP_NAME} {theme.APP_VERSION}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    no_color: bool = typer.Option(False, "--no-color", help="Disable colors and styling. Also honored: NO_COLOR."),
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True, help="Show the version and exit."),
):
    """
    Sceptic CLI: Independent AI-generated code verification.
    When run without arguments, launches the interactive terminal dashboard.
    """
    theme.set_no_color(no_color)
    if ctx.invoked_subcommand is None:
        interactive_dashboard()


# ========================================================
# 1. AUTHENTICATION COMMANDS
# ========================================================

def _login_google_browser(api_url: str):
    captured_data = {}
    auth_event = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)

            if "token" in query_params:
                captured_data["token"] = query_params["token"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authentication successful!</h1><p>You can close this tab and return to your terminal.</p>")
                auth_event.set()
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), CallbackHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    cli_callback_url = f"http://localhost:{port}/callback"

    console.print("[cyan]Opening browser for Google Authentication...[/cyan]")
    try:
        with httpx.Client(timeout=5.0) as client:
            login_resp = client.get(f"{api_url}/auth/google/login", params={"redirect_uri": cli_callback_url})
            if login_resp.status_code == 200:
                auth_url = login_resp.json()["auth_url"]
                webbrowser.open(auth_url)
                console.print(f"[dim]If browser does not open automatically, visit:[/dim]\n{auth_url}\n")
            else:
                console.print(f"[bold red]Failed to initialize Google login:[/bold red] {login_resp.text}")
                server.shutdown()
                raise typer.Exit(code=EXIT_CLI_ERROR)
    except Exception as e:
        console.print(f"[bold red]Could not reach backend at {api_url}:[/bold red] {e}")
        server.shutdown()
        raise typer.Exit(code=EXIT_CLI_ERROR)

    console.print("[yellow]Waiting for authentication in browser... (Press Ctrl+C to cancel)[/yellow]")
    got_auth = auth_event.wait(timeout=120)
    server.shutdown()

    if not got_auth or "token" not in captured_data:
        console.print("[bold red]Authentication timed out or was cancelled.[/bold red]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    token = captured_data["token"]
    with httpx.Client(timeout=5.0) as client:
        me_resp = client.get(f"{api_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
        if me_resp.status_code == 200:
            user_data = me_resp.json()
            AuthManager.store_token(token, user_data)
            console.print(Panel(
                f"[bold green]Successfully logged in as:[/bold green]\n"
                f"[bold]Name:[/bold] {user_data.get('name')}\n"
                f"[bold]Email:[/bold] {user_data.get('email')}",
                title="Sceptic Login",
                border_style="green"
            ))
        else:
            console.print("[bold red]Failed to verify user profile with backend.[/bold red]")
            raise typer.Exit(code=EXIT_CLI_ERROR)


def _login_with_email_password(api_url: str, email: str, password: str):
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{api_url}/auth/login",
                json={"email": email, "password": password}
            )
            if resp.status_code == 200:
                data = resp.json()
                AuthManager.store_token(data["access_token"], data["user"])
                console.print(Panel(
                    f"[bold green]Successfully logged in as:[/bold green]\n"
                    f"[bold]Name:[/bold] {data['user']['name']}\n"
                    f"[bold]Email:[/bold] {data['user']['email']}",
                    title="Sceptic Login",
                    border_style="green"
                ))
            else:
                detail = resp.json().get("detail", resp.text) if "application/json" in resp.headers.get("content-type", "") else resp.text
                console.print(f"[bold red]Login failed:[/bold red] {detail}")
                raise typer.Exit(code=EXIT_CLI_ERROR)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[bold red]Connection error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)


def _register_with_email_password(api_url: str, name: str, email: str, password: str):
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{api_url}/auth/register",
                json={"name": name, "email": email, "password": password}
            )
            if resp.status_code == 201:
                data = resp.json()
                AuthManager.store_token(data["access_token"], data["user"])
                console.print(Panel(
                    f"[bold green]Successfully registered and logged in as:[/bold green]\n"
                    f"[bold]Name:[/bold] {data['user']['name']}\n"
                    f"[bold]Email:[/bold] {data['user']['email']}",
                    title="Sceptic Registration",
                    border_style="green"
                ))
            else:
                detail = resp.json().get("detail", resp.text) if "application/json" in resp.headers.get("content-type", "") else resp.text
                console.print(f"[bold red]Registration failed:[/bold red] {detail}")
                raise typer.Exit(code=EXIT_CLI_ERROR)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[bold red]Connection error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)


def execute_login(
    email: Optional[str] = None,
    password: Optional[str] = None,
    google: bool = False,
    mock_email: Optional[str] = None
):
    """
    Executes login flow with clean type checking to prevent OptionInfo errors.
    """
    api_url = CLIConfig.get_api_url()

    # 1. Direct mock flow for automated testing / headless environments
    if mock_email and isinstance(mock_email, str):
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{api_url}/auth/google/callback",
                    params={"mock_email": mock_email, "mock_name": mock_email.split("@")[0]}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    AuthManager.store_token(data["access_token"], data["user"])
                    console.print(Panel(
                        f"[bold green]Successfully logged in as:[/bold green]\n"
                        f"[bold]Name:[/bold] {data['user']['name']}\n"
                        f"[bold]Email:[/bold] {data['user']['email']}",
                        title="Sceptic Login",
                        border_style="green"
                    ))
                    return
                else:
                    console.print(f"[bold red]Login failed:[/bold red] {resp.text}")
                    raise typer.Exit(code=EXIT_CLI_ERROR)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[bold red]Connection error:[/bold red] {e}")
            raise typer.Exit(code=EXIT_CLI_ERROR)

    # 2. Direct email & password flags
    if email and password and isinstance(email, str) and isinstance(password, str):
        _login_with_email_password(api_url, email, password)
        return

    # 3. Direct Google flag
    if google:
        _login_google_browser(api_url)
        return

    # 4. Interactive menu when called with no flags
    console.print("\n[bold cyan]Sceptic Authentication[/bold cyan]")
    console.print("[1] Login with Email & Password")
    console.print("[2] Register new account (Email & Password)")
    console.print("[3] Login with Google (Browser OAuth)")
    console.print("[4] Dev Mock Login (Test Email)")
    console.print("[0] Cancel\n")
    choice = Prompt.ask("[cyan]Select authentication method[/cyan]", default="1")

    if choice == "1":
        em = prompt_input("Email address")
        pw = prompt_input("Password")
        if em and pw:
            _login_with_email_password(api_url, em, pw)
    elif choice == "2":
        nm = prompt_input("Full Name")
        em = prompt_input("Email address")
        pw = prompt_input("Password (min 6 chars)")
        if nm and em and pw:
            _register_with_email_password(api_url, nm, em, pw)
    elif choice == "3":
        _login_google_browser(api_url)
    elif choice == "4":
        m_email = prompt_input("Mock Email", default="dev@sceptic.ai")
        execute_login(mock_email=m_email)


def execute_register(
    name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None
):
    """
    Executes registration flow with clean input prompts.
    """
    api_url = CLIConfig.get_api_url()

    if not name or not isinstance(name, str):
        name = prompt_input("Full Name")
    if not email or not isinstance(email, str):
        email = prompt_input("Email address")
    if not password or not isinstance(password, str):
        password = prompt_input("Password (min 6 chars)")

    if name and email and password:
        _register_with_email_password(api_url, name, email, password)
    else:
        console.print("[bold red]Name, email, and password are required.[/bold red]")
        raise typer.Exit(code=EXIT_CLI_ERROR)


@app.command(name="login", rich_help_panel="Account")
def login(
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Login with email address."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Login password."),
    google: bool = typer.Option(False, "--google", "-g", help="Authenticate with Google in browser."),
    mock_email: Optional[str] = typer.Option(None, "--mock-email", help="Perform non-interactive mock login with email (for testing & CI).")
):
    """
    Authenticate CLI with Sceptic using Google OAuth or Email & Password.
    """
    clean_email = email if isinstance(email, str) else None
    clean_pw = password if isinstance(password, str) else None
    clean_mock = mock_email if isinstance(mock_email, str) else None
    clean_google = bool(google) if isinstance(google, bool) else False

    execute_login(email=clean_email, password=clean_pw, google=clean_google, mock_email=clean_mock)


@app.command(name="register", rich_help_panel="Account")
def register(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Your full name."),
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Email address to register."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Account password (min 6 chars).")
):
    """
    Register a new Sceptic account using Email & Password.
    """
    clean_name = name if isinstance(name, str) else None
    clean_email = email if isinstance(email, str) else None
    clean_pw = password if isinstance(password, str) else None

    execute_register(name=clean_name, email=clean_email, password=clean_pw)


@app.command(name="logout", rich_help_panel="Account")
def logout():
    """
    Clear CLI's locally stored authentication credentials.
    """
    AuthManager.clear_credentials()
    console.print("[bold green]Successfully logged out from CLI.[/bold green]")


@app.command(name="whoami", rich_help_panel="Account")
def whoami():
    """
    Display current authenticated user profile.
    """
    token = AuthManager.get_token()
    if not token:
        console.print("[yellow]Not logged in. Run 'sceptic login' to authenticate.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    api_url = CLIConfig.get_api_url()
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{api_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                user = resp.json()
                table = Table(title="Authenticated User Profile", show_header=False, border_style="cyan")
                table.add_column("Field", style="bold cyan")
                table.add_column("Value", style="white")
                table.add_row("Name", user.get("name", "N/A"))
                table.add_row("Email", user.get("email", "N/A"))
                table.add_row("User ID", str(user.get("id", "N/A")))
                console.print(table)
            else:
                console.print("[bold red]Authentication token expired or invalid. Please re-login with 'sceptic login'.[/bold red]")
                raise typer.Exit(code=EXIT_CLI_ERROR)
    except Exception as e:
        console.print(f"[bold red]Connection error:[/bold red] {e}")
        raise typer.Exit(code=EXIT_CLI_ERROR)


# ========================================================
# 2. PROJECT COMMANDS
# ========================================================

@app.command(name="project", rich_help_panel="Projects and features")
def project_cmd(
    select_id: Optional[str] = typer.Option(None, "--select", help="Project ID to select as active."),
    create_name: Optional[str] = typer.Option(None, "--create", help="Create and select a new project by name."),
    repo_url: Optional[str] = typer.Option(None, "--repo", help="Repository URL for new project.")
):
    """
    List, switch, or create projects linked to your account.
    """
    token = AuthManager.get_token()
    if not token:
        console.print("[yellow]You must be logged in to manage projects. Run 'sceptic login'.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    api_url = CLIConfig.get_api_url()
    headers = {"Authorization": f"Bearer {token}"}

    clean_select = select_id if isinstance(select_id, str) else None
    clean_create = create_name if isinstance(create_name, str) else None
    clean_repo = repo_url if isinstance(repo_url, str) else None

    with httpx.Client(timeout=5.0) as client:
        # Create project flow
        if clean_create:
            c_resp = client.post(
                f"{api_url}/projects",
                json={"name": clean_create, "repository_url": clean_repo},
                headers=headers
            )
            if c_resp.status_code in (200, 201):
                p = c_resp.json()
                CLIConfig.set_active_project(p["id"], p["name"])
                console.print(f"[bold green]Created & activated project:[/bold green] {p['name']} ({p['id']})")
                return
            else:
                console.print(f"[bold red]Failed to create project:[/bold red] {c_resp.text}")
                raise typer.Exit(code=EXIT_CLI_ERROR)

        # List projects flow
        resp = client.get(f"{api_url}/projects", headers=headers)
        if resp.status_code != 200:
            console.print(f"[bold red]Failed to retrieve projects:[/bold red] {resp.text}")
            raise typer.Exit(code=EXIT_CLI_ERROR)

        projects = resp.json()

        # Switch project flow
        if clean_select:
            matching = [p for p in projects if p["id"] == clean_select]
            if not matching:
                console.print(f"[bold red]Project ID '{clean_select}' not found in your account.[/bold red]")
                raise typer.Exit(code=EXIT_CLI_ERROR)
            CLIConfig.set_active_project(matching[0]["id"], matching[0]["name"])
            console.print(f"[bold green]Activated project:[/bold green] {matching[0]['name']}")
            return

        active = CLIConfig.get_active_project()
        table = Table(title="Your Sceptic Projects", border_style="cyan")
        table.add_column("Active", justify="center")
        table.add_column("Project Name", style="bold")
        table.add_column("Project ID", style="dim")
        table.add_column("Repository URL", style="cyan")

        if not projects:
            console.print("[dim]No projects found. Create one with 'sceptic project --create <name>'[/dim]")
            return

        for p in projects:
            is_active = "[green]✓[/green]" if active and active["id"] == p["id"] else ""
            table.add_row(is_active, p["name"], p["id"], p.get("repository_url") or "Local")

        console.print(table)


# ========================================================
# 3. FEATURE ANALYSIS COMMAND
# ========================================================

@app.command(name="newfeature", rich_help_panel="Projects and features")
def newfeature(
    description: str = typer.Argument(..., help="Feature proposal description to analyze.")
):
    """
    Evaluate feature feasibility, complexity, and risk against the current project.
    """
    token = AuthManager.get_token()
    if not token:
        console.print("[yellow]You must be logged in to analyze features. Run 'sceptic login'.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    active = CLIConfig.get_active_project()
    if not active:
        console.print("[yellow]No active project selected. Run 'sceptic project' or 'sceptic project --create <name>'.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    api_url = CLIConfig.get_api_url()
    headers = {"Authorization": f"Bearer {token}"}

    with console.status(f"[bold green]Evaluating feature proposal for '{active['name']}'...[/bold green]"):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{api_url}/projects/{active['id']}/feature-analyses",
                    json={"feature_description": description},
                    headers=headers
                )
        except Exception as e:
            console.print(f"[bold red]Connection error:[/bold red] {e}")
            raise typer.Exit(code=EXIT_CLI_ERROR)

    if resp.status_code != 201:
        console.print(f"[bold red]Feature analysis failed:[/bold red] {resp.text}")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    res = resp.json()

    # Render results with Rich
    header_text = Text()
    header_text.append("Feature Feasibility Assessment\n", style="bold cyan")
    header_text.append(f"Project: {active['name']}\n", style="white")
    header_text.append(f"Proposal: {res['feature_description']}", style="italic dim")
    console.print(Panel(header_text, border_style="cyan"))

    scores_table = Table(title="Architecture Scoring", border_style="blue")
    scores_table.add_column("Metric", style="bold")
    scores_table.add_column("Score", justify="right")
    scores_table.add_column("Assessment", style="dim")

    scores_table.add_row("Feasibility", f"[green]{res['feasibility_score']:.1f}%[/green]", "High architectural alignment")
    scores_table.add_row("Complexity", f"[yellow]{res['complexity_score']:.1f}%[/yellow]", "Manageable module coupling")
    scores_table.add_row("Risk", f"[green]{res['risk_score']:.1f}%[/green]", "Minimal security attack surface")
    scores_table.add_row("Confidence", f"[cyan]{res['confidence_score']:.1f}%[/cyan]", "High deterministic confidence")
    console.print(scores_table)

    console.print("\n[bold]Implementation Plan:[/bold]")
    console.print(Panel(res["implementation_plan"], border_style="dim"))


# ========================================================
# 4. HISTORY, STATUS & DOCTOR COMMANDS
# ========================================================

@app.command(name="history", rich_help_panel="Projects and features")
def history():
    """
    Display audit and feature analysis history for the current project.
    """
    token = AuthManager.get_token()
    if not token:
        console.print("[yellow]You must be logged in to view history. Run 'sceptic login'.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    active = CLIConfig.get_active_project()
    if not active:
        console.print("[yellow]No active project selected. Run 'sceptic project'.[/yellow]")
        raise typer.Exit(code=EXIT_CLI_ERROR)

    api_url = CLIConfig.get_api_url()
    headers = {"Authorization": f"Bearer {token}"}

    audits = []
    analyses = []
    try:
        with httpx.Client(timeout=15.0) as client:
            # Fetch audits
            a_resp = client.get(f"{api_url}/projects/{active['id']}/audits", headers=headers)
            # Fetch feature analyses
            f_resp = client.get(f"{api_url}/projects/{active['id']}/feature-analyses", headers=headers)

            if a_resp.status_code == 200:
                audits = a_resp.json()
            if f_resp.status_code == 200:
                analyses = f_resp.json()
    except Exception as e:
        console.print(f"[dim yellow]Warning: Could not refresh history from backend ({e})[/dim yellow]")

    console.print(f"[bold cyan]Project History: {active['name']}[/bold cyan]\n")

    table = Table(title="Recent Audits", border_style="cyan")
    table.add_column("Audit ID", style="dim")
    table.add_column("Status")
    table.add_column("Trust Score", justify="right")
    table.add_column("Recommendation")
    table.add_column("Date")

    for a in audits[:5]:
        score_str = f"{a['trust_score']:.1f}" if a.get("trust_score") is not None else "N/A"
        table.add_row(str(a["id"])[:8], a["status"], score_str, a.get("recommendation") or "N/A", a["created_at"][:10])

    console.print(table)

    f_table = Table(title="Feature Analyses", border_style="blue")
    f_table.add_column("Analysis ID", style="dim")
    f_table.add_column("Feature Description")
    f_table.add_column("Feasibility", justify="right")
    f_table.add_column("Risk", justify="right")
    f_table.add_column("Date")

    for f in analyses[:5]:
        f_table.add_row(str(f["id"])[:8], f["feature_description"][:40], f"{f['feasibility_score']:.0f}%", f"{f['risk_score']:.0f}%", f["created_at"][:10])

    console.print(f_table)


@app.command(name="status", rich_help_panel="Operations")
def status():
    """
    Display current user, active project, and backend connectivity.
    """
    api_url = CLIConfig.get_api_url()
    active_proj = CLIConfig.get_active_project()
    token = AuthManager.get_token()

    backend_ok = False
    with httpx.Client(timeout=3.0) as client:
        try:
            r = client.get(f"{api_url}/health")
            backend_ok = r.status_code == 200
        except Exception:
            backend_ok = False

    user_info = None
    if token and backend_ok:
        with httpx.Client(timeout=3.0) as client:
            try:
                ur = client.get(f"{api_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
                if ur.status_code == 200:
                    user_info = ur.json()
            except Exception:
                pass

    # Fetch active deployment status if project is active
    deployment_info = None
    telemetry_info = None
    drift_info = None
    if token and backend_ok and active_proj:
        with httpx.Client(timeout=3.0) as client:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                dep_res = client.get(f"{api_url}/projects/{active_proj['id']}/deployments", headers=headers)
                if dep_res.status_code == 200 and dep_res.json():
                    deployments = dep_res.json()
                    deployment_info = deployments[0]
                    dep_id = deployment_info["id"]

                    # Fetch telemetry
                    tel_res = client.get(f"{api_url}/deployments/{dep_id}/telemetry", headers=headers)
                    if tel_res.status_code == 200 and tel_res.json():
                        telemetry_info = tel_res.json()[0]

                    # Fetch drift
                    drift_res = client.get(f"{api_url}/deployments/{dep_id}/drift", headers=headers)
                    if drift_res.status_code == 200:
                        drift_info = drift_res.json()
            except Exception:
                pass

    table = Table(title="Sceptic CLI System Status", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Backend API", f"[green]{api_url}[/green]" if backend_ok else f"[red]{api_url} (Offline)[/red]")
    table.add_row("Authenticated As", f"{user_info['name']} ({user_info['email']})" if user_info else "[yellow]Not Logged In[/yellow]")
    table.add_row("Active Project", f"{active_proj['name']} ({active_proj['id']})" if active_proj else "[dim]None (Run 'sceptic project')[/dim]")

    if deployment_info:
        table.add_row("Deployment", f"{deployment_info['id'][:8]}... [bold]({deployment_info['status']})[/bold]")
        table.add_row("Environment / Version", f"{deployment_info.get('environment', 'production')} / {deployment_info.get('version', 'unknown')}")

        if telemetry_info:
            h_stat = telemetry_info.get("health_status", "unknown")
            h_color = "green" if h_stat == "healthy" else "red"
            table.add_row("Runtime Health", f"[{h_color}]{h_stat.capitalize()}[/{h_color}]")

            err_rate = telemetry_info.get("error_rate")
            if err_rate is not None:
                err_color = "green" if err_rate < 0.05 else "red"
                table.add_row("Error Rate", f"[{err_color}]{err_rate:.2%}[/{err_color}]")

            lat_p95 = telemetry_info.get("latency_p95")
            if lat_p95 is not None:
                lat_color = "green" if lat_p95 < 0.5 else "yellow"
                table.add_row("P95 Latency", f"[{lat_color}]{lat_p95:.3f}s[/{lat_color}]")

        if drift_info is not None:
            active_drifts = [d for d in drift_info if not d.get("resolved_at")]
            if active_drifts:
                types = ", ".join(d.get("drift_type", "UNKNOWN") for d in active_drifts)
                table.add_row("Drift Events", f"[red]{len(active_drifts)} active drift(s) ({types})[/red]")
            else:
                table.add_row("Drift Events", "[green]None (Synchronized)[/green]")

    console.print(table)


@app.command(name="watchdog", rich_help_panel="Operations")
def watchdog_cmd(
    deployment_id: Optional[str] = typer.Argument(None, help="Deployment UUID to verify"),
):
    """
    Run Pipeline Watchdog runtime health, latency, and error-rate verification.
    """
    api_url = CLIConfig.get_api_url()
    active_proj = CLIConfig.get_active_project()
    token = AuthManager.get_token()

    if not token:
        console.print("[red]Error: Authentication required. Run 'sceptic login' first.[/red]")
        raise typer.Exit(code=1)

    target_dep_id = deployment_id
    if not target_dep_id and active_proj:
        with httpx.Client(timeout=5.0) as client:
            try:
                r = client.get(
                    f"{api_url}/projects/{active_proj['id']}/deployments",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if r.status_code == 200 and r.json():
                    target_dep_id = r.json()[0]["id"]
            except Exception:
                pass

    if not target_dep_id:
        console.print("[red]Error: No deployment specified and no active deployments found.[/red]")
        raise typer.Exit(code=1)

    with console.status(f"[bold cyan]Running Pipeline Watchdog check on {target_dep_id[:8]}...[/bold cyan]"):
        with httpx.Client(timeout=15.0) as client:
            try:
                resp = client.post(
                    f"{api_url}/deployments/{target_dep_id}/watchdog/check",
                    headers={"Authorization": f"Bearer {token}"}
                )
            except Exception as e:
                console.print(f"[red]Error connecting to Sceptic API: {e}[/red]")
                raise typer.Exit(code=1)

    if resp.status_code != 200:
        console.print(f"[red]Watchdog check failed: HTTP {resp.status_code}: {resp.text}[/red]")
        raise typer.Exit(code=1)

    data = resp.json()
    status_str = data.get("status", "UNKNOWN")
    color = "green" if status_str == "PASS" else ("yellow" if status_str == "UNRESOLVED" else "red")

    console.print(Panel(
        f"[bold {color}]Watchdog Status: {status_str}[/bold {color}]\n"
        f"{data.get('summary', '')}",
        title=f"Pipeline Watchdog — {target_dep_id[:8]}",
        border_style=color
    ))

    findings = data.get("findings", [])
    if findings:
        f_table = Table(title="Watchdog Findings", border_style=color)
        f_table.add_column("Type", style="bold")
        f_table.add_column("Severity")
        f_table.add_column("Description")
        for f in findings:
            f_table.add_row(f.get("finding_type", ""), f.get("severity", ""), f.get("description", ""))
        console.print(f_table)


@app.command(name="gatekeeper", rich_help_panel="Operations")
def gatekeeper_cmd(
    deployment_id: Optional[str] = typer.Argument(None, help="Deployment UUID to verify"),
):
    """
    Run Deployment Gatekeeper integrity and configuration drift verification.
    """
    api_url = CLIConfig.get_api_url()
    active_proj = CLIConfig.get_active_project()
    token = AuthManager.get_token()

    if not token:
        console.print("[red]Error: Authentication required. Run 'sceptic login' first.[/red]")
        raise typer.Exit(code=1)

    target_dep_id = deployment_id
    if not target_dep_id and active_proj:
        with httpx.Client(timeout=5.0) as client:
            try:
                r = client.get(
                    f"{api_url}/projects/{active_proj['id']}/deployments",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if r.status_code == 200 and r.json():
                    target_dep_id = r.json()[0]["id"]
            except Exception:
                pass

    if not target_dep_id:
        console.print("[red]Error: No deployment specified and no active deployments found.[/red]")
        raise typer.Exit(code=1)

    with console.status(f"[bold cyan]Running Gatekeeper integrity check on {target_dep_id[:8]}...[/bold cyan]"):
        with httpx.Client(timeout=15.0) as client:
            try:
                resp = client.post(
                    f"{api_url}/deployments/{target_dep_id}/gatekeeper/check",
                    headers={"Authorization": f"Bearer {token}"}
                )
            except Exception as e:
                console.print(f"[red]Error connecting to Sceptic API: {e}[/red]")
                raise typer.Exit(code=1)

    if resp.status_code != 200:
        console.print(f"[red]Gatekeeper check failed: HTTP {resp.status_code}: {resp.text}[/red]")
        raise typer.Exit(code=1)

    data = resp.json()
    status_str = data.get("status", "UNKNOWN")
    color = "green" if status_str == "PASS" else ("yellow" if status_str == "UNRESOLVED" else "red")

    console.print(Panel(
        f"[bold {color}]Gatekeeper Status: {status_str}[/bold {color}]\n"
        f"{data.get('summary', '')}\n"
        f"Drift events recorded: {data.get('drift_events_created', 0)}",
        title=f"Deployment Gatekeeper — {target_dep_id[:8]}",
        border_style=color
    ))

    findings = data.get("findings", [])
    if findings:
        f_table = Table(title="Gatekeeper Findings", border_style=color)
        f_table.add_column("Type", style="bold")
        f_table.add_column("Severity")
        f_table.add_column("Description")
        for f in findings:
            f_table.add_row(f.get("finding_type", ""), f.get("severity", ""), f.get("description", ""))
        console.print(f_table)


@app.command(name="rollback", rich_help_panel="Operations")
def rollback_cmd(
    deployment_id: Optional[str] = typer.Argument(None, help="Deployment UUID to roll back"),
    target: Optional[str] = typer.Option(None, "--target", "-t", help="Specific target deployment UUID to restore"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Operational justification for rollback"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Perform pre-flight safety verification without executing rollback"),
    allow_unsafe_migration: bool = typer.Option(False, "--allow-unsafe-migration", help="Bypass database migration downgrade guard")
):
    """
    Safely recover from a failed deployment using the Sceptic Rollback Agent.
    """
    api_url = CLIConfig.get_api_url()
    active_proj = CLIConfig.get_active_project()
    token = AuthManager.get_token()

    if not token:
        console.print("[red]Error: Authentication required. Run 'sceptic login' first.[/red]")
        raise typer.Exit(code=1)

    target_dep_id = deployment_id
    if not target_dep_id and active_proj:
        with httpx.Client(timeout=5.0) as client:
            try:
                r = client.get(
                    f"{api_url}/projects/{active_proj['id']}/deployments",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if r.status_code == 200 and r.json():
                    target_dep_id = r.json()[0]["id"]
            except Exception:
                pass

    if not target_dep_id:
        console.print("[red]Error: No deployment specified and no active deployments found.[/red]")
        raise typer.Exit(code=1)

    rollback_reason = reason or "Manual deployment recovery triggered via Sceptic CLI"

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "reason": rollback_reason,
        "trigger_source": "MANUAL",
        "target_deployment_id": target,
        "allow_unsafe_migration": allow_unsafe_migration
    }

    if dry_run:
        with console.status(f"[bold cyan]Running Rollback safety evaluation on {target_dep_id[:8]}...[/bold cyan]"):
            with httpx.Client(timeout=15.0) as client:
                try:
                    resp = client.post(
                        f"{api_url}/deployments/{target_dep_id}/rollback/check",
                        json=payload,
                        headers=headers
                    )
                except Exception as e:
                    console.print(f"[red]Error connecting to Sceptic API: {e}[/red]")
                    raise typer.Exit(code=1)

        if resp.status_code != 200:
            console.print(f"[red]Safety evaluation failed: HTTP {resp.status_code}: {resp.text}[/red]")
            raise typer.Exit(code=1)

        data = resp.json()
        is_safe = data.get("is_safe", False)
        color = "green" if is_safe else "red"

        console.print(Panel(
            f"[bold {color}]Pre-Flight Safety Check: {'PASSED' if is_safe else 'FAILED'}[/bold {color}]\n"
            f"{data.get('message', '')}\n"
            f"Target Deployment: {data.get('target_deployment_id') or 'Auto-discovered'}\n"
            f"Target Commit: {data.get('target_commit_sha') or 'N/A'}",
            title=f"Rollback Safety Evaluation — {target_dep_id[:8]}",
            border_style=color
        ))

        checks = data.get("safety_checks", {})
        if checks:
            s_table = Table(title="Safety Verification Checklist", border_style=color)
            s_table.add_column("Safety Check", style="bold")
            s_table.add_column("Status")
            s_table.add_column("Detail")
            for name, res in checks.items():
                p = res.get("passed", False)
                status_badge = "[green]PASS[/green]" if p else "[red]FAIL[/red]"
                s_table.add_row(name, status_badge, res.get("detail", ""))
            console.print(s_table)
        return

    # Full execution
    with console.status(f"[bold cyan]Executing Rollback Agent on deployment {target_dep_id[:8]}...[/bold cyan]"):
        with httpx.Client(timeout=30.0) as client:
            try:
                resp = client.post(
                    f"{api_url}/deployments/{target_dep_id}/rollback",
                    json=payload,
                    headers=headers
                )
            except Exception as e:
                console.print(f"[red]Error connecting to Sceptic API: {e}[/red]")
                raise typer.Exit(code=1)

    if resp.status_code != 200:
        console.print(f"[red]Rollback request failed: HTTP {resp.status_code}: {resp.text}[/red]")
        raise typer.Exit(code=1)

    data = resp.json()
    status_str = data.get("status", "UNKNOWN")
    color = "green" if status_str == "SUCCESS" else ("yellow" if status_str == "ABORTED" else "red")

    console.print(Panel(
        f"[bold {color}]Rollback Status: {status_str}[/bold {color}]\n"
        f"{data.get('message', '')}\n"
        f"Recovered Deployment ID: {data.get('target_deployment_id') or 'N/A'}",
        title=f"Rollback Agent Recovery — {target_dep_id[:8]}",
        border_style=color
    ))

    checks = data.get("safety_checks", {})
    if checks:
        s_table = Table(title="Pre-Flight Safety Checklist", border_style=color)
        s_table.add_column("Safety Check", style="bold")
        s_table.add_column("Status")
        s_table.add_column("Detail")
        for name, res in checks.items():
            p = res.get("passed", False)
            status_badge = "[green]PASS[/green]" if p else "[red]FAIL[/red]"
            s_table.add_row(name, status_badge, res.get("detail", ""))
        console.print(s_table)

    v_details = data.get("verification_details")
    if v_details:
        v_table = Table(title="Recovered Service Runtime Verification", border_style="green")
        v_table.add_column("Property", style="bold")
        v_table.add_column("Value")
        for k, v in v_details.items():
            v_table.add_row(k, str(v))
        console.print(v_table)

    if status_str != "SUCCESS":
        raise typer.Exit(code=1)



@app.command(name="doctor", rich_help_panel="System")
def doctor():
    """
    Check the tools Sceptic relies on, and say what to install for anything missing.
    """
    theme.header("Environment check")
    checks = _environment_checks()

    grid = theme.table(None, [
        ("Check", {"style": "bold", "no_wrap": True}),
        ("Status", {"no_wrap": True}),
        ("Detail", {"style": theme.MUTED, "overflow": "fold"}),
        ("Next step", {"style": theme.WARNING, "overflow": "fold"}),
    ])
    for name, state, detail, hint in checks:
        grid.add_row(name, theme.status_text(state), detail, hint if state in ("fail", "warn") else "")
    console.print(grid)

    counts = {s: sum(1 for c in checks if c[1] == s) for s in ("ok", "fail", "warn", "info")}
    parts = [f"{counts['ok']} passed"]
    if counts["warn"]:
        parts.append(f"{counts['warn']} {'warning' if counts['warn'] == 1 else 'warnings'}")
    if counts["fail"]:
        parts.append(f"{counts['fail']} need{'s' if counts['fail'] == 1 else ''} attention")
    console.print()
    console.print(Text(" · ".join(parts), style="bold"))
    console.print(Text(theme.legend_for_symbols(), style=theme.MUTED))


def _run_quiet(cmd, timeout: int = 10) -> Optional[str]:
    """Runs a command and returns its first output line, or None when it cannot run or fails."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _which_or_path(name: str, env_override: Optional[str] = None) -> Optional[str]:
    if env_override and os.path.exists(os.getenv(env_override, "")):
        return os.getenv(env_override)
    return shutil.which(name)


def _environment_checks():
    """Returns (check, state, detail, next_step) rows for the doctor table."""
    rows = []
    rows.append(("Python", "ok", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", ""))

    git = _run_quiet(["git", "--version"])
    git_version = git.replace("git version ", "") if git else None
    rows.append(("Git", "ok" if git else "warn", git_version or "not found", "" if git else "Install Git: https://git-scm.com"))

    docker_server = _run_quiet(["docker", "version", "--format", "{{.Server.Version}}"])
    if docker_server:
        rows.append(("Docker", "ok", f"daemon {docker_server}", ""))
        image = _run_quiet(["docker", "image", "inspect", "sceptic-sandbox:latest", "--format", "{{.Id}}"])
        rows.append((
            "Sandbox image", "ok" if image else "warn",
            "image present" if image else "image not built",
            "" if image else "docker build -t sceptic-sandbox:latest -f worker/sandbox/Dockerfile worker",
        ))
    else:
        rows.append(("Docker", "fail", "daemon not reachable", "Start Docker, then re-run the check"))
        rows.append(("Sandbox image", "warn", "cannot check without Docker", "Start Docker first"))

    javac = shutil.which("javac")
    rows.append((
        "Java (javac)", "ok" if javac else "warn",
        (_run_quiet(["javac", "-version"]) or "found") if javac else "not found",
        "" if javac else "Install a JDK 17 or newer to check Java code",
    ))

    node = shutil.which("node")
    rows.append((
        "Node.js", "ok" if node else "warn",
        (_run_quiet(["node", "--version"]) or "found") if node else "not found",
        "" if node else "Install Node.js 18 or newer to check JavaScript and TypeScript",
    ))

    tsc = os.path.join(root_dir, "worker", "tools", "js", "node_modules", "typescript", "bin", "tsc")
    rows.append((
        "TypeScript compiler", "ok" if os.path.exists(tsc) else "warn",
        "worker/tools/js" if os.path.exists(tsc) else "not installed",
        "" if os.path.exists(tsc) else "cd worker/tools/js && npm ci",
    ))

    maven = shutil.which("mvn")
    rows.append((
        "Maven", "ok" if maven else "info",
        "found" if maven else "not found (optional)",
        "" if maven else "Optional: lets Java dependencies resolve for type checks",
    ))

    gitleaks = shutil.which("gitleaks")
    rows.append((
        "gitleaks", "ok" if gitleaks else "warn",
        "found" if gitleaks else "not found",
        "" if gitleaks else "Install gitleaks: github.com/gitleaks/gitleaks",
    ))

    osv = _which_or_path("osv-scanner", "OSV_SCANNER_PATH")
    rows.append((
        "osv-scanner", "ok" if osv else "warn",
        "found" if osv else "not found",
        "" if osv else "Install osv-scanner: https://google.github.io/osv-scanner",
    ))

    semgrep = _which_or_path("semgrep")
    rows.append((
        "Semgrep", "ok" if semgrep else "warn",
        "found" if semgrep else "not found",
        "" if semgrep else "pip install semgrep",
    ))

    api_url = CLIConfig.get_api_url()
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(f"{api_url}/health")
        backend_ok = response.status_code == 200
        rows.append((
            "Backend API", "ok" if backend_ok else "fail",
            api_url if backend_ok else f"{api_url} returned HTTP {response.status_code}",
            "" if backend_ok else "Check the backend logs",
        ))
    except Exception:
        rows.append((
            "Backend API", "fail", f"{api_url} is offline",
            "Start it: uvicorn backend.main:app --port 8000",
        ))

    authenticated = bool(AuthManager.get_token())
    rows.append((
        "Sign-in", "ok" if authenticated else "info",
        "signed in" if authenticated else "not signed in",
        "" if authenticated else "Run: sceptic login",
    ))
    return rows




# ========================================================
# 5. AUDIT COMMAND (EXISTING PIPELINE + BACKEND SYNC)
# ========================================================

def execute_audit_flow(path: str, verbose: bool = False, json_output: bool = False) -> int:
    """
    Core executor for Sceptic audit pipeline. Returns appropriate exit code without exiting python process.
    """
    service = AuditService()

    if not json_output:
        theme.header("Audit")
        console.print(theme.kv_table([("Target", path)]))

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
            theme.error(str(e), hint="Check that the path exists and that it is a supported file or directory.", code=EXIT_CLI_ERROR)
        return EXIT_CLI_ERROR

    except PermissionError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            theme.error(str(e), hint="Check the file permissions, or run the audit as a user that can read the target.", code=EXIT_CLI_ERROR)
        return EXIT_CLI_ERROR

    except ValueError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            theme.error(str(e), hint="Sceptic audits Python, Java, JavaScript, and TypeScript files.", code=EXIT_CLI_ERROR)
        return EXIT_CLI_ERROR

    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            theme.error(str(e), hint="Use --json to get the full report. If it persists, report it with the command you ran.", code=EXIT_CLI_ERROR)
        return EXIT_CLI_ERROR

    # Output formatting
    if json_output:
        print(json.dumps(report, indent=2))
        if report.get("recommendation") in ("BLOCK", "REQUEST_CHANGES") or report.get("trust_score", 100) < 80:
            return EXIT_AUDIT_FAILURE
        return EXIT_SUCCESS

    _display_rich_report(report, verbose=verbose)

    # Sync audit run with backend and active project
    token = AuthManager.get_token()
    active = CLIConfig.get_active_project()
    api_url = CLIConfig.get_api_url()

    if token and active:
        try:
            with httpx.Client(timeout=10.0) as client:
                sync_resp = client.post(
                    f"{api_url}/projects/{active['id']}/audits",
                    json={
                        "target_path": str(path),
                        "trust_score": float(report.get("trust_score", 0.0)),
                        "summary": str(report.get("summary", "")),
                        "recommendation": str(report.get("recommendation", "UNKNOWN")),
                        "commit_sha": "cli-local",
                        "findings": report.get("findings", [])
                    },
                    headers={"Authorization": f"Bearer {token}"}
                )
                if sync_resp.status_code in (200, 201):
                    theme.success(f"Results synced to project '{active['name']}' in the web dashboard.")
                    theme.info("Open the web dashboard to inspect this audit.")
        except Exception:
            pass

    if report.get("recommendation") in ("BLOCK", "REQUEST_CHANGES") or report.get("trust_score", 100) < 80:
        return EXIT_AUDIT_FAILURE
    return EXIT_SUCCESS


@app.command(name="audit", rich_help_panel="Verification")
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
    code = execute_audit_flow(path, verbose=verbose, json_output=json_output)
    raise typer.Exit(code=code)


def _display_rich_report(report: dict, verbose: bool = False):
    score = float(report.get("trust_score", 0.0))
    recommendation = report.get("recommendation", "UNKNOWN")
    target = report.get("target_path") or "audit"

    console.print()
    console.print(theme.verdict_panel(score, recommendation, report.get("summary", ""), target))

    statuses = report.get("agent_statuses", {})
    contributions = report.get("agent_contributions", {})
    agents = theme.table("Agents", [
        ("Agent", {"style": "bold", "no_wrap": True}),
        ("Status", {"no_wrap": True}),
        ("Findings", {"justify": "right"}),
    ])
    for agent, status in statuses.items():
        agents.add_row(agent, theme.status_text("ok" if status == "OK" else "warn"), str(contributions.get(agent, 0)))
    console.print(agents)

    breakdown = report.get("severity_breakdown", {})
    line = Text("Severity   ", style=theme.MUTED)
    for label in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        line.append_text(theme.severity_text(label))
        line.append(f" {breakdown.get(label, 0)}    ", style="")
    console.print(line)

    findings = report.get("findings", [])
    actionable = [f for f in findings if (f.get("severity") or "INFO").upper() in ("CRITICAL", "HIGH", "MEDIUM", "LOW")]
    displayed = actionable if actionable else [
        f for f in findings if not (isinstance(f.get("evidence"), dict) and "called_api" in f.get("evidence", {}))
    ]

    if displayed:
        columns = [
            ("Severity", {"no_wrap": True}),
            ("Agent", {"style": theme.MUTED, "no_wrap": True}),
            ("Finding", {"style": "bold", "overflow": "fold", "max_width": 50}),
            ("Location", {"style": theme.MUTED, "overflow": "fold", "max_width": 36}),
        ]
        if verbose:
            columns.append(("Evidence", {"style": theme.MUTED, "overflow": "fold", "max_width": 60}))
        shown = displayed if verbose else displayed[:15]
        grid = theme.table("Findings" if not verbose else "Findings (with evidence)", columns)
        for f in shown:
            location = f"{f.get('file_path') or 'target'}:{f.get('line_number') or '-'}"
            row = [theme.severity_text(f.get("severity")), f.get("agent_name") or "-", str(f.get("title", "")), location]
            if verbose:
                evidence = str(f.get("evidence", ""))
                row.append(evidence if len(evidence) <= 240 else evidence[:237] + "...")
            grid.add_row(*row)
        console.print(grid)
        if not verbose and len(displayed) > 15:
            theme.info(f"Showing 15 of {len(displayed)} findings. Use --verbose for evidence, or open the web dashboard.")
    elif findings:
        theme.success(f"All {len(findings)} checks passed with no defects reported.")




# ========================================================
# 6. INTERACTIVE DASHBOARD (AGY-STYLE TERMINAL UI)
# ========================================================

def print_dashboard_banner():
    """
    Renders the status line shown above the interactive menu.
    """
    token = AuthManager.get_token()
    user_info = AuthManager.get_cached_user()
    active_proj = CLIConfig.get_active_project()

    parts = []
    if token and user_info:
        parts.append(f"Signed in as {user_info.get('name', 'user')} <{user_info.get('email', '')}>")
    elif token:
        parts.append("Signed in")
    else:
        parts.append("Not signed in")
    if active_proj:
        parts.append(f"Project {active_proj['name']}")
    theme.header(" · ".join(parts))


def print_menu_options(is_authenticated: bool):
    """
    Renders the action menu. Actions that need an account are listed only after sign-in.
    """
    menu = theme.table(None, [
        ("Key", {"style": f"bold {theme.ACCENT}", "no_wrap": True}),
        ("Action", {"style": "bold", "no_wrap": True}),
        ("Description", {"style": theme.MUTED, "overflow": "fold"}),
    ])
    if not is_authenticated:
        menu.add_row("1", "Sign in", "Sign in with email and password")
        menu.add_row("2", "Create account", "Register with email and password")
        menu.add_row("3", "Continue with Google", "Sign in through your browser")
        menu.add_row("4", "Demo account", "Development only: quick sign-in for testing")
        menu.add_row("5", "Check environment", "Verify the tools Sceptic needs")
        menu.add_row("0", "Exit", "Leave Sceptic")
    else:
        menu.add_row("1", "Run audit", "Verify a file or directory with every agent")
        menu.add_row("2", "Feature analysis", "Estimate feasibility, complexity, and risk of a change")
        menu.add_row("3", "Projects", "List, switch, or create projects")
        menu.add_row("4", "Account", "View your profile or sign out")
        menu.add_row("5", "Check environment", "Verify the tools Sceptic needs")
        menu.add_row("6", "History", "Recent audits and feature analyses for the active project")
        menu.add_row("0", "Exit", "Leave Sceptic")
    console.print(menu)
    console.print()




def _interactive_audit():
    console.print("\n[bold cyan]─── Run Verification Audit ───[/bold cyan]")
    target_path = Prompt.ask("Enter path to file or directory to audit", default=".")
    verbose_str = Prompt.ask("Show detailed findings and evidence? [y/N]", default="n")
    verbose = verbose_str.lower().startswith("y")
    console.print()
    try:
        execute_audit_flow(target_path, verbose=verbose, json_output=False)
    except Exception as e:
        console.print(f"[bold red]Audit encountered an error:[/bold red] {e}")
    Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def _interactive_newfeature():
    token = AuthManager.get_token()
    if not token:
        console.print("\n[yellow]You must be logged in to analyze features. Select [4] to login.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return
    active = CLIConfig.get_active_project()
    if not active:
        console.print("\n[yellow]No active project selected. Select [3] to choose or create a project.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return

    console.print(f"\n[bold cyan]─── Analyze New Feature for '{active['name']}' ───[/bold cyan]")
    desc = Prompt.ask("Enter feature proposal description")
    if not desc.strip():
        console.print("[yellow]Description cannot be empty.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return

    try:
        newfeature(desc.strip())
    except typer.Exit:
        pass
    except Exception as e:
        console.print(f"[bold red]Analysis error:[/bold red] {e}")
    Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def _interactive_project():
    token = AuthManager.get_token()
    if not token:
        console.print("\n[yellow]You must be logged in to manage projects. Select [4] to login.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return

    console.print("\n[bold cyan]─── Project Management ───[/bold cyan]")
    try:
        project_cmd(select_id=None, create_name=None, repo_url=None)
    except typer.Exit:
        pass

    console.print("\n[1] Switch active project  [2] Create new project  [0] Back to main menu")
    subchoice = Prompt.ask("[cyan]Select action[/cyan]", default="0")
    if subchoice == "1":
        proj_id = Prompt.ask("Enter Project ID to activate")
        if proj_id.strip():
            try:
                project_cmd(select_id=proj_id.strip(), create_name=None, repo_url=None)
            except typer.Exit:
                pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
    elif subchoice == "2":
        name = Prompt.ask("Enter new project name")
        repo = Prompt.ask("Repository URL (optional)", default="")
        if name.strip():
            try:
                project_cmd(select_id=None, create_name=name.strip(), repo_url=repo.strip() or None)
            except typer.Exit:
                pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def _interactive_account():
    token = AuthManager.get_token()
    console.print("\n[bold cyan]─── User Account & Authentication ───[/bold cyan]")
    if token:
        try:
            whoami()
        except typer.Exit:
            pass
        console.print("\n[1] Logout  [0] Back to main menu")
        act = Prompt.ask("[cyan]Select action[/cyan]", default="0")
        if act == "1":
            try:
                logout()
            except typer.Exit:
                pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
    else:
        console.print("[yellow]You are not currently logged in.[/yellow]\n")
        console.print("[1] Login with Email & Password")
        console.print("[2] Register new account (Email & Password)")
        console.print("[3] Login with Google (Browser OAuth)")
        console.print("[4] Dev Mock Login (Test Email)")
        console.print("[0] Back to main menu\n")
        act = Prompt.ask("[cyan]Select action[/cyan]", default="1")
        if act == "1":
            em = prompt_input("Email address")
            pw = prompt_input("Password")
            if em and pw:
                try:
                    execute_login(email=em, password=pw)
                except typer.Exit:
                    pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        elif act == "2":
            nm = prompt_input("Full Name")
            em = prompt_input("Email address")
            pw = prompt_input("Password (min 6 chars)")
            if nm and em and pw:
                try:
                    execute_register(name=nm, email=em, password=pw)
                except typer.Exit:
                    pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        elif act == "3":
            try:
                execute_login(google=True)
            except typer.Exit:
                pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        elif act == "4":
            email = Prompt.ask("Enter dev mock email", default="dev@sceptic.ai")
            try:
                execute_login(mock_email=email)
            except typer.Exit:
                pass
            Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def _interactive_doctor():
    console.print("\n[bold cyan]─── Environment & System Diagnostics ───[/bold cyan]\n")
    try:
        doctor()
    except typer.Exit:
        pass
    except Exception as e:
        console.print(f"[bold red]Diagnostic error:[/bold red] {e}")
    Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def _interactive_history():
    token = AuthManager.get_token()
    if not token:
        console.print("\n[yellow]You must be logged in to view history. Select [4] to login.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return
    active = CLIConfig.get_active_project()
    if not active:
        console.print("\n[yellow]No active project selected. Select [3] to choose or create a project.[/yellow]")
        Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
        return

    console.print(f"\n[bold cyan]─── Project History: {active['name']} ───[/bold cyan]\n")
    try:
        history()
    except typer.Exit:
        pass
    except Exception as e:
        console.print(f"[bold red]History error:[/bold red] {e}")
    Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")


def interactive_dashboard():
    """
    Main interactive loop for the Sceptic CLI dashboard.
    Enforces authentication gating so features are unlocked only after login or sign up.
    """
    while True:
        try:
            token = AuthManager.get_token()
            is_authenticated = bool(token)

            print_dashboard_banner()
            print_menu_options(is_authenticated)

            choice = Prompt.ask("[bold cyan]sceptic[/bold cyan] > ", default="1").strip()

            if choice in ("0", "exit", "quit", "q"):
                console.print("\n[dim]Session closed.[/dim]\n")
                break

            if not is_authenticated:
                if choice == "1":
                    em = prompt_input("Email address")
                    pw = prompt_input("Password")
                    if em and pw:
                        try:
                            execute_login(email=em, password=pw)
                        except typer.Exit:
                            pass
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
                elif choice == "2":
                    nm = prompt_input("Full Name")
                    em = prompt_input("Email address")
                    pw = prompt_input("Password (min 6 chars)")
                    if nm and em and pw:
                        try:
                            execute_register(name=nm, email=em, password=pw)
                        except typer.Exit:
                            pass
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
                elif choice == "3":
                    try:
                        execute_login(google=True)
                    except typer.Exit:
                        pass
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
                elif choice == "4":
                    email = Prompt.ask("Enter dev mock email", default="dev@sceptic.ai")
                    try:
                        execute_login(mock_email=email)
                    except typer.Exit:
                        pass
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
                elif choice == "5":
                    _interactive_doctor()
                else:
                    console.print("[yellow]Please login or sign up first to access verification features.[/yellow]")
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
            else:
                if choice in ("1", "audit"):
                    _interactive_audit()
                elif choice in ("2", "feature", "newfeature"):
                    _interactive_newfeature()
                elif choice in ("3", "project", "projects"):
                    _interactive_project()
                elif choice in ("4", "account", "logout", "whoami"):
                    _interactive_account()
                elif choice in ("5", "doctor"):
                    _interactive_doctor()
                elif choice in ("6", "history"):
                    _interactive_history()
                elif choice in ("status",):
                    try:
                        status()
                    except typer.Exit:
                        pass
                    Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]", default="")
                else:
                    console.print(f"[yellow]Unknown option '{choice}'. Please select an option [0-6].[/yellow]")
                    Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[dim]Session closed.[/dim]\n")
            break


if __name__ == "__main__":
    app()
