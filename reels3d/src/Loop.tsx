// Loop, made to match Chris's reelfolio recording (2026-10-23: "look at what you already inspected AGAIN").
// What the recording does, and this does:
// - a regular GRID of same-size cards in straight rows and columns, wide even gaps of flat dark space between them
// - HOLD: the camera settles onto one card and the rest of the grid falls back into the dark (dim slivers of its
//   neighbours); the card itself never leaves the grid (Chris: "it should only magnify in the loop itself"); its label
//   under it on the dark (name, then a smaller line) and a counter at the right
// - MOVE (slow, about a second and a half): the camera rises, banks a little as it travels through the empty space
//   to the next card, a liquid glass oval gliding across the grid and magnifying the photos it passes over, then
//   levels and settles on the next card
// Four cards in fifteen seconds. Photos unlit and exact; the glass is there only while the camera travels.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, PAPER, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number; room?: string};
const ITEMS = wall as Item[];
const FOV = 30, TAN = Math.tan((FOV * Math.PI) / 360), ASPECT = W / H;
const VIEW_W = 2 * TAN * ASPECT;                              // the width in view per unit of camera distance
const CARD_W = 1.5, CARD_H = 2;                               // every card the same shape: 3:4 portrait, as in the recording
const GAP_X = 0.16, GAP_Y = 0.42;                             // a tight grid; the rows a little further apart for the label
const COLS = 9, ROWS = 11;
const PITCH_X = CARD_W + GAP_X, PITCH_Y = CARD_H + GAP_Y;
const Z_HOLD = (CARD_W / 0.6) / VIEW_W;                       // on the hold the card is 60% of the width
const Z_MOVE = (3 * PITCH_X) / VIEW_W;                        // travelling: three columns in view
const BANK = -0.2;                                            // the turn while travelling; level on every hold
const HOLD = 60, MOVE = 42, FIRST = 24;                       // in 30ths of a second: 2 s held, 1.4 s travelling
// the cards visited, in grid cells (col, row), each a step or two from the last so the travel reads
const VISIT: [number, number][] = [[4, 5], [5, 4], [3, 3], [4, 6]];
const ROOM_WORDS: Record<string, [string, string]> = {         // the approved room lines (design_samples.ROOM_WORDS)
  main_stage: ['Main Stage', 'The keynote, from the room.'], the_crowd: ['The Crowd', 'In the moment.'],
  after_dark: ['After Dark', 'After the last session.'], portraits: ['Portraits', 'Speakers and guests, backstage.'],
  expo_floor: ['Expo Floor', 'On the exhibition floor.'], backstage: ['Backstage', 'The minutes before the doors open.'],
};
const words = (it: Item): [string, string] => ROOM_WORDS[it.room || ''] || ['Event Photography', 'In the moment.'];

const cellPos = (c: number, r: number) => new THREE.Vector2((c - (COLS - 1) / 2) * PITCH_X, ((ROWS - 1) / 2 - r) * PITCH_Y);
// which photo sits in each cell: the visited cards take every fifth photo, the rest spread so no photo sits beside itself
const photoAt = (c: number, r: number) => {
  const v = VISIT.findIndex(([vc, vr]) => vc === c && vr === r);
  return v >= 0 ? (v * 5) % ITEMS.length : (c * 7 + r * 11) % ITEMS.length;
};

// Where the camera is and how it is turned at frame f: held over a card, or travelling to the next.
const arrivals = VISIT.map((_, k) => FIRST + k * (HOLD + MOVE));
const cameraAt = (f: number) => {
  const at = VISIT.map(([c, r]) => cellPos(c, r));
  if (f < FIRST) {                                            // the opening: settling down onto the first card
    const t = easeIO(f / FIRST);
    return {xy: at[0], z: Z_MOVE + (Z_HOLD - Z_MOVE) * t, roll: BANK * (1 - t), travel: -1, k: 0};
  }
  let k = 0;
  for (let j = 0; j < arrivals.length; j++) if (f >= arrivals[j] - (j ? MOVE : 0)) k = j;
  const travel = k > 0 ? (f - (arrivals[k] - MOVE)) / MOVE : 1;
  if (travel < 1) {
    const t = easeIO(travel), rise = Math.sin(Math.PI * Math.min(1, travel));
    return {xy: at[k - 1].clone().lerp(at[k], t), z: Z_HOLD + (Z_MOVE - Z_HOLD) * rise, roll: BANK * rise, travel, k};
  }
  return {xy: at[k], z: Z_HOLD, roll: 0, travel: -1, k};
};

