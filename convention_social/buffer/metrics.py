"""Daily metric snapshots for every sent post on the company's Buffer channels.

Buffer refreshes a post's metrics about once a day (`metrics: [{type, name,
value, unit}]`, `metricsUpdatedAt`). Once a day the watchdog asks Buffer for
the sent posts on every channel in the `channels` table and stores one
snapshot row per post per day in post_metrics, so the dashboard can show
totals for any window and the trend over time, and pacing can learn which
times work. Posts that came from our queue (post_history) are flagged `ours`;
anything else on the channels is kept as the baseline.

Metric names differ by network. `normalise()` folds them into a small fixed set:
reach, impressions, engagement (reactions/likes + comments + shares + saves),
clicks (any click metric), plus the raw map for the detail table.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..core import db, runner, settings

PULLED_KEY = "metrics.pulled_on"
MAX_PAGES = 6            # 6 x 50 posts per day
ENGAGEMENT = ("reactions", "likes", "comments", "reposts", "shares", "saves", "replies")
CLICKS = ("clicks", "link_clicks", "linkclicks", "post_clicks", "website_clicks")


def metric_map(node: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in node.get("metrics") or []:
        t = (m.get("type") or m.get("name") or "").lower().replace(" ", "_")
        try:
            out[t] = out.get(t, 0.0) + float(m.get("value") or 0)
        except (TypeError, ValueError):
            continue
    return out


def normalise(mm: dict[str, float]) -> dict[str, float]:
    return {"reach": mm.get("reach", 0.0), "impressions": mm.get("impressions", mm.get("views", 0.0)),
            "engagement": sum(mm.get(k, 0.0) for k in ENGAGEMENT), "clicks": sum(mm.get(k, 0.0) for k in CLICKS)}


def due(conn, today: date) -> bool:
    return settings.get(conn, PULLED_KEY) != today.isoformat()


def pull(ctx: runner.Context, client, today: Optional[date] = None) -> dict:
    """One snapshot per sent post across every channel in the `channels` table. Returns counts."""
    today = today or date.today()
    stats = {"channels": 0, "posts": 0, "ours": 0, "errors": 0}
    by_channel = {r["buffer_channel_id"]: r["service"]
                  for r in db.rows(ctx.conn, "SELECT buffer_channel_id, service FROM channels ORDER BY id")}
    if by_channel:
        ours_ids = {r["buffer_post_id"] for r in db.rows(ctx.conn, "SELECT buffer_post_id FROM post_history")}
        after, pages = None, 0
        try:
            while pages < MAX_PAGES:
                nodes, page = client.posts(status="sent", channel_ids=list(by_channel), first=50, after=after)
                for n in nodes:
                    pid = n.get("id")
                    if not pid:
                        continue
                    mm = metric_map(n)
                    ours = 1 if pid in ours_ids else 0
                    service = by_channel.get(n.get("channelId")) or (n.get("channelService") or "").lower() or None
                    ctx.conn.execute(
                        "INSERT INTO post_metrics (buffer_post_id, service, ours, sent_at, text, captured_on, metrics, metrics_updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(buffer_post_id, captured_on) DO UPDATE SET metrics=excluded.metrics, "
                        "metrics_updated_at=excluded.metrics_updated_at, sent_at=excluded.sent_at, text=excluded.text, ours=excluded.ours",
                        (pid, service, ours, n.get("sentAt"), (n.get("text") or "")[:500], today.isoformat(), json.dumps(mm),
                         n.get("metricsUpdatedAt")))
                    if ours:
                        ctx.conn.execute("UPDATE post_history SET metrics=?, metrics_updated_at=? WHERE buffer_post_id=?",
                                         (json.dumps(mm), n.get("metricsUpdatedAt"), pid))
                        stats["ours"] += 1
                    stats["posts"] += 1
                pages += 1
                if not page.get("hasNextPage"):
                    break
                after = page.get("endCursor")
            stats["channels"] = len(by_channel)
        except Exception as e:  # noqa: BLE001  (Buffer errors, budget, network)
            stats["errors"] += 1
            runner.record_error(ctx.conn, ctx.agent, "metrics_pull", f"metrics pull failed: {e}")
    settings.set(ctx.conn, PULLED_KEY, today.isoformat())
    return stats


def latest_rows(conn, since: Optional[date] = None, ours_only: bool = True) -> list[dict]:
    """The newest snapshot per post, newest post first, optionally only posts sent since a date."""
    rows = db.rows(conn, "SELECT m.* FROM post_metrics m JOIN (SELECT buffer_post_id, MAX(captured_on) d FROM post_metrics "
                         "GROUP BY buffer_post_id) x ON x.buffer_post_id=m.buffer_post_id AND x.d=m.captured_on ORDER BY m.sent_at DESC")
    out = []
    for r in rows:
        if ours_only and not r["ours"]:
            continue
        sent = (r["sent_at"] or "")[:10]
        if since and sent and sent < since.isoformat():
            continue
        d = dict(r)
        d["raw"] = json.loads(r["metrics"] or "{}")
        d["n"] = normalise(d["raw"])
        out.append(d)
    return out


def summary(conn, days: int = 30, today: Optional[date] = None) -> dict:
    today = today or date.today()
    since = today - timedelta(days=days)
    rows = latest_rows(conn, since=since, ours_only=True)
    totals = {"posts": len(rows), "reach": 0.0, "impressions": 0.0, "engagement": 0.0, "clicks": 0.0}
    per_network: dict[str, dict[str, float]] = {}
    for r in rows:
        for k in ("reach", "impressions", "engagement", "clicks"):
            totals[k] += r["n"][k]
        net = per_network.setdefault(r["service"] or "unknown", {"posts": 0, "reach": 0.0, "engagement": 0.0, "clicks": 0.0})
        net["posts"] += 1
        for k in ("reach", "engagement", "clicks"):
            net[k] += r["n"][k]
    best = max(rows, key=lambda r: r["n"]["engagement"], default=None)
    last = db.one(conn, "SELECT MAX(captured_on) d FROM post_metrics")["d"]
    return {"days": days, "since": since.isoformat(), "totals": totals, "per_network": per_network, "rows": rows,
            "best": best, "last_pull": last}


def trend(conn, weeks: int = 12, today: Optional[date] = None) -> list[dict]:
    """Per week: our posts sent that week and their engagement (latest snapshot)."""
    today = today or date.today()
    rows = latest_rows(conn, since=today - timedelta(weeks=weeks), ours_only=True)
    buckets: dict[str, dict[str, float]] = {}
    for w in range(weeks):
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1 - w)
        buckets[start.isoformat()] = {"week": start.isoformat(), "posts": 0, "engagement": 0.0, "reach": 0.0}
    for r in rows:
        try:
            d = datetime.fromisoformat((r["sent_at"] or "").replace("Z", "+00:00")).astimezone(timezone.utc).date()
        except ValueError:
            continue
        start = (d - timedelta(days=d.weekday())).isoformat()
        if start in buckets:
            buckets[start]["posts"] += 1
            buckets[start]["engagement"] += r["n"]["engagement"]
            buckets[start]["reach"] += r["n"]["reach"]
    return list(buckets.values())
