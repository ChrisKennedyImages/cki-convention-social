"""The 3D reels: five styles in real 3D (reels3d/, Remotion + three.js), rendered by Node on this machine.

Chris, 2026-10-23: "There should be 5 different style reels (all very different)", used at random and never the
same one twice in a row, on random, varied photos. The styles: wall, loop, ring, gallery, orbit. A reel is the
post's photos (named by room), the beats they turn on, more of his approved photos for the style's other slots
(fillers: the wall's tiles, the loop's grid, the ring's cards), and the track. Everything a render needs goes into a
public dir beside the mp4 and Remotion is given that dir; the mp4 is the product and the dir is removed. No Node, no
reel: `node_tool()` fails closed with the reason, and the daily draft falls back to a carousel of the same photos
(content.make_renderer).

No picture twice in a reel (Chris, 2026-11-08, night): every picture a style shows is a slot of its own, and a style
takes exactly as many fillers as it shows (`fillers`): the wall a tile each that comes into the frame, the ring a card
each, the loop's grid a card each in the camera's reach (as many as the photos' shapes make), gallery and orbit none.
The card check proves it on a render (render/reel_check.py, `ccs reel-check STYLE`).

The cover is a frame of the reel itself (Instagram shows the frame at thumbnailOffset, 2026-10-16): COVER_S says
where, per style, and `stills` cuts the same frame for the dashboard and the art director. Before the art director
looks at them it is told the style and what the style puts on the frame on purpose (`brief`), so Loop's glass is not
"a large dark circular artifact over the faces" (post 33, 2026-10-24) and a real fault in a photo still is one.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import signal
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image

from ..core.config import REPO_ROOT
from .meta import ImageMeta, save_jpeg
from .motion import Shot
from .reel import ffmpeg_path

STYLES = ("wall", "loop", "ring", "gallery", "orbit")
COMPOSITION = {s: s.capitalize() for s in STYLES}            # the Remotion composition ids (reels3d/src/Root.tsx)
REELS3D = REPO_ROOT / "reels3d"
TOTAL, END = 450, 72                                          # the reel's length and its close, in 30ths (lib.tsx)
# the cover frame, in seconds: the first photo full and still, before the loop's glass reaches it; the ring's hero
COVER_S = {"wall": 1.6, "loop": 1.2, "ring": 12.6, "gallery": 1.6, "orbit": 1.6}
COVER_MS = {s: int(round(COVER_S[s] * 1000)) for s in STYLES}
STILLS_S = (6.0, 10.5)                                        # with the cover: what the art director looks at
TEXTURE_PX = 1400                                             # a photo's long edge in the render
RENDER_TIMEOUT = 20 * 60
ASSET_WAIT_MS = 120_000                                      # Remotion's wait for fonts and textures (default 30 s): thirty photos
#                                                              on a busy Mini took longer on the first render (2026-10-24)
# Every picture the wall and the ring show: the post's photos, then a filler for each other tile in the frame and each
# other card on the ring (reels3d/src/Wall.tsx and Ring.tsx PICTURES). The loop's grid lays as many as its reach and the
# photos' shapes make (loop-fillers.mjs), at most LOOP_OFFER. Orbit's spin turns its cards past the front before their
# beats, each pass a filler of its own (Orbit.tsx plan): as many as the spin makes for that many cards, the same whatever
# the photos' shapes (60 mixes of shapes for each count, 2026-11-09); the style counts them itself and refuses props of
# another count. Gallery shows only the post's photos, its prints dark but on their own pass.
PICTURES = {"wall": 63, "ring": 30}
LOOP_OFFER = 40
ORBIT_FLASHES = {4: 6, 5: 8, 6: 9}
# What each style puts on the frame on purpose, for the art director: it judges the photos, not the design. Post 33
# (2026-10-24, a Loop reel) was turned back for "a large dark circular artifact over the faces": the loop's own glass,
# which Chris approved as the style (2026-10-23), and the turn-back cost the designed lane one of its retries.
ON_PURPOSE = {
    "wall": "a tilted wall of the photographer's other photos drifts past the camera; on every beat one of the post's "
            "photos lifts out of the wall, turns to face the camera at its full shape, holds, and settles back. The "
            "wall's other tiles are small, at an angle and cropped to the wall's tile shape on purpose.",
    "loop": "a grid of the photographer's photos in level rows; the camera stops over the post's photos one at a time, "
            "the held photo at full brightness while the rest of the grid dims around it, its room named under it; the "
            "grid is bright again while the camera travels. A card-sized oval of liquid glass glides onto the held "
            "photo, magnifies what is under it, faces included, and travels on to the next card ahead of the camera: "
            "the oval is the design, not a defect and not an overlay to remove.",
    "ring": "on paper white, the photos unspool as square cards into a ring turning around a small EVENT CALIBER; then "
            "the ring opens and the cards cascade past the camera at their full shape to rest on one photo. The square "
            "crop in the ring and the soft shadow behind each card are the design.",
    "gallery": "the photos hang like prints at different depths in a dark room with a glossy floor; on every beat the "
               "camera swoops to the next print and pushes in slowly while it holds. A print hangs dark, its frame with no "
               "picture, until the camera reaches it and once it has passed, on purpose: no picture is shown twice. The "
               "dark room, the dark prints and the floor's reflection are the design.",
    "orbit": "thick cards on a tilted ring spin in; on every beat the ring turns the next card to the front and it "
             "slides forward to fill the frame, the others glowing at their edges behind it. A card the ring brings "
             "round again after its own beat shows a dark face, on purpose: no picture is shown twice. The glowing "
             "edges and the dark faces are the design.",
}


def node_tool(name: str) -> str:
    """npx or npm: on the PATH, else Homebrew's (launchd gives the agents a bare PATH)."""
    found = shutil.which(name) or (f"/opt/homebrew/bin/{name}" if Path(f"/opt/homebrew/bin/{name}").exists() else None)
    if not found:
        raise RuntimeError(f"Node is not installed on this machine ({name} not found), so no 3D reel can be made")
    return found


