import React, { useEffect, useState } from "react";
import { AbsoluteFill, Easing, Img, cancelRender, continueRender, delayRender, interpolate, random, spring, staticFile, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { getImageDimensions } from "@remotion/media-utils";
import { FPS, H, Photo, ReelProps, W, clamp, ramp } from "../look";
import { ANTON, ARCHIVO, SANS } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// WEATHER: rain or shine, the pictures stand.
// The craft of the master, not his look (Akira Kurosawa):
//   weather as emotion (the rain of Rashomon and the last battle of Seven Samurai, the wind and the blown leaves of
//   Yojimbo, the fog of Throne of Blood): it drives through every frame, so something always moves even over a still
//   picture; the hard-edged wipe as punctuation, sideways, down and on the diagonal; the long lens, which compresses
//   depth (rain in layers at three depths sliding past at different speeds as the camera tracks sideways, the near
//   streaks soft); and the clearing, when the storm breaks and the light comes back.
// For Event Caliber (Chris's event and conference photography, 2026-11-08) the look was rebuilt around his rules:
//   - every photo is shown whole, at its own shape (read from the file), floating in the storm, so no face is ever cut
//     by a crop; nothing is drawn around a photo (no ring, stroke or outline) and the words never sit on one: they are
//     on solid bands in the space around the pictures;
//   - his photos keep their true colours in every frame: nothing ever lies over the whole of a photo (no grade, tint,
//     fog or grain on it). The storm's dark sky, fog, leaves, grain and big soft near streaks live in the space around
//     and behind the pictures (they hang in it like clean prints); only the thin, sharp rain streaks pass across them,
//     the photo's own colour showing between the drops. The clearing changes the sky and the air, never the photo;
//   - a photo never pushes toward the viewer, so the axial cut-in is gone: the camera tracks sideways past the picture
//     on a long lens instead, the rain layers sliding by at their own speeds;
//   - every line holds two to three seconds: it wipes in once its shot has settled and wipes out before the next move,
//     so the reel runs in five movements rather than eight bars, still cut on the beat.
// Anton caps on solid slate bands so they read through the weather; his cyan is the one bright colour in the storm (a
// band, a cloth, a line of light) until the clearing.
//
// 16 s on the 120 BPM grid (15-frame beats):
//   0-2.5 s     the storm (the cover): the hero hanging in the rain, the hook on a band beneath it, readable at frame 0
//   2.5-5.7 s   the long lens: the camera tracks sideways past picture 1, rain sliding by in three layers; line 1
//               above it, line 2 below
//   5.7-9.2 s   a hard vertical wipe into the gale: heavier rain; a cyan cloth cracking in the wind carries the label;
//               the number stands on a band in the rain, the rain splashing off it; then the wind takes the cloth
//   9.2-13.2 s  a wipe down; three pictures wiped in one by one from three directions, each word beside its picture
//   13.2-16 s   the clearing: the weather front passes up the frame, the sky clears and warms around the hero; the
//               marquee on the cyan band; the end card settles beneath (all in by frame 442, then still)
// Music: the track the suite chose for the reel (src/music.tsx).

// ------------------------------------------------------------------ the world

const SLATE = "#111519";                       // the bands
const PAPER = "#EEF0EE";
const INK = "#0A0A0B";
const RAIN = "230,238,245";
const ph = (p: ReelProps, i: number): Photo => p.photos[i % p.photos.length];

const HEAVY: Face = { family: ANTON, weight: 400 };
const LABEL: Face = { family: ARCHIVO, weight: 600, stretch: "semi-condensed" };
const PLAIN: Face = { family: SANS, weight: 500 };
const STRONG: Face = { family: SANS, weight: 600 };

const flow = Easing.bezier(0.45, 0, 0.15, 1);
const optical = Easing.bezier(0.3, 0, 0.7, 1);   // an optical wipe: near constant speed, the ends just eased
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

/** Mix two #rrggbb colours. */
const mix = (a: string, b: string, k: number) => {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (s: number) => Math.round(lerp((pa >> s) & 255, (pb >> s) & 255, clamp01(k)));
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
};
/** Ink or paper on a colour, whichever reads. */
const onColour = (hex: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 150 ? INK : PAPER;
};

// ------------------------------------------------------------------ the weather, as functions of the frame

/** The wind's gusting, 0 a lull to 1 the strongest: slow swells with quicker buffets on top. */
const gust = (g: number) => clamp01(0.5 + 0.42 * noise2D("gust", g * 0.016, 0) + 0.2 * noise2D("buffet", g * 0.07, 1));
/** How far the wind has carried things by frame g, in px (always forward). */
const carried = (g: number) => 3.4 * g + 80 * noise2D("carry", g * 0.01, 3);
/** The storm's strength through the reel: steady, heavier in the gale, thinning as the front passes. */
const STORM: [number, number][] = [[0, 1], [170, 1], [180, 1.55], [275, 1.55], [287, 1.25], [395, 1.3], [413, 0.15], [480, 0.15]];
const rainK = (g: number) => interpolate(g, STORM.map((s) => s[0]), STORM.map((s) => s[1]), clamp);
/** The rain's slant from the vertical, in degrees: the wind leans it over, harder in the gusts and in the gale. */
const slant = (g: number) => 12 + 13 * gust(g) + 6 * interpolate(g, [170, 180, 255, 275], [0, 1, 1, 0], clamp);

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
      .catch((e) => cancelRender(e));                // a photo that will not load fails the render: never a blank frame
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

/** A picture, whole, in its box, moved sideways by dx: exactly as shot, with nothing over it. */
const Print: React.FC<{ pic: Photo; box: Rect; dx?: number }> = ({ pic, box, dx = 0 }) => {
  const r = fitIn(box, pic);
  return <Img src={staticFile(pic.src)} style={{ position: "absolute", left: r.x + dx, top: r.y, width: r.w, height: r.h, objectFit: "contain", display: "block" }} />;
};

// ------------------------------------------------------------------ type

type Align = "left" | "center" | "right";
/** A line of type placed by its ink: inkTop is where the tops of its capitals sit; x is its left, centre or right. */
const T: React.FC<{ text: string; face: Face; size: number; x: number; inkTop: number; align?: Align; color: string; track?: number; caps?: boolean; opacity?: number }> = ({ text, face, size, x, inkTop, align = "left", color, track = 0, caps = false, opacity = 1 }) => {
  if (opacity <= 0.002) return null;
  const m = metrics(face);
  const span = 4000;
  const left = align === "left" ? x : align === "right" ? x - span : x - span / 2;
  return (
    <div style={{ position: "absolute", left, top: inkTop - (m.base - m.cap) * size, width: span, textAlign: align, whiteSpace: "nowrap", opacity }}>
      <span style={{ fontFamily: face.family, fontWeight: face.weight, fontStretch: face.stretch ?? "normal", fontSize: size, lineHeight: 1, letterSpacing: `${track}em`,
        paddingLeft: align === "center" ? `${track}em` : undefined, color, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums" }}>{text}</span>
    </div>
  );
};
const capOf = (face: Face, size: number) => metrics(face).cap * size;
const fit = (text: string, face: Face, width: number, max: number, track = 0, caps = false) => fitSize(caps ? text.toUpperCase() : text, face, width, max, track);
const widthOf = (text: string, face: Face, size: number, track = 0, caps = false) => textWidth(caps ? text.toUpperCase() : text, face, size, track);
/** One line if it fits at `min` or more, else two lines broken where the larger size comes out (at a middle dot first). */
const balance = (text: string, face: Face, width: number, max: number, min: number, caps = false): { lines: string[]; size: number } => {
  const one = fit(text, face, width, max, 0.02, caps);
  let best = { lines: [text], size: one };
  if (one >= min) return best;
  const parts = text.split("·").map((s) => s.trim()).filter(Boolean);
  const unit = parts.length > 1 ? parts : text.split(" ");
  const join = parts.length > 1 ? " · " : " ";
  for (let i = 1; i < unit.length; i++) {
    const a = unit.slice(0, i).join(join), b = unit.slice(i).join(join);
    const s = Math.min(fit(a, face, width, max, 0.02, caps), fit(b, face, width, max, 0.02, caps));
    if (s > best.size) best = { lines: [a, b], size: s };
  }
  return best;
};

/** A solid band holding type. It wipes in from one side once its shot has settled (frame `at`) and wipes on out the
 *  other way before the next move (frame `out`); an optional line of Event Caliber's colour along its top. */
const Band: React.FC<{ f: number; at: number; out?: number; x: number; y: number; w: number; h: number; bg?: string; edge?: string; from?: "left" | "right"; children?: React.ReactNode }> = ({ f, at, out = 1e9, x, y, w, h, bg = SLATE, edge, from = "left", children }) => {
  const kin = ramp(f, at, at + 8, optical), kout = ramp(f, out, out + 7, optical);
  if (kin <= 0.001 || kout >= 0.999) return null;
  const a = `${((1 - kin) * 100).toFixed(2)}%`, b = `${(kout * 100).toFixed(2)}%`;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, background: bg, overflow: "hidden", clipPath: from === "left" ? `inset(0 ${a} 0 ${b})` : `inset(0 ${b} 0 ${a})` }}>
      {edge && <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 6, background: edge }} />}
      {children}
    </div>
  );
};

