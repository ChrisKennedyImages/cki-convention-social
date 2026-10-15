"""A photo from Chris's phone, while he is shooting, becomes a draft post within minutes.

Chris, 2026-10-14: "if I'm in the middle of shooting conventions and want to share a photo I took from my
phone can we set up a way to send the photos to the suite for social upload?" His answers: a draft post
right away, from a page on the dashboard.

The Send a photo page (Today) takes one picture from the camera roll or the camera and an optional line
about it. The picture is kept under DATA_ROOT/phone as the photo's own file, re-encoded from its pixels so
no camera data or GPS stays with it, and never written to Drive (the library is read only; this is not the
library). It is a `photos` row of its own (drive_id phone-<stamp>, the folder "From the phone", source
'phone'), cleared by the act of sending it: his own photo, sent by him, for his own post. The weekly Drive
pass never marks it trashed and the nightly sweep never deletes its file.

Then this agent (`ccs run phone`, started by the page; a second start while one runs waits its turn) does
for the one photo what the daily draft does: the sorter when one is on (the free local one even in dry
run), Claude's final check (a readable plate or a wedding: the draft stops and the page
says why; no age gate, 2026-10-15), the captions with his line as a fact, the single design, the art director, a queue row for
today marked `asap` (the publisher sends it as soon as he approves it, never at the day's usual slot), and
the ping with the card and the Approve button. Nothing posts without his Approve; the pre-post window
stays. The lane follows the content lane's dry-run switch: it is a draft of that lane.

Post to Event Caliber (Chris, 2026-10-15: "i want to be able to text an image from a current event im doing to the
dashboard to auto post immediately"): a share sheet button on his iPhone sends the photo and a line to eventcaliber.com
(worker/index.js /api/send, his SEND_TOKEN), where it waits under private/sends/, never served. This agent's
one-minute job (`--when-waiting`: a quiet minute leaves no run behind) pulls each one with the Mini's own token, keeps
it exactly like a send from the page (`via` 'share'), deletes it at the site and drafts it on the same road. His send
is his approval: a draft whose art director passed it and whose captions pass the publisher's door (one rewrite, as
at the door) is approved at once and posts right away (Buffer's shareNow, no pre-post window: Chris, 2026-10-15,
"Right away"), and the publisher is started. A readable plate, a wedding, a
caption that still breaks a rule, the art director's no or no look stop it, and the phone hears why. In the content
lane's dry run Claude does not look, so nothing is approved; the phone hears what it would have posted.
"""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import secrets as pysecrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import storage
from ..ai import names
from ..core import approve_token, config, db, notify, runner, settings
from ..library import classify, eligibility

FOLDER_ID = "phone"
FOLDER_NAME = "From the phone"
PREFIX = "phone-"
MIN_WIDTH = 1200                 # the shorter side may be less; a post needs one side this long
MAX_BYTES = 40 * 1024 * 1024
NOTE_MAX = 140
THUMB_EDGE = 400
STATUSES = ("pending", "drafting", "drafted", "failed")
STALE_DRAFTING = timedelta(minutes=20)       # a send left "drafting" this long was a run that died: tried again
SORT_HINT = "Sent from the photographer's phone during an event he is photographing now."
VIA_PAGE, VIA_SHARE = "page", "share"         # the Send a photo page (waits for his Approve); the share sheet (approved by sending)
REMOTE_ID = re.compile(r"^\d{13}-[0-9a-f]{16}$")  # a send's name at the site (worker/index.js SEND_ID)
PULL_FAILURES_KEY = "phone.pull_failures"
PULL_QUIET_FAILURES = 5                       # a minute's blip is not news; five in a row (five minutes) is said, once


class Refused(ValueError):
    pass


def register_heif() -> None:
    """HEIC, the iPhone's own format, through pillow_heif when it is installed (it is on the Mini)."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def folder() -> Path:
    return config.get_config().data_root / "phone"


def thumb_path(drive_id: str) -> Path:
    return config.get_config().data_root / "thumbs" / f"{drive_id}.jpg"


def clean_note(conn: sqlite3.Connection, note: str) -> str:
    """His line, one line, without a known name in it (a caption never names an event or a person)."""
    note = " ".join((note or "").split())[:NOTE_MAX]
    named = names.mentions(note, names.public_names(conn))
    if named:
        raise Refused(f"your line names {', '.join(named)}; say what the room was, never who or which event")
    return note


def _taken_at(im: Image.Image) -> str:
    """When the phone took it, in Drive's form (YYYY:MM:DD HH:MM:SS), else now."""
    try:
        value = im.getexif().get_ifd(0x8769).get(36867)       # DateTimeOriginal
        if isinstance(value, str) and len(value) >= 19:
            return value[:19]
    except Exception:  # noqa: BLE001  a file without EXIF, or an odd one: now
        pass
    return datetime.now().strftime("%Y:%m:%d %H:%M:%S")


