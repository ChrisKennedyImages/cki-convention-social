import React from "react";
import { AbsoluteFill, Easing, Img, random, spring, staticFile, useCurrentFrame } from "remotion";
import { FPS, H, Photo, ReelProps, W, ramp } from "../look";
import { Slots, checkSlots, fillerAt, photoAt, shapeOf } from "../slots";
import { ARCHIVO } from "../fonts";
import { Face, emWidth, metrics, useFontsReady } from "../measure";
import { Music } from "../music";

// TITLES: the opening titles of your own film.
// The craft of the master, not his look (Saul Bass):
//   reduce the whole story to one symbol and let everything grow from it (here, a photograph standing on its paper
//   foot: the foot is placed and a picture assembles on it, everything flies in to build it at the climax, and it signs
//   the end title); cut-paper shapes with hand-cut, slightly ragged edges, moving in exact time with the music (every slide
//   lands on a beat or a sixteenth); the Psycho bars (bars sliding across and splitting the frame, type cut into strips
//   and put back together); the fragmented figure (Anatomy of a Murder: a picture in jagged pieces that come together);
//   type that is part of the graphics, set by hand (each letter a little off its neighbours); two flat inks and black.
// Black ground; flat paper in Event Caliber's two colours; Archivo condensed and heavy for the cut letters. Photos stand
// on the black exactly as shot, the paper beside or beneath them.
//
// For Event Caliber (2026-11-08): a photographer's reel, so his pictures are the heroes, clean and whole. Every photo
// is shown at its own full shape (read from the file), its edges clean, so no face is ever cut; nothing is drawn round
// a photo or laid over it, and no paper surrounds one (the windows and mounts of the first version framed his pictures
// on all four sides, which reads as a border drawn round them: now paper touches a picture on one side, its foot, or two
// at the climax, and a picture can open like a window from the line of the faces with no paper left round it); the
// black covers that split off the climax became that opening, and the scissor line round the symbol's window is gone;
// no photo ever grows toward the viewer. The pieces that move are cut so that faces travel whole: the Psycho bars split a picture above and below
// the band where the faces are, and the fragmented picture is cut from a point below the faces. The symbol became the
// photograph on its paper foot. Words arrive once their picture has settled and hold to the cut (two to three seconds for
// the hook and the lines), so the eight bars became seven scenes, still cut on the beat, and the two lines share one.
// His photos render exactly as shot, in their own colour: no black and white, tint, grade or light on any of them (the
// first version showed them in hard black and white); the inks live only in the paper beside them.
//
// 16 s (480 frames) on the 120 BPM grid of 15-frame beats:
//     0-75   the cover: the hook on bars of paper; the hero whole below, standing on a bar; a bar slides across each beat
//    75-150  the Psycho bars: the picture slides in in three bars from alternate sides on the sixteenths; then the two
//            lines, each cut in strips that slide in from alternate sides and lock on the beat
//   150-225  the symbol: a paper foot is placed, bare; above it a picture assembles from five jagged pieces
//   225-285  the number as giant cut paper, three pieces sliding in on the sixteenths; a picture above on the label's
//            bar; the unit on a bar
//   285-345  three pictures on three bars; on each eighth one opens from the line of the faces, its word set on its bar
//   345-420  the climax: every shape flies in and builds the one big symbol, the paper a picture stands on (its side
//            and its foot); the picture opens on it; the marquee set by hand on the foot
//   420-480  the end title: the symbol (a picture on its foot), the name as the film's main title, the kicker, the call on a
//            paper bar, the site, the town (all in by frame 440, then it holds)

// ------------------------------------------------------------------ the world

const BLACK = "#0A0A0B";
const LIGHT = "#F3F3F1";               // light letters where a colour is too dark to carry black
// Every picture once (Chris, 2026-11-08, night: no picture twice in a reel): the post's seven photos are the hero (the
// cover), the three the words go with (the three bars), the climax's, the end title's and the number's (the suite
// fills a photo slot the post had no photo for from the last); the Psycho bars and the symbol each take a filler.
export const SLOTS: Slots = { photos: 7, fillers: 2 };
const HERO = 0, CLIMAX = 4, END = 5, NUMBER = 6;

const CUT: Face = { family: ARCHIVO, weight: 900, stretch: "condensed" };
const CUT_LIGHT: Face = { family: ARCHIVO, weight: 700, stretch: "condensed" };
const STRETCH: Record<string, string> = { expanded: "125%", "semi-expanded": "112.5%", normal: "100%", "semi-condensed": "87.5%", condensed: "75%" };

