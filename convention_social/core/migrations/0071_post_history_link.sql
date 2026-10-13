-- 7.1 (2026-10-13): the live post's address rides with the history, so the "posted" ping and the Posts page
-- open the post itself.
ALTER TABLE post_history ADD COLUMN external_link TEXT;
