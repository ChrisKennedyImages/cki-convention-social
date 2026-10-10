"""The one till for Anthropic spend: record every call, know month-to-date, stop at the cap.

Rates are USD per million tokens (input, output), matched by longest model
prefix (Anthropic price table, read 2026-10-10). Unknown models are counted with cost 0 so the count stays honest even
when the price is unknown; the watchdog flags any zero-cost Anthropic row.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..core import config, db

RATES = {
    # Longest matching prefix wins, so a family prefix covers every dated member of it:
    # "claude-haiku-4" prices claude-haiku-4-5, "claude-opus-4" prices 4.6, 4.7 and 4.8.
    # Only models that exist are listed. An unknown model costs 0, which the watchdog
    # flags: better a loud zero than a quiet guess at the wrong price.
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (1.00, 5.00),
}


def rate_for(model: str) -> tuple[float, float] | None:
    best = None
    for prefix, rate in RATES.items():
        if str(model).startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, rate)
    return best[1] if best else None


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = rate_for(model)
    if not rate:
        return 0.0
    return round(input_tokens / 1e6 * rate[0] + output_tokens / 1e6 * rate[1], 6)


def record(conn: sqlite3.Connection, agent: str, model: str, input_tokens: int, output_tokens: int,
           detail: str | None = None) -> float:
    cost = cost_usd(model, input_tokens, output_tokens)
    db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent=agent,
              units=input_tokens + output_tokens, unit_kind="tokens", cost_usd=cost,
              detail=f"{model} in={input_tokens} out={output_tokens}" + (f" {detail}" if detail else ""))
    return cost


def month_to_date(conn: sqlite3.Connection, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = db.one(conn, "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM api_usage WHERE provider='anthropic' AND ts >= ?", (start,))
    return float(row["c"])


def cap_reached(conn: sqlite3.Connection) -> bool:
    """Fails closed: a cap of 0 or less means no paid calls at all."""
    cap = config.get_config().ai_monthly_cap_usd
    return cap <= 0 or month_to_date(conn) >= cap
