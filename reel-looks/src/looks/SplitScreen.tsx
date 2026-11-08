import React, { useEffect, useState } from "react";
import { AbsoluteFill, Easing, Img, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame } from "remotion";
import { getImageDimensions } from "@remotion/media-utils";
import { H, Photo, ReelProps, W, ramp } from "../look";
import { ARCHIVO, SANS } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// SPLIT SCREEN: the same moment, every angle. A photographer's reel where his pictures are the heroes.
// The craft of the masters, not their look:
//   Brian De Palma's split screen (two places at the same time; counterpoint, two strips running against each other);
//   Pablo Ferro's multi-screen for The Thomas Crown Affair (the frame divided into many panels at once); Abel Gance's
//   Polyvision triptych for Napoléon (the centre carries the action, the wings answer it); and the resolve, when all the
//   panels give way to one picture.
// For Event Caliber (Chris's event and conference photography, 2026-11-08) the look was rebuilt around his rules:
//   - every photo is shown whole, at its own shape (read from the file), exactly as shot, so no face is ever cut by a
//     crop; nothing is drawn around or over a photo (no ring, stroke, outline or tab);
//   - a photo never pushes toward the viewer: photos hold still in their panels and only the panels travel;
//   - the words ride on solid fields in the space around the photos (his cyan, paper, the black ground): they arrive once
//     their field has settled and lift away before it moves again, each held at least two seconds.
// After Chris watched it ("super choppy, the transitions are not well executed") the motion was rebuilt: the whole reel
// is one vertical strip of four layouts on the same 12 px gutter lattice, like frames on a film strip. Each layout is
// reached by one slow, eased advance of the strip (no empty frame between them, the gutter between two layouts the same
// as every other gutter), and inside a layout only one gesture happens at a time, eased over at least 24 frames and
// landing on a beat, then holding. Archivo condensed (heavy word, light tail), Inter Tight for the plain lines.
//
// 16 s on the 120 BPM grid (15-frame beats):
//   0-2.2 s     the split (the cover): two photos at once, the hook on the cyan field between them, readable at frame 0
//   2.2-3 s     counterpoint: the top strip runs left and the bottom strip runs right, as one mirrored gesture, each
//               bringing in a new photo (lands on beat 6)
//   3-5.6 s     line 1 and line 2 on the two halves of the cyan field
//   5.6-6.5 s   the strip advances to the contact sheet (lands on beat 13): six photos at once, the label above, the
//               number below (Ferro)
//   9-10 s      the strip advances to the triptych (beat 20): the centre's word first, the wings answering (Gance)
//   12.7-13.5 s the strip advances to the resolve (beat 27): one picture, the marquee above it, the end card beneath
//               (everything in by frame 433, then still)
// Music: the track the suite chose for the reel (src/music.tsx).

// ------------------------------------------------------------------ the world

const INK = "#0A0A0B";                         // the ground, and the gutters
const G = 12;                                  // the gutter
const IW = W - 2 * G;                          // the frame inside its outer gutter
const ph = (p: ReelProps, i: number): Photo => p.photos[i % p.photos.length];

const HEAVY: Face = { family: ARCHIVO, weight: 800, stretch: "condensed" };
const LIGHT: Face = { family: ARCHIVO, weight: 300, stretch: "condensed" };
const FIGURE: Face = { family: ARCHIVO, weight: 900, stretch: "condensed" };
const TAG: Face = { family: ARCHIVO, weight: 600, stretch: "semi-condensed" };
const PLAIN: Face = { family: SANS, weight: 500 };
const STRONG: Face = { family: SANS, weight: 700 };

const glide = Easing.bezier(0.65, 0, 0.35, 1);  // every move of a panel: eases out of rest and into it
const rise = Easing.bezier(0.25, 0.1, 0.25, 1); // words settling into their line
const lift = Easing.bezier(0.5, 0, 0.75, 0);    // words lifting away

/** Ink or paper on a colour, whichever reads. */
const onColour = (hex: string, paper: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 150 ? INK : paper;
};

// ------------------------------------------------------------------ the timing (frames of the reel)

const HOOK_OUT = 62;                           // the hook lifts away
const COUNTER = [68, 90] as const;             // the counterpoint gesture
const LINES = { at: [92, 98], out: 164 };      // line 1 and line 2
const ADVANCE: [number, number][] = [[170, 195], [270, 300], [380, 405]];   // the strip, layout to layout
const SHEET_TEXT = { at: [197, 201], out: 263 };
const WORDS = { at: [302, 308], out: 372 };    // the centre's word, then the wings'
const END = { marquee: 407, name: 410, kicker: 413, call: 416, site: 419, town: 422 };

