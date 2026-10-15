-- The doctor (Chris, 2026-10-15: "a doctor agent too to auto fix anything that fails realtime"), agents/doctor.py.
-- One row per remedy it tried (or, in dry run, would have tried), with the signal it saw and what it found after.
CREATE TABLE IF NOT EXISTS doctor_remedies (
    id          INTEGER PRIMARY KEY,
    problem     TEXT NOT NULL,          -- agent:<name> | backup | disk | dashboard | post:<id> | reel:<id> | drive | issue:<signature>
    found       TEXT NOT NULL,          -- the signal, in words
    remedy      TEXT NOT NULL,          -- what it did, or would do
    started_at  TEXT NOT NULL,
    dry_run     INTEGER NOT NULL DEFAULT 1,
    outcome     TEXT NOT NULL DEFAULT 'pending',   -- would | pending | fixed | not_fixed | cannot | left | filed
    checked_at  TEXT,
    detail      TEXT,
    said_at     TEXT                    -- when Chris was told (a remedy that did not work, said once)
);
CREATE INDEX IF NOT EXISTS idx_doctor_remedies_problem ON doctor_remedies (problem, started_at);

-- One GitHub issue per distinct error in our code: agent, kind and the traceback's frames make the signature.
CREATE TABLE IF NOT EXISTS doctor_issues (
    signature       TEXT PRIMARY KEY,
    agent           TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    first_error     INTEGER,
    last_error      INTEGER,             -- errors.id of the newest occurrence
    seen            INTEGER NOT NULL DEFAULT 0,
    last_seen_at    TEXT,
    number          INTEGER,
    url             TEXT,
    opened_at       TEXT,
    reopened_from   INTEGER,             -- the closed issue it came back after
    checked_on      TEXT,                -- the local day its state on GitHub was last read
    checked_error   INTEGER,             -- the newest occurrence that read covered
    pinged_at       TEXT                 -- no token: Chris was pinged instead, once
);
