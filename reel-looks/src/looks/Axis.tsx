import React from "react";
import { AbsoluteFill, Easing, Img, random, staticFile, useCurrentFrame } from "remotion";
import { H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, fillerAt, photoAt } from "../slots";
import { ARCHIVO } from "../fonts";
import { Face, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// AXIS: exactly right. One line runs through every frame, and everything sits on it.
// The craft of the masters, not their look:
//   one-point perspective, the vanishing point on the subject (Leonardo's room: every line leads to it); perfect
//   symmetry; the camera that never stops, never eases, moving at one relentless speed down the axis; stark title
//   cards cut in on the beat; colour as a signal in a black-and-white world, one thing in colour (Kubrick; Coppola's
//   Rumble Fish); pocket doors that part on the axis, each one an event; practical light panels passing overhead and
//   their reflections on a polished floor.
// Archivo at its widest (125 %), heavy caps for the cards and tracked caps for labels. Silver black-and-white photos:
// Axis and Chiaroscuro are the two looks that grade and light his photos (Chris, 2026-11-08: "Keep the photos from any
// color changes except for only the last two I mentioned"). Axis takes portraits only ("the gallery in the last one
// should remain all portraits"). Event Caliber's colour exists only as the axis line, until the last door opens on his
// picture in full colour.
//
// 25 s (750 frames; the other looks run 16 s) on the 120 BPM grid of 15-frame beats, the music locked to it:
//    0-2 s    the hook: a doorway on the axis holding the hero, the corridor converging on it, the words above
//    2-3 s    a card on the bar line (line 1); then back in the corridor, closer, and through the doorway into the picture
//    5-6 s    a card (line 2)
//    6-8 s    three words on three beats, each on its picture across a black band; the three as a list
//    8-10 s   the number, a monolith on the axis with a picture inside it
//   10-16 s   the gallery: the corridor in true perspective, pictures hung on both walls passing one a beat; then the
//             corridor ends at a lit wall carrying the stack, and the wall parts on the axis
//   16-19 s   doors on the beats: each parts on the axis and the next is behind it; the last stays shut and light grows
//             at its crack for a whole second: the held breath
//   19-22 s   the climax, on the music's hit: the last door is open, and the closing burst floods into colour from
//             the axis: one portrait a beat, the last held
//   22-25 s   the end card on the far wall of the room (everything in by frame 24, then holds 2.2 s)
// Music: the suite's Pixabay tracks for Axis, locked to the 120 BPM grid (music_tracks.grid), their hit on 19 s (frame 570).

export const AXIS_FRAMES = 750;

// ------------------------------------------------------------------ the world

const INK = "#0A0A0B";
const K = "10,10,11";
const SILVER = "#F3F2EE";
const ASSET = (f: string) => staticFile(`textures/axis/${f}`);
// Every portrait once, and never the same person twice (Chris, 2026-11-08, night: "there are duplicates! The women in
// red at the end you just used is also in the gallery on the left side!"). The post's eight portraits: the hero in the
// doorway (slot 0), the three under Poise, Light and Presence, the first and last doors, and the burst of two. The
// gallery's eleven walls and the two middle doors are fillers, more of his approved portraits.
export const SLOTS: Slots = { photos: 8, fillers: 13 };
const HERO = 0, FIRST_DOOR = 4, LAST_DOOR = 5, BURST_PHOTOS = [6, 7];
const GALLERY = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], MIDDLE_DOORS = [11, 12];      // filler slots

const HEAVY: Face = { family: ARCHIVO, weight: 800, stretch: "expanded" };
const BLACK: Face = { family: ARCHIVO, weight: 900, stretch: "expanded" };
const LABEL: Face = { family: ARCHIVO, weight: 600, stretch: "expanded" };
const PLAIN: Face = { family: ARCHIVO, weight: 500 };

const VPX = W / 2, VPY = H / 2;            // the vanishing point: the centre of the frame
const DW = 608, DH = 1080;                 // a doorway at scale 1: 9:16, so at FILL it is exactly the frame
const FILL = W / DW;                       // 1.776
const Q = 1.22;                            // the corridor's ribs: one every 1.22x in scale
const smooth = (t: number) => { const x = Math.max(0, Math.min(1, t)); return x * x * (3 - 2 * x); };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);

/** Ink or white on Event Caliber's colour, whichever reads. */
const onColour = (hex: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 150 ? INK : SILVER;
};

// ------------------------------------------------------------------ type

/** A line of caps, centred on cx, placed by its ink: inkTop is where the tops of the capitals sit. */
const Caps: React.FC<{ text: string; face: Face; size: number; inkTop: number; cx?: number; track?: number; color?: string; opacity?: number }> = ({ text, face, size, inkTop, cx = W / 2, track = 0, color = SILVER, opacity = 1 }) => {
  if (opacity <= 0.002) return null;
  const m = metrics(face);
  const top = inkTop - (m.base - m.cap) * size;
  return (
    <div style={{ position: "absolute", left: cx - 1200, width: 2400, top, textAlign: "center", whiteSpace: "nowrap", opacity }}>
      <span style={{ fontFamily: face.family, fontWeight: face.weight, fontStretch: face.stretch === "expanded" ? "125%" : "100%", fontSize: size, lineHeight: 1,
        letterSpacing: `${track}em`, paddingLeft: `${track}em`, textTransform: "uppercase", color, fontVariantNumeric: "lining-nums" }}>{text}</span>
    </div>
  );
};
const capH = (face: Face, size: number) => metrics(face).cap * size;
const fitCaps = (text: string, face: Face, width: number, max: number, track = 0) => fitSize(text.toUpperCase(), face, width, max, track);