// ------------------------------------------------------------------ the photos, whole

const SHAPE = new Map<string, number>();        // width / height of each photo, read from its file
/** Holds the frame until every photo's own shape is known, so each can be laid out whole. */
const useShapes = (pics: Photo[]): boolean => {
  const [ok, setOk] = useState(() => pics.every((q) => SHAPE.has(q.src)));
  const [handle] = useState(() => (ok ? null : delayRender("Reading the photos' shapes")));
  useEffect(() => {
    if (handle === null) return;
    const todo = pics.map((q) => q.src).filter((s) => !SHAPE.has(s));
    Promise.all(todo.map((s) => getImageDimensions(staticFile(s)).then((d) => { SHAPE.set(s, d.width / d.height); })))
      .then(() => { setOk(true); continueRender(handle); })
      .catch((e) => cancelRender(e));                // a photo that will not load fails the render: never a blank panel
  }, [handle, pics]);
  return ok;
};

type Rect = { x: number; y: number; w: number; h: number };
/** The photo's own rectangle, as large as fits in the box and centred in it. */
const fitIn = (box: Rect, pic: Photo): Rect => {
  const shape = SHAPE.get(pic.src) ?? 1.5;
  const w = Math.min(box.w, box.h * shape), h = w / shape;
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h };
};
/** A photo, whole and exactly as shot, in its box; moved sideways by dx. Nothing is ever drawn over it. */
const Pic: React.FC<{ pic: Photo; box: Rect; dx?: number }> = ({ pic, box, dx = 0 }) => {
  const r = fitIn(box, pic);
  if (r.x + dx > W || r.x + r.w + dx < 0) return null;
  return <Img src={staticFile(pic.src)} style={{ position: "absolute", left: r.x + dx, top: r.y, width: r.w, height: r.h, objectFit: "contain", display: "block" }} />;
};

// ------------------------------------------------------------------ fields and type

/** A solid field of colour in the space between photos. */
const Field: React.FC<{ r: Rect; bg: string; children?: React.ReactNode }> = ({ r, bg, children }) => (
  <div style={{ position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, overflow: "hidden", background: bg }}>{children}</div>
);

type Align = "left" | "center" | "right";
/** A line of type placed by its ink: inkTop is where the tops of its capitals sit; x is its left, centre or right. */
const T: React.FC<{ text: string; face: Face; size: number; x: number; inkTop: number; align?: Align; color: string; track?: number; caps?: boolean }> = ({ text, face, size, x, inkTop, align = "left", color, track = 0, caps = false }) => {
  const m = metrics(face);
  const span = 4000;
  const left = align === "left" ? x : align === "right" ? x - span : x - span / 2;
  return (
    <div style={{ position: "absolute", left, top: inkTop - (m.base - m.cap) * size, width: span, textAlign: align, whiteSpace: "nowrap" }}>
      <span style={{ fontFamily: face.family, fontWeight: face.weight, fontStretch: face.stretch ?? "normal", fontSize: size, lineHeight: 1, letterSpacing: `${track}em`,
        paddingLeft: align === "center" ? `${track}em` : undefined, color, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums" }}>{text}</span>
    </div>
  );
};
const capOf = (face: Face, size: number) => metrics(face).cap * size;
const fit = (text: string, face: Face, width: number, max: number, track = 0, caps = false) => fitSize(caps ? text.toUpperCase() : text, face, width, max, track);
/** One line if it fits at `min` or more, else two lines broken where the larger size comes out. */
const balance = (text: string, face: Face, width: number, max: number, min: number): { lines: string[]; size: number } => {
  const one = fit(text, face, width, max);
  const words = text.split(" ");
  let best = { lines: [text], size: one };
  if (one >= min) return best;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" "), b = words.slice(i).join(" ");
    const s = Math.min(fit(a, face, width, max), fit(b, face, width, max));
    if (s > best.size) best = { lines: [a, b], size: s };
  }
  return best;
};

/** A line of type on its field: it rises into its slot at frame `at` (its field has settled) and lifts away at frame
 *  `out` (before its field moves). Frames are the reel's. */
const Line: React.FC<{ g: number; at: number; out?: number; text: string; face: Face; size: number; x: number; inkTop: number; align?: Align; color: string; track?: number; caps?: boolean }> = ({ g, at, out = 1e9, ...t }) => {
  const kin = ramp(g, at, at + 12, rise), kout = ramp(g, out, out + 7, lift);
  if (kin <= 0 || kout >= 1) return null;
  const pad = t.size * 0.38, h = capOf(t.face, t.size) + 2 * pad;
  return (
    <div style={{ position: "absolute", left: 0, top: t.inkTop - pad, width: "100%", height: h, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: (1 - kin) * h * 0.8 - kout * h, width: "100%", height: h, opacity: Math.min(1, kin * 1.6) }}>
        <T {...t} inkTop={pad} />
      </div>
    </div>
  );
};

