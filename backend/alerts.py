"""
Outbound alert dispatcher for Slack and Discord.

Sends a message when a Watchdog check breaches its thresholds or a rollback completes.
Configuration (both optional, HTTPS only):
- ALERT_SLACK_WEBHOOK_URL: Slack incoming webhook URL
- ALERT_DISCORD_WEBHOOK_URL: Discord webhook URL

Delivery is best effort. dispatch_alert never raises, so an unreachable chat service cannot change a
verification result or a rollback outcome. It returns the delivery status for each channel.
"""
import os
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger("sceptic.alerts")

DISCORD_CONTENT_LIMIT = 1900  # Discord rejects messages over 2000 characters


def _configured_url(name: str) -> str:
    url = os.getenv(name, "").strip()
    if url and not url.lower().startswith("https://"):
        logger.error(f"{name} must be an https:// URL; alert channel ignored.")
        return ""
    return url


def _format_message(title: str, details: Dict[str, Any]) -> str:
    lines = [f"*{title}*"]
    lines.extend(f"- {key}: {value}" for key, value in details.items())
    return "\n".join(lines)


async def _post(client: httpx.AsyncClient, channel: str, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = await client.post(url, json=body)
        return {"delivered": 200 <= resp.status_code < 300, "status_code": resp.status_code}
    except httpx.HTTPError as e:
        logger.warning(f"Alert delivery to {channel} failed: {type(e).__name__}")
        return {"delivered": False, "error": type(e).__name__}


async def dispatch_alert(title: str, details: Dict[str, Any]) -> Dict[str, Any]:
    """Posts the alert to every configured channel. Never raises."""
    try:
        slack_url = _configured_url("ALERT_SLACK_WEBHOOK_URL")
        discord_url = _configured_url("ALERT_DISCORD_WEBHOOK_URL")
        if not slack_url and not discord_url:
            return {"delivered": False, "reason": "no alert channel configured"}

        message = _format_message(title, details)
        results: Dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            if slack_url:
                results["slack"] = await _post(client, "slack", slack_url, {"text": message})
            if discord_url:
                results["discord"] = await _post(
                    client, "discord", discord_url, {"content": message[:DISCORD_CONTENT_LIMIT]}
                )
        return results
    except Exception as e:  # defensive: alerting must never break verification or recovery
        logger.error(f"Alert dispatch failed unexpectedly: {type(e).__name__}")
        return {"delivered": False, "error": type(e).__name__}
