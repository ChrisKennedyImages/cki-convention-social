-- Chris, 2026-11-06: "Never go to my phone photos backup". Drive's "Google Photos" folder at the top of My Drive
-- (16,205 photos in 95 folders on the day) leaves the inventory: no photo in it had been sorted, shown on To review,
-- copied off Drive or posted. The scanner never lists it again (drive/scan.py, NEVER_READ_KEY). Drive is not touched:
-- these are the suite's own rows about those files.
CREATE TEMP TABLE backup_folder AS
WITH RECURSIVE tree(id) AS (
    SELECT drive_id FROM drive_folders WHERE path = 'My Drive/Google Photos'
    UNION SELECT f.drive_id FROM drive_folders f JOIN tree t ON f.parent_id = t.id
)
SELECT id FROM tree;
INSERT OR REPLACE INTO settings (key, value, updated_at)
    SELECT 'drive.never_read_ids', json_group_array(id), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') FROM temp.backup_folder;
CREATE TEMP TABLE backup_photo AS SELECT id FROM photos WHERE folder_id IN (SELECT id FROM temp.backup_folder);
-- a copy elsewhere that one of them stood for stands for itself until the next pass links it again (library/copies.py)
UPDATE photos SET picture = NULL WHERE picture IN (SELECT id FROM temp.backup_photo);
DELETE FROM classifications WHERE photo_id IN (SELECT id FROM temp.backup_photo);
DELETE FROM final_checks WHERE photo_id IN (SELECT id FROM temp.backup_photo);
DELETE FROM photo_seo WHERE photo_id IN (SELECT id FROM temp.backup_photo);
DELETE FROM photo_use WHERE photo_id IN (SELECT id FROM temp.backup_photo);
DELETE FROM phone_sends WHERE photo_id IN (SELECT id FROM temp.backup_photo);
DELETE FROM photos WHERE id IN (SELECT id FROM temp.backup_photo);
DELETE FROM drive_folders WHERE drive_id IN (SELECT id FROM temp.backup_folder);
DROP TABLE temp.backup_photo;
DROP TABLE temp.backup_folder;
