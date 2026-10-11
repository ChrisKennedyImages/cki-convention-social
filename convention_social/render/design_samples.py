"""Design samples on Chris's own photos, made on the Mini and shown on the dashboard's Library page.

Chris, 2026-10-11: "these are all original photos being used NO AI at all". The cloud session that
draws the designs cannot open his Drive, so the Mini renders every motion design (render/motion.py)
on the strongest frames of his library and the dashboard shows them.

For review only, like the contact sheets: nothing here is posted, and nothing is written to Drive
(the photos are read through Drive's own previews). A frame is used only when the sort found no one
who may be a minor and no readable personal detail, and when Chris has not blocked it, excluded its
folder, or put it, its folder or a person in it on the do-not-use list. Cleared frames come first.
"""
from __future__ import annotations

import html
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from ..core import config, db
from ..library import eligibility, report
from .. import music
from . import motion

ROOMS = {
    "stage_panel": ("MAIN STAGE", "Keynotes, panels and the full room."),
    "backstage": ("BACKSTAGE", "Green rooms and the minutes before the doors open."),
    "portrait": ("PORTRAITS", "Speakers, guests and staff, lit properly."),
    "headshot": ("PORTRAITS", "Speakers, guests and staff, lit properly."),
    "cosplay_portrait": ("COSPLAY", "Fan conventions shot like the main event they are."),
    "vendor_hall": ("EXPO FLOOR", "Your vendors and exhibitors get their shots too."),
    "booth": ("EXPO FLOOR", "Your vendors and exhibitors get their shots too."),
    "dinner_reception": ("AFTER DARK", "Dinners, receptions and the after party."),
    "crowd": ("THE CROWD", "The people who make the event, in the moment."),
    "candid": ("THE CROWD", "The people who make the event, in the moment."),
    "group": ("THE CROWD", "The people who make the event, in the moment."),
}
OTHER = ("ON THE FLOOR", "Every room of the event, covered.")
FOLDER_PREFIX = "design-"


def usable(conn, row) -> bool:
    photo = db.one(conn, "SELECT * FROM photos WHERE id=?", (row["id"],))
    if photo is None or photo["trashed"]:
        return False
    if eligibility.clearance_of(conn, photo) in ("blocked", "excluded"):
        return False
    if eligibility.blocked_by_list(conn, photo):
        return False
    return not any(c["consent"] == "no" for c in eligibility.credits_for(conn, photo))


def pick(conn, n: int = 6) -> list:
    """Up to n frames, one per room first so the samples show the range, cleared frames first."""
    rows = [r for r in report.best(conn, 60) if usable(conn, r)]
    rows.sort(key=lambda r: 0 if eligibility.clearance_of(conn, r) == "cleared" else 1)
    picked, rooms = [], set()
    for r in rows:
        room = ROOMS.get(r["shot_type"] or "", OTHER)[0]
        if room not in rooms:
            picked.append(r)
            rooms.add(room)
        if len(picked) >= n:
            return picked
    for r in rows:
        if r not in picked:
            picked.append(r)
        if len(picked) >= n:
            break
    return picked


def make(conn, fetch: Callable[[str], bytes], *, out_root: Optional[Path] = None, n: int = 6,
         reels: bool = True, log: Callable[[str], None] = print) -> Path:
    rows = pick(conn, n)
    if len(rows) < 3:
        raise RuntimeError("fewer than 3 usable photos in the library yet: run the scanner first")
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
                      ("spotlight-post.jpg", lambda p: motion.spotlight_post(shots, copy, out=p, index=min(2, len(shots) - 1))),
                      ("facematch-post.jpg", lambda p: motion.facematch_post(shots, copy, out=p))):
        job(out / name)
        made.append(name)
    made += [p.name for p in motion.carousel(shots, copy, out_dir=out)]
    track = music.current(conn)
    if reels:
        if track is None:
            failed.append("the reels are silent: no music added yet (Library page, Music for reels)")
        for name, job in (("rooms-reel.mp4", motion.rooms_reel), ("facematch-reel.mp4", motion.facematch_reel)):
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
