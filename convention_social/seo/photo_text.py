"""Search text for photos: slug, title, alt text, description and keywords, kept in photo_seo.

Which photos: every postable photo (library.eligibility.is_eligible) and every
photo on a content_queue row that is not rejected, as long as it is still a
candidate (a photo on the do-not-use list, or one Chris blocked, gets nothing).

Where the words come from: the photo's classification (subject, shot_type,
convention_name, event_kind, view, summary), the credit Chris recorded
(eligibility.credit_line; only @handles are ever used) and the calendar
(conventions.city, only when a calendar row is tied to the photo by its
folder, by a queued post or by the event's name). Text only: no image is sent.

Writers: claude-haiku-4-5 (SEO_MODEL overrides) when a key is set, the run is
live and the monthly cap allows; otherwise a deterministic template from the
same fields. Every answer is checked before it is stored (problems()): the
copy rules (no price, no dash, no affiliation or client claims), alt text
under 125 characters, no street address or house number, no @handle that is
not a recorded credit, nothing that reads like a person's name, and for
buildings no proper names and no numbers but a year. An answer that fails
is thrown away and the template is stored instead.

Rules for rows: the slug is set once and never changes; a template row is
upgraded when a live run has Claude; a row Chris corrected (edited_at) is
never written again.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, replace
from typing import Optional

from ..ai import copy_rules, spend
from ..ai.claude import FALLBACK_BETA, tidy
from ..core import config, db, runner, secrets
from ..library import eligibility

DEFAULT_MODEL = "claude-haiku-4-5"
ALT_MAX = 124                     # alt text stays under 125 characters
TITLE_MAX = 70
DESCRIPTION_MAX = 200
KEYWORD_MAX_LEN = 60
SLUG_MAX = 70
KEYWORDS_MIN, KEYWORDS_MAX = 5, 10
PER_RUN_DEFAULT = 300
MAX_DEPTH = 64

SHOT_WORDS = {
    "cosplay_portrait": "Cosplay portrait", "portrait": "Portrait", "headshot": "Headshot", "group": "Group photo",
    "candid": "Candid moment", "stage_panel": "Stage and panel", "stage": "Stage", "vendor_hall": "Vendor hall",
    "booth": "Exhibitor booth", "backstage": "Backstage", "dinner_reception": "Dinner and reception", "dinner": "Dinner",
    "crowd": "Crowd", "venue": "Venue",
}
PEOPLE_SHOTS = {"cosplay_portrait", "portrait", "headshot", "group"}
KIND_WORDS = {"fan": "fan convention", "business": "business or political conference"}
KIND_KEYWORDS = {"fan": "fan convention photography", "business": "conference photography"}
# words that are never a person's name, so a Title Cased answer is not mistaken for one
COMMON_WORDS = set("""
a an the and or of at in on for with by from to into near during before after while
photo photos photograph photography photographer event events convention conventions conference conferences
portrait portraits cosplay cosplayer cosplayers candid moment stage panel panels backstage green room rooms vendor vendors
hall halls booth booths exhibitor exhibitors exhibition dinner dinners reception receptions gala galas award awards
headshot headshots crowd crowds venue venues building buildings architecture architectural interior exterior view
group groups keynote speaker speakers presenter presenters attendee attendees staff fan fans business political
anime comic comics gaming game games expo summit forum floor lobby ballroom atrium hotel center centre office tower
glass brick stone modern historic entrance facade evening night morning dusk day light lights coverage professional
full image images moment moments costume costumes character characters crowded busy quiet empty large small
""".split())
ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'’]+\s+){0,3}(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|way|"
    r"court|ct|place|pl|terrace|parkway|pkwy|highway|hwy|circle|cir)\b", re.IGNORECASE)
HANDLE = re.compile(r"@[A-Za-z0-9_.]+")
WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")

SYSTEM = """You write search text for one photo from an event and convention photography company's archive: a short title, alt text for people using screen readers, a one or two sentence description, and search keywords.
Write plain, short sentences in sentence case. Use commas and periods, never a dash of any kind.
Rules:
1. The alt text says literally what the photo shows, in under 125 characters. Do not start it with "image of" or "photo of".
2. Never name a person. The only way to identify anyone is a credit handle given in the facts, written exactly as given.
3. Never write a street address, a house number or a street name. Describe a building by its type, such as hotel, convention center, office tower or house, never by its owner or its name.
4. Never state or hint at a price. Never say or imply the company is an event's official photographer, partner or sponsor, and never name clients.
5. Use only the facts given. Name the event and the year only when the facts give them.
6. Keywords: 5 to 10 short lowercase phrases people search for, such as event photography, convention photography, the kind of event and the kind of shot. Add a city only when the facts give one.
Return JSON only, matching the schema."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "under 70 characters"},
        "alt": {"type": "string", "description": "literal, under 125 characters"},
        "description": {"type": "string", "description": "one or two short sentences"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "alt", "description", "keywords"],
    "additionalProperties": False,
}