def write_thumb(im: Image.Image, path: Path) -> Path:
    small = im.copy()
    small.thumbnail((THUMB_EDGE, THUMB_EDGE))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    small.save(tmp, "JPEG", quality=85)
    tmp.replace(path)
    return path


def ensure_thumb(row) -> Optional[Path]:
    """The preview of a phone photo, made again from its own file when the nightly sweep took it."""
    path = thumb_path(row["drive_id"])
    if path.is_file() and path.stat().st_size > 0:
        return path
    own = Path(row["local_path"] or "")
    if not own.is_file():
        return None
    with Image.open(own) as im:
        return write_thumb(im.convert("RGB"), path)


def keep(conn: sqlite3.Connection, data: bytes, note: str = "", *, now: Optional[str] = None, via: str = VIA_PAGE,
         remote_id: Optional[str] = None) -> int:
    """The picture and the note, kept; the send's id. Refuses what is not a photo, or too small for a post. `via` and
    `remote_id`: a send from the share sheet, by its name at the site."""
    register_heif()
    if not data:
        raise Refused("the file is empty")
    if len(data) > MAX_BYTES:
        raise Refused("the file is over 40 MB")
    note = clean_note(conn, note)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise Refused("not a photo file (send a JPEG, PNG or HEIC)")
    taken = _taken_at(im)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.width, im.height) < MIN_WIDTH:
        raise Refused(f"too small for a post: {im.width} by {im.height} pixels, {MIN_WIDTH} or more on the long side needed "
                      "(send the original, not a preview)")
    im.thumbnail((storage.MAX_EDGE, storage.MAX_EDGE), Image.LANCZOS)      # kept for good, so kept small (2026-10-15)
    now = now or db.utcnow()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + pysecrets.token_hex(3)
    drive_id = PREFIX + stamp
    out = folder() / f"{stamp}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    im.save(tmp, "JPEG", quality=92, optimize=True)       # the pixels only: no camera data, no GPS
    tmp.replace(out)
    write_thumb(im, thumb_path(drive_id))
    kept = out.read_bytes()
    if db.one(conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (FOLDER_ID,)) is None:
        db.insert(conn, "drive_folders", drive_id=FOLDER_ID, name=FOLDER_NAME, path=FOLDER_NAME, clearance="cleared",
                  clearance_at=now, first_seen_at=now, last_seen_at=now)
    pid = db.insert(conn, "photos", drive_id=drive_id, name=out.name, mime_type="image/jpeg", md5=hashlib.md5(kept).hexdigest(),
                    size_bytes=len(kept), folder_id=FOLDER_ID, width=im.width, height=im.height, taken_at=taken,
                    clearance="cleared", clearance_at=now, local_path=str(out), source="phone", first_seen_at=now, last_seen_at=now)
    # a row of its own, so the scanner's folder pass leaves it alone; the sorter and the final check fill it in
    db.insert(conn, "classifications", photo_id=pid, method="folder", is_convention=1, subject="event", event_kind="unknown",
              orientation=classify.orientation(im.width, im.height), classified_at=now)
    conn.execute("UPDATE drive_folders SET image_count = (SELECT COUNT(*) FROM photos WHERE folder_id=? AND trashed=0) WHERE drive_id=?",
                 (FOLDER_ID, FOLDER_ID))
    return db.insert(conn, "phone_sends", photo_id=pid, note=note, status="pending", via=via, remote_id=remote_id,
                     created_at=now, updated_at=now)


SEND_SQL = ("SELECT s.*, p.drive_id, p.local_path, p.width, p.height FROM phone_sends s JOIN photos p ON p.id = s.photo_id ")


def pending(conn: sqlite3.Connection, now: Optional[str] = None) -> list[sqlite3.Row]:
    """The sends still to draft: new ones, and any a run left "drafting" too long ago (it died)."""
    stale = ((datetime.fromisoformat(now) if now else datetime.now(timezone.utc)) - STALE_DRAFTING).replace(microsecond=0).isoformat()
    return db.rows(conn, SEND_SQL + "WHERE s.status = 'pending' OR (s.status = 'drafting' AND s.updated_at < ?) ORDER BY s.id", (stale,))


