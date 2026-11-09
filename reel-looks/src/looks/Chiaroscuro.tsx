import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, random, staticFile, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { H, Photo, ReelProps, W, clamp, ramp } from "../look";
import { Slots, checkSlots, fillerAt, photoAt } from "../slots";
import { GARAMOND } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// CHIAROSCURO: out of the dark. Every moment of an event sits unseen in the dark until a light finds it.
// Chiaroscuro and Axis are the two looks that grade and light his photos (Chris, 2026-11-08: "Keep the photos from any
// color changes except for only the last two I mentioned").
// The craft of the masters, not their look:
//   tenebrism (one raking light from a high window, everything else falls to near black: the worker in the beam);
//   sfumato (no edge anywhere: light melts into shadow, a painting only exists where it is lit);
//   top light and true blacks that hold mystery (Gordon Willis for Coppola); smoke that shows the beam and long
//   superimposed dissolves (Storaro); the slow, relentless pull back from a detail to the whole tableau (the opening of
//   The Godfather, Barry Lyndon); cross-cutting that quickens into a climax; one precious pigment, used once, like
//   ultramarine (Event Caliber's own colour); pearls of light on gilt (Vermeer).
// Cormorant Garamond, roman and italic, lit by the same lamp as the pictures. A canvas weave on every picture.
//
// 25 s (750 frames; the other looks run 16 s) on the 120 BPM grid of 15-frame beats, the music locked to it:
//    0-4 s    the calling: a detail in the beam, the hook above in the dark; one unbroken 4 s pull back to the tableau
//    4-6 s    the next picture rises through the last (a double exposure), the light moving
//    6-8 s    a triptych of three arched panels; the light falls on each in turn, on the beats, its word beneath
//    8-10 s   the number, carved in light, a sheen passing over it
//   10-14 s   the night watch: one picture in the dark; a spot of light finds three details on the beats, each named,
//             then the whole picture is lit and the stack is set beneath it
//   14-16 s   studies: walking past three paintings, each lit as we come to it, one on each half bar
//   16-18 s   cross-cutting that quickens on the eighths and sixteenths, then black
//   18-19 s   one ember (Event Caliber's colour): the held breath
//   19-22 s   the climax, on the music's entrance: the light opens from above on his picture; pearls on the gilt
//   22-25 s   the invitation, in the last of the light (everything in by frame 26, then holds 2.1 s)
// Music: the suite's Pixabay tracks for Chiaroscuro, locked to the 120 BPM grid (music_tracks.grid), their entrance on
// 19 s (frame 570).

export const CHIAROSCURO_FRAMES = 750;

// ------------------------------------------------------------------ the world

const BIT = "#0A0705";                 // bitumen: the ground, a black that keeps its warmth
const B = "10,7,5";
const GILT = "201,162,98";
type RGB = [number, number, number];
const LAMP: RGB = [255, 214, 160];
const rgba = (c: RGB, a: number) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
const ASSET = (f: string) => staticFile(`textures/chiaroscuro/${f}`);
// Every picture once (Chris, 2026-11-08, night: no picture twice in a reel). The post's seven photos: the hero (slot 0,
// the calling), the three under the arches with their words, the climax's, the night watch's and the picture that
// rises through the hero. The picture far back in the dark under the number, the studies' three paintings and the
// montage's eight cuts are fillers, more of his approved photos.
export const SLOTS: Slots = { photos: 7, fillers: 12 };
const HERO = 0, CLIMAX = 4, WATCHED = 5, RISES = 6;
const BEHIND_NUMBER = 0, STUDIES = [1, 2, 3], CUT_FILLERS = [4, 5, 6, 7, 8, 9, 10, 11];   // filler slots, in the order seen

const ROMAN: Face = { family: GARAMOND, weight: 500 };
const ITALIC: Face = { family: GARAMOND, weight: 500, italic: true };
const LIGHTF: Face = { family: GARAMOND, weight: 400 };
const CAPS: Face = { family: GARAMOND, weight: 600 };

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const smooth = (t: number) => { const x = Math.max(0, Math.min(1, t)); return x * x * (3 - 2 * x); };
const soft = Easing.bezier(0.45, 0, 0.2, 1);
const settle = Easing.bezier(0.3, 0.12, 0.3, 1);   // moving from its first frame, settling at the end

/** Sfumato: a falloff with no edge anywhere, written as many stops so the dark never bands. */
const falloff = (core: number, n = 14, gamma = 1.15) => {
  const s: string[] = [];
  for (let i = 0; i <= n; i++) {
    const t = core + (1 - core) * (i / n);
    s.push(`rgba(0,0,0,${Math.pow(1 - smooth(i / n), gamma).toFixed(3)}) ${(t * 100).toFixed(2)}%`);
  }
  return s.join(", ");
};

// ------------------------------------------------------------------ type, lit by the lamp

/** The lamp's light on a word: brightest up left where the window is, falling warm toward the lower right. */
const litFill = (sheen?: number) => sheen === undefined
  ? "linear-gradient(162deg, #FFF7E6 0%, #F4E4C6 38%, #DCC29A 78%, #B9986E 100%)"
  : `linear-gradient(116deg, #B79A72 0%, #D9C3A0 ${sheen - 22}%, #FFFFFF ${sheen}%, #D9C3A0 ${sheen + 22}%, #8E7252 100%)`;

