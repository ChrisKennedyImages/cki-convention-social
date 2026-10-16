-- 2026-10-15: Chris's photographers (agents/team.py). Each has a first name (kept here only, never sent anywhere), the
-- SHA-256 of their send token (the token itself is shown to Chris once and never kept) and an on/off switch. A one-time
-- phone link is kept by its hash too. phone_sends.sender_id says who sent a photo; NULL is Chris himself.
CREATE TABLE IF NOT EXISTS team_members (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_joins (
    id          INTEGER PRIMARY KEY,
    member_id   INTEGER NOT NULL REFERENCES team_members(id) ON DELETE CASCADE,
    code_sha256 TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
ALTER TABLE phone_sends ADD COLUMN sender_id INTEGER REFERENCES team_members(id);
