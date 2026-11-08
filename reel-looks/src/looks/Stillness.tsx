import React, { useEffect, useState } from "react";
import { AbsoluteFill, Easing, Img, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame } from "remotion";
import { H, Photo, ReelProps, W, climaxIndex, heldForClimax } from "../look";
import { SANS, SERIF, SERIF_ROMAN } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// STILLNESS: nothing hurries; the one movement is the one that matters.
// Made first for Event Caliber (Chris Kennedy's event and conference photography, DC · MD · VA): a photographer's reel in
// which his own pictures are the heroes, clean, whole and in their true colours. So every photo stands on the paper at
// its own shape (portraits, stages and groups: a crop never cuts a face), nothing is drawn around or over a photo, no
// photo ever comes toward the viewer, and the one large movement in the film is his best picture, the hero, rising into
// the frame (or the photo props.climax names, whole).
// Chris on the first cut (2026-11-08): the concept held, but hard cuts with nothing moving read as a choppy slideshow on
// a phone. So it flows like cinema: slow dissolves between shots, every photo breathing, fewer and longer holds.
// The craft of the masters, not their look:
//   Chris Marker's La Jetée: a film told in still photographs, carried by slow dissolves and slow movements over the
//   pictures, in which one moment of real movement stops the heart. Yasujirō Ozu: compositions held low and level and
//   full of air, every picture standing on the same level line as his camera stayed at one height; the plain intertitle;
//   the quiet between scenes.
// The rules: every change between shots is an eased dissolve of 15 frames, never a cut. Every photo breathes all through
// its shot, a slow pull-back or a slow sideways drift, eased, never toward the viewer; the paper never moves. No shot is
// shorter than about two seconds. Words fade in once their picture has settled and fade out before the next dissolve.
// The world: warm paper and ink; Instrument Serif, upright and italic, quiet but large enough to read on a phone; small
// tracked caps in Inter Tight for labels; Event Caliber's colour once only, under the call to action.
//
// 16 s (480 frames) on the 120 BPM grid; each dissolve starts on a beat:
//     0-75   the intertitle, the cover: the hook on the paper
//    60-150  the hero on the level line, drawing slowly back; line 1 beneath
//   135-240  photos 4 and 5, one above the other, drifting slowly apart; line 2 beneath, the stack label under it
//   225-285  the number, plain on the paper
//   270-360  the three words: three photos down the page, each drifting a little, each word beside its own photo
//   345-445  silence, then the one movement: the hero rises over the level line and lands softly; the marquee beneath
//   430-480  the end card: name, kicker, the call underlined in Event Caliber's colour, site, town (complete by 445)

// ------------------------------------------------------------------ the world

const PAPER = "#EFE8DC";
const INK = "#1E1A16";
const GREY = "#5F564D";                 // labels: ink thinned on the paper
const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const ease = Easing.inOut(Easing.sin);
/** 0 to 1 between frames a and b, eased. */
const fade = (f: number, a: number, b: number) => ease(clamp((f - a) / (b - a), 0, 1));

const ROMAN: Face = { family: SERIF_ROMAN, weight: 400 };
const ITALIC: Face = { family: SERIF, weight: 400, italic: true };
const CAPS: Face = { family: SANS, weight: 500 };

// ------------------------------------------------------------------ photos, always whole

const ASPECT = new Map<string, number>();
/** Each photo's own shape (width / height), read from its file before the first frame is drawn, so every photo can be
 *  shown whole. A photo that does not load stops the render. */
