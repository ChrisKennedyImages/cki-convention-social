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

Its notes ride on the draft for Chris to read. Dry run: no paid look; the
draft says so. A refusal or a missing answer never blocks: the draft goes to
Chris marked "not reviewed".
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
from ..core import config, secrets

MODEL = "claude-opus-5"
MAX_REDOS = 2
EDGE = 900

SYSTEM = """You are the art director for a photography company's social posts. You see the same post rendered at two aspect ratios.
Judge only what you see, as a picky photo editor would:
1. Crop: is anyone's head, face, hands or feet cut awkwardly, or is the subject jammed against an edge?
2. Placement: is the main subject well placed for the format?
3. Legibility: can the small text and the logo at the bottom be read against the photo?
4. Quality: is the photo sharp where it matters and well exposed?
5. Brand: does it look clean and deliberate?
verdict: "pass" if it is ready; "redo" if a different crop would fix it (give focus_x and focus_y between 0 and 1: the point of the original photo the crop should center on); "reject" if the photo itself is not good enough.
notes: one or two short plain sentences for the photographer. No dashes. Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "redo", "reject"]},
        "focus_x": {"type": "number"},
        "focus_y": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["verdict", "focus_x", "focus_y", "notes"],
    "additionalProperties": False,
}


def _block(path: Path) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((EDGE, EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def look(conn: sqlite3.Connection, paths: list[Path], *, client=None, agent: str = "art_director") -> Optional[dict]:
    """One look at the rendered designs. None when there is no key, the cap is reached, or the model declined."""
    if spend.cap_reached(conn):
        return None
    if client is None:
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    model = config.getenv("ART_MODEL") or MODEL
    content = [_block(p) for p in paths] + [{"type": "text", "text": "Review this post."}]
    response = client.beta.messages.create(
        model=model, max_tokens=3000, betas=[claude_mod.FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}])
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or model, int(u.input_tokens or 0), int(u.output_tokens or 0), "art review")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    data = json.loads(text)
    data["notes"] = claude_mod.tidy(data.get("notes") or "")
    data["focus_x"] = max(0.0, min(1.0, float(data.get("focus_x") or 0.5)))
    data["focus_y"] = max(0.0, min(1.0, float(data.get("focus_y") or 0.42)))
    return data


def direct(conn: sqlite3.Connection, render: Callable[[tuple], dict], *, dry_run: bool, client=None,
           agent: str = "content") -> tuple[dict, dict]:
    """Render, look, and rework the crop until it passes (or MAX_REDOS). `render(focus)` returns
    {aspect: [path]}. Returns (render_paths, verdict)."""
    focus = (0.5, 0.42)
    paths = render(focus)
    if dry_run:
        return paths, {"verdict": "not reviewed", "notes": "Dry run: the art director did not look.", "rounds": 0}
    rounds, last = 0, None
    while True:
        files = [Path(p) for ps in paths.values() for p in ps]
        verdict = look(conn, files, client=client, agent=agent)
        rounds += 1
        if verdict is None:
            out = last or {"verdict": "not reviewed", "notes": "The art director could not look this time."}
            return paths, {**out, "rounds": rounds}
        last = verdict
        if verdict["verdict"] != "redo" or rounds > MAX_REDOS:
            return paths, {**verdict, "rounds": rounds, "focus": list(focus)}
        focus = (verdict["focus_x"], verdict["focus_y"])
        paths = render(focus)


def run(ctx) -> str:
    return "the art director works inside the content agent's daily draft"


if __name__ == "__main__":
    from ..core import runner
    runner.main_for("art_director", run)
