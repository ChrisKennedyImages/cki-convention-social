-- What an architecture frame actually shows, and how strong the picture is.
--
-- Chris, 2026-10-10, after the first building contact sheet: the architecture work is
-- buildings, never rooms. It must never include an empty room, a bathroom, a closet or a
-- residential interior. The library's building work is largely commissioned real estate
-- photography of apartments, so without naming the space there is no way to keep those out.
--
-- The strength columns replace a single vague "quality" guess as the thing the contact sheet
-- ranks by. A 1 to 5 asked once gave 16 photos at 5 and a cliff below; asking whether the
-- subject is sharp, what the light is doing and whether anything is happening gives something
-- that can actually order a shortlist.
ALTER TABLE classifications ADD COLUMN space TEXT;            -- exterior | lobby | bathroom | residential_room | ...
ALTER TABLE classifications ADD COLUMN empty_room INTEGER;    -- 1 when a room is unpeopled and unfurnished
ALTER TABLE classifications ADD COLUMN sharp INTEGER;         -- 1 when the main subject is in focus
ALTER TABLE classifications ADD COLUMN light INTEGER;         -- 1 flat or blown .. 5 light that makes the picture
ALTER TABLE classifications ADD COLUMN moment INTEGER;        -- 1 nothing happening .. 5 a real moment