class CapReached(RuntimeError):
    pass


class TemplateRefused(ValueError):
    """Even the plain template does not pass the checks for this photo (its event name breaks a rule)."""


@dataclass(frozen=True)
class PhotoFacts:
    photo_id: int
    subject: str                     # event | architecture | other
    shot_type: str
    event_name: str                  # '' for buildings: a building is described by type, never by name
    event_kind: str
    year: str
    city: str                        # only from a calendar row
    view: str                        # exterior | interior | ''
    summary: str
    handles: tuple[str, ...]
    brand: str


# ------------------------------------------------------------------ facts

def calendar_row(conn: sqlite3.Connection, photo: sqlite3.Row, event_name: str) -> Optional[sqlite3.Row]:
    """The conventions row tied to this photo: its folder (nearest first), a queued post, or the event's name."""
    folder, seen = photo["folder_id"], set()
    while folder and folder not in seen and len(seen) < MAX_DEPTH:
        seen.add(folder)
        f = db.one(conn, "SELECT parent_id, convention_id FROM drive_folders WHERE drive_id=?", (folder,))
        if f is None:
            break
        if f["convention_id"]:
            row = db.one(conn, "SELECT * FROM conventions WHERE id=?", (f["convention_id"],))
            if row:
                return row
        folder = f["parent_id"]
    for q in db.rows(conn, "SELECT convention_id, photo_ids FROM content_queue WHERE convention_id IS NOT NULL "
                           "AND status != 'rejected' ORDER BY id DESC"):
        if photo["id"] in _ids(q["photo_ids"]):
            row = db.one(conn, "SELECT * FROM conventions WHERE id=?", (q["convention_id"],))
            if row:
                return row
    if event_name:
        return db.one(conn, "SELECT * FROM conventions WHERE lower(name)=lower(?) ORDER BY id LIMIT 1", (event_name,))
    return None


def _ids(value) -> list[int]:
    try:
        out = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    ids = []
    for x in out if isinstance(out, list) else []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    return ids


def gather(conn: sqlite3.Connection, photo_id: int, cfg: Optional[config.Config] = None) -> Optional[PhotoFacts]:
    """Everything the writers may use about one photo, or None when it was never sorted."""
    cfg = cfg or config.get_config()
    row = db.one(conn, "SELECT p.id, p.folder_id, p.taken_at, c.subject, c.shot_type, c.convention_name, c.event_kind, "
                       "c.summary, c.view FROM photos p JOIN classifications c ON c.photo_id = p.id WHERE p.id=?", (photo_id,))
    if row is None or not row["subject"]:
        return None
    subject = row["subject"]
    event_name = (row["convention_name"] or "").strip() if subject == "event" else ""
    cal = calendar_row(conn, row, event_name)
    if subject == "event" and not event_name and cal is not None:
        event_name = (cal["name"] or "").strip()
    year = (row["taken_at"] or "")[:4]
    if not year.isdigit() and cal is not None:
        year = (cal["start_date"] or "")[:4]
    year = year if year.isdigit() else ""
    credit = eligibility.credit_line(conn, photo_id)
    handles = tuple(dict.fromkeys(w for w in credit.split() if w.startswith("@") and len(w) > 1))
    return PhotoFacts(photo_id=photo_id, subject=subject, shot_type=row["shot_type"] or "", event_name=event_name,
                      event_kind=row["event_kind"] or "unknown", year=year,
                      city=((cal["city"] or "").strip() if cal is not None else ""),
                      view=row["view"] if row["view"] in ("exterior", "interior") else "",
                      summary=(row["summary"] or "").strip(), handles=handles, brand=cfg.brand_name)


# ------------------------------------------------------------------ slugs

