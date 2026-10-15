# cki-convention-social: standing instructions for every Claude session

FOUNDER_DECISIONS.md is the source of truth. Read it first.

## Laws

- **Read, don't recall.** Every filename, env key, table, column, module or
  status string you put into code, a command or a claim must come from a
  `grep` / `ls` / `cat` you ran this session.
- **Verify at the consumer.** A thing works when it is proven where it is
  used: a real test post, a real email in Chris's inbox, the dashboard on his
  phone. A check you have not seen fire is not a check.
- **Fail closed.** A gate that cannot run says no. Unknown clearance, an
  unsorted photo, a missing key, a blind spend ledger: all mean "do not
  use, do not send".
- **The photo library is read only.** The suite lists and downloads; it never
  writes to Drive. Only the `drive.readonly` scope is ever requested.
- **People's photos fail closed.** Not cleared by default; the do-not-use list
  is honoured everywhere. No model judges anyone's age: Chris's Approve is the
  check (his ruling, 2026-10-15).
- **No prices, ever, in anything public.** Quote requests only.
- **No affiliation claims** unless Chris confirmed the event.
- **Show first.** Anything visual goes to Chris as a rendered file before it
  is wired. Flags for new surfaces default off.
- **Nothing from another company.** No name, key, account, domain, bucket,
  topic or id from another suite, anywhere (`tests/test_banned_words.py`).
  One exception, Chris's own choice on 2026-10-11: the Anthropic key is the one
  his other suite uses, copied into `.env` with `bin/ccs copy-key` (that suite's
  file is only read; the key never enters the repo).
- **Secrets** live only in the untracked `.env` or the Keychain. Never commit,
  print or repeat them.

## Working in this repo

- Branch per change, pull request, CI green before merge.
- `bin/test` must show 0 failures, 0 errors, 0 skips.
- Runtime data lives in `CCS_DATA_ROOT` (`~/cki-convention-social-data`),
  never in the repo.
- Runtime is the Mac mini, as system LaunchDaemons with the prefix
  `com.chriskennedyimages.conventionsocial.`; the dashboard listens on
  127.0.0.1:4610 and is reached over Tailscale at
  https://mac-mini.tail915d2c.ts.net:8443/
  (`tailscale serve --bg --https=8443 http://127.0.0.1:4610` on the Mini; only devices on
  Chris's Tailscale network can open it). The suite's links use it once
  `DASHBOARD_PUBLIC_URL` is set to it on the Mini (Keys page).
- **The Mini is shared with other suites. Touch only what is ours.** Our launchd
  labels, our port 4610, our `.env`, our data root, Tailscale https port 8443.
  Never https 443 on the Mini's Tailscale name: another suite's dashboard lives
  there. On 2026-10-09 serving port 4610 without `--https=8443` (so on 443) replaced
  it; before any command that changes a machine-wide setting (Tailscale serve,
  wrangler login, Homebrew, launchd outside our prefix), read what is there now
  and leave everything that is not ours exactly as it is.
- Going live and every redeploy: `scripts/go-live.sh` on the Mini. First run
  ended LIVE on 2026-10-09.
- Code reaches the Mini by itself (Chris, 2026-10-11): the updater agent
  tests anything newly merged to `main` with the full suite, then
  fast-forwards and restarts the dashboard. A merge to `main` is therefore a
  deploy: never merge red. New `launchd/` templates still need one
  `scripts/go-live.sh` on the Mini; the updater flags them.
