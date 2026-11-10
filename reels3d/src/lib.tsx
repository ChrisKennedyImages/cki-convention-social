// Shared pieces of the 3D reels: assets that hold the render until they are loaded, timing on the beat, and the
// close every direction ends on. Brand: black, paper white, cyan; Unbounded, JetBrains Mono, Archivo, Inter Tight.
import React, {useEffect, useMemo, useState} from 'react';
import {continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import * as THREE from 'three';
import {Check, Slot, drawnFrom, lit} from './slots';

export const W = 1080, H = 1920, FPS = 30, TOTAL = 450, END = 72;
export const K = '#0a0a0b', PAPER = '#f3f3f1', CYAN = '#00e1ff';

export type Photo = {src: string; room: string; line: string; w: number; h: number};
export type Tile = {src: string; w: number; h: number};                 // a filler: a photo that only fills a slot
// What a reel is made of: the post's photos (named), the beats they turn on, more of Chris's approved photos for the
// style's other slots (Wall's tiles, Loop's cells, Ring's cards: each a picture of its own, exactly as many as the style
// shows), and the track; every path is under the public dir the render is given. `check`: the card check's (slots.ts).
export type Props = {photos: Photo[]; cuts: number[]; fillers: Tile[]; music: string; check?: Check};

export const FONTS: Record<string, string> = {
  display: 'Unbounded-ExtraBold.ttf', mono: 'JetBrainsMono-Medium.ttf', condensed: 'Archivo-XCondBlack.ttf',
  body: 'InterTight-SemiBold.ttf', serif: 'Fraunces-SemiBold.ttf',
};

// Every font in the page before the first frame is taken (a frame drawn in a fallback font is a wrong frame).
export const useFonts = () => {
  const [handle] = useState(() => delayRender('fonts'));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    Promise.all(Object.entries(FONTS).map(async ([family, file]) => {
      const face = new FontFace(family, `url(${staticFile('fonts/' + file)})`);
      await face.load();
      document.fonts.add(face);
    })).then(() => { setReady(true); continueRender(handle); });
  }, [handle]);
  return ready;
};

// The photos as textures, loaded before the first frame.
const useTextures = (srcs: string[]) => {
  const [handle] = useState(() => delayRender('textures'));
  const [tex, setTex] = useState<THREE.Texture[] | null>(null);
  useEffect(() => {
    const loader = new THREE.TextureLoader();
    Promise.all(srcs.map((s) => new Promise<THREE.Texture>((ok, bad) => loader.load(staticFile(s), (t) => {
      t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; ok(t);
    }, undefined, bad)))).then((t) => { setTex(t); continueRender(handle); });
  }, [handle, srcs.join('|')]);
  return tex;
};

// Every picture of the reel as a texture, by its slot: the post's photo i, filler k (a slot the props do not hold stops
// the render). Each place a style draws a slot asks here, so the card check sees every place (slots.ts drawnFrom).
export type Pictures = {photo: (i: number) => THREE.Texture; filler: (k: number) => THREE.Texture};
export const usePictures = (p: Props): Pictures | null => {
  const srcs = useMemo(() => {
    const own = [...p.photos, ...p.fillers].map((x) => x.src);
    return p.check?.codes ? [...own, ...own.map(lit)] : own;
  }, [p]);
  const tex = useTextures(srcs);
  return useMemo(() => {
    if (!tex) return null;
    const bySrc = new Map(srcs.map((s, n) => [s, tex[n]]));
    return {photo: (i: number) => bySrc.get(drawnFrom(p, 'photos', i))!, filler: (k: number) => bySrc.get(drawnFrom(p, 'fillers', k))!};
  }, [tex]);
};