def slugify(text: str, limit: int = SLUG_MAX) -> str:
    """Lowercase ASCII words joined by single hyphens, cut at a word boundary within `limit`."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > limit:
        cut = slug[:limit + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else slug[:limit]
    return slug.strip("-")


def shot_words(f: PhotoFacts) -> str:
    if f.subject == "architecture":
        if f.view or f.shot_type in ("building_exterior", "building_interior"):
            return "Building " + (f.view or f.shot_type.split("_", 1)[1])
        return "Building"
    return SHOT_WORDS.get(f.shot_type, "Event photo")


def slug_base(f: PhotoFacts) -> str:
    if f.subject == "architecture":
        return slugify(" ".join(x for x in (shot_words(f), f.city, "photography") if x))
    return slugify(" ".join(x for x in (shot_words(f), f.event_name, f.year) if x))


def unique_slug(conn: sqlite3.Connection, base: str, photo_id: int) -> str:
    base = base or f"photo-{photo_id}"
    candidate, n = base, 1
    while db.one(conn, "SELECT 1 FROM photo_seo WHERE slug=? AND photo_id != ?", (candidate, photo_id)):
        suffix = f"-{photo_id}" + (f"-{n}" if n > 1 else "")
        candidate = slugify(base, SLUG_MAX - len(suffix)) + suffix
        n += 1
    return candidate


# ------------------------------------------------------------------ the template

def _cut(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.")


def _dedupe(items) -> list[str]:
    out, seen = [], set()
    for item in items:
        k = " ".join((item or "").lower().split())
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def filler_keywords(f: PhotoFacts) -> list[str]:
    """Generic phrases that bring a short list up to five; they go last, after anything more specific."""
    return ["event photographer", "convention photographer", f.brand]


def template_keywords(f: PhotoFacts, *, filler: bool = True) -> list[str]:
    shot = shot_words(f).lower()
    kw = ["event photography", "convention photography"]
    if f.subject == "architecture":
        kw += ["architecture photography", "venue photography", f"{shot} photography"]
    else:
        if f.event_kind in KIND_KEYWORDS:
            kw.append(KIND_KEYWORDS[f.event_kind])
        if shot != "event photo":
            kw.append(shot)
        if f.shot_type == "cosplay_portrait":
            kw.append("cosplay photography")
        if f.event_name:
            kw.append(f"{f.event_name} photography")
            if f.year:
                kw.append(f"{f.event_name} {f.year}")
    if f.city:
        kw.append(f"{f.city} event photography")
    if filler:
        kw += filler_keywords(f)
    return _dedupe(kw)[:KEYWORDS_MAX]


def template(f: PhotoFacts) -> dict:
    """Plain words from the fields alone. It never reads the summary, so it cannot repeat a name or an address."""
    shot = shot_words(f)
    if f.subject == "architecture":
        alt = {"exterior": "Exterior view of a building", "interior": "Interior view of a building"}.get(f.view, "View of a building")
        title = f"{shot} photography" + (f" in {f.city}" if f.city else "")
        description = f"{alt}. Venue and architecture photography by {f.brand}."
    else:
        where = " ".join(x for x in (f.event_name, f.year) if x)
        who = f" of {' and '.join(f.handles)}" if f.handles and f.shot_type in PEOPLE_SHOTS else ""
        title = f"{shot} at {where}" if where else f"{shot}, event photography"
        alt = f"{shot}{who} at {where}" if where else f"{shot}{who} at an event"
        place = f" in {f.city}" if f.city else ""
        description = (f"{shot} at {where}{place}. " if where else f"{shot}{place}. ") + \
                      f"Event and convention photography by {f.brand}."
    return {"title": _cut(title, TITLE_MAX), "alt": _cut(alt, ALT_MAX), "description": _cut(description, DESCRIPTION_MAX),
            "keywords": template_keywords(f)}


# ------------------------------------------------------------------ the checks

def _sentence_starts(text: str) -> set[int]:
    starts = {0}
    for m in re.finditer(r"[.!?:]\s+", text):
        starts.add(m.end())
    return starts


def name_problems(name: str, text: str, f: PhotoFacts) -> list[str]:
    """A guess at a person's or an owner's name: capitalized words that are not the event, the city,
    the brand, a credit or an ordinary word. Events: two such words in a row. Buildings: any one,
    and any number but the year."""
    allowed = set(COMMON_WORDS)
    for phrase in (f.event_name, f.city, f.brand, shot_words(f)):
        allowed.update(w.lower() for w in WORD.findall(phrase or ""))
    starts = _sentence_starts(text)
    flagged = []
    for m in WORD.finditer(text):
        tok = m.group(0)
        unknown = tok[0].isupper() and tok.lower().strip("'’") not in allowed
        flagged.append((m.start(), tok, unknown and m.start() not in starts, unknown))
    out = []
    if f.subject == "architecture":
        names = [tok for _, tok, mid, _u in flagged if mid]
        if names:
            out.append(f"{name} names something ({' '.join(names[:3])}); a building is described by its type")
        numbers = [n for n in re.findall(r"\d+", text) if n != f.year]
        if numbers:
            out.append(f"{name} has a number ({numbers[0]}); a building shot shows no address or house number")
        return out
    run: list[str] = []
    for i, (_, tok, _mid, unknown) in enumerate(flagged):
        prev_end = flagged[i - 1][0] + len(flagged[i - 1][1]) if i else None
        adjacent = prev_end is not None and text[prev_end:flagged[i][0]].strip() == ""
        if unknown and (adjacent and run):
            run.append(tok)
        elif unknown:
            run = [tok]
        else:
            run = []
        if len(run) >= 2:
            out.append(f"{name} may name a person ({' '.join(run)})")
            break
    return out


def problems(fields: dict, f: PhotoFacts, *, guess_names: bool = True) -> list[str]:
    """Why these words may not be stored (empty when they may). `guess_names` is off only for Chris's own edits."""
    out = []
    credited = {h.lower() for h in f.handles}
    for name, limit in (("title", TITLE_MAX), ("alt", ALT_MAX), ("description", DESCRIPTION_MAX)):
        text = fields.get(name)
        if not isinstance(text, str) or not text.strip():
            out.append(f"{name} is empty")
            continue
        if len(text) > limit:
            out.append(f"{name} is {len(text)} characters, the most is {limit}")
        report = copy_rules.check(text)
        if not report.ok:
            out.append(f"{name} {report.blocks[0].message}")
        if ADDRESS.search(text):
            out.append(f"{name} has what looks like a street address")
        for h in HANDLE.findall(text):
            if h.rstrip(".").lower() not in credited:
                out.append(f"{name} names {h}, which is not a recorded credit")
        if guess_names:
            out += name_problems(name, text, f)
    kws = fields.get("keywords")
    if not isinstance(kws, list) or not KEYWORDS_MIN <= len(kws) <= KEYWORDS_MAX:
        out.append(f"keywords must be {KEYWORDS_MIN} to {KEYWORDS_MAX}")
    else:
        for k in kws:
            if not isinstance(k, str) or not k.strip() or len(k) > KEYWORD_MAX_LEN or not copy_rules.check(k).ok \
                    or ADDRESS.search(k) or "@" in k:
                out.append(f"keyword {k!r} is not allowed")
                break
    return out


