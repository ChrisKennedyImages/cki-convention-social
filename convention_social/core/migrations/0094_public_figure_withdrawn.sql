-- 2026-11-01, late evening, Chris: "It can show a public figure!" The LinkedIn public-figure skip of the same day (0092) is
-- withdrawn: photos with a public figure go to LinkedIn like any other approved photo, and nothing reads these columns now.
-- SQLite drops a column in place from 3.35 (the Mini's Python links 3.50, read on 2026-11-01); no index or trigger names them.
ALTER TABLE photos DROP COLUMN public_figure;
ALTER TABLE photos DROP COLUMN public_figure_at;
