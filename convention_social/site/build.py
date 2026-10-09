"""eventcaliber.com, built on the Mini into site/dist and served by the Worker.

`build(conn, photos)` writes every page, the stylesheet, the script, the mark
and the photos. The look lives in site/theme.py (black, greys and white with
one cyan, built like a camera viewfinder; Chris, 2026-10-10) and the logo in
site/marks.py (Aperture, Chris's choice; BRAND_MARK). Photos on the site are public, so they pass the same gate as a
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
from ..seo import markup
from ..library import eligibility
from ..render import fonts
from ..render.meta import ImageMeta, save_jpeg
from . import marks, theme

DIST = config.REPO_ROOT / "site" / "dist"
WIDTHS = (800, 1600)


@dataclass
class SitePhotos:
    hero: list = field(default_factory=list)       # [(image, alt)] or [(image, alt, ImageMeta)]
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


def save_web(im: Image.Image, out_dir: Path, stem: str, meta: Optional[ImageMeta] = None) -> dict:
    """JPEGs at each width, from pixels only: no camera data or GPS, our SEO fields inside. {width: filename}."""
    im = ImageOps.exif_transpose(im).convert("RGB")
    made = {}
    for w in WIDTHS:
        copy = im.copy()
        copy.thumbnail((w, w * 2))
        name = f"{stem}-{w}.jpg"
        save_jpeg(copy, out_dir / name, meta, quality=82)
        made[w] = name
    return made


def img_tag(files: dict, alt: str, sizes: str, cls: str = "", eager: bool = False, extra: str = "") -> str:
    srcset = ", ".join(f"/assets/{n} {w}w" for w, n in sorted(files.items()))
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<img class="{cls}" src="/assets/{files[max(files)]}" srcset="{srcset}" sizes="{sizes}" '
            f'alt="{html.escape(alt)}" {load} decoding="async"{extra}>')


def contact_email() -> str:
    cfg = config.get_config()
    return cfg.brand_from_email or f"hello@{cfg.brand_domain}"


def copy_text() -> dict:
    o = offer.load()
    return {
        "title": f"{o['company']}: {o['tagline']}",
        "lede": ("Fan conventions, conferences, galas and award dinners, photographed room by room. "
                 "Approved images reach your attendees, staff, speakers and presenters while the event is still on."),
        "coverage_p": "Tell us which rooms matter. Coverage is planned around your schedule, and every event is quoted on its own.",
        "deliver_p": ("Approved images go to attendees, staff, speakers and presenters during the event, "
                      "so they share them while the moment is still happening."),
        "steps": [("Tell us about your event", "Dates, venue, the rooms and moments that matter, and who needs images."),
                  ("Get a quote for your dates", "A clear quote for the coverage you need, nothing bundled you did not ask for."),
                  ("Images while it is still on", "Approved images reach your attendees, staff, speakers and presenters during the event.")],
        "venues_p": ("Years of architectural work mean the venue gets shot as carefully as the people in it: "
                     "exteriors, lobbies, halls and ballrooms."),
        "cta_p": "Send the dates and the details. A quote comes back for your event, with the coverage you asked for.",
    }


def check_copy(texts) -> None:
    for t in texts:
        r = copy_rules.check(t)
        if not r.ok:
            raise SiteCopyRefused(f"{t[:60]!r}: {r.blocks[0].message}")


def _photo(entry):
    """(image, alt) or (image, alt, meta) -> (image, alt, meta)."""
    if len(entry) == 3:
        return entry
    im, alt = entry
    return im, alt, ImageMeta(title=alt, description=alt, keywords=("event photography", "convention photography"))


def _ticker(labels: list[str], rev: bool = False) -> str:
    items = []
    for i, label in enumerate(labels):
        items.append(f'<span class="{"o" if i % 2 else ""}">{html.escape(label)}</span><span class="dot">&#9679;</span>')
    run = "".join(items)
    return f'<div class="ticker{" rev" if rev else ""}" aria-hidden="true"><div class="track">{run}{run}</div></div>'


def home_body(t: dict, hero: str, frames: list[tuple[str, str]], stack: list[str], venues: list[tuple[str, str]],
              peeks: list[str]) -> str:
    e = html.escape
    labels = [c["label"] for c in offer.load()["coverage"]]
    rows = "".join(
        f'<a href="/book/" data-img="{e(peeks[i % len(peeks)]) if peeks else ""}"><span class="mono g">{i + 1:02d}</span>'
        f'<span class="t">{e(label if len(label) < 40 else label.split(" to ")[0])}</span><span class="mono">&#8599;</span></a>'
        for i, label in enumerate(labels))
    reel = "".join(f'<div class="frame"><div class="ph">{img}</div><div class="cap mono"><span>FR {i + 1:02d} / {len(frames):02d}</span>'
                   f'<span>{e(cap)}</span></div></div>' for i, (img, cap) in enumerate(frames))
    stack_html = "".join(f"<figure>{img}</figure>" for img in stack[:3])
    venue_html = "".join(f'<figure>{img}<span class="mono">{e(label)}</span></figure>' for img, label in venues[:3])
    steps = "".join(f'<div class="rv"><div class="n">{i:02d}</div><h3>{e(h)}</h3><p>{e(p)}</p></div>'
                    for i, (h, p) in enumerate(t["steps"], start=1))
    short = ["Backstage", "Green rooms", "Breakouts", "Main stage", "Evening events", "Dinners", "Portraits",
             "Cosplay", "Exhibition halls", "Vendors", "Delivered on site"]
    return f"""
