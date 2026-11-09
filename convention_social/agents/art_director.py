"""Art director: looks at every rendered post before Chris does, and reworks what is off in the design.

Inside the daily draft (content.py calls direct()), Claude looks at the rendered designs, small, side by side, and judges
the design that carries the photos: does each word name what its own photo shows, is a head, a hand or a face cut by the
crop, is the subject placed well, can the type and the credit be read against the photo, is the look executed as
designed. It never judges the photos themselves. Chris, 2026-11-08: "NOTHING IS PRIVATE because I have hand approved
every photo! No one can override MY approvals and that is a law"; then "Yes, override everything". Every photo here is
one he used, so a dark, soft or black and white photo, its subject or its quality is never a reason to turn a post
back, and neither is a frame the look leaves empty or white on purpose. The verdict is one of:

  pass    goes to Chris's queue as it is
  redo    the crop is the problem: it gives a new focus point, the post is
          rendered again and looked at again (at most MAX_REDOS times)
  reject  the design does not work with these photos as arranged and no crop
          fixes it (a word that does not name its photo, the look not executed
          as designed): the draft is turned back with the reason, and the
          content agent draws the day again in another arrangement

Before it looks it is told what it is looking at (the brief): the design, and for a reel its style and what the style
puts on the frame on purpose (render/reels3d.brief, render/reel_looks.brief). Post 33 (2026-10-24), a Loop reel, was
turned back for "a large dark circular artifact over the faces": the loop's own glass, which Chris approved as the
style; the Darkroom reel three times for "an empty white cell in position 1", the look's fogged first frame. And before
everything it reads the house brief (house_brief.py): the company, its labels and that his approval is final.

Its notes, and its line on each picture, ride on the draft for Chris to read. Dry run: no paid look; the draft says
so. A refusal or a missing answer never blocks: the draft goes to Chris marked "not reviewed".
"""
from __future__ import annotations

import base64
import io
import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .. import house_brief
from ..ai import claude as claude_mod
from ..ai import spend
from ..core import config, runner, secrets
from ..render.photo import LINKEDIN_PHOTO

MODEL = "claude-opus-5"
MAX_REDOS = 2
EDGE = 900
STILLS = {".jpg", ".jpeg", ".png"}   # a reel is judged by its cover and stills, never the mp4 itself

SYSTEM = """You are the art director for the company's social posts. You see the post as rendered, and the message says what you are looking at: the design, and for a reel its style and what that style puts on the frame on purpose. What the message says the design does is never a fault.
Every photo in the post is one Chris approved by hand, and his approval is final: you never rule an approved photo unfit, and you never turn a post back because of a photo itself, its darkness, black and white, sharpness, exposure, subject or quality, or for a frame the design leaves empty or white on purpose. You judge the design that carries the photos, every picture in turn:
1. Words: does each word on the post name what its own photo plainly shows?
2. Crop: is anyone's head, face, hands or feet cut awkwardly, or is the subject jammed against an edge?
3. Placement: is the main subject well placed for the format?
4. Legibility: can the words, the small text and the logo at the bottom be read against the photo?
5. The look: is it executed as designed, clean and deliberate?
pictures: one short line per picture, in the order given, saying what it shows and any fault of the design in it.
verdict: for the weakest picture. "pass" if it is ready; "redo" if a different crop would fix it (give focus_x and focus_y between 0 and 1: the point of the original photo the crop should center on); "reject" only when the design does not work with these photos as arranged and no crop fixes it (a word that does not name its own photo, the look not executed as designed), so the post is drawn again in another arrangement. Never "reject" for a photo itself.
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
            system=house_brief.system(SYSTEM, cache=True),
            messages=[{"role": "user", "content": content}])
    except Exception as e:  # noqa: BLE001  the API or the network: the draft goes to Chris not reviewed, said once, never a dead run
        spend.release(conn, held)
        runner.record_error_once(conn, agent, "art_director",
                                 f"The art director could not look ({type(e).__name__}: {e}); the draft goes to Chris not reviewed.")
        return None
    spend.record_response(conn, agent, response, model, "art review", reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    data = json.loads(text)
    data["pictures"] = [claude_mod.tidy(line) for line in data["pictures"]]
    data["notes"] = claude_mod.tidy(data.get("notes") or "")
    data["focus_x"] = max(0.0, min(1.0, float(data.get("focus_x") or 0.5)))
    data["focus_y"] = max(0.0, min(1.0, float(data.get("focus_y") or 0.42)))
    return data


JUDGE_SYSTEM = """You look at one photograph for the company and answer the one question you are asked, judging only by what the picture shows. Never write a name, a title, who anyone is, or which organization it is. Return JSON only."""


SUBJECT_QUESTION = ("Is the one main person in this photograph clearly a woman, clearly a man, or is it unclear (no single main person, "
                    "a group, a back view, or you cannot tell)? Answer woman, man or unclear.")
SUBJECT_SCHEMA = {"type": "object", "properties": {"subject": {"type": "string", "enum": ["woman", "man", "unclear"]}},
                  "required": ["subject"], "additionalProperties": False}


def _ask(conn: sqlite3.Connection, image, question: str, schema: dict, *, client=None, agent: str, what: str) -> Optional[dict]:
    """One look at one photo with one question, through the till: the answer as JSON, or None when it cannot be had now (no
    key, the cap reached, a refusal, the API). The model is told to name no one and no organization."""
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
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=house_brief.system(JUDGE_SYSTEM),
            messages=[{"role": "user", "content": [_block(image), {"type": "text", "text": question}]}])
    except Exception as e:  # noqa: BLE001  the API or the network: no answer, said once
        spend.release(conn, held)
        runner.record_error_once(conn, agent, "photo_judgement", f"The {what} could not run ({type(e).__name__}: {e}).")
        return None
    spend.record_response(conn, agent, response, model, what, reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text or not text.strip().startswith("{"):
        return None
    return json.loads(text)


def subject_of(conn: sqlite3.Connection, image, *, client=None, agent: str = "content") -> Optional[str]:
    """The pronoun gate's look (Chris, 2026-11-01: "I just can't have you mixing up captions that say he when it's a she"):
    "woman", "man" or "unclear" for the one main person in the photo, judged by looking, naming no one; None when the look
    could not be had. Asked per caption, never stored: it guards the words, not the photo."""
    data = _ask(conn, image, SUBJECT_QUESTION, SUBJECT_SCHEMA, client=client, agent=agent, what="pronoun check")
    answer = data.get("subject") if data else None
    return answer if answer in ("woman", "man", "unclear") else None


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
        # the LinkedIn photo is the hero as shot, which the cards already show: not looked at twice
        files = [Path(p) for key, ps in paths.items() if key != LINKEDIN_PHOTO for p in ps if Path(p).suffix.lower() in STILLS][:max_files]
        if not files:                  # no card to judge: the draft goes to LinkedIn alone, the photo as shot (2026-11-02)
            return paths, {"verdict": "not reviewed", "notes": "No card to look at: the photo goes as shot.", "rounds": rounds}
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