const Rig: React.FC<{xy: THREE.Vector2; z: number; roll: number}> = ({xy, z, roll}) => {
  const {camera, gl, scene} = useThree();
  useLayoutEffect(() => {                                     // light for the glass only: the photos are unlit
    const pmrem = new THREE.PMREMGenerator(gl);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    return () => pmrem.dispose();
  }, [gl, scene]);
  useLayoutEffect(() => {
    camera.position.set(xy.x, xy.y, z);
    camera.up.set(Math.sin(roll), Math.cos(roll), 0);
    camera.lookAt(xy.x, xy.y, 0);
    camera.updateProjectionMatrix();
  }, [xy.x, xy.y, z, roll]);
  return null;
};

export const Loop: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, closing} = useFrameInfo(cuts);
  const cells = useMemo(() => Array.from({length: COLS * ROWS}, (_, s) => [s % COLS, Math.floor(s / COLS)] as const), []);
  const cardTex = useMemo(() => (tex ? cells.map(([c, r]) => {
    const k = photoAt(c, r); return coverTex(tex[k], ITEMS[k].w / ITEMS[k].h, CARD_W / CARD_H);
  }) : []), [tex]);
  const cam = cameraAt(f);
  // the hold: in as the camera settles, out before it rises again
  const since = f - arrivals[cam.k], until = (cam.k + 1 < VISIT.length ? arrivals[cam.k + 1] - MOVE : TOTAL - END) - f;
  const held = cam.travel < 0 && !closing ? easeIO(Math.min(1, (since + 14) / 18, (until + 4) / 14)) : 0;
  // the rest of the grid falls back into the dark while a card is held
  const grey = Math.round(255 - (255 - 32) * held);
  const dimmed = `rgb(${grey},${grey},${grey})`;
  let z = cam.z;
  if (closing) z = Z_HOLD + (Z_MOVE * 1.2 - Z_HOLD) * easeIO((f - (TOTAL - END)) / 36);
  const [vc, vr] = VISIT[cam.k];
  const it = ITEMS[photoAt(vc, vr)];
  const [title, line] = words(it);
  const labelOn = cam.travel < 0 && !closing ? Math.min(1, since / 10, until / 8) : 0;
  const px = W / (Z_HOLD * VIEW_W);                           // screen pixels per grid unit on the hold
  const glass = cam.travel > 0.15 && cam.travel < 0.9 ? easeIO((cam.travel - 0.15) / 0.75) : -1;
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: FOV, position: [0, 0, Z_MOVE], near: 0.1, far: 100}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Rig xy={cam.xy} z={z} roll={cam.roll} />
          {cells.map(([c, r], s) => {
            const p = cellPos(c, r);
            return (
              <mesh key={s} position={[p.x, p.y, 0]}>
                <planeGeometry args={[CARD_W, CARD_H]} />
                <meshBasicMaterial map={cardTex[s]} alphaMap={roundedMask()} alphaTest={0.5} toneMapped={false}
                                   color={c === vc && r === vr ? '#ffffff' : dimmed} />
              </mesh>
            );
          })}
          {glass >= 0 && (() => {
            const a = cellPos(...VISIT[cam.k - 1]), b = cellPos(...VISIT[cam.k]);
            const xy = a.clone().lerp(b, glass), swell = Math.sin(Math.PI * glass);
            return (
              <mesh position={[xy.x + 0.5 * (1 - glass), xy.y, 1.4]} scale={[0.7 + 0.25 * swell, 0.9 + 0.2 * swell, 0.4]}
                    rotation={[0, 0, 0.6 - 0.7 * glass]}>
                <sphereGeometry args={[1, 64, 64]} />
                <meshPhysicalMaterial transmission={1} thickness={0.5} roughness={0} ior={1.5} envMapIntensity={0.12}
                                      specularIntensity={0.1} dispersion={1} color="#ffffff" />
              </mesh>
            );
          })()}
        </ThreeCanvas>
      )}
      {labelOn > 0 && (
        <div style={{position: 'absolute', left: W / 2 - (CARD_W / 2) * px, width: CARD_W * px, top: H / 2 + (CARD_H / 2) * px + 18,
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
