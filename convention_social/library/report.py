"""The inventory report Chris looks at, and the contact sheet of the best frames.

write_report() produces DATA_ROOT/renders/library-report-<date>.html:
totals (folders, images, RAW skipped, checked so far), convention photos by
event and year, and the folders that look like event work with their
clearance state. write_contact_sheet() lays the best N convention frames on
one JPEG with a label under each (event, year, shot type, folder). Both are
for Chris only and are never published. Possible minors and photos with
readable personal details are left off the sheet.
"""
from __future__ import annotations

import html
import io
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageOps

from ..core import config, db, settings
from ..render import fonts

PER_EVENT_CAP = 4


def _year(row) -> str:
    for v in (row["taken_at"], row["modified_time"]):
        if v and len(v) >= 4 and v[:4].isdigit():
            return v[:4]
    return "unknown"


def convention_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.rows(conn, """
        SELECT p.*, c.method, c.is_convention, c.convention_name, c.event_kind, c.shot_type, c.quality,
               c.people_count, c.possible_minor, c.personal_details, c.summary, f.path AS folder_path, f.clearance AS folder_clearance
        FROM photos p JOIN classifications c ON c.photo_id = p.id LEFT JOIN drive_folders f ON f.drive_id = p.folder_id
        WHERE p.trashed = 0 AND c.is_convention = 1""")


def summary(conn: sqlite3.Connection) -> dict:
    rows = convention_rows(conn)
    by_event: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_event[r["convention_name"] or "(event not named)"][_year(r)] += 1
    stats = json.loads(settings.get(conn, "drive.inventory_stats") or "{}")
    total = db.one(conn, "SELECT COUNT(*) n FROM photos WHERE trashed=0")["n"]
    vision = db.one(conn, "SELECT COUNT(*) n FROM classifications WHERE method IN ('vision','ollama')")["n"]
    vision_yes = db.one(conn, "SELECT COUNT(*) n FROM classifications WHERE method IN ('vision','ollama') AND is_convention=1")["n"]
    minors = db.one(conn, "SELECT COUNT(*) n FROM classifications WHERE possible_minor=1")["n"]
    buildings = db.rows(conn, "SELECT p.taken_at, p.modified_time, c.view FROM photos p JOIN classifications c ON c.photo_id=p.id "
                              "WHERE p.trashed=0 AND c.subject='architecture'")
    by_year_b: Counter = Counter(_year(b) for b in buildings)
    return {"total_images": total, "convention_photos": len(rows), "vision_checked": vision,
            "vision_convention": vision_yes, "possible_minors": minors,
            "skipped_raw": stats.get("skipped_raw", 0), "folders": stats.get("folders", 0),
            "building_photos": len(buildings), "buildings_by_year": dict(sorted(by_year_b.items())),
            "building_exteriors": sum(1 for b in buildings if b["view"] == "exterior"),
            "inventory_at": settings.get(conn, "drive.inventory_at") or "never",
            "by_event": {k: dict(sorted(v.items())) for k, v in sorted(by_event.items(), key=lambda kv: -sum(kv[1].values()))}}


def best(conn: sqlite3.Connection, n: int = 30) -> list[sqlite3.Row]:
    """The strongest convention frames, at most PER_EVENT_CAP per event, never a possible minor."""
    rows = [r for r in convention_rows(conn)
            if r["method"] in ("vision", "ollama") and r["possible_minor"] == 0 and (r["personal_details"] or "[]") == "[]"
            and r["thumbnail_link"]]
    rows.sort(key=lambda r: (-(r["quality"] or 0), -(min(r["people_count"] or 0, 3)), -(r["width"] or 0)))
    picked, per = [], Counter()
    for r in rows:
        key = r["convention_name"] or r["folder_id"]
        if per[key] >= PER_EVENT_CAP:
            continue
        per[key] += 1
        picked.append(r)
        if len(picked) >= n:
            break
    return picked