const useAspects = (photos: Photo[]): number[] => {
  const srcs = photos.map((x) => x.src);
  const [, redraw] = useState(0);
  const [handle] = useState(() => (srcs.some((s) => !ASPECT.has(s)) ? delayRender("Reading the photos' shapes") : null));
  useEffect(() => {
    if (handle === null) return;
    const missing = srcs.filter((s) => !ASPECT.has(s));
    let left = missing.length;
    missing.forEach((s) => {
      const img = new Image();
      img.onload = () => { ASPECT.set(s, img.naturalWidth / img.naturalHeight); if (--left === 0) { redraw((n) => n + 1); continueRender(handle); } };
      img.onerror = () => cancelRender(new Error(`Photo did not load: ${s}`));
      img.src = staticFile(s);
    });
  }, [handle]);   // eslint-disable-line react-hooks/exhaustive-deps
  return srcs.map((s) => ASPECT.get(s) ?? 1.5);
};
/** The largest box of a photo's own shape inside (maxW, maxH). */
const fitBox = (ar: number, maxW: number, maxH: number) => (maxW / maxH > ar ? { w: maxH * ar, h: maxH } : { w: maxW, h: maxW / ar });
/** Photo i and its shape; the photo the climax keeps (props.climax) is never set small, so the hero takes its place
 *  outside the climax. */
const pick = (p: ReelProps, ar: number[], i: number) => { const j = heldForClimax(p, i) ? 0 : i % p.photos.length; return { pic: p.photos[j], ar: ar[j] }; };

/** A photo standing on the paper, whole and exactly as shot, its bottom centre at (cx, bottom). It breathes: s a scale
 *  that only ever falls toward 1 (drawing back, never coming closer), dx a slow sideways drift. */
const Standing: React.FC<{ pic: Photo; w: number; h: number; cx: number; bottom: number; s?: number; dx?: number }> = ({ pic, w, h, cx, bottom, s = 1, dx = 0 }) => (
  <Img src={staticFile(pic.src)} style={{ position: "absolute", left: cx - w / 2, top: bottom - h, width: w, height: h, objectFit: "contain", display: "block",
    transform: `translateX(${dx.toFixed(2)}px) scale(${s.toFixed(5)})`, transformOrigin: "50% 100%" }} />
);

// ------------------------------------------------------------------ type

type Run = { text: string; face: Face };
const runsEm = (runs: Run[], track = 0) => runs.reduce((s, r) => s + textWidth(r.text, r.face, 1, track), 0);
/** A pair like ["Wait", "for it."]: the word upright, the tail in italic. */
const pair = (a: string, b: string): Run[] => [{ text: a, face: ROMAN }, { text: ` ${b}`, face: ITALIC }];
/** For a line whose box starts at its top: how far down the capitals' tops sit, and their height. */
const capOf = (face: Face, size: number) => { const m = metrics(face); return { lead: (m.base - m.cap) * size, cap: m.cap * size }; };

/** A line of type, placed by its ink: capTop is where the tops of its capitals sit. Centred on cx, or set left-aligned
 *  from x (right-aligned to it with right). It fades, never moves. */