def brief(style: str) -> str:
    """What the art director is told before it looks at a reel: what it sees, the style, and what the style puts on
    the frame on purpose (ON_PURPOSE), so it judges the photos themselves."""
    return (f"{2 + len(STILLS_S)} pictures of a fifteen second reel in the {style} style: its cover frame, the first photo "
            f"on a 2:3 card, and {len(STILLS_S)} more frames from later in the reel. In the reel {ON_PURPOSE[style]} A card "
            "cut by the frame's edge is the camera's move, not the crop. Nothing in the render softens or darkens a "
            "featured photo: these frames have no motion blur, no fade and no transition, and every photo is shown as Chris "
            "shot and approved it, never a fault in itself.")


def cuts_for(n: int) -> list[int]:
    """The beats n photos turn on, in 30ths: the first at 8, the last at 326 (the samples' spacing), evenly between."""
    if n < 2:
        raise ValueError("a reel takes at least two photos")
    return [8 + round(k * (TOTAL - END - 60) / (n - 1)) for k in range(n)]


def copy_photo(img: Image.Image, to: Path) -> tuple[int, int]:
    """The photo as a JPEG for a render, its long edge TEXTURE_PX; (width, height) as written."""
    im = img.convert("RGB")
    im.thumbnail((TEXTURE_PX, TEXTURE_PX))
    im.save(to, quality=90)
    return im.width, im.height


@dataclass(frozen=True)
class Filler:
    """One of his approved photos for a slot that is not one of the post's own: its id, for the rotation's record, and its
    copy here. The 3D styles and the ten looks (render/reel_looks.py) draw them alike."""
    id: int
    path: Path
    label: Optional[str] = None      # its sorted label (a key of house_brief.WORDS) when that label may be printed over it


