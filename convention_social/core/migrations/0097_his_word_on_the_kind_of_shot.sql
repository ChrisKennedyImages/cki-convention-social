-- 2026-11-02, Chris: "I also want to be able to change the type of shot that is miss labeled. Most backstage images are
-- called candid". The kind of shot he sets is his word: a later look by a model (the sorter's second look, the final
-- check before a post) keeps it. 'chris' when he set it; NULL when a model's word stands.
ALTER TABLE classifications ADD COLUMN shot_by TEXT;
