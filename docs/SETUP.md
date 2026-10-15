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

**Galleries shared with the account (2026-10-14).** Folders that someone
shares with chriskimages@gmail.com (his brother's galleries) are scanned like
Chris's own: they appear under Folders as `Shared with me/<name>`, with "shared
by <name>" on the card, and nothing in them is used until he approves the
folder or a photo. A gallery shared after the last scan is picked up within
the hour; a photo added to a known gallery arrives with the next changes
read. Drive shortcuts are not followed (the real folder arrives through the
share). Only names are read, never addresses, and still only with the
read-only scope.

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
2. If Search Console verifies the property by itself (a Domain property
   through Cloudflare's DNS, which is how it went on 2026-10-12), there is
   nothing to paste: skip to step 5. If it asks you to prove ownership, pick
   a method and copy what it shows: the **HTML tag** (or only its content
   value), the **TXT record** (`google-site-verification=...`), or the
   **HTML file** (its name).
3. Dashboard, Keys, Search engines: paste it into **Google Search Console
   tag**, save. Anything that is none of these is refused there, with the
   reason; the Website card on the Photos page says the same.
4. The site republishes itself within ten minutes (the Website card says so;
   **Publish the site** starts it now). The tag is then on every page, or the
   file is at the root, and the check from outside after every publish
   confirms it is there.
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

### 8c. The phone number and the social links on the site: the Keys page

Dashboard, Keys, **Website contact** (2026-10-14): the phone number and the
Instagram, Facebook and Pinterest addresses. Each one is blank until you fill
it in, and a blank one shows nowhere. With a number set it is tappable at the
top of every page on phones, on the Contact page, in the footer and in the
business details search engines read; the social addresses go in the footer
(https addresses only). Saving any of them republishes the site by itself
within ten minutes, like a photo change; the Website card on the Photos page
says when it went. Nothing else is needed: no terminal, no Publish tap.

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

## 10. A photo from your phone while you shoot

Open the dashboard on your phone, Today, **Send a photo** (or the button on
the Queue page). Pick the photo from the camera roll (the original, not a
preview) or take one, add one line about it if you like (what the room was;
never a name or which event), and Send. Within a few minutes your phone gets
the ping with the post and Approve; the Send page shows each send and where
it stands, and says why when one could not be drafted (a readable plate, a
wedding, the monthly AI cap). Approved, the
post goes out as soon as Buffer takes it. The photo stays on the Mini and is
never written to Drive.

### 10a. Post to Event Caliber: a photo straight from the iPhone's share sheet

In Photos, pick one photo, tap Share, then **Post to Event Caliber**, add a
line if you like, and that is it: no dashboard, no Tailscale. Your send is
your approval (2026-10-15): the suite still runs its checks, and a readable
plate, a wedding, a caption that will not come right or the art director's no
stops it and your phone says why. Otherwise it goes out on Instagram as soon
as Buffer takes it, about 35 minutes later, and your phone gets two pings:
when it is approved (with the time, and the draft page to stop it), and when
it is up (it opens the post on Instagram, where you can delete it; the
dashboard is the other button).

Once, on the Mini or from the dashboard on your phone:

1. Keys, **Make a send token**. The page shows the token once: copy it. The
   site takes it by itself within about twenty minutes (the next publish puts
   it on the Worker as `SEND_TOKEN`); a new token replaces the old one.
2. For the pickup every minute, run `scripts/go-live.sh` once on the Mini
   (it installs the new `phone` job; the dashboard flags it until then). Until
   you do, the inbox's ten-minute run picks the photos up.

Then build the Shortcut on the iPhone, in the Shortcuts app:

1. Tap **+** for a new shortcut. Tap its name at the top, Rename, and call it
   `Post to Event Caliber`.
2. Tap the **i** (Details) and turn on **Show in Share Sheet**. The first step
   becomes "Receive ... input from Share Sheet": tap the input types and leave
   only **Images**; for "If there's no input" choose **Stop and Respond**.
3. Add **Ask for Input**: input type Text, prompt `A line about it (optional)`.
4. Add **Get Contents of URL** and set its address to
   `https://eventcaliber.com/api/send`. Tap the arrow to show more:
   - Method: **POST**
   - Headers: add one, key `Authorization`, value `Bearer ` (the word Bearer
     and one space) followed by the token you copied.
   - Request Body: **Form**. Add a **File** field with key `photo` and the
     **Shortcut Input** as its value; add a **Text** field with key `note` and
     **Provided Input** as its value.
5. Add **Show Result** with **Contents of URL**, so you see the site's answer.
6. Tap Done. In Photos, the share sheet's Edit Actions can put it at the top.

Send one photo at a time. What the site answers:

- `Received. ...` it is on its way; the pings follow.
- `Not received: the site does not know this token. ...`
  The header is wrong, or the site has not taken a new token yet.
- `Not received: sending from the phone is not set up on the site yet. ...`
  the site has no token yet: wait for the publish after Make a send token.
- `Not received: not a JPEG, PNG or HEIC photo.`, `... over 40 MB.`,
  `... 20 photos an hour is the limit.`, `... 30 photos are already waiting`
  (the Mini is not picking them up: check it).

The token only sends photos: it cannot read or delete anything on the site.
But a photo sent with it can post, so it lives only in the Shortcut. If the
phone is lost, Make a send token again and the old one stops working once the
site has the new one. No signed `.shortcut` file is kept in the
repo: signing one needs Apple's servers under your Apple ID, and it could not
carry your token anyway, so the steps above are the way.
