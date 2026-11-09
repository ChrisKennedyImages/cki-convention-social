import React, { useEffect, useState } from "react";
import { AbsoluteFill, Easing, Img, cancelRender, continueRender, delayRender, random, spring, staticFile, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { FPS, H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, everyPicture, fillerAt, photoAt } from "../slots";
import { HAND, MONO, SERIF, SERIF_ROMAN } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// DARKROOM: the picture was always there; it only needed developing.
// Made first for Event Caliber (Chris Kennedy's event and conference photography, DC · MD · VA): a photographer's reel in
// which his own pictures are the heroes. His rules shape it (Chris, 2026-11-08): every photo renders exactly as shot,
// with no grade, tint, dimming or light on it; the safelight lights the room, never a print, so the pictures hang in
// their true colours in a red room; the one change a photo may go through is a print developing in from paper white,
// ending exactly as shot. Every photo is shown whole, at its own shape (portraits, stages and groups: a crop never cuts
// a face); nothing is drawn around or over a photo; no photo comes toward the viewer; no loupe (Event Caliber's Loop reel
// owns it). The climax is his best picture, the hero, on the line in daylight, whole and untouched.
// The craft of the masters, not their look:
//   the Magnum contact sheet: a whole roll printed on one sheet and edited there, the one decisive frame chosen from many
//   (Cartier-Bresson), told here without a mark: the frame is cut from the sheet and lifted away by hand, and it is the one
//   that goes into the enlarger. The enlarger's beam laying the chosen picture on the easel, the print seen before it
//   exists (Adams' previsualisation). The print emerging in the developer, shadows first and highlights last. Ansel Adams' Zone
//   System: every tone placed on one scale from Zone 0 (black) to Zone X (paper white). Prints pegged on a line to dry.
//   And at the end the safelight goes off, the door opens, and the room is seen in daylight round the print.
// The world: safelight darkness, a deep warm black under a low amber-red lamp, on the walls, the trays, the easel and the
// lines; prints and their paper always neutral and true. Instrument Serif for the lines (an upright word, an italic
// tail); Caveat only for pencil on a print's border; JetBrains Mono only for numbers on the film's edge and the timer's
// dial. Event Caliber's colour: the timer's hand, and the call to action at the end. Words come only from the props; each
// arrives once its shot has settled and leaves before the next move.
//
// 16 s (480 frames) on the 120 BPM grid (a beat is 15 frames, a bar 60), one idea a bar:
//   0  the hook above the contact sheet on the light box: a roll of twelve, each frame whole   (frame 0 is the cover)
//      and each a picture of its own: the hero, the post's photos that carry no word, and fillers (Chris, 2026-11-08,
//      night: no picture twice in a reel); the three word photos are first seen on the line, so none is seen twice
//   1  the choice: the decisive frame is cut from the sheet and lifted away by hand; the light box shows through where
//      it was                                                                                   (bars 0-1 are one shot)
//   2  the enlarger: the chosen frame slides into the carrier, the lamp clicks on and the beam lays the picture on the
//      easel, positive and in its own colours, the lamp's light warm on it; the timer's hand jumps on every beat; line 1
//   3  the paper slides into the tray and the picture comes up out of paper white, shadows first, then mid-tones,
//      highlights last, ending exactly as shot; line 2 above it, the stack label pencilled in its margin
//   4  the zone scale: eleven steps from Zone 0 to Zone X develop across the frame; the number set large above it
//   5  three prints pegged up one a beat, each on its own line, swinging still; each word pencilled on its border; the
//      safelight clicks off on the last beat and the room goes dark round them
//   6  the climax: the hero on the line in the dark room; the door opens and daylight fills the room
//      round it; the marquee word beneath once the light has settled
//   7  the end card as a fine print: the hero whole above, beneath it the name, the kicker, the call on a block of the
//      Event Caliber's colour, the site, the town (all in by frame 441, then holds 1.3 s)

// ------------------------------------------------------------------ the world

type RGB = [number, number, number];
type Pt = [number, number];
const DARK = "#0E0706";
const D = "14,7,6";
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lerpPt = (a: Pt, b: Pt, k: number): Pt => [lerp(a[0], b[0], k), lerp(a[1], b[1], k)];
const smooth = (t: number) => { const x = clamp01(t); return x * x * (3 - 2 * x); };
const soft = Easing.bezier(0.45, 0, 0.2, 1);
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const rgb = (c: RGB, a = 1) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${a.toFixed(3)})`;

/** A tone of the room (0 black to 1 the palest) under the safelight: red-black shadows, amber highlights. */
const safe = (v: number): RGB => { const x = clamp01(v); return [14 + 227 * Math.pow(x, 0.85), 7 + 183 * Math.pow(x, 1.35), 6 + 134 * Math.pow(x, 1.9)]; };
const TYPE = "#F5D6B2";                 // type under the safelight: a breath above the room's palest
const PRINT = "#F4F2EE";                // print paper: neutral, never lit by the safelight
const FILM = "#0B0B0B";                 // the film's black on the contact sheet
const GRAPHITE = "#33302C";             // pencil on a print's border
const LAMP: RGB = [255, 238, 210];      // the enlarger's tungsten
// daylight
const WALL = "#E7E2D9", PAPER = "#F5F2EB", INK = "#1C1916";

/** Development of a tone (0 black to 1 white) at time t: a faint ghost of the whole first, then each tone's density in
 *  proportion to how dark it will be, the shadows first, the highlights last; at t = 1 every tone is fully there. */
const arrived = (v: number, t: number) => Math.max(0.3 * smooth(t * 2.5), smooth((t - v * 0.5) / 0.5));
/** A transfer table for an SVG filter: f over 0..1. */
const table = (f: (x: number) => number, n = 24) => Array.from({ length: n }, (_, i) => clamp01(f(i / (n - 1))).toFixed(4)).join(" ");

/** Ink or paper on Event Caliber's colour, whichever reads. */
const onColour = (hex: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255) > 150 ? INK : PAPER;
};

// ------------------------------------------------------------------ photos, always whole and as shot

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
// The post's six photos: the hero (slot 0), which carries the first word and is the decisive frame, the print, the
// climax and the end card all in one; the two other word photos; and three more, each on the contact sheet once. The
// sheet's seven other frames are fillers, more of his approved photos.
export const SLOTS: Slots = { photos: 6, fillers: 7 };
const HERO = 0, ON_SHEET = [3, 4, 5];
type Shaped = { pic: Photo; ar: number };
/** The post's photo in slot i, and its shape (`ar` is read in everyPicture's order: the photos, then the fillers). */
const own = (p: ReelProps, ar: number[], i: number): Shaped => ({ pic: photoAt(p, i), ar: ar[i] });
/** The filler in slot k, and its shape. */
const filler = (p: ReelProps, ar: number[], k: number): Shaped => ({ pic: fillerAt(p, k), ar: ar[p.photos.length + k] });

/** A photo exactly as shot, filling a box of its own shape. filter: only the developer's transition, never at rest. */
const Shot: React.FC<{ pic: Photo; w: number; h: number; filter?: string }> = ({ pic, w, h, filter }) => (
  <Img src={staticFile(pic.src)} style={{ position: "absolute", left: 0, top: 0, width: w, height: h, objectFit: "contain", display: "block", filter }} />
);

// ------------------------------------------------------------------ type

const ROMAN: Face = { family: SERIF_ROMAN, weight: 400 };
const ITALIC: Face = { family: SERIF, weight: 400, italic: true };
const PENCIL: Face = { family: HAND, weight: 600 };

type Run = { text: string; face: Face };
const runsEm = (runs: Run[], track = 0) => runs.reduce((s, r) => s + textWidth(r.text, r.face, 1, track), 0);
/** A pair like ["Shot", "in the room."]: the word upright, the tail in italic. */
const pair = (a: string, b: string): Run[] => [{ text: a, face: ROMAN }, { text: ` ${b}`, face: ITALIC }];

/** A line of type that develops: it comes up out of the dark and sharpens, like a print brought into focus; gone takes
 *  it back down. */
const Develop: React.FC<{ runs: Run[]; size: number; top: number; k?: number; gone?: number; color?: string; cx?: number; track?: number; caps?: boolean; opacity?: number }> = ({ runs, size, top, k = 1, gone = 0, color = TYPE, cx = W / 2, track = 0, caps = false, opacity = 1 }) => {
  const a = smooth(k * 1.2) * (1 - gone) * opacity;
  if (a <= 0.002) return null;
  const blur = (1 - Math.min(1, k)) * 9 + gone * 8;
  return (
    <div style={{ position: "absolute", left: cx - 1200, width: 2400, top: top + (1 - k) * 18, textAlign: "center", whiteSpace: "nowrap", opacity: a, filter: blur > 0.2 ? `blur(${blur.toFixed(2)}px)` : undefined }}>
      <span style={{ fontSize: size, lineHeight: 1, color, letterSpacing: `${track}em`, paddingLeft: `${track}em`, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums" }}>
        {runs.map((r, i) => <span key={i} style={{ fontFamily: r.face.family, fontWeight: r.face.weight, fontStyle: r.face.italic ? "italic" : "normal" }}>{r.text}</span>)}
      </span>
    </div>
  );
};

/** Pencil on a print's border, written on from left to right. */
const Pencil: React.FC<{ text: string; size: number; cx: number; top: number; k: number; rot?: number }> = ({ text, size, cx, top, k, rot = 0 }) => {
  if (k <= 0.001 || !text) return null;
  return (
    <div style={{ position: "absolute", left: cx - 600, width: 1200, top, textAlign: "center", transform: rot ? `rotate(${rot}deg)` : undefined }}>
      <span style={{ display: "inline-block", fontFamily: HAND, fontWeight: 600, fontSize: size, lineHeight: 1.12, color: GRAPHITE, whiteSpace: "nowrap", clipPath: `inset(-25% ${((1 - k) * 100).toFixed(2)}% -25% -6%)` }}>{text}</span>
    </div>
  );
};

// ------------------------------------------------------------------ the scenes

type Scene = React.FC<{ f: number; g: number; p: ReelProps; ar: number[] }>;

// ··· bars 0-1 · the contact sheet: a roll of twelve on the light box; the decisive frame cut out and lifted away

const FW = 280, FH = 187, FGAP = 14, REB = 42, SGAP = 20, SM = 34;
const STRIP_W = 3 * (FW + FGAP) + FGAP;           // a strip of three frames
const STRIP_H = FH + 2 * REB;                      // with the film's edge above and below
const SHEET_W = STRIP_W + 2 * SM;
const SHEET_H = 4 * STRIP_H + 3 * SGAP + 2 * SM;
const SHEET_TOP = 620, SHEET_ROT = -0.8;
const frameXY = (n: number) => ({ x: SM + FGAP + (n % 3) * (FW + FGAP), y: SM + Math.floor(n / 3) * (STRIP_H + SGAP) + REB });
const HERO_N = 7;                                   // the decisive frame: the third strip, the middle one
const HERO_MID: Pt = [frameXY(HERO_N).x + FW / 2, frameXY(HERO_N).y + FH / 2];

/** The roll: the leader fogged (null), then eleven pictures, each once: the hero in the middle of the third strip, the
 *  post's photos that carry no word spread among the fillers. */
const roll = (p: ReelProps, ar: number[]): (Shaped | null)[] => {
  const [a, b, c] = ON_SHEET.map((i) => own(p, ar, i));
  const f = (k: number) => filler(p, ar, k);
  return [null, a, f(0), f(1), b, f(2), f(3), own(p, ar, HERO), f(4), c, f(5), f(6)];
};

/** One frame of the roll, whole, upright and as shot, in the film's black. */
const Frame: React.FC<{ pic: Photo; ar: number }> = ({ pic, ar }) => {
  const box = fitBox(ar, FW, FH);
  return (
    <div style={{ position: "absolute", inset: 0, background: FILM, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: (FW - box.w) / 2, top: (FH - box.h) / 2, width: box.w, height: box.h }}>
        <Shot pic={pic} w={box.w} h={box.h} />
      </div>
    </div>
  );
};

/** The contact sheet, in its own units: neutral paper, the strips printed black, every frame as shot, the film's edge
 *  numbers. cut: the chosen frame has left its place, and the light box shows through the gap. */
const Sheet: React.FC<{ p: ReelProps; ar: number[]; cut: boolean }> = ({ p, ar, cut }) => {
  const r = roll(p, ar);
  const holes = Array.from({ length: 24 }, (_, k) => FGAP / 2 + k * ((STRIP_W - FGAP) / 24) + 9);
  const h = frameXY(HERO_N);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: SHEET_W, height: SHEET_H, background: PRINT }}>
      {[0, 1, 2, 3].map((row) => (
        <div key={row} style={{ position: "absolute", left: SM, top: SM + row * (STRIP_H + SGAP), width: STRIP_W, height: STRIP_H, background: "#1A1A1A" }}>
          <svg width={STRIP_W} height={STRIP_H} style={{ position: "absolute", left: 0, top: 0 }}>
            {holes.map((x, k) => (
              <React.Fragment key={k}>
                <rect x={x} y={REB - 18} width={17} height={14} rx={3.5} fill={FILM} />
                <rect x={x} y={REB + FH + 4} width={17} height={14} rx={3.5} fill={FILM} />
              </React.Fragment>
            ))}
            {[0, 1, 2].map((c) => {
              const n = row * 3 + c + 1, x = FGAP + c * (FW + FGAP);
              return (
                <g key={c} fill="#A8A6A2">
                  <polygon points={`${x + 10},${STRIP_H - 4} ${x + 10},${STRIP_H - 13} ${x + 17},${STRIP_H - 8.5}`} />
                  <text x={x + 22} y={STRIP_H - 3} fontFamily={MONO} fontSize={13} letterSpacing={1}>{n}</text>
                  <text x={x + FW / 2 + 8} y={STRIP_H - 3} fontFamily={MONO} fontSize={13} letterSpacing={1} opacity={0.75}>{n}</text>
                </g>
              );
            })}
          </svg>
        </div>
      ))}
      {r.map((s, n) => {
        if (n === HERO_N) return null;       // the chosen frame is drawn on its own, so it can be lifted away
        const { x, y } = frameXY(n);
        return (
          <div key={n} style={{ position: "absolute", left: x, top: y, width: FW, height: FH }}>
            {s === null
              ? <div style={{ position: "absolute", inset: 0, background: "linear-gradient(100deg, #FAFAF8, #DEDCD8 45%, #8E8C88 80%, #4A4946)" }} />
              : <Frame pic={s.pic} ar={s.ar} />}
          </div>
        );
      })}
      {/* where the chosen frame was cut from the sheet, the light box shows through */}
      {cut && <div style={{ position: "absolute", left: h.x - 6, top: h.y - 6, width: FW + 12, height: FH + 12, background: `radial-gradient(ellipse 70% 70% at 50% 50%, ${rgb(safe(0.7))}, ${rgb(safe(0.55))})` }} />}
    </div>
  );
};

const Contact: Scene = ({ g, p, ar }) => {
  const drift = lerp(12, -12, soft(clamp01(g / 119)));             // the camera slides along the table, never in
  const cx = W / 2 + drift, cy = SHEET_TOP + SHEET_H / 2;
  const toScreen = (q: Pt): Pt => {
    const a = (SHEET_ROT * Math.PI) / 180, x = q[0] - SHEET_W / 2, y = q[1] - SHEET_H / 2;
    return [cx + x * Math.cos(a) - y * Math.sin(a), cy + x * Math.sin(a) + y * Math.cos(a)];
  };
  // the choice: once the hook has gone, the chosen frame is cut from the sheet and lifted away by hand
  const lift = soft(clamp01((g - 72) / 30));
  const at = lerpPt(toScreen(HERO_MID), [W / 2, 404], lift);
  const arc = Math.sin(Math.PI * lift) * 26;                         // a hand's path: up, over, and down
  const tilt = lerp(SHEET_ROT, 0, lift) + Math.sin(Math.PI * lift) * 2.4;
  // its shadow falls on the dark above the sheet, never across the other frames
  const top0 = toScreen([0, 0]), top1 = toScreen([SHEET_W, 0]);
  const slope = (top1[1] - top0[1]) / (top1[0] - top0[0]);
  const above = `polygon(0px 0px, ${W}px 0px, ${W}px ${(top0[1] + slope * (W - top0[0])).toFixed(1)}px, 0px ${(top0[1] - slope * top0[0]).toFixed(1)}px)`;
  const hero = own(p, ar, HERO);
  // the hook: set at frame 0, held two seconds, gone before the choice
  const open = pair(p.open[0], p.open[1]);
  const openS = Math.min(208, 960 / runsEm(open));
  const subS = Math.min(openS * 0.62, fitSize(p.openSub, ITALIC, 900, 130));
  const gone = ramp(g, 62, 70, soft);
  return (
    <AbsoluteFill style={{ background: DARK }}>
      {/* the light box's glow round the sheet: the room's light */}
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 72% 40% at 50% ${((cy + 60) / H) * 100}%, ${rgb(safe(0.55), 0.24)}, transparent 72%)` }} />
      <div style={{ position: "absolute", left: cx - SHEET_W / 2 - 40, top: cy - SHEET_H / 2 - 40, width: SHEET_W + 80, height: SHEET_H + 80, borderRadius: 10, background: rgb(safe(0.42)), transform: `rotate(${SHEET_ROT}deg)`, boxShadow: `0 0 90px 30px ${rgb(safe(0.6), 0.18)}` }} />
      <div style={{ position: "absolute", left: 0, top: 0, transform: `translate(${cx}px, ${cy}px) rotate(${SHEET_ROT}deg) translate(${-SHEET_W / 2}px, ${-SHEET_H / 2}px)`, transformOrigin: "0 0" }}>
        <Sheet p={p} ar={ar} cut={lift > 0.001} />
      </div>
      {lift > 0.001 && (
        <AbsoluteFill style={{ clipPath: above }}>
          <div style={{ position: "absolute", left: at[0] - FW / 2 + 14 + 18 * lift, top: at[1] - arc - FH / 2 + 18 + 26 * lift, width: FW, height: FH, background: `rgba(${D},.8)`, filter: `blur(${(6 + 12 * lift).toFixed(1)}px)`, transform: `rotate(${tilt.toFixed(2)}deg)` }} />
        </AbsoluteFill>
      )}
      <div style={{ position: "absolute", left: at[0] - FW / 2, top: at[1] - arc - FH / 2, width: FW, height: FH, transform: `rotate(${tilt.toFixed(3)}deg)` }}>
        <Frame pic={hero.pic} ar={hero.ar} />
      </div>
      <Develop runs={open} size={openS} top={150} gone={gone} />
      <Develop runs={[{ text: p.openSub, face: ITALIC }]} size={subS} top={150 + openS * 1.04} gone={gone} />
    </AbsoluteFill>
  );
};