const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
/** A pop with a little overshoot, from 0 at `at`. */
const pop = (f: number, at: number, damping = 13, stiffness = 200) =>
  f < at ? 0 : spring({ frame: f - at, fps: FPS, config: { damping, stiffness, mass: 0.6 } });
/** A slide that lands exactly on `at` (its last frames on the beat): 1 far away, 0 in place. */
const landing = (f: number, at: number, len = 8) => 1 - ramp(f, at - len, at, expoOut);

/** Black or light on a colour, whichever reads. */
const inkOn = (hex: string) => {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 105 ? BLACK : LIGHT;
};

// ------------------------------------------------------------------ the photographs, whole

type Box = { x: number; y: number; w: number; h: number };
/** A photo at its own shape, as big as fits w x h, centred on (cx, cy). */
const placed = (pic: Photo, w: number, h: number, cx: number, cy: number): Box => {
  const a = shapeOf(pic);                 // its shape from its props (slots.ts)
  const s = w / h > a ? { w: h * a, h } : { w, h: w / a };
  return { x: cx - s.w / 2, y: cy - s.h / 2, ...s };
};

// ------------------------------------------------------------------ cut paper

type Pt = [number, number];
/** A polygon cut by hand: each edge walked in short steps, every step a little off the true line (by up to amp px). */
const ragged = (corners: Pt[], seed: string, amp = 4.5, step = 30): Pt[] => {
  const out: Pt[] = [];
  corners.forEach((a, i) => {
    const b = corners[(i + 1) % corners.length];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    const n = Math.max(1, Math.round(len / step));
    const nx = -dy / (len || 1), ny = dx / (len || 1);
    for (let k = 0; k < n; k++) {
      const j = (random(`${seed}-${i}-${k}`) - 0.5) * 2 * amp * (k === 0 ? 0.5 : 1);
      out.push([a[0] + (b[0] - a[0]) * (k / n) + nx * j, a[1] + (b[1] - a[1]) * (k / n) + ny * j]);
    }
  });
  return out;
};
const rect = (x: number, y: number, w: number, h: number): Pt[] => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
const ptsStr = (pts: Pt[]) => pts.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" ");
const clip = (pts: Pt[]) => `polygon(${pts.map(([a, b]) => `${a.toFixed(1)}px ${b.toFixed(1)}px`).join(", ")})`;

/** A piece of flat paper (screen px), moved by (dx, dy). */
const Sheet: React.FC<{ pts: Pt[]; fill: string; dx?: number; dy?: number }> = ({ pts, fill, dx = 0, dy = 0 }) => (
  <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", transform: dx || dy ? `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px)` : undefined }}>
    <polygon points={ptsStr(pts)} fill={fill} />
  </svg>
);

/** A photo exactly as shot, standing on the ground: whole, at its own shape, in its own colour, its edges clean and
 *  nothing round it. It can open like a window from the line of the faces across the picture (open 0 to 1), and once
 *  open there is no paper left round it. */