<section class="hero"><div class="img">{hero}</div>
<div class="vf" aria-hidden="true"><i></i><i></i><i></i><i></i><span class="cross"></span><span class="focus"></span></div>
<div class="hud tl mono"><span class="rec">Rec</span> <span id="tc">00:00:00:00</span></div>
<div class="hud tr mono">ISO 3200 &nbsp; 1/250 &nbsp; F2.8 &nbsp; AWB</div>
<div class="hud br mono">FR <span id="fr">0001</span></div>
<div class="copy"><div class="kick mono c">Event and convention photography</div>
<h1 class="mega"><span><em>Every</em></span><span class="o"><em>room,</em></span><span><em>covered<b>.</b></em></span></h1>
<div class="row"><p class="lede">{e(t['lede'])}</p><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></div></div></section>
{_ticker(short)}
<section id="coverage" class="index"><div class="head rv"><div><div class="kick mono c">01 / Coverage</div>
<h2>From the green room<br><span class="o">to the last</span> reception.</h2></div><p>{e(t['coverage_p'])}</p></div>
<div class="list rv">{rows}</div><div class="peek" aria-hidden="true"><img alt=""></div></section>
{f'<section id="work" class="reel"><div class="pin"><div class="bar"><div class="kick mono c" style="margin:0">02 / Work</div><span class="mono g">Scroll</span></div><div class="track">{reel}</div><div class="sprocket" style="margin-top:22px"></div></div></section>' if reel else ''}
<section class="deliver"><div class="rv"><div class="kick mono c">On site delivery</div>
<div class="lines"><div>Approved.</div><div>Delivered.</div><div>While it is still on.</div></div><p>{e(t['deliver_p'])}</p></div>
{f'<div class="stack rv">{stack_html}<span class="stamp mono">Approved</span></div>' if stack_html else ''}</section>
{f'<section id="venues" class="venues"><div class="head rv"><div><div class="kick mono c">03 / Venues</div><h2>The building is <span class="o">part of</span> the story.</h2></div><p>{e(t["venues_p"])}</p></div><div class="grid">{venue_html}</div></section>' if venue_html else ''}
<section><div class="kick mono c rv">How it works</div><h2 class="rv">Three steps.</h2><div class="steps">{steps}</div></section>
{_ticker(list(reversed(short)), rev=True)}
<section class="cta"><div class="kick mono c" style="justify-content:center">Planning an event</div>
<a class="huge" href="/book/">Request a quote</a><p>{e(t['cta_p'])}</p></section>"""


def build(conn: Optional[sqlite3.Connection], photos: SitePhotos, *, out: Path = DIST, preview: bool = False,
          head_extra: str = "") -> Path:
    o = offer.load()
    cfg = config.get_config()
    brand = cfg.brand_name
    t = copy_text()
    check_copy([v if isinstance(v, str) else " ".join(x for pair in v for x in pair) for v in t.values()] + offer.coverage_labels())
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    (assets / "fonts").mkdir(parents=True)
    for name in ("Michroma-Regular.ttf", "JetBrainsMono-Medium.ttf", "InterTight-Light.ttf", "InterTight-Regular.ttf",
                 "InterTight-SemiBold.ttf", "Unbounded-ExtraBold.ttf"):
        src = fonts._find(name)
        if src:
            shutil.copyfile(src, assets / "fonts" / name)
    (assets / "site.css").write_text(theme.CSS)
    (assets / "site.js").write_text(theme.JS)
    mark_key = (config.getenv("BRAND_MARK") or "aperture").lower()       # Chris chose Aperture, 2026-10-10
    (assets / "mark.svg").write_text(marks.mark(mark_key, brand, light="#0A0A0B", size=64, word=False))
    mark_svg = marks.mark(mark_key, brand, size=40)
    e = html.escape
    hero, frames, stack, venues, peeks = "", [], [], [], []
    shown: list[tuple[str, str, ImageMeta]] = []          # (published path, alt, meta) for the sitemap and JSON-LD
    if photos.hero:
        im, alt, m = _photo(photos.hero[0])
        files = save_web(im, assets, "hero", m)
        hero = img_tag(files, alt, "100vw", eager=True)
        shown.append((f"/assets/{files[max(files)]}", alt, m))
    for i, entry in enumerate(photos.coverage):
        im, alt, m = _photo(entry)
        files = save_web(im, assets, f"work-{i}", m)
        shown.append((f"/assets/{files[max(files)]}", alt, m))
        tag = img_tag(files, alt, "(max-width:900px) 78vw, 34vw")
        frames.append((tag, (m.title or alt)[:34]))
        peeks.append(f"/assets/{files[min(files)]}")
        if i < 3:
            stack.append(tag)
    for i, entry in enumerate(photos.venues):
        im, alt, m = _photo(entry)
        files = save_web(im, assets, f"venue-{i}", m)
        shown.append((f"/assets/{files[max(files)]}", alt, m))
        venues.append((img_tag(files, alt, "(max-width:900px) 100vw, 60vw", extra=' data-speed="0.08"'),
                       "Exterior" if i % 2 == 0 else "Interior"))
    base = f"https://{cfg.brand_domain}"
    pages = {"index.html": (t["title"], t["lede"], home_body(t, hero, frames, stack, venues, peeks))}
    chips = "".join(f'<label><input type="checkbox" name="coverage" value="{e(c["key"])}"><span>{e(c["label"] if len(c["label"]) < 40 else "Approved images delivered on site")}</span></label>'
                    for c in o["coverage"])
    site_key = config.getenv("TURNSTILE_SITE_KEY") or ""
    turnstile = (f'<div class="full"><div class="cf-turnstile" data-sitekey="{e(site_key)}" data-theme="dark"></div></div>'
                 '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>') if site_key else ""
    questions = "".join(f"<li>{e(q)}</li>" for q in (o.get("quote_questions") or [])[:4])
    pages["book/index.html"] = ("Request a quote", "Tell us about your event and get a quote for your dates.", f"""
