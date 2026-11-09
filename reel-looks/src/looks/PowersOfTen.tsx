import React from "react";
import { AbsoluteFill, Easing, Img, random, spring, staticFile, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { FPS, H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, everyPicture, fillerAt, photoAt, shapeOf } from "../slots";
import { MONO, SANS } from "../fonts";
import { Face, emWidth, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";
import { CX, CY, END, M, Mosaic, STRIP, STRIP_UP, TAU_END, TOP_STRIP, tau, world } from "./powersOfTenLayout";

// POWERS OF TEN: seen from further and further away; one photo reaches a whole region.
// The craft of the masters, not their look (Charles and Ray Eames, Powers of Ten, 1977):
//   the whole film is one unbroken shot over one continuous world, no cut for 16 s; the camera pulls back at a constant
//   exponential rate (the log of the scale linear in time), so each view holds the last one at its centre and you
//   always see where you came from; a readout strip at the edge of the frame (their dashboard) gives the power and the
//   distance in plain mono type, ticking continuously; matter-of-fact type, no flourish.
// Made for Event Caliber (event and conference photography, DC · MD · VA), whose pictures are the heroes: the world is a
// single plane of his photos laid edge to edge with small dark gaps, the hero at the centre and rings of photos around
// it, each ring larger than the last (so as the camera pulls back there is always a ring of his pictures at a size worth
// seeing); the whole mosaic sits at the heart of a night map of the region, so as the camera keeps pulling back the
// mosaic becomes a small bright patch and then one light among the town lights. Every photo is whole, at its own shape,
// exactly as shot; nothing is drawn over or around one (the three words sit in dark caption bands beside their photos,
// the hook and lines in a dark title strip at the top, the rest on the map). No photo ever comes toward the viewer.
// Inter Tight for words (heavy heads, regular tails), JetBrains Mono for the readout. Black ground, Event Caliber's colour
// for the call, its second colour for the readout's index.
//
// 16 s, 480 frames: one move, at one constant exponential rate after a half-second ease off the hero, settling at the
// end. The wall is built just big enough to fill the frame until about 10.5 s at that rate; the readout runs at its own
// constant rate from 10^0 to 10^5 m.
//    0-2.3 s    the hero fills the width, the hook in the title strip above (the cover); its word in the band beneath
//    2.3-7 s    the wall opens ring by ring: line 1, line 2; the other two words in their bands as their photos come by,
//               each held at least 1.5 s beside its own photo (Chris, 2026-11-08: no word is ever left off; the mosaic,
//               the move and the words' windows are in powersOfTenLayout.ts, checked by tests/test_reel_looks.py)
//    7-9.4 s    the stack label in the title strip
//    9.4-12 s   the number (label, figure, unit) in the title strip, the wall still filling the frame
//   12-14 s     the strip lifts; the wall, still half the frame wide, draws into the night map, the bright town at its
//               heart; the region's name and the marquee above it
//   14-16 s     the end card below the town (in by frame 440), the move settling; the readout at rest at 100 km

// ------------------------------------------------------------------ the world

const GROUND = "#0A0A0B";
const NIGHT = "#0A1226";               // the map's ground: night over the land
const WATER = "#04080F";               // the bay and the river: no lights, darker than the land
const WHITE = "#F4F5F7";
const DIM = "#9EA4AF";

const HEAVY: Face = { family: SANS, weight: 850 };
const BLACK: Face = { family: SANS, weight: 900 };
const REG: Face = { family: SANS, weight: 400 };
const MED: Face = { family: SANS, weight: 650 };
const MONOF: Face = { family: MONO, weight: 500 };

const smooth = (t: number) => { const x = Math.max(0, Math.min(1, t)); return x * x * (3 - 2 * x); };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);


// ------------------------------------------------------------------ the camera: one move (the mosaic and the move are
// built in powersOfTenLayout.ts, where they can be checked without a browser)

const FINAL_POWER = 5;                             // the readout at rest: 10^5 m, the region
const MAPK = 1.3;                                  // the region map's plane, a little larger than the frame at the end

// ------------------------------------------------------------------ type

type Run = { text: string; face: Face };
const runsEm = (runs: Run[], track = 0) => runs.reduce((s, r) => s + emWidth(r.text, r.face, track), 0);
const capOf = (face: Face, size: number) => metrics(face).cap * size;

/** A line of runs placed by its ink: capTop is where the tops of the capitals sit; x its left edge, or its centre. */
const Type: React.FC<{ runs: Run[]; size: number; capTop: number; x?: number; centre?: boolean; color?: string; track?: number; opacity?: number; caps?: boolean }> = ({ runs, size, capTop, x = M, centre, color = WHITE, track = 0, opacity = 1, caps }) => {
  if (opacity <= 0.002) return null;
  const m = metrics(runs[0].face);
  const top = capTop - (m.base - m.cap) * size;
  return (
    <div style={{ position: "absolute", top, left: centre ? x - 1600 : x, width: centre ? 3200 : undefined, textAlign: centre ? "center" : "left", whiteSpace: "nowrap", opacity,
      fontSize: size, lineHeight: 1, letterSpacing: `${track}em`, color, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums tabular-nums" }}>
      {runs.map((r, i) => <span key={i} style={{ fontFamily: r.face.family, fontWeight: r.face.weight }}>{r.text}</span>)}
    </div>
  );
};

/** "10" with its power raised, in the readout's mono. */
const Pow: React.FC<{ e: string; size: number; color?: string }> = ({ e, size, color = WHITE }) => (
  <span style={{ fontFamily: MONO, fontSize: size, color, whiteSpace: "nowrap" }}>
    10<span style={{ fontSize: size * 0.62, position: "relative", top: -size * 0.42, marginLeft: size * 0.04 }}>{e}</span>
  </span>
);
const signed = (v: number, dp: number) => `${v < -0.5 * Math.pow(10, -dp) ? "−" : ""}${Math.abs(v).toFixed(dp)}`;

/** The view's width in plain units, three figures, ticking. */
const distance = (z: number) => {
  const d = Math.pow(10, z);
  if (d < 0.9995) return `${(d * 100).toPrecision(3)} cm`;
  if (d < 999.5) return `${d.toPrecision(3)} m`;
  return `${(d / 1000).toPrecision(3)} km`;
};


// ------------------------------------------------------------------ the night map (drawn once, from seeded randomness)

type Light = { x: number; y: number; r: number; a: number; c: string };
type MapData = { lights: Light[]; roads: [number, number][][]; river: [number, number][]; bay: [number, number][] };
let MAP: MapData | null = null;

const inPoly = (x: number, y: number, poly: [number, number][]) => {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
const distToLine = (x: number, y: number, line: [number, number][]) => {
  let best = 1e9;
  for (let i = 0; i < line.length - 1; i++) {
    const [ax, ay] = line[i], [bx, by] = line[i + 1];
    const dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)));
    best = Math.min(best, Math.hypot(x - ax - t * dx, y - ay - t * dy));
  }
  return best;
};

/** The region at 100 km, in plane pixels (one plane = the frame at scale 1): our town at the centre, a bay to the east,
 *  a river, other towns joined by roads, and lights strung along the roads and clustered on street grids in the towns. */
const mapData = (): MapData => {
  if (MAP) return MAP;
  const R = (k: string) => random(`pot-${k}`);
  // the bay: the east side, its shore wandering
  const bay: [number, number][] = [[W + 40, -40]];
  for (let i = 0; i <= 24; i++) {
    const y = -40 + (i / 24) * (H + 80);
    const x = 830 + 150 * Math.sin(i * 0.55 + 0.6) + 60 * noise2D("pot-shore", i * 0.4, 0) + (y > 1300 ? (y - 1300) * 0.25 : 0);
    bay.push([x, y]);
  }
  bay.push([W + 40, H + 40]);
  // the river: from the west edge down to the bay, meandering below the town
  const river: [number, number][] = [];
  for (let i = 0; i <= 30; i++) {
    const t = i / 30;
    river.push([-20 + t * 900, 1440 - t * 260 + 70 * Math.sin(t * 9) + 30 * noise2D("pot-river", t * 6, 1)]);
  }
  const wet = (x: number, y: number) => inPoly(x, y, bay) || distToLine(x, y, river) < 9;
  // towns: ours at the centre, the rest scattered on dry land
  const towns: { x: number; y: number; size: number }[] = [{ x: W / 2, y: H / 2, size: 1 }];
  for (let i = 0; towns.length < 13 && i < 400; i++) {
    const x = 40 + R(`tx${i}`) * 860, y = 60 + R(`ty${i}`) * (H - 120);
    if (wet(x, y) || towns.some((t) => Math.hypot(t.x - x, t.y - y) < 210)) continue;
    towns.push({ x, y, size: 0.18 + 0.62 * Math.pow(R(`ts${i}`), 1.6) });
  }
  // roads: every town to its two nearest, and the bigger ones to ours; gently wandering
  const roads: [number, number][][] = [];
  const seen = new Set<string>();
  towns.forEach((a, ai) => {
    const near = towns.map((b, bi) => ({ bi, d: Math.hypot(a.x - b.x, a.y - b.y) })).filter((n) => n.bi !== ai).sort((u, v) => u.d - v.d).slice(0, 2).map((n) => n.bi);
    if (ai > 0 && a.size > 0.4) near.push(0);
    near.forEach((bi) => {
      const key = ai < bi ? `${ai}-${bi}` : `${bi}-${ai}`;
      if (seen.has(key)) return;
      seen.add(key);
      const b = towns[bi], line: [number, number][] = [];
      const nx = -(b.y - a.y), ny = b.x - a.x, nl = Math.hypot(nx, ny) || 1;
      for (let s = 0; s <= 12; s++) {
        const t = s / 12, bend = Math.sin(t * Math.PI) * 26 * noise2D(`pot-road${key}`, t * 2.5, 0);
        line.push([a.x + (b.x - a.x) * t + (nx / nl) * bend, a.y + (b.y - a.y) * t + (ny / nl) * bend]);
      }
      roads.push(line);
    });
  });
  const lights: Light[] = [];
  const tint = (k: string) => { const v = R(k); return v < 0.72 ? "#FFD9A3" : v < 0.93 ? "#FFF3E0" : "#C9DBFF"; };
  // strung along the roads
  roads.forEach((line, ri) => {
    for (let i = 0; i < line.length - 1; i++) {
      const [ax, ay] = line[i], [bx, by] = line[i + 1];
      const n = Math.ceil(Math.hypot(bx - ax, by - ay) / 7);
      for (let j = 0; j < n; j++) {
        const t = j / n, k = `r${ri}-${i}-${j}`;
        const x = ax + (bx - ax) * t + (R(`${k}x`) - 0.5) * 6, y = ay + (by - ay) * t + (R(`${k}y`) - 0.5) * 6;
        if (R(`${k}s`) < 0.35 || wet(x, y)) continue;
        lights.push({ x, y, r: 0.7 + 0.5 * R(`${k}r`), a: 0.45 + 0.4 * R(`${k}a`), c: tint(`${k}c`) });
      }
    }
  });
  // the towns: street grids, dense at the core, thinning out; ours the biggest, so that seen close it is a town
  towns.forEach((t, ti) => {
    const ours = ti === 0;
    const n = Math.round(90 + 1000 * t.size * t.size + (ours ? 2600 : 0));
    const sigma = 22 + 95 * t.size;
    const grid = ours ? 13 : 6 + 4 * R(`g${ti}`), rot = R(`gr${ti}`) * 0.6;
    for (let i = 0; i < n; i++) {
      const k = `t${ti}-${i}`;
      const rr = sigma * Math.sqrt(-2 * Math.log(Math.max(1e-6, R(`${k}u`)))), th = 2 * Math.PI * R(`${k}v`);
      let dx = rr * Math.cos(th), dy = rr * Math.sin(th);
      // lights fall on the street grid most of the time: straight rows of them read as streets when close
      if (R(`${k}g`) < (ours ? 0.88 : 0.7)) {
        const c = Math.cos(rot), s = Math.sin(rot);
        let u = dx * c + dy * s, v = -dx * s + dy * c;
        if (R(`${k}h`) < 0.5) u = Math.round(u / grid) * grid; else v = Math.round(v / grid) * grid;
        dx = u * c - v * s; dy = u * s + v * c;
      }
      const x = t.x + dx, y = t.y + dy;
      if (wet(x, y)) continue;
      const core = Math.exp(-(rr * rr) / (2 * sigma * sigma * 0.35));
      lights.push({ x, y, r: (ours ? 0.6 : 0.75) + 1.1 * R(`${k}r`) * (0.5 + 0.5 * core), a: 0.5 + 0.45 * core * R(`${k}a`) + 0.1, c: tint(`${k}c`) });
    }
  });
  // the countryside: a sprinkle
  for (let i = 0; i < 520; i++) {
    const x = R(`cx${i}`) * W, y = R(`cy${i}`) * H;
    if (wet(x, y)) continue;
    lights.push({ x, y, r: 0.6 + 0.35 * R(`cr${i}`), a: 0.25 + 0.3 * R(`ca${i}`), c: "#FFE2B8" });
  }
  MAP = { lights, roads, river, bay };
  return MAP;
};

/** Lights near the mosaic: neighbourhoods on their own street grids, as many to each tenfold of distance as to the next
 *  (so at every height of the camera the town round the mosaic shows about as many lights), and a few roads passing by
 *  with lights strung along them. In world units, centred on the hero. */
const NEAR = new Map<string, Light[]>();
const nearField = (r0: number, r1: number) => {
  const key = `${Math.round(r0)}|${Math.round(r1)}`;
  const hit = NEAR.get(key);
  if (hit) return hit;
  const R = (k: string) => random(`potn-${k}`);
  const L = Math.log(r1 / r0);
  const tint = (k: string) => { const v = R(k); return v < 0.72 ? "#FFD9A3" : v < 0.93 ? "#FFF3E0" : "#C9DBFF"; };
  const out: Light[] = [];
  for (let c = 0; c < 150; c++) {
    const rc = r0 * Math.exp((0.08 + 0.92 * R(`cu${c}`)) * L), th = R(`ct${c}`) * Math.PI * 2;
    const cx = rc * Math.cos(th), cy = rc * Math.sin(th), sigma = rc * (0.12 + 0.12 * R(`cs${c}`));
    const grid = sigma / (3 + 3 * R(`cg${c}`)), rot = R(`cr${c}`) * Math.PI;
    for (let i = 0; i < 22; i++) {
      const k = `${c}-${i}`;
      const rr = sigma * Math.sqrt(-2 * Math.log(Math.max(1e-6, R(`u${k}`)))), a = R(`v${k}`) * Math.PI * 2;
      let u = rr * Math.cos(a), v = rr * Math.sin(a);
      if (R(`g${k}`) < 0.65) { if (R(`h${k}`) < 0.5) u = Math.round(u / grid) * grid; else v = Math.round(v / grid) * grid; }
      const x = cx + u * Math.cos(rot) - v * Math.sin(rot), y = cy + u * Math.sin(rot) + v * Math.cos(rot);
      out.push({ x, y, r: 0.7 + 0.8 * R(`r${k}`), a: 0.4 + 0.5 * R(`o${k}`), c: tint(`c${k}`) });
    }
  }
  // roads passing by the centre at every scale: lights spaced in proportion to their distance from it
  for (let j = 0; j < 7; j++) {
    const miss = r0 * Math.exp(R(`rm${j}`) * L * 0.5), dir = R(`rd${j}`) * Math.PI, nx = Math.cos(dir), ny = Math.sin(dir);
    for (let n = 0; n < 90; n++) {
      const d = (n % 2 ? 1 : -1) * miss * Math.exp((n / 90) * L * 1.1), bend = 0.04 * d * noise2D(`potn-road${j}`, n * 0.05, 0);
      out.push({ x: -ny * miss + nx * d + -ny * bend, y: nx * miss + ny * d + nx * bend, r: 0.7 + 0.5 * R(`rr${j}-${n}`), a: 0.45 + 0.35 * R(`ra${j}-${n}`), c: tint(`rc${j}-${n}`) });
    }
  }
  NEAR.set(key, out);
  return out;
};

/** The night: the region's map (water, roads, towns) scaled so that at the end of the move it fills the frame with our
 *  town at its heart, and the lights round the mosaic at every scale between. World to screen at scale s. */
const Night: React.FC<{ s: number; sEnd: number; mosaic: Mosaic }> = ({ s, sEnd, mosaic }) => {
  const d = mapData();
  const k = (MAPK / sEnd) * s;                        // region plane pixels to screen
  const X = (u: number) => CX + (u - W / 2) * k, Y = (v: number) => CY + (v - H / 2) * k;
  const pts = (line: [number, number][]) => line.map(([u, v]) => `${X(u).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const mw = mosaic.x1 - mosaic.x0, mh = mosaic.y1 - mosaic.y0;
  const near = nearField(0.5 * Math.min(mw, mh), (130 * MAPK) / sEnd);
  const inMosaic = (wx: number, wy: number) => wx > mosaic.x0 && wx < mosaic.x1 && wy > mosaic.y0 && wy < mosaic.y1;
  const on = (x: number, y: number) => x > -6 && x < W + 6 && y > -6 && y < H + 6;
  const dots: React.ReactNode[] = [];
  near.forEach((l, i) => {
    if (inMosaic(l.x, l.y)) return;
    const x = CX + l.x * s, y = CY + l.y * s;
    if (on(x, y)) dots.push(<circle key={`n${i}`} cx={x} cy={y} r={l.r * 1.25} fill={l.c} opacity={l.a} />);
  });
  const grow = Math.max(0.5, Math.min(1, Math.sqrt(k)));
  d.lights.forEach((l, i) => {
    const x = X(l.x), y = Y(l.y);
    if (on(x, y) && !inMosaic((x - CX) / s, (y - CY) / s)) dots.push(<circle key={`m${i}`} cx={x} cy={y} r={l.r * grow} fill={l.c} opacity={l.a} />);
  });
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <rect width={W} height={H} fill={NIGHT} />
      <polygon points={pts(d.bay)} fill={WATER} stroke="rgba(150,180,230,.22)" strokeWidth={1.2} />
      <polyline points={pts(d.river)} fill="none" stroke={WATER} strokeWidth={Math.max(2, 9 * k)} strokeLinecap="round" />
      <g fill="none" stroke="rgba(255,214,160,.16)" strokeWidth={1}>{d.roads.map((r, i) => <polyline key={i} points={pts(r)} />)}</g>
      <g filter="url(#pot-glow)">{dots}</g>
    </svg>
  );
};

// ------------------------------------------------------------------ the mosaic on screen

/** The plane of photos at scale s about the hero: a dark ground under it (its gaps and caption bands), and every photo
 *  whole and exactly as shot. Once it is no bigger than a few lights it becomes one. */
const MosaicView: React.FC<{ mosaic: Mosaic; s: number; p: ReelProps }> = ({ mosaic, s, p }) => {
  // each cell's picture through its slot (photoAt, fillerAt), so the card check sees where each one is drawn
  const own = p.photos.length;
  const slotOf = new Map<string, () => Photo>(everyPicture(p).map((x, n): [string, () => Photo] =>
    [x.src, () => (n < own ? photoAt(p, n) : fillerAt(p, n - own))]));
  const bw = (mosaic.x1 - mosaic.x0) * s;
  const op = smooth((bw - 5) / 14);
  const light = smooth((26 - bw) / 16);
  const sx = (x: number) => CX + x * s, sy = (y: number) => CY + y * s;
  return (
    <>
      {op > 0.002 && (
        <div style={{ position: "absolute", inset: 0, opacity: op }}>
          <div style={{ position: "absolute", left: sx(mosaic.x0), top: sy(mosaic.y0), width: bw, height: (mosaic.y1 - mosaic.y0) * s, background: GROUND }} />
          {mosaic.cells.map((c, i) => {
            const x = sx(c.x), y = sy(c.y), w = c.w * s, h = c.h * s;
            if (w < 1.5 || x > W || y > H || x + w < 0 || y + h < 0) return null;
            return (
              <div key={i} style={{ position: "absolute", left: x, top: y, width: w, height: h, overflow: "hidden" }}>
                <Img src={staticFile(slotOf.get(c.src)!().src)} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
              </div>
            );
          })}
        </div>
      )}
      {light > 0.002 && (
        <div style={{ position: "absolute", left: CX - 40, top: CY - 40, width: 80, height: 80, opacity: light }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: 40, background: "radial-gradient(circle, rgba(255,236,200,.9) 0%, rgba(255,214,160,.35) 14%, rgba(255,200,140,0) 50%)" }} />
          <div style={{ position: "absolute", left: 36, top: 36, width: 8, height: 8, borderRadius: 4, background: "#FFF6E6" }} />
        </div>
      )}
    </>
  );
};

// ------------------------------------------------------------------ the dashboard

/** The readout strip at the bottom edge: the power and the distance, ticking, and a log ruler from 10^0 to 10^5 with
 *  an index riding on it. */
const RULER = { x0: 640, x1: 1012, lo: 0, hi: 5 };
const Readout: React.FC<{ power: number; p: ReelProps }> = ({ power, p }) => {
  const top = H - STRIP;
  const X = (v: number) => RULER.x0 + ((v - RULER.lo) / (RULER.hi - RULER.lo)) * (RULER.x1 - RULER.x0);
  const ticks: React.ReactNode[] = [];
  for (let e = RULER.lo; e <= RULER.hi; e++) {
    ticks.push(<line key={`M${e}`} x1={X(e)} y1={58} x2={X(e)} y2={82} />);
    if (e < RULER.hi) for (let n = 2; n <= 9; n++) { const x = X(e + Math.log10(n)); ticks.push(<line key={`m${e}${n}`} x1={x} y1={70} x2={x} y2={82} />); }
  }
  const ix = X(Math.max(RULER.lo, Math.min(RULER.hi, power)));
  return (
    <div style={{ position: "absolute", left: 0, top, width: W, height: STRIP, background: GROUND, borderTop: "1.5px solid rgba(255,255,255,.3)" }}>
      <div style={{ position: "absolute", left: M, top: 50, lineHeight: 1 }}><Pow e={signed(power, 2)} size={46} /></div>
      <div style={{ position: "absolute", left: 330, top: 50, lineHeight: 1, fontFamily: MONO, fontSize: 46, color: WHITE, whiteSpace: "nowrap" }}>{distance(power)}</div>
      <svg width={W} height={STRIP} style={{ position: "absolute", left: 0, top: 0 }}>
        <line x1={RULER.x0} y1={82} x2={RULER.x1} y2={82} stroke="rgba(255,255,255,.7)" strokeWidth={1.5} />
        <g stroke="rgba(255,255,255,.7)" strokeWidth={1.5}>{ticks}</g>
        {Array.from({ length: RULER.hi - RULER.lo + 1 }, (_, i) => RULER.lo + i).map((e) => (
          <text key={e} x={X(e)} y={112} textAnchor="middle" fill="rgba(255,255,255,.6)" style={{ fontFamily: MONO, fontSize: 20 }}>{signed(e, 0)}</text>
        ))}
        <line x1={ix} y1={44} x2={ix} y2={86} stroke={p.accent2} strokeWidth={3} />
        <polygon points={`${ix - 9},${34} ${ix + 9},${34} ${ix},${46}`} fill={p.accent2} />
      </svg>
    </div>
  );
};

// ------------------------------------------------------------------ the words

/** Words that hold: they rise into place once, hold, and fade before they go. */
const held = (g: number, at: number, until: number) => ({ k: expoOut(ramp(g, at, at + 10, Easing.linear)), gone: ramp(g, until - 7, until, Easing.in(Easing.quad)) });

/** The title strip at the top, a solid panel over the mosaic's edge while the mosaic fills the frame: the hook (there at
 *  frame 0, the cover), line 1, line 2, then the stack label and the number (label, figure, unit); then it lifts away. */
const TitleStrip: React.FC<{ g: number; p: ReelProps }> = ({ g, p }) => {
  if (g > STRIP_UP + 12) return null;
  const up = Easing.in(Easing.cubic)(ramp(g, STRIP_UP, STRIP_UP + 12, Easing.linear)) * TOP_STRIP;
  const open: Run[] = [{ text: p.open[0], face: HEAVY }, { text: ` ${p.open[1]}`, face: HEAVY }];
  const oS = Math.min(136, (W - 2 * M) / runsEm(open, -0.02));
  const sS = fitSize(p.openSub, REG, W - 2 * M, 60);
  const hookTop = 92, hookGone = ramp(g, 60, 67, Easing.in(Easing.quad));
  const fade = (at: number, until: number) => { const { k, gone } = held(g, at, until); return { op: Math.min(1, k * 1.6) * (1 - gone), dy: (1 - k) * 20 }; };
  const line = (pair: [string, string], at: number, until: number) => {
    if (g < at || g > until) return null;
    const runs: Run[] = [{ text: pair[0], face: HEAVY }, { text: ` ${pair[1]}`, face: REG }];
    const size = Math.min(112, (W - 2 * M) / runsEm(runs, -0.01));
    const { op, dy } = fade(at, until);
    return <Type runs={runs} size={size} capTop={TOP_STRIP / 2 - capOf(HEAVY, size) / 2 + 10 + dy} track={-0.01} opacity={op} />;
  };
  const stack = () => {
    if (g < 214 || g > 280) return null;
    const text = `[ ${p.stackLabel} ]`;
    const size = Math.min(44, (W - 2 * M) / emWidth(text.toUpperCase(), MONOF, 0.12));
    const { op, dy } = fade(214, 280);
    return <Type runs={[{ text, face: MONOF }]} size={size} capTop={TOP_STRIP / 2 - capOf(MONOF, size) / 2 + 10 + dy} track={0.12} caps opacity={op} />;
  };
  const counter = () => {
    if (g < 284 || g > STRIP_UP) return null;
    const { op, dy } = fade(284, STRIP_UP);
    const labS = Math.min(30, (W - 2 * M) / emWidth(p.counter.label.toUpperCase(), MONOF, 0.16));
    const valS = Math.min(170 / metrics(BLACK).cap, 520 / emWidth(p.counter.value, BLACK, -0.03));
    const valW = textWidth(p.counter.value, BLACK, valS, -0.03);
    const unitS = Math.min(64, (W - 2 * M - valW - 40) / emWidth(p.counter.unit, REG));
    const labTop = 62, valTop = labTop + capOf(MONOF, labS) + 38, base = valTop + capOf(BLACK, valS);
    return (
      <div style={{ position: "absolute", inset: 0, opacity: op, transform: `translateY(${dy.toFixed(1)}px)` }}>
        <div style={{ position: "absolute", left: M, top: labTop + capOf(MONOF, labS) / 2 - 9, width: 18, height: 18, borderRadius: 9, background: p.accent }} />
        <Type runs={[{ text: p.counter.label, face: MONOF }]} size={labS} capTop={labTop} x={M + 34} track={0.16} caps color="#E9ECF2" />
        <Type runs={[{ text: p.counter.value, face: BLACK }]} size={valS} capTop={valTop} track={-0.03} />
        <Type runs={[{ text: p.counter.unit, face: REG }]} size={unitS} capTop={base - capOf(REG, unitS)} x={M + valW + 36} color="#D5D8DE" />
      </div>
    );
  };
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateY(${-up.toFixed(1)}px)` }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: TOP_STRIP, background: GROUND, borderBottom: "1.5px solid rgba(255,255,255,.3)" }} />
      {hookGone < 1 && (
        <>
          <Type runs={open} size={oS} capTop={hookTop} track={-0.02} opacity={1 - hookGone} />
          <Type runs={[{ text: p.openSub, face: REG }]} size={sS} capTop={hookTop + capOf(HEAVY, oS) + 34} color="#D5D8DE" opacity={1 - hookGone} />
        </>
      )}
      {line(p.line1, 70, 138)}
      {line(p.line2, 142, 210)}
      {stack()}
      {counter()}
    </div>
  );
};

