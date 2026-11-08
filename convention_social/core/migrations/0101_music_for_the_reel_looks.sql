-- The ten reel looks (Chris, 2026-11-08: "Yes, build it."; render/reel_looks.py) each take a track that suits the look,
-- started on its own second. Four facts a look needs about a track, and the values of the Pixabay tracks Chris added
-- on 2026-11-08, from the ledger that came with them (title, artist, start, tempo) and the tracks the approved reels
-- had (which looks each suits). A track not named here suits no look until its looks are set.
ALTER TABLE music_tracks ADD COLUMN start_s REAL NOT NULL DEFAULT 0;   -- the second of the track a reel starts on
ALTER TABLE music_tracks ADD COLUMN bpm REAL NOT NULL DEFAULT 0;       -- its tempo as measured; 0 when not measured
ALTER TABLE music_tracks ADD COLUMN grid REAL NOT NULL DEFAULT 0;      -- the tempo it is played at so its beats land on a
--                                                                        look's cuts (120: the looks' grid); 0 plays it as recorded
ALTER TABLE music_tracks ADD COLUMN looks TEXT NOT NULL DEFAULT '[]';  -- the looks it suits, a JSON list of reel_looks.LOOKS

UPDATE music_tracks SET start_s = 0, bpm = 0, grid = 0, looks = '["manifesto", "titles"]'
 WHERE title = 'Upbeat Electronic' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 9.5, bpm = 0, grid = 0, looks = '["manifesto", "splitscreen"]'
 WHERE title = 'Upbeat And Inspiring' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 0, bpm = 0, grid = 0, looks = '["stillness"]'
 WHERE title = 'Acoustic Background' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 0, bpm = 0, grid = 0, looks = '["stillness"]'
 WHERE title = 'Acoustic Guitar Sunrise Travel' AND artist = 'alex-morgan';
UPDATE music_tracks SET start_s = 0, bpm = 0, grid = 0, looks = '["powersoften", "section"]'
 WHERE title = 'Inspiration Corporate' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 0, bpm = 0, grid = 0, looks = '["darkroom", "section"]'
 WHERE title = 'Elegant Corporate' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 1.0, bpm = 0, grid = 0, looks = '["titles", "splitscreen"]'
 WHERE title = 'Upbeat Happy Corporate' AND artist = 'kornevmusic';
UPDATE music_tracks SET start_s = 0.7, bpm = 0, grid = 0, looks = '["darkroom", "weather"]'
 WHERE title = 'Corporate Ambient' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 1.0, bpm = 0, grid = 0, looks = '["powersoften", "weather"]'
 WHERE title = 'Inspiring Cinematic Music' AND artist = 'Tunetank';
UPDATE music_tracks SET start_s = 17.986, bpm = 114.96, grid = 120, looks = '["chiaroscuro"]'
 WHERE title = 'Piano And Strings' AND artist = 'AtlasAudio';
UPDATE music_tracks SET start_s = 84.7506, bpm = 121.1, grid = 120, looks = '["chiaroscuro"]'
 WHERE title = 'Emotional Cinematic Orchestra Piano' AND artist = 'echoes_of_lumen';
UPDATE music_tracks SET start_s = 17.5432, bpm = 113.99, grid = 120, looks = '["axis"]'
 WHERE title = 'Tension - Tension Music' AND artist = 'NastelBom';
UPDATE music_tracks SET start_s = 34.995, bpm = 120.03, grid = 120, looks = '["axis"]'
 WHERE title = 'Suspense Tension Trailer' AND artist = 'lNPLUSMUSIC';