// How much of the frame a flat quad covers from this camera, in pixels: its corners projected, clipped to the frame.
// A style that lays more than the camera ever sees draws only what comes into the frame (Wall's tiles, Loop's cells).
export const pixelsOnScreen = (corners: THREE.Vector3[], camera: THREE.Camera): number => {
  let poly = corners.map((c) => { const v = c.clone().project(camera); return [v.x, v.y]; });
  for (const [axis, sign] of [[0, 1], [0, -1], [1, 1], [1, -1]] as const) {          // Sutherland-Hodgman, edge x/y = +-1
    const inside = (q: number[]) => sign * q[axis] <= 1;
    const cut = (a: number[], b: number[]) => { const t = (sign - a[axis]) / (b[axis] - a[axis]); return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; };
    const kept: number[][] = [];
    poly.forEach((q, n) => {
      const prev = poly[(n + poly.length - 1) % poly.length];
      if (inside(q)) { if (!inside(prev)) kept.push(cut(prev, q)); kept.push(q); }
      else if (inside(prev)) kept.push(cut(prev, q));
    });
    poly = kept;
    if (!poly.length) return 0;
  }
  let twice = 0;
  poly.forEach((q, n) => { const r = poly[(n + 1) % poly.length]; twice += q[0] * r[1] - r[0] * q[1]; });
  return Math.abs(twice) / 2 * (W / 2) * (H / 2);
};
// A slot is drawn where it shows at least this much of the frame at some moment (0.1 %: a sliver at the frame's edge
// smaller than this is never a picture anyone sees, and the card check could not tell it from nothing).
export const SHOWN_PX = 0.001 * W * H;

// A style whose cards come round into the frame again (Orbit's ring, Gallery's room) shows a picture on one of a card's
// passes through the frame only (Chris, 2026-11-08, night: no picture twice in a reel). A pass is a run of the render's
// frames (60 a second: f in 30ths, every half) in which `seen(f)` says, for each card, how much of the frame its face
// fills facing the camera; it holds a picture only if it fills SHOWN_PX at some moment on a frame of the 30-a-second
// timeline (the card check's). Each frame of a card then shows the picture of the pass it is in, or, between passes and out
// of sight, of the pass to come: a face changes only where no one sees it.
export type Pass = {from: number; to: number; most: number};     // frames as f * 2; the most pixels the face filled
export const passesOf = (cards: number, seen: (f: number) => number[]): Pass[][] => {
  const passes: Pass[][] = Array.from({length: cards}, () => []);
  for (let s = 0; s < TOTAL * 2; s++) {
    seen(s / 2).forEach((px, k) => {
      if (px <= 0) return;
      const p = passes[k], last = p[p.length - 1];
      const most = s % 2 === 0 ? px : 0;
      if (last && last.to === s - 1) { last.to = s; last.most = Math.max(last.most, most); } else p.push({from: s, to: s, most});
    });
  }
  return passes;
};
export const holdsPicture = (p: Pass) => p.most >= SHOWN_PX;
export const facesOf = (passes: Pass[][], pictureOf: (k: number, pass: number) => Slot | null): (Slot | null)[][] =>
  passes.map((ps, k) => {
    const given = ps.map((_, n) => pictureOf(k, n));
    return Array.from({length: TOTAL * 2}, (_, s) => { const n = ps.findIndex((p) => s <= p.to); return n < 0 ? null : given[n]; });
  });
export const faceAt = (faces: (Slot | null)[][], k: number, f: number) => faces[k][Math.min(TOTAL * 2 - 1, Math.max(0, Math.round(f * 2)))];
// the frame a card's own photo holds at: the middle of its beat
export const holdOf = (cuts: number[], k: number) => (cuts[k] + (k + 1 < cuts.length ? cuts[k + 1] : TOTAL - END)) / 2;
export const passAt = (ps: Pass[], f: number) => ps.findIndex((p) => p.from <= f * 2 && f * 2 <= p.to);

// Which photo is on at frame f, and how far into its time we are (0 to 1).
export const segmentAt = (cuts: number[], f: number) => {
  const edges = [...cuts, TOTAL - END];
  let i = 0;
  for (let k = 0; k < cuts.length; k++) if (f >= cuts[k]) i = k;
  const a = edges[i], b = edges[i + 1];
  return {i, a, b, local: Math.min(1, Math.max(0, (f - a) / Math.max(1, b - a)))};
};