def waiting(conn: sqlite3.Connection) -> int:
    return db.one(conn, "SELECT COUNT(*) AS n FROM phone_sends WHERE status IN ('pending', 'drafting')")["n"]


def recent(conn: sqlite3.Connection, n: int = 20) -> list[dict]:
    """For the page: the latest sends, newest first, each with a line that says where it stands."""
    out = []
    for r in db.rows(conn, "SELECT s.*, p.drive_id, p.local_path, p.width, p.height, q.status AS queue_status FROM phone_sends s "
                           "JOIN photos p ON p.id = s.photo_id LEFT JOIN content_queue q ON q.id = s.queue_id ORDER BY s.id DESC LIMIT ?", (n,)):
        d = dict(r)
        d["line"] = {"pending": "waiting its turn: sorted, checked and drafted in a few minutes; your phone gets a ping",
                     "drafting": "being sorted, checked and drafted now; your phone gets a ping",
                     "drafted": f"drafted as post #{d['queue_id']}; approve it there or on the ping",
                     "failed": f"not drafted: {plain(d['error'])}"}[d["status"]]
        if d.get("via") == VIA_SHARE:
            d["line"] = {"pending": "from the share sheet, waiting its turn: checked in a few minutes; your phone gets a ping",
                         "drafting": "from the share sheet, being checked now; your phone gets a ping",
                         "failed": f"from the share sheet, not posted: {plain(d['error'])}"}.get(
                d["status"], f"from the share sheet, approved by your send as post #{d['queue_id']}"
                if d.get("queue_status") not in (None, "draft", "rejected")
                else f"from the share sheet, drafted as post #{d['queue_id']} and waiting for your Approve")
        out.append(d)
    return out


def _status(conn, sid: int, status: str, *, queue_id: Optional[int] = None, error: Optional[str] = None) -> None:
    conn.execute("UPDATE phone_sends SET status=?, queue_id=COALESCE(?, queue_id), error=?, updated_at=? WHERE id=?",
                 (status, queue_id, error, db.utcnow(), sid))


def via_of(send) -> str:
    return send["via"] if "via" in send.keys() and send["via"] else VIA_PAGE


def local_time(ctx: runner.Context, iso: str) -> str:
    """HH:MM where he is, from a UTC stamp; the stamp's own clock time when it cannot be read."""
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo(ctx.cfg.timezone)).strftime("%H:%M")
    except ValueError:
        return (iso or "")[11:16]


DETAIL_WORDS = {"badge_name": "a name on a badge", "vehicle_plate": "a readable car plate", "screen": "a readable screen",
                "document": "a readable document", "house_number": "a house number", "street_sign": "a street sign"}


def plain(why: str) -> str:
    """A reason in words for the phone: the final check's codes (library/classify.py DETAILS) in plain words, a network
    named as it is written, no full stop of its own (the ping adds the next sentence)."""
    why = (why or "no reason recorded").strip().rstrip(".")
    why = re.sub(r"shows personal details: ([a-z_, ]+)",
                 lambda m: "it shows " + " and ".join(DETAIL_WORDS.get(d.strip(), d.strip().replace("_", " ")) for d in m.group(1).split(",")), why)
    why = re.sub(r"\b(instagram|facebook|pinterest)\b", lambda m: m.group(1).capitalize(), why)
    return why[0].lower() + why[1:] if why.startswith("The ") else why


def tell(ctx: runner.Context, title: str, message: str, **kw) -> bool:
    """A send from the share sheet is answered on the phone, dry run or not: he sent a real photo and is not at the
    dashboard (the same reasoning as the publisher's eight-hour nudge)."""
    return notify.push(title, message, dry_run=False, priority="default", conn=ctx.conn, agent=ctx.agent, **kw)


def _failed(ctx: runner.Context, send, why: str, *, queue_id: Optional[int] = None) -> str:
    """Said on the page and on the Agents page, never only in a log; a send from the share sheet also on the phone."""
    _status(ctx.conn, send["id"], "failed", queue_id=queue_id, error=why)
    runner.record_error(ctx.conn, ctx.agent, "send", f"The photo you sent at {send['created_at'][11:16]} UTC was not drafted: {why}")
    if via_of(send) == VIA_SHARE:
        tell(ctx, f"{ctx.cfg.brand_name}: your photo was not posted",
             f"The photo you sent at {local_time(ctx, send['created_at'])} was not posted: {plain(why)}. Tap to see it.",
             click=notify.link(f"/queue/{queue_id}" if queue_id else "/send"))
    return f"send #{send['id']} not drafted: {why}"


