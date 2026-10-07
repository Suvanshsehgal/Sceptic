"""
Authentication and security utility functions.
Handles JWT creation, verification, passwordless token management, and Google OAuth OpenID Connect.
"""
import os
import sys
import time
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from uuid import UUID

import jwt
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure backend dir is in sys.path
backend_dir = os.path.abspath(os.path.dirname(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import models
from database import get_db

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "sceptic-super-secret-dev-jwt-key-32-chars-long!")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify plain password against PBKDF2-HMAC-SHA256 hash."""
    if not hashed_password or "$" not in hashed_password:
        return False
    try:
        salt, key_hex = hashed_password.split("$", 1)
        key = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(key.hex(), key_hex)
    except Exception:
        return False



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a signed JWT access token for a Sceptic user."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies a JWT access token and returns the payload if valid."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> models.User:
    """
    FastAPI dependency to extract and authenticate the current user via Bearer token.
    Raises 401 Unauthorized if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(models.User).filter(models.User.id == user_uuid)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[models.User]:
    """Returns the current user if a valid token is provided, otherwise None."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def get_google_auth_url(state: str, redirect_uri: Optional[str] = None) -> str:
    """Builds the Google OAuth authorization redirect URL."""
    actual_redirect = redirect_uri or GOOGLE_REDIRECT_URI
    scope = "openid email profile"
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?response_type=code"
        f"&client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={actual_redirect}"
        f"&scope={scope}"
        f"&state={state}"
        f"&access_type=offline"
        f"&prompt=select_account"
    )
    return url


async def exchange_google_code_for_user_info(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """
    Exchanges a Google OAuth authorization code for Google user information.
    """
    actual_redirect = redirect_uri or GOOGLE_REDIRECT_URI
    token_url = "https://oauth2.googleapis.com/token"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": actual_redirect,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"}
        )

        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to retrieve Google token: {token_resp.text}"
            )

        token_data = token_resp.json()
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")

        # Fetch user info from Google userinfo endpoint
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to retrieve Google user profile"
            )

        return userinfo_resp.json()
