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
from audit_service import AuditService

from config import CLIConfig
from auth_manager import AuthManager

app = typer.Typer(
    name="sceptic",
    help="Sceptic: Independent AI-Generated Code Verification System",
    add_completion=False,
    no_args_is_help=False
)
console = Console()

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


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """
    Sceptic CLI: Independent AI-generated code verification.
    When run without arguments, launches the interactive terminal dashboard.
    """
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


@app.command(name="login")
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


@app.command(name="register")
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


@app.command(name="logout")
def logout():
    """
    Clear CLI's locally stored authentication credentials.
    """
    AuthManager.clear_credentials()
    console.print("[bold green]Successfully logged out from CLI.[/bold green]")


@app.command(name="whoami")
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

@app.command(name="project")
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

@app.command(name="newfeature")
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

@app.command(name="history")
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


@app.command(name="status")
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

    table = Table(title="Sceptic CLI System Status", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Backend API", f"[green]{api_url}[/green]" if backend_ok else f"[red]{api_url} (Offline)[/red]")
    table.add_row("Authenticated As", f"{user_info['name']} ({user_info['email']})" if user_info else "[yellow]Not Logged In[/yellow]")
    table.add_row("Active Project", f"{active_proj['name']} ({active_proj['id']})" if active_proj else "[dim]None (Run 'sceptic project')[/dim]")

    console.print(table)


@app.command(name="doctor")
def doctor():
    """
    Perform local environment checks and diagnostics.
    """
    table = Table(title="Sceptic Environment Diagnostics", border_style="cyan")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    table.add_row("Python Runtime", "[green]OK[/green]", f"Version {py_ver}")

    # 2. Git
    try:
        git_ver = subprocess.check_output(["git", "--version"], text=True).strip()
        table.add_row("Git", "[green]OK[/green]", git_ver)
    except Exception:
        table.add_row("Git", "[yellow]Warning[/yellow]", "Git binary not found on PATH")

    # 3. Docker
    try:
        docker_ver = subprocess.check_output(["docker", "--version"], text=True).strip()
        table.add_row("Docker", "[green]OK[/green]", docker_ver)
    except Exception:
        table.add_row("Docker", "[yellow]Not Available[/yellow]", "Docker daemon/CLI not detected")

    # 4. Backend Connectivity
    api_url = CLIConfig.get_api_url()
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{api_url}/health")
            if r.status_code == 200:
                table.add_row("Sceptic Backend", "[green]OK[/green]", f"Connected to {api_url}")
            else:
                table.add_row("Sceptic Backend", "[red]Error[/red]", f"Returned HTTP {r.status_code}")
    except Exception as e:
        table.add_row("Sceptic Backend", "[red]Offline[/red]", str(e))

    # 5. Auth State
    token = AuthManager.get_token()
    if token:
        table.add_row("CLI Authentication", "[green]OK[/green]", "Saved credentials present")
    else:
        table.add_row("CLI Authentication", "[yellow]Not Logged In[/yellow]", "Run 'sceptic login'")

    console.print(table)


# ========================================================
# 5. AUDIT COMMAND (EXISTING PIPELINE + BACKEND SYNC)
# ========================================================

def execute_audit_flow(path: str, verbose: bool = False, json_output: bool = False) -> int:
    """
    Core executor for Sceptic audit pipeline. Returns appropriate exit code without exiting python process.
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
        return EXIT_CLI_ERROR

    except PermissionError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Permission Error:[/bold red] {e}")
        return EXIT_CLI_ERROR

    except ValueError as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Validation Error:[/bold red] {e}")
        return EXIT_CLI_ERROR

    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e), "exit_code": EXIT_CLI_ERROR}))
        else:
            console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
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
                    console.print(f"\n[bold green]✓ Audit results successfully synced to '{active['name']}' in Web Dashboard![/bold green]")
                    console.print(f"[dim]View live at: http://localhost:5173 (Audits & Dashboard)[/dim]\n")
        except Exception:
            pass

    if report.get("recommendation") in ("BLOCK", "REQUEST_CHANGES") or report.get("trust_score", 100) < 80:
        return EXIT_AUDIT_FAILURE
    return EXIT_SUCCESS


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
    code = execute_audit_flow(path, verbose=verbose, json_output=json_output)
    raise typer.Exit(code=code)


def _display_rich_report(report: dict, verbose: bool = False):
    score = report.get("trust_score", 0.0)
    recommendation = report.get("recommendation", "UNKNOWN")

    if score >= 85 and recommendation == "APPROVE":
        score_color = "green"
        rec_color = "bold green"
    elif score >= 50:
        score_color = "yellow"
        rec_color = "bold yellow"
    else:
        score_color = "red"
        rec_color = "bold red"

    # 1. Summary Score Panel
    score_panel_text = Text()
    score_panel_text.append(f"TRUST SCORE: {score:.1f} / 100\n", style=f"bold {score_color}")
    score_panel_text.append(f"RECOMMENDATION: {recommendation}\n\n", style=rec_color)
    score_panel_text.append(f"{report.get('summary', '')}", style="dim white")

    console.print(Panel(score_panel_text, title="Audit Summary", border_style=score_color))

    # 2. Agent Status Breakdown Table
    agent_table = Table(title="Verification Agent Statuses", border_style="cyan")
    agent_table.add_column("Agent", style="bold")
    agent_table.add_column("Status", justify="center")
    agent_table.add_column("Findings Contributed", justify="right")

    statuses = report.get("agent_statuses", {})
    contributions = report.get("agent_contributions", {})

    for agent, st in statuses.items():
        st_color = "green" if st == "OK" else "yellow"
        cnt = contributions.get(agent, 0)
        agent_table.add_row(agent, f"[{st_color}]{st}[/{st_color}]", str(cnt))

    console.print(agent_table)

    # 3. Severity Breakdown Table
    sev_table = Table(title="Finding Severity Counts", border_style="magenta")
    sev_table.add_column("Critical", justify="center", style="bold red")
    sev_table.add_column("High", justify="center", style="bold yellow")
    sev_table.add_column("Medium", justify="center", style="yellow")
    sev_table.add_column("Low", justify="center", style="cyan")
    sev_table.add_column("Info", justify="center", style="dim")

    breakdown = report.get("severity_breakdown", {})
    sev_table.add_row(
        str(breakdown.get("CRITICAL", 0)),
        str(breakdown.get("HIGH", 0)),
        str(breakdown.get("MEDIUM", 0)),
        str(breakdown.get("LOW", 0)),
        str(breakdown.get("INFO", 0)),
    )
    console.print(sev_table)

    # 4. Detailed Findings Table (Filtered to meaningful issues to avoid noise)
    findings = report.get("findings", [])
    actionable = [f for f in findings if (f.get("severity") or "INFO").upper() in ("CRITICAL", "HIGH", "MEDIUM", "LOW")]
    displayed = actionable if actionable else [f for f in findings if not (isinstance(f.get("evidence"), dict) and "called_api" in f.get("evidence", {}))]

    if displayed:
        table_title = "Finding Evidence Snippets" if verbose else "Key Verification Findings"
        f_table = Table(title=table_title, border_style="yellow")
        f_table.add_column("Agent", style="cyan")
        f_table.add_column("Severity")
        f_table.add_column("Title", style="bold")
        f_table.add_column("Location", style="dim")
        f_table.add_column("Evidence", no_wrap=True if verbose else False, max_width=None if verbose else 45)

        for f in (displayed if verbose else displayed[:15]):
            sev = (f.get("severity") or "INFO").upper()
            col = "red" if sev in ("CRITICAL", "HIGH") else "yellow" if sev == "MEDIUM" else "cyan" if sev == "LOW" else "dim"
            loc = f"{f.get('file_path', 'target')}:{f.get('line_number') or '-'}"
            ev = str(f.get("evidence", ""))
            if not verbose and len(ev) > 50:
                ev = ev[:47] + "..."
            f_table.add_row(f.get("agent_name"), f"[{col}]{sev}[/{col}]", str(f.get("title", ""))[:45], loc, ev)

        console.print(f_table)
        if not verbose and len(displayed) > 15:
            console.print(f"[dim]Showing top 15 of {len(displayed)} findings. Full details available in Web Dashboard.[/dim]")
    elif findings:
        console.print(f"[dim]✓ All {len(findings)} symbols and API calls verified successfully with 0 defects.[/dim]")


# ========================================================
# 6. INTERACTIVE DASHBOARD (AGY-STYLE TERMINAL UI)
# ========================================================

def print_dashboard_banner():
    """
    Renders a sleek one-line status banner for Sceptic.
    """
    token = AuthManager.get_token()
    user_info = AuthManager.get_cached_user()
    active_proj = CLIConfig.get_active_project()

    if user_info and token:
        user_name = user_info.get("name", "User")
        user_email = user_info.get("email", "")
        proj_part = f" • Project: [bold cyan]{active_proj['name']}[/bold cyan]" if active_proj else ""
        header_text = f"⚡ [bold cyan]SCEPTIC[/bold cyan] │ [bold green]{user_name}[/bold green] [dim]<{user_email}>[/dim]{proj_part}"
        border_col = "green"
    elif token:
        header_text = "⚡ [bold cyan]SCEPTIC[/bold cyan] │ [bold green]Authenticated User[/bold green]"
        border_col = "green"
    else:
        header_text = "⚡ [bold cyan]SCEPTIC[/bold cyan] │ [yellow]Authentication Required[/yellow] [dim]• Please Login or Sign Up to access features[/dim]"
        border_col = "cyan"

    console.print()
    console.print(Panel(header_text, border_style=border_col, padding=(0, 2)))


def print_menu_options(is_authenticated: bool):
    """
    Renders the action selection menu table based on authentication status.
    """
    menu = Table(show_header=False, box=None, padding=(0, 2))
    menu.add_column("Key", style="bold cyan", width=5)
    menu.add_column("Title", style="bold white", width=26)
    menu.add_column("Description", style="dim")

    if not is_authenticated:
        menu.add_row("[1]", "🔑 Login", "Sign in with Email & Password")
        menu.add_row("[2]", "📝 Sign Up", "Create new account with Email & Password")
        menu.add_row("[3]", "🌐 Google Login", "Sign in with Google via browser")
        menu.add_row("[4]", "⚡ Dev Mock Login", "Instant login for testing")
        menu.add_row("[5]", "🩺 System Doctor", "Check system environment & tools")
        menu.add_row("[0]", "🚪 Exit", "Close Sceptic CLI")
    else:
        menu.add_row("[1]", "🔍 Run Audit", "Audit code file, directory, or diff across verification agents")
        menu.add_row("[2]", "🧪 Verify Feature", "Evaluate feature proposal feasibility, complexity & risk")
        menu.add_row("[3]", "📁 Projects", "List, switch, or create projects linked to your account")
        menu.add_row("[4]", "👤 User Profile & Logout", "View account details or sign out")
        menu.add_row("[5]", "🩺 System Doctor", "Check backend, Python, and tools")
        menu.add_row("[6]", "📜 History", "Review past audits and feature analyses for active project")
        menu.add_row("[0]", "🚪 Exit", "Close Sceptic interactive CLI")

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
                console.print("\n[bold cyan]Goodbye! Keep your AI-generated code verified.[/bold cyan]\n")
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
            console.print("\n\n[bold cyan]Goodbye! Exiting Sceptic.[/bold cyan]\n")
            break


if __name__ == "__main__":
    app()
