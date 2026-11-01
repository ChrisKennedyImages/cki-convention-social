-- 2026-10-31: the sorter stored plain words as event names ("reception" 24, "receptions" 26, "conventions" 33, "awards",
-- "Gala", "volunteer"), from folder names; the public-names gate then refused every reception photo's words. They are
-- cleared here; ai/names.py PLAIN_WORDS keeps new ones out, and tests/test_names.py checks this list matches NOT_NAMES.
UPDATE classifications SET convention_name = NULL
WHERE lower(trim(convention_name)) IN ('unknown', 'none', 'n/a', 'na', 'event', 'events', 'other', 'misc',
    'reception', 'receptions', 'convention', 'conventions', 'conference', 'conferences', 'gala', 'galas', 'award', 'awards',
    'dinner', 'dinners', 'summit', 'summits', 'expo', 'expos', 'panel', 'panels', 'keynote', 'keynotes', 'breakout',
    'breakouts', 'portrait', 'portraits', 'backstage', 'stage', 'candid', 'meeting', 'meetings', 'volunteer', 'volunteers',
    'banquet', 'luncheon', 'ceremony');
