// Loop, made to match Chris's reelfolio recording exactly (2026-10-23: "make it look exactly as I sent").
// The cycle, on every beat: HOLD on one photo inside a dark rounded card that fills most of the frame, a small
// two-line label at its foot; then the camera PULLS straight up and the card is one tile of a FLAT, slightly tilted
// mosaic of many photos in mixed sizes (no perspective wall); it PANS across while a liquid glass oval glides over
// the mosaic, bending it; then it DIVES into the next card and the oval settles into it. Photos unlit, exact; the
// glass is only there in the move between cards.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {MeshTransmissionMaterial} from '@react-three/drei';
import {useThree} from '@react-three/fiber';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, PAPER, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number; room?: string};
const ITEMS = wall as Item[];
const FOV = 30, TAN = Math.tan((FOV * Math.PI) / 360), ASPECT = W / H;
const ROW_H = 0.95, GAP = 0.09, ROWS = 26, ROW_W = 22;          // the mosaic, in plane units
const TILT = -0.13;                                               // the mosaic's slight turn
const CARD_W = 2.2, INSET = 0.09, LABEL_H = 0.34;                 // a project card on the mosaic
const Z_HOLD = (CARD_W / 0.84) / (2 * TAN * ASPECT);              // the card fills 84% of the width
const Z_PEAK = Z_HOLD * 2.6;                                      // pulled up: the mosaic all round
const MOVE = 26;                                                  // frames (30ths) from one card to the next
const HEROES = [0, 5, 11, 17, 22, 27];                            // which photos get a card, in turn (one per beat)
const ROOM_WORDS: Record<string, [string, string]> = {          // the approved room lines (design_samples.ROOM_WORDS)
  main_stage: ['Main Stage', 'The keynote, from the room.'], the_crowd: ['The Crowd', 'In the moment.'],
  after_dark: ['After Dark', 'After the last session.'], portraits: ['Portraits', 'Speakers and guests, backstage.'],
  expo_floor: ['Expo Floor', 'On the exhibition floor.'], backstage: ['Backstage', 'The minutes before the doors open.'],
};
const label = (it: Item): [string, string] => ROOM_WORDS[it.room || ''] || ['Event Photography', 'In the moment.'];

// The cards' places on the mosaic: a zigzag through its middle, far enough apart that the pan reads.
const CARD_AT = HEROES.map((_, k) => new THREE.Vector2((k % 2 ? 1.7 : -1.7) + (k % 3 - 1) * 0.6, 5.4 - k * 2.6));

const cardSize = (it: Item) => {
  const iw = CARD_W - 2 * INSET, ih = Math.min(iw / (it.w / it.h), iw * 1.25);
  return {iw, ih, ph: INSET + ih + LABEL_H};
};

// Justified rows of tiles (each photo at its own shape), leaving room around every card.
const buildMosaic = () => {
  const tiles: {x: number; y: number; w: number; h: number; k: number}[] = [];
  let n = 0;
  for (let r = 0; r < ROWS; r++) {
    const y = (ROWS / 2 - r) * (ROW_H + GAP);
    let x = -ROW_W / 2 - (r % 3) * 0.37;
    while (x < ROW_W / 2) {
      const k = (n * 7 + r * 3) % ITEMS.length; n++;
      const it = ITEMS[k], w = Math.min(ROW_H * 1.6, Math.max(ROW_H * 0.66, ROW_H * (it.w / it.h)));
      const cx = x + w / 2;
      const clear = CARD_AT.every((c, j) => {
        const s = cardSize(ITEMS[HEROES[j]]);
        return Math.abs(cx - c.x) > (CARD_W + w) / 2 + GAP || Math.abs(y - c.y) > (s.ph + ROW_H) / 2 + GAP;
      });
      if (clear) tiles.push({x: cx, y, w, h: ROW_H, k});
      x += w + GAP;
    }
  }
  return tiles;
};

// Light for the glass only: an environment its surface reflects (a soft studio room). The photos are unlit
// (meshBasicMaterial), so this never touches them.
const GlassLight: React.FC = () => {
  const {gl, scene} = useThree();
  useLayoutEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    return () => pmrem.dispose();
  }, [gl, scene]);
  return null;
};

const Cam: React.FC<{p: THREE.Vector3}> = ({p}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    camera.position.copy(p); camera.lookAt(p.x, p.y, 0); camera.up.set(0, 1, 0); camera.updateProjectionMatrix();
  }, [p.x, p.y, p.z]);
  return null;
};