def props(shots: Sequence[Shot], *, music: Path, fillers: Sequence[Path], public: Path) -> dict:
    """The render's props, with every file it names written under `public`."""
    (public / "photos").mkdir(parents=True)
    (public / "fonts").symlink_to(REELS3D / "public" / "fonts")
    photos = []
    for k, sh in enumerate(shots):
        w, h = copy_photo(sh.photo, public / "photos" / f"p{k}.jpg")
        photos.append({"src": f"photos/p{k}.jpg", "room": sh.room, "line": sh.line, "w": w, "h": h})
    tiles = []
    for k, path in enumerate(fillers):
        with Image.open(path) as im:
            w, h = copy_photo(im, public / "photos" / f"f{k}.jpg")
        tiles.append({"src": f"photos/f{k}.jpg", "w": w, "h": h})
    track = public / f"music{Path(music).suffix.lower()}"
    shutil.copyfile(music, track)
    return {"photos": photos, "cuts": cuts_for(len(shots)), "fillers": tiles, "music": track.name}


def fillers_wanted(style: str, photos: int) -> Optional[int]:
    """How many fillers a reel in `style` of that many of the post's photos shows; None for the loop, whose grid lays as
    many as the photos' shapes make (loop_fillers)."""
    if style == "loop":
        return None
    if style == "orbit":
        if photos not in ORBIT_FLASHES:
            raise ValueError(f"an orbit reel takes {min(ORBIT_FLASHES)} to {max(ORBIT_FLASHES)} photos; {photos} came")
        return ORBIT_FLASHES[photos]
    return PICTURES[style] - photos if style in PICTURES else 0


def loop_fillers(props_list: Sequence[dict]) -> list[Optional[int]]:
    """Loop: how many of its fillers the grid lays, for each of these props (None: more than they hold), from the layout
    the style draws with (reels3d/loop-fillers.mjs on src/loopGrid.ts, by Node)."""
    r = subprocess.run([node_tool("node"), "--experimental-strip-types", "--no-warnings", str(REELS3D / "loop-fillers.mjs")],
                       input=json.dumps(list(props_list)), capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"the loop's grid could not be laid out: {(r.stderr or r.stdout).strip()[-300:]}")
    return json.loads(r.stdout)


