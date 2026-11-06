-- Chris, 2026-11-06: "And duplicates stacked as one". The same picture saved under another name (LOR_1573.jpg,
-- LOR_1573-edit.jpg, 1-Texas_2022LOR_1573-TEXAS2022.jpg) with its camera time changed or gone was a card of its own.
-- picture_hash: a 64-bit difference hash of the photo's Drive preview, in hex, read only for photos that share a camera
-- frame number and a shape with another photo (library/copies.py); two such photos whose hashes agree are one picture.
ALTER TABLE photos ADD COLUMN picture_hash TEXT;
