"""Keeps the Mini's disk small. Chris, 2026-10-11: "The mini can't hold all these high res images".

Where pictures live:
  Google Drive          every original, read only; nothing here ever writes there
  DATA_ROOT/thumbs      400 px previews of the photos the dashboard has shown (fetched again on demand)
  DATA_ROOT/photos      a copy of each photo picked for a post, the site or a draft, no more than MAX_EDGE on its long
                        side (2026-10-15: Chris saw 31 MB originals; "make sure nothing is being stored that large on the
                        mini - it cant handle the memory"); the Drive download is shrunk before anything keeps or opens it
  DATA_ROOT/renders     the rendered posts and reels; renders/clean the metadata-free copy of a raw photo
  the company's bucket  only the files of posts that go out, uploaded by the publisher for Buffer

The nightly sweep (run by the backup agent) deletes, inside DATA_ROOT only:
  - any photo copy still larger than MAX_EDGE (kept before 2026-10-15) is shrunk in place, then
  - a photo copy or clean copy once no open post (draft, approved, would_publish, scheduled)
    uses its photo and it is older than KEEP_DAYS; Drive still has the original
  - the oldest previews once all of them pass THUMBS_CAP_MB
  - a day's rendered posts older than RENDERS_KEEP_DAYS that no open post uses, and every design
    sample set but the newest DESIGN_SETS_KEPT
Nothing else is touched: not the database, the backups, the music, the reports or the logs.
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from .core import config, db

KEEP_DAYS = 7
THUMBS_CAP_MB = 1500
RENDERS_KEEP_DAYS = 90
DESIGN_SETS_KEPT = 3
OPEN = ("draft", "approved", "would_publish", "scheduled")
DESIGN_PREFIX = "design-"
MAX_EDGE = 3000          # pixels on a kept photo's long side: a post is 1080 wide, a reel 1080 by 1920, the site's largest 1600
KEPT_QUALITY = 90


def _register_heif() -> None:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def small_copy(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """A photo at no more than `max_edge` on its long side, as a fresh JPEG with its orientation applied to the pixels:
    what the Mini keeps and opens instead of a Drive original (a 31 MB original is over 100 MB in memory once opened).
    A JPEG is decoded at a reduced scale (draft), so the full original never sits whole in memory. A picture already
    small enough comes back as it is; bytes that are not a picture come back as they are, for the caller to refuse."""
    _register_heif()
    try:
        im = Image.open(io.BytesIO(data))
        if max(im.size) <= max_edge:
            return data
        if im.format == "JPEG":
            im.draft("RGB", (max_edge, max_edge))       # decode at 1/2, 1/4 or 1/8 scale, never below max_edge
        im.load()
    except Exception:  # noqa: BLE001  not a picture, or a format Pillow cannot read: unchanged
        return data
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((max_edge, max_edge), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=KEPT_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def shrink_file(path: Path, max_edge: int = MAX_EDGE) -> int:
    """Shrink one kept photo in place when it is larger than `max_edge`; the bytes freed (0 when nothing changed)."""
    before = path.read_bytes()
    after = small_copy(before, max_edge)
    if after is before or len(after) >= len(before):
        return 0
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(after)
    tmp.replace(path)
    return len(before) - len(after)


def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.resolve()) and path.resolve() != folder.resolve()
    except OSError:
        return False


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def open_uses(conn: sqlite3.Connection) -> tuple[set[int], set[str]]:
    """(photo ids, rendered file paths) that an open post still needs."""
    marks = ",".join("?" for _ in OPEN)
    photos, files = set(), set()
    for r in db.rows(conn, f"SELECT photo_ids, render_paths FROM content_queue WHERE status IN ({marks})", OPEN):
        try:
            photos.update(int(x) for x in json.loads(r["photo_ids"] or "[]"))
            for paths in (json.loads(r["render_paths"] or "{}") or {}).values():
                files.update(str(Path(p).resolve()) for p in paths if isinstance(p, str))
        except (TypeError, ValueError):
            continue
    return photos, files


def sweep(conn: sqlite3.Connection, *, now: Optional[float] = None, keep_days: int = KEEP_DAYS,
          thumbs_cap_mb: int = THUMBS_CAP_MB, renders_keep_days: int = RENDERS_KEEP_DAYS) -> dict:
    root = config.get_config().data_root
    now = now or time.time()
    in_use, in_use_files = open_uses(conn)
    freed = {"originals": 0, "previews": 0, "renders": 0, "shrunk": 0}
    old = now - keep_days * 86400

    # every kept photo larger than MAX_EDGE (copies kept before 2026-10-15, phone photos included) is made small first
    for f in [*(root / "photos").glob("*.img"), *(root / "renders" / "clean").glob("photo-*.jpg"), *(root / "phone").glob("*.jpg")]:
        if _inside(f, root):
            try:
                freed["shrunk"] += shrink_file(f)
            except OSError:
                continue

    # full-size originals (photos/<drive id>.img) and clean copies (renders/clean/photo-<id>.jpg)
    def photo_of(drive_id: str) -> Optional[int]:
        row = db.one(conn, "SELECT id FROM photos WHERE drive_id=?", (drive_id,))
        return row["id"] if row else None
    candidates = [(f, photo_of(f.stem)) for f in (root / "photos").glob("*.img")]
    candidates += [(f, int(f.stem.split("-", 1)[1]) if f.stem.split("-", 1)[1].isdigit() else None)
                   for f in (root / "renders" / "clean").glob("photo-*.jpg")]
    for f, pid in candidates:
        if pid in in_use or f.stat().st_mtime > old or not _inside(f, root):
            continue
        freed["originals"] += f.stat().st_size
        f.unlink()
        conn.execute("UPDATE photos SET local_path=NULL WHERE local_path=?", (str(f),))

    # previews, oldest first, once they pass the cap
    thumbs = sorted((root / "thumbs").glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    total, cap = sum(p.stat().st_size for p in thumbs), thumbs_cap_mb * 1024 * 1024
    if total > cap:
        for p in thumbs:
            if total <= cap * 0.8:
                break
            size = p.stat().st_size
            p.unlink()
            total -= size
            freed["previews"] += size

    # rendered posts by day, and design sample sets
    posts = root / "renders" / "posts"
    for day in sorted(posts.glob("*")) if posts.is_dir() else []:
        if not day.is_dir() or day.stat().st_mtime > now - renders_keep_days * 86400 or not _inside(day, posts):
            continue
        if any(str(p.resolve()) in in_use_files for p in day.rglob("*") if p.is_file()):
            continue
        freed["renders"] += _size(day)
        shutil.rmtree(day)
    sets = sorted(p for p in (root / "renders").glob(f"{DESIGN_PREFIX}*") if p.is_dir())
    for d in sets[:-DESIGN_SETS_KEPT] if len(sets) > DESIGN_SETS_KEPT else []:
        if _inside(d, root / "renders"):
            freed["renders"] += _size(d)
            shutil.rmtree(d)

    usage = shutil.disk_usage(root)
    return {"freed_mb": {k: round(v / 1048576, 1) for k, v in freed.items()},
            "data_mb": round(_size(root) / 1048576, 1), "free_gb": round(usage.free / 1073741824, 1)}


def summary(result: dict) -> str:
    f = result["freed_mb"]
    return (f"disk: freed {f['originals']} MB of photo copies, {f['previews']} MB of previews, {f['renders']} MB of renders, "
            f"shrank kept photos by {f.get('shrunk', 0)} MB; "
            f"data folder {result['data_mb']} MB, {result['free_gb']} GB free")
