// Ring: on clean paper white, one photo appears and the ring unspools card by card, turning slowly around a small
// EVENT CALIBER; then it opens and the cards cascade past the camera at different depths, each at its full shape,
// to rest on one hero photo (reference: Chris's reelfolio "Viscose" recording, 2026-10-23). Photos unlit, exact;
// the only shade is a soft shadow on the paper behind each card. Every card is a picture of its own (Chris, 2026-11-08,
// night: no picture twice in a reel): the post's photos, then fillers until the ring is full.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, END, H, K, PAPER, Props, TOTAL, W, coverTex, easeIO, pixelsOnScreen, roundedMask, useFonts, useFrameInfo, usePictures} from './lib';
import {checkFillers, fillerAt, photoAt, reportPresence} from './slots';

const VFOV = 40, CAM_Z = 9, R = 1.5, CARD = 0.34;
/** The cards on the ring: the post's photos, then a filler each (render/reels3d.PICTURES says the same). */
export const PICTURES = 30;
const UNSPOOL = 120, OPEN_AT = 230, HERO_AT = 330;   // frames (at 30 a second): the ring is whole by 4 s, opens at 7.7 s
const OPENING = 50, FALL = 0.028;                    // the ring opens over 50 frames; the cascade falls this far a frame
const HERO = 0;                                      // the cascade rests on the post's first photo
const DEPTH = [0.6, -1.4, -3.2];                     // the cascade's three columns, at different depths
const placeIn = (k: number) => (k * 0.9) % 14;       // a card's place in its column's fall, the columns' cards spread over 14
// The cascade falls once (Chris, 2026-11-08, night: no picture twice in a reel; #76 showed a panel photo at 8.7 s and
// again at 12.7 s, its card taken round from the bottom of its column to the top): nothing is taken round, and each
// column starts its fall with its highest card inside the frame once the ring has opened (its middle INSIDE below the
// top edge, whatever the photo's shape), so no card rises out of the top and falls back in.
const INSIDE = 0.5;
const COLUMN_TOP = DEPTH.map((depth, col) => {
  const top = (CAM_Z - depth) * Math.tan((VFOV * Math.PI) / 360);
  let highest = Infinity;
  for (let k = col; k < PICTURES; k += 3) highest = Math.min(highest, placeIn(k));
  return Math.min(7, top - INSIDE + OPENING * FALL + highest);
});

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

const viewH = 2 * CAM_Z * Math.tan((VFOV * Math.PI) / 360), viewW = viewH * (W / H);
// Card k (of aspect w / h) at frame f: where it is, how it is turned, its size, and null before it is born.
const cardAt = (k: number, aspect: number, f: number) => {
  // ring: each card travels in along the ring's path from the right, in turn
  const born = easeIO((f - (k * UNSPOOL) / PICTURES) / 26);
  if (born <= 0) return null;
  const open = easeIO((f - OPEN_AT) / OPENING), hero = easeIO((f - HERO_AT) / 40);
  const ang = (k / PICTURES) * Math.PI * 2 + f * 0.004 - (1 - born) * 1.1;
  const ring = new THREE.Vector3(Math.cos(ang) * R, Math.sin(ang) * R, 0);
  // cascade: three columns falling past at different depths; each card at its full shape
  const col = k % 3;
  const fall = (f - OPEN_AT) * FALL + placeIn(k);
  const cas = new THREE.Vector3([-1.25, 1.35, 0.1][col], COLUMN_TOP[col] - fall, DEPTH[col]);
  let pos = ring.clone().lerp(cas, open);
  const tilt = [0.12, -0.16, 0.08][col];
  let rot = new THREE.Euler(0, open * tilt * 2, (ang + Math.PI / 2) * (1 - open) + tilt * open);
  let w = CARD + (1.6 - CARD) * open, h = CARD + (1.6 / aspect - CARD) * open;
  if (hero > 0) {
    if (k === HERO) {
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
  return {pos, rot, w, h, open, hero};
};
// whether card k is inside the frame at frame f, whatever covers it (for the card check)
const inFrame = (k: number, aspect: number, f: number, cam: THREE.Camera) => {
  const c = cardAt(k, aspect, f);
  if (!c) return false;
  const m = new THREE.Matrix4().compose(c.pos, new THREE.Quaternion().setFromEuler(c.rot), new THREE.Vector3(1, 1, 1));
  return pixelsOnScreen([[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => new THREE.Vector3((x * c.w) / 2, (y * c.h) / 2, 0).applyMatrix4(m)), cam) > 0;
};

const Cam: React.FC = () => {
  const {camera} = useThree();
  useLayoutEffect(() => { camera.position.set(0, 0, CAM_Z); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix(); }, []);
  return null;
};

export const Ring: React.FC<Props> = (p) => {
  const {photos, cuts, music} = p;
  checkFillers(p, PICTURES - photos.length, 'Ring');
  useFonts();
  // the post's photos first, then a filler each until the ring is full
  const n = photos.length;
  const items = useMemo(() => Array.from({length: PICTURES}, (_, k) => (k < n ? photoAt(p, k) : fillerAt(p, k - n))), [p]);
  const pics = usePictures(p);
  const texOf = (k: number) => (k < n ? pics!.photo(k) : pics!.filler(k - n));
  const {f, closing} = useFrameInfo(cuts);
  const squares = useMemo(() => (pics ? items.map((it, k) => coverTex(texOf(k), it.w / it.h, 1)) : []), [pics]);
  useMemo(() => {
    const cam = new THREE.PerspectiveCamera(VFOV, W / H, 0.1, 60);
    cam.position.set(0, 0, CAM_Z); cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
    reportPresence(p, items.map((it, k) => ({kind: k < n ? 'photos' as const : 'fillers' as const, index: k < n ? k : k - n,
      inFrame: Array.from({length: TOTAL}, (_, f) => inFrame(k, it.w / it.h, f, cam))})));
  }, [p]);
  return (
    <AbsoluteFill style={{background: PAPER}}>
      <Audio src={staticFile(music)} />
      {pics && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, CAM_Z], near: 0.1, far: 60}} gl={{antialias: true}}>
          <color attach="background" args={[PAPER]} />
          <Cam />
          {items.map((it, k) => {
            const c = cardAt(k, it.w / it.h, f);
            if (!c) return null;
            const {pos, rot, w, h, open, hero} = c;
            const isHero = k === HERO;
            const card = open > 0.02 ? coverTex(texOf(k), it.w / it.h, w / h) : squares[k];
            return (
              <group key={k} position={pos} rotation={rot}>
                <mesh position={[0.05, -0.08, -0.02]} scale={[1.25, 1.25, 1]}>
                  <planeGeometry args={[w, h]} />
                  <meshBasicMaterial map={shadowTex()} transparent depthWrite={false} opacity={0.55} />
                </mesh>
                {/* cards overlap on the ring and in a column at one depth: each a step of depth over the one before, so
                    the later card lies cleanly over the earlier (they had fought for the same pixels in stripes) */}
                <mesh renderOrder={isHero ? 3 : 1}>
                  <planeGeometry args={[w, h]} />
                  <meshBasicMaterial map={card} alphaMap={roundedMask()} transparent toneMapped={false} depthTest={!isHero || hero <= 0}
                                     polygonOffset polygonOffsetFactor={0} polygonOffsetUnits={-4 * (k + 1)} />
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