<section class="page"><div class="kick mono c">Request a quote</div><h1>Tell us about<br><span class="o">your</span> event<b>.</b></h1>
<div class="split2"><aside class="side"><div class="mono c">What helps the quote</div><ol>{questions}</ol>
<p class="mono g" style="margin-top:22px">Every event is quoted on its own.</p></aside>
<div><div id="err"></div><form class="book" method="post" action="/api/quote">
<div class="f"><label class="mono" for="name">Your name</label><input id="name" name="name" required maxlength="120" autocomplete="name"></div>
<div class="f"><label class="mono" for="email">Email</label><input id="email" name="email" type="email" required maxlength="200" autocomplete="email"></div>
<div class="f"><label class="mono" for="phone">Phone, optional</label><input id="phone" name="phone" maxlength="40" autocomplete="tel"></div>
<div class="f"><label class="mono" for="organization">Organization</label><input id="organization" name="organization" maxlength="160" autocomplete="organization"></div>
<div class="f full"><label class="mono" for="event_name">Event name</label><input id="event_name" name="event_name" maxlength="200"></div>
<div class="f"><label class="mono" for="event_kind">Kind of event</label><select id="event_kind" name="event_kind"><option value="fan">Fan convention</option>
<option value="business">Conference or political event</option><option value="other">Gala, reception or something else</option></select></div>
<div class="f"><label class="mono" for="attendance">Expected attendance</label><input id="attendance" name="attendance" maxlength="40"></div>
<div class="f"><label class="mono" for="start_date">First day</label><input id="start_date" name="start_date" type="date"></div>
<div class="f"><label class="mono" for="end_date">Last day</label><input id="end_date" name="end_date" type="date"></div>
<div class="f"><label class="mono" for="venue">Venue</label><input id="venue" name="venue" maxlength="200"></div>
<div class="f"><label class="mono" for="city">City</label><input id="city" name="city" maxlength="120"></div>
<div class="f full"><label class="mono">What should be covered</label><div class="chips">{chips}</div></div>
<div class="f full"><label class="mono" for="message">Anything else</label><textarea id="message" name="message" maxlength="4000"></textarea></div>
<div class="hp" aria-hidden="true"><label for="website">Leave this empty</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>
{turnstile}<div class="full"><button class="btn fill" type="submit">Send the request <span class="arr">&#8599;</span></button>
<p class="mono g" style="margin-top:16px">Used only to reply to you and put your quote together. <a href="/privacy/" class="c">Privacy</a>.</p></div>
</form></div></div></section>
<script>const q=new URLSearchParams(location.search).get("error");const m={{missing:"Please add your name and a working email.",busy:"A few requests just came from here. Please try again in an hour, or email us.",check:"The spam check did not pass. Please try again.",unreadable:"Something went wrong. Please try again."}};
if(q)document.getElementById("err").innerHTML='<div class="err mono">'+(m[q]||m.unreadable)+'</div>';</script>""")
    pages["thanks/index.html"] = ("Thank you", "Your request is in.", """<section class="page" style="min-height:70vh">
