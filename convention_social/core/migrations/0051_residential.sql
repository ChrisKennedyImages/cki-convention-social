-- Chris, 2026-10-10, correcting the ruling an hour after making it: bars are fine anywhere,
-- the line is residential. Asking which room type a frame shows cannot carry that rule on its
-- own, because a flat's hallway and a hotel's hallway are both corridors. So the sort asks
-- outright whether the space is somebody's home, and the gate turns on the answer.
ALTER TABLE classifications ADD COLUMN residential INTEGER;   -- 1 when the space is somebody's home
