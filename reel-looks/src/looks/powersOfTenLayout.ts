import type { Photo, ReelProps } from "../look";

// Powers of Ten's world and its one camera move, apart from the drawing so they can be checked without a browser
// (tests/powers_of_ten_windows.mjs, run by tests/test_reel_looks.py): the mosaic of photos, the move, and the frames
// each beat word is on screen. Only type imports, so Node runs this file as it is.

export const W = 1080, H = 1920;                          // the frame (look.ts W, H)
export const M = 64;                                      // the side margin
export const CX = W / 2, CY = 1000;                       // where the hero's centre (the zoom's centre) sits on screen
export const TOP_STRIP = 330, STRIP = 150;                // the title strip at the top, the readout at the foot
export const STRIP_UP = 366;                              // the title strip lifts away as the map comes in

// ------------------------------------------------------------------ the mosaic: one plane of his photos

export type Pic = { src: string; a: number; word?: number };
/** A placed photo, in world units (the hero is 1080 wide). `band`: a word's dark caption band, above or below it. */
export type Cell = { src: string; x: number; y: number; w: number; h: number; word?: number; band?: { y: number; h: number } };
export type Mosaic = { cells: Cell[]; x0: number; y0: number; x1: number; y1: number };
export const BAND_K = 0.3;                               // a caption band's height, as a share of its photo's height

/** Every order of a few photos. */
const orders = (xs: Pic[]): Pic[][] => (xs.length <= 1 ? [xs] : xs.flatMap((c, i) => orders([...xs.slice(0, i), ...xs.slice(i + 1)]).map((r) => [c, ...r])));

/** How far a row's word photos sit from the middle of the frame (x = 0) when the row is laid in this order from x0:
 *  0 when every word photo crosses the middle, which keeps it in view all through the move. */
const offMiddle = (order: Pic[], len: number, x0: number, along: (c: Pic) => number) => {
  const gap = 0.02 * len, t = (len - (order.length - 1) * gap) / order.reduce((s, c) => s + along(c), 0);
  let x = x0, off = 0;
  for (const c of order) {
    const w = t * along(c);
    if (c.word !== undefined) off = Math.max(off, x, -(x + w), 0);
    x += w + gap;
  }
  return off;
};

/** Where the two word photos besides the hero go: in the bottom rows of rings 1 and 2, or both in ring 1's; `swap` puts
 *  word 2's photo in the first; `centred` lets a word row take up to five photos so a word photo can cross the middle of
 *  the frame. `world` tries them in this order and keeps the first that holds every word WORD_HOLD frames (else the one
 *  whose shortest word is longest). The first is the look as approved, its word photos moved to the middle of their rows.
 *  Why: on a reel of 2026-11-08 a word photo led its row at the frame's edge and its word never came on screen; Chris's
 *  rule is that every word is seen beside its own photo. */
export type Placement = { rings: "1 and 2" | "1"; swap: boolean; centred: boolean };
export const PLACEMENTS: Placement[] = [
  { rings: "1 and 2", swap: false, centred: false }, { rings: "1 and 2", swap: true, centred: false }, { rings: "1", swap: false, centred: false },
  { rings: "1 and 2", swap: false, centred: true }, { rings: "1 and 2", swap: true, centred: true }, { rings: "1", swap: false, centred: true },
];

/** Rings round the hero, edge to edge with small dark gaps: each ring a column of photos either side (stacked to the
 *  block's full height), then a row above and below (spanning its full width), every photo whole at its own shape. Each
 *  ring is the same factor bigger than the last in both directions (so the wall keeps a tall frame's shape and the hero
 *  stays at its heart), as many rings as the photos allow, the factor set so the wall is just big enough to fill the
 *  frame for as long as asked (`cover`: how far the camera may pull back before the frame shows past its edge). The
 *  reel's own photos sit nearest the centre; the hero carries the first word in a band beneath it, the other two word
 *  photos sit in bottom rows by `placement`, their words in a band above them. */
