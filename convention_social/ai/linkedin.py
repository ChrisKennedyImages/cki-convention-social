"""The LinkedIn caption, in Chris's voice.

Chris, 2026-11-01 evening, on the first LinkedIn captions (three first-person paragraphs each): "this is way to fake of a
comment above. I need it to be in my voice and less robotic and I don't explain shots.... It's too much, way too much."
Shown six example lines in three styles he chose "Mix all three", "LinkedIn only for now" (Instagram, Facebook and
Pinterest captions stay as they are) and "Photo alone". On the first three real drafts: "The 3rd one is closest - but the
others sound like a robot. Keep the briefness, but more of a human interest grab." He wrote the first two over himself
("she had the whole room on the edge of their seat by the first sentence. And we caught the moment she hooked them";
"the room goes quiet, he takes the podium, we already got the shot and you've already got the promo") and asked for flow.

The caption: one to three short sentences that build, a human-interest hook about the moment and the people, "we",
never "brothers" (Chris, 2026-11-01: "Never use "brothers" use "we". It's fine on the website, but I don't want it to be
a part of posts"), present tense where it fits; then the company's address, then two hashtags. Never how the photo was made
(no light, angles, positions, bursts, gear or technique). LinkedIn is outside the search plan's rules (no search phrase,
no place words, no paragraphs). The copy gate every caption shares still applies (ai/copy_rules.py; on LinkedIn only, a
light hint at how fast the photos come is allowed, "Yes, on LinkedIn only"). The three styles rotate round robin across
drafts and the draft page says which. The writer gets his own voice as examples (his three lines, smoothed, and three of
his real old posts) and may use three facts about him, nothing else. The fallback is one of the lines he approved, in
the draft's style.
"""
from __future__ import annotations

import re
from typing import Optional

STYLES = ("moment", "client", "personal")
STYLE_WORDS = {"moment": "the moment", "client": "the moment and the client", "personal": "a personal line"}
ASKS = {
    "moment": "the moment and the people in it, one to three short sentences that build, as he would say it out loud",
    "client": "the moment, then what the client already has from it, light and human (never the steps, never how it works)",
    "personal": "a personal line, from more than thirty years of doing this, still at it",
}
# his lines, smoothed, which he has seen (the third is the one he liked most)
EXAMPLES = {
    "moment": ("One sentence in and she had the whole room on the edge of their seats. We caught the exact moment she hooked them.",),
    "client": ("The room goes quiet. He steps up to the podium. We've already got the shot, and you've already got the promo.",),
    "personal": ("Thirty some years in and the hallway is still where the good stuff happens. We keep showing up for it.",),
}
# his real old LinkedIn posts, how he writes
HIS_POSTS = ("Looking for a commercial Architecture photographer? #photographer #architecture",
             "You never know when the right moment will come!",
             "An incredible Art Teacher getting ready to take the stage. Event Photography.")
FACTS = "Washington, DC and nationwide; more than thirty years of this"      # the personal line only; never brothers, say we
HASHTAGS = ("#eventphotography", "#conferencephotography")
MAX_SENTENCES = 3
MAX_CHARS = 220              # short
# how a photo was made: light, angles, positions, bursts, gear, technique; he never explains a shot
TECHNIQUE = re.compile(
    r"\b(?:light(?:ing|s)?|lit|backlit|downlight|wash|angles?|lens(?:es)?|shutter|bursts?|exposure|iso|aperture|f/\d|focal|\d+ ?mm"
    r"|tripod|flash|bokeh|depth of field|composition|composed|cropp?(?:ed|ing)?|frames?|framed|framing|shot (?:from|this|it|low|wide|at)"
    r"|i shot|shooting|wide open|stopped down|separation|positions?|positioned|low and|from the (?:house|floor|back|side|wings))\b",
    re.IGNORECASE)
