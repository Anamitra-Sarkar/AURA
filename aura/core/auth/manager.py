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

from aura.core.config import load_config


class AuthError(RuntimeError):
    """Raised when authentication fails."""


@dataclass(slots=True)
class AuthRecord:
    user_id: str
    username: str


# ---------------------------------------------------------------------------
# Persistence strategy for HuggingFace Spaces:
#   HF mounts a persistent volume at /data.  Everything else in the container
#   is ephemeral and is wiped on every restart/rebuild.
#
#   We detect HF by probing whether /data is actually a writable directory
#   (more reliable than checking env vars that differ across HF plan tiers).
#   If /data is writable we always store users.db + quota.db there so that
#   accounts and JWT secret survive restarts.
#
#   On a regular host (local dev, VPS, Docker) /data usually doesn't exist,
#   so we fall back to the configured data_dir (e.g. var/data/).
# ---------------------------------------------------------------------------
def _is_hf_space() -> bool:
    """Return True when running inside a HuggingFace Space container."""
    # Any of these vars being set is a reliable HF signal
    for var in ("SPACE_ID", "HF_SPACE_ID", "SPACE_AUTHOR_NAME", "SPACE_REPO_ID"):
        if os.getenv(var):
            return True
    # Last-resort: /data exists and is writable (HF persistent storage)
    data_dir = Path("/data")
    if data_dir.is_dir():
        try:
            probe = data_dir / ".aura_probe"
            probe.touch()
            probe.unlink()
            return True
        except OSError:
            pass
    return False


def _resolve_db_root(data_path: Path) -> Path:
    """Return the directory where users.db and jwt_secret should live.

    On HF Spaces this is always /data/aura (persistent across restarts).
    Everywhere else it is ``data_path`` as configured.
    """
    if _is_hf_space():
        persistent = Path("/data/aura")
        persistent.mkdir(parents=True, exist_ok=True)
        return persistent
    return data_path


class AuthManager:
    """Register users and issue signed tokens."""

    def __init__(self, data_path: str | Path, secret: str | None = None) -> None:
        self.data_path = _resolve_db_root(Path(data_path))
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.users_db = self.data_path / "users.db"
        # Secret priority (MUST be stable across restarts on HF):
        #   1. Explicit arg passed by the caller (highest priority)
        #   2. AURA_JWT_SECRET env var  ← set this as a HF Space Secret
        #   3. JWT_SECRET env var       ← legacy fallback
        #   4. Persisted secret file in /data/aura/jwt_secret.txt
        #      (written on first boot, survives restarts even without env var)
        #   5. Random token (dev-only — tokens invalidated on every restart)
        resolved_secret = (
            secret
            or os.getenv("AURA_JWT_SECRET")
            or os.getenv("JWT_SECRET")
            or self._load_or_create_secret_file()
        )
        self.secret = resolved_secret.encode("utf-8")
        self._init_db()

    def _load_or_create_secret_file(self) -> str:
        """Load the persisted JWT secret or create one on first run.

        The file lives in self.data_path (which is /data/aura on HF), so it
        survives container restarts.  This means users never get logged out
        just because a new container started.
        """
        secret_file = self.data_path / "jwt_secret.txt"
        if secret_file.exists():
            value = secret_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        # First boot — generate and persist
        new_secret = secrets.token_urlsafe(48)
        try:
            secret_file.write_text(new_secret, encoding="utf-8")
            # Restrict permissions: owner read-only
            secret_file.chmod(0o600)
        except OSError:
            pass  # Can't persist — dev fallback is fine
        return new_secret

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.users_db)

    def _init_db(self) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id       TEXT PRIMARY KEY,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return (
            "pbkdf2$"
            + base64.urlsafe_b64encode(salt).decode("ascii")
            + "$"
            + base64.urlsafe_b64encode(digest).decode("ascii")
        )

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
        payload = {
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        }
        return self._sign({"alg": "HS256", "typ": "JWT"}, payload)

    def register(self, username: str, password: str) -> dict[str, str]:
        user_id = secrets.token_hex(16)
        password_hash = self._hash_password(password)
        try:
            with closing(self._conn()) as conn:
                conn.execute(
                    "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, username, password_hash, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AuthError(f"username '{username}' is already taken") from exc
        return {"user_id": user_id, "token": self._issue_token(user_id)}

    def login(self, username: str, password: str) -> dict[str, str]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT user_id, password_hash FROM users WHERE username=?", (username,)
            ).fetchone()
        if row is None:
            raise AuthError("user not found \u2014 please register first")
        user_id, password_hash = row
        if not self._verify_password(password, password_hash):
            raise AuthError("invalid credentials")
        return {"user_id": str(user_id), "token": self._issue_token(str(user_id))}

    def verify_token(self, token: str) -> str:
        _header, payload = self._decode(token)
        exp = int(payload.get("exp", 0))
        if exp < int(datetime.now(timezone.utc).timestamp()):
            raise AuthError("token expired")
        user_id = str(payload.get("sub", ""))
        if not user_id:
            raise AuthError("missing subject")
        return user_id

    def revoke_token(self, token: str) -> bool:
        revoked_file = self.data_path / "revoked_tokens.json"
        try:
            revoked = set(json.loads(revoked_file.read_text(encoding="utf-8")))
        except Exception:
            revoked = set()
        revoked.add(token)
        revoked_file.write_text(
            json.dumps(sorted(revoked), ensure_ascii=True, indent=2), encoding="utf-8"
        )
        return True

    def get_user_data_path(self, user_id: str) -> Path:
        path = self.data_path / "users" / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path


_DEFAULT_AUTH_MANAGER: AuthManager | None = None


def _default_manager() -> AuthManager:
    global _DEFAULT_AUTH_MANAGER
    if _DEFAULT_AUTH_MANAGER is None:
        config = load_config()
        secret = getattr(getattr(config, "auth", None), "secret", None) or None
        _DEFAULT_AUTH_MANAGER = AuthManager(config.paths.data_dir, secret=secret)
    return _DEFAULT_AUTH_MANAGER


def register(username: str, password: str) -> dict[str, str]:
    return _default_manager().register(username, password)


def login(username: str, password: str) -> dict[str, str]:
    return _default_manager().login(username, password)


def verify_token(token: str) -> str:
    return _default_manager().verify_token(token)


def revoke_token(token: str) -> bool:
    return _default_manager().revoke_token(token)