def allowed_vocabulary(f: PhotoFacts) -> set[str]:
    words = set(COMMON_WORDS)
    for phrase in template_keywords(f) + [f.event_name, f.city, f.brand, shot_words(f), KIND_WORDS.get(f.event_kind, "")]:
        words.update(w.lower() for w in WORD.findall(phrase or ""))
    return words


def merge_keywords(suggested, f: PhotoFacts) -> list[str]:
    """The template's specific keywords first (they always hold), then Claude's extra ones made only of words
    the facts allow, so a city or a name the facts did not give can never slip in, then the generic filler.
    5 to 10, lowercase, unique."""
    vocab = allowed_vocabulary(f)
    extra = []
    for k in suggested if isinstance(suggested, list) else []:
        if not isinstance(k, str):
            continue
        k = " ".join(tidy(k).lower().split())
        tokens = re.findall(r"[a-z0-9'’]+", k)
        if tokens and all(t in vocab or (f.year and t == f.year) for t in tokens) and copy_rules.check(k).ok \
                and len(k) <= KEYWORD_MAX_LEN:
            extra.append(k)
    return _dedupe(template_keywords(f, filler=False) + extra + filler_keywords(f))[:KEYWORDS_MAX]


# ------------------------------------------------------------------ Claude

def user_text(f: PhotoFacts) -> str:
    if f.subject == "architecture":
        subject = "a building from the photographer's architecture work" + (f", {f.view}" if f.view else "")
    else:
        subject = "an event photo"
    return "\n".join([
        f"Company: {f.brand}",
        f"Subject: {subject}",
        f"Shot type: {shot_words(f)}",
        f"Event: {f.event_name or 'none, do not name one'}",
        f"Kind of event: {KIND_WORDS.get(f.event_kind, 'unknown')}",
        f"Year: {f.year or 'unknown, do not give one'}",
        f"City: {f.city or 'none, do not name a city'}",
        f"Credit handles: {' '.join(f.handles) or 'none, identify no one'}",
        f"What the sorter saw: {f.summary or 'nothing recorded'}",
    ])