/** The three words, each in the dark band beside its own photo, while that photo is close enough to read: from the
 *  word's window (powersOfTenLayout.wordWindows, at least WORD_HOLD frames each). Never on a picture. */
const WordBands: React.FC<{ g: number; p: ReelProps; mosaic: Mosaic; scaleAt: (g: number) => number; windows: [number, number][] }> = ({ g, p, mosaic, scaleAt, windows }) => (
  <>
    {mosaic.cells.filter((c) => c.band && c.word !== undefined).map((c, n) => {
      const [a, b] = windows[c.word!] ?? [0, -1];
      if (b < a || g < a || g > b) return null;
      const s = scaleAt(g), bh = c.band!.h * s, top = CY + c.band!.y * s;
      const x0 = Math.max(M, CX + c.x * s + 28), x1 = Math.min(W - M, CX + (c.x + c.w) * s - 28);
      const word = p.words[c.word!];
      const size = Math.min(76 / metrics(HEAVY).cap, (0.52 * bh) / metrics(HEAVY).cap, (x1 - x0) / emWidth(word, HEAVY, -0.01));
      const k = (a === 0 ? 1 : ramp(g, a, a + 8, Easing.linear)) * (1 - ramp(g, b - 6, b, Easing.linear));
      return <Type key={n} runs={[{ text: word, face: HEAVY }]} size={size} capTop={top + bh / 2 - capOf(HEAVY, size) / 2} x={x0} track={-0.01} opacity={k} />;
    })}
  </>
);

