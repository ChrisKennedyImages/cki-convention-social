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

## 4. The domain and its mailbox (decision needed, money)

- Buy the domain at any registrar. Put its name in Keys (Website domain).
- Mail from that domain needs a mailbox that allows SMTP sending with an
  app password. Options, each with its own monthly cost: Google Workspace,
  Fastmail, or a sending service paired with Cloudflare Email Routing.
  Chris chooses; the suite needs the server, the login and an app password
  (Keys, Mail) plus a postal address for the footer of every email.

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

## 8. Image hosting for Buffer

Buffer fetches each post image by link. A Cloudflare R2 bucket for this
company, served from the new domain by the worker in `worker/`
(`wrangler.jsonc.example` names what to fill). The upload token goes in Keys
(Image hosting). Set up after the domain exists.

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
