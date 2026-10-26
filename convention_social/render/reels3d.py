"""The 3D reels: five styles in real 3D (reels3d/, Remotion + three.js), rendered by Node on this machine.

Chris, 2026-10-23: "There should be 5 different style reels (all very different)", used at random and never the
same one twice in a row, on random, varied photos. The styles: wall, loop, ring, gallery, orbit. A reel is the
post's photos (named by room), the beats they turn on, other approved photos to fill a wall or a grid around them
(wall, loop, ring), and the track. Everything a render needs goes into a public dir beside the mp4 and Remotion is
given that dir; the mp4 is the product and the dir is removed. No Node, no reel: `node_tool()` fails closed with the
reason, and the daily draft falls back to a carousel of the same photos (content.make_renderer).

The cover is a frame of the reel itself (Instagram shows the frame at thumbnailOffset, 2026-10-16): COVER_S says
where, per style, and `stills` cuts the same frame for the dashboard and the art director. Before the art director
looks at them it is told the style and what the style puts on the frame on purpose (`brief`), so Loop's glass is not
"a large dark circular artifact over the faces" (post 33, 2026-10-24) and a real fault in a photo still is one.
"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import signal
import sqlite3
import subprocess
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
GRID_PHOTOS = 28                                              # approved photos around the post's, one per room per shoot
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
            "the oval is the design, not a defect and not an overlay to remove, and the photo under it is the one to "
            "judge.",
    "ring": "on paper white, the photos unspool as square cards into a ring turning around a small EVENT CALIBER; then "
            "the ring opens and the cards cascade past the camera at their full shape to rest on one photo. The square "
            "crop in the ring and the soft shadow behind each card are the design.",
    "gallery": "the photos hang like prints at different depths in a dark room with a glossy floor; on every beat the "
               "camera swoops to the next print and pushes in slowly while it holds. The dark room and the floor's "
               "reflection are the design.",
    "orbit": "thick cards on a tilted ring spin in; on every beat the ring turns the next card to the front and it "
             "slides forward to fill the frame, the others glowing at their edges behind it. The glowing edges are "
             "the design.",
}


def node_tool(name: str) -> str:
    """npx or npm: on the PATH, else Homebrew's (launchd gives the agents a bare PATH)."""
    found = shutil.which(name) or (f"/opt/homebrew/bin/{name}" if Path(f"/opt/homebrew/bin/{name}").exists() else None)
    if not found:
        raise RuntimeError(f"Node is not installed on this machine ({name} not found), so no 3D reel can be made")
    return found


def next_style(last: Optional[str], rng: Optional[random.Random] = None) -> str:
    """A style at random, never the one the last reel had."""
    choices = [s for s in STYLES if s != last]
    return (rng or random.Random()).choice(choices)


def brief(style: str) -> str:
    """What the art director is told before it looks at a reel: what it sees, the style, and what the style puts on
    the frame on purpose (ON_PURPOSE), so it judges the photos themselves."""
    return (f"{2 + len(STILLS_S)} pictures of a fifteen second reel in the {style} style: its cover frame, the first photo "
            f"on a 2:3 card, and {len(STILLS_S)} more frames from later in the reel. In the reel {ON_PURPOSE[style]} A card "
            "cut by the frame's edge is the camera's move, not the crop. Nothing in the render softens or darkens a "
            "featured photo: these frames have no motion blur, no fade and no transition, so a featured photo that reads "
            "soft or dark is soft or dark in the photo itself, and that is a fault, as is a photo that does not belong.")


def cuts_for(n: int) -> list[int]:
    """The beats n photos turn on, in 30ths: the first at 8, the last at 326 (the samples' spacing), evenly between."""
    if n < 2:
        raise ValueError("a reel takes at least two photos")
    return [8 + round(k * (TOTAL - END - 60) / (n - 1)) for k in range(n)]


def _copy_photo(img: Image.Image, to: Path) -> tuple[int, int]:
    im = img.convert("RGB")
    im.thumbnail((TEXTURE_PX, TEXTURE_PX))
    im.save(to, quality=90)
    return im.width, im.height


def props(shots: Sequence[Shot], *, music: Path, grid: Sequence[Path], public: Path) -> dict:
    """The render's props, with every file it names written under `public`."""
    (public / "photos").mkdir(parents=True)
    (public / "fonts").symlink_to(REELS3D / "public" / "fonts")
    photos = []
    for k, sh in enumerate(shots):
        w, h = _copy_photo(sh.photo, public / "photos" / f"p{k}.jpg")
        photos.append({"src": f"photos/p{k}.jpg", "room": sh.room, "line": sh.line, "w": w, "h": h})
    tiles = []
    for k, path in enumerate(grid):
        with Image.open(path) as im:
            w, h = _copy_photo(im, public / "photos" / f"g{k}.jpg")
        tiles.append({"src": f"photos/g{k}.jpg", "w": w, "h": h})
    track = public / f"music{Path(music).suffix.lower()}"
    shutil.copyfile(music, track)
    return {"photos": photos, "cuts": cuts_for(len(shots)), "grid": tiles, "music": track.name}


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


def render(style: str, shots: Sequence[Shot], *, out: Path, audio: Optional[Path], grid: Sequence[Path] = (),
           run: Callable = run_remotion) -> Path:
    """The reel as an mp4 at `out`: 1080 x 1920, 60 fps, 15 s, with its track."""
    if style not in STYLES:
        raise ValueError(f"no reel style {style!r}; one of {', '.join(STYLES)}")
    if audio is None:
        raise ValueError("a reel needs its track")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    public = out.with_name(f"{out.stem}-public")
    shutil.rmtree(public, ignore_errors=True)
    try:
        p = props(shots, music=Path(audio), grid=grid, public=public)
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
    return out


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


def fillers(conn: sqlite3.Connection, *, exclude: Sequence[int] = (), n: int = GRID_PHOTOS) -> list[Path]:
    """Approved photos with a copy on this machine to fill a wall or a grid: the strongest first, one per room per
    shoot (Drive folder), the shoots interleaved so no two neighbours come from one, never the post's own."""
    from ..core import config
    from ..library import eligibility, report
    from . import design_samples
    cache = config.get_config().data_root / "photos"
    by_shoot: dict = {}
    seen = set(exclude)
    for r in report.best(conn, 600, cap=None):
        key = (r["folder_id"], r["shot_type"])
        path = Path(r["local_path"]) if r["local_path"] else cache / f"{r['drive_id']}.img"
        if (r["id"] in seen or key in seen or not path.is_file()
                or eligibility.clearance_of(conn, r) != "cleared" or not design_samples.usable(conn, r)):
            continue
        seen.add(key)
        by_shoot.setdefault(r["folder_id"], []).append(path)
    picked: list[Path] = []
    while any(by_shoot.values()) and len(picked) < n:
        for queue in by_shoot.values():
            if queue and len(picked) < n:
                picked.append(queue.pop(0))
    return picked