const Shot: React.FC<{ pic: Photo; b: Box; open?: number }> = ({ pic, b, open = 1 }) => {
  if (open <= 0.001) return null;
  const line = b.h * Math.min(0.85, Math.max(0.15, pic.fy));
  const top = Math.max(0, line * (1 - open)), bot = Math.max(0, (b.h - line) * (1 - open));
  return (
    <Img src={staticFile(pic.src)} style={{ position: "absolute", left: b.x, top: b.y, width: b.w, height: b.h, objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%`,
      clipPath: open < 1 ? `inset(${top.toFixed(1)}px 0 ${bot.toFixed(1)}px 0)` : undefined, display: "block" }} />
  );
};

/** A piece of a photo, exactly as shot (polygon in screen px, at the photo's place), moved by (dx, dy). */
const Piece: React.FC<{ pic: Photo; b: Box; pts: Pt[]; dx: number; dy: number }> = ({ pic, b, pts, dx, dy }) => (
  <AbsoluteFill style={{ clipPath: clip(pts), transform: `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px)` }}>
    <Img src={staticFile(pic.src)} style={{ position: "absolute", left: b.x, top: b.y, width: b.w, height: b.h, objectFit: "cover", objectPosition: `${pic.fx * 100}% ${pic.fy * 100}%` }} />
  </AbsoluteFill>
);

// ------------------------------------------------------------------ cut letters

/** Width of a line of cut letters (each letter set on its own, so no kerning: measured as drawn). */
const cutWidth = (text: string, face: Face, size: number, track = 0) => [...text].reduce((s, c) => s + emWidth(c, face) * size, 0) + track * size * [...text].length;
const fitCut = (text: string, face: Face, width: number, max: number, track = 0) => Math.min(max, width / Math.max(0.01, cutWidth(text, face, 1, track)));
const capOf = (face: Face, size: number) => metrics(face).cap * size;

/** A line of capitals cut from paper by hand: each letter a hair off true (a deterministic tilt and lift), placed by its
 *  ink (the middle of the capitals on y). `enter(i)` (0 to 1, may overshoot) drops letter i into place. */
const Cut: React.FC<{ text: string; size: number; x: number; y: number; color: string; seed: string; face?: Face; align?: "left" | "center" | "right"; track?: number; enter?: (i: number) => number; jitter?: number }> = ({ text, size, x, y, color, seed, face = CUT, align = "left", track = 0, enter, jitter = 1 }) => {
  const chars = [...text];
  const ws = chars.map((c) => emWidth(c, face) * size);
  const total = ws.reduce((a, b) => a + b, 0) + track * size * chars.length;
  const m = metrics(face);
  const top = y - (m.base - m.cap / 2) * size;
  let cx = align === "left" ? x : align === "center" ? x - total / 2 : x - total;
  return (
    <>
      {chars.map((c, i) => {
        const l = cx;
        cx += ws[i] + track * size;
        const k = enter ? enter(i) : 1;
        if (k <= 0.001 || c === " ") return null;
        const r = (random(`${seed}r${i}`) - 0.5) * 2.8 * jitter, lift = (random(`${seed}y${i}`) - 0.5) * 0.035 * size * jitter;
        const off = 1 - k;
        return (
          <div key={i} style={{ position: "absolute", left: l, top, fontFamily: face.family, fontWeight: face.weight, fontStretch: STRETCH[face.stretch ?? "normal"], fontSize: size, lineHeight: 1, color, whiteSpace: "pre",
            transform: `translateY(${(lift - off * size * 0.55).toFixed(2)}px) rotate(${(r + off * 16).toFixed(3)}deg)`, transformOrigin: "50% 70%", opacity: Math.min(1, k * 3), fontVariantNumeric: "lining-nums" }}>{c}</div>
        );
      })}
    </>
  );
};
/** Letters placed one after another by hand: letter i lands `gap` frames after the one before. */
const byHand = (f: number, at: number, gap = 1.2) => (i: number) => pop(f, at + i * gap, 12, 260);

/** A bar of paper with a line of cut letters on it, the letters cut into `strips` horizontal strips that slide in from
 *  alternate sides and lock together, landing at `lands[i]` (the Psycho bars). */
const StripBar: React.FC<{ f: number; text: string; size: number; y: number; h: number; fill: string; seed: string; lands: number[]; track?: number }> = ({ f, text, size, y, h, fill, seed, lands, track = 0 }) => {
  const n = lands.length;
  if (f < lands[0] - 8) return null;
  return (
    <>
      {lands.map((at, i) => {
        const y0 = y + (h * i) / n, y1 = y + (h * (i + 1)) / n;
        const dx = (i % 2 ? 1 : -1) * 1300 * landing(f, at, 8);
        return (
          <div key={i} style={{ position: "absolute", left: 0, top: 0, width: W, height: H, clipPath: `inset(${(y0 - (i ? 0.5 : 60)).toFixed(1)}px -60px ${(H - y1 - (i < n - 1 ? 0.5 : 60)).toFixed(1)}px -60px)`, transform: `translateX(${dx.toFixed(1)}px)` }}>
            <Sheet pts={ragged(rect(-40, y, W + 80, h), `${seed}bar`, 3.5)} fill={fill} />
            <Cut text={text} size={size} x={W / 2} y={y + h / 2} align="center" color={inkOn(fill)} seed={`${seed}t`} track={track} />
          </div>
        );
      })}
    </>
  );
};

// ------------------------------------------------------------------ the scenes

type Scene = React.FC<{ f: number; p: ReelProps }>;

// 0-75 · the cover: the hook on bars of paper across the black; below it the hero, whole, standing on a bar of paper;
// the bars drift, and on each beat another bar slides across a black margin.
const Opening: Scene = ({ f, p }) => {
  const hero = photoAt(p, HERO);
  const footH = 30;
  const b = placed(hero, 1000, 660, W / 2, H - 70 - footH - 330);
  const a = p.open[0].toUpperCase(), bb = p.open[1].toUpperCase(), sub = p.openSub.toUpperCase();
  const M = 66;
  const sA = fitCut(a, CUT, W - 2 * M, 340), sB = fitCut(bb, CUT, W - 2 * M, 340);
  const hA = capOf(CUT, sA) * 1.4, hB = capOf(CUT, sB) * 1.4;
  const subS = fitCut(sub, CUT, W - 2 * M - 30, 92, 0.03);
  const hC = capOf(CUT, subS) * 2.1;
  const gap = 14;
  const block = hA + hB + hC + 2 * gap;
  const top = Math.max(70, (b.y - 50) / 2 - block / 2 + 30);
  const yA = top, yB = yA + hA + gap, yC = yB + hB + gap;
  const t = f / 75;
  const beats = [
    { at: 15, y: Math.max(20, top - 60), h: 22, fill: p.accent2, from: -1 },
    { at: 30, y: yC + hC + 26, h: 34, fill: p.accent, from: 1 },
    { at: 45, y: b.y + b.h + footH + 20, h: 20, fill: p.accent2, from: -1 },
  ];
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      <Sheet pts={ragged(rect(-40, b.y + b.h, W + 80, footH), "hero-foot", 3)} fill={p.accent} />
      <Shot pic={hero} b={b} />
      {beats.map((bar, i) => f >= bar.at - 8 && (
        <Sheet key={i} pts={ragged(rect(-40, bar.y, W + 80, bar.h), `beat${i}`, 3, 40)} fill={bar.fill} dx={bar.from * (W + 120) * landing(f, bar.at)} />
      ))}
      <Sheet pts={ragged(rect(-40, yA, W + 80, hA), "barA")} fill={p.accent} dx={12 * t} />
      <Cut text={a} size={sA} x={M + 12 * t} y={yA + hA / 2} color={inkOn(p.accent)} seed="hA" />
      <Sheet pts={ragged(rect(-40, yB, W + 80, hB), "barB")} fill={p.accent2} dx={-12 * t} />
      <Cut text={bb} size={sB} x={M - 12 * t} y={yB + hB / 2} color={inkOn(p.accent2)} seed="hB" />
      <Cut text={sub} size={subS} x={M + 8 * t} y={yC + hC / 2} color={p.accent2} seed="hC" track={0.03} />
    </AbsoluteFill>
  );
};

// 75-150 · the Psycho bars: the picture slides in as three bars from alternate sides on the sixteenths (split above and
// below the band where the faces are, so faces travel whole) and locks into one; then line 1 and line 2, each cut into
// strips that slide in from alternate sides and lock on the beat, with their tails.
const Psycho: Scene = ({ f, p }) => {
  const pic = fillerAt(p, 0);
  const b = placed(pic, 1000, 600, W / 2, 60 + 300);
  const fy = Math.min(0.85, Math.max(0.15, pic.fy));
  const cuts = [0, Math.max(0.08, fy - 0.26), Math.min(0.92, fy + 0.3), 1].map((t) => b.y + b.h * t);
  const pieceLands = [2, 5, 8];
  const whole = f >= pieceLands[2];
  const h1 = p.line1[0].toUpperCase(), t1 = p.line1[1].toUpperCase(), h2 = p.line2[0].toUpperCase(), t2 = p.line2[1].toUpperCase();
  const room = H - 50 - (b.y + b.h + 40);
  let hs = Math.min(fitCut(h1, CUT, 960, 330), fitCut(h2, CUT, 960, 330));
  let ts = Math.min(fitCut(t1, CUT, 900, 120, 0.02), fitCut(t2, CUT, 900, 120, 0.02));
  const stackH = (h: number, t: number) => 2 * (capOf(CUT, h) * 1.36 + 10 + capOf(CUT, t) * 1.9) + 30;
  while (hs > 60 && stackH(hs, ts) > room) { hs -= 2; ts = Math.min(ts, hs * 0.42); }
  const hb = capOf(CUT, hs) * 1.36, tb = capOf(CUT, ts) * 1.9;
  const y0 = b.y + b.h + 40 + (room - stackH(hs, ts)) / 2;
  const yH1 = y0, yT1 = yH1 + hb + 10, yH2 = yT1 + tb + 30, yT2 = yH2 + hb + 10;
  const tail = (text: string, y: number, at: number, from: number, seed: string) => f >= at - 8 && (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${(from * 1300 * landing(f, at)).toFixed(1)}px)` }}>
      <Sheet pts={ragged(rect(-40, y, W + 80, tb), `${seed}b`, 3.5)} fill={p.accent} />
      <Cut text={text} size={ts} x={W / 2} y={y + tb / 2} align="center" color={inkOn(p.accent)} seed={seed} track={0.02} />
    </div>
  );
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      {whole ? <Shot pic={pic} b={b} /> : pieceLands.map((at, i) => {
        if (f < at - 8) return null;
        const dx = (i % 2 ? 1 : -1) * (W + 100) * landing(f, at, 8);
        return <Piece key={i} pic={pic} b={b} pts={rect(b.x - 2, cuts[i], b.w + 4, cuts[i + 1] - cuts[i] + 0.5)} dx={dx} dy={0} />;
      })}
      <StripBar f={f} text={h1} size={hs} y={yH1} h={hb} fill={p.accent2} seed="ps1" lands={[13, 16, 19]} />
      {tail(t1, yT1, 22, 1, "ps1t")}
      <StripBar f={f} text={h2} size={hs} y={yH2} h={hb} fill={p.accent2} seed="ps2" lands={[26, 29, 32]} />
      {tail(t2, yT2, 35, -1, "ps2t")}
    </AbsoluteFill>
  );
};

