-- Chris, 2026-10-15, on the first round of new post designs: "After Dark" was printed on a sunny garden and "Main
-- Stage" on a reception room, from the sorter's shot type. A post now prints a room's name only when Claude's final
-- check of the full photo says the photo plainly shows that room (render/design_samples.ROOM_WORDS); a photo checked
-- before this column, or with none, says EVENT PHOTOGRAPHY.
ALTER TABLE final_checks ADD COLUMN room TEXT;