export const ease = (t: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
export const easeIO = (t: number) => { t = Math.min(1, Math.max(0, t)); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
export const pop = (t: number, k = 1.7) => { t = Math.min(1, Math.max(0, t)); return 1 + (k + 1) * Math.pow(t - 1, 3) + k * Math.pow(t - 1, 2); };
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// A small camera shake that never repeats the same way twice: a held camera, not a wobble.
export const handheld = (f: number, amp = 0.02) => [
  amp * (Math.sin(f * 0.13) + 0.5 * Math.sin(f * 0.37 + 1.3)),
  amp * (Math.sin(f * 0.11 + 2.1) + 0.5 * Math.sin(f * 0.29)),
];

// Words on top of the 3D picture, in the safe area (clear of Instagram's bar, caption and buttons). They arrive only
// once the shot has settled and leave before it moves: a word never flickers across a cut (Chris, 2026-10-23).
export const Label: React.FC<{room: string; line: string; index: number; count: number; f: number; a: number; b: number; dark?: boolean}> =
  ({room, line, index, count, f, a, b, dark}) => {
  // in as the shot lands, out just before the next move: about two and a half seconds to read (Chris, 2026-10-23:
  // "less then half a second which make it impossible to read")
  const settle = 8, leave = 6;
  const inT = easeIO((f - a - settle) / 10), outT = easeIO((f - (b - leave - 8)) / 8);
  const o = Math.max(0, inT - outT);
  if (o <= 0) return null;
  const ink = dark ? K : PAPER;
  return (
    <div style={{position: 'absolute', left: 80, right: 180, top: 1290, color: ink, opacity: o,
                 transform: `translateY(${(1 - inT) * 26 - outT * 14}px)`}}>
      <div style={{fontFamily: 'mono', fontSize: 28, letterSpacing: 6, color: dark ? K : CYAN}}>
        {String(index + 1).padStart(2, '0')} / {String(count).padStart(2, '0')}
      </div>
      <div style={{fontFamily: 'display', fontSize: 70, lineHeight: 1.05, marginTop: 12}}>{room}</div>
      <div style={{fontFamily: 'body', fontSize: 34, marginTop: 16}}>{line}</div>
    </div>
  );
};

// A photo exactly as shot: no light, no tone mapping, nothing over it (Chris, 2026-10-23: "NEVER EVER NEVER put
// anything over an image that involves any burst of light"). Rounded corners come from an alpha mask, not a frame.
export const roundedMask = (() => {
  let tex: THREE.CanvasTexture | null = null;
  return () => {
    if (tex) return tex;
    const c = document.createElement('canvas'); c.width = 512; c.height = 512;
    const g = c.getContext('2d')!; g.fillStyle = '#000'; g.fillRect(0, 0, 512, 512);
    g.fillStyle = '#fff'; const r = 28; g.beginPath(); g.roundRect(0, 0, 512, 512, r); g.fill();
    tex = new THREE.CanvasTexture(c); return tex;
  };
})();

// A texture cropped to a card of aspect `card` (cover, centred), sharing the loaded image.
export const coverTex = (t: THREE.Texture, photoAspect: number, card: number) => {
  const c = t.clone(); c.needsUpdate = true;
  if (photoAspect > card) { c.repeat.set(card / photoAspect, 1); c.offset.set((1 - card / photoAspect) / 2, 0); }
  else { c.repeat.set(1, photoAspect / card); c.offset.set(0, (1 - photoAspect / card) / 2); }
  return c;
};

// The close: the name, the ask, the address. The same words on every direction; the look is the direction's own.
export const Close: React.FC<{f: number; field?: string; ink?: string}> = ({f, field = K, ink = PAPER}) => {
  const t = (f - (TOTAL - END)) / END;
  const s = pop(t * 2.2);
  return (
    <div style={{position: 'absolute', inset: 0, background: field, display: 'flex', flexDirection: 'column',
                 alignItems: 'center', justifyContent: 'center', opacity: ease(t * 5)}}>
      <div style={{fontFamily: 'display', fontSize: 84, color: ink, whiteSpace: 'nowrap', transform: `scale(${s})`}}>EVENT CALIBER.</div>
      <div style={{marginTop: 70, padding: '22px 40px', background: field === CYAN ? K : CYAN, color: field === CYAN ? PAPER : K,
                   fontFamily: 'mono', fontSize: 42,
                   letterSpacing: 4, opacity: ease((t - 0.3) * 4), transform: `translateY(${30 * (1 - ease((t - 0.3) * 4))}px)`}}>
        REQUEST A QUOTE
      </div>
      <div style={{marginTop: 36, fontFamily: 'mono', fontSize: 34, color: ink, opacity: ease((t - 0.45) * 4)}}>eventcaliber.com</div>
    </div>
  );
};

// Time is counted in 30ths of a second whatever the render rate, so a 60 fps render is the same reel, twice as smooth.
export const useFrameInfo = (cuts: number[]) => {
  const {fps} = useVideoConfig();
  const f = useCurrentFrame() * (30 / fps);
  return useMemo(() => ({f, ...segmentAt(cuts, f), closing: f >= TOTAL - END}), [f, cuts.join(',')]);
};
