# Founder decisions

The source of truth. Every ruling Chris makes lands here, dated, in plain
words, with the code that enforces it named beside it. A decision changes
only when Chris says so.

## 2026-10-09: the start

- **Company name:** Event Caliber, for now. The name can change; it lives in
  one setting (`BRAND_NAME` in `.env`, default in `core/config.py`).
- **Legal entity:** CKI, LLC (`LEGAL_NAME`).
- **Repo:** a fresh private repo, `ChrisKennedyImages/cki-convention-social`,
  with its own history. Nothing from any other company's suite is referenced
  anywhere (`tests/test_banned_words.py`).
- **Conventions:** both fan conventions (comic, anime, gaming, cosplay) and
  business and political conferences.
- **Photo library:** Google Drive of chriskimages@gmail.com, read only, signed
  in as Chris (OAuth, `drive.readonly`).
- **Platforms:** Instagram, a Facebook Page and Pinterest, all through this
  company's own Buffer account.
- **Cadence:** one post a day.
- **Posting times:** left to the suite. Starting times, Eastern:
  Instagram about 11:30 on weekdays and 10:00 on weekends, Facebook about
  9:30, Pinterest about 20:30. These come from general industry data on
  engagement, not this account's own numbers; the suite moves toward what
  its own posts show once Buffer reports them.
- **Credits and consent:** one Google Sheet that Chris keeps.
- **Beyond social:** emails to event organizers (each sent only on Chris's
  Approve) and a website on a new domain, with mail sent from an address on
  that domain.
- **Brand:** the suite designs options for Chris to choose from; nothing is
  wired until he picks.
- **What the company sells:** full event coverage: backstage, green room,
  breakouts, before, during and evening events and dinners, portraits,
  exhibition halls and vendors, and immediate delivery of approved images to
  attendees, staff, speakers and presenters.
- **Prices:** vary by event and are not fixed. No post, email or page ever
  states a price; the call to action is a quote request
  (`ai/copy_rules.py`, rule `price`).

## Standing rules from the brief

- Nothing publishes without Chris's Approve on the dashboard, until he says
  otherwise. Every agent that sends or publishes starts in dry run
  (`core/settings.py`).
- Nothing in Drive is ever modified, moved, renamed or deleted
  (`drive/`, pinned by `tests/test_drive_readonly.py`).
- No photo is eligible until Chris clears its folder or the photo itself.
  Never post anyone who may be a minor. A do-not-use list is honoured
  everywhere.
- Never claim to be a convention's official photographer or any affiliation
  unless Chris confirms it for that event (`ai/copy_rules.py`, rule
  `affiliation`).
- Captions and copy: plain, short sentences, no dashes, never promise what
  the system does not do today.