PHOTO_SQL = """SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
               FROM photos p JOIN classifications c ON c.photo_id = p.id WHERE p.id=?"""


def fill_sort_from_check(conn: sqlite3.Connection, photo_id: int, verdict: dict) -> None:
    """A photo Claude looked at in full is never "not sorted yet": when no sorter ran, the final check's
    answer is the sort (library/eligibility.is_candidate reads classifications first)."""
    row = db.one(conn, "SELECT method FROM classifications WHERE photo_id=?", (photo_id,))
    if row is None or row["method"] in eligibility.SORTED_METHODS:
        return
    kind = verdict.get("event_kind") if verdict.get("event_kind") in classify.KINDS else "unknown"
    conn.execute("UPDATE classifications SET method='vision', personal_details=?, "
                 "shot_type=COALESCE(shot_type, ?), event_kind=?, is_convention=?, summary=?, model=?, classified_at=? WHERE photo_id=?",
                 (__import__("json").dumps(verdict.get("personal_details") or []),
                  verdict.get("shot_type") if verdict.get("shot_type") in classify.SHOT_TYPES else None, kind,
                  0 if kind in classify.NOT_OFFERED_KINDS else 1, (verdict.get("summary") or "")[:300],
                  verdict.get("model_used") or "", db.utcnow(), photo_id))


def draft_send(ctx: runner.Context, send, *, check_client=None, drafter=None, art_client=None, sorter=None) -> str:
    from . import content
    conn = ctx.conn
    _status(conn, send["id"], "drafting")
    photo = db.one(conn, PHOTO_SQL, (send["photo_id"],))
    own = Path((photo["local_path"] if photo else "") or "")
    if photo is None or not own.is_file():
        return _failed(ctx, send, "the photo's file is gone from the Mini (send it again)")
    data = own.read_bytes()
    # the sort (what it shows, how strong it is): the free local sorter even in dry run, Claude when live and the key is set
    sorter = sorter if sorter is not None else classify.pick_sorter(conn, agent=ctx.agent)
    if sorter is not None and (not ctx.dry_run or not sorter.paid()):
        try:
            found = sorter.classify(classify.jpeg_bytes(data), SORT_HINT)
        except Exception as e:  # noqa: BLE001  the sorter failing is not the end: the final check still looks
            found = None
            ctx.log.warning("phone: the sorter failed on send %s: %s", send["id"], e)
        if found:
            classify.save_sort(conn, photo, found, sorter.method, sorter.model)
    if not ctx.dry_run:
        try:
            verdict = classify.final_check(conn, photo["id"], data, client=check_client, agent=ctx.agent)
        except Exception as e:  # noqa: BLE001  the API or the network, not the photo
            return _failed(ctx, send, f"Claude's final check could not run ({type(e).__name__}: {e}); send it again in a few minutes")
        if verdict is None:
            return _failed(ctx, send, "Claude could not look at the photo (no key, the monthly cap, or a refusal: the Agents page says which)")
        fill_sort_from_check(conn, photo["id"], verdict)
        ok, why = eligibility.is_eligible(conn, photo["id"])
    else:
        ok, why = eligibility.is_candidate(conn, photo["id"])
        if not ok:
            why = f"dry run, so Claude did not look at it, and it is {why} (switch the content lane live on the Agents page)"
    if not ok:
        return _failed(ctx, send, why)
    row = dict(db.one(conn, PHOTO_SQL, (photo["id"],)))
    row["credit"] = eligibility.credit_line(conn, row["id"])
    row["last_use"] = None
    today = datetime.now(ZoneInfo(ctx.cfg.timezone)).date()
    shared = via_of(send) == VIA_SHARE
    qid, art, line = content.make_draft(
        ctx, today, [(row, data)], "single", want="event", kind_used="event", asked="single", track=None, drafter=drafter,
        art_client=art_client, why="sent from your share sheet" if shared else "sent from your phone", note=send["note"] or "",
        extra_meta={"source": VIA_SHARE if shared else "phone", "asap": True, "note": send["note"] or "", "send_id": send["id"]},
        ping=(f"{ctx.cfg.brand_name}: your photo from the floor, a post to approve",
              "A single post for today from the photo you sent. Post now and it goes out at once, or follow the pace, or "
              "skip. Tap to see it."),
        quiet=shared)                         # a send from the share sheet is answered below, once it is approved or stopped
    if art.get("verdict") == "reject":
        return _failed(ctx, send, f"the art director turned it back: {art.get('notes', '')}", queue_id=qid)
    if shared:
        return approve_sent(ctx, send, qid, art, line)
    _status(conn, send["id"], "drafted", queue_id=qid)
    return line


