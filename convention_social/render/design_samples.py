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
import shutil
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
COPY_VERSION = "2026-10-15"              # bump when the words on the cards change: the samples are made again (2026-10-15: once, so
#                                          every set on the Mini records its photos per sample and has its Post this)
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
                continue
            try:
                made.append(cover_for(name, shots, copy, out))
            except Exception as e:  # noqa: BLE001 — the reel plays without its poster; the player shows its own first frame
                log(f"{name} cover not made: {e}")
    samples = samples_for(rows, made)
    (out / "about.json").write_text(json.dumps({"photos": [r["drive_id"] for r in rows], "made": made, "failed": failed,
                                                "music": track.name if track else None, "samples": samples,
                                                "at": datetime.now().isoformat(timespec="seconds")}, indent=1))
    (out / "index.html").write_text(page(out.name, made, failed, samples, music=music.credit(conn, track.name) if track else ""))
    # the rotation's memory (a stand-in row without an id, as a test hands in, records nothing)
    report.record_use(conn, "sample", [r["id"] for r in rows if "id" in r.keys()], ref=f"sample:{out.name}")
    log(f"design samples: {out}")
    return out


def cover_for(name: str, shots: list, copy, out: Path) -> str:
    """The reel's own cover frame, saved as `<reel>-cover.jpg` beside it: the poster its player shows until it is
    tapped. A reel's first frame is the empty backdrop before the cards deal in, so without a poster the player
    on the page is a black box (seen on the first unmuted page, 2026-10-14)."""
    stills = motion.reel_stills(name.split("-")[0], shots, copy, out_dir=out / "stills")
    cover = out / f"{name[:-4]}-cover.jpg"
    stills[0].replace(cover)
    shutil.rmtree(out / "stills", ignore_errors=True)
    return cover.name


# ------------------------------------------------------------------ Post this (Chris, 2026-10-15)
# "Put a Post this on every design sample so I can turn a sample I like into a real draft post." Each sample on the
# page names the design it is and the photos it was made from (about.json `samples`, the hero first, the way the
# daily draft's renderer takes them: agents/content.make_renderer puts the hero where the eye goes). The press goes
# to the dashboard (POST /library/design/<folder>/post) and the sample agent (agents/sample.py) drafts it on the daily
# draft's road and gates. A sample whose folder was made again, or whose photos are no longer approved, says so here.

# the file each sample is shown as -> (the daily draft's design name, where its hero sits among the photos); the
# hero is the one make() put in the middle of the fan, at the spotlight's index, or first on the carousel and the reel
SAMPLE_DESIGNS = {"fan-post.jpg": "fan", "spotlight-post.jpg": "spotlight", "slide-01.jpg": "carousel", "rooms-reel.mp4": "reel"}


