"""Drafting the reply to a quote request, in Chris's voice. Chris edits and approves; nothing sends on its own.

The draft never names a price: prices are quoted per event by Chris. Where
the price belongs it leaves QUOTE_MARK, and the dashboard refuses to send
while the mark is still in the text, so a reply cannot go out half written.
Claude (claude-opus-5-5) when a key is set and the cap allows; otherwise a
plain template from the offer file.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

from .. import offer
from ..core import config, secrets
from . import copy_rules, spend
from .claude import FALLBACK_BETA, tidy

QUOTE_MARK = "[[QUOTE: write the price and what it covers here, or delete this line]]"
DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM = """You draft a reply email from a photographer to someone who asked for a quote for event photography. Write in his voice: warm, plain, short sentences, commas and periods, never a dash, no exclamation marks in a row, no hype.
Rules:
1. Never write a price, a rate, a discount or a package. Where the price belongs, put this exact line on its own: {mark}
2. Never claim past clients, an official role at any event, awards, or that you have covered their event before.
3. Offer only coverage that appears in the offer list you are given. Never promise anything else.
4. Ask only for details that are missing from their request, using the question list.
5. Sign off with the first name Chris and the company name.
Return JSON only: a subject line and the body.""".format(mark=QUOTE_MARK)

SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
          "required": ["subject", "body"], "additionalProperties": False}


@dataclass
class ReplyDraft:
    subject: str
    body: str
    model: str


def facts(inquiry) -> str:
    o = offer.load()
    asked = offer.coverage_labels(json.loads(inquiry["coverage"] or "[]"))
    return "\n".join([
        f"Company: {o.get('company')} ({o.get('tagline')})",
        f"Offer list: {'; '.join(offer.coverage_labels())}",
        f"Question list: {'; '.join(o.get('quote_questions') or [])}",
        "Their request:",
        f"  name: {inquiry['name']}", f"  organization: {inquiry['organization'] or ''}",
        f"  event: {inquiry['event_name'] or ''} ({inquiry['event_kind'] or 'unknown kind'})",
        f"  dates: {inquiry['start_date'] or '?'} to {inquiry['end_date'] or inquiry['start_date'] or '?'}",
        f"  where: {inquiry['venue'] or ''}, {inquiry['city'] or ''}", f"  attendance: {inquiry['attendance'] or ''}",
        f"  coverage asked for: {', '.join(asked) or 'not said'}", f"  message: {inquiry['message'] or ''}",
    ])


def template_draft(inquiry) -> ReplyDraft:
    o = offer.load()
    first = (inquiry["name"] or "there").split()[0]
    event = inquiry["event_name"] or "your event"
    asked = offer.coverage_labels(json.loads(inquiry["coverage"] or "[]"))
    lines = [f"Hi {first},", "", f"Thank you for asking about photography for {event}."]
    if asked:
        lines += ["", "You asked about: " + "; ".join(asked) + "."]
    lines += ["", QUOTE_MARK, "", "So I can put the quote together, could you tell me:"]
    lines += [f"  {q}." for q in (o.get("quote_questions") or [])[:4]]
    lines += ["", "Chris", f"{o.get('company')}"]
    return ReplyDraft(subject=f"Photography for {event}", body="\n".join(lines), model="template")


def draft(conn: sqlite3.Connection, inquiry, *, client=None, agent: str = "inbox") -> ReplyDraft:
    if client is None and (not secrets.get_secret("ANTHROPIC_API_KEY") or spend.cap_reached(conn)):
        return template_draft(inquiry)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    model = config.getenv("REPLY_MODEL") or DEFAULT_MODEL
    response = client.beta.messages.create(
        model=model, max_tokens=4000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": facts(inquiry)}],
    )
    u = response.usage
    answered = getattr(response, "model", None) or model
    spend.record(conn, agent, answered, int(u.input_tokens or 0), int(u.output_tokens or 0), "reply draft")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return template_draft(inquiry)
    data = json.loads(text)
    body = tidy(data["body"]) if QUOTE_MARK in data["body"] else tidy(data["body"]) + "\n\n" + QUOTE_MARK
    # the drafter's own words must pass every rule, the price rule included; else fall back to the template
    if not copy_rules.check(body.replace(QUOTE_MARK, "")).ok or not copy_rules.check(data["subject"]).ok:
        return template_draft(inquiry)
    return ReplyDraft(subject=tidy(data["subject"]), body=body, model=answered)


def footer() -> str:
    cfg = config.get_config()
    bits = [f"{cfg.brand_name}, a brand of {cfg.legal_name}"]
    if cfg.brand_postal_address:
        bits.append(cfg.brand_postal_address)
    bits.append(cfg.brand_domain)
    return "\n".join(bits)


def ready_to_send(subject: str, body: str) -> Optional[str]:
    """None when the reply may go; else the reason, written for Chris."""
    if QUOTE_MARK in body or "[[QUOTE" in body:
        return "Fill in the quote line, or delete it, before sending."
    if not subject.strip() or not body.strip():
        return "The reply needs a subject and a body."
    report = copy_rules.check(subject + "\n" + body, allow_price=True)   # Chris may write his own price here
    if not report.ok:
        return report.blocks[0].message
    return None
