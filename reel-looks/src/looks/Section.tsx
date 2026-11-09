import React from "react";
import { AbsoluteFill, Easing, Img, spring, staticFile, useCurrentFrame } from "remotion";
import { FPS, H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, fillerAt, photoAt, shapeOf } from "../slots";
import { MONO, SANS } from "../fonts";
import { Face, emWidth, fitSize, metrics, textWidth, useFontsReady } from "../measure";
import { Music } from "../music";

// SECTION: cut open to show the work inside; every event happens inside a building.
// The craft of the masters, not their look:
//   the architect's section drawing: the building cut through, the cut walls and floors solid black (poché), so inside
//   and outside read at once; David Macaulay's cutaways (The Way Things Work, Underground): the whole system visible at
//   once, numbered callouts on leader lines; Wes Anderson's track through a set built in section (the ship in The Life
//   Aquatic): the camera never cuts, it cranes floor to floor and tracks room to room, square on, and stops to let each
//   room play; the exploded view of technical illustration: parts apart on their axis with dashed assembly lines, then
//   snapping together; the title block in the corner of a drawing sheet.
// Made for Event Caliber (event and conference photography, DC · MD · VA), whose pictures are the heroes, so his rules
// shape the drawing: the building is designed around his pictures, every room exactly the shape of its photo, so each is
// shown whole; a room's picture is up only while the camera is still on it (moving, the rooms are drawn empty, so a
// frame's edge never cuts a picture); nothing is drawn over or around a picture (callouts sit on the cut floors and in
// the margins, leaders stop at the walls); the camera never pushes in (it cranes, tracks and pulls back); the words hold.
// The exploded view is the take: the frames of a moment apart on their axis, snapping into the one, the hero, whole.
// Paper in Event Caliber's second colour when it is a paper colour, ink line work, its colour for callouts, on a black
// table. JetBrains Mono for callouts and dimensions, Inter Tight heavy for the big lines.
//
// 16 s, 480 frames, on the 120 BPM grid (15-frame beats, 60-frame bars). One camera move over two sheets on a table:
//    bar 0  the roof and the attic (its room up), the hook above the roof (the cover); the last lines draw; crane down
//    bar 1  the first floor: its room comes up, callout 1 on the cut floor, its leader to a note: line 1
//    bar 2  crane down and track along the ground floor to room A: callout 2, line 2
//    bar 3  pull back to the whole sheet, its rooms drawn empty: a dimension line draws itself across the roof, the stack
//           label its figure
//    bar 4  the number, sectioned (outline and hatching) in a cartouche, label and unit
//    bar 5  the three words come up on the beats, each word's room numbered in the margin, the words as the legend: rooms
//           B and C come up, room A stays drawn empty beside its number (its word names the photo seen in it on its
//           stop); a whip along the table. Every room seen on its stop stays drawn empty: no picture is shown twice in a
//           reel (Chris, 2026-11-08, night), and the hero is seen once, from the exploded view to the end (2026-11-09:
//           it had come back after its room's stop and its word with no other picture between)
//    bar 6  the exploded view: three frames (fillers) apart on dashed assembly lines, callouts 1 to 4, then together on
//           the hit into the hero, straight on and whole; the marquee as the drawing's title
//    bar 7  the title block grows from the sheet's corner to fill the card under the hero: name, kicker, the call, site,
//           town, a scale bar (everything in by frame 440, then still)

// ------------------------------------------------------------------ the world

const INK = "#16161A";
const TABLE = "#0A0A0B";
// The post's six photos: the hero (slot 0), the exploded view's top plate and the end card's, seen there only; the three
// word rooms (A on the ground floor, seen on its stop, B beside it, C on the first floor); E (the attic, the cover) and D
// (the first floor's other room). The exploded view's three lower plates are fillers, more of his approved photos.
export const SLOTS: Slots = { photos: 6, fillers: 3 };
const HERO = 0, ROOM_A = 1, ROOM_B = 2, ROOM_C = 3, ATTIC = 4, FIRST_FLOOR_OTHER = 5;
const lum = (hex: string) => { const n = parseInt(hex.replace("#", "").slice(0, 6), 16); return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255; };
/** The sheet's paper: Event Caliber's second colour when it is a paper colour; otherwise warm drafting paper. The cut line
 *  takes whichever of the two colours is not the paper. */
const paperOf = (p: ReelProps) => (lum(p.accent2) > 0.86 ? p.accent2 : "#F3EFE6");
const cutOf = (p: ReelProps) => (lum(p.accent2) > 0.86 ? p.accent : p.accent2);

const HEAVY: Face = { family: SANS, weight: 850 };
const BLACK: Face = { family: SANS, weight: 900 };
const REG: Face = { family: SANS, weight: 400 };
const MED: Face = { family: SANS, weight: 650 };
const MONOF: Face = { family: MONO, weight: 500 };

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const clamp01 = (t: number) => Math.max(0, Math.min(1, t));
const smooth = (t: number) => { const x = clamp01(t); return x * x * (3 - 2 * x); };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const dolly = Easing.bezier(0.45, 0, 0.25, 1);      // a dolly: eases off its mark, glides, settles on the next
const M = 64;

// sheet 1 (the section) at x 0, sheet 2 (the detail) beside it on the table; world units are sheet pixels
const SW = 2160, SH = 3840, X2 = SW + 240;

// ------------------------------------------------------------------ the photos' true shapes

// each picture's shape comes from its props (slots.ts shapeOf), so the rooms fit the pictures from the first frame

// ------------------------------------------------------------------ the building, designed around the pictures

type Rect = { x0: number; y0: number; x1: number; y1: number };
type Room = Rect & { photo: number; col: "L" | "R" | "C" };
type Geo = {
  rooms: Room[];                         // A, B (ground), C, D (first floor), E (attic)
  halls: Rect[]; walls: Rect[]; slabs: Rect[]; windows: Rect[];
  XL: number; XR: number; IL: number; IR: number; T: number;
  RY: number; EY: number; EAVE_L: number; EAVE_R: number; ROOF_T: number; AF: number; FH: number;
  GRADE: number; FOUND: number; F0: [number, number]; F1: [number, number];
};
const SLAB = 54, T = 56, IT = 40, ROOF_T = 74;
const F0_FLOOR = 3240, FOUND = 3500;

/** Rooms the shape of their photos (a floor's height times the photo's aspect), two to a floor, a hall between them
 *  when the floor is wider than its rooms; an attic room under a gable pitched to clear it. */
