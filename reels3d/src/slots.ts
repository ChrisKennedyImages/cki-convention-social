import type { Photo, Props, Tile } from "./lib";

// Every picture a slot of its own (Chris, 2026-11-08, night: no picture twice in a reel), as in the ten looks
// (reel-looks/src/slots.ts). Only type imports, so Node runs this file as it is: tests/test_reel_slots.py asks it what a
// slot the props do not hold does, and what the card check's renders draw.

export type Kind = "photos" | "fillers";
/** One picture of the reel: the post's photo or the filler in slot `index`. */
export type Slot = { kind: Kind; index: number };

/** The card check (convention_social/render/reel_check.py, its 3D mode): `probe` says on the console which line of a
 *  style asks for each slot's texture; `codes` numbers every slot at every line the probe heard, and a render then draws
 *  each one's white card (its file with "-lit" before ".jpg") where bit `bit` of its number is 1 (0 when `inverse`) and
 *  its black card where not, so a handful of renders tells every place on screen apart. Never in a reel the suite makes. */
export type Check = { probe?: boolean; codes?: Record<string, number>; bit?: number; inverse?: boolean };

/** A style shows exactly the fillers the props hold, `want` for this many of the post's photos: a style short of a
 *  picture would fill the slot by showing another one again, and a filler it does not show was taken for nothing. */
export const checkFillers = (p: Props, want: number, style: string): void => {
  if (p.fillers.length !== want) {
    throw new Error(`${style} shows ${p.photos.length} photos and ${want} fillers; the props hold ${p.fillers.length} fillers`);
  }
};

const picture = (p: Props, kind: Kind, i: number): Photo | Tile => {
  const list: (Photo | Tile)[] = p[kind];
  if (!Number.isInteger(i) || i < 0 || i >= list.length) {
    throw new Error(`no ${kind === "photos" ? "photo" : "filler"} slot ${i}: the props hold ${list.length}`);
  }
  return list[i];
};
/** The post's photo in slot i (its file, size, room and line). A slot the props do not hold stops the render. */
export const photoAt = (p: Props, i: number): Photo => picture(p, "photos", i) as Photo;
/** The filler in slot k. A slot the props do not hold stops the render. */
export const fillerAt = (p: Props, k: number): Tile => picture(p, "fillers", k);

/** A card's white file beside its black one, in the card check. */
export const lit = (src: string): string => src.replace(/\.jpg$/, "-lit.jpg");

/** Where in a style a slot was asked for: the two stack frames past drawnFrom (the line that asked, and the line that
 *  called it), each "line:column" of the bundle, the same in every render of one bundle. Only the card check asks. */
const siteOf = (stack: string): string =>
  stack.split("\n").filter((l) => l.trim().startsWith("at ")).slice(2, 4).map((l) => {
    const at = l.match(/:(\d+:\d+)\)?\s*$/);
    return at ? at[1] : l.trim().replace(/\s+/g, "_");
  }).join("<");

/** For the card check's probe: the frames of the 30-a-second timeline (index f) each slot's card is inside the frame, by
 *  the style's own geometry, whatever covers it. A card hidden behind another card in front of it while it stays in the
 *  frame (Ring's next card sliding over it to its place, Wall's tiles behind the lifted photo) is one pass to the check;
 *  a card that leaves the frame and comes back is two. Said once a slot on the console; never in a reel the suite makes. */
export const reportPresence = (p: Props, cards: { kind: Kind; index: number; inFrame: boolean[] }[]): void => {
  if (!p.check?.probe) return;
  for (const c of cards) console.log(`REELIN ${c.kind} ${c.index} ${c.inFrame.map((on) => (on ? "1" : "0")).join("")}`);
};

/** For the card check's probe, a style laid on one still plane (Loop's grid): the cell each slot's card has on it. The
 *  camera passing back over a cell whose place on the still grid is unchanged is one picture in one place (the
 *  coordinator's ruling for Loop, 2026-11-09, pending Chris); a picture in two cells is shown twice. */
export const reportCells = (p: Props, cards: { kind: Kind; index: number; x: number; y: number }[]): void => {
  if (!p.check?.probe) return;
  for (const c of cards) console.log(`REELCELL ${c.kind} ${c.index} ${c.x.toFixed(3)},${c.y.toFixed(3)}`);
};

/** The file a slot's texture is drawn from where it is drawn: its own, or in the card check its white or black card
 *  at this place. A place the probe never heard stops the render, so nothing drawn escapes the check. */
export const drawnFrom = (p: Props, kind: Kind, i: number): string => {
  const src = picture(p, kind, i).src;
  if (!p.check) return src;
  const site = siteOf(new Error().stack ?? "");
  if (p.check.probe) {
    console.log(`REELCHECK ${kind} ${i} ${site}`);
    return src;
  }
  const code = p.check.codes?.[`${kind} ${i} ${site}`];
  if (code === undefined) throw new Error(`the card check never heard ${kind} ${i} asked for at ${site}`);
  const white = ((code >> (p.check.bit ?? 0)) & 1) === 1;
  return white !== Boolean(p.check.inverse) ? lit(src) : src;
};
