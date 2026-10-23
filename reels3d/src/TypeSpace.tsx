// B: Type in Space. Each room's word is built of stacked layers (real thickness), slams in on a flat colour field and
// turns in space; on the beat it breaks apart, the letters fly past the camera and the photo opens behind them
// (reference: the CLAUDE motion reel, "WHAT IF").
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, CYAN, H, K, PAPER, Props, W, ease, easeIO, handheld, pop, useFonts, useFrameInfo, useTextures} from './lib';

const FIELDS = [CYAN, '#ff5c29', K, PAPER, CYAN, K];
const INK = (field: string) => (field === K ? PAPER : K);
const LAYERS = 30;
const VFOV = 40, DIST = 6;
const VIEW_H = 2 * DIST * Math.tan((VFOV * Math.PI) / 360), VIEW_W = VIEW_H * (W / H);

type Glyph = {tex: THREE.CanvasTexture; w: number; h: number; x: number};

// One texture per letter, so the word can break apart; widths measured in the browser with the real font.
const glyphsFor = (word: string, color: string): {glyphs: Glyph[]; width: number} => {
  const px = 520, c = document.createElement('canvas'), g = c.getContext('2d')!;
  g.font = `${px}px condensed`;
  const widths = [...word].map((ch) => g.measureText(ch).width);
  const total = widths.reduce((s, x) => s + x, 0);
  const scale = (VIEW_W * 0.9) / total;
  let x = -total * scale / 2;
  const glyphs = [...word].map((ch, k) => {
    const cv = document.createElement('canvas');
    cv.width = Math.ceil(widths[k]) + 8; cv.height = Math.ceil(px * 1.2);
    const cg = cv.getContext('2d')!;
    cg.font = `${px}px condensed`; cg.fillStyle = color; cg.textBaseline = 'alphabetic';
    cg.fillText(ch, 4, px * 0.98);
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    const w = cv.width * scale, h = cv.height * scale;
    const gl: Glyph = {tex, w, h, x: x + w / 2};
    x += widths[k] * scale;
    return gl;
  });
  return {glyphs, width: total * scale};
};

const Word: React.FC<{word: string; color: string; f: number; a: number; b: number}> = ({word, color, f, a, b}) => {
  const {glyphs} = useMemo(() => glyphsFor(word, color), [word, color]);
  const slam = pop((f - a) / 8);
  const burstAt = a + Math.floor((b - a) * 0.5);
  const burst = easeIO((f - burstAt) / 14);
  const depth = 0.012 + 0.022 * Math.min(1, slam);
  return (
    <group position={[0, 0.2, (1 - Math.min(1, slam)) * 4]} rotation={[0.05 * Math.sin(f / 40), 0.28 * Math.sin((f - a) / 34), 0]}>
      {glyphs.map((gph, k) => {
        const spread = (k - (glyphs.length - 1) / 2) / glyphs.length;
        const fly: [number, number, number] = [gph.x + spread * 9 * burst, (k % 2 ? 1 : -1) * 3 * burst * burst, 7.5 * burst];
        return (
          <group key={k} position={fly} rotation={[burst * (k % 2 ? 1.4 : -1.1), burst * spread * 3, burst * spread * 2]}>
            {Array.from({length: LAYERS}, (_, l) => (
              <mesh key={l} position={[0, 0, -l * depth]}>
                <planeGeometry args={[gph.w, gph.h]} />
                <meshBasicMaterial map={gph.tex} transparent alphaTest={0.4} depthWrite
                                   color={l === 0 ? '#ffffff' : new THREE.Color(color).multiplyScalar(0.55 - l * 0.01).getStyle()} />
              </mesh>
            ))}
          </group>
        );
      })}
    </group>
  );
};

const Cam: React.FC<{f: number}> = ({f}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    const [hx, hy] = handheld(f, 0.03);
    camera.position.set(hx, hy, DIST); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

export const TypeSpace: React.FC<Props> = (props) => {
  const fontsReady = useFonts();
  const tex = useTextures(props.photos.map((p) => p.src));
  const {f, i, a, b, closing} = useFrameInfo(props.cuts);
  const p = props.photos[i], field = FIELDS[i % FIELDS.length];
  const word = p.room.split(' ').slice(-1)[0];
  const burstAt = a + Math.floor((b - a) * 0.5);
  const open = easeIO((f - burstAt) / 16);
  // the photo fills the frame once the word has gone: it covers the view at its depth, growing as it opens
  const ph = tex ? (() => {
    const r = p.w / p.h, cover = Math.max(VIEW_W / r, VIEW_H) * 1.06;
    return {w: cover * r, h: cover};
  })() : null;
  return (
    <AbsoluteFill style={{background: field}}>
      <Audio src={staticFile('music.mp4')} />
      {fontsReady && tex && ph && !closing && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, DIST], near: 0.1, far: 60}}>
          <color attach="background" args={[field]} />
          <Cam f={f} />
          <mesh position={[0, 0, -1.6 + 1.6 * open]} scale={0.25 + 0.75 * open}>
            <planeGeometry args={[ph.w, ph.h]} />
            <meshBasicMaterial map={tex[i]} transparent opacity={ease((f - burstAt + 4) / 6)} />
          </mesh>
          <Word word={word} color={INK(field) === K ? '#0a0a0b' : '#f3f3f1'} f={f} a={a} b={b} />
        </ThreeCanvas>
      )}
      {!closing && (
        <div style={{position: 'absolute', left: 80, top: 260, fontFamily: 'mono', fontSize: 32, letterSpacing: 6,
                     color: open > 0.6 ? PAPER : INK(field)}}>
          {String(i + 1).padStart(2, '0')}  {p.room}
        </div>
      )}
      {!closing && open > 0.7 && (
        <div style={{position: 'absolute', left: 0, right: 0, top: 1440, padding: '26px 80px', background: field,
                     color: INK(field), fontFamily: 'body', fontSize: 38, opacity: ease((open - 0.7) * 4)}}>{p.line}</div>
      )}
      {closing && <Close f={f} field={CYAN} ink={K} />}
    </AbsoluteFill>
  );
};