// ------------------------------------------------------------------ the four layouts on the strip

type Layout = React.FC<{ g: number; p: ReelProps }>;

// 1 · the split and the counterpoint (De Palma). Two photos at once with the cyan field between them, centred on the
// cover's 4:5 crop; the hook on the field at frame 0. Once the hook has lifted, the top strip runs left and the bottom
// strip runs right in one mirrored gesture, each bringing in a new photo a gutter behind the old; then line 1 and
// line 2 settle on the two halves of the field.
const TOP: Rect = { x: G, y: G, w: IW, h: 704 };
const MID: Rect = { x: G, y: 728, w: IW, h: 464 };
const LOW: Rect = { x: G, y: 1204, w: IW, h: 704 };
const Opening: Layout = ({ g, p }) => {
  const run = (IW + G) * ramp(g, COUNTER[0], COUNTER[1], glide);
  const ink = onColour(p.accent, p.accent2);
  // the hook
  const both = `${p.open[0]} ${p.open[1]}`;
  const one = fit(both, HEAVY, 960, 230, -0.01);
  const hook = one >= 150 ? [both] : [p.open[0], p.open[1]];
  const hS = hook.length === 1 ? one : Math.min(fit(p.open[0], HEAVY, 960, 170, -0.01), fit(p.open[1], HEAVY, 960, 170, -0.01));
  const sub = balance(p.openSub, STRONG, 960, 76, 58);
  const capH = capOf(HEAVY, hS), capS = capOf(STRONG, sub.size);
  const hLead = hS * 0.96, sLead = sub.size * 1.2, gap = hS * 0.4;
  const hTop = MID.h / 2 - ((hook.length - 1) * hLead + capH + gap + (sub.lines.length - 1) * sLead + capS) / 2;
  // the two lines, one to each half of the field
  const half = MID.w / 2, room = half - 2 * 44;
  const lS = Math.min(fit(p.line1[0], HEAVY, room, 168, -0.01), fit(p.line1[1], LIGHT, room, 168, -0.01), fit(p.line2[0], HEAVY, room, 168, -0.01), fit(p.line2[1], LIGHT, room, 168, -0.01));
  const lCap = capOf(HEAVY, lS), lTop = MID.h / 2 - (lS + lCap) / 2;
  return (
    <>
      <Pic pic={ph(p, 0)} box={TOP} dx={-run} />
      <Pic pic={ph(p, 2)} box={TOP} dx={IW + G - run} />
      <Pic pic={ph(p, 1)} box={LOW} dx={run} />
      <Pic pic={ph(p, 3)} box={LOW} dx={run - (IW + G)} />
      <Field r={MID} bg={p.accent}>
        {hook.map((l, i) => <Line key={i} g={g} at={-30} out={HOOK_OUT} text={l} face={HEAVY} size={hS} x={MID.w / 2} inkTop={hTop + i * hLead} align="center" color={ink} track={-0.01} />)}
        {sub.lines.map((l, i) => <Line key={`s${i}`} g={g} at={-30} out={HOOK_OUT} text={l} face={STRONG} size={sub.size} x={MID.w / 2} inkTop={hTop + (hook.length - 1) * hLead + capH + gap + i * sLead} align="center" color={ink} track={-0.01} />)}
        <Line g={g} at={LINES.at[0]} out={LINES.out} text={p.line1[0]} face={HEAVY} size={lS} x={44} inkTop={lTop} color={ink} track={-0.01} />
        <Line g={g} at={LINES.at[0] + 3} out={LINES.out} text={p.line1[1]} face={LIGHT} size={lS} x={44} inkTop={lTop + lS} color={ink} track={-0.01} />
        <Line g={g} at={LINES.at[1]} out={LINES.out} text={p.line2[0]} face={HEAVY} size={lS} x={half + 44} inkTop={lTop} color={ink} track={-0.01} />
        <Line g={g} at={LINES.at[1] + 3} out={LINES.out} text={p.line2[1]} face={LIGHT} size={lS} x={half + 44} inkTop={lTop + lS} color={ink} track={-0.01} />
      </Field>
    </>
  );
};

