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

## 2026-10-09: second round

- **Official photographer:** none. Chris is not any event's official
  photographer, and there are no booked jobs yet: the company is starting
  back up after four years of caring for his mother. No copy may say or
  hint at an official role, a client list or past bookings that do not
  exist (`ai/copy_rules.py`; the calendar's official box stays unticked).
- **Umbrella:** everything runs under CKI, LLC. Event Caliber is its brand.
- **Domain:** eventcaliber.com, on Cloudflare (`BRAND_DOMAIN`).
- **Brand direction:** Lens (ring monogram, cobalt on graphite, Space
  Grotesk) (`BRAND_DIRECTION=lens`, `render/brand.py`).
- **Booking, built now:** a quote request form on eventcaliber.com that
  lands on the dashboard and on his phone; a drafted reply he edits and
  approves before it sends (he writes any price himself; the drafter never
  does); a public availability calendar that shows booked dates only, with
  no client or event names. The deposit link is built but OFF: no payment
  service yet.
- **Mail:** Cloudflare Email Routing forwards mail for the domain to his
  inbox; a sending service with SMTP sends from the domain.
- **Photo sorting:** Ollama on the Mini sorts the whole library (free). Claude
  looks again only at a photo picked for a post, as the final check for
  minors and personal details. A photo is postable only after that Claude
  check passes (`library/eligibility.py`).
- **Architecture photos:** his exterior and some interior architecture work
  can be used as full building and venue shots: in the daily feed one day a
  week, in the website portfolio, and behind promo graphics. Clearance is
  still per folder, by Chris; readable house numbers and street signs keep a
  photo out.

## 2026-10-10: third round

- **Look:** not Lens. Black, white and greys with a touch of cyan. The first
  site was "not at all dynamic or edgy": rebuilt as a camera viewfinder
  (`site/theme.py`). Logo: four options shown; Viewfinder recommended and in
  use until Chris picks (`BRAND_MARK`, `BRAND_DIRECTION`).
- **Image metadata for search:** yes, our own words only (title,
  description, keywords, creator, copyright CKI, LLC, credit); never the
  camera's data or GPS (`render/meta.py`).
- **The crew grows:** Learner, Outreach, SEO, Scout, Chief of staff and Art
  director, each in dry run until switched on; anything that sends or posts
  still waits for Chris's Approve.

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
