-- 2026-10-29, Chris: "Can we also add a tab for the approved photos that I can click to add to the site's gallery (we
-- already have the button to make any photo the site hero)." His pick for the home page's gallery is on the photo,
-- like his Use: site_pick_at is when he tapped Site gallery (NULL: not picked), written to every copy of the picture,
-- and the gallery leads with his picks in that order (site/build.site_picks).
ALTER TABLE photos ADD COLUMN site_pick_at TEXT;