/** The axis: a hairline in Event Caliber's colour on x = W/2, from y0 to y1, drawing from `from` (0 top, 1 bottom). */
const AxisLine: React.FC<{ y0: number; y1: number; k?: number; colour: string; from?: number; w?: number; glow?: number }> = ({ y0, y1, k = 1, colour, from = 0, w = 3, glow = 0.5 }) => {
  if (k <= 0.002 || y1 <= y0) return null;
  return (
    <div style={{ position: "absolute", left: VPX - w / 2, top: y0, width: w, height: y1 - y0, background: colour, transform: `scaleY(${k})`, transformOrigin: from ? "50% 100%" : "50% 0%",
      boxShadow: `0 0 ${w * 4}px ${colour}${Math.round(glow * 255).toString(16).padStart(2, "0")}` }} />
  );
};

// ------------------------------------------------------------------ the corridor

/** A plane on the axis at screen scale s: its rectangle. */
const rectAt = (s: number) => ({ x0: VPX - (DW / 2) * s, x1: VPX + (DW / 2) * s, y0: VPY - (DH / 2) * s, y1: VPY + (DH / 2) * s });

/** The corridor between the planes at screen scales `near` (towards the camera) and `far`: its ribs (door frames along
 *  the walls), the light panels on its ceiling and their reflections in the floor, and its four edges. `phase` slides the
 *  ribs so they flow outward as the camera moves. */
const Corridor: React.FC<{ far: number; near: number; phase: number; light?: number; ribs?: number; edges?: number }> = ({ far, near, phase, light = 1, ribs = 0.24, edges = 0.32 }) => {
  const top = Math.min(near, 2.4);
  const scales: number[] = [];
  // rib scales: far * Q^(m + phase), for every m that lands between far and near
  const m0 = Math.ceil(Math.log(far) / Math.log(Q) - phase - 1e-6);
  for (let m = m0; m < m0 + 40; m++) {
    const s = Math.pow(Q, m + phase);
    if (s <= far * 1.0001) continue;
    if (s >= top) break;
    scales.push(s);
  }
  const f = rectAt(far);
  const segs: React.ReactNode[] = [];
  const all = [far, ...scales, top];
  for (let i = 0; i < all.length - 1; i++) {
    const a = all[i], b = all[i + 1];
    if (i % 2 === 1 || b / a < 1.05) continue;
    // a light panel in the middle of every other bay, perspective-correct (interpolated in log scale)
    const u0 = Math.pow(b / a, 0.28) * a, u1 = Math.pow(b / a, 0.72) * a;
    const hw = 0.24 * (DW / 2);
    const fade = Math.min(1, (2.1 - u1) / 0.4);
    const ceil = `${VPX - hw * u0},${VPY - (DH / 2) * u0} ${VPX + hw * u0},${VPY - (DH / 2) * u0} ${VPX + hw * u1},${VPY - (DH / 2) * u1} ${VPX - hw * u1},${VPY - (DH / 2) * u1}`;
    const rw = hw * 0.55, v1 = Math.min(u1 * 1.18, 2.4);
    const floor = `${VPX - rw * u0},${VPY + (DH / 2) * u0} ${VPX + rw * u0},${VPY + (DH / 2) * u0} ${VPX + rw * v1},${VPY + (DH / 2) * v1} ${VPX - rw * v1},${VPY + (DH / 2) * v1}`;
    segs.push(<polygon key={`c${i}`} points={ceil} fill="#FFFFFF" opacity={0.85 * light * fade} filter="url(#ax-glow)" />);
    segs.push(<polygon key={`f${i}`} points={floor} fill="url(#ax-reflect)" opacity={0.5 * light * fade} filter="url(#ax-soft)" />);
  }
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      {/* the walls, ceiling and floor: the faintest gradient toward the far end, where the light gathers */}
      <polygon points={`0,0 ${W},0 ${f.x1},${f.y0} ${f.x0},${f.y0}`} fill="url(#ax-ceil)" />
      <polygon points={`0,${H} ${W},${H} ${f.x1},${f.y1} ${f.x0},${f.y1}`} fill="url(#ax-floor)" />
      <polygon points={`0,0 ${f.x0},${f.y0} ${f.x0},${f.y1} 0,${H}`} fill="url(#ax-wall-l)" />
      <polygon points={`${W},0 ${f.x1},${f.y0} ${f.x1},${f.y1} ${W},${H}`} fill="url(#ax-wall-r)" />
      {segs}
      {scales.map((s, i) => {
        const r = rectAt(s);
        const a = ribs * Math.min(1, (2.0 - s) / 0.35) * Math.min(1, (s / far - 1) / 0.1);
        return <rect key={i} x={r.x0} y={r.y0} width={r.x1 - r.x0} height={r.y1 - r.y0} fill="none" stroke="#FFFFFF" strokeOpacity={Math.max(0, a)} strokeWidth={1.6} />;
      })}
      <g stroke="#FFFFFF" strokeOpacity={edges} strokeWidth={1.6}>
        <line x1={0} y1={0} x2={f.x0} y2={f.y0} /><line x1={W} y1={0} x2={f.x1} y2={f.y0} />
        <line x1={0} y1={H} x2={f.x0} y2={f.y1} /><line x1={W} y1={H} x2={f.x1} y2={f.y1} />
      </g>
    </svg>
  );
};

