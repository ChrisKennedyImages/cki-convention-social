-- 2026-11-01, Chris: "LinkedIn posts avoid photos whose main subject is a recognisable public figure; Instagram stays as it is."
-- public_figure: the art director's one judgement of the photo, 1 yes, 0 no, NULL not judged yet; asked once through the AI till
-- and never again (agents/art_director.public_figure). public_figure_at: when. A photo not judged is not sent to LinkedIn.
ALTER TABLE photos ADD COLUMN public_figure INTEGER;
ALTER TABLE photos ADD COLUMN public_figure_at TEXT;
