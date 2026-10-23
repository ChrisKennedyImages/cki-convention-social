// Ring: on clean paper white, one photo appears and the ring unspools card by card, turning slowly around a small
// EVENT CALIBER; then it opens and the cards cascade past the camera at different depths, each at its full shape,
// to rest on one hero photo (reference: Chris's reelfolio "Viscose" recording, 2026-10-23). Photos unlit, exact;
// the only shade is a soft shadow on the paper behind each card.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, PAPER, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number};
const ITEMS = wall as Item[];
const N = ITEMS.length, VFOV = 40, CAM_Z = 9, R = 1.5, CARD = 0.34;
const UNSPOOL = 120, OPEN_AT = 230, HERO_AT = 330;   // frames (at 30 a second): the ring is whole by 4 s, opens at 7.7 s
const HERO = 4;                                      // which photo the cascade rests on

const shadowTex = (() => {
  let t: THREE.CanvasTexture | null = null;
  return () => {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d')!; const grd = g.createRadialGradient(64, 64, 10, 64, 64, 64);
    grd.addColorStop(0, 'rgba(0,0,0,0.35)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128); t = new THREE.CanvasTexture(c); return t;
  };
})();

const Cam: React.FC = () => {
  const {camera} = useThree();
  useLayoutEffect(() => { camera.position.set(0, 0, CAM_Z); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix(); }, []);
  return null;
};

export const Ring: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, closing} = useFrameInfo(cuts);
  const squares = useMemo(() => (tex ? ITEMS.map((it, k) => coverTex(tex[k], it.w / it.h, 1)) : []), [tex]);
  const spin = f * 0.004;
  const open = easeIO((f - OPEN_AT) / 50);
  const hero = easeIO((f - HERO_AT) / 40);
  const viewH = 2 * CAM_Z * Math.tan((VFOV * Math.PI) / 360), viewW = viewH * (W / H);
  return (
    <AbsoluteFill style={{background: PAPER}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, CAM_Z], near: 0.1, far: 60}} gl={{antialias: true}}>
          <color attach="background" args={[PAPER]} />
          <Cam />
          {ITEMS.map((it, k) => {
            // ring: each card travels in along the ring's path from the right, in turn
            const born = easeIO((f - (k * UNSPOOL) / N) / 26);
            if (born <= 0) return null;
            const ang = (k / N) * Math.PI * 2 + spin - (1 - born) * 1.1;
            const ring = new THREE.Vector3(Math.cos(ang) * R, Math.sin(ang) * R, 0);
            // cascade: two columns falling past at different depths; each card at its full shape
            const col = k % 3, depth = [0.6, -1.4, -3.2][col];
            const fall = ((f - OPEN_AT) * 0.028 + k * 0.9) % 14;
            const cas = new THREE.Vector3([-1.25, 1.35, 0.1][col], 7 - fall, depth);
            let pos = ring.clone().lerp(cas, open);
            let rot = new THREE.Euler(0, 0, ang + Math.PI / 2);
            const tilt = [0.12, -0.16, 0.08][col];
            rot = new THREE.Euler(0, open * tilt * 2, (ang + Math.PI / 2) * (1 - open) + tilt * open);
            const aspect = it.w / it.h;
            let w = CARD + (1.6 - CARD) * open, h = CARD + (1.6 / aspect - CARD) * open;
            const isHero = k === HERO;
            if (hero > 0) {
              if (isHero) {
                // the hero comes to the front at its full shape: 90% of the width (a wide photo) or 60% of the height
                const z = 1.2, wAtZ = viewW * (CAM_Z - z) / CAM_Z, hAtZ = viewH * (CAM_Z - z) / CAM_Z;
                const fw = aspect >= 1 ? wAtZ * 0.9 : hAtZ * 0.6 * aspect;
                pos = pos.lerp(new THREE.Vector3(0, 0.3, z), hero);
                rot = new THREE.Euler(rot.x * (1 - hero), rot.y * (1 - hero), rot.z * (1 - hero));
                w = w + (fw - w) * hero; h = w / aspect;
              } else {
                pos = pos.clone().add(new THREE.Vector3(0, -10 * hero * hero, 0));
              }
            }
            const card = open > 0.02 ? coverTex(tex[k], aspect, w / h) : squares[k];
            return (
              <group key={k} position={pos} rotation={rot}>
                <mesh position={[0.05, -0.08, -0.02]} scale={[1.25, 1.25, 1]}>
                  <planeGeometry args={[w, h]} />
                  <meshBasicMaterial map={shadowTex()} transparent depthWrite={false} opacity={0.55} />
                </mesh>
                <mesh renderOrder={isHero ? 3 : 1}>
                  <planeGeometry args={[w, h]} />
                  <meshBasicMaterial map={card} alphaMap={roundedMask()} transparent toneMapped={false} depthTest={!isHero || hero <= 0} />
                </mesh>
              </group>
            );
          })}
        </ThreeCanvas>
      )}
      {!closing && (
        <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
                     fontFamily: 'mono', fontSize: 30, letterSpacing: 8, color: K,
                     opacity: Math.max(0, easeIO((f - 70) / 30) - easeIO((f - OPEN_AT) / 20))}}>EVENT CALIBER</div>
      )}
      {closing && <Close f={f} field="rgba(243,243,241,0.9)" ink={K} />}
    </AbsoluteFill>
  );
};
