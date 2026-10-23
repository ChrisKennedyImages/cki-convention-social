// Loop, made to match Chris's reelfolio recording (2026-10-23, compared frame by frame against it).
// What the recording does, and this does:
// - a GRID of cards in level rows, every card its own shape (nothing cropped), tight even gaps of flat dark space
// - HOLD: the camera settles onto one card and the rest of the grid falls back into the dark (dim slivers of its
//   neighbours); the card never leaves the grid (Chris: "it should only magnify in the loop itself"); its label
//   under it on the dark (name, then a smaller line) and a counter at the right
// - MOVE (slow, about a second and a half): the camera rises and travels, level, through the grid to the next card,
//   a small clear lens gliding along the way and bending only the picture under it, then settles on the next card
// Four cards in fifteen seconds. Photos unlit and exact; the glass is there only while the camera travels and is
// smaller than any card, so it never rings a photo (Chris: "always avoid the single red line circle or drawing
// around a photo").
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, PAPER, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number; room?: string};
const ITEMS = wall as Item[];
const FOV = 30, TAN = Math.tan((FOV * Math.PI) / 360), ASPECT = W / H;
const VIEW_W = 2 * TAN * ASPECT, VIEW_H = 2 * TAN;             // the width and height in view per unit of camera distance
const ROW_H = 1.5, GAP_X = 0.16, GAP_Y = 0.42;                 // rows of one height; a little more room under for the label
const ROW_W = 15, ROWS = 11;                                   // each row filled to about this width, centred
const PITCH_Y = ROW_H + GAP_Y;
const Z_MOVE = 5 / VIEW_W;                                     // travelling: about three cards across the view
const HOLD = 60, MOVE = 42, FIRST = 24;                        // in 30ths of a second: 2 s held, 1.4 s travelling
const ROOM_WORDS: Record<string, [string, string]> = {         // the approved room lines (design_samples.ROOM_WORDS)
  main_stage: ['Main Stage', 'The keynote, from the room.'], the_crowd: ['The Crowd', 'In the moment.'],
  after_dark: ['After Dark', 'After the last session.'], portraits: ['Portraits', 'Speakers and guests, backstage.'],
  expo_floor: ['Expo Floor', 'On the exhibition floor.'], backstage: ['Backstage', 'The minutes before the doors open.'],
};
const words = (it: Item): [string, string] => ROOM_WORDS[it.room || ''] || ['Event Photography', 'In the moment.'];

// The grid: photos laid row by row in their own shape (aspect kept between 2:3 and 16:9), each row centred, so
// columns fall where they fall, as in the recording; the photos cycle, so none repeats within view.
type Card = {x: number; y: number; w: number; h: number; k: number};
const shape = (it: Item) => Math.min(16 / 9, Math.max(2 / 3, it.w / it.h));
const CARDS: Card[] = (() => {
  const cards: Card[] = [];
  let k = 0;
  for (let r = 0; r < ROWS; r++) {
    const row: Card[] = [];
    let x = 0;
    while (x < ROW_W) {
      const it = ITEMS[k % ITEMS.length], w = ROW_H * shape(it);
      row.push({x: x + w / 2, y: ((ROWS - 1) / 2 - r) * PITCH_Y, w, h: ROW_H, k: k % ITEMS.length});
      x += w + GAP_X; k++;
    }
    const width = x - GAP_X;
    for (const c of row) cards.push({...c, x: c.x - width / 2});
  }
  return cards;
})();
// the cards visited: in the middle rows, each a step or two from the last so the travel reads
const nearest = (r: number, x: number) => CARDS.filter((c) => c.y === ((ROWS - 1) / 2 - r) * PITCH_Y)
  .reduce((a, c) => (Math.abs(c.x - x) < Math.abs(a.x - x) ? c : a));
const VISIT: Card[] = [nearest(5, 0), nearest(4, 1.6), nearest(3, -1.4), nearest(6, 0.8)];
// held, a card is about 60% of the width, or 46% of the height when it is tall
const zFor = (c: Card) => Math.max(c.w / (0.6 * VIEW_W), c.h / (0.46 * VIEW_H));

// Where the camera is at frame f: held over a card, or travelling, level, to the next.
const arrivals = VISIT.map((_, k) => FIRST + k * (HOLD + MOVE));
const cameraAt = (f: number) => {
  if (f < FIRST) {                                            // the opening: settling down onto the first card
    const t = easeIO(f / FIRST), c = VISIT[0];
    return {x: c.x, y: c.y, z: Z_MOVE + (zFor(c) - Z_MOVE) * t, travel: -1, k: 0};
  }
  let k = 0;
  for (let j = 0; j < arrivals.length; j++) if (f >= arrivals[j] - (j ? MOVE : 0)) k = j;
  const travel = k > 0 ? (f - (arrivals[k] - MOVE)) / MOVE : 1;
  const c = VISIT[k];
  if (travel < 1) {
    const a = VISIT[k - 1], t = easeIO(travel), rise = Math.sin(Math.PI * travel);
    const zHeld = zFor(a) + (zFor(c) - zFor(a)) * t;
    return {x: a.x + (c.x - a.x) * t, y: a.y + (c.y - a.y) * t, z: zHeld + (Z_MOVE - zHeld) * rise, travel, k};
  }
  return {x: c.x, y: c.y, z: zFor(c), travel: -1, k};
};