// 2 · the contact sheet (Ferro's multi-screen). Six photos at once in two columns, the label on the cyan field above them,
// the number on paper below.
const SHEET_TOP = 354, CELL_W = (IW - G) / 2, CELL_H = 348;
const cellOf = (c: number, r: number): Rect => ({ x: G + c * (CELL_W + G), y: SHEET_TOP + r * (CELL_H + G), w: CELL_W, h: CELL_H });
const SHEET = [{ c: 0, r: 0, pic: 0 }, { c: 1, r: 0, pic: 1 }, { c: 0, r: 1, pic: 2 }, { c: 1, r: 1, pic: 3 }, { c: 0, r: 2, pic: 4 }, { c: 1, r: 2, pic: 5 }];
const LABEL_F: Rect = { x: G, y: G, w: IW, h: SHEET_TOP - 2 * G };
const COUNT_F: Rect = { x: G, y: SHEET_TOP + 3 * CELL_H + 3 * G, w: IW, h: H - G - (SHEET_TOP + 3 * CELL_H + 3 * G) };
const Sheet: Layout = ({ g, p }) => {
  const set = balance(p.stackLabel, HEAVY, 960, 124, 86);
  const capL = capOf(HEAVY, set.size), leadL = set.size * 1.0;
  const labTop = LABEL_F.h / 2 - ((set.lines.length - 1) * leadL + capL) / 2;
  const { label, value, unit } = p.counter;
  const tS = fit(label, TAG, 900, 44, 0.14, true), capT = capOf(TAG, tS);
  const roomH = COUNT_F.h - 64 - capT - 46 - 70;
  const vS = Math.min(fit(value, FIGURE, 520, 460, -0.02), roomH / metrics(FIGURE).cap);
  const capV = capOf(FIGURE, vS), vW = textWidth(value, FIGURE, vS, -0.02);
  const uS = Math.min(fit(unit, HEAVY, 960 - vW - 40, 210, -0.01), (capV / metrics(HEAVY).cap) * 0.62);
  const uW = textWidth(unit, HEAVY, uS, -0.01);
  const vX = COUNT_F.w / 2 - (vW + 34 + uW) / 2;
  const base = 64 + capT + 46 + capV;
  const ink = onColour(p.accent, p.accent2), inkP = onColour(p.accent2, p.accent2);
  const [a, b] = SHEET_TEXT.at, out = SHEET_TEXT.out;
  return (
    <>
      {SHEET.map((s) => <Pic key={`${s.c}${s.r}`} pic={ph(p, s.pic)} box={cellOf(s.c, s.r)} />)}
      <Field r={LABEL_F} bg={p.accent}>
        {set.lines.map((l, i) => <Line key={i} g={g} at={a + i * 3} out={out} text={l} face={HEAVY} size={set.size} x={LABEL_F.w / 2} inkTop={labTop + i * leadL} align="center" color={ink} track={-0.01} />)}
      </Field>
      <Field r={COUNT_F} bg={p.accent2}>
        <Line g={g} at={b} out={out} text={label} face={TAG} size={tS} x={COUNT_F.w / 2} inkTop={64} align="center" color={inkP} track={0.14} caps />
        <Line g={g} at={b + 2} out={out} text={value} face={FIGURE} size={vS} x={vX} inkTop={base - capV} color={inkP} track={-0.02} />
        <Line g={g} at={b + 5} out={out} text={unit} face={HEAVY} size={uS} x={vX + vW + 34} inkTop={base - capOf(HEAVY, uS)} color={inkP} track={-0.01} />
      </Field>
    </>
  );
};

// 3 · the triptych (Gance). Three photos one above another, each with its word on a field beside it, the field as tall as
// its photo. The centre's word arrives first and carries the line; the two wings answer it together.
const ROW_H = 540, ROW_TOP = Math.round((H - 3 * ROW_H - 2 * G) / 2), PHOTO_W = 700;
const Triptych: Layout = ({ g, p }) => {
  const idx = p.wordPhotos ?? [0, 1, 2];
  const size = Math.min(...p.words.map((w) => fit(w, HEAVY, IW - PHOTO_W - G - 60, 150, -0.01)));
  const cap = capOf(HEAVY, size);
  return (
    <>
      {[0, 1, 2].map((i) => {
        const photoLeft = i !== 1;
        const box: Rect = { x: photoLeft ? G : W - G - PHOTO_W, y: ROW_TOP + i * (ROW_H + G), w: PHOTO_W, h: ROW_H };
        const shot = fitIn(box, ph(p, idx[i]));
        // the word's field takes the photo's own height and runs from the photo's edge (one gutter away) to the frame's
        const fr: Rect = photoLeft ? { x: shot.x + shot.w + G, y: shot.y, w: W - G - (shot.x + shot.w + G), h: shot.h } : { x: G, y: shot.y, w: shot.x - 2 * G, h: shot.h };
        const bg = i === 1 ? p.accent2 : p.accent;
        return (
          <React.Fragment key={i}>
            <Pic pic={ph(p, idx[i])} box={box} />
            <Field r={fr} bg={bg}>
              <Line g={g} at={i === 1 ? WORDS.at[0] : WORDS.at[1]} out={WORDS.out} text={p.words[i]} face={HEAVY} size={size} x={fr.w / 2} inkTop={fr.h / 2 - cap / 2} align="center" color={onColour(bg, p.accent2)} track={-0.01} />
            </Field>
          </React.Fragment>
        );
      })}
    </>
  );
};