type Run = { text: string; face: Face };
/** A line of type, made of runs (roman and italic), condensing out of the dark (k) and dissolving up into it (gone). */
const Lit: React.FC<{ runs: Run[]; size: number; top: number; k?: number; gone?: number; track?: number; sheen?: number; caps?: boolean; glow?: number; opacity?: number; cx?: number }> = ({ runs, size, top, k = 1, gone = 0, track = 0, sheen, caps, glow = 0.32, opacity = 1, cx }) => {
  const a = Math.min(1, k * 1.4) * (1 - gone) * opacity;
  if (a <= 0.002) return null;
  const blur = (1 - k) * 14 + gone * 18;
  return (
    <div style={{ position: "absolute", left: cx === undefined ? 0 : cx - 1000, width: cx === undefined ? W : 2000, top: top - gone * 34 + (1 - k) * 18, textAlign: "center", whiteSpace: "nowrap", opacity: a,
      filter: `${blur > 0.2 ? `blur(${blur.toFixed(2)}px) ` : ""}drop-shadow(0 0 ${size * 0.12}px rgba(255,170,100,${glow * 0.45})) drop-shadow(0 ${size * 0.04}px ${size * 0.1}px rgba(${B},.8))` }}>
      <span style={{ fontSize: size, lineHeight: 1, letterSpacing: `${track + (1 - k) * 0.08}em`, paddingLeft: `${track}em`, textTransform: caps ? "uppercase" : "none",
        backgroundImage: litFill(sheen), WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", fontVariantNumeric: "lining-nums" }}>
        {runs.map((r, i) => (
          <span key={i} style={{ fontFamily: r.face.family, fontWeight: r.face.weight, fontStyle: r.face.italic ? "italic" : "normal" }}>{r.text}</span>
        ))}
      </span>
    </div>
  );
};
/** Width of a line of runs in em. */
const runsEm = (runs: Run[], track = 0) => runs.reduce((s, r) => s + textWidth(r.text, r.face, 1, track), 0);
/** A pair like ["Every", "moment."] as a roman word and an italic tail. */
const pair = (a: string, b: string): Run[] => [{ text: a, face: ROMAN }, { text: ` ${b}`, face: ITALIC }];

/** A gilt hairline that draws out from its centre. */
const Gilt: React.FC<{ x: number; y: number; w: number; k: number; a?: number; origin?: string }> = ({ x, y, w, k, a = 0.7, origin = "center" }) => (
  <div style={{ position: "absolute", left: x, top: y - 1, width: w, height: 2, transform: `scaleX(${k})`, transformOrigin: origin,
    background: `linear-gradient(90deg, rgba(${GILT},0), rgba(${GILT},${a}) 22%, rgba(255,236,196,${a}) 50%, rgba(${GILT},${a}) 78%, rgba(${GILT},0))` }} />
);
/** Small caps between two gilt hairlines. */
const Ruled: React.FC<{ text: string; y: number; size: number; k: number; track?: number; reach?: number }> = ({ text, y, size, k, track = 0.26, reach = 110 }) => {
  const tw = textWidth(text.toUpperCase(), CAPS, size, track) + track * size;
  const m = metrics(CAPS);
  const mid = y + (m.base - m.cap / 2) * size;
  return (
    <>
      <Gilt x={W / 2 - tw / 2 - 30 - reach} y={mid} w={reach} k={k} origin="right" />
      <Gilt x={W / 2 + tw / 2 + 30} y={mid} w={reach} k={k} origin="left" />
      <Lit runs={[{ text, face: CAPS }]} size={size} top={y} k={k} caps track={track} glow={0.15} />
    </>
  );
};

// ------------------------------------------------------------------ the pictures, as paintings in the dark

type Pool = { x: number; y: number; r: number; core?: number; aspect?: number; dir?: number; shade?: number };

/** A photo as a painting that exists only where the light falls on it. (cx, cy, w, h): its place at scale 1; s: the
 *  camera's scale about (ox, oy), a point on the painting (0..1); pool: where the light falls, on the painting (0..1),
 *  its radius r a fraction of the painting's width. Graded like old varnished oil; a linen weave over it. */
const Painting: React.FC<{ p: Photo; cx: number; cy: number; w: number; h: number; s?: number; ox?: number; oy?: number; dx?: number; dy?: number; pool: Pool; grade?: boolean; dim?: number; blur?: number; opacity?: number; blend?: React.CSSProperties["mixBlendMode"]; radius?: string; weave?: number; edge?: number }> = ({ p, cx, cy, w, h, s = 1, ox, oy, pool, grade = true, dim = 1, blur = 0, opacity = 1, blend, radius, weave = 0.13, edge = 0.14, dx = 0, dy = 0 }) => {
  if (opacity <= 0.002) return null;
  const px = pool.x * w, py = pool.y * h, rx = pool.r * w, ry = rx * (pool.aspect ?? 1.12);
  const core = pool.core ?? 0.2;
  const masks = [`radial-gradient(ellipse ${rx.toFixed(1)}px ${ry.toFixed(1)}px at ${px.toFixed(1)}px ${py.toFixed(1)}px, #000 0%, ${falloff(core)})`];
  // the far side from the window falls away: a second falloff along the light's direction (dir: CSS degrees, the way the light travels)
  const shade = pool.shade ?? 0.62;
  if (shade > 0) masks.push(`linear-gradient(${pool.dir ?? 152}deg, #000 0%, #000 34%, rgba(0,0,0,${(1 - shade * 0.55).toFixed(3)}) 64%, rgba(0,0,0,${(1 - shade).toFixed(3)}) 100%)`);
  if (edge > 0) masks.push(`linear-gradient(90deg, transparent 0%, #000 ${edge * 100}%, #000 ${100 - edge * 100}%, transparent 100%)`, `linear-gradient(180deg, transparent 0%, #000 ${edge * 80}%, #000 ${100 - edge * 80}%, transparent 100%)`);
  const mask = masks.join(", ");
  const filter = [grade ? "url(#cs-grade)" : "", dim !== 1 ? `brightness(${dim.toFixed(3)})` : "", blur > 0.1 ? `blur(${blur.toFixed(1)}px)` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div style={{ position: "absolute", left: cx - w / 2, top: cy - h / 2, width: w, height: h, transform: s !== 1 || dx || dy ? `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) scale(${s.toFixed(5)})` : undefined,
      transformOrigin: `${((ox ?? p.fx) * 100).toFixed(2)}% ${((oy ?? p.fy) * 100).toFixed(2)}%`, opacity, mixBlendMode: blend }}>
      <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: radius, WebkitMaskImage: mask, maskImage: mask, WebkitMaskComposite: "source-in", maskComposite: "intersect" } as React.CSSProperties}>
        <Img src={staticFile(p.src)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: `${p.fx * 100}% ${p.fy * 100}%`, display: "block", filter }} />
        {/* the light falls off even inside the pool, and the shadows stay umber, never grey */}
        <div style={{ position: "absolute", inset: 0, mixBlendMode: "multiply", background: `radial-gradient(ellipse ${(rx * 1.05).toFixed(1)}px ${(ry * 1.05).toFixed(1)}px at ${(px - rx * 0.08).toFixed(1)}px ${(py - ry * 0.1).toFixed(1)}px, #FFFFFF 0%, #FFF6EA 24%, #B58E6C 62%, #5A3D2A 100%)` }} />
        {/* the hot spot, nearest the window */}
        <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen", background: `radial-gradient(circle ${(rx * 0.55).toFixed(1)}px at ${(px - rx * 0.16).toFixed(1)}px ${(py - ry * 0.22).toFixed(1)}px, ${rgba(LAMP, grade ? 0.14 : 0.08)} 0%, transparent 100%)` }} />
        {weave > 0 && <div style={{ position: "absolute", inset: -2, mixBlendMode: "overlay", opacity: weave, backgroundImage: `url(${ASSET("canvas.png")})`, backgroundSize: "150px 150px" }} />}
      </div>
    </div>
  );
};