const Line: React.FC<{ runs: Run[]; size: number; capTop: number; cx?: number; x?: number; right?: boolean; color?: string; track?: number; caps?: boolean; opacity?: number }> = ({ runs, size, capTop, cx = W / 2, x, right = false, color = INK, track = 0, caps = false, opacity = 1 }) => {
  if (opacity <= 0.002) return null;
  const top = capTop - capOf(runs[0].face, size).lead;
  const box: React.CSSProperties = x === undefined ? { left: cx - 1200, width: 2400, textAlign: "center" } : right ? { left: x - 2400, width: 2400, textAlign: "right" } : { left: x, width: 2400, textAlign: "left" };
  return (
    <div style={{ position: "absolute", top, whiteSpace: "nowrap", opacity, ...box }}>
      <span style={{ fontSize: size, lineHeight: 1, color, letterSpacing: `${track}em`, paddingLeft: x === undefined ? `${track}em` : 0, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums" }}>
        {runs.map((r, i) => <span key={i} style={{ fontFamily: r.face.family, fontWeight: r.face.weight, fontStyle: r.face.italic ? "italic" : "normal" }}>{r.text}</span>)}
      </span>
    </div>
  );
};
const capsRun = (t: string): Run[] => [{ text: t, face: CAPS }];
/** Tracked caps sized to fit a width, never above max. */
const capsSize = (t: string, width: number, max: number, track: number) => Math.min(max, width / (textWidth(t.toUpperCase(), CAPS, 1, track) + track));

// ------------------------------------------------------------------ the shots

/** A shot gets its own frame f (0 at its first frame, dissolve included) and its length n. */
type Shot = React.FC<{ f: number; n: number; p: ReelProps; ar: number[] }>;
const DISSOLVE = 15;
const EYE = 880;                         // the optical centre the intertitles sit on, a little above the middle
const M = 108;                           // the margin: a tenth of the width
/** The level line every picture stands on, the same in every shot, as Ozu's camera stayed at one height; the line the
 *  hero rises over at the climax. Captions sit at one height beneath it. */
const LEVEL = 1262;
const UNDER = LEVEL + 112;
/** Words in a shot: in once the dissolve has settled, out before the next one begins. */
const words = (f: number, n: number, at = DISSOLVE + 7) => fade(f, at, at + 10) * (1 - fade(f, n - DISSOLVE - 8, n - DISSOLVE - 1));

/** The intertitle: the hook, centred on the paper. The cover. */
const Intertitle: Shot = ({ p }) => {
  const open = pair(p.open[0], p.open[1]);
  const oS = Math.min(184, 880 / runsEm(open));
  const sS = Math.min(oS * 0.58, fitSize(p.openSub, ITALIC, 840, 108));
  const a = capOf(ROMAN, oS), b = capOf(ITALIC, sS);
  const gap = oS * 0.46;
  const top = EYE - (a.cap + gap + b.cap) / 2;
  return (
    <>
      <Line runs={open} size={oS} capTop={top} />
      <Line runs={[{ text: p.openSub, face: ITALIC }]} size={sS} capTop={top + a.cap + gap} />
    </>
  );
};

/** The hero on the level line, drawing slowly back all through the shot; line 1 beneath it. */
const HeroLine: Shot = ({ f, n, p, ar }) => {
  const h = pick(p, ar, 0);
  const b = fitBox(h.ar, 900, LEVEL - 420);
  const runs = pair(p.line1[0], p.line1[1]);
  const s = Math.min(130, 860 / runsEm(runs));
  return (
    <>
      <Standing pic={h.pic} w={b.w} h={b.h} cx={W / 2} bottom={LEVEL} s={lerp(1.045, 1, fade(f, 0, n))} />
      <Line runs={runs} size={s} capTop={UNDER} opacity={words(f, n)} />
    </>
  );
};

/** Photos 4 and 5, one above the other, the lower on the level line, drifting slowly apart; line 2 beneath, and the
 *  stack label under it like a gallery's label. */
const Pair: Shot = ({ f, n, p, ar }) => {
  const a = pick(p, ar, 4), b = pick(p, ar, 5);
  const gap = 44, maxH = (LEVEL - 300 - gap) / 2;
  const ba = fitBox(a.ar, 820, maxH), bb = fitBox(b.ar, 820, maxH);
  const drift = 16 * (fade(f, 0, n) - 0.5);
  const runs = pair(p.line2[0], p.line2[1]);
  const s = Math.min(112, 860 / runsEm(runs));
  const track = 0.16, ls = capsSize(p.stackLabel, 860, 40, track);
  return (
    <>
      <Standing pic={a.pic} w={ba.w} h={ba.h} cx={W / 2} bottom={LEVEL - bb.h - gap} dx={drift} />
      <Standing pic={b.pic} w={bb.w} h={bb.h} cx={W / 2} bottom={LEVEL} dx={-drift} />
      <Line runs={runs} size={s} capTop={UNDER} opacity={words(f, n)} />
      <Line runs={capsRun(p.stackLabel)} size={ls} capTop={UNDER + capOf(ROMAN, s).cap + 74} caps track={track} color={GREY} opacity={words(f, n, DISSOLVE + 15)} />
    </>
  );
};

/** The number, plain: its label above in small caps, the figure in upright serif, the unit below in italic. */
const Count: Shot = ({ p }) => {
  const track = 0.22;
  const labS = capsSize(p.counter.label, 820, 42, track);
  const numS = fitSize(p.counter.value, ROMAN, 860, 640);
  const unitS = fitSize(p.counter.unit, ITALIC, 860, 124);
  const nn = capOf(ROMAN, numS), u = capOf(ITALIC, unitS), l = capOf(CAPS, labS);
  const gapA = 96, gapB = 92;
  const top = EYE - (l.cap + gapA + nn.cap + gapB + u.cap) / 2;
  return (
    <>
      <Line runs={capsRun(p.counter.label)} size={labS} capTop={top} caps track={track} color={GREY} />
      <Line runs={[{ text: p.counter.value, face: ROMAN }]} size={numS} capTop={top + l.cap + gapA} />
      <Line runs={[{ text: p.counter.unit, face: ITALIC }]} size={unitS} capTop={top + l.cap + gapA + nn.cap + gapB} />
    </>
  );
};

/** The three words: three photos down the page, alternating sides, each drifting a little toward its word; each word
 *  beside its own photo, fading in one after another once the page has settled. */
const Words: Shot = ({ f, n, p, ar }) => {
  const idx = p.wordPhotos ?? [0, 1, 2];
  const PW = 560, PH = 340, gap = 64, top = (H - (3 * PH + 2 * gap)) / 2 - 40;
  const s = Math.min(...p.words.map((w) => fitSize(w, ITALIC, W - 2 * M + 40 - PW - 56, 110)));
  const drift = fade(f, 0, n);
  return (
    <>
      {[0, 1, 2].map((i) => {
        const { pic, ar: a } = pick(p, ar, idx[i]);
        const b = fitBox(a, PW, PH);
        const left = i % 2 === 0;                       // photo on the left, word on the right; then the other way
        const cx = left ? M - 20 + PW / 2 : W - M + 20 - PW / 2;
        const rowMid = top + i * (PH + gap) + PH / 2;
        const toward = (left ? 1 : -1) * 12 * (drift - 0.5);
        const wordX = left ? M - 20 + PW + 56 : W - M + 20 - PW - 56;
        return (
          <React.Fragment key={i}>
            <Standing pic={pic} w={b.w} h={b.h} cx={cx} bottom={rowMid + b.h / 2} dx={toward} />
            <Line runs={[{ text: p.words[i], face: ITALIC }]} size={s} capTop={rowMid - capOf(ITALIC, s).cap / 2} x={wordX} right={!left} opacity={words(f, n, DISSOLVE + 5 + 4 * i)} />
          </React.Fragment>
        );
      })}
    </>
  );
};

/** Silence, then the one movement: the hero (or the photo props.climax names) rises slowly over the level line, as
 *  the sun clears a horizon, lands softly and goes on drawing back a breath; the marquee fades in beneath. */
const Rise: Shot = ({ f, n, p, ar }) => {
  const piece = { pic: p.photos[climaxIndex(p)], ar: ar[climaxIndex(p)] };
  const b = fitBox(piece.ar, 900, 800);
  const rest = LEVEL - 40;
  const k = Easing.bezier(0.33, 0, 0.12, 1)(clamp((f - 13) / 38, 0, 1));
  const bottom = lerp(LEVEL + b.h + 4, rest, k);
  const back = lerp(1, 0.985, fade(f, 51, n));
  const s = fitSize(p.marquee, ITALIC, W - 2 * M, 200);
  return (
    <>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: LEVEL, overflow: "hidden" }}>
        <Standing pic={piece.pic} w={b.w} h={b.h} cx={W / 2} bottom={bottom} s={back} />
      </div>
      <div style={{ position: "absolute", left: M, width: W - 2 * M, top: LEVEL, height: 1.5, background: "rgba(30,26,22,.28)" }} />
      <Line runs={[{ text: p.marquee, face: ITALIC }]} size={s} capTop={UNDER} opacity={words(f, n, 51)} />
    </>
  );
};