// 150-225 · the symbol: a photograph standing on its paper foot. The foot is placed on the black; above it, on the black,
// a picture assembles from five jagged pieces cut from a point below the faces (Anatomy of a Murder), each sliding in
// from its own side on the sixteenths. The foot is bare: the reel's room list set on it named rooms this picture (a
// filler) does not show (Chris, 2026-11-09: a word over or beside a photo is true of that photo); each room is named on
// the bar beneath its own photo.
const Emblem: Scene = ({ f, p }) => {
  const pic = fillerAt(p, 1);
  const foot = 190;
  const b0 = placed(pic, 900, 600, W / 2, 0);
  const b: Box = { ...b0, y: H / 2 - (b0.h + foot) / 2 };
  const place = pop(f, 0, 14, 170);
  const dy = -700 * (1 - place);
  // the pieces: rays from a point below the faces out to the picture's edge, jagged; the top piece holds the faces
  const c: Pt = [b.x + b.w * pic.fx, b.y + b.h * Math.min(0.9, Math.max(0.15, pic.fy) + 0.36)];
  const angles = [-8, 38, 92, 142, 188].map((a, i) => a + (random(`fa${i}`) - 0.5) * 10);
  const exit = (a: number): Pt => {
    const dx = Math.cos((a * Math.PI) / 180), dyy = Math.sin((a * Math.PI) / 180);
    const ts = [dx > 0 ? (b.x + b.w - c[0]) / dx : dx < 0 ? (b.x - c[0]) / dx : Infinity, dyy > 0 ? (b.y + b.h - c[1]) / dyy : dyy < 0 ? (b.y - c[1]) / dyy : Infinity];
    const t = Math.min(...ts);
    return [c[0] + dx * t, c[1] + dyy * t];
  };
  const P = 2 * (b.w + b.h);
  const per = ([x, y]: Pt) => (Math.abs(y - b.y) < 0.5 ? x - b.x : Math.abs(x - b.x - b.w) < 0.5 ? b.w + (y - b.y) : Math.abs(y - b.y - b.h) < 0.5 ? b.w + b.h + (b.x + b.w - x) : 2 * b.w + b.h + (b.y + b.h - y));
  const corners: Pt[] = [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
  const cuts = angles.map((a, i) => {
    const e = exit(a);
    const nx = -Math.sin((a * Math.PI) / 180), ny = Math.cos((a * Math.PI) / 180);
    const line: Pt[] = [];
    for (let k = 1; k < 7; k++) {
      const t = k / 7, j = (random(`fc${i}${k}`) - 0.5) * 34;
      line.push([c[0] + (e[0] - c[0]) * t + nx * j, c[1] + (e[1] - c[1]) * t + ny * j]);
    }
    return { a, e, line };
  });
  const pieces = cuts.map((cut, i) => {
    const next = cuts[(i + 1) % cuts.length];
    const p0 = per(cut.e), span = (per(next.e) - p0 + P) % P;
    const between = corners.filter((q) => (per(q) - p0 + P) % P < span).sort((u, v) => ((per(u) - p0 + P) % P) - ((per(v) - p0 + P) % P));
    let mid = next.a - cut.a;
    if (mid < 0) mid += 360;
    return { pts: [c, ...cut.line, cut.e, ...between, next.e, ...[...next.line].reverse()] as Pt[], bis: cut.a + mid / 2 };
  });
  const arrive = [10, 13, 16, 19, 22];
  const order = [0, 2, 1, 3, 4];                        // the top piece (the faces) lands last
  const whole = f >= arrive[arrive.length - 1];
  const footW = b.w + 80;
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateY(${dy.toFixed(1)}px)` }}>
        <Sheet pts={ragged(rect(W / 2 - footW / 2, b.y + b.h, footW, foot), "sym-foot", 4.5)} fill={p.accent} />
        {whole ? <Shot pic={pic} b={b} /> : pieces.map((pc, i) => {
          const at = arrive[order.indexOf(i)];
          if (f < at - 9) return null;
          const d = 1500 * landing(f, at, 9);
          return <Piece key={i} pic={pic} b={b} pts={pc.pts} dx={Math.cos((pc.bis * Math.PI) / 180) * d} dy={Math.sin((pc.bis * Math.PI) / 180) * d} />;
        })}
      </div>
    </AbsoluteFill>
  );
};

// 225-285 · the number, cut from paper: a picture at the top, there from the cut (so no head is ever pushed off the
// frame), the label on a bar right under it; the figure in three jagged pieces sliding in from three sides on the
// sixteenths, its cuts showing; the unit on a bar.
const Figure: Scene = ({ f, p }) => {
  const pic = photoAt(p, NUMBER);
  const v = p.counter.value.toUpperCase();
  const label = p.counter.label.toUpperCase(), unit = p.counter.unit.toUpperCase();
  const b = placed(pic, 860, 470, W / 2, 50 + 235);
  const ls = fitCut(label, CUT, 860, 92, 0.04), lb = capOf(CUT, ls) * 2;
  const us = fitCut(unit, CUT, 860, 112, 0.04), ub = capOf(CUT, us) * 1.9;
  const lTop = b.y + b.h;
  const nTopInk = lTop + lb + 60;
  const room = H - 60 - ub - 50 - nTopInk;
  const ns = Math.min(fitCut(v, CUT, 900, 2000), room / metrics(CUT).cap);
  const nCap = capOf(CUT, ns);
  const nY = nTopInk + nCap / 2;
  const uTop = nTopInk + nCap + 50;
  const nW = cutWidth(v, CUT, ns);
  const x0 = W / 2 - nW / 2 - 60, x1 = W / 2 + nW / 2 + 60, y0 = nTopInk - 80, y1 = nTopInk + nCap + 80;
  const cutAt = (frac: number, tilt: number, seed: string): Pt[] => {
    const pts: Pt[] = [];
    for (let k = 0; k <= 10; k++) pts.push([x0 + ((x1 - x0) * k) / 10, y0 + (y1 - y0) * frac + tilt * (k / 10 - 0.5) + (random(`${seed}${k}`) - 0.5) * 34]);
    return pts;
  };
  const c1 = cutAt(0.36, 160, "nc1"), c2 = cutAt(0.68, -140, "nc2");
  const pieces: { pts: Pt[]; from: Pt; at: number }[] = [
    { pts: [[x0, y0 - 400], [x1, y0 - 400], ...[...c1].reverse()], from: [-1, 0], at: 8 },
    { pts: [...c1, ...[...c2].reverse()], from: [1, 0], at: 12 },
    { pts: [...c2, [x1, y1 + 400], [x0, y1 + 400]], from: [0, 1], at: 15 },
  ];
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      <Shot pic={pic} b={b} />
      {pieces.map((pc, i) => {
        if (f < pc.at - 8) return null;
        const far = landing(f, pc.at, 8);
        return (
          <div key={i} style={{ position: "absolute", left: 0, top: 0, width: W, height: H, clipPath: clip(pc.pts), transform: `translate(${(pc.from[0] * 900 * far).toFixed(1)}px, ${(pc.from[1] * 900 * far).toFixed(1)}px)` }}>
            <Cut text={v} size={ns} x={W / 2} y={nY} align="center" color={p.accent2} seed="num" jitter={0.6} />
          </div>
        );
      })}
      {f >= 15 && (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <polyline points={ptsStr(c1)} fill="none" stroke={BLACK} strokeWidth={7} strokeLinejoin="round" />
          <polyline points={ptsStr(c2)} fill="none" stroke={BLACK} strokeWidth={7} strokeLinejoin="round" />
        </svg>
      )}
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${(-1300 * landing(f, 6)).toFixed(1)}px)` }}>
        <Sheet pts={ragged(rect(-40, lTop, W + 80, lb), "nl", 3.5)} fill={p.accent} />
        <Cut text={label} size={ls} x={W / 2} y={lTop + lb / 2} align="center" color={inkOn(p.accent)} seed="nl-t" track={0.04} />
      </div>
      {f >= 12 && (
        <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${(1300 * landing(f, 20)).toFixed(1)}px)` }}>
          <Sheet pts={ragged(rect(-40, uTop, W + 80, ub), "nu", 3.5)} fill={p.accent} />
          <Cut text={unit} size={us} x={W / 2} y={uTop + ub / 2} align="center" color={inkOn(p.accent)} seed="nu-t" track={0.04} />
        </div>
      )}
    </AbsoluteFill>
  );
};

// 285-345 · three pictures, one per word, each standing on its own bar of paper; on each eighth one opens like a window
// from the line of the faces (no paper left round it once it is open) and its word is set by hand on its bar. All three
// stay.
const Apertures: Scene = ({ f, p }) => {
  const idx = p.wordPhotos;
  const words = p.words.map((w) => w.toUpperCase());
  const fills = [p.accent, p.accent2, p.accent];
  const hS = H / 3;
  const ws = Math.min(...words.map((w) => fitCut(w, CUT, 900, 140, 0.02)));
  const wCap = capOf(CUT, ws);
  const barH = wCap * 1.9;
  const winH = hS - 36 - barH - 28;
  const opens = [0, 8, 15];
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      {[0, 1, 2].map((i) => {
        const y = i * hS;
        const pic = photoAt(p, idx[i]);
        const b = placed(pic, W - 140, winH, W / 2, y + 36 + winH / 2);
        const open = ramp(f, opens[i] - 3, opens[i] + 5, expoOut);
        const barIn = landing(f, opens[i] + 2, 8);
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${((i % 2 ? 1 : -1) * 1300 * barIn).toFixed(1)}px)` }}>
              <Sheet pts={ragged(rect(-40, b.y + b.h, W + 80, barH), `ap${i}`, 4)} fill={fills[i]} />
            </div>
            <Shot pic={pic} b={b} open={open} />
            <Cut text={words[i]} size={ws} x={W / 2} y={b.y + b.h + barH / 2} align="center" color={inkOn(fills[i])} seed={`apt${i}`} track={0.02} enter={byHand(f, opens[i] + 5, 1.1)} />
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};