def where_words(row) -> str:
    """The networks the post goes to, in words: its targets the suite posts to (POST_NETWORKS when the code has it)."""
    from ..buffer import payloads
    on = payloads.posting_networks() if hasattr(payloads, "posting_networks") else payloads.NETWORKS
    try:
        nets = [n for n in json.loads(row["targets"] or "[]") if n in on]
    except ValueError:
        nets = []
    names = [n.capitalize() for n in nets] or ["Instagram"]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def approve_sent(ctx: runner.Context, send, qid: int, art: dict, line: str) -> str:
    """Chris, 2026-10-15: a photo he sends from the share sheet is approved by the act of sending. What still stops it:
    Claude's final check (above), the art director's no or no look, and the publisher's own door (the captions, one
    rewrite, then they still break a rule; the photo; a repeat). In the content lane's dry run Claude did not look, so
    nothing is approved. Approved, it posts right away (Chris, 2026-10-15: Buffer's shareNow, publisher.posts_now, no
    pre-post window), and the publisher is started now."""
    from . import publisher
    conn = ctx.conn
    row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
    at = local_time(ctx, send["created_at"])
    brand = ctx.cfg.brand_name
    if ctx.dry_run:
        _status(conn, send["id"], "drafted", queue_id=qid)
        tell(ctx, f"{brand}: dry run, your photo was not posted",
             f"Dry run: the photo you sent at {at} was drafted as post {qid} and not posted. The content lane is in dry run, so "
             "Claude did not check it, and nothing is approved without that check. Tap to see what it would have posted.",
             click=notify.link(f"/queue/{qid}"))
        return f"{line}; dry run: not approved, and the phone was told"
    if art.get("verdict") != "pass":
        _status(conn, send["id"], "drafted", queue_id=qid)
        why = ("the art director could not look at it this time" if art.get("verdict") == "not reviewed"
               else f"the art director did not pass it: {plain(art.get('notes') or str(art.get('verdict')))}")
        tell(ctx, f"{brand}: your photo was not posted yet",
             f"The photo you sent at {at} is drafted as post {qid} but not posted: {why}. It waits for your Approve. Tap to see it.",
             click=notify.link(f"/queue/{qid}"), **content_ping(conn, row, art))
        return f"{line}; not approved: the art director did not pass it"
    stop, row = publisher.check_in(ctx, row)
    if stop:
        why = stop[1]
        conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (why, db.utcnow(), qid))
        return _failed(ctx, send, why, queue_id=qid)
    meta = json.loads(row["rule_report"] or "{}")
    meta["approved_by"] = VIA_SHARE
    now = db.utcnow()
    conn.execute("UPDATE content_queue SET status='approved', approved_at=?, last_error=NULL, rule_report=?, updated_at=? WHERE id=?",
                 (now, json.dumps(meta), now, qid))
    _status(conn, send["id"], "drafted", queue_id=qid)
    row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
    where = where_words(row)
    card = {"click": notify.link(f"/queue/{qid}"), "actions": notify.open_action(qid),
            "attach": notify.card_link(qid, approve_token.issue(conn, row)), "filename": f"post-{qid}.jpg"}
    if settings.dry_run(conn, "publisher"):
        tell(ctx, f"{brand}: dry run, your photo was not posted",
             f"Dry run: the photo you sent at {at} passed the checks and is approved by your send as post {qid}, but the "
             f"publisher is in dry run, so nothing was posted. Live, it would have gone out on {where} right away. "
             "Tap to see it.", **card)
    else:
        tell(ctx, f"{brand}: your photo is going out now",
             f"The photo you sent at {at} passed the checks and is going to {where} now. You get a ping when it is up, "
             "with the link; to take it down, delete it there. Tap to see it.", **card)
    runner.start_agent("publisher", wait=True)        # handed to Buffer now (shareNow), not on the publisher's next ten minutes
    return f"{line}; approved by your send, going out now"


def content_ping(conn, row, art) -> dict:
    from . import content
    return {k: v for k, v in content.ping_extras(conn, row, art).items() if k != "click"}


# ------------------------------------------------------------------ the share sheet's sends, from the site

