-- 2026-10-26, Chris: "The sorting should also not name names! Just the type of image!" The sorters' one-line summaries
-- had named people read off stages, screens and badges (60 of 1,888 Claude summaries named a politician; the local
-- model's named buildings and signs). The prompts now forbid it; what was written under the old prompt is cleared, and
-- the Photos pages show the type of picture only once a photo is sorted again.
UPDATE classifications SET summary = '' WHERE summary IS NOT NULL AND summary <> '';
