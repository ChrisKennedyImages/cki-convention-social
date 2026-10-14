"""Design samples on Chris's own approved photos, made on the Mini and shown on the dashboard's Photos page.

Chris, 2026-10-11: "these are all original photos being used NO AI at all". The cloud session that
draws the designs cannot open his Drive, so the Mini renders every motion design (render/motion.py)
on the strongest frames of his library and the dashboard shows them.

Nothing here is posted, and nothing is written to Drive (the photos are read through Drive's own
previews). Only frames Chris approved (the photo or its folder cleared) are used, and only when the
sort found no one who may be a minor and no readable personal detail, and nothing on the do-not-use
list covers them.
"""
from __future__ import annotations

import html
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from ..core import config, db, settings
from ..library import eligibility, report
from .. import music
from . import motion

# The room a photo is from and one line about what it shows. Never what is offered or how it is done
# (Chris, 2026-10-11: "keep to specifics and not talk about what is offered or what is a service").
ROOMS = {
    "stage_panel": ("MAIN STAGE", "The keynote, from the room."),
    "backstage": ("BACKSTAGE", "The minutes before the doors open."),
    "portrait": ("PORTRAITS", "Speakers and guests, backstage."),      # Chris, 2026-10-12: the speakers and VIPs, not the attendees
    "headshot": ("PORTRAITS", "Speakers and guests, backstage."),
    "vendor_hall": ("EXPO FLOOR", "On the exhibition floor."),
    "booth": ("EXPO FLOOR", "On the exhibition floor."),
    "dinner_reception": ("AFTER DARK", "After the last session."),
    "crowd": ("THE CROWD", "In the moment."),
    "candid": ("THE CROWD", "In the moment."),
    "group": ("THE CROWD", "In the moment."),
    "venue": ("THE VENUE", "The room, before the event."),
    "building_exterior": ("THE VENUE", "The building, before the event."),
    "building_interior": ("THE VENUE", "The room, before the event."),
}
OTHER = ("ON THE FLOOR", "In the moment.")
COPY_VERSION = "2026-10-11b"             # bump when the words on the cards change: the samples are made again
FOLDER_PREFIX = "design-"
STATUS_FILE = "design-status.json"       # in DATA_ROOT/renders: what the designer did last, for the Design card
LAST_SET_KEY = "designer.last_set"         # the set the last finished run was made on (written by `ccs design` when done)
PENDING_SET_KEY = "designer.pending_set"   # the set the run just started is on; it becomes LAST_SET_KEY only when it finishes
STALE_RUNNING = 45 * 60                  # a "running" status older than this was a run that died
MIN_PHOTOS = 3


# ------------------------------------------------------------------ what Chris sees on the Design card
# Chris, 2026-10-11: "Where are the mock ups with the approved images". The samples are made by
# themselves whenever the approved photos they would use change (the hourly scanner starts them), and
# the Design card always says what happened: being made, ready, or why not.

def _status_path() -> Path:
    return config.get_config().data_root / "renders" / STATUS_FILE


def write_status(state: str, message: str, **extra) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "message": message, "at": datetime.now().isoformat(timespec="seconds"), **extra}))


def read_status() -> dict:
    try:
        st = json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {}
    if st.get("state") == "running":
        try:
            if (datetime.now() - datetime.fromisoformat(st["at"])).total_seconds() > STALE_RUNNING:
                return {**st, "state": "failed", "message": "the last run stopped before it finished; it starts again on its own"}
        except (KeyError, ValueError):
            pass
    return st