// ------------------------------------------------------------------ the light

/** Conic angle (0 up, clockwise) from (sx, sy) to (x, y). */
const angleTo = (sx: number, sy: number, x: number, y: number) => ((Math.atan2(x - sx, -(y - sy)) * 180) / Math.PI + 360) % 360;

/** A shaft of light from a high window: a soft wedge, and smoke drifting through it that only the beam shows. */
const Shaft: React.FC<{ g: number; sx: number; sy: number; tx: number; ty: number; spread: number; k: number; reach?: number; haze?: number; seed?: number }> = ({ g, sx, sy, tx, ty, spread, k, reach = 2600, haze = 1, seed = 0 }) => {
  if (k <= 0.002) return null;
  const dir = angleTo(sx, sy, tx, ty);
  const a0 = dir - spread / 2;
  const breathe = 0.86 + 0.14 * noise2D(`sh${seed}`, g * 0.02, 0);
  const wedge = (alpha: number) => `conic-gradient(from ${a0.toFixed(2)}deg at ${sx}px ${sy}px, transparent 0deg, rgba(0,0,0,${(alpha * 0.55).toFixed(3)}) ${(spread * 0.22).toFixed(2)}deg, rgba(0,0,0,${alpha.toFixed(3)}) ${(spread * 0.5).toFixed(2)}deg, rgba(0,0,0,${(alpha * 0.55).toFixed(3)}) ${(spread * 0.78).toFixed(2)}deg, transparent ${spread.toFixed(2)}deg, transparent 360deg)`;
  const fall = `radial-gradient(circle at ${sx}px ${sy}px, #000 0px, #000 ${(reach * 0.25).toFixed(0)}px, transparent ${reach.toFixed(0)}px)`;
  const both = `${wedge(1)}, ${fall}`;
  const hx = (n: number) => -120 + noise2D(`hx${seed}${n}`, g * 0.004, n) * 90 + g * (0.35 + n * 0.12);
  const hy = (n: number) => -220 - g * (0.55 + n * 0.2) + noise2D(`hy${seed}${n}`, n, g * 0.004) * 70;
  return (
    <>
      {/* the air the beam passes through */}
      <AbsoluteFill style={{ mixBlendMode: "screen", WebkitMaskImage: both, maskImage: both, WebkitMaskComposite: "source-in", maskComposite: "intersect", background: rgba(LAMP, 0.15 * k * breathe) } as React.CSSProperties} />
      {haze > 0 && [0, 1].map((n) => (
        <AbsoluteFill key={n} style={{ mixBlendMode: "screen", WebkitMaskImage: both, maskImage: both, WebkitMaskComposite: "source-in", maskComposite: "intersect" } as React.CSSProperties}>
          <div style={{ position: "absolute", left: hx(n), top: hy(n), width: 1440, height: 2400, background: rgba(LAMP, (n ? 0.32 : 0.42) * k * haze * breathe),
            WebkitMaskImage: `url(${ASSET(`haze-${n}.png`)})`, maskImage: `url(${ASSET(`haze-${n}.png`)})`, WebkitMaskSize: "100% 100%", maskSize: "100% 100%" }} />
        </AbsoluteFill>
      ))}
      {/* the window itself, just out of frame, blooming at the edge */}
      <AbsoluteFill style={{ mixBlendMode: "screen", background: `radial-gradient(circle at ${sx}px ${sy}px, ${rgba(LAMP, 0.5 * k)} 0px, ${rgba(LAMP, 0.12 * k)} 420px, transparent 900px)` }} />
    </>
  );
};

/** One ember in the dark: the held breath before the light. */
const Ember: React.FC<{ x: number; y: number; k: number; g: number; tint: string }> = ({ x, y, k, g, tint }) => {
  if (k <= 0.002) return null;
  const fl = 0.8 + 0.2 * noise2D("ember", g * 0.3, 0);
  const r = 5 + 2 * fl;
  return (
    <>
      <div style={{ position: "absolute", left: x - 160, top: y - 160, width: 320, height: 320, borderRadius: "50%", opacity: k * 0.5 * fl, mixBlendMode: "screen",
        background: `radial-gradient(circle, ${tint} 0%, rgba(${LAMP.join(",")},.25) 18%, transparent 70%)` }} />
      <div style={{ position: "absolute", left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: "50%", opacity: k, background: "radial-gradient(circle, #FFFBF0 0%, #FFD9A0 45%, rgba(255,180,110,0) 100%)" }} />
    </>
  );
};

