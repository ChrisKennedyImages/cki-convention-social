import type { Photo, Tile } from "./lib";
import type { Slot } from "./slots";

// Loop's grid (Loop.tsx), laid out where Node runs it too: reels3d/loop-fillers.mjs tells the suite how many fillers a
// grid of these photos lays. Level rows of cards, every card its own shape, tight even gaps; the reel's four photos are
// the cards the loop visits, its fifth and sixth photo and the fillers the other cards. Every card is a picture of its
// own (Chris, 2026-11-08, night: no picture twice in a reel), and a row holds only the cards that come into the frame:
// the grid slides between the four visited cards and the camera never sees the rest of a row, so a card there would be a
// photo taken and never shown. Only type imports, so Node runs this file as it is.

export const FOV = 30;
export const TAN = Math.tan((FOV * Math.PI) / 360);
const ASPECT = 1080 / 1920;                                    // the reel's frame (lib.tsx W / H)
export const VIEW_W = 2 * TAN * ASPECT;                        // the width in view per unit of distance to the grid
export const ROW_H = 1.5, GAP_X = 0.16, GAP_Y = 0.42;          // rows of one height; a little more room under for the label
export const ROWS = 11;
export const PITCH_Y = ROW_H + GAP_Y;
export const Z = (ROW_H * 1.5) / (0.66 * VIEW_W);             // the grid at rest: a 3:2 card is two thirds of the width
export const ENLARGE = 1.2;                                    // the whole grid, while the loop crosses a card: that photo bigger
// where the four visited cards sit: (row, x) in the middle rows, each a step or two from the last, so the slide reads
export const VISITS: [number, number][] = [[5, 0], [4, 1.6], [3, 0.2], [4, -1.8]];
const SHOWN_SHARE = 0.001;                                     // a card is laid where it shows 0.1 % of the frame (lib.tsx SHOWN_PX)

export type Card = { x: number; y: number; w: number; h: number; p: Tile; slot: Slot };
export const shape = (p: Tile) => Math.min(16 / 9, Math.max(2 / 3, p.w / p.h));   // aspect kept between 2:3 and 16:9
export const rowY = (r: number) => ((ROWS - 1) / 2 - r) * PITCH_Y;

// Where the grid stands in the reel (Loop.tsx gridAt): resting on each visited card, from 1 to ENLARGE, and sliding,
// level, from one to the next while it shrinks back from ENLARGE to 1. The frame sees the most of it at 1.
type Stand = { x: number; y: number; s: number };
const standsOver = (visit: { x: number; y: number }[]): Stand[] => visit.flatMap((c, k) => {
  if (k === 0) return [{ x: c.x, y: c.y, s: 1 }];
  const a = visit[k - 1];
  return Array.from({ length: 241 }, (_, n) => {
    const u = n / 240;
    return { x: a.x + (c.x - a.x) * u, y: a.y + (c.y - a.y) * u, s: ENLARGE - (ENLARGE - 1) * u };
  });
});
const halfView = (s: number) => ({ hw: (Z * VIEW_W) / 2 / s, hh: (Z * TAN) / s });
// the most of the frame a card at (x, y), w wide, ever fills
const mostShown = (x: number, y: number, w: number, stands: Stand[]) => Math.max(0, ...stands.map((st) => {
  const { hw, hh } = halfView(st.s);
  const ox = Math.min(x + w / 2, st.x + hw) - Math.max(x - w / 2, st.x - hw);
  const oy = Math.min(y + ROW_H / 2, st.y + hh) - Math.max(y - ROW_H / 2, st.y - hh);
  return ox > 0 && oy > 0 ? (ox * oy) / (4 * hw * hh) : 0;
}));

/** The grid: its cards, the four visited ones among them (in the order the loop visits them), and how many of the props'
 *  other pictures (the fifth and sixth photo, then the fillers, in turn) it laid, each once. Each visited card is laid on
 *  its spot (a second in its row as near its spot as the cards between allow); then each row reaches out, card by card,
 *  while a card there, however narrow, would come into the frame. Where a card goes never hangs on a picture the grid has
 *  not laid yet, so the props trimmed to the pictures it laid lay the same grid. A grid that needs a picture more than the
 *  props hold stops. */
export const layout = (photos: Photo[], fillers: Tile[]): { cards: Card[]; visit: Card[]; laid: number } => {
  const others: Slot[] = [
    ...photos.slice(VISITS.length).map((_, i): Slot => ({ kind: "photos", index: VISITS.length + i })),
    ...fillers.map((_, k): Slot => ({ kind: "fillers", index: k })),
  ];
  let laid = 0;
  const rows: Card[][] = Array.from({ length: ROWS }, () => []);
  const card = (r: number, x: number, p: Tile, slot: Slot): Card => ({ x, y: rowY(r), w: ROW_H * shape(p), h: ROW_H, p, slot });
  const put = (r: number, c: Card) => { rows[r].push(c); rows[r].sort((a, b) => a.x - b.x); };
  // the next of the other pictures, as a card in row r at the middle `at` gives for its width
  const lay = (r: number, at: (w: number) => number) => {
    if (laid >= others.length) throw new Error(`Loop's grid lays more cards than the props hold pictures for (${others.length})`);
    const slot = others[laid++], p = slot.kind === "photos" ? photos[slot.index] : fillers[slot.index];
    put(r, card(r, at(ROW_H * shape(p)), p, slot));
  };
  // the middle of a card w wide beside the row's end (+1 right, -1 left)
  const beside = (r: number, side: 1 | -1, w: number) => {
    const end = side > 0 ? rows[r][rows[r].length - 1] : rows[r][0];
    return end.x + side * (end.w / 2 + GAP_X + w / 2);
  };
  const visit: Card[] = [];
  VISITS.forEach(([r, at], v) => {
    if (v >= photos.length) return;
    const p = photos[v], w = ROW_H * shape(p);
    if (rows[r].length) {
      // a second visited card in its row: the cards between, until one more would put it further from its spot
      const side: 1 | -1 = at > rows[r][0].x ? 1 : -1;
      const nextW = () => (laid < others.length ? ROW_H * shape(others[laid].kind === "photos" ? photos[others[laid].index] : fillers[others[laid].index]) : Infinity);
      while (Math.abs(beside(r, side, nextW() + GAP_X + w) - at) < Math.abs(beside(r, side, w) - at)) lay(r, (cw) => beside(r, side, cw));
      at = beside(r, side, w);
    }
    visit.push(card(r, at, p, { kind: "photos", index: v }));
    put(r, visit[visit.length - 1]);
  });
  const stands = standsOver(visit);
  const NARROWEST = ROW_H * (2 / 3);
  const comesIn = (x: number, y: number) => mostShown(x, y, NARROWEST, stands) >= SHOWN_SHARE;
  rows.forEach((row, r) => {
    const y = rowY(r);
    if (!row.length) {
      // a row with no visited card: its first card in the middle of the stretch of it the frame ever sees
      const seen = stands.filter((st) => Math.abs(st.y - y) < halfView(st.s).hh + ROW_H / 2);
      if (!seen.length) return;
      const mid = (Math.min(...seen.map((st) => st.x - halfView(st.s).hw)) + Math.max(...seen.map((st) => st.x + halfView(st.s).hw))) / 2;
      if (!comesIn(mid, y)) return;
      lay(r, () => mid);
    }
    for (const side of [1, -1] as const) {
      while (comesIn(beside(r, side, NARROWEST), y)) lay(r, (w) => beside(r, side, w));
    }
  });
  return { cards: rows.flat(), visit, laid };
};