/** The phase that makes the ribs flow at the camera's speed: log of the camera scale in units of Q. */
const phaseOf = (cam: number) => { const x = Math.log(cam) / Math.log(Q); return x - Math.floor(x); };

/** A doorway on the axis at screen scale s holding a picture, in silver (or colour), as two pocket doors that part on
 *  the axis (split 0 shut, 1 gone into the walls), framed by its jamb. */
const Door: React.FC<{ pic?: Photo; s: number; split?: number; colour?: boolean; slab?: boolean; crack?: number; accent?: string; jamb?: number }> = ({ pic, s, split = 0, colour = false, slab = false, crack = 0, accent = "#fff", jamb = 0.55 }) => {
  const r = rectAt(s);
  const w = r.x1 - r.x0, h = r.y1 - r.y0;
  const half = (side: 0 | 1) => {
    const shift = (side ? 1 : -1) * split * (w / 2);
    return (
      <div style={{ position: "absolute", left: side ? w / 2 : 0, top: 0, width: w / 2, height: h, overflow: "hidden", transform: `translateX(${shift}px)` }}>
        {slab ? (
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(${side ? 270 : 90}deg, #050506, #111114 70%, #1A1A1E)` }} />
        ) : pic ? (
          <Img src={staticFile(pic.src)} style={{ position: "absolute", left: side ? -w / 2 : 0, top: 0, width: w, height: h, objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`, filter: colour ? undefined : "url(#ax-silver)" }} />
        ) : null}
        {/* the door's edge on the axis catches the light from the panels as it opens */}
        <div style={{ position: "absolute", top: 0, bottom: 0, [side ? "left" : "right"]: 0, width: Math.max(2, 3 * s), background: `rgba(255,255,255,${(0.1 + 0.5 * Math.min(1, split * 6)).toFixed(3)})` } as React.CSSProperties} />
      </div>
    );
  };
  return (
    <>
      <div style={{ position: "absolute", left: r.x0, top: r.y0, width: w, height: h, overflow: "hidden" }}>
        {split < 0.999 && half(0)}
        {split < 0.999 && half(1)}
        {crack > 0 && (
          <>
            <div style={{ position: "absolute", left: w / 2 - 1.5 * s, top: 0, width: 3 * s, height: h, background: "#FFFFFF", opacity: Math.min(1, crack * 1.4) }} />
            <div style={{ position: "absolute", left: w / 2 - 120 * s, top: 0, width: 240 * s, height: h, opacity: crack, background: `linear-gradient(90deg, transparent, ${accent}55 42%, #FFFFFFcc 50%, ${accent}55 58%, transparent)` }} />
          </>
        )}
      </div>
      <div style={{ position: "absolute", left: r.x0 - 1, top: r.y0 - 1, width: w + 2, height: h + 2, border: `${Math.max(1.5, 2 * s)}px solid rgba(255,255,255,${jamb})`, boxSizing: "border-box" }} />
    </>
  );
};

/** A picture filling the frame in silver, pushed in at one constant speed. */
const Full: React.FC<{ pic: Photo; z: number; colour?: boolean }> = ({ pic, z, colour }) => (
  <AbsoluteFill style={{ transform: `scale(${z.toFixed(5)})`, transformOrigin: "50% 50%" }}>
    <Img src={staticFile(pic.src)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`, filter: colour ? undefined : "url(#ax-silver)" }} />
  </AbsoluteFill>
);

// ------------------------------------------------------------------ the scenes

type Scene = React.FC<{ f: number; g: number; p: ReelProps }>;

/** The camera of the opening: it reaches the doorway (FILL) at frame 130 and keeps going. */
const camOpen = (g: number) => Math.pow(FILL, g / 130);

/** The approach (bars 0-2, under the cards): the corridor converging on the hero's doorway, the camera relentless. */
const Approach: Scene = ({ g, p }) => {
  const hero = photoAt(p, HERO);
  const s = camOpen(g);
  const r = rectAt(s);
  const inside = s >= FILL;
  // the hook: set above the doorway, still while the room moves; gone before the first card
  const open = `${p.open[0]} ${p.open[1]}`;
  const oS = fitCaps(open, HEAVY, 960, 128, -0.01);
  const sS = fitCaps(p.openSub, LABEL, 880, 50, 0.16);
  const hookA = 1 - ramp(g, 50, 58, Easing.linear);
  const oTop = 168, sTop = oTop + capH(HEAVY, oS) + 52;
  return (
    <AbsoluteFill style={{ background: INK }}>
      {inside ? (
        <Full pic={hero} z={s / FILL} />
      ) : (
        <>
          <Corridor far={s} near={2.4} phase={phaseOf(s)} light={1 - 0.75 * hookA} />
          <Door pic={hero} s={s} />
          <AxisLine y0={r.y1 + 2} y1={H} colour={p.accent} />
        </>
      )}
      {hookA > 0 && (
        <>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: sTop + 150, opacity: hookA, background: `linear-gradient(180deg, rgba(${K},.92) 0%, rgba(${K},.85) 70%, rgba(${K},0) 100%)` }} />
          <Caps text={open} face={HEAVY} size={oS} inkTop={oTop} track={-0.01} opacity={hookA} />
          <Caps text={p.openSub} face={LABEL} size={sS} inkTop={sTop} track={0.16} opacity={hookA} color="#CFCDC6" />
          <AxisLine y0={0} y1={oTop - 44} colour={p.accent} />
        </>
      )}
    </AbsoluteFill>
  );
};

/** A title card: black, two lines of heavy caps on the axis, cut in on the beat and held. */
const Card: React.FC<{ lines: [string, string]; f: number; p: ReelProps }> = ({ lines, f, p }) => {
  const size = Math.min(fitCaps(lines[0], HEAVY, 940, 190, -0.01), fitCaps(lines[1], HEAVY, 940, 190, -0.01));
  const ch = capH(HEAVY, size), gap = size * 0.3;
  const top = VPY - (2 * ch + gap) / 2;
  const z = 1 + 0.03 * (f / 30);
  return (
    <AbsoluteFill style={{ background: INK }}>
      <AbsoluteFill style={{ transform: `scale(${z})` }}>
        <Caps text={lines[0]} face={HEAVY} size={size} inkTop={top} track={-0.01} />
        <Caps text={lines[1]} face={HEAVY} size={size} inkTop={top + ch + gap} track={-0.01} />
      </AbsoluteFill>
      <AxisLine y0={0} y1={top - 90} colour={p.accent} />
      <AxisLine y0={top + 2 * ch + gap + 90} y1={H} colour={p.accent} />
    </AbsoluteFill>
  );
};

/** 3 · three words on three beats, each across a black band on its picture; then the three as a list. */
const Words: Scene = ({ f, p }) => {
  const idx = p.wordPhotos;
  const i = Math.min(3, Math.floor(f / 15));
  if (i === 3) {
    const size = Math.min(...p.words.map((w) => fitCaps(w, HEAVY, 900, 132, -0.005)));
    const ch = capH(HEAVY, size), gap = size * 0.42;
    const top = VPY - (3 * ch + 2 * gap) / 2;
    return (
      <AbsoluteFill style={{ background: INK }}>
        {p.words.map((w, k) => <Caps key={k} text={w} face={HEAVY} size={size} inkTop={top + k * (ch + gap)} track={-0.005} />)}
        <AxisLine y0={0} y1={top - 90} colour={p.accent} />
        <AxisLine y0={top + 3 * ch + 2 * gap + 90} y1={H} colour={p.accent} />
      </AbsoluteFill>
    );
  }
  const pic = photoAt(p, idx[i]);
  const lf = f - i * 15;
  const size = fitCaps(p.words[i], HEAVY, 960, 210, -0.01);
  const ch = capH(HEAVY, size);
  const band = ch * 2.1;
  return (
    <AbsoluteFill style={{ background: INK }}>
      <Full pic={pic} z={1.06 + 0.004 * lf} />
      <div style={{ position: "absolute", left: 0, right: 0, top: VPY - band / 2, height: band, background: INK }} />
      <Caps text={p.words[i]} face={HEAVY} size={size} inkTop={VPY - ch / 2} track={-0.01} />
      <AxisLine y0={0} y1={VPY - band / 2} colour={p.accent} glow={0.3} />
      <AxisLine y0={VPY + band / 2} y1={H} colour={p.accent} glow={0.3} />
    </AbsoluteFill>
  );
};

/** 4 · the number: a monolith on the axis at the end of the corridor, a picture inside it, the camera still moving. */
const Monolith: Scene = ({ f, p }) => {
  const cam = 1 + 0.12 * (f / 60);
  const v = p.counter.value;
  const size = fitCaps(v, BLACK, 760, 1020, -0.02);
  const ch = capH(BLACK, size);
  const m = metrics(BLACK);
  const inkTop = VPY - ch / 2 - 30;
  const top = inkTop - (m.base - m.cap) * size;
  const numStyle: React.CSSProperties = { fontFamily: ARCHIVO, fontWeight: 900, fontStretch: "125%", fontSize: size, letterSpacing: "-0.02em", fontVariantNumeric: "lining-nums" };
  const labS = Math.min(40, 860 / (textWidth(p.counter.label.toUpperCase(), LABEL, 1, 0.3) + 0.3));
  const unitS = Math.min(48, 860 / (textWidth(p.counter.unit.toUpperCase(), LABEL, 1, 0.3) + 0.3));
  return (
    <AbsoluteFill style={{ background: INK }}>
      <Corridor far={0.8 * cam} near={2.4} phase={phaseOf(cam * 3)} light={0.3} ribs={0.16} edges={0.22} />
      <AbsoluteFill style={{ transform: `scale(${cam})`, transformOrigin: "50% 50%" }}>
        {/* the figure is a window: the picture (a real <Img>, so the render waits for it) clipped to the glyphs */}
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <clipPath id="ax-num"><text x={W / 2} y={top + m.base * size} textAnchor="middle" style={numStyle}>{v}</text></clipPath>
            <filter id="ax-num-shadow" x="-20%" y="-20%" width="140%" height="160%"><feGaussianBlur stdDeviation="28" /></filter>
          </defs>
          <text x={W / 2} y={top + m.base * size + 34} textAnchor="middle" style={numStyle} fill="#000" opacity={0.7} filter="url(#ax-num-shadow)">{v}</text>
        </svg>
        {/* Event Caliber (Chris, 2026-11-08: "There's a glitch in 10 at the 7-9 second mark"): a photo clipped to the
            narrow glyph read as broken pieces of a face, so the figure is solid silver, lit like the corridor */}
        <div style={{ position: "absolute", inset: 0, clipPath: "url(#ax-num)", background: `linear-gradient(180deg, #FFFFFF 0%, ${SILVER} 45%, #9E9C96 100%)` }} />
        <Caps text={p.counter.label} face={LABEL} size={labS} inkTop={inkTop - 120} track={0.3} color="#CFCDC6" />
        <Caps text={p.counter.unit} face={LABEL} size={unitS} inkTop={inkTop + ch + 90} track={0.3} />
      </AbsoluteFill>
      <AxisLine y0={0} y1={(inkTop - 120 - VPY) * cam + VPY - 70} colour={p.accent} />
      <AxisLine y0={(inkTop + ch + 90 + capH(LABEL, unitS) - VPY) * cam + VPY + 70} y1={H} colour={p.accent} />
    </AbsoluteFill>
  );
};

/** The stack on the gallery's far wall, a line per part: "Your logo · license # · town" as three lines, "3 posts a week,
 *  every week" as two, anything else as one. */
const stackLines = (s: string) => {
  const dots = s.split(/\s+·\s+/).map((x) => x.trim()).filter(Boolean);
  if (dots.length >= 2) return dots.slice(0, 3);
  const comma = s.split(/,\s+/).map((x) => x.trim()).filter(Boolean);
  return comma.length === 2 ? comma : [s];
};

/** the gallery · the corridor in true perspective (CSS 3D): pictures hung on both walls, one passing the camera on each
 *  beat, left and right in turn; door frames along the walls, light panels overhead and their reflections in the floor.
 *  The camera moves at one constant speed. No words. */
const P3 = 1000;                 // perspective distance, px
const V3 = 60;                   // the camera's speed, px a frame: a picture a beat
const PANEL_L = 820, PANEL_H = 1160, BEAT_Z = V3 * 15;
const WALL_Z = -12 * BEAT_Z;      // the corridor's far wall: the camera reaches it on frame 180, the end of the scene
const Gallery: Scene = ({ f, p }) => {
  const camZ = f * V3;
  const pics = GALLERY.map((k) => fillerAt(p, k));
  const depthA = (zRel: number) => Math.max(0, Math.min(1, (7200 + zRel) / 2600));     // atmospheric: far things fade into the dark
  const els: React.ReactNode[] = [];
  // the door frames along the corridor, every half beat
  for (let k = 0; k < 24; k++) {
    const z = -k * (BEAT_Z / 2), zr = z + camZ;
    if (zr > -20 || zr < -7400) continue;
    els.push(<div key={`r${k}`} style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translate3d(${-W / 2}px, ${-H / 2}px, ${z}px)`,
      border: "2px solid rgba(255,255,255,.2)", boxSizing: "border-box", opacity: depthA(zr) }} />);
  }
  // light panels on the ceiling and their reflections in the floor, one a beat
  for (let k = 0; k < 12; k++) {
    const zNear = -k * BEAT_Z - 200, zr = zNear + camZ;
    if (zr > 0 || zr < -7400) continue;
    els.push(<div key={`l${k}`} style={{ position: "absolute", left: 0, top: 0, width: 300, height: 480, transformOrigin: "0 0", transform: `translate3d(-150px, ${-H / 2}px, ${zNear}px) rotateX(-90deg)`,
      background: "#FFFFFF", boxShadow: "0 0 70px 24px rgba(255,255,255,.35)", opacity: 0.9 * depthA(zr) }} />);
    els.push(<div key={`m${k}`} style={{ position: "absolute", left: 0, top: 0, width: 300, height: 480, transformOrigin: "0 0", transform: `translate3d(-150px, ${H / 2}px, ${zNear - 480}px) rotateX(90deg)`,
      background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,.22))", filter: "blur(10px)", opacity: depthA(zr) }} />);
  }
  // the pictures: left, right, left... each passes the camera on a beat
  pics.forEach((pic, k) => {
    const zNear = -(BEAT_Z + k * BEAT_Z), zr = zNear + camZ;
    if (zNear - PANEL_L < WALL_Z) return;
    if (zr > P3 - 120 || zr < -7600) return;
    const left = k % 2 === 0;
    const t = left
      ? `translate3d(${-W / 2}px, ${-PANEL_H / 2}px, ${zNear}px) rotateY(90deg)`
      : `translate3d(${W / 2}px, ${-PANEL_H / 2}px, ${zNear - PANEL_L}px) rotateY(-90deg)`;
    els.push(
      <div key={`p${k}`} style={{ position: "absolute", left: 0, top: 0, width: PANEL_L, height: PANEL_H, transformOrigin: "0 0", transform: t, opacity: depthA(zr - PANEL_L / 2), outline: "3px solid rgba(255,255,255,.75)", outlineOffset: 10 }}>
        <Img src={staticFile(pic.src)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`, filter: "url(#ax-silver)", display: "block" }} />
      </div>,
    );
  });
  // the far wall: lit, the stack set on it in heavy caps on the axis; it parts on the axis as the camera arrives
  const wallZr = WALL_Z + camZ;
  if (wallZr < 0 && wallZr > -11000) {
    const lines = stackLines(p.stackLabel);
    const size = Math.min(...lines.map((l) => fitCaps(l, HEAVY, 900, 150, -0.01)));
    const ch = capH(HEAVY, size), gap = size * 0.36;
    const top0 = H / 2 - (lines.length * ch + (lines.length - 1) * gap) / 2;
    const part = smooth(ramp(f, 166, 180, Easing.linear));
    const half = (side: 0 | 1) => (
      <div key={`w${side}`} style={{ position: "absolute", left: side ? W / 2 : 0, top: 0, width: W / 2, height: H, overflow: "hidden", transform: `translateX(${(side ? 1 : -1) * part * (W / 2)}px)` }}>
        <div style={{ position: "absolute", left: side ? -W / 2 : 0, top: 0, width: W, height: H, background: "radial-gradient(ellipse 70% 50% at 50% 50%, #26262B, #121214)" }}>
          {lines.map((l, i) => <Caps key={i} text={l} face={HEAVY} size={size} inkTop={top0 + i * (ch + gap)} track={-0.01} />)}
          <AxisLine y0={0} y1={top0 - 120} colour={p.accent} />
          <AxisLine y0={top0 + lines.length * ch + (lines.length - 1) * gap + 120} y1={H} colour={p.accent} />
        </div>
      </div>
    );
    els.push(
      <div key="wall" style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translate3d(${-W / 2}px, ${-H / 2}px, ${WALL_Z}px)`, opacity: depthA(wallZr) }}>
        {half(0)}{half(1)}
      </div>,
    );
  }
  return (
    <AbsoluteFill style={{ background: INK }}>
      {/* the corridor's four edges run to the vanishing point */}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs><radialGradient id="ax-edge" cx="50%" cy="50%" r="60%"><stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset="1" stopColor="#fff" stopOpacity=".35" /></radialGradient></defs>
        <g stroke="url(#ax-edge)" strokeWidth={1.6}><line x1={0} y1={0} x2={VPX} y2={VPY} /><line x1={W} y1={0} x2={VPX} y2={VPY} /><line x1={0} y1={H} x2={VPX} y2={VPY} /><line x1={W} y1={H} x2={VPX} y2={VPY} /></g>
      </svg>
      <AbsoluteFill style={{ perspective: `${P3}px`, perspectiveOrigin: "50% 50%" }}>
        <div style={{ position: "absolute", left: W / 2, top: H / 2, width: 0, height: 0, transformStyle: "preserve-3d", transform: `translateZ(${camZ}px)` }}>
          {els}
        </div>
      </AbsoluteFill>
      <AxisLine y0={VPY + 40} y1={H} colour={p.accent} />
      <AxisLine y0={0} y1={VPY - 40} colour={p.accent} glow={0.2} w={2} />
    </AbsoluteFill>
  );
};

/** 5 · the doors, one on each beat: each parts on the axis to show the next behind it. The last is a black slab that
 *  will not open; light leaks along its crack, brighter and brighter: the held breath. */
const R = FILL;                       // one door per beat: as one fills the frame, the next has reached scale 1
const Doors: Scene = ({ f, g, p }) => {
  const order = [photoAt(p, FIRST_DOOR), ...MIDDLE_DOORS.map((k) => fillerAt(p, k)), photoAt(p, LAST_DOOR)];
  const SLAB = 4;
  const cam = Math.pow(R, f / 15);    // door k sits at scale cam / R^k
  const sc = (k: number) => cam / Math.pow(R, k);
  const doors = [0, 1, 2, 3, 4];
  const splitOf = (k: number) => (k === SLAB ? 0 : smooth((sc(k) - 1.12) / 0.5));
  // back to front: the slab, then each door with the corridor in front of it
  const visible = doors.filter((k) => sc(k) < 2.6 && sc(k) > 0.05 && splitOf(k) < 0.999);
  const nearestShut = visible.length ? Math.min(...visible.map((k) => k)) : SLAB;
  const crack = f >= 60 ? ramp(f, 60, 89, Easing.in(Easing.quad)) : 0;
  const nodes: React.ReactNode[] = [];
  for (let k = SLAB; k >= 0; k--) {
    const s = sc(k);
    if ((k !== SLAB && s > 2.6) || splitOf(k) >= 0.999) continue;
    const behind = k < SLAB ? sc(k + 1) : 0.0;
    if (k === SLAB) nodes.push(<Door key="slab" s={Math.min(s, FILL * 1.002)} slab crack={0.25 + 0.75 * crack} accent={p.accent} jamb={0.4} />);
    else nodes.push(<React.Fragment key={`d${k}`}><Corridor far={behind > 0 ? Math.max(behind, 0.05) : 0.05} near={s} phase={phaseOf(cam)} light={0.9} /><Door pic={order[k]} s={s} split={splitOf(k)} /></React.Fragment>);
  }
  const front = sc(nearestShut);
  return (
    <AbsoluteFill style={{ background: INK }}>
      {nodes}
      {front < FILL && <Corridor far={front} near={2.4} phase={phaseOf(cam)} light={0.9} />}
      {front < FILL && <AxisLine y0={rectAt(front).y1 + 2} y1={H} colour={p.accent} />}
    </AbsoluteFill>
  );
};

/** 6 · the climax, on the hit: the last door has opened; the burst floods into colour outward from the axis; the marquee
 *  word above it, the axis line running on below it. */
const PW_POST = 720, PH_POST = 900, PCY = 1000;
// Event Caliber (Chris, 2026-11-08): "three portraits that should be the ending of 10 as a quick, but not to quick burst
// with a hold on the last image"; he chose two: one picture a beat, the last held.
const BURST = 15;
const Colour: Scene = ({ f, p }) => {
  const k = Math.min(BURST_PHOTOS.length - 1, Math.floor(f / BURST));
  const piece = photoAt(p, BURST_PHOTOS[k]);
  // a burst picture taken wide gets a wide window (3:2), as the approved burst had; one taken upright the 4:5 window, so
  // a portrait's face is never cut by the crop
  const wide = !(piece.w && piece.h && piece.h > piece.w);
  const PW = wide ? 960 : PW_POST, PHh = wide ? 640 : PH_POST;
  const z = 1 + 0.06 * (f / 90);
  const flood = expoOut(Math.min(1, Math.max(0, (f - 2) / 14)));
  const flash = Math.max(0, 1 - f / 5);
  const mS = fitCaps(p.marquee, HEAVY, 940, 150, -0.01);
  const top = PCY - PHh / 2, bot = PCY + PHh / 2;
  const mTop = top - 90 - capH(HEAVY, mS);
  return (
    <AbsoluteFill style={{ background: INK }}>
      <AbsoluteFill style={{ transform: `scale(${z})`, transformOrigin: `50% ${PCY / H * 100}%` }}>
        <div style={{ position: "absolute", left: VPX - PW / 2, top, width: PW, height: PHh, overflow: "hidden" }}>
          <Img src={staticFile(piece.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: `${piece.fx * 100}% ${piece.fy * 100}%`, filter: "url(#ax-silver)" }} />
          <Img src={staticFile(piece.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: `${piece.fx * 100}% ${piece.fy * 100}%`,
            clipPath: `inset(0 ${(50 - 50 * flood).toFixed(3)}% 0 ${(50 - 50 * flood).toFixed(3)}%)` }} />
          {flood < 0.999 && <div style={{ position: "absolute", top: 0, bottom: 0, left: `${50 - 50 * flood}%`, width: 3, marginLeft: -1.5, background: p.accent, boxShadow: `0 0 20px ${p.accent}` }} />}
          {flood < 0.999 && <div style={{ position: "absolute", top: 0, bottom: 0, left: `${50 + 50 * flood}%`, width: 3, marginLeft: -1.5, background: p.accent, boxShadow: `0 0 20px ${p.accent}` }} />}
        </div>
        <div style={{ position: "absolute", left: VPX - PW / 2 - 16, top: top - 16, width: PW + 32, height: PHh + 32, border: "2px solid rgba(255,255,255,.7)", boxSizing: "border-box" }} />
        <Caps text={p.marquee} face={HEAVY} size={mS} inkTop={mTop} track={-0.01} opacity={ramp(f, 4, 10, Easing.linear)} />

        <AxisLine y0={0} y1={mTop - 70} colour={p.accent} />
        <AxisLine y0={bot + 60} y1={H} colour={p.accent} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#FFFFFF", opacity: flash * 0.85 }} />
    </AbsoluteFill>
  );
};

/** 7 · the end card, on the far wall of the room: the name, the kicker, the call on a bar of Event Caliber's colour (the
 *  only block of colour in the reel), the site, the town. */
const End: Scene = ({ f, p }) => {
  const nS = fitCaps(p.business, HEAVY, 900, 118, -0.01);
  const kS = Math.min(30, 880 / (textWidth(p.kicker.toUpperCase(), LABEL, 1, 0.24) + 0.24));
  const cS = 36, cTrack = 0.18;
  const cW = textWidth(p.cta.toUpperCase(), LABEL, cS, cTrack) + cTrack * cS + 120, cH = 104;
  const sS = fitSize(p.phone, PLAIN, 820, 46);
  const tS = 24;
  const nTop = 700, kTop = nTop + capH(HEAVY, nS) + 50, cY = kTop + capH(LABEL, kS) + 84;
  const sTop = cY + cH + 74, tTop = sTop + metrics(PLAIN).cap * sS + 40;
  const a = (from: number) => ramp(f, from, from + 8, Easing.linear);
  const z = 1 + 0.03 * (f / 90);
  const wall = 1.32;
  return (
    <AbsoluteFill style={{ background: INK }}>
      <AbsoluteFill style={{ transform: `scale(${z})` }}>
        <Corridor far={wall} near={2.4} phase={phaseOf(z * 2)} light={0.55} ribs={0.12} edges={0.18} />
        <Caps text={p.business} face={HEAVY} size={nS} inkTop={nTop} track={-0.01} opacity={a(0)} />
        <Caps text={p.kicker} face={LABEL} size={kS} inkTop={kTop} track={0.24} color="#CFCDC6" opacity={a(4)} />
        <div style={{ position: "absolute", left: VPX - cW / 2, top: cY, width: cW, height: cH, background: p.accent, opacity: a(8), transform: `scaleX(${0.6 + 0.4 * expoOut(ramp(f, 8, 20, Easing.linear))})` }} />
        <Caps text={p.cta} face={LABEL} size={cS} inkTop={cY + cH / 2 - capH(LABEL, cS) / 2} track={cTrack} color={onColour(p.accent)} opacity={a(10)} />
        <div style={{ position: "absolute", left: 0, right: 0, top: sTop - (metrics(PLAIN).base - metrics(PLAIN).cap) * sS, textAlign: "center", fontFamily: ARCHIVO, fontWeight: 500, fontSize: sS, lineHeight: 1, color: SILVER, opacity: a(12) }}>{p.phone}</div>
        <Caps text={p.town} face={LABEL} size={tS} inkTop={tTop} track={0.4} color="#A9A79F" opacity={a(14)} />
      </AbsoluteFill>
      <AxisLine y0={0} y1={(nTop - 90 - VPY) * z + VPY} colour={p.accent} k={ramp(f, 0, 12, expoOut)} />
      <AxisLine y0={(tTop + tS + 90 - VPY) * z + VPY} y1={H} colour={p.accent} k={ramp(f, 0, 12, expoOut)} from={1} />
    </AbsoluteFill>
  );
};

// the timeline: the approach runs under the two cards (time does not stop while a card is up)
const TIMELINE: { at: number; end: number; S: Scene }[] = [
  { at: 0, end: 60, S: Approach },
  { at: 60, end: 90, S: ({ f, p }) => <Card lines={p.line1} f={f} p={p} /> },
  { at: 90, end: 150, S: Approach },
  { at: 150, end: 180, S: ({ f, p }) => <Card lines={p.line2} f={f} p={p} /> },
  { at: 180, end: 240, S: Words },
  { at: 240, end: 300, S: Monolith },
  { at: 300, end: 480, S: Gallery },
  { at: 480, end: 570, S: Doors },
  { at: 570, end: 660, S: Colour },
  { at: 660, end: 750, S: End },
];

// ------------------------------------------------------------------ over everything

const Defs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {/* silver: luminance only, then a print curve with deep blacks and clean whites, the shadows a breath cool */}
      <filter id="ax-silver" colorInterpolationFilters="sRGB" x="0%" y="0%" width="100%" height="100%">
        <feColorMatrix type="matrix" values="0.28 0.6 0.12 0 0  0.28 0.6 0.12 0 0  0.28 0.6 0.12 0 0  0 0 0 1 0" />
        <feComponentTransfer>
          <feFuncR type="table" tableValues="0.012 0.07 0.25 0.55 0.82 0.95 0.98" />
          <feFuncG type="table" tableValues="0.014 0.074 0.255 0.552 0.82 0.948 0.975" />
          <feFuncB type="table" tableValues="0.02 0.085 0.265 0.556 0.815 0.94 0.965" />
        </feComponentTransfer>
      </filter>
      <filter id="ax-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <filter id="ax-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5 16" /></filter>
      <linearGradient id="ax-reflect" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFFFFF" stopOpacity="0.32" /><stop offset="1" stopColor="#FFFFFF" stopOpacity="0" /></linearGradient>
      <linearGradient id="ax-ceil" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#1B1B1F" /><stop offset="1" stopColor="#0C0C0E" /></linearGradient>
      <linearGradient id="ax-floor" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stopColor="#141417" /><stop offset="1" stopColor="#09090A" /></linearGradient>
      <linearGradient id="ax-wall-l" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#121215" /><stop offset="1" stopColor="#0B0B0D" /></linearGradient>
      <linearGradient id="ax-wall-r" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stopColor="#121215" /><stop offset="1" stopColor="#0B0B0D" /></linearGradient>
    </defs>
  </svg>
);

/** Fine silver grain: one of six tiles at a fresh offset each frame. */
const Grain: React.FC<{ g: number }> = ({ g }) => {
  const T = 512, tile = g % 6, ox = Math.floor(random(`agx${g}`) * T), oy = Math.floor(random(`agy${g}`) * T);
  const tiles = [];
  for (let r = 0; r < 5; r++) for (let c = 0; c < 4; c++) tiles.push(<Img key={`${r}${c}`} src={ASSET(`grain-${tile}.png`)} style={{ position: "absolute", left: c * T - ox, top: r * T - oy, width: T, height: T }} />);
  return <AbsoluteFill style={{ mixBlendMode: "overlay", opacity: 0.13, pointerEvents: "none" }}>{tiles}</AbsoluteFill>;
};

export const Axis: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Axis");
  const g = useCurrentFrame();
  useFontsReady();
  const seg = TIMELINE.find((s) => g >= s.at && g < s.end) ?? TIMELINE[TIMELINE.length - 1];
  const S = seg.S;
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden" }}>
      <Music track={p.music} />
      <Defs />
      <S f={g - seg.at} g={g} p={p} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 85% 70% at 50% 50%, transparent 60%, rgba(${K},.45) 100%)` }} />
      <Grain g={g} />
    </AbsoluteFill>
  );
};