# the years belong to the personal line only: on a feed every post would otherwise say them (2026-11-01)
YEARS = re.compile(r"\b(?:thirty|three decades|decades?|years)\b", re.IGNORECASE)
HASHTAG = re.compile(r"(?<!\w)#\w+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# the fallback: lines he approved on 2026-11-01, the stage ones where the photo is a stage
FALLBACK = {
    "moment": {"stage": "Some speakers just own the room!", "": "Another great one in the books."},
    "client": {"stage": "Good room, good speaker, good day. If you've got a conference coming up, let's talk.",
               "": "Good room, good people, good day. If you've got an event coming up, let's talk."},
    "personal": {"stage": "Over thirty years of doing this and moments like this still never get old.",
                 "": "Thirty some years in and the hallway is still where the good stuff happens. We keep showing up for it."},
}


def next_style(last: Optional[str]) -> str:
    """Round robin: the style after the last draft's, so no two LinkedIn captions in a row read the same way."""
    if last not in STYLES:
        return STYLES[0]
    return STYLES[(STYLES.index(last) + 1) % len(STYLES)]


def prompt_lines(style: str) -> list[str]:
    """What the writer is told for the LinkedIn caption: his voice, this draft's style, the few facts it may use."""
    style = style if style in STYLES else STYLES[0]
    return [
        f"LinkedIn, on the photographer's own profile, in his own words. This time: {ASKS[style]}. Brief: one to three short "
        "sentences that build, with a human-interest hook about the moment and the people. Say \"we\", never brother or brothers, in "
        "the present tense where it fits. No hashtags, no link, no quote ask. Never say how the photo was made (no light, angles, "
        "positions, bursts, gear or technique).",
        (f"The only facts you may use about him: {FACTS}. Nothing else about him or the company." if style == "personal" else
         "Say nothing about him or the company: not the years, not where he is based; stay on the moment and the people in it."),
        "How he writes, from his own posts: " + " | ".join(HIS_POSTS),
        "His line for this style, which he approved: " + " | ".join(EXAMPLES[style]) + ". Write a fresh one of your own in that "
        "voice, with that flow, never a copy.",
    ]


def words_of(text: str) -> str:
    """His words alone: whatever hashtags or address the writer added are taken off (finish puts them back where they go)."""
    return " ".join(HASHTAG.sub(" ", text or "").replace("\n", " ").split())


def finish(text: str, domain: str) -> str:
    """The caption as it posts: his words, then the company's address on its own line, then the two hashtags."""
    words = words_of(text)
    if domain:
        words = " ".join(words.replace(f"https://{domain}", " ").replace(f"{domain}/book", " ").replace(domain, " ").split())
    return "\n\n".join(x for x in (words, domain, " ".join(HASHTAGS)) if x)


def words_posted(caption: str) -> str:
    """His words out of a finished caption (the first paragraph)."""
    return (caption or "").split("\n\n", 1)[0].strip()


def problems(caption: str, style: str = "") -> list[str]:
    """What a LinkedIn caption misses of his rules: too long, too many sentences, it explains the shot, or (any style but
    the personal line) it mentions the years."""
    words = words_posted(caption)
    out = []
    m = YEARS.search(words) if style != "personal" else None
    if m:
        out.append(f"the LinkedIn caption mentions the years ({m.group(0)!r}); only the personal line does")
    sentences = [s for s in SENTENCE_END.split(words) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        out.append(f"the LinkedIn caption runs to {len(sentences)} sentences; one to three short ones")
    if len(words) > MAX_CHARS:
        out.append(f"the LinkedIn caption is over {MAX_CHARS} characters; one to three short sentences")
    m = TECHNIQUE.search(words)
    if m:
        out.append(f"the LinkedIn caption explains the shot ({m.group(0)!r}); he never does")
    return out


def template(style: str, room: str = "") -> str:
    """The fallback, one of his approved lines in the draft's style: the stage ones where the photo is a stage."""
    lines = FALLBACK.get(style, FALLBACK["moment"])
    return lines["stage" if room == "stage" else ""]
