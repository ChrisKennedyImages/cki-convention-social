-- 2026-11-01, SEO part two, near misses (seo/leads.py): a page sitting just off Google's first page for a search gets its
-- lead sentence reworded to work that search in. Such a change is made for one search and judged on it, the page's
-- average place for that search, not on the page's click rate (seo/changes.py PLACE). The search it was made for; ''
-- for a change to the page as a whole (part one's titles and descriptions).
ALTER TABLE seo_changes ADD COLUMN search TEXT NOT NULL DEFAULT '';
