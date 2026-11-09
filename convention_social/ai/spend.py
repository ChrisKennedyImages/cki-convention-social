"""The one till for Anthropic spend: record every call, know the cycle to date, stop at the cap.

The cap counts one cycle: from the first of the month as it always did, or from the day the Anthropic credit
arrives (AI_CAP_RESETS_ON; Chris's Max plan pays $200 of API credit on the 17th, 2026-10-25), so the cap and the
credit count the same days and two cycles cannot stack inside one credit.

Rates are USD per million tokens (input, output), matched by longest model
prefix (Anthropic price table, read 2026-10-10). Unknown models are counted with cost 0 so the count stays honest even
when the price is unknown; the watchdog flags any zero-cost Anthropic row.

A prompt read from Anthropic's cache or written to it is paid for too, at its own share of the input rate (CACHE_READ,
CACHE_WRITE; the Claude API's prompt caching guide, read 2026-11-09). Until 2026-11-09 the till counted only the uncached
input and the output, so every row before then under-counts a call that read or wrote a cached prompt. `record_response`
is the one way a call is put on the ledger: it reads the four counts off the response's usage.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core import config, db

RESERVE_USD = 0.15                 # what one call is held for before its real cost is known (8.2, 2026-10-13)
RESERVE_SWEEP = timedelta(minutes=30)      # a reservation this old is a call that died: swept, not counted forever
RESERVED = "reserved"              # the detail prefix of an in-flight row

RATES = {
    # Longest matching prefix wins, so a family prefix covers every dated member of it:
    # "claude-haiku-4" prices claude-haiku-4-5, "claude-opus-4" prices 4.6, 4.7 and 4.8.
    # Only models that exist are listed. An unknown model costs 0, which the watchdog
    # flags: better a loud zero than a quiet guess at the wrong price.
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (1.00, 5.00),
}


# A cache read costs this share of the model's input rate: about a tenth, a twentieth on Claude Opus 5.5 and a fortieth
# on Claude Fable 5.1 and Claude Mythos 5.1. A cache write costs 1.25 times the input rate for the 5-minute entry the
# suite writes ({"type": "ephemeral"}) and twice it for a 1-hour one.
CACHE_READ = {"": 0.1, "claude-opus-5-5": 0.05, "claude-fable-5-1": 0.025, "claude-mythos-5-1": 0.025}
CACHE_WRITE = {"5m": 1.25, "1h": 2.0}


def _longest(table: dict, model: str):
    best = None
    for prefix, value in table.items():
        if str(model).startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, value)
    return best[1] if best else None


def rate_for(model: str) -> tuple[float, float] | None:
    return _longest(RATES, model)


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write_5m: int = 0,
             cache_write_1h: int = 0) -> float:
    rate = rate_for(model)
    if not rate:
        return 0.0
    prompt = (input_tokens + cache_read * _longest(CACHE_READ, model) + cache_write_5m * CACHE_WRITE["5m"]
              + cache_write_1h * CACHE_WRITE["1h"])
    return round(prompt / 1e6 * rate[0] + output_tokens / 1e6 * rate[1], 6)


def _count(obj, key: str) -> int:
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return int(value or 0) if isinstance(value, (int, float)) else 0


def record_response(conn: sqlite3.Connection, agent: str, response, model: str, detail: str | None = None,
                    reservation: Optional[int] = None) -> tuple[str, float]:
    """A call's response on the ledger, at the model that answered: its uncached input, its output, and the prompt it read
    from the cache and wrote to it, by the entry's lifetime when the usage says (else the 5-minute entry the suite
    writes). (the model that answered, the cost). The one way a call is recorded; no caller does its own arithmetic."""
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    answered = (response.get("model") if isinstance(response, dict) else getattr(response, "model", None)) or model
    written = _count(usage, "cache_creation_input_tokens")
    by_ttl = usage.get("cache_creation") if isinstance(usage, dict) else getattr(usage, "cache_creation", None)
    hour = min(written, _count(by_ttl, "ephemeral_1h_input_tokens"))
    cost = record(conn, agent, answered, _count(usage, "input_tokens"), _count(usage, "output_tokens"), detail,
                  reservation=reservation, cache_read=_count(usage, "cache_read_input_tokens"),
                  cache_write_5m=written - hour, cache_write_1h=hour)
    return answered, cost


def record(conn: sqlite3.Connection, agent: str, model: str, input_tokens: int, output_tokens: int,
           detail: str | None = None, reservation: Optional[int] = None, *, cache_read: int = 0, cache_write_5m: int = 0,
           cache_write_1h: int = 0) -> float:
    """The call's real cost on the ledger. With `reservation`, the in-flight row becomes this one (no second
    row); an unknown reservation (swept, or none) still records the call. A call's response goes through
    record_response, which reads these counts off its usage."""
    cost = cost_usd(model, input_tokens, output_tokens, cache_read, cache_write_5m, cache_write_1h)
    cached = cache_read + cache_write_5m + cache_write_1h
    words = (f"{model} in={input_tokens} out={output_tokens}"
             + (f" cache_read={cache_read} cache_write={cache_write_5m + cache_write_1h}" if cached else "")
             + (f" {detail}" if detail else ""))
    units = input_tokens + output_tokens + cached
    if reservation is not None:
        done = conn.execute("UPDATE api_usage SET ts=?, agent=?, units=?, unit_kind='tokens', cost_usd=?, detail=? "
                            "WHERE id=? AND detail LIKE ?", (db.utcnow(), agent, units, cost, words,
                                                           reservation, f"{RESERVED} %")).rowcount
        if done:
            return cost
    db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent=agent,
              units=units, unit_kind="tokens", cost_usd=cost, detail=words)
    return cost


def sweep(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Reservations older than RESERVE_SWEEP are calls that never settled (a crash): gone, so the cap is not held
    by ghosts. How many were swept."""
    cutoff = ((now or datetime.now(timezone.utc)) - RESERVE_SWEEP).isoformat()
    return conn.execute("DELETE FROM api_usage WHERE provider='anthropic' AND detail LIKE ? AND ts < ?", (f"{RESERVED} %", cutoff)).rowcount