// 345-420 · the climax: every shape flies in from the edges on the sixteenths and they make the one big symbol, the
// paper the photograph stands on (a strip at its side and its foot, two sides only); on the beat the picture opens like
// a window from the line of the faces, whole, with nothing round it; the marquee is set by hand on the foot.
const Climax: Scene = ({ f, p }) => {
  const pic = photoAt(p, CLIMAX);
  const side = 60, foot = 270;
  const b0 = placed(pic, 900, 640, 0, 0);
  const b: Box = { ...b0, x: W / 2 - (b0.w + side) / 2 + side, y: H / 2 - (b0.h + foot) / 2 - 20 };
  const x0 = b.x - side, fy = b.y + b.h, x1 = b.x + b.w, mid = (x0 + x1) / 2;
  // the slabs of the L (a hair of overlap where they meet, so no seam shows)
  const slabs: { pts: Pt[]; from: Pt; at: number }[] = [
    { pts: rect(x0, fy, mid - x0 + 1, foot), from: [-0.4, 1], at: 4 },
    { pts: rect(mid, fy, x1 - mid, foot), from: [1, 0.4], at: 7 },
    { pts: rect(x0, b.y + b.h / 2, side, b.h / 2 + 1), from: [-1, 0.3], at: 10 },
    { pts: rect(x0, b.y, side, b.h / 2 + 1), from: [-1, -0.4], at: 13 },
  ];
  const L = ragged([[x0, b.y], [b.x, b.y], [b.x, fy], [x1, fy], [x1, fy + foot], [x0, fy + foot]], "cl-L", 4.5);
  const built = f >= 13;
  const open = ramp(f, 14, 23, expoOut);
  const word = p.marquee.toUpperCase();
  const ms = fitCut(word, CUT, x1 - x0 - 80, (foot - 60) / metrics(CUT).cap, 0.02);
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      {built ? <Sheet pts={L} fill={p.accent} /> : slabs.map((sl, i) => {
        if (f < sl.at - 9) return null;
        const far = landing(f, sl.at, 9);
        return <Sheet key={i} pts={sl.pts} fill={p.accent} dx={sl.from[0] * 1500 * far} dy={sl.from[1] * 1500 * far} />;
      })}
      <Shot pic={pic} b={b} open={open} />
      <Cut text={word} size={ms} x={mid} y={fy + foot / 2} align="center" color={inkOn(p.accent)} seed="mq" track={0.02} enter={byHand(f, 20, 1.6)} />
    </AbsoluteFill>
  );
};