/** A line as two stacked bands from one edge of the frame: the heavy word, then its tail, each wiping in on its beat. */
const lineSet = (line: [string, string], maxW = 170) => {
  const [word, tail] = line;
  const wS = fit(word, HEAVY, 880, maxW, 0.01, true), tS = Math.min(wS * 0.64, fit(tail, HEAVY, 880, maxW * 0.7, 0.01, true));
  const wCap = capOf(HEAVY, wS), tCap = capOf(HEAVY, tS);
  const wPad = Math.round(wS * 0.3), tPad = Math.round(tS * 0.36), side = 60;
  return { word, tail, wS, tS, wCap, tCap, wPad, tPad, side, wW: widthOf(word, HEAVY, wS, 0.01, true) + 2 * side, tW: widthOf(tail, HEAVY, tS, 0.01, true) + 2 * side, wH: wCap + 2 * wPad, tH: tCap + 2 * tPad };
};
const LineBands: React.FC<{ line: [string, string]; y: number; f: number; at: [number, number]; out: number; from: "left" | "right"; edge: string; max?: number }> = ({ line, y, f, at, out, from, edge, max }) => {
  const s = lineSet(line, max);
  return (
    <>
      <Band f={f} at={at[0]} out={out} x={from === "left" ? 0 : W - s.wW} y={y} w={s.wW} h={s.wH} edge={edge} from={from}>
        <T text={s.word} face={HEAVY} size={s.wS} x={s.side} inkTop={s.wPad + 3} color={PAPER} track={0.01} caps />
      </Band>
      <Band f={f} at={at[1]} out={out} x={from === "left" ? 0 : W - s.tW} y={y + s.wH} w={s.tW} h={s.tH} from={from}>
        <T text={s.tail} face={HEAVY} size={s.tS} x={s.side} inkTop={s.tPad} color="#D5DADD" track={0.01} caps />
      </Band>
    </>
  );
};

