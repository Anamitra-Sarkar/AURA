"""SQLite-backed quota tracking for router providers."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import ProviderStatus


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass(slots=True)
class _Limit:
    requests: int | None = None
    tokens: int | None = None
    neurons: int | None = None
    credits: float | None = None


class QuotaTracker:
    """Track provider usage and temporary rate limits."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.reset_if_new_day()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_usage (
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    requests_used_today INTEGER NOT NULL DEFAULT 0,
                    tokens_used_today INTEGER NOT NULL DEFAULT 0,
                    credits_used_today REAL NOT NULL DEFAULT 0,
                    neurons_used_today INTEGER NOT NULL DEFAULT 0,
                    last_reset_date TEXT NOT NULL,
                    rate_limited_until TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    last_success TEXT,
                    PRIMARY KEY (provider, model)
                )
                """
            )
            conn.commit()

    def _ensure_row(self, provider: str, model: str) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO quota_usage (provider, model, last_reset_date) VALUES (?, ?, ?)",
                (provider, model, _utc_today()),
            )
            conn.commit()

    def _limit_for(self, provider: str, model: str) -> _Limit:
        if provider == "groq":
            return _Limit(requests=14400 if "8b" in model or "instant" in model or "scout" in model or "gemma" in model else 1000)
        if provider == "openrouter":
            return _Limit(requests=200)
        if provider == "cerebras":
            return _Limit(tokens=1_000_000)
        if provider == "gemini":
            if model.endswith("pro"):
                return _Limit(requests=100)
            if model.endswith("flash-lite"):
                return _Limit(requests=1000)
            return _Limit(requests=250)
        if provider == "mistral":
            return _Limit(tokens=33_000_000)
        if provider == "cloudflare":
            return _Limit(neurons=10_000)
        if provider == "xai":
            return _Limit(credits=25.0)
        return _Limit(requests=100)

    def reset_if_new_day(self) -> None:
        today = _utc_today()
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT provider, model, last_reset_date FROM quota_usage").fetchall()
            for provider, model, last_reset in rows:
                if str(last_reset) != today:
                    conn.execute(
                        "UPDATE quota_usage SET requests_used_today=0, tokens_used_today=0, credits_used_today=0, neurons_used_today=0, last_reset_date=?, rate_limited_until=NULL, last_error='' WHERE provider=? AND model=?",
                        (today, provider, model),
                    )
            conn.commit()

    def mark_rate_limited(self, provider: str, model: str, retry_after_seconds: int = 60) -> None:
        self._ensure_row(provider, model)
        until = (datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)).isoformat()
        with closing(self._conn()) as conn:
            conn.execute(
                "UPDATE quota_usage SET rate_limited_until=?, last_error=? WHERE provider=? AND model=?",
                (until, "rate_limited", provider, model),
            )
            conn.commit()

    def record_usage(self, provider: str, model: str, tokens: int, requests: int = 1, credits: float = 0.0, neurons: int = 0) -> None:
        self._ensure_row(provider, model)
        with closing(self._conn()) as conn:
            conn.execute(
                """
                UPDATE quota_usage
                SET requests_used_today = requests_used_today + ?,
                    tokens_used_today = tokens_used_today + ?,
                    credits_used_today = credits_used_today + ?,
                    neurons_used_today = neurons_used_today + ?,
                    last_success = ?,
                    last_error = ''
                WHERE provider = ? AND model = ?
                """,
                (requests, tokens, credits, neurons, datetime.now(timezone.utc).isoformat(), provider, model),
            )
            conn.commit()

    def _row(self, provider: str, model: str) -> dict[str, Any]:
        self._ensure_row(provider, model)
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT requests_used_today, tokens_used_today, credits_used_today, neurons_used_today, last_reset_date, rate_limited_until, last_error, last_success FROM quota_usage WHERE provider=? AND model=?",
                (provider, model),
            ).fetchone()
        assert row is not None
        return {
            "requests_used_today": row[0],
            "tokens_used_today": row[1],
            "credits_used_today": row[2],
            "neurons_used_today": row[3],
            "last_reset_date": row[4],
            "rate_limited_until": row[5],
            "last_error": row[6],
            "last_success": row[7],
        }

    def is_available(self, provider: str, model: str) -> bool:
        self.reset_if_new_day()
        row = self._row(provider, model)
        rate_limited_until = row["rate_limited_until"]
        if rate_limited_until:
            try:
                if datetime.fromisoformat(rate_limited_until) > datetime.now(timezone.utc):
                    return False
            except Exception:
                pass
        limit = self._limit_for(provider, model)
        if limit.requests is not None and row["requests_used_today"] >= limit.requests:
            return False
        if limit.tokens is not None and row["tokens_used_today"] >= limit.tokens:
            return False
        if limit.neurons is not None and row["neurons_used_today"] >= limit.neurons:
            return False
        if limit.credits is not None and row["credits_used_today"] >= limit.credits:
            return False
        return True

    def get_remaining(self, provider: str, model: str) -> dict[str, Any]:
        row = self._row(provider, model)
        limit = self._limit_for(provider, model)
        return {
            "requests_remaining": None if limit.requests is None else max(0, limit.requests - row["requests_used_today"]),
            "tokens_remaining": None if limit.tokens is None else max(0, limit.tokens - row["tokens_used_today"]),
            "credits_remaining": None if limit.credits is None else max(0.0, limit.credits - row["credits_used_today"]),
            "neurons_remaining": None if limit.neurons is None else max(0, limit.neurons - row["neurons_used_today"]),
        }

    def get_all_status(self) -> list[ProviderStatus]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT provider, model, requests_used_today, tokens_used_today, credits_used_today, neurons_used_today, rate_limited_until, last_error, last_success FROM quota_usage"
            ).fetchall()
        statuses: list[ProviderStatus] = []
        now = datetime.now(timezone.utc)
        for provider, model, requests_used, tokens_used, credits_used, neurons_used, rate_limited_until, last_error, last_success in rows:
            limit = self._limit_for(provider, model)
            available = True
            if rate_limited_until:
                try:
                    available = datetime.fromisoformat(rate_limited_until) <= now
                except Exception:
                    available = True
            if limit.requests is not None and requests_used >= limit.requests:
                available = False
            if limit.tokens is not None and tokens_used >= limit.tokens:
                available = False
            if limit.neurons is not None and neurons_used >= limit.neurons:
                available = False
            if limit.credits is not None and credits_used >= limit.credits:
                available = False
            statuses.append(
                ProviderStatus(
                    name=f"{provider}:{model}",
                    available=available,
                    requests_remaining=max(0, (limit.requests or 0) - requests_used) if limit.requests is not None else 0,
                    tokens_remaining=max(0, (limit.tokens or 0) - tokens_used) if limit.tokens is not None else 0,
                    reset_at=datetime.fromisoformat(rate_limited_until) if rate_limited_until else now,
                    last_error=last_error,
                    last_success=datetime.fromisoformat(last_success) if last_success else now,
                )
            )
        return statuses
