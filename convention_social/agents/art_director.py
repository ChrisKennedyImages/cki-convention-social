"""Art director: looks at every rendered post before Chris does, and reworks what is off.

Inside the daily draft (content.py calls direct()), Claude looks at the
rendered designs, small, side by side, and judges them the way a photo editor
would: is a head, a hand or a face cut by the crop, is the subject placed
well, can the type and the credit be read against the photo, is the photo
sharp where it matters, does it look like the brand. The verdict is one of:

  pass    goes to Chris's queue as it is
  redo    the crop is the problem: it gives a new focus point, the post is
          rendered again and looked at again (at most MAX_REDOS times)
  reject  the photo itself does not hold up: the draft is turned back with
          the reason, and the content agent tries the next photo

Before it looks it is told what it is looking at (the brief): the design,
and for a reel its style and what the style puts on the frame on purpose
(render/reels3d.brief). Post 33 (2026-10-24), a Loop reel, was turned back
for "a large dark circular artifact over the faces": the loop's own glass,
which Chris approved as the style. Told, the director passes the glass and
still turns back a cut face, a soft or dark frame, a wrong photo.

Its notes, and its line on each picture, ride on the draft for Chris to
read. Dry run: no paid look; the draft says so. A refusal or a missing
answer never blocks: the draft goes to Chris marked "not reviewed".
"""
from __future__ import annotations

import base64
import io
import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from ..ai import claude as claude_mod
from ..ai import spend
from ..core import config, db, runner, secrets
from ..render.motion import LINKEDIN_CARD

MODEL = "claude-opus-5"
MAX_REDOS = 2
EDGE = 900
STILLS = {".jpg", ".jpeg", ".png"}   # a reel is judged by its cover and stills, never the mp4 itself