def reserve(conn: sqlite3.Connection, agent: str, model: str, estimate_usd: float = RESERVE_USD) -> Optional[int]:
    """Hold `estimate_usd` on the ledger before a call, so two agents cannot each overshoot the cap by one call
    (8.2, 2026-10-13). None when the cap would be passed: the caller does not call. The row's id is handed to
    record() to settle, or to release() when the call failed."""
    sweep(conn)
    if cap_reached(conn, about_to_spend=estimate_usd):
        return None
    return db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent=agent, units=0, unit_kind="tokens",
                     cost_usd=float(estimate_usd), detail=f"{RESERVED} {model}")


def release(conn: sqlite3.Connection, reservation: Optional[int]) -> None:
    """The call did not happen (or failed): nothing to count."""
    if reservation is not None:
        conn.execute("DELETE FROM api_usage WHERE id=? AND detail LIKE ?", (reservation, f"{RESERVED} %"))


def cycle_start(now: datetime, resets_on: int) -> datetime:
    """Midnight UTC of the most recent `resets_on` day of the month. A day past the 28th reads as the 28th, so every
    month has one; below 1 reads as the 1st."""
    day = min(max(int(resets_on), 1), 28)
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if start > now:
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=day)
    return start


def cycle_to_date(conn: sqlite3.Connection, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = cycle_start(now, config.get_config().ai_cap_resets_on).isoformat()
    row = db.one(conn, "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM api_usage WHERE provider='anthropic' AND ts >= ?", (start,))
    return float(row["c"])


def cap_reached(conn: sqlite3.Connection, about_to_spend: float = 0.0) -> bool:
    """Fails closed: a cap of 0 or less means no paid calls at all. Reservations count (they are rows).
    `about_to_spend` asks whether a call of that size would pass the cap."""
    cap = config.get_config().ai_monthly_cap_usd
    return cap <= 0 or cycle_to_date(conn) + max(0.0, about_to_spend) >= cap + (1e-9 if about_to_spend else 0)
