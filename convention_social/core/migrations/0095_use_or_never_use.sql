-- 2026-11-02, Chris: "MANY of the approved photos, I never approved and say ready to use which is a very huge problem".
-- Two folders his iPhone had approved whole on 2026-10-11 (Approve all) made 1,648 photos ready to use that he had
-- never looked at. He chose that a photo is only ever approved by his own Use on it: no folder approves any more. The
-- two folders were taken back by hand the same day, keeping what was live as his Use (the 45 photos on the website,
-- the photos of every post he had approved); the phone's own folder had marked itself approved, and its photos are
-- each his Use already.
UPDATE drive_folders
   SET clearance = 'not_cleared', clearance_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
 WHERE clearance = 'cleared';

-- "The don't use photos I click should be never use ... moving forward it's just use and never use." Never use is the
-- photo's own decision ('blocked', on every identical copy); a photo he had put on the do-not-use list with the old
-- Never use button is Never use on the photo too, so it shows on the Never use list with the others.
UPDATE photos
   SET clearance = 'blocked', clearance_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
 WHERE trashed = 0 AND clearance <> 'blocked'
   AND (drive_id IN (SELECT value FROM do_not_use WHERE kind = 'photo')
        OR (md5 IS NOT NULL AND md5 IN (SELECT md5 FROM photos
                                         WHERE drive_id IN (SELECT value FROM do_not_use WHERE kind = 'photo'))));
