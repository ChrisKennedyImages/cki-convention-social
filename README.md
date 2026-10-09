# cki-convention-social

The marketing suite for Event Caliber (eventcaliber.com), a brand of CKI, LLC, a convention and event
photography company. It finds Chris's convention photos in his Google Drive
(read only), lets him clear which ones may be used, drafts one post a day with
captions and designs built around his photos, and publishes through the
company's own Buffer account once he approves each post on the dashboard.

## Layout

| Path | What it is |
|---|---|
| `convention_social/core/` | config, `.env` + Keychain secrets, SQLite with numbered migrations, fail-closed dry-run switches, runner with locks and run records, logs, mail, phone push, dashboard password |
| `convention_social/drive/` | the Drive photo library: OAuth as Chris (`drive.readonly`), full inventory, then the Changes API |
| `convention_social/ai/` | Claude drafting (strict JSON), the monthly spend cap, the copy rules gate |
| `convention_social/buffer/` | the Buffer GraphQL client, payloads, media hosting, rate budget, metrics |
| `convention_social/render/` | post designs built around the photos |
| `convention_social/agents/` | scanner, content (the daily draft), publisher, inbox (booking), watchdog, backup |
| `convention_social/booking/`, `worker/` | quote requests, replies, booked dates; the eventcaliber.com Worker |
| `convention_social/site/` | the eventcaliber.com pages, built from postable photos |
| `offer.json` | what the company offers, in Chris's words; never a price |
| `convention_social/dashboard/` | the review UI: login, queue with Approve/Reject, clearance, keys, agents |
| `bin/ccs`, `bin/test` | the command line and the test runner |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill per docs/SETUP.md
bin/test                        # 0 failures, 0 errors, 0 skips
bin/ccs init-db
bin/ccs status
```

Every agent that sends or publishes is in dry run until switched on from
the dashboard's Agents page.