/** A pearl of light on gilt: a point that swells and fades, with a faint cross of glare. */
const Pearl: React.FC<{ x: number; y: number; k: number; size?: number }> = ({ x, y, k, size = 70 }) => {
  if (k <= 0.01) return null;
  return (
    <div style={{ position: "absolute", left: x - size, top: y - size, width: size * 2, height: size * 2, opacity: k, mixBlendMode: "screen" }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,250,236,1) 0%, rgba(255,226,170,.55) 6%, rgba(255,200,130,.12) 26%, transparent 60%)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: size - 1, height: 2, background: "linear-gradient(90deg, transparent, rgba(255,240,210,.7), transparent)" }} />
      <div style={{ position: "absolute", top: size * 0.35, bottom: size * 0.35, left: size - 1, width: 2, background: "linear-gradient(180deg, transparent, rgba(255,240,210,.5), transparent)" }} />
    </div>
  );
};

// ------------------------------------------------------------------ the scenes

type Scene = React.FC<{ f: number; g: number; p: ReelProps }>;

/** The hero tableau: 4:5, the shape of a portrait post. */
const TW = 900, TH = 1125, TCX = W / 2, TCY = 1062;

// 0-1 · the calling. One unbroken pull back over 4 s: from a detail in the beam to the whole tableau, the light widening
// with it. The hook is set in the dark above at frame 0 (the cover); the answer condenses beneath it; then line 1.
const Calling: Scene = ({ g, p }) => {
  const hero = photoAt(p, HERO);
  const t = Math.min(1, g / 118);
  const e = settle(t);
  const s = Math.exp(lerp(Math.log(1.78), Math.log(1), e));
  const pool: Pool = { x: hero.fx - 0.03, y: hero.fy - 0.04, r: lerp(0.4, 0.6, e), core: lerp(0.14, 0.24, e), aspect: lerp(1.3, 1.2, e) };
  // the focal point travels from low on the golden section (where the detail sits under the hook) to its place in the tableau
  const bx = TCX - TW / 2 + hero.fx * TW, by = TCY - TH / 2 + hero.fy * TH;
  const fpx = lerp(W / 2, bx, e), fpy = lerp(1170, by, e);
  // the hook
  const open = pair(p.open[0], p.open[1]);
  const openS = Math.min(196, 950 / runsEm(open, -0.01));
  const subS = fitSize(p.openSub, ITALIC, 900, 124);
  const top = 150;
  const gone = ramp(g, 64, 82, soft);
  const l1 = pair(p.line1[0], p.line1[1]);
  const l1S = Math.min(178, 950 / runsEm(l1, -0.01));
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <Painting p={hero} cx={TCX} cy={TCY} w={TW} h={TH} s={s} dx={fpx - bx} dy={fpy - by} pool={pool} />
      <Shaft g={g} sx={-260} sy={-620} tx={fpx} ty={fpy} spread={lerp(13, 17, e)} k={0.95} seed={1} />
      <Lit runs={open} size={openS} top={top} track={lerp(0.006, -0.01, ramp(g, 0, 60, Easing.linear))} gone={gone} glow={0.4} />
      <Lit runs={[{ text: p.openSub, face: ITALIC }]} size={subS} top={top + openS * 1.0 + 4} track={lerp(0.012, 0, ramp(g, 0, 60, Easing.linear))} gone={gone} />
      <Lit runs={l1} size={l1S} top={top + 70} k={ramp(g, 75, 98, soft)} gone={ramp(g, 112, 120, soft)} track={-0.01} />
    </AbsoluteFill>
  );
};

// 2 · the next picture rises through the last: both in the frame at once for a breath, a double exposure in the dark,
// the light swinging across to find it.
const Layers: Scene = ({ f, g, p }) => {
  const hero = photoAt(p, HERO), next = photoAt(p, RISES);
  const out = ramp(f, 0, 42, soft);
  const inn = ramp(f, 2, 44, soft);
  const l2 = pair(p.line2[0], p.line2[1]);
  const l2S = Math.min(178, 950 / runsEm(l2, -0.01));
  const nfx = TCX - TW / 2 + next.fx * TW, nfy = TCY - TH / 2 + next.fy * TH;
  const toDark = ramp(f, 55, 61, Easing.in(Easing.quad));
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <Painting p={hero} cx={TCX} cy={TCY} w={TW} h={TH} s={lerp(1, 0.94, ramp(f, 0, 60, Easing.linear))} pool={{ x: hero.fx - 0.03, y: hero.fy - 0.05, r: 0.7 - out * 0.25, core: 0.3 }} opacity={1 - out} />
      <Painting p={next} cx={TCX} cy={TCY} w={TW} h={TH} s={lerp(1.16, 1.02, ramp(f, 0, 60, soft))} pool={{ x: next.fx + 0.02, y: next.fy - 0.06, r: lerp(0.4, 0.6, inn), core: 0.24 }} opacity={inn} blend={out < 0.98 ? "screen" : undefined} />
      <Shaft g={g} sx={lerp(-260, -120, inn)} sy={-620} tx={lerp(TCX - TW / 2 + hero.fx * TW, nfx, inn)} ty={lerp(TCY - TH / 2 + hero.fy * TH, nfy, inn)} spread={16} k={0.95} seed={1} />
      <Lit runs={l2} size={l2S} top={220} k={ramp(f, 6, 28, soft)} gone={ramp(f, 50, 60, soft)} track={-0.01} />
      <AbsoluteFill style={{ background: BIT, opacity: toDark }} />
    </AbsoluteFill>
  );
};

