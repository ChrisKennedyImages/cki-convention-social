"""The LinkedIn caption, in Chris's voice, gated against drift.

Chris, 2026-11-01, on the first LinkedIn captions: "this is way to fake of a comment above. I need it to be in my voice and
less robotic and I don't explain shots.... It's too much, way too much." On the next: "The 3rd one is closest - but the
others sound like a robot." Then: "Never use "brothers" use "we"." Then: "You're using a lot of innuendo's and silly kid of
wording. Tell it more specifically and more casually written. You're dancing around the "we got the shot and you already
got the promo before the speech ends.... It's written like AI would write it. It's needs to feel personal and human." And
on the lines written in his own rhythm: "Much better! That's great, but gate any drift so you don't steer back to another
tone or voice." "the 1st image is a women which is VERY VERY VERY important not to mess up." "I just can't have you mixing
up captions that say he when it's a she."

His rhythm: plain action beats strung with commas, present tense, then the payoff, "we got it" or "we got the shot",
sometimes "and the client / her team / the attendees already have it ... before ...". Short and casual, contractions fine.
No tag line on the end, no metaphor or innuendo, no reflecting, no I, never brothers, no thirty years, never how the photo
was made. Delivery comes up in some captions, not every one, and says only what the site says (offer.json, instant
delivery): the client or the speaker's team has the photo for promo before the talk ends or the speaker leaves the stage;
attendees get their own photos on their phones while the event is still going, when the organizer picks it. Never the
steps, never face match, badges or selfies, never a price (the shared gate, ai/copy_rules.py). He or she only when the
photo clearly shows one main person and which; a separate look at the photo confirms every gendered pronoun
(agents/art_director.subject_of), else the caption is written again with none. Three styles rotate: the moment alone, the
moment and the client's promo, the moment and the attendees' phones. Two misses fall back to a fixed sentence in his
rhythm, never to another tone. LinkedIn only: Instagram, Facebook and Pinterest are untouched.
"""
from __future__ import annotations

import re
from typing import Optional

STYLES = ("moment", "client", "attendees")
STYLE_WORDS = {"moment": "the moment", "client": "the moment and the client's promo", "attendees": "the moment and the attendees' phones"}
ASKS = {
    "moment": "the beats of the moment, then \"we got it\" or \"we got the shot\", and nothing about delivery",
    "client": "the beats, then \"we got the shot\", and that the client or the speaker's team already had it for promo before the talk was over",
    "attendees": "the beats, then \"we get the shot\", and that the attendees already have theirs on their phones before the session lets out",
}
# his lines, approved on 2026-11-01 ("Much better! That's great"), by style
EXAMPLES = {
    "moment": ("She walks right up to the edge of the stage and the front row's hanging on every word, we got it.",
               "Ceremony starts, the honor guard steps in, the whole crowd goes quiet, we got the shot."),
    "client": ("She had the whole room listening from her first sentence. We got the shot, and her team had it for promo before she even walked off stage.",),
    "attendees": ("Keynote wraps, the whole room's clapping, we get the shot and the attendees already have theirs on their phones before they hit the hallway.",),
}
DELIVERY = ("What you may say about delivery, and only this: the client or the speaker's team has the photo for promo before the talk "
            "ends or before the speaker leaves the stage; attendees get their own photos on their phones while the event is still going, "
            "when the organizer picks it. Never the steps, never how it works, never face match, badges or selfies, never a price.")
HASHTAGS = ("#eventphotography", "#conferencephotography")
MAX_WORDS = 35
MAX_SENTENCES = 3
# the drift gate: what he turned back, so the writer never steers back to it
PAYOFF = re.compile(r"\bwe(?:'ve)? (?:got|get|have|had) (?:it|that|the shot)\b", re.IGNORECASE)
FIRST_PERSON = re.compile(r"\b(?:I|I'm|I'd|I've|I'll|my|me|myself|mine)\b")
METAPHOR = re.compile(r"\b(?:hooked|hooks? them|landed|point land|land it|hits? home|hits? different|nail(?:s|ed) it|killed it|crushed it"
                      r"|magic|electric|on fire|pure gold)\b", re.IGNORECASE)
REFLECTION = re.compile(r"\b(?:still gets? (?:me|us)|never gets old|half the story|the good stuff|you can'?t plan|have to be ready"
                        r"|forget they(?:'re| are) being|tells? (?:me|us) more|that(?:'s| is) (?:where|why|what)|the best part|nothing beats"
                        r"|there(?:'s| is) nothing like|reminds? (?:me|us)|(?:thirty|twenty|forty) (?:some |odd )?years|\w+ decades|years in\b"
                        r"|years of (?:this|doing)|more than \w+ years)\b", re.IGNORECASE)
TAGLINE = re.compile(r"(?:^|[.!?]\s+)(?:love (?:it|when|that|this)|that'?s how it should|that'?s (?:the job|the work|what we do)|what a (?:day|room|moment|night)"
                     r"|still love it|good stuff|never gets old)[^.!?]*[.!?]*\s*$", re.IGNORECASE)
