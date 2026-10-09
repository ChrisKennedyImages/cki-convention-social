-- 0010: building shots, the final Claude check, and booking.

-- What a photo is of: event work, a building (exterior or interior), or neither.
ALTER TABLE classifications ADD COLUMN subject TEXT;          -- event | architecture | other
ALTER TABLE classifications ADD COLUMN view TEXT;             -- exterior | interior | NULL

-- The last look before a photo may be posted: Claude, on the chosen photo only.
-- A photo is postable only with a passing row here (fail closed).
CREATE TABLE IF NOT EXISTS final_checks (
    photo_id         INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    possible_minor   INTEGER NOT NULL,                        -- 1 maybe, 0 confident none
    personal_details TEXT NOT NULL DEFAULT '[]',              -- JSON list
    summary          TEXT,
    model            TEXT NOT NULL,
    checked_at       TEXT NOT NULL
);

-- Quote requests from the website, pulled from the site's own store.
CREATE TABLE IF NOT EXISTS inquiries (
    id              INTEGER PRIMARY KEY,
    remote_id       TEXT NOT NULL UNIQUE,                     -- the site's id for the request
    received_at     TEXT NOT NULL,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    phone           TEXT,
    organization    TEXT,
    event_name      TEXT,
    event_kind      TEXT,                                     -- fan | business | other
    start_date      TEXT,
    end_date        TEXT,
    city            TEXT,
    venue           TEXT,
    attendance      TEXT,
    coverage        TEXT,                                     -- JSON list of what they asked for
    message         TEXT,
    status          TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new', 'drafted', 'replied', 'quoted', 'booked', 'declined', 'spam')),
    reply_subject   TEXT,
    reply_body      TEXT,                                     -- the drafted reply, edited by Chris
    reply_status    TEXT NOT NULL DEFAULT 'none'
                    CHECK (reply_status IN ('none', 'draft', 'approved', 'sent', 'would_send', 'failed')),
    reply_sent_at   TEXT,
    reply_message_id TEXT,
    deposit_link    TEXT,                                     -- unused until a payment service exists
    notes           TEXT,
    updated_at      TEXT NOT NULL
);

-- Dates Chris is booked. The public calendar shows the dates only.
CREATE TABLE IF NOT EXISTS bookings (
    id              INTEGER PRIMARY KEY,
    inquiry_id      INTEGER REFERENCES inquiries(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,                            -- private; never published
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'hold' CHECK (status IN ('hold', 'booked', 'cancelled')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