/** Over the map, above the mosaic (the bright town at the centre): the region's name and the marquee. */
const Marquee: React.FC<{ g: number; p: ReelProps; topAt: (f: number) => number }> = ({ g, p, topAt }) => {
  if (g < 376 || g > 426) return null;
  const size = Math.min(210, (W - 2 * M) / emWidth(p.marquee, BLACK, -0.03));
  const townS = Math.min(34, (W - 2 * M) / emWidth(p.town.toUpperCase(), MONOF, 0.42));
  const { k, gone } = held(g, 376, 425);
  const op = Math.min(1, k * 1.6) * (1 - gone);
  const bottom = Math.min(topAt(376), topAt(425)) - 60;            // clear of the mosaic all the while
  const capTop = Math.max(250, bottom - capOf(BLACK, size));
  return (
    <div style={{ position: "absolute", inset: 0, opacity: op, filter: "drop-shadow(0 0 14px rgba(5,8,16,.95))" }}>
      <Type runs={[{ text: p.town, face: MONOF }]} size={townS} capTop={capTop - 90 + (1 - k) * 20} x={CX + (townS * 0.42) / 2} centre track={0.42} caps color="#E9ECF2" />
      <Type runs={[{ text: p.marquee, face: BLACK }]} size={size} capTop={capTop + (1 - k) * 26} x={CX} centre track={-0.03} />
    </div>
  );
};