// ------------------------------------------------------------------ the wipe

type Dir = [number, number];
/** What is left of an area (the frame unless given) ahead of a straight edge travelling along `dir`: all of it at k = 0,
 *  none at 1. A clip-path in frame coordinates, for a layer that covers the frame. */
const ahead = (k: number, dir: Dir, area: Rect = { x: 0, y: 0, w: W, h: H }) => {
  const n = Math.hypot(dir[0], dir[1]), ux = dir[0] / n, uy = dir[1] / n;
  const corners: [number, number][] = [[area.x, area.y], [area.x + area.w, area.y], [area.x + area.w, area.y + area.h], [area.x, area.y + area.h]];
  const proj = corners.map(([x, y]) => x * ux + y * uy);
  const c = lerp(Math.min(...proj), Math.max(...proj), k);
  const out: [number, number][] = [];
  for (let i = 0; i < 4; i++) {
    const a = corners[i], b = corners[(i + 1) % 4];
    const da = a[0] * ux + a[1] * uy - c, db = b[0] * ux + b[1] * uy - c;
    if (da >= 0) out.push(a);
    if ((da >= 0) !== (db >= 0)) { const t = da / (da - db); out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]); }
  }
  if (out.length < 3) return "polygon(0px 0px, 0px 0px, 0px 0px)";
  return `polygon(${out.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(", ")})`;
};

// ------------------------------------------------------------------ the storm

type Depth = { n: number; len: [number, number]; w: number; v: number; blur: boolean; lens: number };
/** Three depths of rain through a long lens: far, fine and dense; mid, sharp; near, a few big soft streaks. `lens`: how
 *  fast each depth slides past when the camera tracks (the near rain fastest). */
const DEPTHS: Record<"far" | "mid" | "near", Depth> = {
  far: { n: 460, len: [34, 62], w: 1.6, v: 33, blur: false, lens: 0.5 },
  mid: { n: 150, len: [110, 170], w: 2.8, v: 58, blur: false, lens: 1.5 },
  near: { n: 20, len: [340, 480], w: 12, v: 98, blur: true, lens: 3.4 },
};
const SPAN = 2400;                                   // the rain's square: covers the frame at any slant
/** One depth of rain, slanted by the wind: drops fall straight down a square turned to the wind's angle. `track`: the
 *  camera's sideways move, which carries each depth past at its own speed. */
const Rain: React.FC<{ g: number; depth: keyof typeof DEPTHS; k: number; track?: number }> = ({ g, depth, k, track = 0 }) => {
  if (k <= 0.02) return null;
  const d = DEPTHS[depth];
  const count = Math.round(d.n * Math.min(1.6, k));
  const drops: React.ReactNode[] = [];
  for (let i = 0; i < count; i++) {
    const len = lerp(d.len[0], d.len[1], random(`${depth}l${i}`));
    const v = d.v * (0.86 + 0.28 * random(`${depth}v${i}`));
    const y = ((random(`${depth}y${i}`) * SPAN + v * g) % SPAN) - SPAN / 2;
    drops.push(<rect key={i} x={((random(`${depth}x${i}`) - 0.5) * SPAN).toFixed(1)} y={y.toFixed(1)} width={d.w} height={len.toFixed(1)} rx={d.w / 2} fill={`url(#wx-drop-${depth})`} />);
  }
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, opacity: Math.min(1, k * 1.25) }}>
      <g transform={`translate(${(W / 2 + track * d.lens).toFixed(1)} ${H / 2}) rotate(${(-slant(g)).toFixed(2)})`} filter={d.blur ? "url(#wx-near)" : undefined}>{drops}</g>
    </svg>
  );
};