def write_contact_sheet(conn: sqlite3.Connection, fetch_thumb: Callable[[str], bytes], *, n: int = 30,
                        out: Optional[Path] = None, cols: int = 5) -> Path:
    picks = best(conn, n)
    cell_w, cell_h, label_h, pad = 420, 420, 74, 18
    rows_n = max(1, (len(picks) + cols - 1) // cols)
    sheet = Image.new("RGB", (pad + cols * (cell_w + pad), 120 + rows_n * (cell_h + label_h + pad)), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 34), f"{config.get_config().brand_name}  library contact sheet, best {len(picks)} convention frames",
           font=fonts.font("display", 34), fill=(240, 240, 240))
    d.text((pad, 80), f"made {datetime.now():%Y-%m-%d %H:%M}. For review only, nothing here is cleared or posted.",
           font=fonts.font("body", 20), fill=(160, 160, 165))
    small, tiny = fonts.font("body_medium", 18), fonts.font("body", 15)
    for i, r in enumerate(picks):
        x = pad + (i % cols) * (cell_w + pad)
        y = 120 + (i // cols) * (cell_h + label_h + pad)
        try:
            with Image.open(io.BytesIO(fetch_thumb(r["drive_id"]))) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im = ImageOps.contain(im, (cell_w, cell_h))
                sheet.paste(im, (x + (cell_w - im.width) // 2, y + (cell_h - im.height) // 2))
        except Exception:  # noqa: BLE001 — a missing thumbnail leaves an empty cell, not a crash
            d.rectangle((x, y, x + cell_w, y + cell_h), outline=(80, 80, 80))
        name = (r["convention_name"] or "event not named")[:36]
        d.text((x, y + cell_h + 8), f"{name}  {_year(r)}", font=small, fill=(235, 235, 235))
        d.text((x, y + cell_h + 34), f"{(r['shot_type'] or '').replace('_', ' ')}  q{r['quality'] or '?'}  "
               f"{(r['folder_path'] or '')[-40:]}", font=tiny, fill=(150, 150, 155))
    out = out or config.get_config().data_root / "renders" / f"contact-sheet-{datetime.now():%Y%m%d}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=88)
    return out


def write_report(conn: sqlite3.Connection, *, out: Optional[Path] = None, sheet: Optional[Path] = None) -> Path:
    s = summary(conn)
    folders = db.rows(conn, """
        SELECT f.path, f.name, f.clearance, f.image_count,
               SUM(CASE WHEN c.is_convention=1 THEN 1 ELSE 0 END) AS conv
        FROM drive_folders f JOIN photos p ON p.folder_id=f.drive_id AND p.trashed=0
        JOIN classifications c ON c.photo_id=p.id
        GROUP BY f.drive_id HAVING conv > 0 ORDER BY conv DESC""")
    e = html.escape
    years = sorted({y for v in s["by_event"].values() for y in v})
    head = "".join(f"<th>{e(y)}</th>" for y in years)
    body = "".join(f"<tr><td>{e(ev)}</td>" + "".join(f"<td>{v.get(y, '')}</td>" for y in years) +
                   f"<td><b>{sum(v.values())}</b></td></tr>" for ev, v in s["by_event"].items())
    frows = "".join(f"<tr><td>{e(f['path'] or f['name'])}</td><td>{f['conv']}</td><td>{f['image_count']}</td>"
                    f"<td>{e(f['clearance'].replace('_', ' '))}</td></tr>" for f in folders)
    sheet_html = f'<p><img src="{e(sheet.name)}" style="max-width:100%"></p>' if sheet else ""
    doc = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Library report</title>
<style>body{{font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;margin:24px;color:#1c1c1e}}
table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left}}
th{{background:#f4f4f5}}.big{{font-size:28px;font-weight:700}}</style>
<h1>{e(config.get_config().brand_name)} photo library</h1>
<p>Scanned {e(s['inventory_at'])}. Read only. Nothing was changed in Drive.</p>
<p class="big">{s['convention_photos']} convention photos found</p>
<ul><li>{s['total_images']} photos in Drive that can be posted (JPEG, PNG, HEIC and the like)</li>
<li>{s['skipped_raw']} RAW camera files skipped</li>
<li>{s['vision_checked']} looked at closely so far, {s['vision_convention']} of them convention work</li>
<li>{s['possible_minors']} set aside because someone may be under 18</li></ul>
<p class="big">{s['building_photos']} building photos found</p>
<p>{s['building_exteriors']} exteriors. By year: {e(', '.join(f'{y}: {n}' for y, n in s['buildings_by_year'].items()) or 'none yet')}</p>
<h2>Event photos by event and year</h2><table><tr><th>Event</th>{head}<th>Total</th></tr>{body}</table>
<h2>Folders with convention work</h2><p>Nothing is used until you clear a folder on the dashboard.</p>
<table><tr><th>Folder</th><th>Convention photos</th><th>All photos</th><th>Cleared?</th></tr>{frows}</table>
{sheet_html}"""
    out = out or config.get_config().data_root / "renders" / f"library-report-{datetime.now():%Y%m%d}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
