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
  unchecked minor flag, a missing key, a blind spend ledger: all mean "do not
  use, do not send".
- **The photo library is read only.** The suite lists and downloads; it never
  writes to Drive. Only the `drive.readonly` scope is ever requested.
- **People's photos fail closed.** Not cleared by default; never anyone who
  may be a minor; the do-not-use list is honoured everywhere.
- **No prices, ever, in anything public.** Quote requests only.
- **No affiliation claims** unless Chris confirmed the event.
- **Show first.** Anything visual goes to Chris as a rendered file before it
  is wired. Flags for new surfaces default off.
- **Nothing from another company.** No name, key, account, domain, bucket,
  topic or id from another suite, anywhere (`tests/test_banned_words.py`).
- **Secrets** live only in the untracked `.env` or the Keychain. Never commit,
  print or repeat them.

## Working in this repo

- Branch per change, pull request, CI green before merge.
- `bin/test` must show 0 failures, 0 errors, 0 skips.
- Runtime data lives in `CCS_DATA_ROOT` (`~/cki-convention-social-data`),
  never in the repo.
- Runtime is the Mac mini, as system LaunchDaemons with the prefix
  `com.chriskennedyimages.conventionsocial.`; the dashboard listens on
  127.0.0.1:4610 and is reached over Tailscale.
