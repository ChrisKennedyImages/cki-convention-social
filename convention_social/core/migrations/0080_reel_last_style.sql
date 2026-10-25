-- 2026-10-24: a reel's style is chosen and recorded in one write (settings reel.last_style, agents/content.reel_style),
-- no longer read back from the last reel's queue row minutes after its render. The last reel so far seeds the memory,
-- so the first reel on this code is still never the same style as the one before it.
INSERT INTO settings (key, value, updated_at)
SELECT 'reel.last_style', json_extract(rule_report, '$.reel'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
FROM content_queue WHERE json_extract(rule_report, '$.reel') IS NOT NULL ORDER BY id DESC LIMIT 1
ON CONFLICT(key) DO NOTHING;