const Rig: React.FC<{x: number; y: number; z: number}> = ({x, y, z}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    camera.position.set(x, y, z);
    camera.up.set(0, 1, 0);
    camera.lookAt(x, y, 0);
    camera.updateProjectionMatrix();
  }, [x, y, z]);
  return null;
};

export const Loop: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, closing} = useFrameInfo(cuts);
  const cardTex = useMemo(() => (tex ? CARDS.map((c) => coverTex(tex[c.k], ITEMS[c.k].w / ITEMS[c.k].h, c.w / c.h)) : []), [tex]);
  const cam = cameraAt(f);
  const card = VISIT[cam.k];
  // the hold: in as the camera settles, out before it rises again
  const since = f - arrivals[cam.k], until = (cam.k + 1 < VISIT.length ? arrivals[cam.k + 1] - MOVE : TOTAL - END) - f;
  const held = cam.travel < 0 && !closing ? easeIO(Math.min(1, (since + 14) / 18, (until + 4) / 14)) : 0;
  // the rest of the grid falls back into the dark while a card is held
  const grey = Math.round(255 - (255 - 32) * held);
  const dimmed = `rgb(${grey},${grey},${grey})`;
  let z = cam.z;
  if (closing) z = zFor(card) + (Z_MOVE * 1.2 - zFor(card)) * easeIO((f - (TOTAL - END)) / 36);
  const [title, line] = words(ITEMS[card.k]);
  const labelOn = cam.travel < 0 && !closing ? Math.min(1, since / 10, until / 8) : 0;
  const px = W / (zFor(card) * VIEW_W);                        // screen pixels per grid unit on the hold
  const glass = cam.travel > 0.15 && cam.travel < 0.9 ? easeIO((cam.travel - 0.15) / 0.75) : -1;
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: FOV, position: [0, 0, Z_MOVE], near: 0.1, far: 100}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Rig x={cam.x} y={cam.y} z={z} />
          <mesh position={[0, 0, -0.02]}>                       {/* the field: a real surface, so the glass sees it */}
            <planeGeometry args={[100, 100]} />
            <meshBasicMaterial color={K} toneMapped={false} />
          </mesh>
          {CARDS.map((c, s) => (
            <mesh key={s} position={[c.x, c.y, 0]}>
              <planeGeometry args={[c.w, c.h]} />
              <meshBasicMaterial map={cardTex[s]} alphaMap={roundedMask()} alphaTest={0.5} toneMapped={false}
                                 color={c === card ? '#ffffff' : dimmed} />
            </mesh>
          ))}
          {glass >= 0 && (() => {
            const a = VISIT[cam.k - 1], b = VISIT[cam.k], swell = Math.sin(Math.PI * glass);
            return (
              <mesh position={[a.x + (b.x - a.x) * glass, a.y + (b.y - a.y) * glass, 1.2]}
                    scale={[0.42 + 0.08 * swell, 0.55 + 0.08 * swell, 0.3]} rotation={[0, 0, 0.5 - 0.6 * glass]}>
                <sphereGeometry args={[1, 64, 64]} />
                <meshPhysicalMaterial transmission={1} thickness={0.35} roughness={0} ior={1.2} envMapIntensity={0}
                                      specularIntensity={0} color="#ffffff" />
              </mesh>
            );
          })()}
        </ThreeCanvas>
      )}
      {labelOn > 0 && (
        <div style={{position: 'absolute', left: W / 2 - (card.w / 2) * px, width: card.w * px, top: H / 2 + (card.h / 2) * px + 18,
                     display: 'flex', justifyContent: 'space-between', color: PAPER, opacity: labelOn}}>
          <div style={{lineHeight: 1.3}}>
            <div style={{fontFamily: 'body', fontSize: 32}}>{title}</div>
            <div style={{fontFamily: 'body', fontSize: 25, color: '#8c8c93'}}>{line}</div>
          </div>
          <div style={{fontFamily: 'mono', fontSize: 22, color: '#8c8c93', paddingTop: 8}}>
            {String(cam.k + 1).padStart(2, '0')} / {String(VISIT.length).padStart(2, '0')}
          </div>
        </div>
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.82)" />}
    </AbsoluteFill>
  );
};
