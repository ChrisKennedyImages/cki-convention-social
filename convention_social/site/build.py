"""eventcaliber.com, built on the Mini into site/dist and served by the Worker.

`build(conn, photo_source)` writes every page, the stylesheet, the mark and
the photos. Photos on the site are public, so they pass the same gate as a
post: only postable photos (cleared, sorted, Claude's final check passed),
saved fresh from pixels at web size so no EXIF or GPS travels. With
`preview=True` it takes whatever photos it is handed (the stand-ins for Chris's
first look) and stamps every page PREVIEW so it can never be mistaken for live.

Every word on every page passes ai.copy_rules: no price, no dash, no claim of
an official role, a client list or past bookings.
"""
from __future__ import annotations

import html
import io
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps

from .. import offer
from ..ai import copy_rules
from ..core import config, db
from ..library import eligibility
from ..render.brand import DIRECTIONS
from ..render import fonts

DIST = config.REPO_ROOT / "site" / "dist"
WIDTHS = (800, 1600)


@dataclass
class SitePhotos:
    hero: list = field(default_factory=list)       # [(image, alt)]
    coverage: list = field(default_factory=list)
    venues: list = field(default_factory=list)


class SiteCopyRefused(ValueError):
    pass


def pick_photos(conn: sqlite3.Connection, fetch: Callable[[dict], Image.Image]) -> SitePhotos:
    """Postable photos only: event work for the hero and the grid, building work for venues."""
    rows = db.rows(conn, """
        SELECT p.*, c.subject, c.quality, c.shot_type, c.convention_name, c.summary FROM photos p
        JOIN classifications c ON c.photo_id=p.id WHERE p.trashed=0 AND c.subject IN ('event','architecture')
        ORDER BY COALESCE(c.quality,0) DESC, p.width DESC LIMIT 400""")
    ok = [dict(r) for r in rows if eligibility.is_eligible(conn, r["id"])[0]]
    events = [r for r in ok if r["subject"] == "event"]
    venues = [r for r in ok if r["subject"] == "architecture"]
    land = [r for r in events if (r["width"] or 0) > (r["height"] or 0)]
    out = SitePhotos()
    if land:
        out.hero = [(fetch(land[0]), land[0]["summary"] or "Event photography")]
    out.coverage = [(fetch(r), r["summary"] or "Event photography") for r in events[1:7]]
    out.venues = [(fetch(r), r["summary"] or "Venue") for r in venues[:4]]
    return out


def save_web(im: Image.Image, out_dir: Path, stem: str) -> dict:
    """JPEGs at each width, from pixels only (no metadata). Returns {width: filename}."""
    im = ImageOps.exif_transpose(im).convert("RGB")
    made = {}
    for w in WIDTHS:
        copy = im.copy()
        copy.thumbnail((w, w * 2))
        name = f"{stem}-{w}.jpg"
        copy.save(out_dir / name, format="JPEG", quality=82, optimize=True, progressive=True)
        made[w] = name
    return made


def img_tag(files: dict, alt: str, sizes: str, cls: str = "") -> str:
    srcset = ", ".join(f"/assets/{n} {w}w" for w, n in sorted(files.items()))
    return (f'<img class="{cls}" src="/assets/{files[max(files)]}" srcset="{srcset}" sizes="{sizes}" '
            f'alt="{html.escape(alt)}" loading="lazy" decoding="async">')


MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img" aria-label="{name}">
<circle cx="60" cy="60" r="54" fill="none" stroke="#2F5BFF" stroke-width="8"/>
<line x1="94" y1="26" x2="104" y2="16" stroke="#2F5BFF" stroke-width="8" stroke-linecap="round"/>
<text x="60" y="76" text-anchor="middle" font-family="Space Grotesk, Arial, sans-serif" font-weight="700" font-size="46" fill="{fill}">{initials}</text>
</svg>"""


def css(b) -> str:
    ink, paper, accent = ("#%02X%02X%02X" % c for c in (b.ink, b.paper, b.accent))
    return f"""@font-face{{font-family:"Space Grotesk";src:url(/assets/fonts/SpaceGrotesk-Medium.ttf) format("truetype");font-weight:500;font-display:swap}}
