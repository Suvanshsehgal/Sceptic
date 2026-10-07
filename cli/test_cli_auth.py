"""
Tests for foundational CLI commands: login, logout, whoami, project, newfeature, history, status, doctor.
"""
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from cli.main import app, EXIT_SUCCESS, EXIT_CLI_ERROR
from cli.auth_manager import AuthManager
from cli.config import CLIConfig

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_auth():
    AuthManager.clear_credentials()
    yield
    AuthManager.clear_credentials()


def test_cli_whoami_unauthenticated():
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == EXIT_CLI_ERROR
    assert "Not logged in" in result.stdout


def test_cli_doctor_command():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Sceptic Environment Diagnostics" in result.stdout
    assert "Python Runtime" in result.stdout


def test_cli_status_command():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Backend API" in result.stdout
    assert "Not Logged In" in result.stdout


def test_cli_logout_clears_credentials():
    AuthManager.store_token("mock-token", {"name": "Test User", "email": "test@example.com"})
    assert AuthManager.get_token() == "mock-token"
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Successfully logged out" in result.stdout
    assert AuthManager.get_token() is None


def test_cli_login_mock_flow():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "valid-mock-jwt-token",
        "user": {"name": "Alice Developer", "email": "alice@sceptic.dev", "id": "123"}
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        result = runner.invoke(app, ["login", "--mock-email", "alice@sceptic.dev"])
        assert result.exit_code == EXIT_SUCCESS
        assert "Successfully logged in as" in result.stdout
        assert "alice@sceptic.dev" in result.stdout
        assert AuthManager.get_token() == "valid-mock-jwt-token"


def test_cli_whoami_authenticated():
    AuthManager.store_token("valid-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "Alice",
        "email": "alice@sceptic.dev",
        "id": "u-1234"
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == EXIT_SUCCESS
        assert "Alice" in result.stdout
        assert "alice@sceptic.dev" in result.stdout


def test_cli_project_create_and_list():
    AuthManager.store_token("valid-token")

    # Mock list projects
    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = [
        {"id": "p-1", "name": "Core Platform", "repository_url": "https://github.com/org/repo"}
    ]

    with patch("httpx.Client.get", return_value=mock_list_resp):
        result = runner.invoke(app, ["project"])
        assert result.exit_code == EXIT_SUCCESS
        assert "Core Platform" in result.stdout


def test_cli_newfeature_flow():
    AuthManager.store_token("valid-token")
    CLIConfig.set_active_project("p-1", "Core Platform")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "fa-1",
        "feature_description": "Implement Webhook Verification",
        "feasibility_score": 90.0,
        "complexity_score": 40.0,
        "risk_score": 20.0,
        "confidence_score": 95.0,
        "implementation_plan": "Step 1: Add HMAC signature validation."
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        result = runner.invoke(app, ["newfeature", "Implement Webhook Verification"])
        assert result.exit_code == EXIT_SUCCESS
        assert "Feature Feasibility Assessment" in result.stdout
        assert "90.0%" in result.stdout
        assert "Step 1: Add HMAC signature validation" in result.stdout
