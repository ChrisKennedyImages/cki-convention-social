import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame } from "remotion";
import { FPS, H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, fillerAt, photoAt, shapeOf } from "../slots";
import { ANTON, ARCHIVO } from "../fonts";
import { Face, emWidth, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// MANIFESTO: say it loud. Your pictures, on every wall in town.
// The craft of the masters, not their look (Alexander Rodchenko and El Lissitzky, Constructivism):
//   the dynamic diagonal (nothing sits level: every word and every shape is built on the 30° line and its partner at
//   60°); photomontage (photographs cut out hard and collided, at different scales, to make an argument); the shout
//   (Rodchenko's 1924 poster: the words fly out of the caller and grow as they go); type as architecture (words carried
//   on beams and girders; a numeral built from two halves that slide together); El Lissitzky's story told in pure
//   shapes (the wedge driving into the white circle).
// The poster's world: Event Caliber's paper (its second colour) as the sheet, ink, and its first colour as the poster's
// one colour. Anton for the shout, Archivo at its widest and heaviest on the beams. The photographs exactly as shot.
//
// For Event Caliber (2026-11-08): a photographer's reel, so his pictures are the heroes, clean and whole. Every photo
// is shown at its own full shape (read from the file), never cropped, so no face is ever cut; nothing is drawn round it
// or laid over it (no ring, stroke or outline, no word, band or shape on a picture: words and shapes sit beside or
// behind); no photo ever grows toward the viewer (they slide, they collide, they hold). The hero circle of the first cut
// became the whole picture; the wedges that held cropped photos now point at whole ones; the circle at the climax is an
// aperture that opens on the picture rather than a picture that swells out of it. Words arrive once their shot has
// settled and hold to the cut (about two to three seconds each), so the eight bars became six longer scenes, still cut
// on the beat. His photos render exactly as shot, in their own colour: no print, tint, grade or light on any of them
// (the first version printed them in ink on the paper); the colour and the light live only in the shapes round them.
//
// 16 s (480 frames) on the 120 BPM grid of 15-frame beats:
//     0-75   the shout (the cover): the hero whole at the foot; the hook flies out above it along the 30° line, every
//            letter bigger than the last, filling the wedge; the sub on a beam beneath; a line of the shout each beat
//    75-165  photomontage: two photographs race in along the 30° line and collide; the couplet (lines 1 and 2) slides
//            in on two girders below them
//   165-240  the number, constructed: a photo above; the numeral in two halves that slide together on the disc;
//            label and unit on beams
//   240-315  three wedges, one an eighth, each driving in to its word's photo, the word along it; all three stay
//   315-420  the climax (Lissitzky): the ground splits on the 60° line, the wedge drives into the white circle on the
//            beat and the circle opens like an aperture on a photograph; the marquee on a slogan band, the stack
//            label on a beam
//   420-480  the manifesto: a photo, the name huge on the diagonal, the kicker on a beam, the call on an ink bar, the
//            site, the town (all in by frame 440, then it holds)

// ------------------------------------------------------------------ the world

const INK = "#0A0A0B";
const LIGHT = "#F3F3F1";               // light text on ink, where a colour is too dark to carry ink
// Every picture once (Chris, 2026-11-08, night: no picture twice in a reel): the post's seven photos are the hero (the
// shout), the three the words go with (the wedges), the climax's, the manifesto's and the number's (the suite fills a
// photo slot the post had no photo for from the last); the photomontage collides two fillers, more approved photos.
export const SLOTS: Slots = { photos: 7, fillers: 2 };
const HERO = 0, CLIMAX = 4, POSTER = 5, NUMBER = 6;

const SHOUT: Face = { family: ANTON, weight: 400 };

const RAD = Math.PI / 180;
const dir = (deg: number): [number, number] => [Math.cos(deg * RAD), Math.sin(deg * RAD)];
const UP = -30;                        // the rising diagonal: 30° above the horizon, to the right
const STEEP = -60;
const TAN30 = Math.tan(30 * RAD), COS30 = Math.cos(30 * RAD);
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const fall = Easing.in(Easing.cubic);
/** An arrival with a little overshoot, from 0 at `at`. */
const pop = (f: number, at: number, damping = 14, stiffness = 170) =>
  f < at ? 0 : spring({ frame: f - at, fps: FPS, config: { damping, stiffness, mass: 0.8 } });
/** After a contact: the two pieces part by a few pixels and settle back together over `len` frames. */
const give = (f: number, at: number, px = 8, len = 9) => (f < at || f > at + len ? 0 : px * Math.sin(((f - at) / len) * Math.PI));

/** Ink or light on a colour, whichever reads. */
const inkOn = (hex: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 105 ? INK : LIGHT;
};

// ------------------------------------------------------------------ the photographs, whole

/** The biggest size of a photo, at its own shape, inside w x h. */
const fitIn = (pic: Photo, w: number, h: number) => {
  const a = shapeOf(pic);                 // its shape from its props (slots.ts)
  return w / h > a ? { w: h * a, h } : { w, h: w / a };
};

/** A photograph exactly as shot: whole, at its own shape, in its own colour, with nothing on it. */
const Shot: React.FC<{ pic: Photo; x: number; y: number; w: number; h: number; clip?: string }> = ({ pic, x, y, w, h, clip }) => (
  <Img src={staticFile(pic.src)} style={{ position: "absolute", left: x, top: y, width: w, height: h, objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`, clipPath: clip, display: "block" }} />
);

// ------------------------------------------------------------------ type and construction

const STRETCH: Record<string, string> = { expanded: "125%", "semi-expanded": "112.5%", normal: "100%", "semi-condensed": "87.5%", condensed: "75%" };
/** The widest Archivo that still sets `text` across `width` at `min` px or more: a beam carries as wide a face as it can. */
const beamFace = (text: string, width: number, min: number, weight = 900): Face => {
  for (const stretch of ["expanded", "semi-expanded", "normal"] as const) {
    const face: Face = { family: ARCHIVO, weight, stretch };
    if (fitSize(text, face, width, 999) >= min) return face;
  }
  return { family: ARCHIVO, weight, stretch: "semi-condensed" };
};

/** A line of capitals placed by its ink: the middle of the capitals on y, anchored at x (callers upper-case it). */
const Say: React.FC<{ text: string; face: Face; size: number; x: number; y: number; align?: "left" | "center" | "right"; color: string; track?: number; opacity?: number }> = ({ text, face, size, x, y, align = "left", color, track = 0, opacity = 1 }) => {
  if (opacity <= 0.002) return null;
  const m = metrics(face);
  const left = align === "left" ? x : align === "center" ? x - 2500 : x - 5000;
  return (
    <div style={{ position: "absolute", left, top: y - (m.base - m.cap / 2) * size, width: 5000, textAlign: align, whiteSpace: "pre", lineHeight: 1, opacity }}>
      <span style={{ fontFamily: face.family, fontWeight: face.weight, fontStretch: STRETCH[face.stretch ?? "normal"], fontSize: size, letterSpacing: `${track}em`,
        paddingLeft: align === "center" ? `${track}em` : 0, marginRight: align === "right" ? `${-track}em` : 0, color, fontVariantNumeric: "lining-nums" }}>{text}</span>
    </div>
  );
};
const capOf = (face: Face, size: number) => metrics(face).cap * size;

/** A frame of reference: its origin at (x, y), its x axis turned to `deg`, scaled about its origin. */
const Turn: React.FC<{ x: number; y: number; deg: number; s?: number; children: React.ReactNode }> = ({ x, y, deg, s = 1, children }) => (
  <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, transform: `rotate(${deg}deg)${s !== 1 ? ` scale(${s.toFixed(5)})` : ""}`, transformOrigin: "0 0" }}>{children}</div>
);
/** A beam in a Turn's frame: from u0 to u1 along its axis, centred on v, `h` deep, drawn out from one end (k). */
const Beam: React.FC<{ u0: number; u1: number; v?: number; h: number; color: string; k?: number; from?: "start" | "end" }> = ({ u0, u1, v = 0, h, color, k = 1, from = "start" }) => (
  k <= 0.001 ? null : <div style={{ position: "absolute", left: u0, top: v - h / 2, width: u1 - u0, height: h, background: color, transform: k < 1 ? `scaleX(${k})` : undefined, transformOrigin: from === "start" ? "0 50%" : "100% 50%" }} />
);
const pts2 = (pts: [number, number][]) => pts.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" ");
/** A flat shape (points in the parent's frame; overflow visible, so the frame is unbounded). */
const Shape: React.FC<{ pts: [number, number][]; fill: string }> = ({ pts, fill }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
    <polygon points={pts2(pts)} fill={fill} />
  </svg>
);

/** A heavy word and its tail on one line: Anton, then Archivo black with half the cap height, on one baseline. */
const TAIL: Face = { family: ARCHIVO, weight: 900, stretch: "normal" };
const tailScale = () => 0.5 * (metrics(SHOUT).cap / metrics(TAIL).cap);
/** The line's width per px of the heavy word's size. */
const pairEm = (heavy: string, tail: string) => emWidth(heavy, SHOUT, 0.01) + 0.3 + tailScale() * emWidth(tail, TAIL, 0.02);
const Pair: React.FC<{ heavy: string; tail: string; size: number; x: number; y: number; color: string }> = ({ heavy, tail, size, x, y, color }) => {
  const tS = tailScale() * size;
  const base = y + capOf(SHOUT, size) / 2;
  return (
    <>
      <Say text={heavy} face={SHOUT} size={size} x={x} y={y} color={color} track={0.01} />
      <Say text={tail} face={TAIL} size={tS} x={x + textWidth(heavy, SHOUT, size, 0.01) + 0.3 * size} y={base - capOf(TAIL, tS) / 2} color={color} track={0.02} />
    </>
  );
};

// ------------------------------------------------------------------ the scenes

type Scene = React.FC<{ f: number; p: ReelProps }>;

// 0-75 · the shout. The hero stands whole at the foot of the poster; above it, along the 30° line, the hook flies up
// to the right, each letter as tall as its distance from the source (Rodchenko's growing words), two lines that fill
// the wedge; the sub on a beam beneath them; one more line of the shout on each beat.
const GAP = 30;
type Glyph = { ch: string; u: number; size: number; w: number; v0: number; v1: number };
const grow = (text: string, u0: number, k: number) => {
  const cap = metrics(SHOUT).cap;
  let u = u0;
  const out: { ch: string; u: number; size: number; w: number }[] = [];
  for (const ch of [...text]) {
    const size = (k * u) / cap, w = emWidth(ch, SHOUT) * size;
    out.push({ ch, u, size, w });
    u += w + 0.02 * size;
  }
  return out;
};
/** The two lines of the hook above the axis (the second word on it, the first word above that), at growth k. */
const shoutLines = (a: string, b: string, Ax: number, k: number): { A: Glyph[]; B: Glyph[] } => {
  const cap = metrics(SHOUT).cap;
  // where each line can start so that its first letter's top-left corner stays inside the frame
  const first = (ch: string, u: number) => (emWidth(ch, SHOUT) * k * u) / cap;
  let u0B = (46 - Ax + GAP / 4) / (COS30 - 0.5 * k), u0A = (46 - Ax + 0.75 * GAP) / (COS30 - k);
  for (let i = 0; i < 4; i++) u0A = (46 - Ax + 0.75 * GAP + 0.5 * k * first([...a][0] ?? "M", u0A)) / (COS30 - k);
  u0B = Math.max(u0B, 0);
  const B = grow(b, u0B, k).map((l) => ({ ...l, v0: -GAP / 2, v1: -(GAP / 2 + cap * l.size) }));
  const A = grow(a, u0A, k).map((l) => { const floor = GAP / 2 + k * (l.u + l.w) + GAP; return { ...l, v0: -floor, v1: -(floor + cap * l.size) }; });
  return { A, B };
};
const Shout: Scene = ({ f, p }) => {
  const hero = photoAt(p, HERO);
  const hs = fitIn(hero, W, 760);
  const hx = (W - hs.w) / 2, hy = H - 56 - hs.h;
  const a = p.open[0].toUpperCase(), b = p.open[1].toUpperCase();
  const sub = p.openSub.toUpperCase();
  const subFace = beamFace(sub, 840, 62);
  const subS = fitSize(sub, subFace, 840, 92, 0.02);
  const subH = capOf(subFace, subS) * 2.0;
  const vSub = GAP / 2 + subH / 2;
  // the axis runs low on the left, just clear of the photo with the sub's beam hanging from it
  const yAxis0 = hy - 30 - (GAP / 2 + subH) / COS30;
  const A = { x: -320, y: yAxis0 + 320 * TAN30 };
  const swell = 1 + 0.025 * (f / 75);
  const inside = (k: number) => {
    const { A: la, B: lb } = shoutLines(a, b, A.x, k);
    for (const l of [...la, ...lb]) {
      if (l.size * metrics(SHOUT).cap > 430) return false;
      for (const [u, v] of [[l.u, l.v0], [l.u + l.w, l.v0], [l.u, l.v1], [l.u + l.w, l.v1]]) {
        const x = A.x + (u * COS30 + v * 0.5) * 1.025, y = A.y + (-u * 0.5 + v * COS30) * 1.025;
        if (x < 40 || x > W - 40 || y < 56) return false;
      }
    }
    return true;
  };
  let lo = 0.05, hi = 0.6;
  for (let i = 0; i < 22; i++) { const mid = (lo + hi) / 2; if (inside(mid)) lo = mid; else hi = mid; }
  const k = lo;
  const { A: la, B: lb } = shoutLines(a, b, A.x, k);
  const m = metrics(SHOUT);
  const top = (u: number) => -(1.5 * GAP + 2.45 * k * u + 24);
  const wedge: [number, number][] = [[0, 6], [3600, 6], [3600, top(3600)], [0, top(0)]];
  const glyph = (l: Glyph, i: number) => (
    <div key={i} style={{ position: "absolute", left: l.u, top: l.v1 - (m.base - m.cap) * l.size, fontFamily: ANTON, fontSize: l.size, lineHeight: 1, color: inkOn(p.accent), whiteSpace: "pre" }}>{l.ch}</div>
  );
  const rayBase = Math.atan(2.45 * k) / RAD;
  const rays = [{ d: 5, at: 0, w: 10 }, { d: 10, at: 15, w: 5 }, { d: 16, at: 30, w: 14 }, { d: 23, at: 45, w: 4 }];
  const subU = (64 - A.x - 0.5 * vSub) / COS30;
  return (
    <AbsoluteFill>
      {rays.map((r, i) => (
        <Turn key={i} x={A.x} y={A.y} deg={UP - rayBase - r.d}>
          <Beam u0={420} u1={3400} h={r.w} color={INK} k={r.at === 0 ? 1 : ramp(f, r.at, r.at + 10, expoOut)} />
        </Turn>
      ))}
      <Turn x={A.x} y={A.y} deg={UP} s={swell}>
        <Shape pts={wedge} fill={p.accent} />
        {lb.map(glyph)}
        {la.map((l, i) => glyph(l, 100 + i))}
      </Turn>
      <Turn x={A.x} y={A.y} deg={UP}>
        <Beam u0={200} u1={3600} v={vSub} h={subH} color={INK} />
        <Say text={sub} face={subFace} size={subS} x={subU + 24 * (f / 75)} y={vSub} color={p.accent2} track={0.02} />
      </Turn>
      <Shot pic={hero} x={hx} y={hy} w={hs.w} h={hs.h} />
    </AbsoluteFill>
  );
};

// 75-165 · photomontage: two photographs at different scales; the smaller drives up the 60° line, faster and faster,
// and strikes the bigger edge to edge on the beat (it gives, and settles); then the couplet slides in on two girders
// below them, line 1 from the left, line 2 from the right, each heavy word with its tail on one beam.
const Montage: Scene = ({ f, p }) => {
  const one = fillerAt(p, 0), two = fillerAt(p, 1);
  const s1 = fitIn(one, 820, 550), s2 = fitIn(two, 560, 380);
  const x1 = 30, y1 = 60;
  const x2 = Math.min(W - 150 - s2.w, x1 + s1.w - 200), y2 = y1 + s1.h;
  const meet = 12;
  const [nx, ny] = dir(60);
  const travel = Math.min(260, (W - 4 - (x2 + s2.w)) / nx);   // never past the frame's edge
  const d = travel * (1 - fall(Math.min(1, f / meet)));
  const recoil = give(f, meet, 10);                            // the struck picture gives a little and comes back
  // the couplet: both lines at one size, as big as the room under the photos allows
  const l1h = p.line1[0].toUpperCase(), l1t = p.line1[1].toUpperCase(), l2h = p.line2[0].toUpperCase(), l2t = p.line2[1].toUpperCase();
  const e = Math.max(pairEm(l1h, l1t), pairEm(l2h, l2t));
  const yTop = y2 + s2.h + 36, yBot = H - 44;
  const beamOf = (s: number) => capOf(SHOUT, s) * 1.42;
  const extent = (s: number) => 0.5 * (s * e + 110) + (2 * beamOf(s) + 22) / COS30;
  let size = 230;
  while (size > 60 && (extent(size) > yBot - yTop || size * e + 110 > 1080)) size -= 2;
  const bh = beamOf(size), L = size * e + 110;
  const cy = (yTop + yBot) / 2;
  const v1 = -(bh + 22) / 2, v2 = (bh + 22) / 2;
  const slide1 = -1500 * (1 - ramp(f, 12, 24, expoOut)), slide2 = 1500 * (1 - ramp(f, 24, 36, expoOut));
  const line = (heavy: string, tail: string, v: number, slide: number, fill: string, at: number) => f >= at && (
    <>
      <Beam u0={-TAN30 * v - L / 2 + slide} u1={-TAN30 * v + L / 2 + slide} v={v} h={bh} color={fill} />
      <Pair heavy={heavy} tail={tail} size={size} x={-TAN30 * v - L / 2 + 55 + slide} y={v} color={fill === INK ? p.accent2 : inkOn(fill)} />
    </>
  );
  return (
    <AbsoluteFill>
      <Shot pic={one} x={x1 - recoil * 0.5} y={y1 - recoil * 0.866} w={s1.w} h={s1.h} />
      <Shot pic={two} x={x2 + nx * d} y={y2 + ny * d} w={s2.w} h={s2.h} />
      <Turn x={W / 2} y={cy} deg={UP}>
        {line(l1h, l1t, v1, slide1, INK, 12)}
        {line(l2h, l2t, v2, slide2, p.accent, 24)}
      </Turn>
    </AbsoluteFill>
  );
};

// 165-240 · the number, constructed: a photo above; on Event Caliber's colour as a disc, the numeral on the diagonal,
// cut along its axis into two halves that slide together along the cut and lock on the beat; the label on a beam above
// it, the unit on a beam below, each sliding in along its own axis.
const Counter: Scene = ({ f, p }) => {
  const pic = photoAt(p, NUMBER);
  const s = fitIn(pic, 900, 500);
  const px = (W - s.w) / 2, py = 56;
  const label = p.counter.label.toUpperCase(), unit = p.counter.unit.toUpperCase(), v = p.counter.value.toUpperCase();
  const lFace = beamFace(label, 640, 54), uFace = beamFace(unit, 640, 54);
  const lS = fitSize(label, lFace, 640, 74, 0.03), uS = fitSize(unit, uFace, 640, 74, 0.03);
  const lH = capOf(lFace, lS) * 2.2, uH = capOf(uFace, uS) * 2.2;
  const lL = textWidth(label, lFace, lS, 0.03) + 90, uL = textWidth(unit, uFace, uS, 0.03) + 90;
  const ext = (len: number, h: number) => 0.5 * len + h / COS30;
  const top = py + s.h + 40, bot = H - 44;
  const cyL = top + ext(lL, lH) / 2, cyU = bot - ext(uL, uH) / 2;
  const dy = (cyL + cyU) / 2, r = Math.min(360, (cyU - cyL) / 2);
  const nS = Math.min(fitSize(v, SHOUT, 1.45 * r, 2000), (1.25 * r) / metrics(SHOUT).cap);
  const lock = 12;
  const off = 520 * (1 - fall(Math.min(1, f / lock))) + give(f, lock, 10);
  const disc = 0.4 + 0.6 * pop(f, 0, 13, 160);
  const kL = ramp(f, 8, 18, expoOut), kU = ramp(f, 14, 24, expoOut);
  const half = (lower: boolean, du: number) => (
    <div style={{ position: "absolute", left: 0, top: 0, transform: `translateX(${du.toFixed(2)}px)` }}>
      <div style={{ position: "absolute", left: -2500, top: lower ? 0 : -2500, width: 5000, height: 2501, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 2500, top: lower ? 0 : 2500 }}>
          <Say text={v} face={SHOUT} size={nS} x={0} y={0} align="center" color={inkOn(p.accent)} />
        </div>
      </div>
    </div>
  );
  return (
    <AbsoluteFill>
      <Shot pic={pic} x={px} y={py} w={s.w} h={s.h} />
      <div style={{ position: "absolute", left: W / 2 - r, top: dy - r, width: r * 2, height: r * 2, borderRadius: "50%", background: p.accent, transform: `scale(${disc.toFixed(4)})` }} />
      <Turn x={W / 2} y={dy} deg={UP}>
        {half(false, off)}
        {half(true, -off)}
      </Turn>
      <Turn x={W / 2} y={cyL} deg={UP}>
        <Beam u0={-lL / 2 - 1500 * (1 - kL)} u1={lL / 2 - 1500 * (1 - kL)} h={lH} color={INK} />
        <Say text={label} face={lFace} size={lS} x={-1500 * (1 - kL)} y={0} align="center" color={p.accent2} track={0.03} />
      </Turn>
      <Turn x={W / 2} y={cyU} deg={UP}>
        <Beam u0={-uL / 2 + 1500 * (1 - kU)} u1={uL / 2 + 1500 * (1 - kU)} h={uH} color={INK} />
        <Say text={unit} face={uFace} size={uS} x={1500 * (1 - kU)} y={0} align="center" color={p.accent2} track={0.03} />
      </Turn>
    </AbsoluteFill>
  );
};

// 240-315 · three wedges: on each eighth a photo is cut in, whole and still, and its wedge drives in from
// the frame's edge until its tip meets the photo's side, the wedge's sides on the 30° lines; the word runs up the
// wedge's rising side. Photos and wedges alternate sides, and the words stay, so all three are read together.
const Wedges: Scene = ({ f, p }) => {
  const idx = p.wordPhotos;
  const words = p.words.map((w) => w.toUpperCase());
  const tierH = (H - 100) / 3;
  const M = 14;                                         // the words' margin inside their wedge
  const tiers = [0, 1, 2].map((i) => {
    const pic = photoAt(p, idx[i]);
    const s = fitIn(pic, 520, tierH - 190);
    const left = i % 2 === 0;
    const px = left ? 34 : W - 34 - s.w;
    const py = 50 + i * tierH + (tierH - s.h) / 2;
    const tip: [number, number] = [left ? px + s.w + 16 : px - 16, py + s.h / 2];
    const reach = left ? W - 34 - tip[0] : tip[0] - 34;   // how far the wedge runs inside the frame
    return { pic, s, left, px, py, tip, reach };
  });
  // one size for the three words: as big as the narrowest wedge allows (each word clear of both sides, in the frame)
  const fits = (size: number) => tiers.every((t, i) => {
    const cap = capOf(SHOUT, size), len = textWidth(words[i], SHOUT, size, 0.01);
    const t1 = (cap + 2 * M) / Math.tan(60 * RAD);
    return (t1 + len) * COS30 + 0.5 * (M + cap) <= t.reach;
  });
  let size = 220;
  while (size > 50 && !fits(size)) size -= 2;
  const cap = capOf(SHOUT, size);
  const cutIn = [0, 8, 15];                            // on the eighths, so the third word still holds for a second and a half
  return (
    <AbsoluteFill>
      {tiers.map((t, i) => {
        if (f < cutIn[i]) return null;
        const land = cutIn[i] + 8;
        const dx = (t.left ? 1 : -1) * 700 * (1 - ramp(f, cutIn[i], land, expoOut));   // the wedge's drive
        const far = 1600, sgn = t.left ? 1 : -1;
        const tri: [number, number][] = [t.tip, [t.tip[0] + sgn * far, t.tip[1] - far * TAN30], [t.tip[0] + sgn * far, t.tip[1] + far * TAN30]];
        const len = textWidth(words[i], SHOUT, size, 0.01);
        const mid = (cap + 2 * M) / Math.tan(60 * RAD) + len / 2;
        // the word's centre: along the rising side, inside the wedge
        const [ex, ey] = t.left ? dir(UP) : dir(150), [ix, iy] = t.left ? dir(60) : dir(-120);
        const cx = t.tip[0] + ex * mid + ix * (M + cap / 2), cyw = t.tip[1] + ey * mid + iy * (M + cap / 2);
        const wordIn = ramp(f, land + 2, land + 9, expoOut);
        return (
          <div key={i} style={{ position: "absolute", left: 0, top: 0, width: W, height: H }}>
            <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${dx.toFixed(1)}px)` }}>
              <Shape pts={tri} fill={p.accent} />
            </div>
            <Shot pic={t.pic} x={t.px} y={t.py} w={t.s.w} h={t.s.h} />
            {wordIn > 0.001 && (
              <Turn x={cx} y={cyw} deg={UP}>
                <Say text={words[i]} face={SHOUT} size={size} x={(t.left ? -1 : 1) * 60 * (1 - wordIn)} y={0} align="center" color={inkOn(p.accent)} track={0.01} opacity={Math.min(1, wordIn * 1.6)} />
              </Turn>
            )}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// 315-420 · the climax (El Lissitzky): the ground splits on a 60° line, paper on the left and ink on the right; the
// white circle stands on the ink; the wedge drives up out of the paper into it, faster and faster, and hits on the
// beat; the circle opens like an aperture on a photograph, whole. The marquee runs on a slogan band
// beneath it and the stack label on a beam under that.
const Climax: Scene = ({ f, p }) => {
  const pic = photoAt(p, CLIMAX);
  const s = fitIn(pic, 940, 640);
  const cx = W / 2, cy = 130 + s.h / 2;
  const px = cx - s.w / 2, py = cy - s.h / 2;
  const R = 230;
  const hit = 15;
  const Q: [number, number] = [90, cy + 120];
  const [lx, ly] = dir(60), [nx, ny] = dir(-30);
  const split: [number, number][] = [[Q[0] - lx * 3000, Q[1] - ly * 3000], [Q[0] + lx * 3000, Q[1] + ly * 3000],
    [Q[0] + lx * 3000 + nx * 4000, Q[1] + ly * 3000 + ny * 4000], [Q[0] - lx * 3000 + nx * 4000, Q[1] - ly * 3000 + ny * 4000]];
  const [wx, wy] = dir(STEEP), [qx, qy] = dir(STEEP + 90);
  const back = 1500 * (1 - fall(Math.min(1, f / hit))) + give(f, hit, 10);
  const tip: [number, number] = [cx - wx * (R - 26) - wx * back, cy - wy * (R - 26) - wy * back];
  const wedge: [number, number][] = [tip, [tip[0] - wx * 1900 + qx * 300, tip[1] - wy * 1900 + qy * 300], [tip[0] - wx * 1900 - qx * 300, tip[1] - wy * 1900 - qy * 300]];
  const circleIn = 0.4 + 0.6 * pop(f, 0, 13, 200);
  const open = ramp(f, hit + 1, hit + 15, expoOut);
  const clipR = interpolate(open, [0, 1], [R, Math.hypot(s.w, s.h) / 2 + 2]);
  // under the photo: the slogan band and the stack beam, parallel, as big as the room under the photo allows
  const word = p.marquee.toUpperCase();
  const stack = p.stackLabel.toUpperCase();
  const yTop = py + s.h + 40, yBot = H - 40;
  const bandL = 860;
  const sFace = beamFace(stack, 820, 50);
  let mS = fitSize(word, SHOUT, 560, 230, 0.02), sS = fitSize(stack, sFace, 820, 70, 0.03);
  const T = () => capOf(SHOUT, mS) * 1.5 + 22 + capOf(sFace, sS) * 2.2;
  const sL = () => textWidth(stack, sFace, sS, 0.03) + 90;
  while (mS > 60 && 0.5 * Math.max(bandL, sL()) + T() / COS30 > yBot - yTop) { mS -= 2; sS *= 0.99; }
  const bandH = capOf(SHOUT, mS) * 1.5, sH = capOf(sFace, sS) * 2.2;
  const bcy = (yTop + yBot) / 2;
  const vBand = -T() / 2 + bandH / 2, vStack = T() / 2 - sH / 2;
  const uBand = -TAN30 * vBand, uStack = -TAN30 * vStack;
  const run = `${word}  ·  `;
  const runW = textWidth(run, SHOUT, mS, 0.02);
  const bandK = ramp(f, 30, 40, expoOut), stackK = ramp(f, 37, 47, expoOut);
  const drift = 0.8 * Math.max(0, f - 30);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <polygon points={pts2(split)} fill={INK} />
        <polygon points={pts2(wedge)} fill={p.accent} />
      </svg>
      <Turn x={W / 2} y={bcy} deg={UP}>
        <Beam u0={uBand - bandL / 2} u1={uBand + bandL / 2} v={vBand} h={bandH} color={p.accent} k={bandK} />
        {bandK > 0.6 && (
          <div style={{ position: "absolute", left: uBand - bandL / 2, top: vBand - bandH / 2, width: bandL, height: bandH, overflow: "hidden" }}>
            {[-2, -1, 0, 1, 2].map((i) => (
              <React.Fragment key={i}>
                <Say text={word} face={SHOUT} size={mS} x={bandL / 2 + i * runW - drift} y={bandH / 2} align="center" color={inkOn(p.accent)} track={0.02} />
                <Say text="·" face={SHOUT} size={mS} x={bandL / 2 + (i + 0.5) * runW - drift} y={bandH / 2} align="center" color={inkOn(p.accent)} />
              </React.Fragment>
            ))}
          </div>
        )}
        <Beam u0={uStack - sL() / 2} u1={uStack + sL() / 2} v={vStack} h={sH} color={p.accent2} k={stackK} from="end" />
        <Say text={stack} face={sFace} size={sS} x={uStack + 900 * (1 - stackK)} y={vStack} align="center" color={inkOn(p.accent2)} track={0.03} opacity={stackK > 0.05 ? 1 : 0} />
      </Turn>
      {open < 0.999 && <div style={{ position: "absolute", left: cx - R, top: cy - R, width: R * 2, height: R * 2, borderRadius: "50%", background: p.accent2, transform: `scale(${circleIn.toFixed(4)})` }} />}
      {f > hit && <Shot pic={pic} x={px} y={py} w={s.w} h={s.h} clip={open < 0.999 ? `circle(${clipR.toFixed(1)}px at ${(cx - px).toFixed(1)}px ${(cy - py).toFixed(1)}px)` : undefined} />}
    </AbsoluteFill>
  );
};

// 420-480 · the manifesto: a photo at the head of the poster; beneath it the name huge on the 30° line, the kicker on
// a beam, the call on an ink bar, the site, the town, each line sliding in along its own axis. Complete by frame 440,
// then it holds.
const Poster: Scene = ({ f, p }) => {
  const pic = photoAt(p, POSTER);
  const s = fitIn(pic, 860, 520);
  const px = (W - s.w) / 2, py = 56;
  const name = p.business.toUpperCase();
  const kick = p.kicker.toUpperCase();
  const kFace = beamFace(kick, 880, 42, 800);
  const kS = fitSize(kick, kFace, 880, 54, 0.04), kH = capOf(kFace, kS) * 2.3, kL = textWidth(kick, kFace, kS, 0.04) + 80;
  const cta = p.cta.toUpperCase();
  const cFace = beamFace(cta, 760, 48);
  const cS = fitSize(cta, cFace, 760, 66, 0.03), cH = capOf(cFace, cS) * 2.4, cW = textWidth(cta, cFace, cS, 0.03) + 120;
  const site = p.phone;
  const sFace: Face = { family: ARCHIVO, weight: 800, stretch: "expanded" };
  const sS = fitSize(site, sFace, 760, 60), sL = textWidth(site, sFace, sS);
  const town = p.town.toUpperCase();
  const tFace: Face = { family: ARCHIVO, weight: 700, stretch: "expanded" };
  const tS = fitSize(town, tFace, 560, 34, 0.3), tL = textWidth(town, tFace, tS, 0.3);
  const top = py + s.h + 36, bot = H - 40;
  // the stack, measured across the lines (v), each line centred on the frame's vertical middle; the name as big as the
  // room allows
  const gaps = [64, 46, 54, 40];
  const layout = (nS: number) => {
    const rows = [{ h: capOf(SHOUT, nS), L: textWidth(name, SHOUT, nS, 0.005) }, { h: kH, L: kL }, { h: cH, L: cW }, { h: capOf(sFace, sS), L: sL }, { h: capOf(tFace, tS), L: tL }];
    const vs: number[] = [];
    let v = 0;
    rows.forEach((r, i) => { vs.push(v + r.h / 2); v += r.h + (gaps[i] ?? 0); });
    const mid = v / 2;
    const tops = rows.map((r, i) => (vs[i] - mid) / COS30 - 0.25 * r.L - 0.5 * r.h);
    const bots = rows.map((r, i) => (vs[i] - mid) / COS30 + 0.25 * r.L + 0.5 * r.h);
    return { vs: vs.map((x) => x - mid), span: Math.max(...bots) - Math.min(...tops), lift: (Math.max(...bots) + Math.min(...tops)) / 2 };
  };
  let nS = fitSize(name, SHOUT, 1000, 280, 0.005);
  while (nS > 60 && layout(nS).span > bot - top) nS -= 2;
  const { vs, lift } = layout(nS);
  const cy = (top + bot) / 2 - lift;
  const uOf = (i: number) => -TAN30 * vs[i];
  const slide = (from: number, dist: number, len = 12) => dist * (1 - ramp(f, from, from + len, expoOut));
  const ctaK = pop(f, 6, 16, 220);
  const photoIn = 1 - ramp(f, 0, 12, expoOut);
  return (
    <AbsoluteFill>
      <Shot pic={pic} x={px - Math.min(400, px - 24) * photoIn} y={py} w={s.w} h={s.h} />
      <Turn x={W / 2} y={cy} deg={UP}>
        <Say text={name} face={SHOUT} size={nS} x={uOf(0) + slide(0, -800)} y={vs[0]} align="center" color={INK} track={0.005} />
        <Beam u0={uOf(1) - kL / 2 + slide(3, 1400)} u1={uOf(1) + kL / 2 + slide(3, 1400)} v={vs[1]} h={kH} color={p.accent} />
        <Say text={kick} face={kFace} size={kS} x={uOf(1) + slide(3, 1400)} y={vs[1]} align="center" color={inkOn(p.accent)} track={0.04} />
        <div style={{ position: "absolute", left: uOf(2) - cW / 2, top: vs[2] - cH / 2, width: cW, height: cH, background: INK, transform: `scale(${ctaK.toFixed(4)})` }} />
        <Say text={cta} face={cFace} size={cS} x={uOf(2)} y={vs[2]} align="center" color={p.accent2} track={0.03} opacity={ramp(f, 9, 12, Easing.linear)} />
        <Say text={site} face={sFace} size={sS} x={uOf(3) + slide(8, -1000, 10)} y={vs[3]} align="center" color={INK} />
        <Say text={town} face={tFace} size={tS} x={uOf(4) + slide(10, 1000, 9)} y={vs[4]} align="center" color={INK} track={0.3} />
      </Turn>
    </AbsoluteFill>
  );
};

const SCENES: { at: number; S: Scene }[] = [
  { at: 0, S: Shout }, { at: 75, S: Montage }, { at: 165, S: Counter }, { at: 240, S: Wedges }, { at: 315, S: Climax }, { at: 420, S: Poster },
];

// ------------------------------------------------------------------ over everything

/** The poster paper: its fibre and a faint unevenness, still (it is paper; it does not crawl). Under everything. */
const Paper: React.FC<{ paper: string }> = ({ paper }) => (
  <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
    <filter id="mf-fibre" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.75" numOctaves={2} seed={11} />
      <feColorMatrix type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.3  0 0 0 0 0.3  1.3 0 0 0 -0.6" />
    </filter>
    <filter id="mf-mottle" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.004 0.006" numOctaves={3} seed={4} />
      <feColorMatrix type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.45  0 0 0 0 0.45  1.1 0 0 0 -0.45" />
    </filter>
    <rect width={W} height={H} fill={paper} />
    <rect width={W} height={H} filter="url(#mf-mottle)" opacity={0.22} />
    <rect width={W} height={H} filter="url(#mf-fibre)" opacity={0.16} />
  </svg>
);

export const Manifesto: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Manifesto");
  const g = useCurrentFrame();
  useFontsReady();
  const i = SCENES.reduce((n, s, k) => (g >= s.at ? k : n), 0);
  const { at, S } = SCENES[i];
  return (
    <AbsoluteFill style={{ background: p.accent2, overflow: "hidden" }}>
      <Music track={p.music} />
      <Paper paper={p.accent2} />
      <S f={g - at} p={p} />
    </AbsoluteFill>
  );
};