def run_remotion(cmd: Sequence[str], *, cwd: str, timeout: float) -> subprocess.CompletedProcess:
    """Remotion in a process group of its own, so a render past its time is stopped together with the browser it
    started (2026-10-24 audit: subprocess.run's kill reached npx alone and could leave Chrome rendering on)."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)          # the group's id is the leader's pid (start_new_session)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise RuntimeError(f"remotion ran past {int(timeout)} s and was stopped, with its browser") from None
    return subprocess.CompletedProcess(list(cmd), proc.returncode, out, err)


@dataclass(frozen=True)
class Reel:
    """A rendered 3D reel: its mp4, and the fillers it showed (to be recorded on the wall: record_wall)."""
    video: Path
    fillers: tuple[Filler, ...] = ()


def staged(style: str, shots: Sequence[Shot], *, fillers: Sequence[Filler], music: Path, public: Path,
           laid: Callable = loop_fillers) -> tuple[dict, list[Filler]]:
    """A render's props, every file they name written under `public`, and the fillers the reel shows: exactly the ones
    the style shows, the loop's grid keeping the ones it lays on the photos as written (`laid`, its seam). Short of a
    picture, refused: a reel is never made by showing one twice."""
    wanted = fillers_wanted(style, len(shots))
    if wanted is not None and len(fillers) != wanted:
        raise ValueError(f"a {style} reel of {len(shots)} photos shows {wanted} fillers; {len(fillers)} came "
                         "(more approved photos with a copy here are needed)")
    p = props(shots, music=music, fillers=[f.path for f in fillers], public=public)
    if wanted is not None:
        return p, list(fillers)
    [kept] = laid([p])
    if kept is None:
        raise ValueError(f"the loop's grid for these photos lays more cards than {len(fillers)} fillers "
                         "(more approved photos with a copy here are needed)")
    for gone in p["fillers"][kept:]:
        (public / gone["src"]).unlink()
    p["fillers"] = p["fillers"][:kept]
    return p, list(fillers[:kept])


def render(style: str, shots: Sequence[Shot], *, out: Path, audio: Optional[Path], fillers: Sequence[Filler] = (),
           run: Callable = run_remotion, laid: Callable = loop_fillers) -> Reel:
    """The reel as an mp4 at `out`: 1080 x 1920, 60 fps, 15 s, with its track, and the fillers it showed (`staged`)."""
    if style not in STYLES:
        raise ValueError(f"no reel style {style!r}; one of {', '.join(STYLES)}")
    if audio is None:
        raise ValueError("a reel needs its track")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    public = out.with_name(f"{out.stem}-public")
    shutil.rmtree(public, ignore_errors=True)
    try:
        p, fillers = staged(style, shots, fillers=fillers, music=Path(audio), public=public, laid=laid)
        (public / "props.json").write_text(json.dumps(p))
        cmd = [node_tool("npx"), "remotion", "render", "src/Root.tsx", COMPOSITION[style], str(out),
               f"--props={public / 'props.json'}", f"--public-dir={public}", "--gl=angle", f"--timeout={ASSET_WAIT_MS}", "--log=error"]
        r = run(cmd, cwd=str(REELS3D), timeout=RENDER_TIMEOUT)
        if r.returncode != 0:
            said = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError(f"remotion stopped with code {r.returncode}: {' '.join(said[-3:])[:400]}")
        if not out.is_file():
            raise RuntimeError("remotion finished but left no video")
    finally:
        shutil.rmtree(public, ignore_errors=True)
    return Reel(out, tuple(fillers))


def frame_at(video: Path, seconds: float) -> Image.Image:
    """The reel's frame at `seconds`, cut from the mp4."""
    r = subprocess.run([ffmpeg_path(), "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=120)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"no frame at {seconds} s of {Path(video).name}: {r.stderr.decode(errors='replace')[-300:]}")
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def stills(style: str, video: Path, *, out_dir: Path, meta: Optional[ImageMeta] = None) -> list[Path]:
    """The reel's cover and stills, cut from the reel itself, saved as JPEGs with the company's metadata. The
    cover is first, at the frame Instagram will show (COVER_S)."""
    out_dir = Path(out_dir)
    saved = []
    for s in (COVER_S[style], *STILLS_S):
        saved.append(save_jpeg(frame_at(video, s), out_dir / f"{style}-{int(round(s * 1000)):05d}.jpg", meta, quality=92))
    return saved


def wall_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Every approved photo with a copy on this machine a wall or a look's fillers can draw on, strongest first, one file
    per picture: the photo rows, each with its copy's "path". Drawn from every approved photo: the strongest 600 frames
    of the whole library held 42 approved photos with a copy here (2026-11-09), so the rest of his approved work never
    reached a wall, and the rotation is all of them. The slow part of a pick; a draft that asks for several reads it once."""
    from ..core import config
    from ..library import eligibility, report
    from . import design_samples
    cache = config.get_config().data_root / "photos"
    out = []
    for r in report.best(conn, None, cap=None):
        if r["clearance"] != "cleared":
            continue                                # a photo he has not used is never cleared: passed over before the rest
        path = Path(r["local_path"]) if r["local_path"] else cache / f"{r['drive_id']}.img"
        if path.is_file() and eligibility.clearance_of(conn, r) == "cleared" and design_samples.usable(conn, r):
            out.append({**dict(r), "path": path})
    return out


def wall_picks(conn: sqlite3.Connection, *, exclude: Sequence[int], n: int, rng=None,
               most_portraits: Optional[int] = None, only: Optional[str] = None,
               candidates: Optional[list[dict]] = None) -> list[dict]:
    """Approved photos with a copy on this machine to fill a wall or a grid (`candidates`, wall_candidates when not given):
    in rotation (the least recently shown on any surface first, equals in strength by chance), one per room per shoot
    (Drive folder), the shoots interleaved so no two neighbours come from one, never the post's own (nor a copy of one of
    its pictures, nor a frame of its moments): the photo rows, each with its copy's "path". What a reel shows of them is
    recorded as a use on the "grid" surface (record_wall), so the next reel's wall reaches for other photos: Chris,
    2026-10-26, "it keeps posting the same photos again" — the strongest 28 had stood on every reel's wall.
    `most_portraits`: at most that many portraits (Powers of Ten's mosaic is mostly not portraits, 2026-11-08); `only`:
    that shot type alone (Axis's portraits).
    A moment needs the camera's clock. Where the post holds a photo with none, nothing of its shoot and shot type fills
    (a frame of the same sitting could not be told from another), nor does a photo with none from a shoot and shot type
    the post holds. Nor does a photo another post still to go out holds (storage.OPEN: a draft, approved or scheduled),
    a copy of it or a frame of its moment: that post would show the picture again (#90's tiles held photos of #80, #85
    and #86, 2026-11-09). Nor does a photo labelled a portrait with other than one person in it (house_brief.may_name):
    Axis's walls are its portraits gallery; a pair or a group waits for its own label."""
    from .. import house_brief, storage
    from ..core import db
    from ..library import copies, moments, report
    own = copies.every_copy(conn, exclude)
    # never a frame of the post's own moments on its wall (2026-11-02), nor a copy of its pictures filed elsewhere
    seen = moments.siblings(conn, own)
    marks = ",".join("?" * len(storage.OPEN))
    held = [int(p) for r in db.rows(conn, f"SELECT photo_ids FROM content_queue WHERE status IN ({marks})", storage.OPEN)
            for p in json.loads(r["photo_ids"] or "[]")]
    seen |= moments.siblings(conn, copies.every_copy(conn, held))
    own_keys, untimed_keys = set(), set()
    if own:
        marks = ",".join("?" * len(own))
        for r in db.rows(conn, f"SELECT p.folder_id, p.taken_at, c.shot_type FROM photos p LEFT JOIN classifications c "
                               f"ON c.photo_id = p.id WHERE p.id IN ({marks})", sorted(own)):
            own_keys.add((r["folder_id"], r["shot_type"]))
            if moments.taken(r["taken_at"]) is None:
                untimed_keys.add((r["folder_id"], r["shot_type"]))
    usable = []
    for r in wall_candidates(conn) if candidates is None else candidates:
        key = (r["folder_id"], r["shot_type"])
        if (r["id"] in seen or (only is not None and r["shot_type"] != only) or key in untimed_keys
                or (key in own_keys and moments.taken(r["taken_at"]) is None)
                or (only is not None and not house_brief.may_name(r["shot_type"], r["people_count"]))):
            continue
        usable.append(r)
    by_shoot: dict = {}
    for r in report.rotate(conn, usable, rng=rng, alike=lambda r: -report.strength(r)):
        key = (r["folder_id"], r["shot_type"])
        if key in seen:
            continue
        seen.add(key)
        by_shoot.setdefault(r["folder_id"], []).append(r)
    picked: list[dict] = []
    while any(by_shoot.values()) and len(picked) < n:
        for queue in by_shoot.values():
            if queue and len(picked) < n:
                r = queue.pop(0)
                if any(moments.same_moment(r, p) for p in picked):       # one frame of a moment on the wall (2026-11-02)
                    continue
                if most_portraits is not None and r["shot_type"] == "portrait" and \
                        sum(1 for p in picked if p["shot_type"] == "portrait") >= most_portraits:
                    continue
                picked.append(r)
    return picked


def record_wall(conn: sqlite3.Connection, photo_ids: Sequence[int]) -> None:
    """These approved photos stood on a reel's wall (or filled a look's slots): a use on the "grid" surface, never one
    the post's repeat window counts."""
    from ..library import report
    if photo_ids:
        report.record_use(conn, "grid", list(photo_ids), ref=f"grid:{report.use_stamp()}")


def fillers(conn: sqlite3.Connection, style: str, photos: int, *, exclude: Sequence[int], rng=None) -> list[Filler]:
    """The fillers a reel in `style` of that many of the post's photos (their ids `exclude`) shows, each once (wall_picks:
    in rotation, one per room per shoot, never the post's own nor a picture another open post holds); for the loop,
    LOOP_OFFER, of which its grid keeps the ones it lays (render). Fewer than the style shows when the Mini holds too few:
    the render then refuses the reel. Recorded as shown on the wall's record (record_wall) once the reel is made."""
    wanted = fillers_wanted(style, photos)
    if wanted == 0:
        return []
    picked = wall_picks(conn, exclude=exclude, n=LOOP_OFFER if wanted is None else wanted, rng=rng)
    return [Filler(r["id"], r["path"]) for r in picked]
