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

## 4. Mail on eventcaliber.com: Google Workspace

Chris chose (2026-10-13): `chris@eventcaliber.com` on Google Workspace. One
mailbox sends and receives; the suite's sender is plain SMTP with STARTTLS on
port 587, which is exactly what Gmail offers (`core/mail.py`, nothing to
change in the code).

1. Workspace sign-up for eventcaliber.com, with `chris@eventcaliber.com` as
   the first user. Google's setup wizard verifies the domain and gives the
   DNS records: the MX records, SPF (a TXT on the root: `v=spf1
   include:_spf.google.com ~all`) and DKIM (Admin console, Apps, Google
   Workspace, Gmail, Authenticate email: generate the key, add the TXT it
   shows). Add each one in Cloudflare DNS exactly as shown; keep the TXT
   records the site already has.
2. Cloudflare, eventcaliber.com, Email: switch Email Routing off if it is
   on. Both want the MX records; with Workspace, Google receives the mail.
   A `hello@` address, if you want one, is an alias on the Workspace user
   (Admin console, Users, the user, Alternate email addresses), free.
3. Gmail, the account: turn on 2-Step Verification, then make an app
   password (Google Account, Security, 2-Step Verification, App passwords;
   name it Event Caliber suite). That 16-character password is for the suite
   only; the account password is never typed anywhere in the suite.
4. Keys (Mail): server `smtp.gmail.com`, login `chris@eventcaliber.com`, the
   app password. Keys (Company): Mail sent from `chris@eventcaliber.com`,
   or an alias Google has verified (Gmail, Settings, Accounts, "Send mail as";
   Gmail rewrites any other From address to the login), and a postal
   address for the footer.
5. Prove it: send yourself one quote request from the site, approve the
   drafted reply with the inbox agent switched live. It must land in your
   inbox, not spam (SPF and DKIM above are what keep it out of spam).

## 5. Buffer: the one publisher

1. A **new** Buffer account for this company (its own email login).
2. Connect: the Instagram professional account, the Facebook Page, the
   Pinterest business account. Create the Pinterest board posts land on.
3. publish.buffer.com/settings/api: create an API key. Keys (Buffer).
4. More, Buffer: tap Find channels, then Use on each of this company's own
   accounts (nothing links by itself). If the key sees more than one Buffer
   organization, choose this company's first. Find boards, Use the Pinterest
   board. Check the video format (for the Saturday reels).
5. `bin/ccs run publisher --dry-run` (or Run now on the Agents page) lists
   what it would send. Nothing publishes until you switch the publisher to
   live on the Agents page, and even then only posts you approved.

## 6. Anthropic: your key

Chris, 2026-10-11: this suite uses the Anthropic key his other suite already
uses. On the Mini, from this repo (that other file is only read, and the key
is never shown):

    bin/ccs copy-key ANTHROPIC_API_KEY --from <path to that suite's .env>

It also takes the key under the name CLAUDE_API_KEY, or any name with
`--as NAME`, and ends with one free check that Anthropic accepts it. The
monthly cap on Keys (AI, default 20 USD) stops this suite's paid calls once
reached, whatever the other suite spends.

## 7. Phone alerts: ntfy

1. Install the ntfy app. Subscribe to a new topic with a long random name.
2. Put the same name in Keys (Phone alerts).

## 8. eventcaliber.com itself: the Worker

One Cloudflare Worker serves the website, takes quote requests, publishes
the booked dates and hosts post images for Buffer. You do not type the
Cloudflare steps: `scripts/go-live.sh` on the Mini (section 9) signs in to
Cloudflare (a browser opens; use the account that holds eventcaliber.com and
click Allow), creates the image bucket and the booking database, builds and
deploys the site, gives the site and the Mini the same upload token without
showing it, and checks every page from the outside. After that first run the
site keeps itself current: the updater redeploys it when a merge changes a
site file, and **Publish the site** on the Photos page (Approved) redeploys it
from your phone, for instance once photos are cleared or the hero changes.
The Website card there says what happened. `scripts/go-live.sh` still works
for a full redeploy.

Two things only you can do in the Cloudflare dashboard, and the script tells
you when it needs them: turning on R2 (it asks for a card even for the free
allowance) and, if the domain still has old website records, deleting the old
A, AAAA or CNAME records for eventcaliber.com and www (keep MX and TXT; they
carry the mail).

Optional spam check: a free Cloudflare Turnstile widget for the domain; its
site key goes in `.env` as `TURNSTILE_SITE_KEY` and its secret into
`npx wrangler secret put TURNSTILE_SECRET -c wrangler.live.jsonc`.

### 8a. Search engines: Google Search Console and IndexNow

The site has carried a sitemap (`/sitemap.xml`, every public page and every
photo on the home page, each page with the date its content last changed)
and a `robots.txt` that names it since the first build, and the weekly site
check reads both from outside. A search engine still has to be told the site
exists. From your phone:

1. Open https://search.google.com/search-console and add a property of the
   **URL prefix** kind: `https://eventcaliber.com/`.
2. Under verification methods choose **HTML tag** and copy the tag.
3. Dashboard, Keys, Search engines: paste the tag (or only its content value)
   into **Google Search Console tag**, save.
4. Dashboard, Photos, Approved: **Publish the site**. The tag is now on every
   page.
5. Back in Search Console press **Verify**. Then Sitemaps, enter `sitemap.xml`,
   Submit. Google reads the sitemap from then on; the first pages appear in
   its results within days, not minutes.

Bing, Yandex and the other IndexNow engines need no account: the first publish
makes an IndexNow key (Keys page, Search engines), the site hosts it at
`/<key>.txt`, and every publish tells them which pages to read again. The
Website card on the Photos page says whether they heard. Bing Webmaster Tools
can also import the Search Console property if you want its reports.

Organizer emails (the Outreach agent) need the opt-out table too. It is in
`worker/schema.sql`, which the go-live script applies on every run; it only
adds what is missing. Every organizer email
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
scripts/go-live.sh
```

It asks, the first time only, for your Mac password (installing the agents
as system services), a dashboard password of your choosing, and the
Cloudflare sign-in. It ends with `LIVE` when the site and the dashboard both
pass, or `STOP` with the reason. Later, run it again: it first brings the
checkout up to date with GitHub (tested first, the updater's way), then
skips what is done and refreshes the rest. It needs Python 3.13 and Node
(`brew install python@3.13 node`); it says so if either is missing.

After this first run you should not need a terminal again. The **updater**
agent checks GitHub every 10 minutes and, once you switch it from dry run to
LIVE on the dashboard's Agents page, tests anything new with the full suite
and only then updates the Mini and restarts the dashboard. Every agent also
has a **Run now** button there. The only exception: when an update brings new
service files, the Agents page says so, and `scripts/go-live.sh` has to run
once more for your Mac password.

The dashboard listens on 127.0.0.1:4610. From your phone, reach it over
Tailscale on port 8443, never 443 (another dashboard on this Mini uses 443):
`tailscale serve --bg --https=8443 http://127.0.0.1:4610` on the Mini, then open the address it
prints. Every agent starts in dry run.