// ··· bar 2 · the enlarger: the chosen frame goes into the carrier and the beam lays the picture on the easel

/** The easel, lying on the baseboard, seen from above and in front: a plane tilted back about its centre. */
const EZ = { cx: 540, cy: 1000, w: 860, h: 640, tilt: 50, P: 2200, ox: 540, oy: 420 };
const LENS: Pt = [540, 354];
const CARRIER_Y = 204;                                     // the negative carrier's slot, between lamphouse and bellows
/** A point on the easel (its own px) to the screen, as CSS perspective draws it. */
const onEasel = (x: number, y: number): Pt => {
  const a = (EZ.tilt * Math.PI) / 180, dx = x - EZ.w / 2, dy = y - EZ.h / 2;
  const sx = EZ.cx + dx, sy = EZ.cy + dy * Math.cos(a), z = dy * Math.sin(a);
  const k = EZ.P / (EZ.P - z);
  return [EZ.ox + (sx - EZ.ox) * k, EZ.oy + (sy - EZ.oy) * k];
};

/** The enlarger's head: lamphouse (light leaking from its vents), the carrier's slot, bellows, lens; column and arm. */
const Head: React.FC<{ lamp: number }> = ({ lamp }) => {
  const edge = rgb(safe(0.5));
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <defs>
        <linearGradient id="dr-body" x1="0" x2="1"><stop offset="0" stopColor="#40200f" /><stop offset="0.16" stopColor="#1d0f09" /><stop offset="1" stopColor="#0c0605" /></linearGradient>
        <radialGradient id="dr-lensglow"><stop offset="0" stopColor={rgb(LAMP, 0.55 * lamp)} /><stop offset="1" stopColor={rgb(LAMP, 0)} /></radialGradient>
      </defs>
      <rect x={850} y={-10} width={30} height={800} fill="url(#dr-body)" />
      <rect x={640} y={118} width={226} height={34} fill="url(#dr-body)" />
      <rect x={378} y={16} width={324} height={180} rx={26} fill="url(#dr-body)" stroke={edge} strokeOpacity={0.4} strokeWidth={2} />
      {[0, 1, 2, 3].map((k) => <rect key={k} x={424} y={54 + k * 24} width={232} height={5} rx={2.5} fill={rgb(LAMP, 0.7 * lamp)} />)}
      <rect x={360} y={CARRIER_Y - 8} width={360} height={16} fill="#0a0504" stroke={edge} strokeOpacity={0.35} />
      <polygon points="430,212 650,212 612,300 468,300" fill="#130906" />
      {Array.from({ length: 7 }, (_, k) => { const y = 220 + k * 12, t = (y - 212) / 88; return <line key={k} x1={430 + 38 * t} y1={y} x2={650 - 38 * t} y2={y} stroke={edge} strokeOpacity={0.28} strokeWidth={2} />; })}
      <rect x={450} y={300} width={180} height={20} fill="url(#dr-body)" />
      <rect x={504} y={320} width={72} height={32} fill="#0d0605" stroke={edge} strokeOpacity={0.45} />
      {[0, 1, 2, 3, 4, 5].map((k) => <line key={k} x1={510 + k * 12} y1={322} x2={510 + k * 12} y2={350} stroke={edge} strokeOpacity={0.25} />)}
      <circle cx={540} cy={360} r={90} fill="url(#dr-lensglow)" />
      <ellipse cx={540} cy={354} rx={30} ry={7} fill={rgb(LAMP, 0.95 * lamp)} />
    </svg>
  );
};

