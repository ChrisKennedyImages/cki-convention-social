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


def check(text: str, *, official: bool = False) -> Report:
    report = Report()
    text = text or ""
    m = PRICE.search(text)
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
    return report