// 3 · the triptych: three arched panels, the centre one taller, dark until the light falls on each in turn (on the
// beats), its word beneath. Then all three, and the camera leans in.
const PANELS = [
  { cx: 190, w: 296, h: 600 },
  { cx: 540, w: 352, h: 744 },
  { cx: 890, w: 296, h: 600 },
];
const PANEL_BASE = 1366;
const Triptych: Scene = ({ f, g, p }) => {
  const idx = p.wordPhotos;
  const lean = 1 + 0.035 * ramp(f, 30, 75, Easing.linear);
  const wordS = Math.min(...PANELS.map((pn, i) => fitSize(p.words[i], ITALIC, pn.w + 24, 84)));
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <AbsoluteFill style={{ transform: `scale(${lean})`, transformOrigin: "50% 52%" }}>
        {PANELS.map((pn, i) => {
          const pic = photoAt(p, idx[i]);
          const at = i * 15;
          const lit = ramp(f, at, at + 11, soft);
          const top = PANEL_BASE - pn.h;
          const arch = `M ${pn.cx - pn.w / 2} ${PANEL_BASE} L ${pn.cx - pn.w / 2} ${top + pn.w / 2} A ${pn.w / 2} ${pn.w / 2} 0 0 1 ${pn.cx + pn.w / 2} ${top + pn.w / 2} L ${pn.cx + pn.w / 2} ${PANEL_BASE} Z`;
          const len = 2 * (pn.h - pn.w / 2) + Math.PI * pn.w / 2 + pn.w;
          return (
            <React.Fragment key={i}>
              {/* the light arrives from above: its pool slides down onto the panel as it brightens */}
              <Painting p={pic} cx={pn.cx} cy={top + pn.h / 2} w={pn.w} h={pn.h} s={1 + 0.04 * (1 - lit)} ox={0.5} oy={0.4}
                pool={{ x: 0.42, y: lerp(0.05, 0.42, lit), r: lerp(0.9, 1.5, lit), core: 0.35, aspect: 1.6, dir: 165, shade: 0.5 }} dim={0.1 + 0.9 * lit} radius={`${pn.w / 2}px ${pn.w / 2}px 2px 2px`} edge={0} weave={0.16} />
              <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
                <path d={arch} fill="none" stroke={`rgba(${GILT},${(0.15 + 0.55 * lit).toFixed(3)})`} strokeWidth={2} strokeDasharray={len} strokeDashoffset={len * (1 - ramp(f, at, at + 22, soft))} />
              </svg>
              <Lit runs={[{ text: p.words[i], face: ITALIC }]} size={wordS} top={PANEL_BASE + 40} cx={pn.cx} k={ramp(f, at + 4, at + 18, soft)} glow={0.3} />
              {/* the left of each panel reflects up a little gilt from the light: its sill */}
              <Gilt x={pn.cx - pn.w / 2 - 6} y={PANEL_BASE + 12} w={pn.w + 12} k={lit} a={0.4} />
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      <Shaft g={g} sx={-240} sy={-760} tx={lerp(190, 890, ramp(f, 0, 36, soft))} ty={PANEL_BASE - 420} spread={lerp(12, 22, ramp(f, 0, 40, soft))} k={0.75} haze={0.85} seed={2} />
    </AbsoluteFill>
  );
};

// 4 · the number, carved in light: a sheen crosses it the way light crosses stone, over a picture far back in the dark.
const Figure: Scene = ({ f, g, p }) => {
  const back = fillerAt(p, BEHIND_NUMBER);
  const v = p.counter.value;
  const numS = fitSize(v, LIGHTF, 820, 760);
  const m = metrics(LIGHTF);
  const capTop = 560;                                         // where the figures' tops sit
  const top = capTop - (m.base - m.cap) * numS;
  const base = top + m.base * numS;
  const unitS = fitSize(p.counter.unit, ITALIC, 760, 132);
  const labS = Math.min(44, 760 / (textWidth(p.counter.label.toUpperCase(), CAPS, 1, 0.3) + 0.3));
  const k = ramp(f, 0, 18, soft);
  const sheen = interpolate(f, [6, 50], [-30, 130], clamp);
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <Painting p={back} cx={W / 2} cy={H / 2 + 60} w={W * 1.1} h={H * 1.1} s={1.08 - 0.05 * ramp(f, 0, 60, Easing.linear)} pool={{ x: 0.5, y: 0.45, r: 0.62, core: 0.1 }} dim={0.42} blur={16} weave={0} edge={0} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 60% 40% at 50% 46%, rgba(${B},.15), rgba(${B},.75))` }} />
      <Shaft g={g} sx={-300} sy={-700} tx={560} ty={base - numS * 0.3} spread={14} k={0.8} seed={3} />
      <Ruled text={p.counter.label} y={capTop - 150} size={labS} k={ramp(f, 2, 20, soft)} />
      <Lit runs={[{ text: v, face: LIGHTF }]} size={numS} top={top} k={k} sheen={sheen} glow={0.5} />
      <Lit runs={[{ text: p.counter.unit, face: ITALIC }]} size={unitS} top={base + 40} k={ramp(f, 10, 28, soft)} />
    </AbsoluteFill>
  );
};

// the night watch · one picture in the dark, and a spot of light that finds its details on the beats, the way Rembrandt
// lit only what mattered: three stops, each named by a part of the stack ("Your logo", "license #", "town"), then on the
// fourth the whole picture comes up and the stack is set beneath it between gilt rules.
const stackParts = (s: string) => {
  const dots = s.split(/\s+·\s+/).map((x) => x.trim()).filter(Boolean);
  if (dots.length >= 2) return dots.slice(0, 3);
  const comma = s.split(/,\s+/).map((x) => x.trim()).filter(Boolean);
  return comma.length >= 2 ? comma.slice(0, 3) : [];
};
const NightWatch: Scene = ({ f, g, p }) => {
  const pic = photoAt(p, WATCHED);   // the work itself, examined: the light goes over it, detail by detail
  const parts = stackParts(p.stackLabel);
  const clampP = (v: number) => Math.min(0.82, Math.max(0.18, v));
  const stops = [
    { x: clampP(pic.fx - 0.2), y: clampP(pic.fy - 0.12) },
    { x: clampP(pic.fx + 0.2), y: clampP(pic.fy + 0.02) },
    { x: clampP(pic.fx - 0.04), y: clampP(pic.fy + 0.22) },
  ];
  // the spot travels between stops in the 8 frames before each beat and arrives on it
  const at = (k: number) => k * 30;
  let sx = stops[0].x, sy = stops[0].y;
  for (let k = 1; k < 3; k++) {
    const m = soft(ramp(f, at(k) - 8, at(k), Easing.linear));
    sx = lerp(sx, stops[k].x, m); sy = lerp(sy, stops[k].y, m);
  }
  const whole = ramp(f, 82, 92, soft);              // on the fourth stop (frame 90) the whole picture comes up
  sx = lerp(sx, pic.fx - 0.03, whole); sy = lerp(sy, pic.fy - 0.04, whole);
  const r = lerp(0.34, 0.66, whole), core = lerp(0.14, 0.26, whole);
  const z = 1.12 + 0.05 * (f / 120);
  const stepK = (k: number) => ramp(f, at(k), at(k) + 10, soft) * (1 - ramp(f, at(k + 1) - 4, at(k + 1) + 4, soft));
  const capY = TCY + TH / 2 + 46;
  const capS = Math.min(...(parts.length ? parts : [p.stackLabel]).map((t) => fitSize(t, ITALIC, 860, 110)));
  const stackS = Math.min(34, 860 / (textWidth(p.stackLabel.toUpperCase(), CAPS, 1, 0.24) + 0.24));
  const spot = { x: TCX - TW / 2 + sx * TW, y: TCY - TH / 2 + sy * TH };
  return (
    <AbsoluteFill style={{ background: BIT }}>
      {/* the whole picture, faint in the dark (the room's last light), and the spot that finds each detail over it */}
      <Painting p={pic} cx={TCX} cy={TCY} w={TW} h={TH} s={z} ox={0.5} oy={0.5} pool={{ x: 0.48, y: 0.45, r: 0.75, core: 0.3, shade: 0.5 }} dim={lerp(0.2, 0.5, whole)} weave={0.1} />
      <Painting p={pic} cx={TCX} cy={TCY} w={TW} h={TH} s={z} ox={0.5} oy={0.5} pool={{ x: sx, y: sy, r, core, aspect: 1.1, shade: 0.4 }} dim={lerp(0.95, 1, whole)} />
      <Shaft g={g} sx={-260} sy={-700} tx={spot.x} ty={spot.y} spread={lerp(9, 16, whole)} k={0.95} seed={7} />
      {parts.map((t, k) => (
        <Lit key={k} runs={[{ text: t, face: ITALIC }]} size={capS} top={capY} k={stepK(k)} glow={0.4} />
      ))}
      <Ruled text={p.stackLabel} y={capY + 30} size={stackS} k={ramp(f, 90, 104, soft)} reach={80} />
    </AbsoluteFill>
  );
};

// studies · a breath with no words: walking along a dark wall past three paintings, each lit as we come to it, the
// way a lamp carried through a gallery finds one picture after another. One constant lateral dolly.
const STUDY_W = 700, STUDY_H = 875, STUDY_GAP = 790, STUDY_Y = 960;
const Studies: Scene = ({ f, g, p }) => {
  const pics = STUDIES.map((k) => fillerAt(p, k));
  const cam = lerp(-STUDY_GAP, STUDY_GAP, Math.min(1, f / 60));          // the camera walks right at one speed: a painting each half bar
  return (
    <AbsoluteFill style={{ background: BIT }}>
      {pics.map((pic, i) => {
        const x = W / 2 + (i - 1) * STUDY_GAP - cam;
        const near = smooth(1 - Math.abs(x - W / 2) / 900);
        if (x < -STUDY_W || x > W + STUDY_W) return null;
        return (
          <React.Fragment key={i}>
            <Painting p={pic} cx={x} cy={STUDY_Y} w={STUDY_W} h={STUDY_H} s={1.02} pool={{ x: 0.46, y: 0.42, r: 0.5 + 0.4 * near, core: 0.22 + 0.22 * near, dir: 150, shade: 0.5 }} dim={0.35 + 0.65 * near} edge={0.05} />
            <div style={{ position: "absolute", left: x - STUDY_W / 2 - 16, top: STUDY_Y - STUDY_H / 2 - 16, width: STUDY_W + 32, height: STUDY_H + 32, border: `2px solid rgba(${GILT},${(0.12 + 0.6 * near).toFixed(3)})`, boxSizing: "border-box" }} />
          </React.Fragment>
        );
      })}
      {/* the lamp we carry: a warm pool at the centre of the wall, and the window's beam from up left */}
      <AbsoluteFill style={{ mixBlendMode: "screen", background: `radial-gradient(ellipse 520px 760px at ${W / 2}px ${STUDY_Y}px, ${rgba(LAMP, 0.08)}, transparent 70%)` }} />
      <Shaft g={g} sx={-260} sy={-760} tx={W / 2} ty={STUDY_Y} spread={16} k={0.8} seed={6} />
    </AbsoluteFill>
  );
};

// 5 · cross-cutting that quickens: six details, each in its own pool of light, held 12, 10, 8, 6, 5 then 4 frames;
// then black, and one ember (Event Caliber's own colour, the first time it appears): the held breath.
const CUTS = [0, 15, 30, 38, 45, 49, 53, 56, 60];   // on the grid: two beats, two eighths, then sixteenths
const Montage: Scene = ({ f, g, p }) => {
  const n = CUTS.findIndex((c, i) => f >= c && f < (CUTS[i + 1] ?? 999));
  const ember = ramp(f, 62, 72, soft);
  if (n < 0 || n >= CUTS.length - 1) {
    return (
      <AbsoluteFill style={{ background: BIT }}>
        <Ember x={W / 2} y={560} k={ember} g={g} tint={p.accent} />
      </AbsoluteFill>
    );
  }
  const pic = fillerAt(p, CUT_FILLERS[n]);
  const lf = f - CUTS[n], len = CUTS[n + 1] - CUTS[n];
  const jx = (random(`mx${n}`) - 0.5) * 0.24, jy = (random(`my${n}`) - 0.5) * 0.2;
  const z = 1.34 + 0.12 * random(`mz${n}`) + 0.06 * (lf / len);
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <Painting p={pic} cx={W / 2} cy={H / 2} w={W} h={H} s={z} ox={Math.min(0.85, Math.max(0.15, pic.fx + jx))} oy={Math.min(0.85, Math.max(0.15, pic.fy + jy))}
        pool={{ x: Math.min(0.8, Math.max(0.2, pic.fx + jx)), y: Math.min(0.8, Math.max(0.2, pic.fy + jy)), r: 0.62, core: 0.18 }} edge={0} />
      <Shaft g={g} sx={n % 2 ? 1300 : -220} sy={-640} tx={W / 2} ty={H * 0.55} spread={18} k={0.8} seed={10 + n} />
      {/* each cut lands with a breath of light */}
      <AbsoluteFill style={{ background: rgba(LAMP, 1), mixBlendMode: "screen", opacity: 0.18 * Math.max(0, 1 - lf / 3) }} />
    </AbsoluteFill>
  );
};

// 6 · the light. On the music's entrance the ember opens into a shaft from straight above (top light) and the chosen
// picture is seen at last, a photo of its own. Gilt draws round it; pearls of light
// catch the gilt; the marquee word, and the stack beneath it on a ruled line.
const PW = 760, PHt = 950, PCX = W / 2, PCY = 820;
const Light: Scene = ({ f, g, p }) => {
  // the climax's picture is seen in its own colours, the light alone on it (the approved Event Caliber reel, 2026-11-08)
  const piece = photoAt(p, CLIMAX);
  const open = ramp(f, 0, 16, Easing.out(Easing.cubic));
  const bloom = f < 3 ? f / 3 : Math.max(0, 1 - (f - 3) / 10);
  const push = 1 + 0.035 * ramp(f, 0, 90, Easing.linear);
  const frameK = ramp(f, 8, 30, soft);
  const top = PCY - PHt / 2, left = PCX - PW / 2;
  const marS = fitSize(p.marquee, ITALIC, 880, 196);
  const pearls = [[left - 14, top + 120, 26], [left + PW + 14, top + 300, 31], [PCX + 140, top - 14, 36], [left + 90, top + PHt + 14, 41]];
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <AbsoluteFill style={{ transform: `scale(${push})`, transformOrigin: `50% ${PCY / H * 100}%` }}>
        <Painting p={piece} cx={PCX} cy={PCY} w={PW} h={PHt} s={1.06 - 0.06 * open} ox={0.5} oy={0.5} pool={{ x: 0.5, y: lerp(0.22, 0.46, open), r: lerp(0.5, 1.05, open), core: lerp(0.12, 0.55, open), aspect: 1.25 }} grade={false} edge={0} weave={0.06} />
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <rect x={left - 14} y={top - 14} width={PW + 28} height={PHt + 28} fill="none" stroke={`rgba(${GILT},.75)`} strokeWidth={2} pathLength={1} strokeDasharray="1" strokeDashoffset={1 - frameK} />
          <rect x={left - 24} y={top - 24} width={PW + 48} height={PHt + 48} fill="none" stroke={`rgba(${GILT},.3)`} strokeWidth={1} pathLength={1} strokeDasharray="1" strokeDashoffset={1 - ramp(f, 14, 36, soft)} />
        </svg>
        {pearls.map(([x, y, at], i) => <Pearl key={i} x={x} y={y} k={Math.max(0, Math.sin(Math.PI * Math.min(1, Math.max(0, (f - at) / 16))))} size={60 + i * 8} />)}
      </AbsoluteFill>
      <Shaft g={g} sx={W / 2} sy={-1100} tx={W / 2} ty={PCY} spread={lerp(1.5, 22, open)} k={1} seed={4} />
      <Lit runs={[{ text: p.marquee, face: ITALIC }]} size={marS} top={PCY + PHt / 2 + 60} k={ramp(f, 12, 30, soft)} glow={0.5} />
      <Gilt x={W / 2 - 170} y={PCY + PHt / 2 + 96 + marS * 1.02} w={340} k={ramp(f, 22, 44, soft)} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 38% 60% at 50% 18%, ${rgba([255, 248, 232], 1)} 0%, ${rgba(LAMP, 0.55)} 40%, transparent 100%)`, mixBlendMode: "screen", opacity: bloom * 0.7 }} />
    </AbsoluteFill>
  );
};