/** The darkroom timer on the wall: a luminous dial, its hand (Event Caliber's colour) jumping a second on every beat. */
const Timer: React.FC<{ cx: number; cy: number; r: number; f: number; hand: string }> = ({ cx, cy, r, f, hand }) => {
  const lum = rgb(safe(0.78));
  const beat = Math.floor(f / 15), t = f % 15;
  const kick = t === 0 ? 0.22 : t === 1 ? -0.08 : t === 2 ? 0.03 : 0;     // the hand's jump, with its weight
  const a = ((52 + beat + kick) / 60) * Math.PI * 2;
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <circle cx={cx} cy={cy} r={r + 12} fill="#1b0d08" stroke={rgb(safe(0.45))} strokeOpacity={0.5} strokeWidth={3} />
      <circle cx={cx} cy={cy} r={r} fill="#0a0504" />
      {Array.from({ length: 60 }, (_, i) => {
        const b = (i / 60) * Math.PI * 2, l = i % 5 === 0 ? 16 : 7;
        return <line key={i} x1={cx + Math.sin(b) * (r - 6)} y1={cy - Math.cos(b) * (r - 6)} x2={cx + Math.sin(b) * (r - 6 - l)} y2={cy - Math.cos(b) * (r - 6 - l)} stroke={lum} strokeWidth={i % 5 === 0 ? 3 : 1.5} opacity={0.85} />;
      })}
      {[0, 10, 20, 30, 40, 50].map((n) => {
        const b = (n / 60) * Math.PI * 2;
        return <text key={n} x={cx + Math.sin(b) * (r - 40)} y={cy - Math.cos(b) * (r - 40) + 8} textAnchor="middle" fontFamily={MONO} fontSize={22} fill={lum}>{n}</text>;
      })}
      <line x1={cx - Math.sin(a) * 18} y1={cy + Math.cos(a) * 18} x2={cx + Math.sin(a) * (r - 14)} y2={cy - Math.cos(a) * (r - 14)} stroke={hand} strokeWidth={4} strokeLinecap="round" />
      <circle cx={cx} cy={cy} r={8} fill={hand} />
    </svg>
  );
};

