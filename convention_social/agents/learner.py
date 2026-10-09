"""Learner agent (daily, 23:00): read how the posts did and nudge the suite toward what works.

What it learns, per network, from the numbers Buffer reports (post_metrics,
the newest snapshot of each post, folded by buffer.metrics.normalise):

  * the posting hour (local, TIMEZONE) that gets the most engagement per post,
    from every sent post on the company's channels (ours and Chris's own);
  * which photos do best: subject (event or building), shot_type and
    event_kind, from our own posts only (post_history.queue_id ->
    content_queue.photo_ids -> classifications). Engagement is compared
    inside each network first, so a big Instagram number never outweighs a
    small Pinterest one.

Noise is never acted on. A network needs MIN_POSTS_FOR_TIME posts with
numbers before its time moves; an hour or a kind of photo needs MIN_BUCKET
posts before it counts; every average is shrunk toward the prior (a
Bayesian average worth PRIOR_WEIGHT posts); and a better hour has to beat
the current one by LIFT_MARGIN. Posts younger than SETTLE are left out
because their numbers are still filling in.

What it may change, only through settings keys it owns:
  learner.post_times  {network: {weekday, weekend, base_weekday, base_weekend,
                      moved_at, best_hour, posts}}. A time moves at most
                      MAX_STEP minutes, at most once in MOVE_EVERY, and always
                      stays between 07:00 and 22:00. It starts from pacing's
                      times (POST_TIMES included); when Chris changes those,
                      his new time wins and learning starts again from it.
  learner.weights     {"shot_type": {...}, "event_kind": {...}}, each 0.5 to 1.5.
Pacing and the content picker read them through post_time_for() and
weight_for(), and only when they exist. With nothing applied, or anything
unreadable, both hand back the caller's default.

What it never changes: one post a day, the building day once a week,
approvals, clearance, the do-not-use list, any money cap, any dry-run
switch. Subject (event or building) goes in the note and never becomes a
weight, because the building day is fixed.

Dry run (the default) works out the same suggestion and stores it with
status 'suggested', not applied. Live stores it as 'applied'. Both are
internal; nothing leaves the Mini. With a Buffer key the run first refreshes
the numbers (metrics.pull, read only, once a day); without one it uses what
the tables already hold.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..buffer import metrics
from ..buffer.client import BufferClient
from ..core import config, db, runner, settings

DAY_TYPES = ("weekday", "weekend")
MIN_POSTS_FOR_TIME = 8          # posts with numbers on a network before its time may move
MIN_BUCKET = 5                  # posts in an hour or a kind of photo before it counts
PRIOR_WEIGHT = 5.0              # the prior is worth this many posts in every average
LIFT_MARGIN = 0.10              # a better hour must beat the current one by 10%
MAX_STEP = 60                   # minutes a time may move in one go
MOVE_EVERY = timedelta(days=7)  # and at most once a week
EARLIEST = 7 * 60               # 07:00
LATEST = 22 * 60                # 22:00
ROUND_TO = 15                   # target times land on the quarter hour
WEIGHT_MIN, WEIGHT_MAX = 0.5, 1.5
LOOKBACK_DAYS = 90
SETTLE = timedelta(hours=48)

TIMES_KEY = "learner.post_times"
WEIGHTS_KEY = "learner.weights"
SUGGESTION_KEY = "learner.suggestion"
NOTE_KEY = "learner.note"
OWNED_KEYS = (TIMES_KEY, WEIGHTS_KEY, SUGGESTION_KEY, NOTE_KEY)
WEIGHT_FIELDS = ("shot_type", "event_kind")


# ------------------------------------------------------------------ small helpers

def parse_clock(value) -> Optional[int]:
    """'HH:MM' -> minutes after midnight, or None."""
    try:
        hh, mm = str(value).strip().split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def words(minutes: int) -> str:
    """09:30 -> '9:30 am', 20:30 -> '8:30 pm'."""
    h, m = divmod(minutes, 60)
    return f"{(h % 12) or 12}:{m:02d} {'am' if h < 12 else 'pm'}"


def of_time(t: time) -> int:
    return t.hour * 60 + t.minute


def clamp_clock(minutes: int) -> int:
    return max(EARLIEST, min(LATEST, minutes))


def clamp_weight(value: float) -> float:
    return max(WEIGHT_MIN, min(WEIGHT_MAX, value))


def bayes(total: float, n: int, prior: float, k: float = PRIOR_WEIGHT) -> float:
    """The average shrunk toward the prior: few posts barely move it, many posts speak for themselves."""
    return (total + k * prior) / (n + k)


def parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _json(value, default):
    try:
        out = json.loads(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return out if isinstance(out, type(default)) else default


def label(network: str) -> str:
    return network.capitalize()


def when_words(times: dict[str, int]) -> str:
    wd, we = times["weekday"], times["weekend"]
    return words(wd) if wd == we else f"{words(wd)} weekdays, {words(we)} weekends"


# ------------------------------------------------------------------ what the consumers call

def applied_times(conn: sqlite3.Connection) -> dict:
    try:
        return _json(settings.get(conn, TIMES_KEY), {})
    except sqlite3.Error:
        return {}


def applied_weights(conn: sqlite3.Connection) -> dict:
    try:
        return _json(settings.get(conn, WEIGHTS_KEY), {})
    except sqlite3.Error:
        return {}


def post_time_for(conn: sqlite3.Connection, network: str, default: time, day: Optional[date] = None) -> time:
    """The time this network posts at: the learned one when the learner applied one that grew from
    this same default, else `default`. Pass `day` so weekdays and weekends each get their own time.
    Never raises: anything unreadable or outside 07:00 to 22:00 gives back `default`."""
    try:
        entry = applied_times(conn).get(network)
        if not isinstance(entry, dict):
            return default
        want = fmt(of_time(default))
        kinds = DAY_TYPES if day is None else (("weekend",) if day.weekday() >= 5 else ("weekday",))
        for kind in kinds:
            if entry.get(f"base_{kind}") != want:
                continue          # Chris changed the time since the learner moved it: his time wins
            learned = parse_clock(entry.get(kind))
            if learned is None or not EARLIEST <= learned <= LATEST:
                return default
            return time(learned // 60, learned % 60)
        return default
    except Exception:  # noqa: BLE001  a learner problem must never stop a post being paced
        return default


def _weight(table, key) -> float:
    if not key or not isinstance(table, dict):
        return 1.0
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    return clamp_weight(float(value))


def weight_for(conn: sqlite3.Connection, shot_type: Optional[str], event_kind: Optional[str]) -> float:
    """How much to favour a photo of this shot type and event kind: 1.0 when nothing is learned,
    always between 0.5 and 1.5. Never raises."""
    try:
        w = applied_weights(conn)
        return round(clamp_weight(_weight(w.get("shot_type"), shot_type) * _weight(w.get("event_kind"), event_kind)), 4)
    except Exception:  # noqa: BLE001
        return 1.0


# ------------------------------------------------------------------ the numbers

@dataclass
class Obs:
    post_id: str
    network: str
    local: datetime
    engagement: float
    ours: bool
    queue_id: Optional[int]


def observations(conn: sqlite3.Connection, tz: ZoneInfo, now: datetime) -> list[Obs]:
    """The newest snapshot of every post sent inside the lookback window and old enough to have settled."""
    queue_of = {r["buffer_post_id"]: r["queue_id"] for r in db.rows(conn, "SELECT buffer_post_id, queue_id FROM post_history")}
    rows = db.rows(conn, "SELECT m.* FROM post_metrics m JOIN (SELECT buffer_post_id, MAX(captured_on) d FROM post_metrics "
                         "GROUP BY buffer_post_id) x ON x.buffer_post_id=m.buffer_post_id AND x.d=m.captured_on")
    oldest, newest = now - timedelta(days=LOOKBACK_DAYS), now - SETTLE
    out = []
    for r in rows:
        network = (r["service"] or "").strip().lower()
        sent = parse_ts(r["sent_at"])
        if not network or sent is None or not oldest <= sent <= newest:
            continue
        raw = _json(r["metrics"], {})
        engagement = metrics.normalise({k: float(v) for k, v in raw.items() if isinstance(v, (int, float))})["engagement"]
        pid = r["buffer_post_id"]
        out.append(Obs(pid, network, sent.astimezone(tz), float(engagement), bool(r["ours"]) or pid in queue_of, queue_of.get(pid)))
    return out


def photo_attrs(conn: sqlite3.Connection, queue_ids) -> dict[int, list[dict]]:
    """{queue id: [{subject, shot_type, event_kind}]} for the photos on each post."""
    out: dict[int, list[dict]] = {}
    for qid in set(queue_ids):
        row = db.one(conn, "SELECT photo_ids FROM content_queue WHERE id=?", (qid,))
        ids = _json(row["photo_ids"], []) if row else []
        attrs = []
        for pid in ids:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            c = db.one(conn, "SELECT subject, shot_type, event_kind FROM classifications WHERE photo_id=?", (pid,))
            if c:
                attrs.append({"subject": c["subject"], "shot_type": c["shot_type"], "event_kind": c["event_kind"]})
        out[qid] = attrs
    return out


# ------------------------------------------------------------------ times

def start_times(network: str, base: tuple[time, time], entry: Optional[dict]) -> tuple[dict[str, int], Optional[datetime], bool]:
    """(current {weekday, weekend} minutes, when it last moved, reset). The applied learned time when it grew
    from today's pacing times; else pacing's times, and `reset` says Chris changed them since."""
    base_m = {"weekday": of_time(base[0]), "weekend": of_time(base[1])}
    if isinstance(entry, dict):
        same = all(entry.get(f"base_{k}") == fmt(base_m[k]) for k in DAY_TYPES)
        learned = {k: parse_clock(entry.get(k)) for k in DAY_TYPES}
        if same and all(v is not None for v in learned.values()):
            return learned, parse_ts(entry.get("moved_at")), False
        return dict(base_m), None, not same
    return dict(base_m), None, False


def decide_time(network: str, obs: list[Obs], base: tuple[time, time], entry: Optional[dict],
                now: datetime) -> tuple[dict, dict, str, bool]:
    """(new entry, detail, one plain sentence, moved?) for one network."""
    current, moved_at, reset = start_times(network, base, entry)
    base_m = {"weekday": of_time(base[0]), "weekend": of_time(base[1])}
    new = dict(current)
    n = len(obs)
    detail: dict = {"posts": n, "hours": {}, "best_hour": None, "target": None}
    out_entry = {"weekday": fmt(current["weekday"]), "weekend": fmt(current["weekend"]),
                 "base_weekday": fmt(base_m["weekday"]), "base_weekend": fmt(base_m["weekend"]),
                 "moved_at": moved_at.isoformat() if moved_at else None, "best_hour": None, "posts": n}
    lead = f"{label(network)} stays at {when_words(current)}"
    if reset:
        lead = f"{label(network)} starts again from your time, {when_words(current)}"
    if n < MIN_POSTS_FOR_TIME:
        return out_entry, detail, f"{lead}: {n} of the {MIN_POSTS_FOR_TIME} posts it needs have numbers so far.", False
    prior = sum(o.engagement for o in obs) / n
    detail["prior"] = round(prior, 3)
    if prior <= 0:
        return out_entry, detail, f"{lead}: no engagement has been recorded on it yet.", False
    buckets: dict[int, list[Obs]] = {}
    for o in obs:
        buckets.setdefault(o.local.hour, []).append(o)
    scores = {h: bayes(sum(o.engagement for o in b), len(b), prior) for h, b in buckets.items()}
    detail["hours"] = {str(h): {"posts": len(b), "mean": round(sum(o.engagement for o in b) / len(b), 3),
                                "score": round(scores[h], 3)} for h, b in sorted(buckets.items())}
    counted = sorted(h for h, b in buckets.items() if len(b) >= MIN_BUCKET)
    if not counted:
        return out_entry, detail, f"{lead}: no posting hour has {MIN_BUCKET} posts with numbers yet.", False
    best = max(counted, key=lambda h: (scores[h], -h))
    minutes = [o.local.hour * 60 + o.local.minute for o in buckets[best]]
    target = clamp_clock(int(round(sum(minutes) / len(minutes) / ROUND_TO)) * ROUND_TO)
    detail.update(best_hour=best, target=fmt(target))
    out_entry["best_hour"] = best
    lifts, waiting = [], False
    for kind in DAY_TYPES:
        cur = current[kind]
        cur_score = scores.get(cur // 60, prior)
        if best == cur // 60 or target == cur or scores[best] < cur_score * (1 + LIFT_MARGIN):
            continue
        if moved_at and now - moved_at < MOVE_EVERY:
            waiting = True
            continue
        step = max(-MAX_STEP, min(MAX_STEP, target - cur))
        new[kind] = clamp_clock(cur + step)
        if new[kind] != cur:
            lifts.append(scores[best] / cur_score - 1 if cur_score > 0 else 0.0)
    moved = new != current
    out_entry.update(weekday=fmt(new["weekday"]), weekend=fmt(new["weekend"]))
    if moved:
        out_entry["moved_at"] = now.isoformat()
        changes = [f"from {words(current[k])} to {words(new[k])}" + ("" if current["weekday"] == current["weekend"] else f" on {k}s")
                   for k in DAY_TYPES if new[k] != current[k]]
        if current["weekday"] == current["weekend"] and new["weekday"] == new["weekend"]:
            changes = changes[:1]
        lift = max(lifts) if lifts else 0.0
        sentence = (f"{label(network)}{' starts again from your time and' if reset else ''} moves {' and '.join(changes)}: "
                    f"posts near {words(target)} drew "
                    f"{round(lift * 100)}% more engagement per post than its current hour, over {len(buckets[best])} posts.")
        return out_entry, detail, sentence, True
    if waiting:
        nxt = (moved_at + MOVE_EVERY).astimezone(obs[0].local.tzinfo).date()
        return out_entry, detail, f"{lead} until {nxt:%b %d}: a time moves at most once a week.", False
    if best == current["weekday"] // 60 and best == current["weekend"] // 60:
        return out_entry, detail, f"{lead}: its own hour already does best.", False
    return out_entry, detail, f"{lead}: no other hour did clearly better yet.", False


# ------------------------------------------------------------------ weights

def kind_words(fieldname: str, value: str) -> str:
    if fieldname == "event_kind":
        return {"fan": "fan convention photos", "business": "business event photos"}.get(value, f"{value} event photos")
    return value.replace("_", " ") + " photos"


def decide_weights(conn: sqlite3.Connection, obs: list[Obs], before: dict) -> tuple[dict, dict, list[str]]:
    """(weights, detail, sentences). Lift = a post's engagement over its network's average for our posts."""
    ours = [o for o in obs if o.ours and o.queue_id is not None]
    by_net: dict[str, list[float]] = {}
    for o in ours:
        by_net.setdefault(o.network, []).append(o.engagement)
    mean = {net: sum(v) / len(v) for net, v in by_net.items() if v}
    attrs = photo_attrs(conn, [o.queue_id for o in ours])
    buckets: dict[str, dict[str, list[float]]] = {"subject": {}, "shot_type": {}, "event_kind": {}}
    per_network: dict[str, dict[str, dict[str, list[float]]]] = {}
    for o in ours:
        if mean.get(o.network, 0) <= 0:
            continue
        lift = o.engagement / mean[o.network]
        for a in attrs.get(o.queue_id, []):
            for fieldname in buckets:
                value = a.get(fieldname)
                if value:
                    buckets[fieldname].setdefault(value, []).append(lift)
                    per_network.setdefault(o.network, {}).setdefault(fieldname, {}).setdefault(value, []).append(lift)

    def table(b: dict[str, list[float]]) -> dict:
        return {v: {"posts": len(l), "lift": round(bayes(sum(l), len(l), 1.0), 3)} for v, l in sorted(b.items())}

    detail: dict = {f: table(b) for f, b in buckets.items()}
    detail["per_network"] = {net: {f: table(b) for f, b in fields.items()} for net, fields in sorted(per_network.items())}
    weights: dict[str, dict[str, float]] = {f: {} for f in WEIGHT_FIELDS}
    for fieldname in WEIGHT_FIELDS:
        for value, lifts in buckets[fieldname].items():
            if len(lifts) >= MIN_BUCKET:
                weights[fieldname][value] = round(clamp_weight(bayes(sum(lifts), len(lifts), 1.0)), 2)
    sentences = []
    for fieldname in WEIGHT_FIELDS:
        old = before.get(fieldname) if isinstance(before.get(fieldname), dict) else {}
        for value in sorted(set(weights[fieldname]) | set(old)):
            new_w = weights[fieldname].get(value, 1.0)
            old_w = _weight(old, value)
            if abs(new_w - old_w) < 0.005:
                continue
            n = len(buckets[fieldname].get(value, []))
            if value not in weights[fieldname]:
                sentences.append(f"{kind_words(fieldname, value).capitalize()} go back to 1.0: {n} recent posts, fewer than {MIN_BUCKET}.")
                continue
            lift = detail[fieldname][value]["lift"] - 1
            how = f"{abs(round(lift * 100))}% {'better' if lift >= 0 else 'worse'} than average"
            sentences.append(f"{kind_words(fieldname, value).capitalize()} now weigh {new_w:.2f}, was {old_w:.2f}: "
                             f"{n} posts did {how}.")
    subj = detail["subject"]
    if all(subj.get(k, {}).get("posts", 0) >= MIN_BUCKET for k in ("event", "architecture")):
        a, e = subj["architecture"]["lift"], subj["event"]["lift"]
        diff = (a / e - 1) if e > 0 else 0.0
        sentences.append(f"Building posts did {abs(round(diff * 100))}% {'better' if diff >= 0 else 'worse'} than event posts. "
                         "The building day stays once a week.")
    return weights, detail, sentences


# ------------------------------------------------------------------ the whole suggestion

@dataclass
class Suggestion:
    times: dict
    weights: dict
    note: str
    posts: int
    moves: int
    detail: dict = field(default_factory=dict)


def learn(conn: sqlite3.Connection, cfg: config.Config, now: datetime) -> Suggestion:
    from . import pacing          # imported here: pacing may import this module to read the learned times
    tz = ZoneInfo(cfg.timezone)
    obs = observations(conn, tz, now)
    before_times = applied_times(conn)
    times, detail, sentences, moves = {}, {"times": {}}, [], 0
    for network, base in pacing.times_table().items():
        mine = [o for o in obs if o.network == network]
        entry, d, sentence, moved = decide_time(network, mine, base, before_times.get(network), now)
        times[network] = entry
        detail["times"][network] = d
        sentences.append(sentence)
        moves += int(moved)
    weights, wdetail, wsentences = decide_weights(conn, obs, applied_weights(conn))
    detail["photos"] = wdetail
    sentences += wsentences or ["Photo weights are unchanged."]
    head = f"Numbers from {len(obs)} posts in the last {LOOKBACK_DAYS} days."
    return Suggestion(times=times, weights=weights, note=" ".join([head] + sentences), posts=len(obs), moves=moves, detail=detail)


def save(conn: sqlite3.Connection, s: Suggestion, *, applied: bool, run_id: Optional[int], now: datetime) -> int:
    """The history row and the suggestion, always; the learned times and weights only when applied (live)."""
    status = "applied" if applied else "suggested"
    note = s.note if applied else "Suggested, not applied: the learner is in dry run. " + s.note
    hid = db.insert(conn, "learner_history", created_at=now.replace(microsecond=0).isoformat(), run_id=run_id, status=status,
                    applied=int(applied), posts_seen=s.posts, note=note, times=json.dumps(s.times, sort_keys=True),
                    weights=json.dumps(s.weights, sort_keys=True), detail=json.dumps(s.detail, sort_keys=True))
    settings.set(conn, SUGGESTION_KEY, json.dumps({"status": status, "applied": applied, "at": now.isoformat(), "history_id": hid,
                                                   "posts": s.posts, "times": s.times, "weights": s.weights}, sort_keys=True))
    settings.set(conn, NOTE_KEY, note)
    if applied:
        settings.set(conn, TIMES_KEY, json.dumps(s.times, sort_keys=True))
        settings.set(conn, WEIGHTS_KEY, json.dumps(s.weights, sort_keys=True))
    return hid


def refresh_numbers(ctx: runner.Context, client: Optional[BufferClient], now: datetime) -> str:
    """Read only: pull today's numbers from Buffer when a key exists and the watchdog has not already."""
    client = client if client is not None else BufferClient.from_config(ctx.conn, ctx.agent)
    if client is None:
        return "no Buffer key, used the stored numbers"
    today = now.astimezone(ZoneInfo(ctx.cfg.timezone)).date()
    if not metrics.due(ctx.conn, today):
        return "numbers already pulled today"
    m = metrics.pull(ctx, client, today=today)
    return f"pulled numbers for {m['posts']} posts" + (" (the pull failed, see errors)" if m["errors"] else "")