@font-face{{font-family:"Space Grotesk";src:url(/assets/fonts/SpaceGrotesk-Bold.ttf) format("truetype");font-weight:700;font-display:swap}}
:root{{--ink:{ink};--paper:{paper};--accent:{accent};--line:rgba(233,236,242,.14);--muted:#A9AFBC}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--ink);color:var(--paper);font:500 18px/1.55 "Space Grotesk",system-ui,-apple-system,Helvetica,Arial,sans-serif}}
a{{color:inherit}}img{{max-width:100%;display:block}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 24px}}
header.top{{position:sticky;top:0;z-index:5;background:rgba(27,29,34,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}}
header.top .wrap{{display:flex;align-items:center;gap:16px;height:68px}}
.brand{{display:flex;align-items:center;gap:12px;text-decoration:none;font-weight:700;font-size:22px;letter-spacing:-.01em;white-space:nowrap}}
.brand svg{{width:38px;height:38px}}
nav.main{{margin-left:auto;display:flex;gap:22px;font-size:16px}}nav.main a{{text-decoration:none;opacity:.85}}nav.main a:hover{{opacity:1}}
.btn{{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;padding:14px 24px;border-radius:999px;border:0;font:inherit;font-weight:700;cursor:pointer}}
.btn.ghost{{background:transparent;border:1.5px solid var(--line)}}
.kicker{{text-transform:uppercase;letter-spacing:.16em;font-size:13px;color:var(--accent);font-weight:700}}
h1,h2,h3{{font-weight:700;letter-spacing:-.02em;line-height:1.05;margin:0}}
h1{{font-size:clamp(40px,6.4vw,84px)}}h2{{font-size:clamp(30px,4vw,52px)}}h3{{font-size:22px}}
.hero{{position:relative;min-height:min(88vh,860px);display:flex;align-items:flex-end;overflow:hidden}}
.hero img.bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.hero:after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(27,29,34,.05) 30%,rgba(27,29,34,.92) 92%)}}
.hero .wrap{{position:relative;z-index:1;padding-bottom:72px}}
.hero p{{max-width:640px;font-size:20px;color:var(--paper);opacity:.9;margin:20px 0 28px}}
.ctas{{display:flex;gap:12px;flex-wrap:wrap}}
section{{padding:96px 0;border-top:1px solid var(--line)}}
.split{{display:grid;grid-template-columns:1fr 1.3fr;gap:56px;align-items:start}}
ul.cover{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:4px 28px}}
ul.cover li{{padding:12px 0 12px 22px;border-bottom:1px solid var(--line);position:relative}}
ul.cover li:before{{content:"";position:absolute;left:0;top:22px;width:10px;height:10px;background:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:40px}}
.grid img{{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:4px}}
.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin-top:40px}}
.step{{border-top:2px solid var(--accent);padding-top:18px}}.step .n{{color:var(--accent);font-weight:700}}
.venues{{display:grid;grid-template-columns:1.4fr 1fr;gap:10px;margin-top:40px}}
.venues img{{width:100%;height:100%;object-fit:cover;border-radius:4px;aspect-ratio:3/2}}
.muted{{color:var(--muted)}}
.cta-band{{text-align:center}}.cta-band p{{max-width:620px;margin:16px auto 28px;color:var(--muted)}}
footer{{border-top:1px solid var(--line);padding:40px 0;color:var(--muted);font-size:15px}}
footer .wrap{{display:flex;gap:24px;flex-wrap:wrap;align-items:center}}
form.book{{display:grid;grid-template-columns:1fr 1fr;gap:16px 20px;margin-top:32px}}
form.book .full{{grid-column:1/-1}}
form.book label{{display:block;font-size:14px;color:var(--muted);margin-bottom:6px}}
form.book input,form.book select,form.book textarea{{width:100%;font:inherit;color:var(--paper);background:#23262D;border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
form.book textarea{{min-height:140px}}
.checks{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 20px}}form.book .checks label{{display:flex;gap:10px;align-items:center;color:var(--paper);font-size:16px;margin:0}}
form.book .checks input{{width:auto;flex:none;margin:0}}
.hp{{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}}
.err{{background:#3a1d22;border:1px solid #6b2b35;padding:12px 16px;border-radius:10px;margin-top:20px}}
.cal{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:28px;margin-top:36px}}
.month h3{{margin-bottom:10px;font-size:18px}}.days{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;font-size:14px;text-align:center}}
.days span{{padding:8px 0;border-radius:6px;background:#23262D}}.days span.h{{background:none;color:var(--muted);font-size:12px}}
.days span.x{{background:none}}.days span.b{{background:var(--accent);color:#fff;text-decoration:line-through}}
.preview{{position:fixed;bottom:14px;right:14px;z-index:9;background:#FFD54A;color:#1B1D22;font-weight:700;padding:8px 14px;border-radius:999px;font-size:14px}}
@media (max-width:820px){{.split,.venues{{grid-template-columns:1fr}}.grid{{grid-template-columns:1fr 1fr}}.steps{{grid-template-columns:1fr}}
ul.cover{{grid-template-columns:1fr}}form.book{{grid-template-columns:1fr}}.checks{{grid-template-columns:1fr}}nav.main{{display:none}}
section{{padding:64px 0}}.hero .wrap{{padding-bottom:48px}}
header.top .btn{{padding:10px 16px;font-size:15px;margin-left:auto}}.brand{{font-size:19px}}.brand svg{{width:32px;height:32px}}}}
"""


def page(title: str, body: str, *, preview: bool, description: str, brand: str) -> str:
    cfg = config.get_config()
    mark = MARK_SVG.format(name=html.escape(brand), fill="#E9ECF2", initials="".join(w[0] for w in brand.split()[:2]).upper())
    stamp = '<div class="preview">PREVIEW, not live</div>' if preview else ""
    robots = '<meta name="robots" content="noindex">' if preview else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">{robots}
<link rel="icon" href="/assets/mark.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/site.css">
</head><body>
<header class="top"><div class="wrap"><a class="brand" href="/">{mark}<span>{html.escape(brand.lower())}</span></a>
<nav class="main"><a href="/#coverage">Coverage</a><a href="/#venues">Venues</a><a href="/availability/">Availability</a></nav>
<a class="btn" href="/book/">Request a quote</a></div></header>
{body}
<footer><div class="wrap"><span>{html.escape(brand)}, a brand of {html.escape(cfg.legal_name)}</span>
<a href="/privacy/">Privacy and photo removal</a><a href="mailto:{html.escape(contact_email())}">{html.escape(contact_email())}</a></div></footer>
{stamp}</body></html>"""


def contact_email() -> str:
    cfg = config.get_config()
    return cfg.brand_from_email or f"hello@{cfg.brand_domain}"


def copy_text() -> dict:
    o = offer.load()
    return {
        "title": f"{o['company']}: {o['tagline']}",
        "kicker": o["tagline"],
        "h1": "Every room of your event, covered.",
        "lede": ("Photography for fan conventions, conferences, galas and award dinners. "
                 "Approved images go to your attendees, staff, speakers and presenters while the event is still on."),
        "coverage_h": "From the green room to the last reception.",
        "coverage_p": "Tell us which rooms matter. Coverage is planned around your schedule, and every event is quoted on its own.",
        "steps": [("Tell us about your event", "Dates, venue, the rooms and moments that matter, and who needs images."),
                  ("Get a quote for your dates", "A clear quote for the coverage you need, nothing bundled you did not ask for."),
                  ("Images while it is still on", "Approved images reach your attendees, staff, speakers and presenters during the event.")],
        "venues_h": "The building is part of the story.",
        "venues_p": "Years of architectural work mean the venue gets shot as carefully as the people in it: exteriors, lobbies, halls and ballrooms.",
        "band_h": "Planning an event?",
        "band_p": "Send the dates and the details. A quote comes back for your event, with the coverage you asked for.",
    }


def check_copy(texts) -> None:
    for t in texts:
        r = copy_rules.check(t)
        if not r.ok:
            raise SiteCopyRefused(f"{t[:60]!r}: {r.blocks[0].message}")


def build(conn: Optional[sqlite3.Connection], photos: SitePhotos, *, out: Path = DIST, preview: bool = False) -> Path:
    b = DIRECTIONS["lens"]
    o = offer.load()
    brand = config.get_config().brand_name
    t = copy_text()
    check_copy([v if isinstance(v, str) else " ".join(x for pair in v for x in pair) for v in t.values()] + offer.coverage_labels())
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    (assets / "fonts").mkdir(parents=True)
    for name in ("SpaceGrotesk-Medium.ttf", "SpaceGrotesk-Bold.ttf"):
        src = fonts._find(name)
        if src:
            shutil.copyfile(src, assets / "fonts" / name)
    (assets / "site.css").write_text(css(b))
    (assets / "mark.svg").write_text(MARK_SVG.format(name=html.escape(brand), fill="#1B1D22",
                                                     initials="".join(w[0] for w in brand.split()[:2]).upper()))
    e = html.escape
    hero = ""
    if photos.hero:
        files = save_web(photos.hero[0][0], assets, "hero")
        hero = img_tag(files, photos.hero[0][1], "100vw", "bg").replace('loading="lazy"', 'loading="eager" fetchpriority="high"')
    grid = "".join(img_tag(save_web(im, assets, f"cover-{i}"), alt, "(max-width:820px) 50vw, 33vw") for i, (im, alt) in enumerate(photos.coverage))
    venues = "".join(img_tag(save_web(im, assets, f"venue-{i}"), alt, "(max-width:820px) 100vw, 60vw") for i, (im, alt) in enumerate(photos.venues[:2]))
    cover_list = "".join(f"<li>{e(label)}</li>" for label in offer.coverage_labels())
    steps = "".join(f'<div class="step"><div class="n">0{i}</div><h3>{e(h)}</h3><p class="muted">{e(p)}</p></div>'
                    for i, (h, p) in enumerate(t["steps"], start=1))
    home = f"""<div class="hero">{hero}<div class="wrap"><div class="kicker">{e(t['kicker'])}</div><h1>{e(t['h1'])}</h1>
<p>{e(t['lede'])}</p><div class="ctas"><a class="btn" href="/book/">Request a quote</a><a class="btn ghost" href="/availability/">See availability</a></div></div></div>
<section id="coverage"><div class="wrap"><div class="split"><div><div class="kicker">Coverage</div><h2>{e(t['coverage_h'])}</h2>
<p class="muted">{e(t['coverage_p'])}</p></div><ul class="cover">{cover_list}</ul></div>{f'<div class="grid">{grid}</div>' if grid else ''}</div></section>
<section><div class="wrap"><div class="kicker">How it works</div><h2>Three steps.</h2><div class="steps">{steps}</div></div></section>
{f'<section id="venues"><div class="wrap"><div class="kicker">Venues</div><h2>{e(t["venues_h"])}</h2><p class="muted" style="max-width:640px">{e(t["venues_p"])}</p><div class="venues">{venues}</div></div></section>' if venues else ''}
<section class="cta-band"><div class="wrap"><h2>{e(t['band_h'])}</h2><p>{e(t['band_p'])}</p><a class="btn" href="/book/">Request a quote</a></div></section>"""
    pages = {"index.html": (t["title"], home)}
    checks = "".join(f'<label><input type="checkbox" name="coverage" value="{e(c["key"])}"> {e(c["label"])}</label>' for c in o["coverage"])
    site_key = config.getenv("TURNSTILE_SITE_KEY") or ""
    turnstile = (f'<div class="full"><div class="cf-turnstile" data-sitekey="{e(site_key)}" data-theme="dark"></div></div>'
                 '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>') if site_key else ""
    book = f"""<section style="border-top:0"><div class="wrap" style="max-width:860px"><div class="kicker">Request a quote</div>
<h1 style="font-size:clamp(36px,5vw,60px)">Tell us about your event.</h1>
<p class="muted">Every event is quoted on its own. The more you share, the more exact the quote.</p>
<div id="err"></div>
<form class="book" method="post" action="/api/quote">
<div><label for="name">Your name</label><input id="name" name="name" required maxlength="120" autocomplete="name"></div>
<div><label for="email">Email</label><input id="email" name="email" type="email" required maxlength="200" autocomplete="email"></div>
<div><label for="phone">Phone (optional)</label><input id="phone" name="phone" maxlength="40" autocomplete="tel"></div>
<div><label for="organization">Organization</label><input id="organization" name="organization" maxlength="160" autocomplete="organization"></div>
<div class="full"><label for="event_name">Event name</label><input id="event_name" name="event_name" maxlength="200"></div>
<div><label for="event_kind">Kind of event</label><select id="event_kind" name="event_kind"><option value="fan">Fan convention</option>
<option value="business">Conference or political event</option><option value="other">Gala, reception or something else</option></select></div>
<div><label for="attendance">Expected attendance</label><input id="attendance" name="attendance" maxlength="40"></div>
<div><label for="start_date">First day</label><input id="start_date" name="start_date" type="date"></div>
<div><label for="end_date">Last day</label><input id="end_date" name="end_date" type="date"></div>
<div><label for="venue">Venue</label><input id="venue" name="venue" maxlength="200"></div>
<div><label for="city">City</label><input id="city" name="city" maxlength="120"></div>
<div class="full"><label>What should be covered</label><div class="checks">{checks}</div></div>
<div class="full"><label for="message">Anything else</label><textarea id="message" name="message" maxlength="4000"></textarea></div>
<div class="hp" aria-hidden="true"><label for="website">Leave this empty</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>
{turnstile}<div class="full"><button class="btn" type="submit">Send the request</button>
<p class="muted" style="font-size:14px">Used only to reply to you and put your quote together. <a href="/privacy/">Privacy</a>.</p></div>
</form></div></section>
<script>
const p=new URLSearchParams(location.search).get("error");
const m={{missing:"Please add your name and a working email.",busy:"A few requests just came from here. Please try again in an hour, or email us.",check:"The spam check did not pass. Please try again.",unreadable:"Something went wrong. Please try again."}};
if(p){{document.getElementById("err").innerHTML='<div class="err">'+(m[p]||m.unreadable)+'</div>';}}
</script>"""
    pages["book/index.html"] = ("Request a quote", book)
    pages["thanks/index.html"] = ("Thank you", """<section style="border-top:0;min-height:60vh"><div class="wrap" style="max-width:760px">
<div class="kicker">Request received</div><h1 style="font-size:clamp(36px,5vw,60px)">Thank you.</h1>
<p class="muted">Your request is in. A reply comes back to you by email.</p><p><a class="btn ghost" href="/">Back to the site</a></p></div></section>""")
    pages["availability/index.html"] = ("Availability", """<section style="border-top:0"><div class="wrap"><div class="kicker">Availability</div>
<h1 style="font-size:clamp(36px,5vw,60px)">Open dates.</h1><p class="muted">Dates marked in blue are booked. Every other date is open to request.</p>
<div class="cal" id="cal"></div><p style="margin-top:36px"><a class="btn" href="/book/">Request a quote</a></p></div></section>
<script>
const MONTHS=["January","February","March","April","May","June","July","August","September","October","November","December"];
function draw(booked){const set=new Set(booked);const cal=document.getElementById("cal");const t=new Date();
for(let k=0;k<6;k++){const first=new Date(t.getFullYear(),t.getMonth()+k,1);const y=first.getFullYear(),m=first.getMonth();
let h='<div class="month"><h3>'+MONTHS[m]+' '+y+'</h3><div class="days">'+["S","M","T","W","T","F","S"].map(d=>'<span class="h">'+d+'</span>').join("");
for(let i=0;i<first.getDay();i++)h+='<span class="x"></span>';const n=new Date(y,m+1,0).getDate();
for(let d=1;d<=n;d++){const iso=y+"-"+String(m+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");h+='<span class="'+(set.has(iso)?"b":"")+'" title="'+(set.has(iso)?"Booked":"Open")+'">'+d+'</span>';}
cal.insertAdjacentHTML("beforeend",h+'</div></div>');}}
fetch("/api/availability").then(r=>r.json()).then(j=>draw(j.booked||[])).catch(()=>draw([]));
</script>""")
    pages["privacy/index.html"] = ("Privacy and photo removal", f"""<section style="border-top:0"><div class="wrap" style="max-width:760px">
<div class="kicker">Privacy</div><h1 style="font-size:clamp(34px,4.6vw,54px)">Privacy and photo removal.</h1>
<h3 style="margin-top:36px">The quote form</h3><p class="muted">What you send through the form is used only to reply to you and to prepare your quote.
It is never sold or shared. The website holds it only until it is collected, usually within minutes.</p>
<h3 style="margin-top:28px">Photos of you</h3><p class="muted">If you appear in a photo shared by {e(brand)} and want it taken down, email
<a href="mailto:{e(contact_email())}">{e(contact_email())}</a> with a link to it. It comes down, and it stays out of anything shared after that.</p>
<h3 style="margin-top:28px">Who we are</h3><p class="muted">{e(brand)} is a brand of {e(config.get_config().legal_name)}.</p></div></section>""")
    pages["404.html"] = ("Not found", """<section style="border-top:0;min-height:60vh"><div class="wrap"><h1>Not found.</h1>
<p><a class="btn ghost" href="/">Back to the site</a></p></div></section>""")
    for rel, (title, body) in pages.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(title if rel == "index.html" else f"{title} | {brand}", body, preview=preview,
                             description=t["lede"], brand=brand), encoding="utf-8")
    (out / "build.json").write_text(json.dumps({"preview": preview, "hero": len(photos.hero), "coverage": len(photos.coverage),
                                                "venues": len(photos.venues)}))
    return out
