-- 2026-10-26: Drive holds the same file in several places (2,916 live photos in 1,432 identical copies), and a Use
-- or Don't use landed on one copy only, so the twin stayed on the review list (31 groups half decided: "when I
-- click Use the photo reappears"). A decision is on the picture: the copies with none take it, Don't use winning.
UPDATE photos
   SET clearance = (SELECT CASE WHEN SUM(p2.clearance = 'blocked') > 0 THEN 'blocked' ELSE 'cleared' END
                      FROM photos p2 WHERE p2.md5 = photos.md5 AND p2.trashed = 0 AND p2.clearance IN ('cleared', 'blocked')),
       clearance_at = (SELECT MAX(p2.clearance_at) FROM photos p2
                        WHERE p2.md5 = photos.md5 AND p2.trashed = 0 AND p2.clearance IN ('cleared', 'blocked'))
 WHERE trashed = 0 AND clearance = 'inherit' AND md5 IS NOT NULL
   AND md5 IN (SELECT md5 FROM photos WHERE trashed = 0 AND clearance IN ('cleared', 'blocked'));