const buildGeo = (p: ReelProps, aspect: (pic: Photo) => number): Geo => {
  const a = (i: number) => aspect(photoAt(p, i));
  let FH = 560, AH = 480;
  const wOf = (i: number, h: number) => Math.min(1000, h * a(i));
  const span = () => Math.max(wOf(ROOM_A, FH) + wOf(ROOM_B, FH) + IT, wOf(ROOM_C, FH) + wOf(FIRST_FLOOR_OTHER, FH) + IT, wOf(ATTIC, AH) + 320, 1100);
  const k = Math.min(1, 1640 / span());
  FH *= k; AH *= k;
  const BI = span();
  const IL = (SW - BI) / 2, IR = IL + BI, XL = IL - T, XR = IR + T;
  const F0: [number, number] = [F0_FLOOR - FH, F0_FLOOR];
  const F1: [number, number] = [F0[0] - SLAB - FH, F0[0] - SLAB];
  const AF = F1[0] - SLAB;
  const rooms: Room[] = [], halls: Rect[] = [], walls: Rect[] = [];
  const floor = (l: number, r: number, [y0, y1]: [number, number]) => {
    const wl = wOf(l, FH), wr = wOf(r, FH);
    rooms.push({ photo: l, col: "L", x0: IL, x1: IL + wl, y0, y1 }, { photo: r, col: "R", x0: IR - wr, x1: IR, y0, y1 });
    const gap = BI - wl - wr;
    if (gap <= IT + 70) walls.push({ x0: IL + wl, x1: IR - wr, y0, y1 });
    else {
      walls.push({ x0: IL + wl, x1: IL + wl + IT, y0, y1 }, { x0: IR - wr - IT, x1: IR - wr, y0, y1 });
      halls.push({ x0: IL + wl + IT, x1: IR - wr - IT, y0, y1 });
    }
  };
  floor(ROOM_A, ROOM_B, F0);
  floor(ROOM_C, FIRST_FLOOR_OTHER, F1);
  const wE = wOf(ATTIC, AH);
  rooms.push({ photo: ATTIC, col: "C", x0: SW / 2 - wE / 2, x1: SW / 2 + wE / 2, y0: AF - AH, y1: AF });
  // the gable: eaves past the walls; the ridge high enough that the roof's underside clears the attic room by 40
  const EAVE_L = XL - 110, EAVE_R = XR + 110, EY = AF - 12, run = SW / 2 - EAVE_L;
  const q = wE / 2 / run;
  const RY = Math.max(820, Math.min(EY - 0.45 * run, (AF * (1 - q) - AH - 40 - ROOF_T + 12 * q) / (1 - q) - 10));
  const slabs: Rect[] = [{ x0: XL, x1: XR, y0: AF, y1: AF + SLAB }, { x0: XL, x1: XR, y0: F0[0] - SLAB, y1: F0[0] }, { x0: XL, x1: XR, y0: F0_FLOOR, y1: F0_FLOOR + SLAB }];
  const windows: Rect[] = [];
  [F0, F1].forEach(([y0]) => [XL, IR].forEach((x) => windows.push({ x0: x, x1: x + T, y0: y0 + FH * 0.28, y1: y0 + FH * 0.82 })));
  return { rooms, halls, walls, slabs, windows, XL, XR, IL, IR, T, RY, EY, EAVE_L, EAVE_R, ROOF_T, AF, FH, GRADE: F0_FLOOR + 22, FOUND, F0, F1 };
};
const centreOf = (r: Rect): [number, number] => [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2];
const roomOfPhoto = (geo: Geo, i: number) => geo.rooms.find((r) => r.photo === i) ?? geo.rooms[0];

// ------------------------------------------------------------------ the camera: one move, no cuts, never in

type Key = [number, number, number, number, ((t: number) => number)?];   // frame, centre x, centre y, scale, easing in
const keysOf = (geo: Geo): Key[] => {
  const [ex] = centreOf(geo.rooms[4]);
  const [dx, dy] = centreOf(geo.rooms[3]);
  const [ax, ay] = centreOf(geo.rooms[0]);
  const [bx] = centreOf(geo.rooms[1]);
  const top = Math.max(geo.RY + 360, geo.rooms[4].y1 - 920);         // the hook in the sky, the attic whole below it
  return [
    [0, ex, top, 1],
    [50, ex, top, 1, Easing.linear],
    [68, dx, dy, 1, dolly],                    // crane down to the first floor
    [124, dx, dy, 1, Easing.linear],
    [134, bx, ay, 1, dolly],                   // down a floor...
    [146, ax, ay, 1, dolly],                   // ...and along the ground floor to room A
    [200, ax, ay, 1, Easing.linear],
    [220, SW / 2, SH / 2, 0.5, dolly],         // pull back to the whole sheet
    [354, SW / 2, SH / 2, 0.47, Easing.linear],
    [368, X2 + SW / 2, SH / 2, 0.47, Easing.bezier(0.72, 0, 0.28, 1)],   // the whip along the table to sheet 2
    [480, X2 + SW / 2, SH / 2, 0.47, Easing.linear],
  ];
};
const camAt = (keys: Key[], g: number) => {
  let i = 0;
  while (i < keys.length - 2 && g >= keys[i + 1][0]) i++;
  const a = keys[i], b = keys[i + 1];
  const k = (b[4] ?? Easing.linear)(clamp01((g - a[0]) / (b[0] - a[0])));
  return { x: lerp(a[1], b[1], k), y: lerp(a[2], b[2], k), s: Math.exp(lerp(Math.log(a[3]), Math.log(b[3]), k)) };
};
type Cam = ReturnType<typeof camAt>;
const toScreen = (c: Cam, x: number, y: number): [number, number] => [(x - c.x) * c.s + W / 2, (y - c.y) * c.s + H / 2];

// ------------------------------------------------------------------ type

type Run = { text: string; face: Face };
const runsEm = (runs: Run[], track = 0) => runs.reduce((s, r) => s + emWidth(r.text, r.face, track), 0);
const capOf = (face: Face, size: number) => metrics(face).cap * size;

/** A line of runs placed by its ink: capTop is where the tops of the capitals sit; x its left edge, or its centre. */
const Type: React.FC<{ runs: Run[]; size: number; capTop: number; x: number; centre?: boolean; color?: string; track?: number; opacity?: number; caps?: boolean; chars?: number }> = ({ runs, size, capTop, x, centre, color = INK, track = 0, opacity = 1, caps, chars }) => {
  if (opacity <= 0.002) return null;
  const m = metrics(runs[0].face);
  const top = capTop - (m.base - m.cap) * size;
  let left = chars ?? 1e9;
  return (
    <div style={{ position: "absolute", top, left: centre ? x - 4000 : x, width: centre ? 8000 : undefined, textAlign: centre ? "center" : "left", whiteSpace: "nowrap", opacity,
      fontSize: size, lineHeight: 1, letterSpacing: `${track}em`, color, textTransform: caps ? "uppercase" : "none", fontVariantNumeric: "lining-nums tabular-nums" }}>
      {runs.map((r, i) => {
        const shown = r.text.slice(0, Math.max(0, left)), hidden = r.text.slice(Math.max(0, left));
        left -= r.text.length;
        return <span key={i} style={{ fontFamily: r.face.family, fontWeight: r.face.weight }}>{shown}<span style={{ opacity: 0 }}>{hidden}</span></span>;
      })}
    </div>
  );
};

/** A callout: a disc of Event Caliber's colour, ink-ringed, its number in mono. Pops on its beat. Never on a picture. */
const Bubble: React.FC<{ x: number; y: number; r: number; n: string; k: number; fill: string }> = ({ x, y, r, n, k, fill }) => {
  if (k <= 0.002) return null;
  return (
    <div style={{ position: "absolute", left: x - r, top: y - r, width: 2 * r, height: 2 * r, borderRadius: r, background: fill, boxShadow: `inset 0 0 0 ${r * 0.1}px ${INK}`,
      transform: `scale(${k.toFixed(4)})`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: MONO, fontSize: r * 1.05, color: INK, lineHeight: 1 }}>
      <span style={{ marginTop: r * 0.06 }}>{n}</span>
    </div>
  );
};