def say_refused(ctx: runner.Context, sent: dict, why: str) -> None:
    runner.record_error(ctx.conn, ctx.agent, "send", f"A photo from the share sheet was not kept: {why}")
    tell(ctx, f"{ctx.cfg.brand_name}: your photo was not posted",
         f"The photo you sent at {local_time(ctx, str(sent.get('received_at') or ''))} was not posted: {plain(why)}.",
         click=notify.link("/send"))


def pull(ctx: runner.Context, api) -> str:
    """Each photo the share sheet left at eventcaliber.com: fetched with the Mini's token, kept like a send from the page
    (`via` share, `remote_id` its name there), then deleted there. One that cannot be a photo is deleted there too and
    the phone hears why. A fetch that fails leaves it there for the next minute; a send kept before its delete went
    through is deleted again, never kept twice. A site that cannot be reached is said once, after five minutes of it."""
    conn = ctx.conn
    try:
        waiting = api.sends()
    except Exception as e:  # noqa: BLE001  the site or the network: counted, said once it stands
        failures = int(settings.get(conn, PULL_FAILURES_KEY) or 0) + 1
        settings.set(conn, PULL_FAILURES_KEY, str(failures))
        if failures >= PULL_QUIET_FAILURES:
            runner.record_error_once(conn, ctx.agent, "send_pull",
                                     "The photos sent from the share sheet cannot be read from eventcaliber.com (five minutes or more). "
                                     "They wait there and are picked up when it answers.")
        return f"the site could not be reached ({type(e).__name__}); nothing pulled"
    settings.set(conn, PULL_FAILURES_KEY, "0")
    done, kept, refused, left = [], 0, 0, 0
    for sent in waiting:
        rid = str(sent.get("id") or "")
        if not REMOTE_ID.match(rid):
            continue
        if db.one(conn, "SELECT 1 FROM phone_sends WHERE remote_id=?", (rid,)):
            done.append(rid)                              # kept on an earlier pull; the delete there did not go through
            continue
        try:
            data = api.send_bytes(rid)
        except Exception as e:  # noqa: BLE001  left at the site for the next pull
            ctx.log.warning("phone: send %s could not be fetched: %s", rid, e)
            left += 1
            continue
        try:
            keep(conn, data, str(sent.get("note") or ""), via=VIA_SHARE, remote_id=rid)
            kept += 1
        except Refused as e:
            say_refused(ctx, sent, str(e))
            refused += 1
        done.append(rid)
    deleted = 0
    if done:
        try:
            deleted = api.ack_sends(done)
        except Exception as e:  # noqa: BLE001  kept here already; the next pull deletes them there
            ctx.log.warning("phone: the site did not take the delete of %s: %s", done, e)
    return f"share sheet: kept {kept}, refused {refused}, left at the site {left}, deleted there {deleted}"


def run(ctx: runner.Context, api=None, **clients) -> str:
    """The share sheet's sends first (when this Mini has the site's token), then every send waiting, one after the
    other, on the content lane's dry-run switch."""
    dry = settings.dry_run(ctx.conn, "content")
    if dry != ctx.dry_run:
        ctx = dataclasses.replace(ctx, dry_run=dry)
    from ..booking.remote import SiteAPI
    api = api or SiteAPI.from_config()
    pulled = pull(ctx, api) if api is not None else ""
    lines = []
    while True:
        rows = pending(ctx.conn)
        if not rows:
            break
        lines.append(draft_send(ctx, rows[0], **clients))
    drafted = "; ".join(lines) if lines else "nothing sent from the phone is waiting"
    return f"{pulled}; {drafted}" if pulled else drafted


def anything_waiting() -> bool:
    """The one-minute job's first look (launchd, `--when-waiting`): a send left on the Mini, or one waiting at the site.
    A site that cannot be asked means yes: the full run says why, and counts it."""
    conn = db.connect()
    try:
        if pending(conn):
            return True
    finally:
        conn.close()
    from ..booking.remote import SiteAPI
    api = SiteAPI.from_config()
    if api is None:
        return False
    try:
        return bool(api.sends())
    except Exception:  # noqa: BLE001
        return True


def main() -> None:
    """`python -m convention_social.agents.phone [--when-waiting]`: with the flag, a quiet minute exits at once and
    leaves no agent run behind (the job runs every minute)."""
    if "--when-waiting" in sys.argv and not anything_waiting():
        sys.exit(0)
    runner.main_for("phone", run)


if __name__ == "__main__":
    main()