TECHNIQUE = re.compile(
    r"\b(?:light(?:ing|s)?|lit|backlit|downlight|angles?|lens(?:es)?|shutter|bursts?|exposure|iso|aperture|f/\d|focal|\d+ ?mm|tripod"
    r"|flash|bokeh|depth of field|composition|composed|cropp?(?:ed|ing)?|framed|framing|in the (?:same )?frame|shot (?:from|low|wide|at)"
    r"|wide open|stopped down|separation|positioned|from the (?:house|floor|back|side|wings))\b", re.IGNORECASE)
SHE = re.compile(r"\b(?:she|her|hers|herself)\b", re.IGNORECASE)
HE = re.compile(r"\b(?:he|him|his|himself)\b", re.IGNORECASE)
HASHTAG = re.compile(r"(?<!\w)#\w+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# the fallback, a fixed sentence in his rhythm for each style, no he or she, nothing a photo could contradict
FALLBACK = {
    "moment": "Doors open, the room fills up, the speaker steps up, we got the shot.",
    "client": "Talk starts, the room settles in, we got the shot, and the team had it for promo before the talk was over.",
    "attendees": "Session wraps, the room's clapping, we get the shot, and the attendees already have theirs on their phones before they hit the hallway.",
}


def next_style(last: Optional[str]) -> str:
    """Round robin: the style after the last draft's, so no two LinkedIn captions in a row read the same way."""
    if last not in STYLES:
        return STYLES[0]
    return STYLES[(STYLES.index(last) + 1) % len(STYLES)]


def prompt_lines(style: str) -> list[str]:
    """What the writer is told for the LinkedIn caption: his rhythm, this draft's style, his lines for it."""
    style = style if style in STYLES else STYLES[0]
    lines = [
        "LinkedIn, on the photographer's own profile, in his own words and his own rhythm: plain action beats strung with commas, "
        f"present tense, then the payoff, \"we got it\" or \"we got the shot\". This time: {ASKS[style]}. Short and casual, under "
        f"{MAX_WORDS} words, contractions fine. Say we, never I or my, never brothers, no thirty years. No tag line on the end, no "
        "metaphor or innuendo (hooked, landed, hit home), no reflecting (still gets me, half the story, where the good stuff happens), "
        "no hashtags, no link. Never say how the photo was made. Say he or she only when the photo clearly shows one main person and "
        "which; otherwise say the speaker, or no one.",
    ]
    if style != "moment":
        lines.append(DELIVERY)
    lines.append("His lines for this, which he approved: " + " | ".join(EXAMPLES[style]) + " Write a fresh one of your own in exactly "
                 "that rhythm, about this photo, never a copy.")
    return lines


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
    """The drift gate: what a LinkedIn caption misses of his rhythm. Empty when it reads like his."""
    words = words_posted(caption)
    out = []
    if len(words.split()) > MAX_WORDS:
        out.append(f"the LinkedIn caption runs to {len(words.split())} words; under {MAX_WORDS}")
    sentences = [s for s in SENTENCE_END.split(words) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        out.append(f"the LinkedIn caption runs to {len(sentences)} sentences; one to three short ones")
    if not PAYOFF.search(words):
        out.append("the LinkedIn caption has no payoff (\"we got it\", \"we got the shot\"); that is his rhythm")
    m = FIRST_PERSON.search(words)
    if m:
        out.append(f"the LinkedIn caption says {m.group(0)!r}; he says we")
    m = TAGLINE.search(words)
    if m:
        out.append(f"the LinkedIn caption ends on a tag line ({m.group(0).strip()!r}); it ends on the payoff")
    m = METAPHOR.search(words)
    if m:
        out.append(f"the LinkedIn caption reaches for a metaphor ({m.group(0)!r}); he says it plainly")
    m = REFLECTION.search(words)
    if m:
        out.append(f"the LinkedIn caption reflects ({m.group(0)!r}); he tells what happened")
    m = TECHNIQUE.search(words)
    if m:
        out.append(f"the LinkedIn caption explains the shot ({m.group(0)!r}); he never does")
    last = sentences[-1].strip() if sentences else ""
    if last.endswith("!") and len(last.split()) <= 6 and not PAYOFF.search(last):
        out.append(f"the LinkedIn caption ends on a tag line ({last!r}); it ends on the payoff")
    return out


def pronouns_in(caption: str) -> set[str]:
    """Which gendered pronouns the caption uses: a subset of {"she", "he"}."""
    words = words_posted(caption)
    return {name for name, rx in (("she", SHE), ("he", HE)) if rx.search(words)}


def pronoun_problems(caption: str, subject: Optional[str]) -> list[str]:
    """The pronoun gate: a he or she stands only when the photo check (art_director.subject_of: woman | man | unclear, None
    when it could not run) clearly says so. Chris: "I just can't have you mixing up captions that say he when it's a she"."""
    used = pronouns_in(caption)
    if not used:
        return []
    allowed = {"woman": "she", "man": "he"}.get(subject or "")
    if allowed and used == {allowed}:
        return []
    return [f"the LinkedIn caption says {' and '.join(sorted(used))} and the photo check "
            f"{'says ' + subject if subject in ('woman', 'man') else 'is not sure' if subject else 'could not run'}; "
            "say the speaker, or no one, with no he or she"]


def template(style: str, room: str = "") -> str:
    """The fallback: a fixed sentence in his rhythm for the draft's style, never another tone."""
    return FALLBACK.get(style, FALLBACK["moment"])