/** A sheet of paper on the table: the faint drafting grid, a double border with zone marks along it. */
const Paper: React.FC<{ x: number; paper: string; children?: React.ReactNode }> = ({ x, paper, children }) => (
  <div style={{ position: "absolute", left: x, top: 0, width: SW, height: SH, backgroundColor: paper, boxShadow: "0 40px 90px rgba(0,0,0,.6)",
    backgroundImage: ["linear-gradient(rgba(22,22,26,.085) 2px, transparent 2px)", "linear-gradient(90deg, rgba(22,22,26,.085) 2px, transparent 2px)",
      "linear-gradient(rgba(22,22,26,.04) 1.5px, transparent 1.5px)", "linear-gradient(90deg, rgba(22,22,26,.04) 1.5px, transparent 1.5px)"].join(", "),
    backgroundSize: "200px 200px, 200px 200px, 40px 40px, 40px 40px", backgroundPosition: "40px 40px, 40px 40px, 40px 40px, 40px 40px" }}>
    {children}
    <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0 }}>
      <rect x={44} y={44} width={SW - 88} height={SH - 88} fill="none" stroke={INK} strokeWidth={5} />
      <rect x={60} y={60} width={SW - 120} height={SH - 120} fill="none" stroke={INK} strokeWidth={1.6} />
      <g stroke={INK} strokeWidth={1.6}>
        {[1, 2, 3].map((i) => <React.Fragment key={i}><line x1={(SW * i) / 4} y1={44} x2={(SW * i) / 4} y2={60} /><line x1={(SW * i) / 4} y1={SH - 60} x2={(SW * i) / 4} y2={SH - 44} /></React.Fragment>)}
        {[1, 2, 3, 4, 5].map((i) => <React.Fragment key={i}><line x1={44} y1={(SH * i) / 6} x2={60} y2={(SH * i) / 6} /><line x1={SW - 60} y1={(SH * i) / 6} x2={SW - 44} y2={(SH * i) / 6} /></React.Fragment>)}
      </g>
    </svg>
  </div>
);

/** The scale bar: 0, 1, 2 and 5 m, in alternating ink and paper. */
const ScaleBar: React.FC<{ x: number; y: number; px: number; size?: number; paper: string }> = ({ x, y, px, size = 30, paper }) => (
  <svg width={6 * px + 200} height={size * 3 + 30} style={{ position: "absolute", left: x - 20, top: y - size * 1.6, overflow: "visible" }}>
    <g transform={`translate(20 ${size * 1.6})`}>
      {[0, 1, 2, 3, 4].map((i) => <rect key={i} x={i * px} y={0} width={px} height={size * 0.5} fill={i % 2 ? paper : INK} stroke={INK} strokeWidth={2} />)}
      {[0, 1, 2, 5].map((m) => <text key={m} x={m * px} y={-size * 0.45} textAnchor="middle" fill={INK} style={{ fontFamily: MONO, fontSize: size }}>{m}</text>)}
      <text x={5 * px + size * 0.5} y={size * 0.48} fill={INK} style={{ fontFamily: MONO, fontSize: size }}>m</text>
    </g>
  </svg>
);

// ------------------------------------------------------------------ sheet 1: the section

/** A room: drawn empty (its far wall in thin line: a door, a dado) until it is lit, when its picture is up in it, whole,
 *  the room's exact shape, exactly as shot (it comes and goes on the beat, never fading: a fade would darken it). */