export const buildMosaic = (p: ReelProps, aspect: (pic: Photo) => number, cover: number, placement: Placement = PLACEMENTS[0]): Mosaic => {
  const idx = p.wordPhotos ?? [0, 1, 2];
  const wordOf = (i: number) => { const n = idx.indexOf(i); return n < 0 ? undefined : n; };
  const reel = (i: number): Pic => ({ src: p.photos[i].src, a: aspect(p.photos[i]), word: wordOf(i) });
  const wordRest = idx.filter((i) => i !== 0);
  const queue: Pic[] = [1, 2, 3, 4, 5].filter((i) => i < p.photos.length && !wordRest.includes(i)).map(reel).concat((p.tiles ?? []).map((t) => ({ src: t.src, a: t.w / t.h })));
  const wordQueue: Pic[] = wordRest.map(reel);
  if (placement.swap) wordQueue.reverse();
  const cellA = (c: Pic) => (c.word === undefined ? c.a : c.a / (1 + BAND_K));
  const cells: Cell[] = [];
  const place = (c: Pic, x: number, y: number, w: number, hCell: number, bandAbove: boolean) => {
    if (c.word === undefined) { cells.push({ src: c.src, x, y, w, h: hCell }); return; }
    const h = hCell / (1 + BAND_K), bh = hCell - h;
    cells.push({ src: c.src, x, w, h, y: bandAbove ? y + bh : y, word: c.word, band: { y: bandAbove ? y : y + h, h: bh } });
  };
  // the hero, its word (if it has one) in a band beneath it
  const hero = reel(0);
  const hw = 1080, hh = hw / cellA(hero);
  place(hero, -hw / 2, -hh / 2, hw, hh, false);
  let b = { x0: -hw / 2, y0: -hh / 2, x1: hw / 2, y1: hh / 2 };
  const covers = () => 1 / Math.max(CX / -b.x0, (W - CX) / b.x1, CY / -b.y0, (H - CY) / b.y1);
  const photos = queue.length + wordQueue.length;
  const rings = Math.max(1, Math.min(Math.round(Math.log(cover / covers()) / Math.log(2.4)), Math.floor(photos / 8)));
  const grow = Math.pow(cover / covers(), 1 / rings);
  // a justified run of photos along a side of length `len`: how many give a thickness nearest `want`
  const pick = (len: number, want: number, along: (c: Pic) => number, first: Pic[], max: number, take = true) => {
    let k = Math.max(1, first.length), best = 1e12;
    for (let n = Math.max(1, first.length); n <= Math.min(max, first.length + queue.length); n++) {
      const list = [...first, ...queue.slice(0, n - first.length)];
      const t = (len - (n - 1) * 0.02 * len) / list.reduce((s, c) => s + along(c), 0);
      if (Math.abs(Math.log(t / want)) < best) { best = Math.abs(Math.log(t / want)); k = n; }
    }
    return [...first, ...(take ? queue.splice(0, k - first.length) : queue.slice(0, k - first.length))];
  };
  // a row that carries word photos: the run (the words, then the next in the queue) and the order that put the word photos
  // across the middle of the frame (centred: of runs up to five photos; else as `pick` sizes it), the thickness nearest
  // `want` between equals
  const wordRow = (words: Pic[], len: number, want: number): Pic[] => {
    const sizes = placement.centred ? [words.length, Math.min(5, words.length + queue.length)]
      : [pick(len, want, cellA, words, Math.max(3, words.length + 1), false).length];
    let best: Pic[] = words, score = Infinity;
    for (let n = sizes[0]; n <= sizes[sizes.length - 1]; n++) {
      const run = [...words, ...queue.slice(0, n - words.length)];
      const t = (len - (n - 1) * 0.02 * len) / run.reduce((s, c) => s + cellA(c), 0);
      for (const o of orders(run)) {
        const sc = offMiddle(o, len, b.x0, cellA) * 1000 + Math.abs(Math.log(t / want));
        if (sc < score) { score = sc; best = o; }
      }
    }
    queue.splice(0, best.length - words.length);
    return best;
  };
  for (let ring = 1; ring <= rings && queue.length + wordQueue.length > 0; ring++) {
    const bw = b.x1 - b.x0, bh = b.y1 - b.y0;
    for (const side of [-1, 1]) {
      if (!queue.length) break;
      const list = pick(bh, ((grow - 1) / 2) * bw, (c) => 1 / cellA(c), [], 6);
      const gap = 0.02 * bh, t = (bh - (list.length - 1) * gap) / list.reduce((s, c) => s + 1 / cellA(c), 0);
      const x = side < 0 ? b.x0 - gap - t : b.x1 + gap;
      let y = b.y0;
      list.forEach((c) => { const h = t / cellA(c); place(c, x, y, t, h, false); y += h + gap; });
      if (side < 0) b = { ...b, x0: x }; else b = { ...b, x1: x + t };
    }
    for (const side of [-1, 1]) {
      // the bottom rows of rings 1 and 2 carry the other two word photos (the last ring takes what is left, so one ring
      // can carry both), each where the row crosses the middle of the frame, so the camera keeps it in view
      const words = side > 0 && ring <= 2 ? wordQueue.splice(0, placement.rings === "1" || ring === rings || ring === 2 ? wordQueue.length : 1) : [];
      if (!queue.length && !words.length) continue;
      const nbw = b.x1 - b.x0;
      const list = words.length ? wordRow(words, nbw, ((grow - 1) / 2) * bh) : pick(nbw, ((grow - 1) / 2) * bh, cellA, words, 3);
      const gap = 0.02 * nbw, t = (nbw - (list.length - 1) * gap) / list.reduce((s, c) => s + cellA(c), 0);
      const y = side < 0 ? b.y0 - gap - t : b.y1 + gap;
      let x = b.x0;
      list.forEach((c) => { const w = t * cellA(c); place(c, x, y, w, t, side > 0); x += w + gap; });
      if (side < 0) b = { ...b, y0: y }; else b = { ...b, y1: y + t };
    }
  }
  return { cells, ...b };
};