/** The end card over the map, below the mosaic: name, what they do, the call in a pill of Event Caliber's colour, the
 *  site, the town. In by frame 440; then still as the move settles. */
const EndCard: React.FC<{ g: number; p: ReelProps; bottomAt: (f: number) => number }> = ({ g, p, bottomAt }) => {
  if (g < 426) return null;
  const nameS = Math.min(112, fitSize(p.business, HEAVY, W - 2 * M, 112, -0.02));
  const kickS = fitSize(p.kicker, REG, W - 2 * M, 50);
  const ctaS = fitSize(p.cta, MED, W - 2 * M - 110, 46), ctaW = textWidth(p.cta, MED, ctaS) + 110, ctaH = 100;
  const siteS = fitSize(p.phone, MONOF, 600, 42);
  const townS = Math.min(26, 360 / emWidth(p.town.toUpperCase(), MONOF, 0.3));
  const nameTop = Math.max(1180, bottomAt(426) + 70), kickTop = nameTop + capOf(HEAVY, nameS) + 36;
  const ctaY = kickTop + capOf(REG, kickS) + 40;
  const siteTop = ctaY + ctaH + 42;
  const a = (from: number) => ramp(g, from, from + 8, Easing.linear);
  const rise = (from: number) => (1 - expoOut(ramp(g, from, from + 10, Easing.linear))) * 16;
  const pop = spring({ frame: g - 430, fps: FPS, config: { damping: 15, stiffness: 200, mass: 0.6 } });
  const mC = metrics(MED);
  return (
    <>
      <div style={{ position: "absolute", left: 0, top: nameTop - 80, width: W, height: H - STRIP - (nameTop - 80), opacity: a(426), background: "linear-gradient(180deg, rgba(10,18,38,0) 0%, rgba(8,12,24,.75) 24%, rgba(8,12,24,.85) 100%)" }} />
      <Type runs={[{ text: p.business, face: HEAVY }]} size={nameS} capTop={nameTop + rise(426)} x={CX} centre track={-0.02} opacity={a(426)} />
      <Type runs={[{ text: p.kicker, face: REG }]} size={kickS} capTop={kickTop + rise(428)} x={CX} centre color="#C9CCD3" opacity={a(428)} />
      <div style={{ position: "absolute", left: CX - ctaW / 2, top: ctaY, width: ctaW, height: ctaH, borderRadius: ctaH / 2, background: p.accent, transform: `scale(${(0.7 + 0.3 * pop).toFixed(4)})`, opacity: Math.min(1, pop * 2) }} />
      <div style={{ position: "absolute", left: CX - ctaW / 2, width: ctaW, top: ctaY + ctaH / 2 - (mC.base - mC.cap / 2) * ctaS, textAlign: "center", fontFamily: SANS, fontWeight: 650, fontSize: ctaS, lineHeight: 1, color: GROUND, opacity: a(431), whiteSpace: "nowrap" }}>{p.cta}</div>
      <Type runs={[{ text: p.phone, face: MONOF }]} size={siteS} capTop={siteTop} x={CX} centre opacity={a(432)} />
      <Type runs={[{ text: p.town, face: MONOF }]} size={townS} capTop={siteTop + capOf(MONOF, siteS) + 30} x={CX + (townS * 0.3) / 2} centre color={DIM} track={0.3} opacity={a(433)} caps />
    </>
  );
};