def run(ctx: runner.Context, *, client: Optional[BufferClient] = None, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    pulled = refresh_numbers(ctx, client, now)
    s = learn(ctx.conn, ctx.cfg, now)
    save(ctx.conn, s, applied=not ctx.dry_run, run_id=ctx.run_id, now=now)
    nweights = sum(len(v) for v in s.weights.values())
    return (f"{'DRY RUN suggested' if ctx.dry_run else 'applied'}: {s.moves} time move(s), {nweights} photo weight(s) "
            f"from {s.posts} posts; {pulled}")


# ------------------------------------------------------------------ the dashboard page

def dashboard_view(conn: sqlite3.Connection) -> dict:
    from . import pacing
    applied = applied_times(conn)
    suggestion = _json(settings.get(conn, SUGGESTION_KEY), {})
    suggested_times = suggestion.get("times") if isinstance(suggestion.get("times"), dict) else {}
    def shown(entry) -> str:
        if not isinstance(entry, dict):
            return ""
        got = {k: parse_clock(entry.get(k)) for k in DAY_TYPES}
        return when_words(got) if all(v is not None for v in got.values()) else ""

    monday, saturday = date(2026, 10, 5), date(2026, 10, 10)      # any weekday and any weekend day
    networks = []
    for network, (wd, we) in pacing.times_table().items():
        start = {"weekday": of_time(wd), "weekend": of_time(we)}
        now_used = {"weekday": of_time(post_time_for(conn, network, wd, monday)),
                    "weekend": of_time(post_time_for(conn, network, we, saturday))}
        networks.append({"network": network, "start": when_words(start), "in_use": when_words(now_used),
                         "applied": shown(applied.get(network)), "suggested": shown(suggested_times.get(network)),
                         "best_hour": (suggested_times.get(network) or {}).get("best_hour"),
                         "posts": (suggested_times.get(network) or {}).get("posts", 0)})
    applied_w = applied_weights(conn)
    suggested_w = suggestion.get("weights") if isinstance(suggestion.get("weights"), dict) else {}
    weights = []
    for fieldname in WEIGHT_FIELDS:
        a = applied_w.get(fieldname) if isinstance(applied_w.get(fieldname), dict) else {}
        s = suggested_w.get(fieldname) if isinstance(suggested_w.get(fieldname), dict) else {}
        for value in sorted(set(a) | set(s)):
            weights.append({"field": fieldname.replace("_", " "), "value": value.replace("_", " "),
                            "applied": _weight(a, value) if value in a else None,
                            "suggested": _weight(s, value) if value in s else None})
    history = [dict(r) for r in db.rows(conn, "SELECT id, created_at, status, applied, posts_seen, note FROM learner_history "
                                              "ORDER BY id DESC LIMIT 30")]
    return {"networks": networks, "weights": weights, "history": history, "suggestion": suggestion,
            "note": settings.get(conn, NOTE_KEY) or "", "dry_run": settings.dry_run(conn, "learner")}


if __name__ == "__main__":
    runner.main_for("learner", run)
