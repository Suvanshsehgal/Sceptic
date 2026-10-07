"""
CLI configuration and state manager.
Stores user settings (e.g. backend API URL, active project ID) in ~/.sceptic/config.json.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

SCEPTIC_DIR = Path.home() / ".sceptic"
CONFIG_FILE = SCEPTIC_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_url": os.getenv("SCEPTIC_API_URL", "http://localhost:8000"),
    "active_project_id": None,
    "active_project_name": None
}


class CLIConfig:
    @staticmethod
    def _ensure_dir():
        SCEPTIC_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> Dict[str, Any]:
        cls._ensure_dir()
        if not CONFIG_FILE.exists():
            cls.save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            return dict(DEFAULT_CONFIG)

    @classmethod
    def save(cls, config: Dict[str, Any]) -> None:
        cls._ensure_dir()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    @classmethod
    def get_api_url(cls) -> str:
        return cls.load().get("api_url", "http://localhost:8000")

    @classmethod
    def set_active_project(cls, project_id: str, project_name: str) -> None:
        cfg = cls.load()
        cfg["active_project_id"] = project_id
        cfg["active_project_name"] = project_name
        cls.save(cfg)

    @classmethod
    def get_active_project(cls) -> Optional[Dict[str, str]]:
        cfg = cls.load()
        pid = cfg.get("active_project_id")
        pname = cfg.get("active_project_name")
        if pid:
            return {"id": pid, "name": pname or "Unnamed Project"}
        return None