// 4 · the resolve, and the end card. After all the panels, one picture: the hero, whole, with the marquee on the cyan
// field above it and the end card on the fields beneath. Everything settles in turn and holds.
const MARQ: Rect = { x: G, y: G, w: IW, h: 300 };
const HERO: Rect = { x: G, y: 324, w: IW, h: 704 };
const NAME: Rect = { x: G, y: 1040, w: IW, h: 340 };
const CALL: Rect = { x: G, y: 1392, w: IW, h: 200 };
const SITE: Rect = { x: G, y: 1604, w: IW, h: H - G - 1604 };
const Resolve: Layout = ({ g, p }) => {
  const ink = onColour(p.accent, p.accent2), inkP = onColour(p.accent2, p.accent2);
  const mS = fit(p.marquee, HEAVY, 940, 230, 0.02), capM = capOf(HEAVY, mS);
  const L = 48, room = IW - 2 * L;
  const nS = fit(p.business, HEAVY, room, 200, -0.01), kS = fit(p.kicker, PLAIN, room, 60);
  const capN = capOf(HEAVY, nS), capK = capOf(PLAIN, kS);
  const nTop = (NAME.h - (capN + 54 + capK)) / 2;
  const cS = fit(p.cta, HEAVY, room, 130, -0.01), capC = capOf(HEAVY, cS);
  const sS = fit(p.phone, STRONG, room, 88, -0.01), tS = fit(p.town, TAG, room, 40, 0.3, true);
  const capS = capOf(STRONG, sS), capTn = capOf(TAG, tS);
  const sTop = (SITE.h - (capS + 44 + capTn)) / 2;
  return (
    <>
      <Pic pic={ph(p, 0)} box={HERO} />
      <Field r={MARQ} bg={p.accent}>
        <Line g={g} at={END.marquee} text={p.marquee} face={HEAVY} size={mS} x={MARQ.w / 2} inkTop={(MARQ.h - capM) / 2 + 10} align="center" color={ink} track={0.02} />
      </Field>
      <Field r={NAME} bg={p.accent2}>
        <Line g={g} at={END.name} text={p.business} face={HEAVY} size={nS} x={L} inkTop={nTop} color={inkP} track={-0.01} />
        <Line g={g} at={END.kicker} text={p.kicker} face={PLAIN} size={kS} x={L} inkTop={nTop + capN + 54} color={inkP} />
      </Field>
      <Field r={CALL} bg={p.accent}>
        <Line g={g} at={END.call} text={p.cta} face={HEAVY} size={cS} x={L} inkTop={(CALL.h - capC) / 2} color={ink} track={-0.01} />
      </Field>
      <Field r={SITE} bg={p.accent2}>
        <Line g={g} at={END.site} text={p.phone} face={STRONG} size={sS} x={L} inkTop={sTop} color={inkP} track={-0.01} />
        <Line g={g} at={END.town} text={p.town} face={TAG} size={tS} x={L} inkTop={sTop + capS + 44} color={inkP} track={0.3} caps />
      </Field>
    </>
  );
};

// the strip: four layouts one above another, each STEP below the last so the gutter between two layouts is the same 12 px
// as every other; the strip advances one layout at a time
const STRIP: Layout[] = [Opening, Sheet, Triptych, Resolve];
const STEP = H - G;
const stripAt = (g: number) => ADVANCE.reduce((s, [a, b]) => s + ramp(g, a, b, glide), 0);

export const SplitScreen: React.FC<ReelProps> = (p) => {
  const g = useCurrentFrame();
  useFontsReady();
  const ready = useShapes(p.photos);
  const s = stripAt(g);
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden" }}>
      <Music track={p.music} />
      {ready && STRIP.map((L, k) => (Math.abs(k - s) < 1 ? (
        <AbsoluteFill key={k} style={{ transform: `translateY(${((k - s) * STEP).toFixed(2)}px)` }}><L g={g} p={p} /></AbsoluteFill>
      ) : null))}
    </AbsoluteFill>
  );
};
