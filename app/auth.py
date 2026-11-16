"""Lightweight role-based authentication.

Issues HMAC-signed session tokens (no external dependency). In a real
deployment this module is the integration point for Enterprise SSO / OAuth 2.0
(BD-08); the role -> permission model below stays the same.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from functools import lru_cache
from typing import Optional

from .config import get_settings

# Role -> permission set. (BRD section 9)
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": {"view", "create", "update", "delete", "download", "chat", "admin"},
    "Project Manager": {"view", "update", "download", "chat"},
    "Developer": {"view", "update", "download", "chat"},
    "Business User": {"view", "download", "chat"},
    "Read-Only User": {"view"},
}


def _hash(pw: str) -> str:
    """Salted sha256 of a password. Salt comes from configuration (.env)."""
    return hashlib.sha256((get_settings().auth_password_salt + pw).encode()).hexdigest()


@lru_cache(maxsize=1)
def _user_directory() -> dict[str, dict]:
    """Build the user directory from configured demo users (passwords hashed)."""
    return {
        username: {
            "password": _hash(info["password"]),
            "role": info["role"],
            "name": info["name"],
        }
        for username, info in get_settings().demo_users.items()
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def authenticate(username: str, password: str) -> Optional[dict]:
    user = _user_directory().get(username.strip().lower())
    if not user:
        return None
    if not hmac.compare_digest(user["password"], _hash(password)):
        return None
    return {"username": username.strip().lower(), "role": user["role"], "name": user["name"]}


def issue_token(user: dict) -> str:
    payload = {
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
        "exp": int(time.time()) + get_settings().session_ttl_seconds,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(
        get_settings().app_secret_key.encode(), body.encode(), hashlib.sha256
    ).digest()
    return f"{body}.{_b64url(sig)}"


def verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        get_settings().app_secret_key.encode(), body.encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(_b64url(expected), sig):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (json.JSONDecodeError, ValueError):
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for(role)