def _hero_index(design: str, n: int) -> int:
    return {"fan": n // 2, "spotlight": min(2, n - 1)}.get(design, 0)


def samples_for(rows: list, made: list[str]) -> list[dict]:
    """[{design, file, photos (ids, the hero first), hero}] for every sample make() made. A stand-in row without an id
    (as a test hands in) leaves the photos empty, and that sample has no Post this."""
    ids = [r["id"] for r in rows if "id" in r.keys()]
    out = []
    for name, design in SAMPLE_DESIGNS.items():
        if name not in made:
            continue
        if len(ids) != len(rows) or not ids:
            out.append({"design": design, "file": name, "photos": [], "hero": None})
            continue
        hero = ids[_hero_index(design, len(ids))]
        out.append({"design": design, "file": name, "photos": [hero] + [i for i in ids if i != hero], "hero": hero})
    return out


def renders_root() -> Path:
    return config.get_config().data_root / "renders"


def latest_folder() -> Optional[str]:
    """The newest samples folder with its page: the samples the Design card opens now."""
    root = renders_root()
    if not root.is_dir():
        return None
    names = sorted(p.name for p in root.iterdir()
                   if p.name.startswith(FOLDER_PREFIX) and p.is_dir() and (p / "index.html").is_file())
    return names[-1] if names else None


def about(folder: str) -> dict:
    try:
        data = json.loads((renders_root() / folder / "about.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def sample_of(folder: str, design: str) -> Optional[dict]:
    """What the samples record keeps about one sample: its design and the photos it was made from."""
    for s in about(folder).get("samples") or []:
        if isinstance(s, dict) and s.get("design") == design:
            return s
    return None


def stale(conn, folder: str, sample: Optional[dict]) -> Optional[str]:
    """Why this sample can no longer become a draft, in plain words; None when it can. Fail closed: a sample the
    record does not know, or a photo that is not approved now, is refused."""
    latest = latest_folder()
    if not (renders_root() / folder / "about.json").is_file():
        return "these samples are gone from the Mini; open the newest ones from the Design card"
    if latest != folder:
        return "these samples were made again since, on your newest approved photos; open the newest ones from the Design card"
    if not sample or not sample.get("photos"):
        return "this sample does not record which photos it was made from; the next samples will"
    if sample.get("design") == "reel" and music.current(conn) is None:
        return "a reel never goes out silent and no music is added yet (Library page, Music for reels)"
    for pid in sample["photos"]:
        row = db.one(conn, """SELECT p.*, c.shot_type, c.event_kind FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id
                              WHERE p.id=?""", (int(pid),))
        if row is None or row["trashed"]:
            return f"photo {pid} in it is no longer in the library"
        if eligibility.clearance_of(conn, row) != "cleared" or not usable(conn, row):
            return f"photo {pid} in it is no longer approved"
    return None


def live_page(conn, folder: str, msg: str = "") -> Optional[str]:
    """The samples page as it stands now: each sample's Post this, or why it cannot be drafted, and what its last
    press became. None when the folder has no record (the page written at make time is served instead)."""
    record = about(folder)
    if not record:
        return None
    samples = [s for s in record.get("samples") or [] if isinstance(s, dict)]
    if not samples and not msg:
        msg = ("These samples were made before Post this and do not record their photos per sample; the next samples will, "
               "and they are made again by themselves within the hour.")
    state = {}
    for s in samples:
        last = db.one(conn, "SELECT * FROM sample_posts WHERE folder=? AND design=? ORDER BY id DESC LIMIT 1", (folder, s.get("design")))
        state[s.get("design")] = {"stale": stale(conn, folder, s), "last": dict(last) if last else None}
    track = record.get("music")
    return page(folder, record.get("made") or [], record.get("failed") or [], samples, state=state, msg=msg,
                music=music.credit(conn, track) if track else "")


def _post_this(folder: str, sample: Optional[dict], state: Optional[dict]) -> str:
    """The Post this button under one sample, or the plain reason it cannot be drafted, and its last press."""
    if not sample:
        return ""
    st = (state or {}).get(sample["design"]) or {}
    last = st.get("last")
    said = ""
    if last:
        said = {"pending": "Waiting its turn: checked and drafted in a few minutes; your phone gets a ping.",
                "drafting": "Being checked and drafted now; your phone gets a ping.",
                "drafted": f'Drafted as post #{last["queue_id"]}. <a href="/queue/{last["queue_id"]}">Open the draft</a> to approve it.',
                "failed": f"Not drafted: {html.escape(last['error'] or 'no reason recorded')}"}.get(last["status"], "")
        said = f'<p class="{"bad" if last["status"] == "failed" else "said"}">{said}</p>'
    if st.get("stale"):
        return f'<p class="stale">Cannot be posted: {html.escape(st["stale"])}.</p>{said}'
    if not sample.get("photos"):
        return f'<p class="stale">Cannot be posted: this sample does not record which photos it was made from; the next samples will.</p>{said}'
    ids = ",".join(str(int(p)) for p in sample["photos"])
    return (f'<form method="post" action="/library/design/{html.escape(folder)}/post" class="post">'
            f'<input type="hidden" name="design" value="{html.escape(sample["design"])}">'
            f'<input type="hidden" name="photos" value="{ids}">'
            f'<button type="submit">Post this</button></form>{said}')


def page(folder: str, made: list[str], failed: list[str], samples: Optional[list[dict]] = None, *, music: str = "",
         state: Optional[dict] = None, msg: str = "") -> str:
    """One dark page for the phone: the reels first, then the posts, then the carousel in order. A reel plays on a
    tap, with its sound, and the line under it names the track (`music`: "title, artist"; "" for a silent reel).
    Until 2026-10-14 the reels started by themselves, which a browser allows only muted, and Chris asked where the
    music was: it was in every reel. Each sample with the photos it was made from on record has its Post this
    (2026-10-15)."""
    by_file = {s.get("file"): s for s in samples or [] if isinstance(s, dict)}

    def src(name: str) -> str:
        return html.escape(f"/library/design/{folder}/{name}")
    credit = f"Music: {html.escape(music)}" if music else "No music"

    def poster(name: str) -> str:
        cover = f"{name[:-4]}-cover.jpg"
        return f' poster="{src(cover)}"' if cover in made else ""
    vids = "".join(f'<h2>{html.escape(n.replace("-", " ").replace(".mp4", ""))}</h2>'
                   f'<video src="{src(n)}"{poster(n)} controls playsinline loop preload="metadata"></video><p class="music">{credit}</p>'
                   f'{_post_this(folder, by_file.get(n), state)}'
                   for n in made if n.endswith(".mp4"))
    if vids:
        vids = "<p>Tap a reel to play it with sound.</p>" + vids
    posts = "".join(f'<h2>{html.escape(n.replace("-", " ").replace(".jpg", ""))}</h2><img src="{src(n)}" alt="">'
                    f'{_post_this(folder, by_file.get(n), state)}'
                    for n in made if n.endswith("-post.jpg"))
    slides = "".join(f'<img src="{src(n)}" alt="">' for n in sorted(n for n in made if n.startswith("slide-")))
    slides_post = _post_this(folder, by_file.get("slide-01.jpg"), state)
    errs = "".join(f"<p class=bad>{html.escape(f)}</p>" for f in failed)
    note = f'<p class="msg">{html.escape(msg)}</p>' if msg else ""
    waiting = any(((v or {}).get("last") or {}).get("status") in ("pending", "drafting") for v in (state or {}).values())
    refresh = f"<script>setTimeout(function(){{location.replace('/library/design/{html.escape(folder)}/index.html')}}, 20000)</script>" if waiting else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Design samples</title><style>
body{{margin:0;background:#0a0a0b;color:#f3f3f1;font:16px/1.5 -apple-system,Helvetica,Arial,sans-serif;padding:16px}}
h1{{font-size:22px;margin:4px 0}}h2{{font-size:15px;color:#00e1ff;text-transform:uppercase;letter-spacing:.12em;margin:28px 0 8px}}
p{{color:#8c8c93}}.bad{{color:#ff6b6b}}.music{{margin:-2px 0 0;font-size:14px}}img,video{{width:100%;max-width:540px;display:block;border-radius:10px;margin:0 0 10px}}
.strip{{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory}}.strip img{{flex:none;width:86%;max-width:460px;scroll-snap-align:start}}
.post{{margin:0 0 6px}}.post button{{font:600 15px/1 -apple-system,Helvetica,Arial,sans-serif;background:#00e1ff;color:#0a0a0b;border:0;
border-radius:10px;padding:0 20px;min-height:44px;cursor:pointer}}.stale{{color:#ffb454}}.said{{color:#c9c9cf}}.said a{{color:#00e1ff}}
.msg{{color:#f3f3f1;background:#17171a;border-radius:10px;padding:10px 12px}}
</style></head><body><h1>Design samples on your photos</h1>
<p>Made on the Mini from the strongest frames in your library. For review: nothing here is posted by itself. Post this makes a draft
on the same road as the daily post (Claude's final check on every photo, the captions, the art director) and your phone
gets it with Approve. Nothing goes out until you approve it.</p>{note}{errs}
{vids}{posts}<h2>carousel, swipe</h2><div class="strip">{slides}</div>{slides_post}{refresh}</body></html>"""