// 7 · the invitation, in the last of the light from above: the name, a gilt rule drawing out, the kicker, the call in a
// gilt-edged panel tinted with Event Caliber's colour, the site and the town. All in by frame 26; then it holds.
const Invitation: Scene = ({ f, g, p }) => {
  const nameS = fitSize(p.business, ROMAN, 920, 176, -0.01);
  const mR = metrics(ROMAN);
  const nameTop = 690;
  const nameBase = nameTop + mR.base * nameS;
  const kickS = fitSize(p.kicker, ITALIC, 880, 68);
  const ctaS = 40, ctaTrack = 0.16;
  const ctaW = textWidth(p.cta.toUpperCase(), CAPS, ctaS, ctaTrack) + ctaTrack * ctaS + 132, ctaH = 112;
  const ctaY = nameBase + 60 + kickS * 1.2 + 64;
  const siteS = fitSize(p.phone, ROMAN, 860, 56);
  const siteY = ctaY + ctaH + 70;
  const mC = metrics(CAPS);
  const ctaTextTop = ctaY + ctaH / 2 - (mC.base - mC.cap / 2) * ctaS;
  const panelK = ramp(f, 10, 26, soft);
  return (
    <AbsoluteFill style={{ background: BIT }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 55% 34% at 50% 30%, ${rgba(LAMP, 0.1)}, transparent 70%)` }} />
      <Shaft g={g} sx={-260} sy={-820} tx={W / 2} ty={nameBase} spread={18} k={0.75} haze={1.1} seed={5} />
      <Lit runs={[{ text: p.business, face: ROMAN }]} size={nameS} top={nameTop} k={ramp(f, 0, 18, soft)} track={-0.01} glow={0.45} />
      <Gilt x={W / 2 - 200} y={nameBase + 40} w={400} k={ramp(f, 6, 24, soft)} />
      <Lit runs={[{ text: p.kicker, face: ITALIC }]} size={kickS} top={nameBase + 72} k={ramp(f, 8, 22, soft)} />
      <div style={{ position: "absolute", left: W / 2 - ctaW / 2, top: ctaY, width: ctaW, height: ctaH, opacity: panelK, transform: `scale(${0.96 + 0.04 * panelK})`,
        border: `2px solid rgba(${GILT},.85)`, background: `linear-gradient(180deg, ${p.accent}38, ${p.accent}1c)`, boxShadow: `0 0 50px ${p.accent}26, inset 0 0 30px rgba(${B},.5)` }} />
      <Lit runs={[{ text: p.cta, face: CAPS }]} size={ctaS} top={ctaTextTop} k={ramp(f, 12, 24, soft)} caps track={ctaTrack} glow={0.2} />
      <Lit runs={[{ text: p.phone, face: ROMAN }]} size={siteS} top={siteY} k={ramp(f, 14, 24, soft)} glow={0.2} />
      <Lit runs={[{ text: p.town, face: CAPS }]} size={28} top={siteY + siteS + 34} k={ramp(f, 16, 26, soft)} caps track={0.32} glow={0.1} opacity={0.75} />
    </AbsoluteFill>
  );
};

// the bars: 0-1 are one shot
const SCENES: { at: number; S: Scene }[] = [
  { at: 0, S: Calling }, { at: 120, S: Layers }, { at: 180, S: Triptych }, { at: 240, S: Figure },
  { at: 300, S: NightWatch }, { at: 420, S: Studies }, { at: 480, S: Montage }, { at: 570, S: Light }, { at: 660, S: Invitation },
];
/** Dissolves across a bar line: the outgoing scene, still moving, fades over the incoming one for this many frames. */
const DISSOLVE: Record<number, number> = { 240: 14, 300: 12, 420: 8, 660: 16 };

// ------------------------------------------------------------------ over everything

const Defs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {/* old varnished oil: some colour out, then tone curves per channel; highlights to lead white and gold,
          shadows to umber and bitumen, never grey */}
      <filter id="cs-grade" colorInterpolationFilters="sRGB" x="0%" y="0%" width="100%" height="100%">
        <feColorMatrix type="saturate" values="0.86" />
        <feComponentTransfer>
          <feFuncR type="table" tableValues="0.03 0.19 0.46 0.73 0.88 0.94" />
          <feFuncG type="table" tableValues="0.02 0.135 0.36 0.61 0.78 0.86" />
          <feFuncB type="table" tableValues="0.014 0.088 0.25 0.45 0.62 0.71" />
        </feComponentTransfer>
      </filter>
    </defs>
  </svg>
);

/** Film grain over everything: one of six tiles at a fresh offset each frame. */
const Grain: React.FC<{ g: number }> = ({ g }) => {
  const T = 512, tile = g % 6, ox = Math.floor(random(`cgx${g}`) * T), oy = Math.floor(random(`cgy${g}`) * T);
  const tiles = [];
  for (let r = 0; r < 5; r++) for (let c = 0; c < 4; c++) tiles.push(<Img key={`${r}${c}`} src={ASSET(`grain-${tile}.png`)} style={{ position: "absolute", left: c * T - ox, top: r * T - oy, width: T, height: T }} />);
  return <AbsoluteFill style={{ mixBlendMode: "overlay", opacity: 0.17, pointerEvents: "none" }}>{tiles}</AbsoluteFill>;
};

export const Chiaroscuro: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Chiaroscuro");
  const g = useCurrentFrame();
  useFontsReady();
  const i = SCENES.reduce((n, s, k) => (g >= s.at ? k : n), 0);
  const { at, S } = SCENES[i];
  const d = DISSOLVE[at] ?? 0;
  const prev = i > 0 && d > 0 && g < at + d ? SCENES[i - 1] : null;
  // the camera never quite still; the light breathing like a flame
  const wx = noise2D("cw-x", g * 0.05, 0) * 1.4, wy = noise2D("cw-y", 0, g * 0.05) * 1.2, wr = noise2D("cw-r", g * 0.04, 2) * 0.03;
  const flame = 0.03 + 0.03 * (0.5 + 0.5 * noise2D("flame", g * 0.22, 0));
  return (
    <AbsoluteFill style={{ background: BIT, overflow: "hidden" }}>
      <Music track={p.music} />
      <Defs />
      {/* the smoke and the weave are used as CSS images, which the render does not wait for: load them as <Img> first */}
      {["haze-0.png", "haze-1.png", "canvas.png"].map((f) => <Img key={f} src={ASSET(f)} style={{ position: "absolute", width: 2, height: 2, opacity: 0 }} />)}
      <AbsoluteFill style={{ transform: `translate(${wx}px, ${wy}px) rotate(${wr}deg) scale(1.006)` }}>
        <S f={g - at} g={g} p={p} />
        {prev && (
          <AbsoluteFill style={{ opacity: 1 - soft((g - at) / d) }}>
            <prev.S f={g - prev.at} g={g} p={p} />
          </AbsoluteFill>
        )}
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 80% 64% at 50% 46%, transparent 50%, rgba(10,7,5,.6) 100%)" }} />
      <AbsoluteFill style={{ background: `rgba(${B},${flame.toFixed(3)})` }} />
      <Grain g={g} />
    </AbsoluteFill>
  );
};
