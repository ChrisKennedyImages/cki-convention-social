import type { Photo, ReelProps } from "./look";

// Every slot a picture of its own (Chris, 2026-11-08, night: no picture twice in a reel). Only type imports, so Node
// runs this file as it is: tests/test_reel_slots.py asks it what a slot the props do not hold does.

/** How many pictures a look shows: `photos`, the post's own (the hero first, then the photos its words go with, then
 *  the look's other slots for them), and `fillers`, more of Chris's approved photos for every other slot (a contact
 *  sheet, a gallery, a montage). Each slot is a picture of its own: no picture is shown twice in a reel (Chris,
 *  2026-11-08, night). Every look exports its SLOTS; the suite gives it exactly that many (render/reel_looks.SLOTS).
 *  `fillersFrom`: a look whose layout places as many fillers as its photos' shapes allow (Powers of Ten's mosaic) takes
 *  from that many to `fillers`, and stops its render if it would leave one of them unplaced. */
export type Slots = { photos: number; fillers: number; fillersFrom?: number };

/** The props hold exactly the slots the look shows and three different word photos among its photos; anything else
 *  stops the render, so a look is never short of a picture it would fill by showing another one again. */
export const checkSlots = (p: ReelProps, slots: Slots, look: string): void => {
  const given = { photos: p.photos?.length ?? 0, fillers: p.fillers?.length ?? 0 };
  const least = slots.fillersFrom ?? slots.fillers;
  if (given.photos !== slots.photos || given.fillers < least || given.fillers > slots.fillers) {
    const fillers = least === slots.fillers ? `${slots.fillers}` : `${least} to ${slots.fillers}`;
    throw new Error(`${look} shows ${slots.photos} photos and ${fillers} fillers; the props hold ${given.photos} and ${given.fillers}`);
  }
  const w = p.wordPhotos ?? [];
  if (w.length !== 3 || new Set(w).size !== 3 || w.some((i) => !Number.isInteger(i) || i < 0 || i >= slots.photos)) {
    throw new Error(`${look}: the three words go on three different photos of its ${slots.photos}; wordPhotos is ${JSON.stringify(w)}`);
  }
};

/** Where in the look a slot was asked for: the two stack frames past slot() and photoAt or fillerAt (the line that asked,
 *  and the line that called it, so a helper such as Darkroom's own() is told apart by its callers), each "line:column"
 *  of the bundle, the same in every render of one bundle. Only the card check asks. */
const siteOf = (stack: string): string =>
  stack.split("\n").filter((l) => l.trim().startsWith("at ")).slice(2, 4).map((l) => {
    const at = l.match(/:(\d+:\d+)\)?\s*$/);
    return at ? at[1] : l.trim().replace(/\s+/g, "_");
  }).join("<");

const slot = (p: ReelProps, kind: "photos" | "fillers", i: number): Photo => {
  const list = p[kind];
  if (!Number.isInteger(i) || i < 0 || i >= list.length) throw new Error(`no ${kind === "photos" ? "photo" : "filler"} slot ${i}: the props hold ${list.length}`);
  const pic = list[i];
  if (!p.check) return pic;
  const site = siteOf(new Error().stack ?? "");
  if (p.check.probe) console.log(`REELCHECK ${kind} ${i} ${site}`);
  const l = p.check.light;
  return l && l.kind === kind && l.index === i && l.site === site ? { ...pic, src: pic.src.replace(/\.jpg$/, "-lit.jpg") } : pic;
};
/** The post's photo in slot i. A slot the props do not hold stops the render. */
export const photoAt = (p: ReelProps, i: number): Photo => slot(p, "photos", i);
/** The filler in slot k. A slot the props do not hold stops the render. */
export const fillerAt = (p: ReelProps, k: number): Photo => slot(p, "fillers", k);
/** A picture's shape (width over height) from its props: the size of the file the suite wrote (copy_photo), known before
 *  the file loads, so every pass of a layout and the suite's own (reel-looks/mosaic-fillers.mjs) lay it out alike. */
export const shapeOf = (pic: Photo): number => {
  if (!(pic.w && pic.h && pic.w > 0 && pic.h > 0)) throw new Error(`no size in the props for ${pic.src}`);
  return pic.w / pic.h;
};
/** Every picture the reel shows, the photos then the fillers: what a look reads the shapes of before its first frame. */
export const everyPicture = (p: ReelProps): Photo[] => [...p.photos, ...p.fillers];