/** The end card, an intertitle: the name, the kicker, the call with Event Caliber's colour under it (the only time it
 *  appears), the site, the town. */
const End: Shot = ({ p }) => {
  const nameS = fitSize(p.business, ROMAN, 880, 150);
  const kickS = fitSize(p.kicker, ITALIC, 860, 70);
  const ctaS = fitSize(p.cta, ROMAN, 820, 72);
  const siteS = fitSize(p.phone, ROMAN, 860, 62);
  const townTrack = 0.26, townS = capsSize(p.town, 760, 32, townTrack);
  const nm = capOf(ROMAN, nameS), k = capOf(ITALIC, kickS), c = capOf(ROMAN, ctaS), st = capOf(ROMAN, siteS), t = capOf(CAPS, townS);
  const g1 = 72, g2 = 150, g3 = 132, g4 = 64;
  const block = nm.cap + g1 + k.cap + g2 + c.cap + g3 + st.cap + g4 + t.cap;
  const nT = EYE + 20 - block / 2, kT = nT + nm.cap + g1, cT = kT + k.cap + g2, sT = cT + c.cap + g3, tT = sT + st.cap + g4;
  const ctaW = textWidth(p.cta, ROMAN, ctaS);
  return (
    <>
      <Line runs={[{ text: p.business, face: ROMAN }]} size={nameS} capTop={nT} />
      <Line runs={[{ text: p.kicker, face: ITALIC }]} size={kickS} capTop={kT} color={GREY} />
      <Line runs={[{ text: p.cta, face: ROMAN }]} size={ctaS} capTop={cT} />
      <div style={{ position: "absolute", left: (W - ctaW) / 2, width: ctaW, top: cT + c.cap + 30, height: 7, background: p.accent }} />
      <Line runs={[{ text: p.phone, face: ROMAN }]} size={siteS} capTop={sT} />
      <Line runs={capsRun(p.town)} size={townS} capTop={tT} caps track={townTrack} color={GREY} />
    </>
  );
};

