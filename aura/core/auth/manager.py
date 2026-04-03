"""JWT-style local authentication manager."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AuthError(RuntimeError):
    """Raised when authentication fails."""


@dataclass(slots=True)
class AuthRecord:
    user_id: str
    username: str


class AuthManager:
    """Register users and issue signed tokens."""

    def __init__(self, data_path: str | Path, secret: str | None = None) -> None:
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.users_db = self.data_path / "users.db"
        self.secret = (secret or os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)).encode("utf-8")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.users_db)

    def _init_db(self) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return "pbkdf2$" + base64.urlsafe_b64encode(salt).decode("ascii") + "$" + base64.urlsafe_b64encode(digest).decode("ascii")

    def _verify_password(self, password: str, stored: str) -> bool:
        if not stored.startswith("pbkdf2$"):
            return False
        _prefix, salt_b64, digest_b64 = stored.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return hmac.compare_digest(actual, expected)

    def _encode_segment(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _sign(self, header: dict[str, Any], payload: dict[str, Any]) -> str:
        header_b64 = self._encode_segment(header)
        payload_b64 = self._encode_segment(payload)
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def _decode(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError as exc:
            raise AuthError("invalid token") from exc
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(sig_b64 + "==")
        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid signature")
        header = json.loads(base64.urlsafe_b64decode(header_b64 + "==").decode("utf-8"))
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
        return header, payload

    def _issue_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {"sub": user_id, "iat": int(now.timestamp()), "exp": int((now + timedelta(days=30)).timestamp())}
        return self._sign({"alg": "HS256", "typ": "JWT"}, payload)

    def register(self, username: str, password: str) -> dict[str, str]:
        user_id = secrets.token_hex(16)
        password_hash = self._hash_password(password)
        with closing(self._conn()) as conn:
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return {"user_id": user_id, "jwt_token": self._issue_token(user_id)}

    def login(self, username: str, password: str) -> dict[str, str]:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT user_id, password_hash FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise AuthError("user not found")
        user_id, password_hash = row
        if not self._verify_password(password, password_hash):
            raise AuthError("invalid credentials")
        return {"user_id": str(user_id), "jwt_token": self._issue_token(str(user_id))}

    def verify_token(self, token: str) -> str:
        _header, payload = self._decode(token)
        exp = int(payload.get("exp", 0))
        if exp < int(datetime.now(timezone.utc).timestamp()):
            raise AuthError("token expired")
        user_id = str(payload.get("sub", ""))
        if not user_id:
            raise AuthError("missing subject")
        return user_id

    def get_user_data_path(self, user_id: str) -> Path:
        path = self.data_path / "users" / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path