const Enlarger: Scene = ({ f, g, p, ar }) => {
  const hero = own(p, ar, HERO);
  // the chosen frame slides into the carrier, then the lamp clicks on
  const into = soft(clamp01(f / 10));
  const fb = fitBox(hero.ar, FW * 0.62, FH * 0.62);
  const lamp = f < 11 ? 0 : f === 11 ? 0.3 : f === 12 ? 1 : f === 13 ? 0.72 : 1;
  // the opening between the easel's blades, set to the picture's shape: paper waiting in the safelight until the lamp
  // lays the picture on it, positive and in its own colours, the lamp's warmth on it while it burns
  const box = fitBox(hero.ar, EZ.w - 120, EZ.h - 110);
  const OPEN = { x: (EZ.w - box.w) / 2, y: (EZ.h - box.h) / 2, w: box.w, h: box.h };
  const shown = ramp(f, 11, 15, Easing.out(Easing.quad));
  const cone = [onEasel(OPEN.x, OPEN.y), onEasel(OPEN.x + OPEN.w, OPEN.y), onEasel(OPEN.x + OPEN.w, OPEN.y + OPEN.h), onEasel(OPEN.x, OPEN.y + OPEN.h)];
  const conePts = [LENS, cone[1], cone[2], cone[3], cone[0]].map((q) => q.map((v) => v.toFixed(1)).join(",")).join(" ");
  // dust in the beam, drifting
  const motes = Array.from({ length: 34 }, (_, i) => {
    const u = (random(`mu${i}`) + g * (0.0012 + 0.001 * random(`ms${i}`)) + 1 + noise2D(`mn${i}`, g * 0.01, 0) * 0.04) % 1;
    const v = clamp01(random(`mv${i}`) + noise2D(`mw${i}`, 0, g * 0.012) * 0.06);
    const end = lerpPt(lerpPt(cone[3], cone[2], v), lerpPt(cone[0], cone[1], v), 0.5);
    return { q: lerpPt(LENS, end, 0.12 + u * 0.82), r: 1.2 + 2.2 * random(`mr${i}`), a: 0.25 + 0.5 * random(`ma${i}`) };
  }).filter((m) => m.q[1] < Math.min(cone[0][1], cone[1][1]) - 12);       // in the air above the easel, off the picture
  const l1 = pair(p.line1[0], p.line1[1]);
  const l1S = Math.min(150, 940 / runsEm(l1));
  return (
    <AbsoluteFill style={{ background: DARK }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 62% 30% at 50% 56%, ${rgb(safe(0.2), 0.55)}, transparent 75%)` }} />
      {/* the chosen frame, as shot, carried in from the left at the carrier's height and slid in behind the head */}
      {into < 0.999 && (
        <div style={{ position: "absolute", left: lerp(-fb.w - 40, 540 - fb.w / 2, into), top: CARRIER_Y - fb.h / 2, width: fb.w, height: fb.h }}>
          <Shot pic={hero.pic} w={fb.w} h={fb.h} />
        </div>
      )}
      <Head lamp={lamp} />
      <AbsoluteFill style={{ perspective: `${EZ.P}px`, perspectiveOrigin: `${EZ.ox}px ${EZ.oy}px` }}>
        <div style={{ position: "absolute", left: EZ.cx - EZ.w / 2, top: EZ.cy - EZ.h / 2, width: EZ.w, height: EZ.h, transform: `rotateX(${EZ.tilt}deg)`, transformOrigin: "50% 50%",
          background: rgb(safe(0.5)), boxShadow: `0 30px 60px rgba(${D},.8)`, borderRadius: 6 }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: 6, background: `radial-gradient(ellipse 60% 70% at 50% 50%, ${rgb(LAMP, 0.38 * lamp)}, ${rgb(LAMP, 0.06 * lamp)} 80%)` }} />
          <div style={{ position: "absolute", left: OPEN.x, top: OPEN.y, width: OPEN.w, height: OPEN.h, overflow: "hidden", background: rgb(safe(0.62)) }}>
            <div style={{ position: "absolute", inset: 0, opacity: shown }}>
              <Shot pic={hero.pic} w={OPEN.w} h={OPEN.h} />
            </div>
            {/* the beam's own light on it, warmest under the lens, while the lamp is on */}
            <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen", opacity: 0.2 * lamp, background: `radial-gradient(ellipse 70% 75% at 50% 42%, ${rgb(LAMP)}, ${rgb(LAMP, 0)} 100%)` }} />
          </div>
        </div>
      </AbsoluteFill>
      {/* the beam in the air, shown only by the dust in it */}
      {lamp > 0 && (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, mixBlendMode: "screen", opacity: lamp }}>
          <defs>
            <linearGradient id="dr-cone" x1="0" y1={LENS[1]} x2="0" y2={cone[2][1]} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={rgb(LAMP, 0.34)} /><stop offset="0.5" stopColor={rgb(LAMP, 0.1)} /><stop offset="1" stopColor={rgb(LAMP, 0.05)} />
            </linearGradient>
          </defs>
          <polygon points={conePts} fill="url(#dr-cone)" />
          {motes.map((m, i) => <circle key={i} cx={m.q[0]} cy={m.q[1]} r={m.r} fill={rgb(LAMP, m.a)} />)}
        </svg>
      )}
      <Timer cx={176} cy={236} r={112} f={f} hand={p.accent} />
      <Develop runs={l1} size={l1S} top={1450} k={ramp(f, 14, 26, expoOut)} gone={ramp(f, 55, 59, soft)} />
    </AbsoluteFill>
  );
};

// ··· bar 3 · the tray: the paper goes in and the picture comes up out of paper white, shadows first, highlights last

const Tray: Scene = ({ f, p, ar }) => {
  const hero = own(p, ar, HERO);
  const box = fitBox(hero.ar, 780, 700);
  const B = 28, BB = 118;                                  // the print's borders, the bottom one wide for pencil
  const pw = box.w + 2 * B, phh = box.h + B + BB;
  const tw = pw + 116, th = phh + 116, cy = 1110;         // the tray round it
  const sp = spring({ frame: f, fps: FPS, config: { damping: 15, stiffness: 105, mass: 0.9 } });
  const slide = (1 - sp) * -1500;
  const t = 1 - Math.pow(1 - clamp01((f - 10) / 40), 1.6);
  const rock = Math.sin(f * 0.11);
  const stackS = fitSize(p.stackLabel, PENCIL, box.w - 40, 66);
  const l2 = pair(p.line2[0], p.line2[1]);
  const l2S = Math.min(150, 940 / runsEm(l2));
  const trayTop = cy - th / 2;
  return (
    <AbsoluteFill style={{ background: DARK }}>
      {t < 1 && (
        <svg width={0} height={0} style={{ position: "absolute" }}>
          <defs>
            {/* the developer: the picture's own pixels, let through from paper white by how dark each one is */}
            <filter id="dr-dev" colorInterpolationFilters="sRGB" x="0%" y="0%" width="100%" height="100%">
              <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.3 0.59 0.11 0 0" result="lum" />
              <feComponentTransfer in="lum" result="mask"><feFuncA type="table" tableValues={table((v) => arrived(v, t))} /></feComponentTransfer>
              <feComposite in="SourceGraphic" in2="mask" operator="in" />
            </filter>
          </defs>
        </svg>
      )}
      {/* the tray: its rim, the dark bath with faint ribs, the safelight lying on the moving surface */}
      <div style={{ position: "absolute", left: W / 2 - tw / 2 - 30, top: trayTop - 30, width: tw + 60, height: th + 60, borderRadius: 40, background: rgb(safe(0.62)), boxShadow: `0 40px 80px rgba(${D},.9), inset 0 0 0 3px ${rgb(safe(0.75))}` }} />
      <div style={{ position: "absolute", left: W / 2 - tw / 2, top: trayTop, width: tw, height: th, borderRadius: 26, overflow: "hidden", background: `radial-gradient(ellipse 70% 60% at 45% 40%, ${rgb(safe(0.34))}, ${rgb(safe(0.22))})`, boxShadow: `inset 0 10px 30px rgba(${D},.6)` }}>
        {[0, 1, 2, 3].map((k) => <div key={k} style={{ position: "absolute", left: 0, right: 0, top: 90 + k * (th / 4), height: 5, background: rgb(safe(0.16), 0.6) }} />)}
        {[0, 1].map((n) => {
          const y = -400 + ((f * (5 + n * 3) + n * 560 + rock * 50 + 1800) % 1800);
          return <div key={n} style={{ position: "absolute", left: -200, width: tw + 400, top: y, height: 220, transform: `rotate(${-14 + n * 9}deg)`, mixBlendMode: "screen", opacity: 0.16 - n * 0.05, background: `linear-gradient(180deg, transparent, ${rgb(safe(0.95), 1)} 50%, transparent)` }} />;
        })}
        <div style={{ position: "absolute", left: 30, top: 22, width: 240, height: 70, borderRadius: 14, mixBlendMode: "screen", opacity: 0.55, background: "linear-gradient(180deg, rgba(255,120,52,.9), rgba(214,58,24,.7))", filter: "blur(7px)", transform: `translate(${(rock * 10).toFixed(2)}px, ${(Math.cos(f * 0.11) * 4).toFixed(2)}px) skewX(${(rock * 3).toFixed(2)}deg)` }} />
      </div>
      {/* the print, lying in the bath: its paper neutral, its picture coming up out of paper white */}
      <div style={{ position: "absolute", left: W / 2 - pw / 2, top: cy - phh / 2 + slide, width: pw, height: phh, transform: `rotate(${lerp(-6, 0.8, sp).toFixed(3)}deg)` }}>
        <div style={{ position: "absolute", inset: 0, background: PRINT, boxShadow: `0 8px 22px rgba(${D},.55)` }} />
        <div style={{ position: "absolute", left: B, top: B, width: box.w, height: box.h }}>
          <Shot pic={hero.pic} w={box.w} h={box.h} filter={t < 1 ? "url(#dr-dev)" : undefined} />
        </div>
        <Pencil text={p.stackLabel} size={stackS} cx={pw / 2} top={B + box.h + (BB - stackS * 1.12) / 2 + 4} k={ramp(f, 30, 44, Easing.linear)} rot={-1.2} />
        {/* the wave the paper makes going in: one band of the safelight on the developer, crossing the print once */}
        {f >= 8 && f <= 22 && <div style={{ position: "absolute", left: -20, right: -20, top: lerp(-140, phh + 20, (f - 8) / 14), height: 120, mixBlendMode: "screen", opacity: 0.3 * Math.sin(Math.PI * (f - 8) / 14), background: `linear-gradient(180deg, transparent, ${rgb(safe(0.95))}, transparent)` }} />}
      </div>
      <Develop runs={l2} size={l2S} top={trayTop - l2S - 150} k={ramp(f, 16, 28, expoOut)} gone={ramp(f, 55, 59, soft)} />
    </AbsoluteFill>
  );
};

// ··· bar 4 · the zone scale: the number placed among the eleven tones from black to paper white

const ZONES = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
const Zones: Scene = ({ f, p }) => {
  const v = p.counter.value;
  const numS = fitSize(v, ROMAN, 900, 720);
  const labS = fitSize(p.counter.label, ITALIC, 860, 84);
  const unitS = fitSize(p.counter.unit, ITALIC, 860, 132);
  const t = clamp01(f / 26);
  const m = metrics(ROMAN);
  const capTop = 500;                                    // where the figures' tops sit
  const numTop = capTop - (m.base - m.cap) * numS;
  const base = numTop + m.base * numS;
  const SX = 46, SY = base + unitS + 150, SW = W - 92, PW_ = (SW - 40) / 11, PH_ = 150;
  const out = ramp(f, 55, 59, soft);
  const grey = (z: number) => { const g8 = 255 * (1 - (1 - z) * arrived(z, t)); return `rgb(${g8.toFixed(0)},${g8.toFixed(0)},${(g8 * 0.985).toFixed(0)})`; };
  return (
    <AbsoluteFill style={{ background: DARK }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 40% at 50% 0%, ${rgb(safe(0.5), 0.22)}, transparent 70%)` }} />
      <Develop runs={[{ text: p.counter.label, face: ITALIC }]} size={labS} top={capTop - labS - 70} k={ramp(f, 0, 14, expoOut)} gone={out} opacity={0.88} />
      <Develop runs={[{ text: v, face: ROMAN }]} size={numS} top={numTop} k={ramp(f, 4, 24, expoOut)} gone={out} />
      <Develop runs={[{ text: p.counter.unit, face: ITALIC }]} size={unitS} top={base + 30} k={ramp(f, 10, 26, expoOut)} gone={out} />
      {/* the step tablet, printed on a strip of paper, developing like a print: Zone 0 first, Zone X never darkens */}
      <div style={{ position: "absolute", left: SX, top: SY, width: SW, height: PH_ + 112, background: PRINT, boxShadow: `0 20px 50px rgba(${D},.7)`, transform: `translateY(${((1 - expoOut(clamp01(f / 14))) * 60).toFixed(2)}px)` }}>
        {ZONES.map((z, i) => (
          <React.Fragment key={z}>
            <div style={{ position: "absolute", left: 20 + i * PW_, top: 20, width: PW_ + 0.5, height: PH_, background: grey(0.03 + 0.97 * (i / 10)) }} />
            <div style={{ position: "absolute", left: 20 + i * PW_, top: PH_ + 38, width: PW_, textAlign: "center", fontFamily: MONO, fontSize: 26, lineHeight: 1, color: GRAPHITE }}>{z}</div>
          </React.Fragment>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ··· bar 5 · the drying lines: three prints pegged up one a beat, each word pencilled on its border

const LINES_Y = [300, 790, 1280];
const LINE_X = [372, 708, 372];                            // the prints zigzag down the wall, each on its own line
const DP = { maxW: 510, maxH: 340, b: 16, bb: 94 };       // a drying print: the picture's box, its borders
const sag = (y: number, x: number) => y + 18 * (1 - Math.pow((x - W / 2) / 560, 2));

/** A clothes peg seen from the front: one wooden slat and its spring; it tilts while open and straightens shut. In the
 *  safelight, its light falls with the room's (light); in daylight it is wood. */
const Peg: React.FC<{ x: number; y: number; open: number; day?: boolean; light?: number }> = ({ x, y, open, day, light = 1 }) => (
  <div style={{ position: "absolute", left: x - 11, top: y - 34, width: 22, height: 74, transform: `rotate(${(open * 14).toFixed(2)}deg)`, transformOrigin: "50% 46%", filter: light < 0.999 ? `brightness(${light.toFixed(3)})` : undefined }}>
    <div style={{ position: "absolute", inset: 0, borderRadius: 4, background: day ? "linear-gradient(90deg, #D6B48C, #C29B70 60%, #A98157)" : `linear-gradient(90deg, ${rgb(safe(0.62))}, ${rgb(safe(0.48))} 60%, ${rgb(safe(0.36))})`, boxShadow: day ? "-6px 8px 10px rgba(60,45,30,.28)" : `0 4px 8px rgba(${D},.6)` }} />
    <div style={{ position: "absolute", left: -3, top: 30, width: 28, height: 8, borderRadius: 4, background: day ? "#77736d" : rgb(safe(0.2)) }} />
  </div>
);

const Drying: Scene = ({ f, p, ar }) => {
  const idx = p.wordPhotos;
  const wordS = Math.min(...p.words.map((w) => fitSize(w, PENCIL, DP.maxW - 40, 78)));
  const room = 1 - ramp(f, 56, 59, Easing.in(Easing.quad));     // the safelight clicks off on the last beat
  return (
    <AbsoluteFill style={{ background: DARK }}>
      {/* the room: the safelight above, its glow on the wall, the lines; all of it goes with the lamp */}
      <AbsoluteFill style={{ opacity: room }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse 66% 30% at 50% 4%, rgba(255,92,40,.2), transparent 72%)" }} />
        <div style={{ position: "absolute", left: 420, top: 70, width: 240, height: 92, borderRadius: 10, background: "linear-gradient(180deg, #2a140c, #120806)", boxShadow: `0 0 0 2px ${rgb(safe(0.3), 0.6)}` }} />
        <div style={{ position: "absolute", left: 438, top: 84, width: 204, height: 64, borderRadius: 5, background: "linear-gradient(180deg, rgb(255,120,52), rgb(214,58,24))", boxShadow: "0 0 60px rgba(255,90,40,.7)" }} />
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          {LINES_Y.map((y, i) => <path key={i} d={`M -20 ${sag(y, -20)} Q ${W / 2} ${y + 36} ${W + 20} ${sag(y, W + 20)}`} fill="none" stroke={rgb(safe(0.5))} strokeWidth={3} />)}
        </svg>
      </AbsoluteFill>
      {LINES_Y.map((ly, i) => {
        const x = LINE_X[i], y = sag(ly, x);
        const lf = f - i * 15;
        if (lf < 0) return <Peg key={i} x={x} y={y} open={1} light={room} />;
        const { pic, ar: a } = own(p, ar, idx[i]);
        const box = fitBox(a, DP.maxW, DP.maxH);
        const pw = box.w + 2 * DP.b, phh = box.h + DP.b + DP.bb;
        const up = expoOut(clamp01(lf / 8));
        const s = Math.max(0, lf - 8);
        const swing = lf < 8 ? lerp(6, 3, up) : 3 * Math.exp(-s / 13) * Math.cos((s * 2 * Math.PI) / 26);
        // drips from the lowest print only, falling to the floor, never across another picture
        const drops = i === 2 ? Array.from({ length: 5 }, (_, j) => {
          const born = 12 + j * 9 + random(`db${j}`) * 4, age = lf - born;
          if (age < 0) return null;
          const yy = y + phh + 2 + 0.85 * age * age;
          if (yy > H) return null;
          return <div key={j} style={{ position: "absolute", left: x + (random(`dx${j}`) - 0.5) * pw * 0.8 - 3, top: yy, width: 6, height: 15, borderRadius: "50% 50% 50% 50% / 60% 60% 40% 40%", background: rgb(safe(0.92), 0.85 * room) }} />;
        }) : null;
        return (
          <React.Fragment key={i}>
            {drops}
            <div style={{ position: "absolute", left: x - pw / 2, top: y - 6 + (1 - up) * 300, width: pw, height: phh, transform: `rotate(${swing.toFixed(3)}deg)`, transformOrigin: "50% 0%" }}>
              <div style={{ position: "absolute", inset: 0, background: PRINT, boxShadow: `0 18px 40px rgba(${D},${(0.75 * room).toFixed(3)})` }} />
              <div style={{ position: "absolute", left: DP.b, top: DP.b, width: box.w, height: box.h }}>
                <Shot pic={pic} w={box.w} h={box.h} />
              </div>
              <Pencil text={p.words[i]} size={wordS} cx={pw / 2} top={DP.b + box.h + (DP.bb - wordS * 1.12) / 2 + 2} k={ramp(lf, 9, 19, Easing.linear)} rot={-1.5} />
            </div>
            <Peg x={x} y={y} open={1 - ramp(lf, 6, 9, Easing.out(Easing.quad))} light={room} />
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};

// ··· bar 6 · daylight: the hero on the line in the dark room; the door opens and daylight fills the room round it

const MOUNT = { side: 24, top: 64, bottom: 24 };          // the card it is pinned by, so the pegs never touch the picture
const Daylight: Scene = ({ f, p, ar }) => {
  const piece = own(p, ar, HERO);
  const box = fitBox(piece.ar, 900, 760);
  const mTop = 360, px = W / 2 - box.w / 2, py = mTop + MOUNT.top;
  const mw = box.w + 2 * MOUNT.side, mh = MOUNT.top + box.h + MOUNT.bottom;
  const lineAt = mTop + 16;
  // the door, at the right, swings open: its light sweeps across the room from a crack to everything
  const door = Easing.bezier(0.5, 0, 0.25, 1)(clamp01((f - 4) / 16));
  const edge = lerp(101, -46, door);
  const mask = `linear-gradient(97deg, transparent ${edge.toFixed(2)}%, #000 ${(edge + 22).toFixed(2)}%)`;
  const marS = fitSize(p.marquee, ITALIC, 880, 220);
  const pegs = (day: boolean) => (
    <>
      <Peg x={px + 90} y={lineAt} open={0} day={day} light={day ? 1 : 0.08} />
      <Peg x={px + box.w - 90} y={lineAt} open={0} day={day} light={day ? 1 : 0.08} />
    </>
  );
  return (
    <AbsoluteFill style={{ background: DARK }}>
      {/* the room in daylight, where the door's light has reached: the wall, the line, the print's shadow */}
      <AbsoluteFill style={{ WebkitMaskImage: mask, maskImage: mask }}>
        <AbsoluteFill style={{ background: `linear-gradient(100deg, #D9D3C8 0%, ${WALL} 46%, #F1EEE8 100%)` }} />
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <line x1={-20} y1={lineAt + 30} x2={W + 20} y2={lineAt + 30} stroke="rgba(70,55,40,.16)" strokeWidth={4} filter="url(#dr-soft)" />
          <line x1={-20} y1={lineAt} x2={W + 20} y2={lineAt} stroke="#5E554B" strokeWidth={3} />
        </svg>
        <div style={{ position: "absolute", left: px - MOUNT.side - 18, top: mTop + 26, width: mw, height: mh, background: "rgba(60,45,30,.26)", filter: "blur(17px)" }} />
      </AbsoluteFill>
      {/* the print and its card: as shot, the same in the dark as in the light */}
      <div style={{ position: "absolute", left: px - MOUNT.side, top: mTop, width: mw, height: mh, background: PAPER }} />
      <div style={{ position: "absolute", left: px, top: py, width: box.w, height: box.h }}>
        <Shot pic={piece.pic} w={box.w} h={box.h} />
      </div>
      {pegs(false)}
      <AbsoluteFill style={{ WebkitMaskImage: mask, maskImage: mask }}>{pegs(true)}</AbsoluteFill>
      <Develop runs={[{ text: p.marquee, face: ITALIC }]} size={marS} top={py + box.h + MOUNT.bottom + 60} k={ramp(f, 24, 36, expoOut)} color={INK} />
    </AbsoluteFill>
  );
};

// ··· bar 7 · the end card: a fine print, the hero whole above, its border annotated

const FinePrint: Scene = ({ f, p, ar }) => {
  const hero = own(p, ar, HERO);
  const box = fitBox(hero.ar, 840, 560);
  const imgTop = 190;
  const nameS = fitSize(p.business, ROMAN, 880, 164, -0.01);
  const kickS = fitSize(p.kicker, ITALIC, 860, 72);
  const ctaS = fitSize(p.cta, ROMAN, 680, 60);
  const ctaW = textWidth(p.cta, ROMAN, ctaS) + 110, ctaH = ctaS + 54;
  const siteS = fitSize(p.phone, ROMAN, 820, 64);
  const townS = Math.min(34, 760 / (textWidth(p.town.toUpperCase(), ROMAN, 1, 0.24) + 0.24));
  const nameTop = imgTop + box.h + 104, kickTop = nameTop + nameS + 18, ctaTop = kickTop + kickS + 72;
  const siteTop = ctaTop + ctaH + 72, townTop = siteTop + siteS + 30;
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <div style={{ position: "absolute", left: W / 2 - box.w / 2, top: imgTop, width: box.w, height: box.h }}>
        <Shot pic={hero.pic} w={box.w} h={box.h} />
      </div>
      <Develop runs={[{ text: p.business, face: ROMAN }]} size={nameS} top={nameTop} k={ramp(f, 2, 14, expoOut)} color={INK} track={-0.01} />
      <Develop runs={[{ text: p.kicker, face: ITALIC }]} size={kickS} top={kickTop} k={ramp(f, 5, 16, expoOut)} color={INK} opacity={0.78} />
      <div style={{ position: "absolute", left: W / 2 - ctaW / 2, top: ctaTop, width: ctaW, height: ctaH, background: p.accent, opacity: ramp(f, 8, 16, expoOut), transform: `scaleX(${(0.9 + 0.1 * expoOut(clamp01((f - 8) / 10))).toFixed(4)})` }} />
      <Develop runs={[{ text: p.cta, face: ROMAN }]} size={ctaS} top={ctaTop + (ctaH - ctaS) / 2 + 2} k={ramp(f, 9, 18, expoOut)} color={onColour(p.accent)} />
      <Develop runs={[{ text: p.phone, face: ROMAN }]} size={siteS} top={siteTop} k={ramp(f, 12, 20, expoOut)} color={INK} />
      <Develop runs={[{ text: p.town, face: ROMAN }]} size={townS} top={townTop} k={ramp(f, 14, 21, expoOut)} color={INK} caps track={0.24} opacity={0.72} />
    </AbsoluteFill>
  );
};

// the bars: 0-1 are one shot
const SCENES: { at: number; S: Scene }[] = [
  { at: 0, S: Contact }, { at: 120, S: Enlarger }, { at: 180, S: Tray }, { at: 240, S: Zones },
  { at: 300, S: Drying }, { at: 360, S: Daylight }, { at: 420, S: FinePrint },
];

export const Darkroom: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Darkroom");
  const g = useCurrentFrame();
  useFontsReady();
  const ar = useAspects(everyPicture(p));
  const i = SCENES.reduce((n, s, k) => (g >= s.at ? k : n), 0);
  const { at, S } = SCENES[i];
  return (
    <AbsoluteFill style={{ background: DARK, overflow: "hidden" }}>
      <Music track={p.music} />
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <defs><filter id="dr-soft" x="-5%" y="-200%" width="110%" height="500%"><feGaussianBlur stdDeviation="6" /></filter></defs>
      </svg>
      <S f={g - at} g={g} p={p} ar={ar} />
    </AbsoluteFill>
  );
};
