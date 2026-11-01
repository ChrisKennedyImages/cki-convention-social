-- 2026-11-01, Chris on the Search Console numbers: "shouldn't we have it do it all. Why wouldn't we?" For every change,
-- "One tap from my phone": drafted and pinged with before and after and Approve; on Approve it goes live, is measured
-- four weeks and is put back by itself if the numbers drop (seo/changes.py). Part one: weak titles and descriptions.

-- What Google's search numbers said, per page and per search on a page, for each 28-day window the weekly read takes
-- (seo/search_console.py). query '' is the page's own total over every search: Google leaves its rare searches out of
-- the per-search rows to keep them private, so the per-search rows of a page add up to less than its total.
CREATE TABLE IF NOT EXISTS search_console_rows (
    id           INTEGER PRIMARY KEY,
    read_at      TEXT NOT NULL,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    page         TEXT NOT NULL,                  -- the address as Google gives it: https://eventcaliber.com/coverage/stage/
    query        TEXT NOT NULL DEFAULT '',
    clicks       INTEGER NOT NULL,
    impressions  INTEGER NOT NULL,
    position     REAL NOT NULL,
    UNIQUE (start_date, end_date, page, query)
);
CREATE INDEX IF NOT EXISTS idx_search_console_rows_page ON search_console_rows (page, end_date);

-- Every change the SEO agent proposes to the site, from its draft to its verdict.
CREATE TABLE IF NOT EXISTS seo_changes (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL,                -- 'title': a page's title and description (part one)
    page           TEXT NOT NULL,                -- the site path: '/coverage/stage/'
    fields         TEXT NOT NULL,                -- JSON list of what it changes: ["title", "description"]
    before         TEXT NOT NULL,                -- JSON {field: words}: what the page said when it was proposed
    after          TEXT NOT NULL,                -- JSON {field: words}: what it says once approved
    queries        TEXT NOT NULL DEFAULT '[]',   -- JSON: the searches that motivated it, with their numbers
    reason         TEXT NOT NULL,                -- why, in plain words, with the numbers
    status         TEXT NOT NULL DEFAULT 'proposed'
                   CHECK (status IN ('proposed', 'approved', 'live', 'kept', 'reverted', 'skipped')),
    proposed_at    TEXT NOT NULL,
    approved_at    TEXT,
    live_at        TEXT,                         -- the deploy that carried it succeeded
    measure_after  TEXT,                         -- live_at + 31 days: 28 days of numbers and Google's 3-day lag
    verdict_at     TEXT,                         -- kept, reverted, or his Skip
    baseline       TEXT,                         -- JSON: the page's clicks, impressions, ctr, position before it went live
    result         TEXT,                         -- JSON: the same for the days since, and what was decided
    updated_at     TEXT NOT NULL                 -- signed into the ping's one-tap token: any change to the row kills it
);
-- one open change per page at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_changes_one_open ON seo_changes (page) WHERE status IN ('proposed', 'approved', 'live');
CREATE INDEX IF NOT EXISTS idx_seo_changes_status ON seo_changes (status, kind);
