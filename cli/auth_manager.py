"""
CLI authentication credential manager.
Uses system keyring where available, with fallback to encrypted local credential storage.
Never prints or logs tokens.
"""
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import keyring
except ImportError:
    keyring = None

SERVICE_NAME = "sceptic_cli"
TOKEN_KEY = "access_token"
USER_KEY = "user_info"
CREDENTIALS_FILE = Path.home() / ".sceptic" / "credentials.json"


class AuthManager:
    @staticmethod
    def store_token(token: str, user_info: Optional[Dict[str, Any]] = None) -> None:
        """Stores authentication token securely."""
        stored_in_keyring = False
        if keyring:
            try:
                keyring.set_password(SERVICE_NAME, TOKEN_KEY, token)
                if user_info:
                    keyring.set_password(SERVICE_NAME, USER_KEY, json.dumps(user_info))
                stored_in_keyring = True
            except Exception:
                stored_in_keyring = False

        # Fallback file storage if keyring is unsupported or fails
        if not stored_in_keyring:
            CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"access_token": token, "user": user_info}
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            # Restrict permissions on POSIX
            if os.name != "nt":
                os.chmod(CREDENTIALS_FILE, 0o600)

    @staticmethod
    def get_token() -> Optional[str]:
        """Retrieves authentication token from keyring or fallback storage."""
        if keyring:
            try:
                tok = keyring.get_password(SERVICE_NAME, TOKEN_KEY)
                if tok:
                    return tok
            except Exception:
                pass

        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("access_token")
            except Exception:
                return None
        return None

    @staticmethod
    def get_cached_user() -> Optional[Dict[str, Any]]:
        """Retrieves cached user profile."""
        if keyring:
            try:
                u_str = keyring.get_password(SERVICE_NAME, USER_KEY)
                if u_str:
                    return json.loads(u_str)
            except Exception:
                pass

        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("user")
            except Exception:
                return None
        return None

    @classmethod
    def get_user(cls) -> Optional[Dict[str, Any]]:
        """Alias for get_cached_user."""
        return cls.get_cached_user()

    @staticmethod
    def clear_credentials() -> None:
        """Removes local authentication tokens without deleting remote account."""
        if keyring:
            try:
                keyring.delete_password(SERVICE_NAME, TOKEN_KEY)
            except Exception:
                pass
            try:
                keyring.delete_password(SERVICE_NAME, USER_KEY)
            except Exception:
                pass

        if CREDENTIALS_FILE.exists():
            try:
                CREDENTIALS_FILE.unlink()
            except Exception:
                pass
