-- 2026-11-02, Chris: "And I thought you got rid of the duplicates and I still see so many". The same picture is also
-- saved as other files (a low-res export beside the original, the client's copies filed per person: 620 pictures put
-- 825 extra cards on To review), so "the same picture" is stored rather than read off the md5 at every turn:
-- photos.picture is the id of the photo that stands for it (library/copies.py, whose pass the scanner runs after every
-- inventory). Filled here for what SQL can tell, by that pass's order (copies.stands_first): identical files stand
-- behind one of them, in Drive and sorted by a model first, then the lowest id; every other photo stands for itself, so
-- nothing regresses before the first pass.
ALTER TABLE photos ADD COLUMN picture INTEGER;
UPDATE photos
   SET picture = COALESCE((SELECT p2.id FROM photos p2 LEFT JOIN classifications c ON c.photo_id = p2.id
                            WHERE p2.md5 = photos.md5
                            ORDER BY p2.trashed, COALESCE(c.method IN ('ollama', 'vision'), 0) DESC, p2.id LIMIT 1), id);
CREATE INDEX IF NOT EXISTS idx_photos_picture ON photos (picture);