export const Loop: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, i, closing} = useFrameInfo(cuts);
  const mosaic = useMemo(buildMosaic, []);
  const tileTex = useMemo(() => (tex ? mosaic.map((t) => coverTex(tex[t.k], ITEMS[t.k].w / ITEMS[t.k].h, t.w / t.h)) : []), [tex]);
  const rot = (v: THREE.Vector2) => v.clone().rotateAround(new THREE.Vector2(0, 0), TILT);
  const at = CARD_AT.map(rot);
  // where the camera is: holding over card k, or moving from card k-1 to card k in the MOVE frames before cut k
  const n = Math.min(cuts.length, HEROES.length);
  let k = 0;
  for (let j = 0; j < n; j++) if (f >= cuts[j] - (j ? MOVE : 0)) k = j;
  const arrive = cuts[k], moveT = k > 0 ? (f - (arrive - MOVE)) / MOVE : 1;
  let pos: THREE.Vector3, lens = -1;
  if (f < cuts[0] + 18) {
    const t = easeIO(f / (cuts[0] + 18));                           // the hook: from high above, straight down into card 0
    pos = new THREE.Vector3(at[0].x, at[0].y, Z_PEAK * 1.2 + (Z_HOLD - Z_PEAK * 1.2) * t);
  } else if (moveT < 1) {
    const t = easeIO(Math.max(0, moveT));
    const xy = at[k - 1].clone().lerp(at[k], t);
    pos = new THREE.Vector3(xy.x, xy.y, Z_HOLD + (Z_PEAK - Z_HOLD) * Math.sin(Math.PI * Math.min(1, Math.max(0, moveT))));
    lens = moveT;
  } else {
    const hold = (f - arrive) / Math.max(1, ((k + 1 < n ? cuts[k + 1] - MOVE : TOTAL - END) - arrive));
    pos = new THREE.Vector3(at[k].x, at[k].y, Z_HOLD * (1 - 0.025 * Math.min(1, hold)));
  }
  if (closing) {
    const t = easeIO((f - (TOTAL - END)) / 36);
    pos = pos.clone().lerp(new THREE.Vector3(pos.x, pos.y, Z_PEAK * 1.4), t);
  }
  const holding = !closing && moveT >= 1 && f >= cuts[0] + 18;
  const lab = label(ITEMS[HEROES[k]]);
  const showLabel = holding ? Math.min(1, (f - arrive) / 8) * Math.min(1, ((k + 1 < n ? cuts[k + 1] - MOVE : TOTAL - END) - f) / 8) : 0;
  // the label sits at the card's foot, inside its dark panel: placed from the camera height
  const s = cardSize(ITEMS[HEROES[k]]);
  const pxPerUnit = W / (2 * pos.z * TAN * ASPECT);
  const labelY = H / 2 + (s.ph / 2 - LABEL_H * 0.82) * pxPerUnit;
  const labelX = W / 2 - (CARD_W / 2 - INSET) * pxPerUnit;
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: FOV, position: [0, 0, Z_PEAK], near: 0.1, far: 100}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Cam p={pos} />
          <GlassLight />
          <ambientLight intensity={1} />
          <directionalLight position={[2, 4, 6]} intensity={2.5} />
          <group rotation={[0, 0, TILT]}>
            {mosaic.map((t, j) => (
              <mesh key={j} position={[t.x, t.y, 0]}>
                <planeGeometry args={[t.w, t.h]} />
                <meshBasicMaterial map={tileTex[j]} alphaMap={roundedMask()} alphaTest={0.5} toneMapped={false} />
              </mesh>
            ))}
            {HEROES.slice(0, n).map((h, j) => {
              const it = ITEMS[h], c = CARD_AT[j], cs = cardSize(it);
              return (
                <group key={j} position={[c.x, c.y, 0.01]} rotation={[0, 0, -TILT]}>
                  <mesh>
                    <planeGeometry args={[CARD_W, cs.ph]} />
                    <meshBasicMaterial color="#121214" alphaMap={roundedMask()} alphaTest={0.5} />
                  </mesh>
                  <mesh position={[0, cs.ph / 2 - INSET - cs.ih / 2, 0.005]}>
                    <planeGeometry args={[cs.iw, cs.ih]} />
                    <meshBasicMaterial map={coverTex(tex[h], it.w / it.h, cs.iw / cs.ih)} alphaMap={roundedMask()} alphaTest={0.5} toneMapped={false} />
                  </mesh>
                </group>
              );
            })}
          </group>
          {lens > 0.12 && lens < 0.92 && (() => {
            const t = easeIO(Math.min(1, (lens - 0.12) / 0.8));
            const xy = at[k - 1].clone().lerp(at[k], t);
            const grow = Math.sin(Math.PI * t);
            return (
              <mesh position={[xy.x + 0.3 * (1 - t), xy.y - 0.2, 1.6]} scale={[0.95 + 0.25 * grow, 1.25 + 0.2 * grow, 0.17]}
                    rotation={[0, 0, 0.5 - 0.6 * t]}>
                <sphereGeometry args={[1, 64, 64]} />
                <meshPhysicalMaterial transmission={1} thickness={1.6} roughness={0} ior={1.5} metalness={0} envMapIntensity={0.45}
                                      clearcoat={0} specularIntensity={0.15} dispersion={4} color="#ffffff" />
              </mesh>
            );
          })()}
        </ThreeCanvas>
      )}
      {showLabel > 0 && (
        <div style={{position: 'absolute', left: labelX + 6, top: labelY, color: PAPER, opacity: showLabel, lineHeight: 1.25}}>
          <div style={{fontFamily: 'body', fontSize: 30}}>{lab[0]}</div>
          <div style={{fontFamily: 'body', fontSize: 24, color: '#8c8c93'}}>{lab[1]}</div>
        </div>
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.8)" />}
    </AbsoluteFill>
  );
};
