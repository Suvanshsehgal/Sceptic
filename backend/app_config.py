"""
Sceptic Backend Configuration & Settings Manager.
Centralizes environment settings for services, thresholds, and timeouts.
"""
import os
from typing import Optional
from dotenv import load_dotenv

# Ensure .env is loaded
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class Settings:
    @property
    def PROMETHEUS_URL(self) -> str:
        return os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")

    @property
    def TARGET_SERVICE_URL(self) -> str:
        return os.getenv("TARGET_SERVICE_URL", "http://localhost:8080").rstrip("/")

    @property
    def WATCHDOG_ERROR_RATE_THRESHOLD(self) -> float:
        return float(os.getenv("WATCHDOG_ERROR_RATE_THRESHOLD", "0.05"))

    @property
    def WATCHDOG_LATENCY_P95_THRESHOLD(self) -> float:
        return float(os.getenv("WATCHDOG_LATENCY_P95_THRESHOLD", "0.5"))

    @property
    def WATCHDOG_MIN_REQUESTS(self) -> int:
        return int(os.getenv("WATCHDOG_MIN_REQUESTS", "10"))

    @property
    def WATCHDOG_HEALTH_TIMEOUT(self) -> float:
        return float(os.getenv("WATCHDOG_HEALTH_TIMEOUT", "5.0"))

    @property
    def WATCHDOG_PROMETHEUS_TIMEOUT(self) -> float:
        return float(os.getenv("WATCHDOG_PROMETHEUS_TIMEOUT", "5.0"))

    @property
    def WATCHDOG_LOOKBACK_MINUTES(self) -> int:
        return int(os.getenv("WATCHDOG_LOOKBACK_MINUTES", "5"))

    @property
    def ROLLBACK_HEALTH_TIMEOUT(self) -> float:
        return float(os.getenv("ROLLBACK_HEALTH_TIMEOUT", "15.0"))

    @property
    def ROLLBACK_POLL_INTERVAL(self) -> float:
        return float(os.getenv("ROLLBACK_POLL_INTERVAL", "1.0"))

    @property
    def ROLLBACK_SERVICE_READY_WAIT(self) -> float:
        return float(os.getenv("ROLLBACK_SERVICE_READY_WAIT", "1.0"))


settings = Settings()


def get_settings() -> Settings:
    return settings