SYSTEM = """You are the art director for a photography company's social posts. You see the post as rendered, and the message says what you are looking at: the design, and for a reel its style and what that style puts on the frame on purpose. What the message says the design does is never a fault; nothing else is the design, so do not excuse a soft or dark photo as a transition or an effect. A fault in a photo is one wherever it shows.
Look at every picture in turn, as a picky photo editor would:
1. Crop: is anyone's head, face, hands or feet cut awkwardly, or is the subject jammed against an edge?
2. Placement: is the main subject well placed for the format?
3. Legibility: can the small text and the logo at the bottom be read against the photo?
4. Quality: is the photo sharp where it matters and well exposed?
5. Brand: does it look clean and deliberate?
pictures: one short line per picture, in the order given, saying what it shows and any fault in it.
verdict: for the weakest picture. "pass" if it is ready; "redo" if a different crop would fix it (give focus_x and focus_y between 0 and 1: the point of the original photo the crop should center on); "reject" if a photo itself is not good enough.
notes: one or two short plain sentences for the photographer, naming the picture a fault is in. No dashes. Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "pictures": {"type": "array", "items": {"type": "string"}},    # first, so every picture is looked at before the verdict
        "verdict": {"type": "string", "enum": ["pass", "redo", "reject"]},
        "focus_x": {"type": "number"},
        "focus_y": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["pictures", "verdict", "focus_x", "focus_y", "notes"],
    "additionalProperties": False,
}


def _block(image) -> dict:
    """`image`: a rendered file's path, or a photo's own bytes."""
    with Image.open(io.BytesIO(image) if isinstance(image, (bytes, bytearray)) else image) as im:
        im = im.convert("RGB")
        im.thumbnail((EDGE, EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def look(conn: sqlite3.Connection, paths: list[Path], *, brief: str, client=None, agent: str = "art_director") -> Optional[dict]:
    """One look at the rendered designs, told by `brief` what they are. None when there is no key, the cap is
    reached, or the model declined."""
    if spend.cap_reached(conn):
        return None
    if client is None:
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    model = config.getenv("ART_MODEL") or MODEL
    held = spend.reserve(conn, agent, model)
    if held is None:
        return None
    content = [_block(p) for p in paths] + [{"type": "text", "text": f"{brief}\n\nReview this post."}]
    try:
        response = client.beta.messages.create(
            model=model, max_tokens=3000, betas=[claude_mod.FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}])
    except Exception as e:  # noqa: BLE001  the API or the network: the draft goes to Chris not reviewed, said once, never a dead run
        spend.release(conn, held)
        runner.record_error_once(conn, agent, "art_director",
                                 f"The art director could not look ({type(e).__name__}: {e}); the draft goes to Chris not reviewed.")
        return None
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or model, int(u.input_tokens or 0), int(u.output_tokens or 0), "art review",
                 reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    data = json.loads(text)
    data["pictures"] = [claude_mod.tidy(line) for line in data["pictures"]]
    data["notes"] = claude_mod.tidy(data.get("notes") or "")
    data["focus_x"] = max(0.0, min(1.0, float(data.get("focus_x") or 0.5)))
    data["focus_y"] = max(0.0, min(1.0, float(data.get("focus_y") or 0.42)))
    return data


# Chris, 2026-11-01: "LinkedIn posts avoid photos whose main subject is a recognisable public figure; Instagram stays as it
# is." The art director judges a photo once, by looking, never by a name: the model is told to name no one, and nothing
# here compares names. The judgement is stored on the photo (photos.public_figure) and never asked again.
FIGURE_SYSTEM = """You look at one photograph for a photography company and answer one question: is the main subject of this photograph a recognisable public figure, someone a general audience would know by sight (a politician, a celebrity, a broadcaster, a well-known executive)? The main subject is the person the photograph is of, by its composition, not someone in the background or in a crowd. Judge only by what the picture shows. Never write a name, a title or who you think anyone is. Return JSON only."""
FIGURE_SCHEMA = {"type": "object", "properties": {"public_figure": {"type": "boolean"}}, "required": ["public_figure"],
                 "additionalProperties": False}
FIGURE_SKIP = "the photo's main subject is a recognisable public figure; LinkedIn posts avoid those (Chris, 2026-11-01)"
FIGURE_WAIT = "the photo has not been judged for a public figure yet; LinkedIn waits (the next live run with budget judges it)"


def public_figure(conn: sqlite3.Connection, photo_id: int, image, *, client=None, agent: str = "content") -> Optional[bool]:
    """Is this photo's main subject a recognisable public figure? The stored judgement when the photo has one; else one look
    through the till, stored on the photo with the time and never asked again. `image`: the photo's bytes or its file.
    None when it is not judged and cannot be now (no key, the cap reached, a refusal, the API): then the photo does not go
    to LinkedIn until it is (agents/publisher.linkedin_hold)."""
    row = db.one(conn, "SELECT public_figure FROM photos WHERE id=?", (photo_id,))
    if row is None:
        return None
    if row["public_figure"] is not None:
        return bool(row["public_figure"])
    if spend.cap_reached(conn):
        return None
    if client is None:
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    model = config.getenv("ART_MODEL") or MODEL
    held = spend.reserve(conn, agent, model)
    if held is None:
        return None
    try:
        response = client.beta.messages.create(
            model=model, max_tokens=1500, betas=[claude_mod.FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": FIGURE_SCHEMA}},
            system=[{"type": "text", "text": FIGURE_SYSTEM}],
            messages=[{"role": "user", "content": [_block(image), {"type": "text", "text": "Is the main subject of this photograph a recognisable public figure?"}]}])
    except Exception as e:  # noqa: BLE001  the API or the network: not judged, said once; LinkedIn waits
        spend.release(conn, held)
        runner.record_error_once(conn, agent, "public_figure",
                                 f"The public figure check could not run ({type(e).__name__}: {e}); LinkedIn waits for it.")
        return None
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or model, int(u.input_tokens or 0), int(u.output_tokens or 0),
                 "public figure", reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    answer = json.loads(text).get("public_figure") if text.strip().startswith("{") else None
    if not isinstance(answer, bool):
        return None                      # not the answer asked for: not judged, nothing stored
    verdict = answer
    conn.execute("UPDATE photos SET public_figure=?, public_figure_at=? WHERE id=? AND public_figure IS NULL",
                 (int(verdict), db.utcnow(), photo_id))
    return verdict


def direct(conn: sqlite3.Connection, render: Callable[[tuple], dict], *, brief: Callable[[dict], str], dry_run: bool,
           client=None, agent: str = "content", allow_redo: bool = True, max_files: Optional[int] = None) -> tuple[dict, dict]:
    """Render, look, and rework the crop until it passes (or MAX_REDOS). `render(focus)` returns
    {aspect: [path]}; `brief(paths)` says what those files are (the design; a reel's style and what it
    puts on the frame on purpose), asked after the render because a reel that could not be made is a
    carousel. Returns (render_paths, verdict). A design built from several photos has no single crop
    to move (allow_redo False): a "redo" there passes with its notes for Chris. `max_files` caps how
    many of the rendered files are looked at (a carousel's first slides)."""
    focus = (0.5, 0.42)
    paths = render(focus)
    if dry_run:
        return paths, {"verdict": "not reviewed", "notes": "Dry run: the art director did not look.", "rounds": 0}
    rounds, last = 0, None
    while True:
        # the LinkedIn card is the hero card again (the 4:5 or the 2:3 shows the same crop): not looked at twice
        files = [Path(p) for key, ps in paths.items() if key != LINKEDIN_CARD for p in ps if Path(p).suffix.lower() in STILLS][:max_files]
        verdict = look(conn, files, brief=brief(paths), client=client, agent=agent)
        rounds += 1
        if verdict is None:
            out = last or {"verdict": "not reviewed", "notes": "The art director could not look this time."}
            return paths, {**out, "rounds": rounds}
        last = verdict
        if verdict["verdict"] == "redo" and not allow_redo:
            return paths, {**verdict, "verdict": "pass", "rounds": rounds}
        if verdict["verdict"] != "redo" or rounds > MAX_REDOS:
            return paths, {**verdict, "rounds": rounds, "focus": list(focus)}
        focus = (verdict["focus_x"], verdict["focus_y"])
        paths = render(focus)


def run(ctx) -> str:
    return "the art director works inside the content agent's daily draft"


if __name__ == "__main__":
    from ..core import runner
    runner.main_for("art_director", run)