def waiting_for_sort(conn) -> int:
    """Approved photos (by the photo or its folder) the sorter has not looked at yet; it does these first."""
    cleared = [(fid,) for fid, d in eligibility.folder_decisions(conn).items() if d == "cleared"]
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS cleared_folder (drive_id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM temp.cleared_folder")
    conn.executemany("INSERT INTO temp.cleared_folder VALUES (?)", cleared)
    return db.one(conn, """SELECT COUNT(*) AS n FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id
                           WHERE p.trashed = 0 AND COALESCE(c.method, '') NOT IN ('ollama', 'vision')
                             AND (p.clearance = 'cleared'
                                  OR (p.clearance = 'inherit' AND p.folder_id IN (SELECT drive_id FROM temp.cleared_folder)))""")["n"]


def readiness(conn) -> dict:
    """{ready: approved photos the designs can use now, waiting: approved photos still to be sorted}."""
    return {"ready": len(pick(conn, 400)), "waiting": waiting_for_sort(conn)}


def too_few(r: dict) -> str:
    more = f"; {r['waiting']} more approved are waiting for the sorter, which does approved photos first" if r["waiting"] else \
        "; approve more on the Photos page"
    return f"only {r['ready']} approved photo(s) are ready for designs (sorted, nobody who may be under 18), {MIN_PHOTOS} are needed{more}"


def start_in_background() -> None:
    """`ccs design` on its own (its own lock: a second start while one runs does nothing). The output
    goes to logs/designer.log; what happened goes to the status file the Design card reads."""
    import subprocess
    import sys
    cfg = config.get_config()
    cfg.ensure_dirs()
    with open(cfg.data_root / "logs" / "designer.log", "ab") as log:
        subprocess.Popen([sys.executable, "-m", "convention_social.cli", "design"], cwd=str(config.REPO_ROOT),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def auto(conn) -> str:
    """For the hourly scanner: new samples whenever the approved photos they would use have changed."""
    rows = pick(conn, 6)
    if len(rows) < MIN_PHOTOS:
        return "design samples: " + too_few(readiness(conn))
    if read_status().get("state") == "running":
        return "design samples: being made"
    key = pool_key(conn)
    if settings.get(conn, LAST_SET_KEY) == key:
        return "design samples: up to date"
    # the set is recorded as made only when the run finishes (made()); a run that fails is tried again next hour
    settings.set(conn, PENDING_SET_KEY, key)
    write_status("running", "being made on your newest approved photos")
    start_in_background()
    return "design samples: started on the newest approved photos"


def pool_key(conn) -> str:
    """What the samples are made from: the approved photos they may use, as a set. Not the six drawn (2026-10-14):
    those rotate with every use, and a remake on every rotation would churn hourly; a remake comes when the approved
    photos change (one approved, one taken away) or the words on the cards do."""
    return COPY_VERSION + ":" + ",".join(sorted(r["drive_id"] for r in pick(conn, 400)))


def made(conn) -> None:
    """`ccs design` finished: the set it started on is the set the samples are made on."""
    settings.set(conn, LAST_SET_KEY, settings.get(conn, PENDING_SET_KEY) or "")


def usable(conn, row) -> bool:
    photo = db.one(conn, "SELECT * FROM photos WHERE id=?", (row["id"],))
    if photo is None or photo["trashed"]:
        return False
    if eligibility.clearance_of(conn, photo) in ("blocked", "excluded"):
        return False
    if eligibility.blocked_by_list(conn, photo):
        return False
    if (row["shot_type"] if "shot_type" in row.keys() else None) in eligibility.NOT_OFFERED:
        return False                     # a costume photo, which Event Caliber does not offer
    if (row["event_kind"] if "event_kind" in row.keys() else None) in eligibility.NOT_OFFERED_KINDS:
        return False                     # a wedding or a private occasion (Chris, 2026-10-11)
    return not any(c["consent"] == "no" for c in eligibility.credits_for(conn, photo))


def pick(conn, n: int = 6) -> list:
    """Up to n of the frames Chris approved, one per room first so the samples show the range.
    Chris, 2026-10-11: "if it's not approved then don't use it yet or at all"."""
    # every approved photo counts here, not four per event: most of the work Chris approved can be from one
    rows = [r for r in report.best(conn, 400, cap=None) if eligibility.clearance_of(conn, r) == "cleared" and usable(conn, r)]
    # the rotation (2026-10-14): the least recently used first, on any surface, so each set of samples shows photos the
    # posts, the site and the last samples did not; the strength order only breaks ties (library/report.rotate)
    rows = report.rotate(conn, rows)
    # one room and one event before any repeats (Chris, 2026-10-11: "not have CPAC and ACU the first thing on everything")
    picked, rooms, events = [], set(), set()
    for want_room, want_event in ((True, True), (True, False), (False, True), (False, False)):
        for r in rows:
            room = ROOMS.get(r["shot_type"] or "", OTHER)[0]
            event = (r["convention_name"] or "").strip().lower() or r["folder_id"]
            if r in picked or (want_room and room in rooms) or (want_event and event in events):
                continue
            picked.append(r)
            rooms.add(room)
            events.add(event)
            if len(picked) >= n:
                return picked
    return picked


def make(conn, fetch: Callable[[str], bytes], *, out_root: Optional[Path] = None, n: int = 6,
         reels: bool = True, log: Callable[[str], None] = print) -> Path:
    rows = pick(conn, n)
    if len(rows) < MIN_PHOTOS:
        raise RuntimeError(too_few(readiness(conn)))
    shots = []
    for r in rows:
        room, line = ROOMS.get(r["shot_type"] or "", OTHER)
        im = Image.open(io.BytesIO(fetch(r["drive_id"])))
        im.load()
        shots.append(motion.Shot(im.convert("RGB"), room, line))
    root = out_root or config.get_config().data_root / "renders"
    out = root / f"{FOLDER_PREFIX}{datetime.now():%Y%m%d-%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    copy = motion.MotionCopy()
    made, failed = [], []
    for name, job in (("fan-post.jpg", lambda p: motion.fan_post(shots, copy, out=p, focus=len(shots) // 2)),
                      ("spotlight-post.jpg", lambda p: motion.spotlight_post(shots, copy, out=p, index=min(2, len(shots) - 1)))):
        job(out / name)
        made.append(name)
    made += [p.name for p in motion.carousel(shots, copy, out_dir=out)]
    track = music.current(conn)
    if reels:
        if track is None:
            failed.append("the reels are silent: no music added yet (Library page, Music for reels)")
        for name, job in (("rooms-reel.mp4", motion.rooms_reel),):
            try:
                job(shots, copy, out=out / name, audio=track)
                made.append(name)
            except Exception as e:  # noqa: BLE001 — the stills stand on their own; the page says why
                failed.append(f"{name}: {e}")
                log(f"{name} not made: {e}")
    (out / "about.json").write_text(json.dumps({"photos": [r["drive_id"] for r in rows], "made": made, "failed": failed,
                                                "music": track.name if track else None,
                                                "at": datetime.now().isoformat(timespec="seconds")}, indent=1))
    (out / "index.html").write_text(page(out.name, made, failed))
    # the rotation's memory (a stand-in row without an id, as a test hands in, records nothing)
    report.record_use(conn, "sample", [r["id"] for r in rows if "id" in r.keys()], ref=f"sample:{out.name}")
    log(f"design samples: {out}")
    return out


def page(folder: str, made: list[str], failed: list[str]) -> str:
    """One dark page for the phone: the reels first, then the posts, then the carousel in order."""
    def src(name: str) -> str:
        return html.escape(f"/library/design/{folder}/{name}")
    vids = "".join(f'<h2>{html.escape(n.replace("-", " ").replace(".mp4", ""))}</h2><video src="{src(n)}" controls playsinline loop muted autoplay></video>'
                   for n in made if n.endswith(".mp4"))
    posts = "".join(f'<h2>{html.escape(n.replace("-", " ").replace(".jpg", ""))}</h2><img src="{src(n)}" alt="">'
                    for n in made if n.endswith("-post.jpg"))
    slides = "".join(f'<img src="{src(n)}" alt="">' for n in sorted(n for n in made if n.startswith("slide-")))
    errs = "".join(f"<p class=bad>{html.escape(f)}</p>" for f in failed)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Design samples</title><style>
body{{margin:0;background:#0a0a0b;color:#f3f3f1;font:16px/1.5 -apple-system,Helvetica,Arial,sans-serif;padding:16px}}
h1{{font-size:22px;margin:4px 0}}h2{{font-size:15px;color:#00e1ff;text-transform:uppercase;letter-spacing:.12em;margin:28px 0 8px}}
p{{color:#8c8c93}}.bad{{color:#ff6b6b}}img,video{{width:100%;max-width:540px;display:block;border-radius:10px;margin:0 0 10px}}
.strip{{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory}}.strip img{{flex:none;width:86%;max-width:460px;scroll-snap-align:start}}
</style></head><body><h1>Design samples on your photos</h1>
<p>Made on the Mini from the strongest frames in your library. For review only: nothing here is posted.</p>{errs}
{vids}{posts}<h2>carousel, swipe</h2><div class="strip">{slides}</div></body></html>"""
