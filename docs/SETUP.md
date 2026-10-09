# Setup: what Chris creates, in order

Nothing here is shared with any other company. Every account, key, topic,
bucket and domain below is new and belongs to this company only. Values go
in the dashboard's **Keys** page (or `.env` on the Mini); secrets are never
typed into chat.

## 1. GitHub: the repo

1. github.com/new, signed in as ChrisKennedyImages.
2. Name `cki-convention-social`, **Private**, and leave every "add a file" option off.
3. If the Claude GitHub app is set to "only selected repositories", add this
   repo: github.com/settings/installations, the Claude app, Configure.

## 2. Google Drive: read-only access to the photos (chriskimages@gmail.com)

The suite signs in as you and asks for one permission only: see and download
your Drive files. It can never change, move or delete anything.

1. console.cloud.google.com, signed in as chriskimages@gmail.com.
   New project, name it `event-caliber-suite`.
2. APIs and services, Library: enable **Google Drive API**.
3. Google Auth Platform (OAuth consent screen): Get started.
   App name `Event Caliber suite`, user support email your own,
   audience **External**, contact email your own. Create.
4. Data access: Add scope, search `drive.readonly`, tick
   `.../auth/drive.readonly`, Update, Save.
5. Audience: **Publish app**, so the status reads **In production**.
   This is the important step. An app left in "Testing" gets a sign-in that
   dies after 7 days. In production, for your own use, the sign-in lasts
   until you revoke it or it goes unused for about six months (the scanner
   uses it every hour). Google may show "Google hasn't verified this app"
   when you sign in: that is expected for a personal app. Choose Advanced,
   then Go to Event Caliber suite.
6. Clients: Create client, type **Desktop app**, name `mini`. Copy the
   client ID and client secret into Keys (Google Drive).
7. On the Mini: `bin/ccs drive login`. Open the link it prints, sign in as
   chriskimages@gmail.com, allow. If the last page does not load, copy its
   address and paste it into the terminal.

If the sign-in ever stops working, the dashboard shows it on every page,
and you get a phone push and an email within the hour.

## 3. Credits and consent sheet

1. A new Google Sheet in the same Drive, named `Event Caliber credits`.
2. Row 1, these headers: `Photo or folder | Name | Handle | Consent | Notes`.
3. One row per person or per folder: paste the Drive link of the photo or
   folder, the name, the handle exactly as it should print (`@name`),
   `yes` or `no` for consent.
4. Paste the sheet's link into Keys (Credits sheet). The suite reads it
   every hour and never edits it.

## 4. Mail on eventcaliber.com

Chris chose (2026-10-09): Cloudflare forwards incoming mail, a sending
service sends outgoing mail.

1. Cloudflare dashboard, eventcaliber.com, Email, Email Routing: enable it,
   add a custom address `hello@eventcaliber.com`, destination your own inbox
   (verify the link Cloudflare emails you). Free.
2. A sending service with SMTP for the domain (Resend, Postmark or Mailgun
   are common; check each one's current free allowance, that is money).
   Add the domain there; it shows DNS records (SPF, DKIM, a return path).
   Add each one in Cloudflare DNS exactly as shown, then let the service
   verify the domain.
3. Keys (Mail): the service's SMTP server, login and password (its API key
   is usually the password). Keys (Company): Mail sent from
   `hello@eventcaliber.com`, and a postal address for the footer.
4. Prove it: approve one reply to a test request you send yourself, with the
   inbox agent switched live. It must land in your inbox, not spam.

## 5. Buffer: the one publisher

1. A **new** Buffer account for this company (its own email login).
2. Connect: the Instagram professional account, the Facebook Page, the
   Pinterest business account. Create the Pinterest board posts land on.
3. publish.buffer.com/settings/api: create an API key. Keys (Buffer).
4. On the Mini: `bin/ccs run publisher --dry-run` lists what it would send.
   Nothing publishes until you switch the publisher to live on the Agents
   page, and even then only posts you approved.

## 6. Anthropic: this company's own key

1. console.anthropic.com: a new workspace `event-caliber`, an API key in it.
2. Keys (AI). The monthly cap there (default 20 USD) stops every paid call
   once reached.

## 7. Phone alerts: ntfy

1. Install the ntfy app. Subscribe to a new topic with a long random name.
2. Put the same name in Keys (Phone alerts).

## 8. eventcaliber.com itself: the Worker

One Cloudflare Worker serves the website, takes quote requests, publishes
the booked dates and hosts post images for Buffer. `wrangler.jsonc` lists
every step at the top; in short, on the Mini, signed in to the Cloudflare
account that holds eventcaliber.com (`npx wrangler login`, you click Allow):

```bash
npx wrangler r2 bucket create eventcaliber-media
npx wrangler d1 create eventcaliber-booking      # paste the id into wrangler.jsonc
npx wrangler d1 execute eventcaliber-booking --remote --file worker/schema.sql
npx wrangler secret put UPLOAD_TOKEN             # a long random value; the same one goes in Keys (Image hosting)
npx wrangler secret put NTFY_TOPIC               # optional: a push on every quote request
bin/ccs site build && npx wrangler deploy        # only after you approved the site preview
```

Keys (Image hosting): `https://eventcaliber.com/m` and the same token.
Optional spam check: a free Cloudflare Turnstile widget for the domain; its
site key goes in `.env` as `TURNSTILE_SITE_KEY` and its secret into
`npx wrangler secret put TURNSTILE_SECRET`.

Organizer emails (the Outreach agent) need the opt-out table too. It is in
`worker/schema.sql`, so the same `d1 execute` line above creates it; run it
again after any update, it only adds what is missing. Every organizer email
carries the postal address from `.env` (`BRAND_POSTAL_ADDRESS`), an opt-out link
and a "reply STOP" line. A STOP reply lands in your inbox; add that address
on the dashboard's Outreach page, under Do not contact.

The Scout searches only where you tell it: set `SCOUT_REGION` in `.env` in
plain words (for example "Washington DC, Baltimore and Northern Virginia").
Empty means it does not search.

## 8b. Ollama on the Mini (already installed)

The scanner uses the first vision model Ollama has. If it has none:
`ollama pull qwen2.5vl:7b` (or name another in Keys, Local sorting). Ollama
keeps its own port; nothing in this suite changes it.

## 9. The Mini

```bash
git clone git@github.com:ChrisKennedyImages/cki-convention-social.git ~/Projects/cki-convention-social
cd ~/Projects/cki-convention-social
scripts/setup.sh                 # venv, packages, data folder, fonts, the database
bin/ccs hash-password            # paste the printed line into .env
sudo scripts/install-daemons.sh  # the agents as system LaunchDaemons (you type the password)
bin/ccs status
```

The dashboard listens on 127.0.0.1:4610. From your phone, reach it over
Tailscale: `tailscale serve --bg 4610` on the Mini, then open the address it
prints. Every agent starts in dry run.