/** The shots, each overlapping the next by one dissolve; every dissolve starts on a beat. A card is a shot of type
 *  alone: a dissolve to or from one passes through bare paper, so type never lies over a fading picture. */
const SHOTS: { at: number; end: number; S: Shot; card?: boolean }[] = [
  { at: 0, end: 75, S: Intertitle, card: true },
  { at: 60, end: 150, S: HeroLine },
  { at: 135, end: 240, S: Pair },
  { at: 225, end: 285, S: Count, card: true },
  { at: 270, end: 360, S: Words },
  { at: 345, end: 445, S: Rise },
  { at: 430, end: 480, S: End, card: true },
];
/** How far into a dissolve through paper the outgoing shot is gone, and the incoming one begins. */
const THROUGH = 6;

// ------------------------------------------------------------------ the paper

/** The paper: its fibre and a faint mottle, fixed for the whole film (it never moves), under everything. */
const Paper: React.FC = () => (
  <AbsoluteFill style={{ background: PAPER }}>
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <filter id="st-fibre"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={3} seed={3} /><feColorMatrix type="matrix" values="0 0 0 0 0.12  0 0 0 0 0.1  0 0 0 0 0.08  0 0 0 0.22 0" /></filter>
      <filter id="st-mottle"><feTurbulence type="fractalNoise" baseFrequency="0.005 0.008" numOctaves={2} seed={9} /><feColorMatrix type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.25  0 0 0 0 0.18  0 0 0 0.16 0" /></filter>
      <rect width={W} height={H} filter="url(#st-fibre)" opacity={0.45} />
      <rect width={W} height={H} filter="url(#st-mottle)" opacity={0.5} />
    </svg>
  </AbsoluteFill>
);

export const Stillness: React.FC<ReelProps> = (p) => {
  const g = useCurrentFrame();
  useFontsReady();
  const ar = useAspects(p.photos);
  return (
    <AbsoluteFill style={{ background: PAPER, overflow: "hidden" }}>
      <Music track={p.music} />
      <Paper />
      {SHOTS.map(({ at, end, S, card }, i) => {
        if (g < at || g >= end) return null;
        const prev = SHOTS[i - 1], next = SHOTS[i + 1];
        const inn = !prev ? 1 : fade(g, at + (card || prev.card ? THROUGH : 0), at + DISSOLVE);
        const out = !next ? 1 : 1 - fade(g, end - DISSOLVE, end - (card || next.card ? THROUGH : 0));
        return (
          <AbsoluteFill key={i} style={{ opacity: Math.min(inn, out) }}>
            <S f={g - at} n={end - at} p={p} ar={ar} />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
