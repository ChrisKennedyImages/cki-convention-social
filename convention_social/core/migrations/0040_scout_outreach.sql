-- 0040: the scout (events worth a look) and outreach (emails to organizers, each sent only on Chris's Approve).

-- What the weekly scout found on the web. Nothing here is on the calendar until
-- Chris presses "Add to calendar" (status added, convention_id set); dismissed
-- rows stay so the same event is not offered again.
-- dedup_key = normalized name + "|" + start_date ('' when no date was found).
CREATE TABLE IF NOT EXISTS scout_events (
    id               INTEGER PRIMARY KEY,
    dedup_key        TEXT NOT NULL UNIQUE,
    name_key         TEXT NOT NULL,                           -- normalized name alone
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('fan', 'business', 'other')),
    start_date       TEXT,                                    -- YYYY-MM-DD, NULL when the source did not say
    end_date         TEXT,
    city             TEXT,
    venue            TEXT,
    website          TEXT,
    organizer        TEXT,
    organizer_email  TEXT,                                    -- only when printed on the event's own site
    email_source_url TEXT,                                    -- the page of that site the address was read from
    sources          TEXT NOT NULL DEFAULT '[]',              -- JSON list of source URLs (never empty when stored)
    status           TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'added', 'dismissed')),
    convention_id    INTEGER REFERENCES conventions(id) ON DELETE SET NULL,
    model            TEXT,
    found_at         TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scout_events_name ON scout_events (name_key);
CREATE INDEX IF NOT EXISTS idx_scout_events_status ON scout_events (status, start_date);

-- Addresses that must never get an outreach email: opt-out links, STOP replies,
-- anything Chris adds. Checked before drafting and again before sending.
CREATE TABLE IF NOT EXISTS do_not_contact (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,                         -- lowercased
    source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'unsubscribe', 'reply', 'bounce')),
    reason      TEXT,
    added_at    TEXT NOT NULL
);

-- One row per email: a first note to an organizer about one event, or the one
-- follow-up Chris may approve 7 days or more after the first was sent.
-- status: queued (a prospect Chris added, not drafted yet) | draft | approved |
-- rejected | sent | would_send (dry run wrote the .eml) | failed | opted_out.
-- token: random hex, the only thing the opt-out link carries; never the address.
CREATE TABLE IF NOT EXISTS outreach (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL DEFAULT 'first' CHECK (kind IN ('first', 'follow_up')),
    parent_id       INTEGER REFERENCES outreach(id) ON DELETE SET NULL,
    scout_event_id  INTEGER REFERENCES scout_events(id) ON DELETE SET NULL,
    event_key       TEXT NOT NULL,                            -- same normalization as scout_events.dedup_key
    event_name      TEXT NOT NULL,
    event_kind      TEXT NOT NULL DEFAULT 'other' CHECK (event_kind IN ('fan', 'business', 'other')),
    start_date      TEXT,
    end_date        TEXT,
    city            TEXT,
    venue           TEXT,
    website         TEXT,
    organizer       TEXT,
    email           TEXT NOT NULL,                            -- lowercased
    subject         TEXT,
    body            TEXT,                                     -- Chris's words; the footer is added at send time
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('queued', 'draft', 'approved', 'rejected', 'sent', 'would_send', 'failed', 'opted_out')),
    token           TEXT NOT NULL UNIQUE,
    model           TEXT,
    notes           TEXT,
    drafted_at      TEXT,
    approved_at     TEXT,
    last_attempt_at TEXT,                                     -- a live send or a dry-run .eml, for the daily cap
    sent_at         TEXT,
    message_id      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (email, event_key, kind)                           -- one note per prospect per event, one follow-up at most
);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach (status, id);
CREATE INDEX IF NOT EXISTS idx_outreach_email ON outreach (email);