// 420-480 · the end title: the symbol (a picture standing on its paper foot), the name set as the film's main title
// between two paper rules, the kicker, the call on a paper bar, the site and the town. Everything is in by frame 440,
// then it holds.
const EndTitle: Scene = ({ f, p }) => {
  const pic = photoAt(p, END);
  const name = p.business.toUpperCase();
  const ns = fitCut(name, CUT, 960, 260, 0.02), nCap = capOf(CUT, ns);
  const kick = p.kicker.toUpperCase();
  const ks = fitCut(kick, CUT_LIGHT, 880, 58, 0.12), kCap = capOf(CUT_LIGHT, ks);
  const cta = p.cta.toUpperCase();
  const cs = fitCut(cta, CUT, 760, 92, 0.04), cCap = capOf(CUT, cs);
  const cW = cutWidth(cta, CUT, cs, 0.04) + 120, cH = cCap * 2.1;
  const site = p.phone;
  const ss = fitCut(site, CUT_LIGHT, 860, 80, 0.01), sCap = capOf(CUT_LIGHT, ss);
  const town = p.town.toUpperCase();
  const tws = fitCut(town, CUT_LIGHT, 600, 40, 0.3), tCap = capOf(CUT_LIGHT, tws);
  const b0 = placed(pic, 500, 330, 0, 0);
  const symFoot = 44;                                   // the paper the picture stands on, like the symbol before it
  const symW = b0.w + 60, symH = b0.h + symFoot;
  const block = symH + 110 + nCap + 70 + kCap + 80 + cH + 80 + sCap + 56 + tCap;
  const symY = H / 2 - block / 2;
  const b: Box = { x: W / 2 - b0.w / 2, y: symY, w: b0.w, h: b0.h };
  const nY = symY + symH + 110 + nCap / 2;
  const kY = nY + nCap / 2 + 70 + kCap / 2;
  const cTop = kY + kCap / 2 + 80;
  const sY = cTop + cH + 80 + sCap / 2;
  const tY = sY + sCap / 2 + 56 + tCap / 2;
  const sym = pop(f, 0, 14, 200);
  const ruleA = landing(f, 8, 8), ruleB = landing(f, 10, 8);
  const ctaIn = landing(f, 16, 8);
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateY(${(-260 * (1 - sym)).toFixed(1)}px)` }}>
        <Sheet pts={ragged(rect(W / 2 - symW / 2, b.y + b.h, symW, symFoot), "es", 3, 22)} fill={p.accent} />
        <Shot pic={pic} b={b} />
      </div>
      <Sheet pts={ragged(rect(W / 2 - 300, nY - nCap / 2 - 52, 600, 12), "ra", 2, 40)} fill={p.accent2} dx={-(W + 400) * ruleA} />
      <Sheet pts={ragged(rect(W / 2 - 300, nY + nCap / 2 + 40, 600, 12), "rb", 2, 40)} fill={p.accent2} dx={(W + 400) * ruleB} />
      <Cut text={name} size={ns} x={W / 2} y={nY} align="center" color={p.accent2} seed="en" track={0.02} enter={byHand(f, 2, 0.9)} />
      <Cut text={kick} size={ks} x={W / 2} y={kY} align="center" color={p.accent2} face={CUT_LIGHT} seed="ek" track={0.12} jitter={0.4} enter={() => ramp(f, 10, 15, Easing.linear)} />
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `translateX(${(1300 * ctaIn).toFixed(1)}px)` }}>
        <Sheet pts={ragged(rect(W / 2 - cW / 2, cTop, cW, cH), "ec", 3.5, 26)} fill={p.accent2} />
        <Cut text={cta} size={cs} x={W / 2} y={cTop + cH / 2} align="center" color={inkOn(p.accent2)} seed="ect" track={0.04} />
      </div>
      <Cut text={site} size={ss} x={W / 2} y={sY} align="center" color={p.accent2} face={CUT_LIGHT} seed="esi" track={0.01} jitter={0.4} enter={() => ramp(f, 14, 19, Easing.linear)} />
      <Cut text={town} size={tws} x={W / 2} y={tY} align="center" color={p.accent} face={CUT_LIGHT} seed="et" track={0.3} jitter={0.3} enter={() => ramp(f, 15, 20, Easing.linear)} />
    </AbsoluteFill>
  );
};

const SCENES: { at: number; S: Scene }[] = [
  { at: 0, S: Opening }, { at: 75, S: Psycho }, { at: 150, S: Emblem }, { at: 225, S: Figure }, { at: 285, S: Apertures }, { at: 345, S: Climax }, { at: 420, S: EndTitle },
];

// ------------------------------------------------------------------ over everything

export const Titles: React.FC<ReelProps> = (p) => {
  checkSlots(p, SLOTS, "Titles");
  const g = useCurrentFrame();
  useFontsReady();
  const i = SCENES.reduce((n, s, k) => (g >= s.at ? k : n), 0);
  const { at, S } = SCENES[i];
  return (
    <AbsoluteFill style={{ background: BLACK, overflow: "hidden" }}>
      <Music track={p.music} />
      <S f={g - at} p={p} />
    </AbsoluteFill>
  );
};