// ------------------------------------------------------------------ the camera: one move

export const EASE_IN = 15, SETTLE = 40, END = 480;
/** Time along the move: a gentle ease off the mark, constant, then a settle onto the last frame. */
export const tau = (g: number) => {
  if (g < EASE_IN) return (g * g) / (2 * EASE_IN);
  const t1 = END - SETTLE;
  if (g < t1) return g - EASE_IN / 2;
  const x = Math.min(1, (g - t1) / SETTLE);
  return t1 - EASE_IN / 2 + SETTLE * (x - x * x * x + (x * x * x * x) / 2);
};
export const TAU_END = tau(END);
// The screen's rate: slow enough that the mosaic is still a wall half the frame wide at 12.5 s; the mosaic is built just
// big enough to fill the frame until 10.5 s at that rate (frame 315), so only the last seconds open onto the map.
export const RATE = 0.005, FILL_UNTIL = 315;

/** The mosaic for these props and photo shapes, and the move over it: one constant exponential rate, slow enough that
 *  the mosaic fills the frame to about 10.5 s (frame 315) and is still a wall half the frame wide at 12.5 s. Of the word
 *  placements (PLACEMENTS), the one whose shortest word window is longest, the first between equals. */
export const world = (p: ReelProps, aspect: (pic: Photo) => number) => {
  const shortest = (w: [number, number][]) => Math.min(...[0, 1, 2].map((k) => (w[k] ? w[k][1] - w[k][0] : -1)));
  let best: { mosaic: Mosaic; scaleAt: (f: number) => number; windows: [number, number][] } | null = null;
  for (const place of PLACEMENTS) {
    const mosaic = buildMosaic(p, aspect, Math.pow(10, RATE * tau(FILL_UNTIL)), place);
    const sCover = Math.max(CX / -mosaic.x0, (W - CX) / mosaic.x1, CY / -mosaic.y0, (H - CY) / mosaic.y1);
    const rate = Math.min(Math.log10(1 / sCover) / tau(FILL_UNTIL), RATE);
    const scaleAt = (f: number) => Math.pow(10, -rate * tau(f));
    const windows = wordWindows(mosaic, scaleAt);
    if (best === null || shortest(windows) > shortest(best.windows)) best = { mosaic, scaleAt, windows };
    if (shortest(windows) >= WORD_HOLD) break;          // the look as approved, or the first placement that holds every word
  }
  return best!;
};

// ------------------------------------------------------------------ the words' time on screen

/** A word's band can be read at frame f: big enough, wholly in view below the title strip and above the readout, and
 *  its photo across the middle of the frame. */
export const readable = (c: Cell, s: number, f: number) => {
  const bh = c.band!.h * s, top = CY + c.band!.y * s, x0 = CX + c.x * s, x1 = x0 + c.w * s;
  const ceiling = f < STRIP_UP + 12 ? TOP_STRIP + 6 : 6;
  return bh >= 48 && top >= ceiling && top + bh <= H - STRIP - 6 && x1 > M + 200 && x0 < W - M - 200;
};

export const WORD_TURN = 45;                              // the words come one after another, a second and a half apart
export const WORD_HOLD = 45;                              // and each holds at least a second and a half beside its photo

/** [first, last] frame each word is on screen (by word: 0, 1, 2): inside the longest run of frames its band can be read
 *  in, from its turn (word k at k x WORD_TURN) when that leaves it WORD_HOLD frames, else earlier, so it holds at least
 *  that long. [0, -1] for a word whose band cannot be read for WORD_HOLD frames at all. */
export const wordWindows = (mosaic: Mosaic, scaleAt: (f: number) => number): [number, number][] => {
  const out: [number, number][] = [];
  for (const c of mosaic.cells) {
    if (!c.band || c.word === undefined) continue;
    let best: [number, number] = [0, -1], run = -1;
    for (let f = 0; f <= 470; f++) {
      if (readable(c, scaleAt(f), f)) { if (run < 0) run = f; if (f - run > best[1] - best[0]) best = [run, f]; } else run = -1;
    }
    const [a, b] = best;
    out[c.word] = b - a < WORD_HOLD ? [0, -1] : [Math.max(a, Math.min(c.word * WORD_TURN, b - WORD_HOLD)), b];
  }
  return out;
};