/** A fog bank: fractal noise drifting with the wind, white where it is thick, feathered top and bottom. */
const FOG_W = W + 1500;
const Fog: React.FC<{ g: number; y: number; h: number; amount: number; seed: number; speed?: number; tint?: string; blend?: "screen" | "normal" }> = ({ g, y, h, amount, seed, speed = 0.6, tint = "1 1 1", blend = "screen" }) => {
  if (amount <= 0.01) return null;
  const [r, gg, b] = tint.split(" ");
  const id = `wx-fog${seed}-${tint.replace(/\D/g, "")}`;        // one filter per seed and tint: two scenes can be on screen in a wipe
  const feather = "linear-gradient(180deg, transparent 0%, #000 38%, #000 62%, transparent 100%)";
  return (
    <div style={{ position: "absolute", left: -carried(g) * speed * 0.5, top: y, width: FOG_W, height: h, opacity: amount, mixBlendMode: blend, WebkitMaskImage: feather, maskImage: feather }}>
      <svg width={FOG_W} height={h} style={{ display: "block" }}>
        <filter id={id} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.0017 0.0048" numOctaves={4} seed={seed} />
          <feColorMatrix type="matrix" values={`0 0 0 0 ${r}  0 0 0 0 ${gg}  0 0 0 0 ${b}  1.9 0 0 0 -0.62`} />
        </filter>
        <rect width={FOG_W} height={h} filter={`url(#${id})`} />
      </svg>
    </div>
  );
};