<div class="kick mono c">Request received</div><h1>Thank<br><span class="o">you</span><b>.</b></h1>
<p class="g" style="max-width:560px;margin-top:30px">Your request is in. A reply comes back to you by email.</p>
<p style="margin-top:30px"><a class="btn" href="/">Back to the site <span class="arr">&#8599;</span></a></p></section>""")
    pages["availability/index.html"] = ("Availability", "Booked dates are marked. Every other date is open to request.", """
<section class="page"><div class="kick mono c">04 / Availability</div><h1>Open<br><span class="o">dates</span><b>.</b></h1>
<div class="legend mono"><span><i class="b"></i>Booked</span><span><i></i>Open to request</span></div>
<div class="cal" id="cal"></div><p style="margin-top:50px"><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></p></section>
<script>
const MONTHS=["January","February","March","April","May","June","July","August","September","October","November","December"];
function draw(booked){const set=new Set(booked),cal=document.getElementById("cal"),t=new Date(),today=t.toISOString().slice(0,10);
for(let k=0;k<6;k++){const first=new Date(t.getFullYear(),t.getMonth()+k,1),y=first.getFullYear(),m=first.getMonth();
let h='<div class="month"><h3>'+MONTHS[m]+' '+y+'</h3><div class="days">'+["S","M","T","W","T","F","S"].map(d=>'<span class="h">'+d+'</span>').join("");
for(let i=0;i<first.getDay();i++)h+='<span class="x"></span>';const n=new Date(y,m+1,0).getDate();
for(let d=1;d<=n;d++){const iso=y+"-"+String(m+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");
h+='<span class="'+(set.has(iso)?"b":(iso===today?"t":""))+'" title="'+(set.has(iso)?"Booked":"Open")+'">'+d+'</span>';}
cal.insertAdjacentHTML("beforeend",h+'</div></div>');}}
fetch("/api/availability").then(r=>r.json()).then(j=>draw(j.booked||[])).catch(()=>draw([]));
</script>""")
    pages["privacy/index.html"] = ("Privacy and photo removal", "How quote requests are handled, and how to have a photo taken down.", f"""
<section class="page"><div class="kick mono c">Privacy</div><h1>Privacy<b>.</b></h1><div class="prose">
<h3>The quote form</h3><p>What you send through the form is used only to reply to you and to prepare your quote.
It is never sold or shared. The website holds it only until it is collected, usually within minutes.</p>
<h3>Photos of you</h3><p>If you appear in a photo shared by {e(brand)} and want it taken down, email
<a class="c" href="mailto:{e(contact_email())}">{e(contact_email())}</a> with a link to it. It comes down, and it stays out of anything shared after that.</p>
<h3>Who we are</h3><p>{e(brand)} is a brand of {e(cfg.legal_name)}.</p></div></section>""")
    pages["404.html"] = ("Not found", "Not found.", """<section class="page" style="min-height:70vh"><div class="kick mono c">Out of frame</div>
<h1>Not<br><span class="o">found</span><b>.</b></h1><p style="margin-top:30px"><a class="btn" href="/">Back to the site <span class="arr">&#8599;</span></a></p></section>""")
    og = f"{base}/assets/hero-1600.jpg" if hero else ""
    if not head_extra:
        blocks = [markup.jsonld_business(brand, cfg.legal_name, base + "/", contact_email(), t["lede"])]
        blocks += [markup.jsonld_image(markup.absolute(base, loc), brand, cfg.legal_name, m.credit or brand)
                   for loc, _, m in shown]
        head_extra = "".join(markup.jsonld_script(b) for b in blocks)
    for rel, (title, desc, body) in pages.items():
        check_copy([desc])
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        path = "/" + rel.replace("index.html", "")
        dest.write_text(theme.shell(title=e(title if rel == "index.html" else f"{title} | {brand}"), description=e(desc), body=body,
                                    mark_svg=mark_svg, brand=e(brand), legal=e(cfg.legal_name), email=e(contact_email()),
                                    preview=preview, canonical=base + path, jsonld=head_extra if rel == "index.html" else "",
                                    og_image=og), encoding="utf-8")
    # a preview is never crawled; the live site lists its public pages and every photo on them
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if preview else markup.robots_txt(base))
    (out / "sitemap.xml").write_text(markup.sitemap_xml(
        base, ["/", "/book/", "/availability/", "/privacy/"],
        {"/": [{"loc": loc, "title": m.title or alt, "caption": m.description or alt} for loc, alt, m in shown]}))
    (out / "build.json").write_text(json.dumps({"preview": preview, "hero": len(photos.hero), "coverage": len(photos.coverage),
                                                "venues": len(photos.venues), "mark": mark_key}))
    return out