class ClaudeWriter:
    def __init__(self, conn: sqlite3.Connection, *, agent: str = "seo", client=None, model: Optional[str] = None):
        self.conn = conn
        self.agent = agent
        self.model = model or config.getenv("SEO_MODEL") or DEFAULT_MODEL
        if client is None:
            import anthropic  # here, so the template path needs neither key nor SDK
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        self.client = client

    def write(self, f: PhotoFacts) -> Optional[dict]:
        """Claude's raw answer as a dict (with '_model'), or None when it refused or answered nothing readable."""
        if spend.cap_reached(self.conn):
            raise CapReached("monthly AI spend cap reached")
        common = dict(model=self.model, system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": user_text(f)}])
        if self.model.startswith("claude-opus"):
            response = self.client.beta.messages.create(
                **common, max_tokens=4000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
        else:
            response = self.client.messages.create(
                **common, max_tokens=1500, output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
        u = response.usage
        answered = getattr(response, "model", None) or self.model
        spend.record(self.conn, self.agent, answered, int(u.input_tokens or 0), int(u.output_tokens or 0),
                     f"seo text photo {f.photo_id}")
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        data["_model"] = answered
        return data


def from_claude(raw: dict, f: PhotoFacts) -> dict:
    def clean(key):
        value = raw.get(key)
        return " ".join(tidy(value).split()) if isinstance(value, str) else ""
    return {"title": clean("title"), "alt": clean("alt"), "description": clean("description"),
            "keywords": merge_keywords(raw.get("keywords"), f)}


def compose(f: PhotoFacts, writer: Optional[ClaudeWriter]) -> tuple[dict, str, list[str]]:
    """(fields, model, why Claude's answer was not used). Raises CapReached before a paid call over the cap."""
    why: list[str] = []
    if writer is not None:
        raw = writer.write(f)
        if raw is None:
            why = ["the model refused or gave nothing readable"]
        else:
            fields = from_claude(raw, f)
            why = problems(fields, f)
            if not why:
                return fields, raw["_model"], []
    for facts in (f, replace(f, event_name="", city="", handles=())):
        fields = template(facts)
        if not problems(fields, facts):
            return fields, "template", why
    raise TemplateRefused(f"photo {f.photo_id}: even the plain template does not pass the checks")


# ------------------------------------------------------------------ storing

def save(conn: sqlite3.Connection, photo_id: int, fields: dict, model: str, facts: Optional[PhotoFacts] = None) -> str:
    """Insert or update the row; the slug of an existing row never changes and a row Chris edited is left alone."""
    existing = db.one(conn, "SELECT slug, edited_at FROM photo_seo WHERE photo_id=?", (photo_id,))
    if existing is not None and existing["edited_at"]:
        return existing["slug"]
    slug = existing["slug"] if existing is not None else None
    if slug is None:
        f = facts or gather(conn, photo_id)
        slug = unique_slug(conn, slug_base(f) if f else "", photo_id)
    conn.execute("INSERT INTO photo_seo (photo_id, slug, title, alt, description, keywords, model, written_at) "
                 "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET title=excluded.title, alt=excluded.alt, "
                 "description=excluded.description, keywords=excluded.keywords, model=excluded.model, "
                 "written_at=excluded.written_at WHERE photo_seo.edited_at IS NULL",
                 (photo_id, slug, fields["title"], fields["alt"], fields["description"], json.dumps(fields["keywords"]),
                  model, db.utcnow()))
    return slug


def wanted_photos(conn: sqlite3.Connection) -> tuple[list[int], int]:
    """(photo ids to have text, how many queued photos were left out because they are no longer usable)."""
    eligible = [r["photo_id"] for r in db.rows(conn, "SELECT photo_id FROM final_checks ORDER BY photo_id")
                if eligibility.is_eligible(conn, r["photo_id"])[0]]
    seen = set(eligible)
    queued, left_out = [], 0
    for r in db.rows(conn, "SELECT photo_ids FROM content_queue WHERE status != 'rejected' ORDER BY id DESC"):
        for pid in _ids(r["photo_ids"]):
            if pid in seen:
                continue
            seen.add(pid)
            if eligibility.is_candidate(conn, pid)[0]:
                queued.append(pid)
            else:
                left_out += 1
    return eligible + queued, left_out


def pick_writer(conn: sqlite3.Connection, *, dry_run: bool, client=None, agent: str = "seo") -> Optional[ClaudeWriter]:
    """None (the template) in dry run, with AI_MODEL=template, or with no key and no client."""
    if dry_run or (config.getenv("AI_MODEL") or "").lower() == "template":
        return None
    if client is not None:
        return ClaudeWriter(conn, agent=agent, client=client)
    if secrets.get_secret("ANTHROPIC_API_KEY"):
        return ClaudeWriter(conn, agent=agent)
    return None


def write_all(conn: sqlite3.Connection, cfg: Optional[config.Config] = None, *, dry_run: bool = True, client=None,
              agent: str = "seo", limit: Optional[int] = None) -> dict:
    cfg = cfg or config.get_config()
    if limit is None:
        try:
            limit = int(config.getenv("SEO_PER_RUN", str(PER_RUN_DEFAULT)) or PER_RUN_DEFAULT)
        except ValueError:
            limit = PER_RUN_DEFAULT
    writer = pick_writer(conn, dry_run=dry_run, client=client, agent=agent)
    ids, left_out = wanted_photos(conn)
    stats = {"wanted": len(ids), "written": 0, "claude": 0, "template": 0, "fell_back": 0, "kept": 0, "edited": 0,
             "left_out": left_out, "unsorted": 0, "refused": 0, "stopped": "", "model": writer.model if writer else "template"}
    for pid in ids:
        row = db.one(conn, "SELECT model, edited_at FROM photo_seo WHERE photo_id=?", (pid,))
        if row is not None and row["edited_at"]:
            stats["edited"] += 1
            continue
        if row is not None and (row["model"] != "template" or writer is None):
            stats["kept"] += 1
            continue
        if stats["written"] >= limit:
            stats["stopped"] = stats["stopped"] or f"the {limit} per run limit"
            break
        f = gather(conn, pid, cfg)
        if f is None:
            stats["unsorted"] += 1
            continue
        fields = None
        try:
            fields, model, why = compose(f, writer)
        except TemplateRefused:
            stats["refused"] += 1
            continue
        except CapReached:
            stats["stopped"] = "monthly AI spend cap reached; the rest got the template"
            writer = None
        except Exception as e:  # noqa: BLE001  the API failing must not stop the run: the template stands in
            runner.record_error(conn, agent, "seo_text", f"photo {pid}: {type(e).__name__}: {e}")
            stats["stopped"] = f"the writer failed ({type(e).__name__}); the rest got the template"
            writer = None
        if fields is None:
            if row is not None:            # it already has template text; nothing better to give it
                stats["kept"] += 1
                continue
            try:
                fields, model, why = compose(f, None)
            except TemplateRefused:
                stats["refused"] += 1
                continue
        save(conn, pid, fields, model, f)
        stats["written"] += 1
        stats["template" if model == "template" else "claude"] += 1
        stats["fell_back"] += int(bool(why))
    return stats


def edit(conn: sqlite3.Connection, photo_id: int, *, alt: str, title: Optional[str] = None,
         description: Optional[str] = None) -> Optional[str]:
    """Chris's correction from the dashboard. None when stored; else why not, in plain words.
    His words pass the same hard rules (copy rules, length, no address, credited handles only);
    only the name guess is left out, because he knows who is in his photos."""
    row = db.one(conn, "SELECT * FROM photo_seo WHERE photo_id=?", (photo_id,))
    if row is None:
        return "There is no search text for this photo yet."
    f = gather(conn, photo_id)
    if f is None:
        return "This photo has not been sorted, so its text cannot be checked."
    fields = {"title": (title if title is not None and title.strip() else row["title"]).strip(),
              "alt": (alt or "").strip(),
              "description": (description if description is not None and description.strip() else row["description"]).strip(),
              "keywords": json.loads(row["keywords"] or "[]")}
    why = problems(fields, f, guess_names=False)
    if why:
        return why[0][0].upper() + why[0][1:] + "."
    conn.execute("UPDATE photo_seo SET title=?, alt=?, description=?, edited_at=? WHERE photo_id=?",
                 (fields["title"], fields["alt"], fields["description"], db.utcnow(), photo_id))
    return None