/** Leaves blown across the storm on the wind, tumbling; the nearest soft. They stay in the air behind the pictures. */
const LEAF = "M0,0 C0.28,-0.36 0.74,-0.32 1,0 C0.74,0.3 0.28,0.36 0,0 Z";
const Leaves: React.FC<{ g: number; n?: number }> = ({ g, n = 5 }) => (
  <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
    {Array.from({ length: n }, (_, i) => {
      const size = 46 + 40 * random(`lf-s${i}`);
      const x = ((random(`lf-x${i}`) * 2400 + carried(g) * (2.6 + 2.4 * random(`lf-v${i}`))) % (W + 700)) - 350;
      const y = ((random(`lf-y${i}`) * H + g * (1.4 + random(`lf-f${i}`)) + 140 * Math.sin(g * 0.045 + i * 2.1)) % (H + 200)) - 100;
      const rot = random(`lf-r${i}`) * 360 + g * (6 + 10 * random(`lf-w${i}`));
      const flip = Math.cos(g * (0.12 + 0.1 * random(`lf-t${i}`)) + i);
      const near = i % 3 === 0;
      return (
        <g key={i} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${rot.toFixed(1)}) scale(${(size * (near ? 1.5 : 1)).toFixed(1)} ${(size * (near ? 1.5 : 1) * Math.max(0.12, Math.abs(flip))).toFixed(1)})`} filter={near ? "url(#wx-leaf)" : undefined}>
          <path d={LEAF} fill={flip > 0 ? "#2B2D24" : "#3F3E30"} opacity={0.92} />
          <path d="M-0.16,0 L0.92,0" stroke={flip > 0 ? "#4A4936" : "#24261F"} strokeWidth={0.035} />
        </g>
      );
    })}
  </svg>
);

/** Film grain for the storm: fractal noise, a fresh seed every frame. */
const Grain: React.FC<{ g: number }> = ({ g }) => (
  <AbsoluteFill style={{ mixBlendMode: "overlay", opacity: 0.15, pointerEvents: "none" }}>
    <svg width={W} height={H}>
      <filter id={`wx-grain${g % 24}`}><feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves={2} seed={g % 24} /><feColorMatrix type="saturate" values="0" /></filter>
      <rect width={W} height={H} filter={`url(#wx-grain${g % 24})`} />
    </svg>
  </AbsoluteFill>
);

/** The storm behind the pictures: the sky, the fog banks, the far rain in sheets, the leaves, the big soft near streaks
 *  and the grain. Each picture is drawn over it, so all of this stays in the space around the pictures. `track`: the
 *  camera's sideways move, carrying each depth of rain past at its own speed. */
const Sky: React.FC<{ g: number; track?: number; fog?: number }> = ({ g, track = 0, fog = 1 }) => {
  const sheet = "linear-gradient(90deg, rgba(0,0,0,.38), #000 26%, rgba(0,0,0,.55) 52%, #000 78%, rgba(0,0,0,.38))";
  const pos = `${((carried(g) * 1.7) % 1500).toFixed(1)}px 0px`;
  return (
    <>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, #0B0F13 0%, #1A2129 46%, #141A20 72%, #0B0E11 100%)" }} />
      <Fog g={g} y={1080} h={980} amount={0.45 * fog} seed={7} speed={0.8} />
      <AbsoluteFill style={{ WebkitMaskImage: sheet, maskImage: sheet, WebkitMaskSize: "1500px 100%", maskSize: "1500px 100%", WebkitMaskPosition: pos, maskPosition: pos, WebkitMaskRepeat: "repeat-x", maskRepeat: "repeat-x" } as React.CSSProperties}>
        <Rain g={g} depth="far" k={rainK(g)} track={track} />
      </AbsoluteFill>
      <Fog g={g} y={-260} h={760} amount={0.3 * fog} seed={3} speed={1.1} />
      <Leaves g={g} />
      <Fog g={g} y={1240} h={700} amount={0.22} seed={11} speed={1.3} />
      <Rain g={g} depth="near" k={rainK(g)} track={track} />
      <Grain g={g} />
    </>
  );
};
/** The one layer of weather that crosses the pictures: thin, sharp streaks of rain passing over them, the photo's own
 *  colour showing between the drops. Never a layer over the whole of a photo. */
const Streaks: React.FC<{ g: number; track?: number }> = ({ g, track = 0 }) => <Rain g={g} depth="mid" k={rainK(g)} track={track} />;

// ------------------------------------------------------------------ the movements

type Scene = React.FC<{ f: number; g: number; p: ReelProps }>;

// 1 · the storm. At frame 0 (the cover) the rain is already falling around and across the hero, hanging in the storm; the hook
// sits on a solid band beneath it: the first word in paper, the second in Event Caliber's colour, the question beneath.
// It holds to be read, and wipes out before the cut.
const HERO_BOX: Rect = { x: 60, y: 250, w: 960, h: 680 };
const Storm: Scene = ({ f, g, p }) => {
  const r = fitIn(HERO_BOX, ph(p, 0));
  const size = Math.min(fit(p.open[0], HEAVY, 940, 210, 0.01, true), fit(p.open[1], HEAVY, 940, 210, 0.01, true));
  const cap = capOf(HEAVY, size);
  const sub = balance(p.openSub, STRONG, 900, 66, 54);
  const capS = capOf(STRONG, sub.size);
  const gap = size * 0.13, padT = 62, padB = 72, subGap = 50, subLead = sub.size * 1.22;
  const bandH = padT + 2 * cap + gap + subGap + capS + (sub.lines.length - 1) * subLead + padB;
  return (
    <AbsoluteFill>
      <Sky g={g} />
      <Print pic={ph(p, 0)} box={HERO_BOX} />
      <Streaks g={g} />
      <Band f={f} at={-20} out={66} x={0} y={r.y + r.h + 44} w={W} h={bandH}>
        <T text={p.open[0]} face={HEAVY} size={size} x={W / 2} inkTop={padT} align="center" color={PAPER} track={0.01} caps />
        <T text={p.open[1]} face={HEAVY} size={size} x={W / 2} inkTop={padT + cap + gap} align="center" color={p.accent} track={0.01} caps />
        {sub.lines.map((l, i) => <T key={i} text={l} face={STRONG} size={sub.size} x={W / 2} inkTop={padT + 2 * cap + gap + subGap + i * subLead} align="center" color="#C9CFD3" />)}
      </Band>
    </AbsoluteFill>
  );
};

// 2 · the long lens. The camera tracks sideways past picture 1, slowly, the whole way through: the picture glides across
// while the rain slides by in its three layers at three speeds, the near streaks fastest (the long lens stacking the
// depths, the picture moving least). Line 1 wipes in above the picture from the left, line 2 below it from the right.
const TRACK_BOX: Rect = { x: 40, y: 640, w: 1000, h: 640 };
const Track: Scene = ({ f, g, p }) => {
  const pic = ph(p, 1);
  const r = fitIn(TRACK_BOX, pic);
  const cam = lerp(110, -110, ramp(f, 0, 95, Easing.inOut(Easing.sin)));
  const room = Math.max(0, r.x - 16);
  const dx = Math.max(-room, Math.min(room, cam * 0.3));                  // the picture stays whole in the frame
  const s1 = lineSet(p.line1, 150), s2 = lineSet(p.line2, 150);
  return (
    <AbsoluteFill>
      <Sky g={g} track={cam} />
      <Print pic={pic} box={TRACK_BOX} dx={dx} />
      <Streaks g={g} track={cam} />
      <LineBands line={p.line1} y={r.y - 40 - s1.wH - s1.tH} f={f} at={[10, 16]} out={86} from="left" edge={p.accent} max={150} />
      <LineBands line={p.line2} y={Math.min(r.y + r.h + 40, H - 250 - s2.wH - s2.tH)} f={f} at={[24, 30]} out={86} from="right" edge={p.accent} max={150} />
    </AbsoluteFill>
  );
};

// 3 · the gale. A hard vertical wipe and the rain thickens and leans over. A cloth in Event Caliber's colour, fixed off the
// left edge, blows out across the air above the picture and cracks in the wind (a wave running to its free end,
// snapping harder on each beat, its folds lit and shaded), the label printed on it. The number stands on a band below,
// the rain splashing off its top. Then the wind takes the cloth away.
const CLOTH_X = -46, CLOTH_LEN = 1070, SLICES = 120;
const GALE_BOX: Rect = { x: 90, y: 560, w: 900, h: 600 };
const Gale: Scene = ({ f, g, p }) => {
  const pic = ph(p, 3);
  const r = fitIn(GALE_BOX, pic);
  // the cloth
  const set = balance(p.stackLabel, HEAVY, 860, 130, 96, true);
  const cap = capOf(HEAVY, set.size), lead = cap + set.size * 0.2, pad = Math.round(set.size * 0.42);
  const BH = Math.round(2 * pad + cap + (set.lines.length - 1) * lead + 10);
  const top = r.y - 64 - BH;
  const ink = onColour(p.accent);
  const blow = ramp(f, 4, 18, flow);                        // blowing out from the fixed edge
  const away = ramp(f, 92, 104, Easing.in(Easing.quad));    // and taken by the wind
  const beats = [4, 19, 34, 49, 64, 79];
  const snap = beats.reduce((s, b) => s + (f >= b ? Math.exp(-(f - b) / 4.5) : 0), 0);
  const amp = 20 + 24 * gust(g) + 46 * snap + 60 * away;
  const kw = (2 * Math.PI) / 470;
  const phase = g * 0.36 + 2.2 * beats.reduce((s, b) => s + (f >= b ? 1 - Math.exp(-(f - b) / 5) : 0), 0);
  const du = CLOTH_LEN / SLICES;
  const shown = CLOTH_LEN * blow;
  const content = (
    <div style={{ position: "absolute", left: 0, top: 0, width: CLOTH_LEN, height: BH, background: `linear-gradient(180deg, rgba(0,0,0,.16), rgba(0,0,0,0) 9%, rgba(0,0,0,0) 88%, rgba(0,0,0,.22)), ${p.accent}` }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 9, height: 2, background: "rgba(0,0,0,.18)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 9, height: 2, background: "rgba(0,0,0,.18)" }} />
      {set.lines.map((l, i) => <T key={i} text={l} face={HEAVY} size={set.size} x={W / 2 - CLOTH_X} inkTop={pad + 5 + i * lead} align="center" color={ink} track={0.02} caps />)}
    </div>
  );
  /** The cloth at a point u along it: its depth, its slope, and the light on it (from the left, a little in front). */
  const at = (u: number) => {
    const t = u / CLOTH_LEN, A = amp * Math.pow(t, 1.35), phs = kw * u - phase;
    const slope = A * kw * Math.cos(phs) + ((amp * 1.35 * Math.pow(t, 0.35)) / CLOTH_LEN) * Math.sin(phs);
    const c = 1 / Math.sqrt(1 + slope * slope);
    return { z: A * Math.sin(phs), c, lit: -slope * c };
  };
  const shade = (lit: number) => (lit < 0 ? `rgba(0,0,0,${Math.min(0.5, -lit * 0.9).toFixed(3)})` : `rgba(255,248,230,${Math.min(0.28, lit * 0.5).toFixed(3)})`);
  const slices: React.ReactNode[] = [];
  let sx = CLOTH_X;
  for (let i = 0; i < SLICES; i++) {
    const u0 = i * du;
    if (u0 >= shown) break;
    const a = at(u0), m = at(u0 + du / 2), b = at(u0 + du);
    const w = Math.min(du, shown - u0) * m.c;
    const sy = 1 + m.z / 1600;
    slices.push(
      <div key={i} style={{ position: "absolute", left: sx, top: top + m.z * 0.22 - (BH * (sy - 1)) / 2, width: w + 0.8, height: BH * sy, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: CLOTH_LEN, height: BH, transform: `scale(${m.c.toFixed(4)}, ${sy.toFixed(4)}) translateX(${-u0}px)`, transformOrigin: "0 0" }}>{content}</div>
        <div style={{ position: "absolute", inset: 0, background: `linear-gradient(90deg, ${shade(a.lit)}, ${shade(m.lit)}, ${shade(b.lit)})` }} />
      </div>,
    );
    sx += w;
  }
  // the number on its band beneath the picture
  const { label, value, unit } = p.counter;
  const bandY = r.y + r.h + 56;
  const lS = fit(label, LABEL, 900, 44, 0.24, true), capL = capOf(LABEL, lS);
  const vS = Math.min(fit(value, HEAVY, 520, 300, 0.01, true), 300);
  const capV = capOf(HEAVY, vS), vW = widthOf(value, HEAVY, vS, 0.01, true);
  const uS = Math.min(fit(unit, HEAVY, 900 - vW - 40, 150, 0.02, true), vS * 0.5), uW = widthOf(unit, HEAVY, uS, 0.02, true);
  const bandH = Math.round(56 + capL + 40 + capV + 64);
  const base = 56 + capL + 40 + capV;
  const vX = W / 2 - (vW + 30 + uW) / 2;
  const stand = spring({ frame: f - 26, fps: FPS, config: { damping: 14, stiffness: 120, mass: 0.9 } });
  const shown2 = ramp(f, 20, 28, optical) > 0 && ramp(f, 92, 99, optical) < 1;
  const splashes = shown2 ? Array.from({ length: Math.round(20 * rainK(g)) }, (_, j) => {
    const x = random(`sp${g}-${j}`) * W, s = 9 + 14 * random(`sps${g}-${j}`);
    return <path key={j} d={`M${x - s} ${bandY - s * 1.1} L${x - 2} ${bandY - 1} M${x + 2} ${bandY - 1} L${x + s * 0.8} ${bandY - s * 1.2} M${x} ${bandY - 2} L${x + s * 0.1} ${bandY - s * 1.5}`} stroke={`rgba(${RAIN},.8)`} strokeWidth={2.4} fill="none" strokeLinecap="round" />;
  }) : null;
  return (
    <AbsoluteFill>
      <Sky g={g} fog={1.1} />
      <Print pic={pic} box={GALE_BOX} />
      <Streaks g={g} />
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translate(${(away * 1400).toFixed(1)}px, ${(-away * 260).toFixed(1)}px) rotate(${(away * 9).toFixed(2)}deg)`, transformOrigin: "0% 30%" }}>{slices}</div>
      <Band f={f} at={20} out={92} x={0} y={bandY} w={W} h={bandH} edge={p.accent}>
        <T text={label} face={LABEL} size={lS} x={W / 2} inkTop={56} align="center" color="#C9CFD3" track={0.24} caps />
        <div style={{ position: "absolute", left: 0, top: base - capV * 1.25, width: W, height: capV * 1.4, overflow: "hidden" }}>
          <div style={{ position: "absolute", left: 0, top: (1 - stand) * capV * 1.3, width: W, height: capV * 1.4 }}>
            <T text={value} face={HEAVY} size={vS} x={vX} inkTop={capV * 0.25} color={PAPER} track={0.01} caps />
            <T text={unit} face={HEAVY} size={uS} x={vX + vW + 30} inkTop={capV * 0.25 + capV - capOf(HEAVY, uS)} color={p.accent} track={0.02} caps />
          </div>
        </div>
      </Band>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>{splashes}</svg>
    </AbsoluteFill>
  );
};

// 4 · three pictures wiped in one by one, each from a new direction (from the left, from the right, on the diagonal),
// like three cameras on the same night, each word on a band beside its picture. The rain keeps falling around and across them.
const ROW_H = 467, ROW_GAP = 24, ROW_PHOTO_W = 700, ROW_EDGE = 20;
const ROW_TOPS = [0, 1, 2].map((i) => 196 + i * (ROW_H + ROW_GAP));
const ROW_WIPES: Dir[] = [[1, 0], [-1, 0], [0.62, 0.78]];
const Words: Scene = ({ f, g, p }) => {
  const idx = p.wordPhotos ?? [0, 1, 2];
  const size = Math.min(...p.words.map((w) => fit(w, HEAVY, W - ROW_EDGE - ROW_PHOTO_W - 20 - 76, 150, 0.01, true)));
  const cap = capOf(HEAVY, size), pad = Math.round(size * 0.36);
  const bh = cap + 2 * pad;
  const rows = [0, 1, 2].map((i) => {
    const at = 2 + i * 12;
    const left = i !== 1;
    const box: Rect = { x: left ? ROW_EDGE : W - ROW_EDGE - ROW_PHOTO_W, y: ROW_TOPS[i], w: ROW_PHOTO_W, h: ROW_H };
    const r = fitIn(box, ph(p, idx[i]));
    return { i, at, left, box, r, k: ramp(f, at, at + 10, optical), bandX: left ? r.x + r.w + 20 : 0, bandW: left ? W - (r.x + r.w + 20) : r.x - 20 };
  }).filter((row) => row.k > 0);
  return (
    <AbsoluteFill>
      <Sky g={g} />
      {rows.map(({ i, box, r, k }) => (
        // revealed behind an edge travelling across the picture: what is left ahead of it, run backwards
        <AbsoluteFill key={i} style={{ clipPath: k < 1 ? ahead(1 - k, [-ROW_WIPES[i][0], -ROW_WIPES[i][1]], r) : undefined }}>
          <Print pic={ph(p, idx[i])} box={box} />
        </AbsoluteFill>
      ))}
      <Streaks g={g} />
      {rows.map(({ i, at, left, r, bandX, bandW }) => (
        <Band key={i} f={f} at={at + 12} out={110} x={bandX} y={r.y + r.h / 2 - bh / 2} w={bandW} h={bh} edge={p.accent} from={left ? "right" : "left"}>
          <T text={p.words[i]} face={HEAVY} size={size} x={left ? 38 : bandW - 38} inkTop={pad + 3} align={left ? "left" : "right"} color={PAPER} track={0.01} caps />
        </Band>
      ))}
    </AbsoluteFill>
  );
};

// 5 · the clearing. The weather front passes up the frame (the wipe into this movement) and behind it the air is clear:
// the sky warming, the last fog lifting away, no rain, and the hero hanging in the clear air exactly as it hung in the
// storm. The marquee on a band of Event Caliber's colour above it; the end card settles beneath; then everything holds
// in still air.
const CLEAR_BOX: Rect = { x: 90, y: 400, w: 900, h: 600 };
const Clearing: Scene = ({ f, g, p }) => {
  const hero = ph(p, 0);
  const r = fitIn(CLEAR_BOX, hero);
  const warm = ramp(f, 0, 50, Easing.out(Easing.quad));
  const sky = `linear-gradient(180deg, ${mix("#B9C7D0", "#CFE0EA", warm)} 0%, ${mix("#D3DBDE", "#F2F0EA", warm)} 50%, ${mix("#DCDCD5", "#F8E4C2", warm)} 100%)`;
  const mS = fit(p.marquee, HEAVY, 860, 170, 0.06, true), capM = capOf(HEAVY, mS);
  const mH = Math.round(capM + mS * 0.6);
  const nS = fit(p.business, HEAVY, 940, 170, 0.02, true), capN = capOf(HEAVY, nS);
  const kS = fit(p.kicker, PLAIN, 900, 54), capK = capOf(PLAIN, kS);
  const cS = fit(p.cta, HEAVY, 800, 80, 0.03, true), capC = capOf(HEAVY, cS);
  const cW = widthOf(p.cta, HEAVY, cS, 0.03, true) + 120, cH = Math.round(capC + cS * 0.8);
  const sS = fit(p.phone, STRONG, 900, 66), capS = capOf(STRONG, sS);
  const tS = fit(p.town, LABEL, 900, 36, 0.32, true);
  const nTop = r.y + r.h + 60, kTop = nTop + capN + 36, cY = kTop + capK + 52, sTop = cY + cH + 56, tTop = sTop + capS + 36;
  const settle = (a: number) => ({ k: ramp(f, a, a + 9, flow), dy: (1 - ramp(f, a, a + 9, flow)) * 24 });
  const n = settle(24), k = settle(27), c = settle(30), s = settle(33), t = settle(36);
  return (
    <AbsoluteFill style={{ background: sky }}>
      {/* the low sun come back, warm on the clearing air */}
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 40% at 30% 26%, rgba(255,206,140,${(0.55 * warm).toFixed(3)}), transparent 72%)` }} />
      {/* the last of the fog, lifting away */}
      <Fog g={g} y={980 - f * 9} h={900} amount={0.5 * (1 - ramp(f, 6, 46, Easing.linear))} seed={7} speed={0.8} tint="0.74 0.79 0.83" blend="normal" />
      <Fog g={g} y={360 - f * 7} h={700} amount={0.36 * (1 - ramp(f, 0, 40, Easing.linear))} seed={3} speed={1.1} tint="0.78 0.82 0.86" blend="normal" />
      <Print pic={hero} box={CLEAR_BOX} />
      <Band f={f} at={18} x={0} y={r.y - 40 - mH} w={W} h={mH} bg={p.accent}>
        <T text={p.marquee} face={HEAVY} size={mS} x={W / 2} inkTop={(mH - capM) / 2} align="center" color={onColour(p.accent)} track={0.06} caps />
      </Band>
      <div style={{ position: "absolute", left: 0, top: n.dy, width: W, height: H, opacity: n.k }}><T text={p.business} face={HEAVY} size={nS} x={W / 2} inkTop={nTop} align="center" color={INK} track={0.02} caps /></div>
      <div style={{ position: "absolute", left: 0, top: k.dy, width: W, height: H, opacity: k.k }}><T text={p.kicker} face={PLAIN} size={kS} x={W / 2} inkTop={kTop} align="center" color="#3A4046" /></div>
      <div style={{ position: "absolute", left: W / 2 - cW / 2, top: cY + c.dy, width: cW, height: cH, background: SLATE, opacity: c.k }}>
        <T text={p.cta} face={HEAVY} size={cS} x={cW / 2} inkTop={(cH - capC) / 2} align="center" color={PAPER} track={0.03} caps />
      </div>
      <div style={{ position: "absolute", left: 0, top: s.dy, width: W, height: H, opacity: s.k }}><T text={p.phone} face={STRONG} size={sS} x={W / 2} inkTop={sTop} align="center" color={INK} /></div>
      <div style={{ position: "absolute", left: 0, top: t.dy, width: W, height: H, opacity: t.k }}><T text={p.town} face={LABEL} size={tS} x={W / 2} inkTop={tTop} align="center" color="#30363C" track={0.32} caps /></div>
    </AbsoluteFill>
  );
};

// the movements, and the wipes that bring them in: the outgoing scene, still moving, held ahead of a straight edge
const SCENES: { at: number; S: Scene }[] = [
  { at: 0, S: Storm }, { at: 75, S: Track }, { at: 170, S: Gale }, { at: 275, S: Words }, { at: 395, S: Clearing },
];
const WIPES: Record<number, { len: number; dir: Dir }> = {
  170: { len: 12, dir: [1, 0] },              // a vertical edge, left to right
  275: { len: 12, dir: [0, 1] },              // down from the top
  395: { len: 18, dir: [0, -1] },             // the weather front, passing up the frame
};

// ------------------------------------------------------------------ over everything

const Defs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      <filter id="wx-near" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5" /></filter>
      <filter id="wx-leaf" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="0.035" /></filter>
      {(["far", "mid", "near"] as const).map((d) => (
        <linearGradient key={d} id={`wx-drop-${d}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={`rgb(${RAIN})`} stopOpacity="0" />
          <stop offset="1" stopColor={`rgb(${RAIN})`} stopOpacity={d === "far" ? 0.5 : d === "mid" ? 0.66 : 0.38} />
        </linearGradient>
      ))}
    </defs>
  </svg>
);

export const Weather: React.FC<ReelProps> = (p) => {
  const g = useCurrentFrame();
  useFontsReady();
  const ready = useShapes(p.photos);
  const i = SCENES.reduce((n, s, k) => (g >= s.at ? k : n), 0);
  const { at, S } = SCENES[i];
  const w = WIPES[at];
  const prev = i > 0 && w && g < at + w.len ? SCENES[i - 1] : null;
  return (
    <AbsoluteFill style={{ background: SLATE, overflow: "hidden" }}>
      <Music track={p.music} />
      <Defs />
      {ready && <S f={g - at} g={g} p={p} />}
      {ready && prev && w && (
        <AbsoluteFill style={{ clipPath: ahead(optical(clamp01((g - at) / w.len)), w.dir) }}>
          <prev.S f={g - prev.at} g={g} p={p} />
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
