-- 2026-11-01, Chris, asked whether LinkedIn should skip photos where an organization's name or logo is prominent (a banner
-- behind the people in one of the sample posts): "Yes, skip on LinkedIn". Instagram is unchanged.
-- prominent_logo: the art director's one judgement, 1 yes, 0 no, NULL not judged yet; asked once through the AI till and never
-- again, with the public figure question when both are open (agents/art_director.judgements). prominent_logo_at: when.
ALTER TABLE photos ADD COLUMN prominent_logo INTEGER;
ALTER TABLE photos ADD COLUMN prominent_logo_at TEXT;