const RoomView: React.FC<{ room: Room; pic: Photo; lit: boolean }> = ({ room, pic, lit }) => {
  const w = room.x1 - room.x0, h = room.y1 - room.y0;
  return (
    <>
      <svg width={w} height={h} style={{ position: "absolute", left: room.x0, top: room.y0, overflow: "visible" }}>
        <g stroke={INK} strokeWidth={2.2} fill="none" opacity={0.42}>
          <rect x={w * 0.1} y={h * 0.26} width={Math.min(150, w * 0.18)} height={h * 0.74} />
          <line x1={0} y1={h * 0.58} x2={w} y2={h * 0.58} strokeWidth={1.4} />
          <line x1={w / 2} y1={0} x2={w / 2} y2={h * 0.12} strokeWidth={1.4} /><circle cx={w / 2} cy={h * 0.12 + 9} r={9} />
        </g>
      </svg>
      {lit && (
        <div style={{ position: "absolute", left: room.x0, top: room.y0, width: w, height: h }}>
          <Img src={staticFile(pic.src)} style={{ width: "100%", height: "100%", objectFit: "contain", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`, display: "block" }} />
        </div>
      )}
    </>
  );
};

/** The line work: poché (the roof, the walls, the floors, the footings, solid), windows cut through, halls drawn empty,
 *  the ground hatched below grade; then the drawing's marks: levels, a dimension chain, the key plan with its cut line,
 *  a scale bar. `draw` (0 to 1) finishes the secondary lines over the first bar. */
const Linework: React.FC<{ geo: Geo; draw: number; cut: string; paper: string }> = ({ geo, draw, cut, paper }) => {
  const { XL, XR, IL, IR, RY, EY, EAVE_L, EAVE_R, AF, GRADE, F0, F1 } = geo;
  const roof = `M ${EAVE_L} ${EY} L ${SW / 2} ${RY} L ${EAVE_R} ${EY} L ${EAVE_R} ${EY + ROOF_T} L ${SW / 2} ${RY + ROOF_T} L ${EAVE_L} ${EY + ROOF_T} Z`;
  const dash = (len: number, k: number) => ({ strokeDasharray: `${len} ${len}`, strokeDashoffset: len * (1 - k) });
  const kDim = ramp(draw, 0.1, 0.75, Easing.linear), kLev = ramp(draw, 0.2, 0.8, Easing.linear), kKey = ramp(draw, 0.3, 1, Easing.linear), kHatch = ramp(draw, 0, 0.6, Easing.linear);
  const storey = (F0[1] - F1[1]) / 3;   // the drawing's scale: a storey is 3.00 m
  const levels: [number, string][] = [[F0[1], "±0.00"], [F1[1], `+${((F0[1] - F1[1]) / storey).toFixed(2)}`], [AF, `+${((F0[1] - AF) / storey).toFixed(2)}`]];
  const chain = [F0[1], F1[1], AF, RY];
  const KP = { x: 1580, y: 3620, w: 420, h: 150 };
  const lx = 80;
  return (
    <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      {/* the ground below grade, cut and hatched; it fades out downward */}
      <g mask="url(#sec-fade)" opacity={kHatch}>
        <rect x={90} y={GRADE} width={XL - 90} height={320} fill="url(#sec-earth)" />
        <rect x={XR} y={GRADE} width={2070 - XR} height={320} fill="url(#sec-earth)" />
        <rect x={IL} y={F0[1] + SLAB} width={IR - IL} height={300} fill="url(#sec-gravel)" />
      </g>
      {/* poché: everything the cut passes through */}
      <g fill={INK}>
        <path d={roof} />
        <rect x={XL} y={AF - 20} width={T} height={FOUND - AF + 20} /><rect x={IR} y={AF - 20} width={T} height={FOUND - AF + 20} />
        {geo.slabs.map((r, i) => <rect key={`s${i}`} x={r.x0} y={r.y0} width={r.x1 - r.x0} height={r.y1 - r.y0} />)}
        {geo.walls.map((r, i) => <rect key={`w${i}`} x={r.x0} y={r.y0} width={r.x1 - r.x0} height={r.y1 - r.y0} />)}
        <rect x={XL - 44} y={FOUND} width={T + 88} height={60} /><rect x={IR - 44} y={FOUND} width={T + 88} height={60} />
      </g>
      {/* the windows, cut through the walls: an opening with its glass */}
      {geo.windows.map((r, i) => (
        <g key={`win${i}`}>
          <rect x={r.x0} y={r.y0} width={r.x1 - r.x0} height={r.y1 - r.y0} fill={paper} />
          <g stroke={INK} strokeWidth={2.4}><line x1={r.x0 + T / 2 - 6} y1={r.y0} x2={r.x0 + T / 2 - 6} y2={r.y1} /><line x1={r.x0 + T / 2 + 6} y1={r.y0} x2={r.x0 + T / 2 + 6} y2={r.y1} /></g>
        </g>
      ))}
      {/* halls, drawn empty: a door beyond */}
      <g stroke={INK} strokeWidth={2.2} fill="none" opacity={0.42}>
        {geo.halls.map((r, i) => <rect key={`h${i}`} x={(r.x0 + r.x1) / 2 - Math.min(70, (r.x1 - r.x0) * 0.3)} y={r.y0 + (r.y1 - r.y0) * 0.26} width={Math.min(140, (r.x1 - r.x0) * 0.6)} height={(r.y1 - r.y0) * 0.74} />)}
      </g>
      {/* grade */}
      <g stroke={INK} strokeWidth={6} strokeLinecap="square"><line x1={90} y1={GRADE} x2={XL} y2={GRADE} /><line x1={XR} y1={GRADE} x2={2070} y2={GRADE} /></g>
      {/* levels, on the left */}
      <g opacity={kLev}>
        {levels.map(([y, t], i) => (
          <g key={i}>
            <line x1={lx} y1={y} x2={lx + 70} y2={y} stroke={INK} strokeWidth={2.4} {...dash(70, kLev)} />
            <polygon points={`${lx + 18},${y} ${lx + 6},${y - 18} ${lx + 30},${y - 18}`} fill={INK} />
            <text x={lx} y={y - 30} fill={INK} style={{ fontFamily: MONO, fontSize: 30 }}>{t}</text>
          </g>
        ))}
      </g>
      {/* the dimension chain, on the right: floor to floor, and to the ridge */}
      <g stroke={INK} strokeWidth={2.4} fill="none">
        <line x1={2082} y1={chain[0]} x2={2082} y2={chain[3]} {...dash(chain[0] - chain[3], kDim)} />
        {chain.map((y, i) => <React.Fragment key={i}><line x1={i === 3 ? SW / 2 + 30 : XR + 110} y1={y} x2={2096} y2={y} strokeWidth={1.4} opacity={kDim} /><line x1={2068} y1={y + 14} x2={2096} y2={y - 14} strokeWidth={5} opacity={kDim} /></React.Fragment>)}
      </g>
      {/* the key plan, bottom right: where the section is cut */}
      <g opacity={kKey}>
        <rect x={KP.x} y={KP.y} width={KP.w} height={KP.h} fill="none" stroke={INK} strokeWidth={7} />
        <line x1={KP.x + KP.w * 0.54} y1={KP.y} x2={KP.x + KP.w * 0.54} y2={KP.y + KP.h} stroke={INK} strokeWidth={4} />
        <line x1={KP.x - 50} y1={KP.y + KP.h * 0.5} x2={KP.x + KP.w + 50} y2={KP.y + KP.h * 0.5} stroke={cut} strokeWidth={6} strokeDasharray="38 10 6 10" />
        {[KP.x - 50, KP.x + KP.w + 50].map((x, i) => (
          <g key={i}>
            <polygon points={`${x - 16},${KP.y + KP.h * 0.5 - 6} ${x + 16},${KP.y + KP.h * 0.5 - 6} ${x},${KP.y + KP.h * 0.5 - 34}`} fill={INK} />
            <circle cx={x} cy={KP.y + KP.h * 0.5 + 34} r={24} fill={paper} stroke={INK} strokeWidth={2.4} />
            <text x={x} y={KP.y + KP.h * 0.5 + 45} textAnchor="middle" fill={INK} style={{ fontFamily: MONO, fontSize: 30 }}>A</text>
          </g>
        ))}
      </g>
    </svg>
  );
};

/** 0 · the hook, in heavy ink above the roof: there from frame 0 (the cover); it goes before the camera moves. */
const Hook: React.FC<{ g: number; p: ReelProps; geo: Geo }> = ({ g, p, geo }) => {
  if (g > 48) return null;
  const open: Run[] = [{ text: p.open[0], face: HEAVY }, { text: ` ${p.open[1]}`, face: HEAVY }];
  const oS = Math.min(150, (W - 2 * M) / runsEm(open, -0.02));
  const sS = fitSize(p.openSub, REG, W - 2 * M, 68);
  const top = geo.RY - 330;
  const gone = ramp(g, 41, 48, Easing.in(Easing.quad));
  return (
    <>
      <Type runs={open} size={oS} capTop={top} x={SW / 2} centre track={-0.02} opacity={1 - gone} />
      <Type runs={[{ text: p.openSub, face: REG }]} size={sS} capTop={top + capOf(HEAVY, oS) + 52} x={SW / 2} centre color="#3A3A40" opacity={1 - gone} />
    </>
  );
};

/** 3 · the dimension across the roof, eave to eave: extension lines, the line drawing out from the middle, ticks; the
 *  stack label lettered in as its figure. */
const RoofDim: React.FC<{ g: number; p: ReelProps; geo: Geo }> = ({ g, p, geo }) => {
  if (g < 218 || g > 266) return null;
  const y = geo.RY - 70, gone = ramp(g, 258, 265, Easing.linear);
  const ext = ramp(g, 220, 228, Easing.linear), line = expoOut(ramp(g, 222, 238, Easing.linear));
  const half = ((geo.EAVE_R - geo.EAVE_L) / 2) * line;
  const size = Math.min(84, (geo.EAVE_R - geo.EAVE_L - 200) / emWidth(p.stackLabel.toUpperCase(), MONOF, 0.14));
  const chars = Math.floor(ramp(g, 228, 244, Easing.linear) * (p.stackLabel.length + 1));
  return (
    <div style={{ position: "absolute", left: 0, top: 0, opacity: 1 - gone }}>
      <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <g stroke={INK} strokeWidth={3}>
          {[geo.EAVE_L, geo.EAVE_R].map((x, i) => <line key={i} x1={x} y1={geo.EY - 24} x2={x} y2={geo.EY - 24 - (geo.EY - 24 - (y - 30)) * ext} />)}
          <line x1={SW / 2 - half} y1={y + 9} x2={SW / 2 + half} y2={y + 9} stroke={p.accent} strokeWidth={10} />
          <line x1={SW / 2 - half} y1={y} x2={SW / 2 + half} y2={y} />
          {line > 0.98 && [geo.EAVE_L, geo.EAVE_R].map((x, i) => <line key={`t${i}`} x1={x - 22} y1={y + 22} x2={x + 22} y2={y - 22} strokeWidth={7} />)}
        </g>
      </svg>
      <Type runs={[{ text: p.stackLabel, face: MONOF }]} size={size} capTop={y - 44 - capOf(MONOF, size)} x={SW / 2 + size * 0.07} centre track={0.14} caps chars={chars} />
    </div>
  );
};

/** Where the legend of words sits: in the sky, just above the ridge. */
const legendTop = (geo: Geo) => Math.min(geo.RY - 230, 980);

/** 4 · the number: a cartouche drawn in the sky, the figure in section (its outline cut, the inside hatched), the label
 *  over it, the unit under it. It stays while the rooms come up. */
const Cartouche: React.FC<{ g: number; p: ReelProps; geo: Geo; paper: string }> = ({ g, p, geo, paper }) => {
  if (g < 246 || g > 356) return null;
  const gone = ramp(g, 348, 355, Easing.linear);
  const y0 = 100, y1 = legendTop(geo) - 70;
  const box = { x: 230, y: y0, w: 1700, h: y1 - y0 }, n = 64;
  const frame = (o: number) => {
    const x0 = box.x + o, yy0 = box.y + o, x1 = box.x + box.w - o, yy1 = box.y + box.h - o, r = n - o;
    return `M ${x0 + r} ${yy0} L ${x1 - r} ${yy0} A ${r} ${r} 0 0 0 ${x1} ${yy0 + r} L ${x1} ${yy1 - r} A ${r} ${r} 0 0 0 ${x1 - r} ${yy1} L ${x0 + r} ${yy1} A ${r} ${r} 0 0 0 ${x0} ${yy1 - r} L ${x0} ${yy0 + r} A ${r} ${r} 0 0 0 ${x0 + r} ${yy0} Z`;
  };
  const kF = ramp(g, 248, 264, Easing.inOut(Easing.quad)), kOut = ramp(g, 252, 268, Easing.linear), kHatch = ramp(g, 258, 272, Easing.linear);
  const v = p.counter.value;
  const mB = metrics(BLACK);
  const labS = Math.min(72, (box.w - 300) / emWidth(p.counter.label.toUpperCase(), MONOF, 0.22));
  const unitS = Math.min(96, fitSize(p.counter.unit, REG, box.w - 300, 96));
  const labTop = box.y + 66, capTop = labTop + capOf(MONOF, labS) + 56;
  const numCap = Math.max(150, box.y + box.h - 50 - capOf(REG, unitS) - 46 - capTop);
  const numS = Math.min(numCap / mB.cap, (box.w - 300) / emWidth(v, BLACK, -0.02));
  const base = capTop + mB.cap * numS;
  const tw = textWidth(v, BLACK, numS, -0.02);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, opacity: 1 - gone }}>
      <div style={{ position: "absolute", left: box.x, top: box.y, width: box.w, height: box.h, background: paper, opacity: ramp(g, 246, 252, Easing.linear) }} />
      <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <path d={frame(0)} fill="none" stroke={INK} strokeWidth={6} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - kF} />
        <path d={frame(20)} fill="none" stroke={INK} strokeWidth={2} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ramp(g, 252, 268, Easing.inOut(Easing.quad))} />
        <defs><clipPath id="sec-hatch-wipe"><rect x={SW / 2 - tw / 2 - 40} y={capTop - 60} width={(tw + 80) * kHatch} height={mB.cap * numS + 120} /></clipPath></defs>
        <text x={SW / 2} y={base} textAnchor="middle" fill="url(#sec-hatch)" clipPath="url(#sec-hatch-wipe)" style={{ fontFamily: SANS, fontWeight: 900, fontSize: numS, letterSpacing: "-0.02em" }}>{v}</text>
        <text x={SW / 2} y={base} textAnchor="middle" fill="none" stroke={INK} strokeWidth={9} strokeLinejoin="round" strokeDasharray="9000 9000" strokeDashoffset={9000 * (1 - kOut)}
          style={{ fontFamily: SANS, fontWeight: 900, fontSize: numS, letterSpacing: "-0.02em" }}>{v}</text>
      </svg>
      <Type runs={[{ text: p.counter.label, face: MONOF }]} size={labS} capTop={labTop} x={SW / 2 + labS * 0.11} centre track={0.22} caps opacity={ramp(g, 254, 262, Easing.linear)} />
      <Type runs={[{ text: p.counter.unit, face: REG }]} size={unitS} capTop={base + 46} x={SW / 2} centre opacity={ramp(g, 260, 268, Easing.linear)} />
    </div>
  );
};

const WORD_AT = [285, 300, 315];          // the beats the three words come up on
// the camera's stops on sheet 1, each with its room up (by its place in geo.rooms: A, B, C, D, E) and the frames it is up
const STOPS: [number, number, number][] = [[4, 0, 44], [3, 70, 120], [0, 148, 196]];

/** 5 · the legend in the sky: each word's number and the word, in on its beat; and each word's room numbered in the
 *  margin beside it, its leader stopping at the wall. */
const Legend: React.FC<{ g: number; p: ReelProps; geo: Geo }> = ({ g, p, geo }) => {
  if (g < 283 || g > 356) return null;
  const idx = p.wordPhotos;
  const gone = ramp(g, 346, 353, Easing.linear);
  const r = 46, gap = 80;
  const size = Math.min(116, (1900 - 3 * (2 * r + 26) - 2 * gap) / p.words.reduce((s, w) => s + emWidth(w, HEAVY, -0.01), 0));
  const widths = p.words.map((w) => 2 * r + 26 + textWidth(w, HEAVY, size, -0.01));
  let x = SW / 2 - (widths.reduce((a, b) => a + b, 0) + 2 * gap) / 2;
  const top = legendTop(geo);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, opacity: 1 - gone }}>
      {p.words.map((w, i) => {
        const at = WORD_AT[i];
        const x0 = x; x += widths[i] + gap;
        if (g < at) return null;
        const pop = spring({ frame: g - at, fps: FPS, config: { damping: 12, stiffness: 220, mass: 0.6 } });
        const k = ramp(g, at + 1, at + 7, Easing.linear);
        const room = roomOfPhoto(geo, idx[i]);
        const [, ry] = centreOf(room);
        const right = room.col === "R" || (room.col === "C" && i % 2 === 1);
        const wallX = right ? (room.col === "C" ? room.x1 : geo.XR) : room.col === "C" ? room.x0 : geo.XL;
        const bx = right ? Math.min(SW - 100, geo.XR + 58) : Math.max(100, geo.XL - 58);
        const lead = ramp(g, at + 2, at + 9, Easing.linear);
        const end = wallX + (right ? 6 : -6);
        return (
          <React.Fragment key={i}>
            <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <line x1={bx + (right ? -r : r)} y1={ry} x2={lerp(bx + (right ? -r : r), end, lead)} y2={ry} stroke={INK} strokeWidth={4} />
            </svg>
            <Bubble x={bx} y={ry} r={r} n={`${i + 1}`} k={pop} fill={p.accent} />
            <Bubble x={x0 + r} y={top + capOf(HEAVY, size) / 2} r={r} n={`${i + 1}`} k={pop} fill={p.accent} />
            <Type runs={[{ text: w, face: HEAVY }]} size={size} capTop={top + (1 - k) * 14} x={x0 + 2 * r + 26} track={-0.01} opacity={k} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

const Sheet1: React.FC<{ g: number; p: ReelProps; geo: Geo; lit: (i: number) => boolean; paper: string; cut: string }> = ({ g, p, geo, lit, paper, cut }) => (
  <Paper x={0} paper={paper}>
    {geo.rooms.map((room, i) => <RoomView key={i} room={room} pic={photoAt(p, room.photo)} lit={lit(i)} />)}
    <Linework geo={geo} draw={ramp(g, 0, 40, Easing.linear)} cut={cut} paper={paper} />
    <ScaleBar x={130} y={3730} px={(geo.F0[1] - geo.F1[1]) / 3 * 0.5} size={30} paper={paper} />
    <Hook g={g} p={p} geo={geo} />
    <RoofDim g={g} p={p} geo={geo} />
    <Cartouche g={g} p={p} geo={geo} paper={paper} />
    <Legend g={g} p={p} geo={geo} />
  </Paper>
);

// ------------------------------------------------------------------ sheet 2: the exploded view of the take

const S2 = 0.47;                                   // the camera's scale on sheet 2 (the scale of the whole-sheet view)
const toLocal = (sx: number, sy: number): [number, number] => [SW / 2 + (sx - W / 2) / S2, SH / 2 + (sy - H / 2) / S2];
const ISO_TH = (-28 * Math.PI) / 180, ISO_PH = (56 * Math.PI) / 180;
const fitBox = (a: number, bw: number, bh: number): [number, number] => { const w = Math.min(bw, bh * a); return [w / S2, w / a / S2]; };

/** Plate space (u, v across the plate from its centre, h up the stack's axis) to the sheet: turn about the axis, tilt,
 *  drop the depth. Orthographic, so a flat plate stays a parallelogram and its picture is an affine image of itself. */
const proj = (u: number, v: number, h: number, th: number, phi: number, cx: number, cy: number): [number, number] => {
  const x = u * Math.cos(th) - v * Math.sin(th), y = u * Math.sin(th) + v * Math.cos(th);
  return [cx + x, cy + y * Math.cos(phi) - h * Math.sin(phi)];
};

const HERO_Y = 520, HERO_W = 720, HERO_H = 580;   // where the hero's centre sits on screen, and the box it fills
const Exploded: React.FC<{ g: number; p: ReelProps; aspect: (pic: Photo) => number; cut: string }> = ({ g, p, aspect, cut }) => {
  const t = g - 368;
  if (t < 0) return null;
  const plates = [fillerAt(p, 0), fillerAt(p, 1), fillerAt(p, 2), photoAt(p, HERO)];     // bottom to top; the hero last
  const sizes = plates.map((pic, n) => fitBox(aspect(pic), n === 3 ? HERO_W : 420, n === 3 ? HERO_H : 300));
  const projH = ([w, h]: [number, number]) => Math.cos(ISO_PH) * (Math.abs(Math.sin(ISO_TH)) * w + Math.cos(ISO_TH) * h);
  // exploded, the plates hang below the hero on its axis, each clear of the next
  const drop: number[] = [0, 0, 0, 0];
  for (let n = 2; n >= 0; n--) drop[n] = drop[n + 1] + (projH(sizes[n + 1]) + projH(sizes[n])) / 2 + 40 / S2;
  const apart = t < 30 ? expoOut(ramp(t, 2, 14, Easing.linear)) : 1 - Easing.in(Easing.cubic)(ramp(t, 30, 37, Easing.linear));
  const q = Easing.inOut(Easing.quad)(ramp(t, 31, 38, Easing.linear));
  const th = ISO_TH * (1 - q), phi = ISO_PH * (1 - q);
  const [cx, cy] = toLocal(lerp(500, W / 2, q), HERO_Y);
  const hOf = (n: number) => (-drop[n] * apart) / Math.sin(ISO_PH);
  const P = (n: number, u: number, v: number) => proj(u, v, hOf(n), th, phi, cx, cy);
  const corners = (n: number): [number, number][] => { const [w, h] = sizes[n]; return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]; };
  const css = (n: number) => {
    const [w, h] = sizes[n];
    const a = Math.cos(th), b = Math.cos(phi) * Math.sin(th), c = -Math.sin(th), d = Math.cos(phi) * Math.cos(th);
    const [px, py] = P(n, 0, 0);
    return `matrix(${a.toFixed(5)}, ${b.toFixed(5)}, ${c.toFixed(5)}, ${d.toFixed(5)}, ${(px - (a * w) / 2 - (c * h) / 2).toFixed(2)}, ${(py - (b * w) / 2 - (d * h) / 2).toFixed(2)})`;
  };
  const dashK = ramp(t, 4, 14, Easing.linear) * (1 - ramp(t, 28, 31, Easing.linear));
  const callK = (n: number) => smooth((t - 6 - n * 2) / 5) * (1 - smooth((t - 27) / 3));
  const axisA = proj(0, 0, 300, th, phi, cx, cy), axisB = proj(0, 0, hOf(0) - 300, th, phi, cx, cy);
  return (
    <>
      {/* under everything: the axis the frames slide on, and the assembly lines from the hero's corners down it */}
      <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <line x1={axisA[0]} y1={axisA[1]} x2={axisB[0]} y2={axisB[1]} stroke={cut} strokeWidth={9} strokeDasharray="70 20 12 20" opacity={smooth(apart * 3) * (1 - q)} />
        <g stroke={INK} strokeWidth={4.5} strokeDasharray="30 20" opacity={dashK}>
          {corners(3).map(([u, v], i) => { const a = P(3, u, v), b = proj(u, v, hOf(0), th, phi, cx, cy); return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />; })}
        </g>
      </svg>
      {/* the frames of the take, bottom to top, the hero last: each whole, exactly as shot */}
      {plates.map((pic, n) => {
        if (n < 3 && apart < 0.02) return null;
        const [w, h] = sizes[n];
        return (
          <div key={n} style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0", transform: css(n) }}>
            <Img src={staticFile(pic.src)} style={{ width: "100%", height: "100%", objectFit: "fill", display: "block" }} />
          </div>
        );
      })}
      {/* callouts 1 to 4, off each frame's right-hand corner */}
      {plates.map((_, n) => {
        const k = callK(n);
        if (k <= 0.002) return null;
        const c = corners(n).map(([u, v]) => P(n, u, v)).reduce((m, pt) => (pt[0] > m[0] ? pt : m));
        const bx = c[0] + 140, by = c[1];
        return (
          <React.Fragment key={`c${n}`}>
            <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: k }}>
              <line x1={c[0] + 16} y1={c[1]} x2={bx - 52} y2={by} stroke={INK} strokeWidth={4.5} />
            </svg>
            <Bubble x={bx} y={by} r={52} n={`${n + 1}`} k={k} fill={p.accent} />
          </React.Fragment>
        );
      })}
    </>
  );
};

/** 6 · the marquee as the drawing's title, under the hero once it is together: detail number, word, rule, scale. */
const DetailTitle: React.FC<{ g: number; p: ReelProps; aspect: (pic: Photo) => number }> = ({ g, p, aspect }) => {
  if (g < 403) return null;
  const [, hh] = fitBox(aspect(photoAt(p, HERO)), HERO_W, HERO_H);
  const [x0] = toLocal(W / 2 - HERO_W / 2, 0);
  const y = toLocal(0, HERO_Y)[1] + hh / 2 + 150;
  const r = 66, width = HERO_W / S2;
  const size = Math.min(230, (width - 2 * r - 70) / emWidth(p.marquee, BLACK, -0.02));
  const rule = expoOut(ramp(g, 406, 418, Easing.linear));
  const pop = spring({ frame: g - 404, fps: FPS, config: { damping: 12, stiffness: 200, mass: 0.6 } });
  const capH = capOf(BLACK, size);
  return (
    <>
      <div style={{ position: "absolute", left: x0, top: y - r, width: 2 * r, height: 2 * r, borderRadius: r, border: `7px solid ${INK}`, boxSizing: "border-box", transform: `scale(${pop.toFixed(4)})`,
        display: "flex", alignItems: "center", justifyContent: "center", fontFamily: MONO, fontSize: 70, color: INK }}>1</div>
      <div style={{ position: "absolute", left: x0 + 2 * r + 36, top: y + capH / 2 + 30, width: (width - 2 * r - 36) * rule, height: 16, background: INK }} />
      <div style={{ position: "absolute", left: x0 + 2 * r + 36, top: y - capH / 2 - 40, width: width - 2 * r - 36, height: capH + 64, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: 0, transform: `translateY(${((1 - expoOut(ramp(g, 407, 417, Easing.linear))) * (capH + 70)).toFixed(1)}px)` }}>
          <Type runs={[{ text: p.marquee, face: BLACK }]} size={size} capTop={40} x={0} track={-0.02} />
        </div>
      </div>
      <Type runs={[{ text: "1:1", face: MONOF }]} size={56} capTop={y + capH / 2 + 80} x={x0 + 2 * r + 36} opacity={ramp(g, 412, 420, Easing.linear)} />
    </>
  );
};

// ------------------------------------------------------------------ over the drawing: notes and the title block

/** 1, 2 · a note on a leader: the callout pops on the cut floor beside the lit room, its leader runs to a note card laid
 *  over a dark room (never over a picture), the line lettered on it, heavy word then tail. Gone before the camera moves. */
const Note: React.FC<{ g: number; cam: Cam; at: number; until: number; n: number; target: [number, number]; cardY: number; pair: [string, string]; p: ReelProps; paper: string }> = ({ g, cam, at, until, n, target, cardY, pair, p, paper }) => {
  if (g < at || g > until) return null;
  const gone = ramp(g, until - 6, until, Easing.in(Easing.quad));
  const pop = spring({ frame: g - at, fps: FPS, config: { damping: 11, stiffness: 210, mass: 0.6 } });
  const [bx, by] = toScreen(cam, target[0], target[1]);
  const r = 25 * cam.s;
  const runs: Run[] = [{ text: pair[0], face: HEAVY }, { text: ` ${pair[1]}`, face: REG }];
  const size = Math.min(100, (W - 2 * M - 100) / runsEm(runs, -0.01));
  const pad = 44, h = capOf(HEAVY, size) + 2 * pad;
  const below = cardY > by;
  const edge = below ? cardY : cardY + h;
  const lead = ramp(g, at + 2, at + 9, Easing.linear);
  const open = expoOut(ramp(g, at + 6, at + 14, Easing.linear));
  const y0 = by + (below ? r : -r);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - gone }}>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <line x1={bx} y1={y0} x2={bx} y2={lerp(y0, edge, lead)} stroke={INK} strokeWidth={3} />
      </svg>
      <div style={{ position: "absolute", left: M, top: cardY, width: W - 2 * M, height: h, background: paper, border: `3px solid ${INK}`, boxSizing: "border-box", transform: `scaleX(${open})`, transformOrigin: `${bx - M}px 50%`,
        boxShadow: "10px 10px 0 rgba(22,22,26,.14)" }} />
      <Type runs={runs} size={size} capTop={cardY + pad + (1 - expoOut(ramp(g, at + 10, at + 18, Easing.linear))) * 14} x={M + 48} track={-0.01} opacity={ramp(g, at + 10, at + 16, Easing.linear)} />
      <Bubble x={bx} y={by} r={r} n={`${n}`} k={pop} fill={p.accent} />
    </div>
  );
};

/** 7 · the title block: it grows out of the sheet's bottom right-hand corner to fill the card under the hero, then its
 *  cells letter in: the name as the title, what they do, the call in a box of Event Caliber's colour, the site and the
 *  town, a scale bar. All in by frame 440; then still. */
const TB_TOP = 1040;
const TitleBlock: React.FC<{ g: number; p: ReelProps; paper: string }> = ({ g, p, paper }) => {
  if (g < 420) return null;
  const k = expoOut(ramp(g, 420, 434, Easing.linear));
  const m = 40;
  const x0 = lerp(W - m - 330, m, k), y0 = lerp(H - m - 190, TB_TOP, k), x1 = W - m, y1 = H - m;
  const a = (from: number) => ramp(g, from, from + 7, Easing.linear);
  const L = 110, R = W - 110;
  const nameS = Math.min(124, fitSize(p.business, HEAVY, R - L, 124, -0.02));
  const kickS = fitSize(p.kicker, REG, R - L, 52);
  const ctaS = fitSize(p.cta, MED, R - L - 110, 50), ctaH = 112, ctaW = textWidth(p.cta, MED, ctaS) + 110;
  const siteS = fitSize(p.phone, MONOF, (R - L) * 0.62 - 40, 42);
  const townS = Math.min(30, ((R - L) * 0.38 - 50) / emWidth(p.town.toUpperCase(), MONOF, 0.24));
  const rows = [TB_TOP + 250, TB_TOP + 370, TB_TOP + 560, TB_TOP + 700];   // the rules between the cells
  const cellMid = (top: number, bottom: number, face: Face, size: number) => (top + bottom) / 2 - capOf(face, size) / 2;
  const ctaY = (rows[1] + rows[2]) / 2 - ctaH / 2;
  const mC = metrics(MED);
  const midX = L + (R - L) * 0.62;
  const rule = (i: number) => expoOut(ramp(g, 424 + i * 2, 432 + i * 2, Easing.linear));
  const clip = `inset(${y0.toFixed(1)}px ${(W - x1).toFixed(1)}px ${(H - y1).toFixed(1)}px ${x0.toFixed(1)}px)`;
  return (
    <>
      <div style={{ position: "absolute", left: x0, top: y0, width: x1 - x0, height: y1 - y0, background: paper, border: `5px solid ${INK}`, boxSizing: "border-box", overflow: "hidden",
        boxShadow: "0 20px 60px rgba(0,0,0,.45)" }}>
        <div style={{ position: "absolute", inset: 12, border: `1.6px solid ${INK}` }} />
        <div style={{ position: "absolute", inset: 12, backgroundImage: "linear-gradient(rgba(22,22,26,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(22,22,26,.05) 1px, transparent 1px)", backgroundSize: "20px 20px" }} />
      </div>
      <div style={{ position: "absolute", inset: 0, clipPath: clip }}>
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <g stroke={INK} strokeWidth={2.4}>
            {rows.map((y, i) => <line key={i} x1={m + 12} y1={y} x2={m + 12 + (W - 2 * m - 24) * rule(i)} y2={y} />)}
            <line x1={midX} y1={rows[2]} x2={midX} y2={rows[2] + (rows[3] - rows[2]) * rule(2)} />
          </g>
          {[TB_TOP, ...rows].map((y, i) => <text key={i} x={m + 26} y={y + 34} fill={INK} opacity={0.55 * a(426)} style={{ fontFamily: MONO, fontSize: 22 }}>{`0${i + 1}`}</text>)}
        </svg>
        <Type runs={[{ text: p.business, face: HEAVY }]} size={nameS} capTop={cellMid(TB_TOP, rows[0], HEAVY, nameS) + 12} x={L} track={-0.02} opacity={a(425)} />
        <Type runs={[{ text: p.kicker, face: REG }]} size={kickS} capTop={cellMid(rows[0], rows[1], REG, kickS) + 6} x={L} color="#3A3A40" opacity={a(427)} />
        <div style={{ position: "absolute", left: L, top: ctaY, width: ctaW, height: ctaH, background: p.accent, border: `4px solid ${INK}`, boxSizing: "border-box", transform: `scaleX(${expoOut(ramp(g, 428, 435, Easing.linear))})`, transformOrigin: "0 50%" }} />
        <div style={{ position: "absolute", left: L, width: ctaW, top: ctaY + ctaH / 2 - (mC.base - mC.cap / 2) * ctaS, textAlign: "center", fontFamily: SANS, fontWeight: 650, fontSize: ctaS, lineHeight: 1, color: INK, opacity: a(430), whiteSpace: "nowrap" }}>{p.cta}</div>
        <Type runs={[{ text: p.phone, face: MONOF }]} size={siteS} capTop={cellMid(rows[2], rows[3], MONOF, siteS) + 6} x={L} opacity={a(431)} />
        <Type runs={[{ text: p.town, face: MONOF }]} size={townS} capTop={cellMid(rows[2], rows[3], MONOF, townS) + 6} x={midX + 40} track={0.24} caps opacity={a(432)} />
        <div style={{ position: "absolute", left: 0, top: 0, opacity: a(432) }}>
          <ScaleBar x={L} y={rows[3] + 104} px={110} size={28} paper={paper} />
          <Type runs={[{ text: "1:50", face: MONOF }]} size={30} capTop={rows[3] + 76} x={R - textWidth("1:50", MONOF, 30)} />
        </div>
      </div>
    </>
  );
};

// ------------------------------------------------------------------ the reel

const Defs: React.FC<{ blur: number }> = ({ blur }) => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {/* poché hatching for the sectioned figure: 45° ink lines */}
      <pattern id="sec-hatch" width={26} height={26} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1={0} y1={0} x2={0} y2={26} stroke={INK} strokeWidth={7} />
      </pattern>
      {/* earth, cut: diagonal strokes; gravel under the slab: dots */}
      <pattern id="sec-earth" width={44} height={44} patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
        <line x1={0} y1={0} x2={0} y2={44} stroke={INK} strokeWidth={2.2} />
        <line x1={22} y1={6} x2={22} y2={26} stroke={INK} strokeWidth={2.2} />
      </pattern>
      <pattern id="sec-gravel" width={46} height={40} patternUnits="userSpaceOnUse">
        <circle cx={8} cy={8} r={4} fill={INK} /><circle cx={30} cy={18} r={3} fill={INK} /><circle cx={16} cy={31} r={3.5} fill={INK} /><circle cx={40} cy={36} r={2.5} fill={INK} />
      </pattern>
      <linearGradient id="sec-fade-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" /><stop offset="0.45" stopColor="#fff" /><stop offset="1" stopColor="#000" /></linearGradient>
      <mask id="sec-fade" maskUnits="userSpaceOnUse" x={0} y={3200} width={SW} height={400}><rect x={0} y={3200} width={SW} height={400} fill="url(#sec-fade-g)" /></mask>
      {/* the whip along the table */}
      <filter id="sec-whip" x="-5%" y="0%" width="110%" height="100%"><feGaussianBlur stdDeviation={`${blur.toFixed(2)} 0`} /></filter>
    </defs>
  </svg>
);

export const Section: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Section");
  const g = useCurrentFrame();
  useFontsReady();
  const aspect = shapeOf;
  const geo = buildGeo(p, aspect);
  const keys = keysOf(geo);
  const cam = camAt(keys, g);
  const paper = paperOf(p), cut = cutOf(p);
  // which rooms are up: each on its stop while the camera is still on it (the attic E for the cover, D, then A), then on
  // the whole sheet the word rooms on their beats; all down before the whip. A room seen on its stop stays drawn empty on
  // the whole sheet, so no picture comes back: room A carries the first word drawn empty
  const idx = p.wordPhotos;
  const wordRoom = idx.map((i) => geo.rooms.indexOf(roomOfPhoto(geo, i)));
  const lit = (r: number) => {
    const stop = STOPS.find(([room]) => room === r);
    if (g >= 222 && g < 346) return !stop && wordRoom.includes(r) && g >= WORD_AT[wordRoom.indexOf(r)];
    return stop !== undefined && g >= stop[1] && g < stop[2];
  };
  const speed = Math.abs(camAt(keys, g + 0.5).x - camAt(keys, g - 0.5).x) * cam.s;
  const blur = Math.min(28, Math.max(0, (speed - 12) * 0.4));
  const [A, D] = [geo.rooms[0], geo.rooms[3]];
  return (
    <AbsoluteFill style={{ background: TABLE, overflow: "hidden" }}>
      <Music track={p.music} />
      <Defs blur={blur} />
      <AbsoluteFill style={{ filter: blur > 0.3 ? "url(#sec-whip)" : undefined }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0, transformOrigin: "0 0", transform: `translate(${W / 2}px, ${H / 2}px) scale(${cam.s.toFixed(5)}) translate(${(-cam.x).toFixed(2)}px, ${(-cam.y).toFixed(2)}px)` }}>
          <Sheet1 g={g} p={p} geo={geo} lit={lit} paper={paper} cut={cut} />
          <Paper x={X2} paper={paper}>
            <Exploded g={g} p={p} aspect={aspect} cut={cut} />
            <DetailTitle g={g} p={p} aspect={aspect} />
          </Paper>
        </div>
      </AbsoluteFill>
      <Note g={g} cam={cam} at={72} until={120} n={1} target={[D.x0 + 70, D.y1 + SLAB / 2]} cardY={1400} pair={p.line1} p={p} paper={paper} />
      <Note g={g} cam={cam} at={150} until={196} n={2} target={[A.x0 + 70, A.y0 - SLAB / 2]} cardY={290} pair={p.line2} p={p} paper={paper} />
      <TitleBlock g={g} p={p} paper={paper} />
    </AbsoluteFill>
  );
};
