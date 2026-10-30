"""The gate every caption, email and page passes before Chris sees it and again before it leaves.

The prompt asks for these rules; this module enforces them. A block stops
the draft (it goes back to drafts with the reason); nothing here rewrites
words silently except the dash tidy, which ai.claude.tidy already applies.

Blocks:
  price       any money amount, rate or discount (prices are never published)
  dash        an en or em dash, or a spaced hyphen used as a dash
  affiliation "official photographer", "official partner", "sponsored by",
              "affiliated with", "trusted by", "clients include" and the like,
              unless the event is confirmed official (none are, 2026-10-09)
  promise     a claim the suite cannot stand behind ("guaranteed", "#1", "best in")
  names       public copy only (callers pass `names`): the name of an event, the company behind it
              or a person, or any @handle (Chris, 2026-10-11; ai/names.py)
  claims      anything about how the company works that Chris has not stated ("within 24 hours" is his
              stated reply promise, 2026-10-12, and "within the hour" his stated promise for selects when the
              moments are known before the event, 2026-10-30; both pass): what a service
              includes or comes with, what anyone leaves with, how long anything takes, packages,
              turnaround. Chris, 2026-10-11, on a draft that said conference photography "includes
              portraits like this one, shot on site in a few minutes": "Suite wide - NOTHING
              INCLUDES ANYTHING! Don't ever say something you don't know or don't ask me about my
              own company." The facts come from offer.json and him; everything else is a question.
  offer       social copy only (callers pass `social=True`: captions, the cards, the reels): any talk of
              what is offered or what a service is: offer, service, coverage, covered, delivery, face
              match, selfie, "we cover", "your vendors", "every room". Chris, 2026-10-11: "keep to
              specifics and not talk about what is offered or what is a service, specifically in
              captions and social media". A post is about the photo; the rest is between him and the client.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PRICE = re.compile(
    r"(?:[$£€]\s?\d)"                              # $150, £90, €200
    r"|(?:\b\d[\d,.]*\s?(?:usd|dollars?|bucks)\b)"
    r"|(?:\b(?:per|an|a)\s+(?:hour|hr|day|session|image|photo)\b.*\b\d)"
    r"|(?:\b\d+\s?%\s?off\b)|(?:\bdiscount|\bcoupon|\bpromo code|\bsale price|\bstarting at\b|\bstarts at\b|\bonly\s+\$)",
    re.IGNORECASE,
)
DASH = re.compile(r"[‐-―−]|\s-{1,2}\s")
AFFILIATION = re.compile(
    r"\bofficial\s+(?:photographer|photography|partner|sponsor|media|vendor)"
    r"|\bsponsored\s+by\b|\baffiliated\s+with\b|\bin\s+partnership\s+with\b|\bpartnered\s+with\b|\bendorsed\s+by\b"
    r"|\btrusted\s+by\b|\bclients\s+include\b|\bas\s+seen\s+(?:at|in|on)\b|\bhired\s+by\b",
    re.IGNORECASE,
)
PROMISE = re.compile(r"\bguarantee(?:d|s)?\b|#1\b|\bnumber one\b|\bbest in\b|\baward[- ]winning\b", re.IGNORECASE)
CLAIMS = re.compile(
    r"\binclud(?:e|es|ed|ing|ive)\b|\bcomes?\s+with\b|\bcame\s+with\b|\bleaves?\s+with\b|\bleft\s+with\b|\bwalks?\s+away\s+with\b"
    r"|\bpackages?\b|\bbundles?\b|\badd[- ]ons?\b|\bturnaround\b|\bunlimited\b|\b(?:same|next)[- ]day\b"
    r"|\bwithin\s+(?!24\s+hours\b|the\s+hour\b)(?:minutes|hours|an?\s+(?:hour|day|week)|\d+)\b|\bin\s+(?:a\s+few\s+|just\s+|under\s+)?minutes\b",
    re.IGNORECASE,
)
OFFER = re.compile(
    r"\bwe\s+(?:offer|cover|deliver|provide|shoot|photograph|also|do|bring|make)\b|\boffer(?:s|ed|ing|ings)?\b"
    r"|\bour\s+services?\b|\bservices?\b|\bcoverage\b|\bcovered\b|\bdeliver(?:y|ed|s|ing)?\b|\bprovid(?:e|es|ed|ing)\b"
    r"|\bface\s+match\b|\bselfies?\b|\bgets?\s+their\s+(?:photos?|shots?|pictures?)\b"
    r"|\byour\s+(?:vendors|exhibitors|guests|staff|team|attendees|speakers|sponsors)\b|\bevery\s+(?:room|guest|attendee)\b",
    re.IGNORECASE,
)


@dataclass
class Block:
    rule: str
    message: str


@dataclass
class Report:
    blocks: list[Block] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocks

    def as_dict(self) -> dict:
        return {"ok": self.ok, "blocks": [{"rule": b.rule, "message": b.message} for b in self.blocks]}


def check(text: str, *, official: bool = False, allow_price: bool = False, names=None, social: bool = False) -> Report:
    """`allow_price` only for a private quote reply Chris wrote the price into himself; never for public copy.
    `names` (ai/names.public_names) for public copy: no event, company or person is named in it.
    `social` for captions and cards: nothing about what is offered or what a service is."""
    report = Report()
    text = text or ""
    m = None if allow_price else PRICE.search(text)
    if m:
        report.blocks.append(Block("price", f"mentions a price or discount ({m.group(0).strip()!r}); prices are never published"))
    if DASH.search(text):
        report.blocks.append(Block("dash", "uses a dash; use a comma or a period"))
    m = AFFILIATION.search(text)
    if m and not official:
        report.blocks.append(Block("affiliation", f"claims a tie to the event ({m.group(0)!r}) that Chris has not confirmed"))
    m = PROMISE.search(text)
    if m:
        report.blocks.append(Block("promise", f"makes a claim the company cannot back ({m.group(0)!r})"))
    m = CLAIMS.search(text)
    if m:
        report.blocks.append(Block("claims", f"says something about the company Chris has not stated ({m.group(0)!r}); nothing includes "
                                             "anything, and nothing about how the work is done, what comes with it or when"))
    m = OFFER.search(text) if social else None
    if m:
        report.blocks.append(Block("offer", f"talks about what is offered ({m.group(0)!r}); a post keeps to what the photo shows, "
                                            "never a service"))
    if names is not None:
        from .names import mentions
        hit = mentions(text, names)
        if hit:
            report.blocks.append(Block("names", f"names {hit[0]!r}; say what kind of event it was, never which one or who is in it"))
    return report