// ------------------------------------------------------------------ the shot

const Defs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      <filter id="pot-glow" x="-10%" y="-10%" width="120%" height="120%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3.2" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>
  </svg>
);

// The post's six photos nearest the hero, and the mosaic's outer rings in up to forty fillers, more of his approved
// photos: each picture once on the one plane (Chris, 2026-11-08, night: no picture twice in a reel). The suite gives the
// mosaic only the fillers it places for these shapes (reel-looks/mosaic-fillers.mjs); one left off stops the render.
export const SLOTS: Slots = { photos: 6, fillers: 40, fillersFrom: 8 };

const WORLDS = new Map<string, ReturnType<typeof world>>();
export const PowersOfTen: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "PowersOfTen");
  const g = useCurrentFrame();
  useFontsReady();
  // every picture's shape from its props (shapeOf), so the first pass lays out the mosaic the suite counted its fillers on
  const key = [...everyPicture(p).map((x) => `${x.src}:${shapeOf(x).toFixed(4)}`), p.wordPhotos.join(",")].join("|");
  // the mosaic and the one move over it (powersOfTenLayout.world): it ends as the bright town at the heart of the map
  const built = WORLDS.get(key) ?? world(p, shapeOf);
  WORLDS.set(key, built);
  const { mosaic, scaleAt, windows } = built;
  const placed = new Set(mosaic.cells.map((c) => c.src));
  const left = everyPicture(p).filter((pic) => !placed.has(pic.src)).map((pic) => pic.src);
  if (left.length) throw new Error(`the mosaic leaves off ${left.join(", ")}: a photo taken and never shown`);
  const s = scaleAt(g), sEnd = scaleAt(END);
  const power = (FINAL_POWER * tau(g)) / TAU_END;
  // the night shows once the mosaic no longer covers the frame
  const covered = CX + mosaic.x0 * s <= 0 && CX + mosaic.x1 * s >= W && CY + mosaic.y0 * s <= 0 && CY + mosaic.y1 * s >= H;
  return (
    <AbsoluteFill style={{ background: GROUND, overflow: "hidden" }}>
      <Music track={p.music} />
      <Defs />
      {!covered && <Night s={s} sEnd={sEnd} mosaic={mosaic} />}
      {!covered && (
        <div style={{ position: "absolute", left: CX + ((mosaic.x0 + mosaic.x1) / 2) * s - (mosaic.y1 - mosaic.y0) * s * 1.1, top: CY + ((mosaic.y0 + mosaic.y1) / 2) * s - (mosaic.y1 - mosaic.y0) * s * 1.1,
          width: (mosaic.y1 - mosaic.y0) * s * 2.2, height: (mosaic.y1 - mosaic.y0) * s * 2.2, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,214,160,.32) 0%, rgba(255,200,140,.12) 38%, rgba(255,200,140,0) 70%)" }} />
      )}
      <MosaicView mosaic={mosaic} s={s} p={p} />
      <WordBands g={g} p={p} mosaic={mosaic} scaleAt={scaleAt} windows={windows} />
      <TitleStrip g={g} p={p} />
      <Marquee g={g} p={p} topAt={(f) => CY + mosaic.y0 * scaleAt(f)} />
      <EndCard g={g} p={p} bottomAt={(f) => CY + mosaic.y1 * scaleAt(f)} />
      <Readout power={power} p={p} />
    </AbsoluteFill>
  );
};
