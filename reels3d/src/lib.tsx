// Shared pieces of the 3D reels: assets that hold the render until they are loaded, timing on the beat, and the
// close every direction ends on. Brand: black, paper white, cyan; Unbounded, JetBrains Mono, Archivo, Inter Tight.
import React, {useEffect, useMemo, useState} from 'react';
import {continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import * as THREE from 'three';

export const W = 1080, H = 1920, FPS = 30, TOTAL = 450, END = 72;
export const K = '#0a0a0b', PAPER = '#f3f3f1', CYAN = '#00e1ff';

export type Photo = {src: string; room: string; line: string; w: number; h: number};
export type Tile = {src: string; w: number; h: number};                 // a photo that only fills a wall or a grid
// What a reel is made of: the post's photos (named), the beats they turn on, other approved photos to fill a wall or a
// grid around them (Wall, Loop, Ring), and the track; every path is under the public dir the render is given.
export type Props = {photos: Photo[]; cuts: number[]; grid: Tile[]; music: string};

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
export const useTextures = (srcs: string[]) => {
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
