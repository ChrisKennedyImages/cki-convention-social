// Wall: a tilted wall of Chris's photos drifts past the camera; on every beat one of the post's photos lifts out of
// the wall, turns to face the camera at its full shape (never cropped), holds, and settles back as the next one
// rises. One continuous move, no cuts, no words until the close. Chris, 2026-10-23: "I do still like the wall one
// you created", kept beside Loop (Loop.tsx). Photos unlit, exact. Every tile that comes into the frame is a picture of
// its own (Chris, 2026-11-08, night: no picture twice in a reel): the hero tiles the post's photos, the rest fillers. A
// tile holds its picture on its first pass through the frame only: one that drifts out and comes back into view when the
// camera backs away for the close stays dark, as Orbit's cards do (2026-11-09).
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, END, H, K, Props, SHOWN_PX, TOTAL, W, coverTex, easeIO, pixelsOnScreen, roundedMask, useFonts, useFrameInfo, usePictures} from './lib';
import {checkFillers, fillerAt, photoAt, reportPresence} from './slots';

const COLS = 9, ROWS = 11, TW = 0.9, TH = 0.62, GAP = 0.08, VFOV = 40, CAM_Z = 8, HERO_Z = 3.4;
const TILE_ASPECT = TW / TH;
const HEROES = [4 * COLS + 4, 5 * COLS + 3, 4 * COLS + 5, 6 * COLS + 4, 5 * COLS + 5, 6 * COLS + 3];
const WALL_ROT = new THREE.Euler(-0.38, 0.24, 0.14);

const slotLocal = (slot: number) => {
  const c = slot % COLS, r = Math.floor(slot / COLS);
  return new THREE.Vector3((c - (COLS - 1) / 2) * (TW + GAP), ((ROWS - 1) / 2 - r) * (TH + GAP), 0);
};
// where the wall stands at frame f, and the camera, which backs away for the close
const wallAt = (f: number) => {
  const drift = f / TOTAL;
  return {pos: new THREE.Vector3(0.55 - 1.1 * drift, -0.45 + 0.9 * drift, 0),
          q: new THREE.Quaternion().setFromEuler(new THREE.Euler(WALL_ROT.x, WALL_ROT.y, WALL_ROT.z + 0.04 * Math.sin(f / 90)))};
};
const camZ = (f: number) => CAM_Z + 2.2 * easeIO((f - (TOTAL - END)) / 40);

// How much of the frame each tile fills at every frame of the render (60 a second, f * 2), the close's pull back
// included, whatever covers it: the wall is wider than the frame.
const SEEN: number[][] = Array.from({length: TOTAL * 2}, (_, n) => {
  const f = n / 2, cam = new THREE.PerspectiveCamera(VFOV, W / H, 0.1, 50);
  cam.position.set(0, 0, camZ(f)); cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
  const {pos, q} = wallAt(f);
  return Array.from({length: COLS * ROWS}, (_, s) => {
    const c = slotLocal(s);
    return pixelsOnScreen([[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) =>
      new THREE.Vector3(c.x + (x * TW) / 2, c.y + (y * TH) / 2, 0).applyQuaternion(q).add(pos)), cam);
  });
});
// Each tile's first pass through the frame: where it ends (f * 2; -1 for a tile never in the frame) and the most of the
// frame it fills in it. A tile is drawn in its first pass only, and takes a picture only if it then fills SHOWN_PX: a tile
// never seen, or seen as a sliver smaller than that, takes none.
const FIRST_PASS = Array.from({length: COLS * ROWS}, (_, s) => {
  let end = -1, most = 0;
  for (let n = 0; n < SEEN.length; n++) {
    if (SEEN[n][s] > 0) { end = n; most = Math.max(most, SEEN[n][s]); }
    else if (end >= 0) break;
  }
  return {end, most};
});
const SHOWN: number[] = FIRST_PASS.flatMap(({most}, s) => (most >= SHOWN_PX ? [s] : []));
/** Every picture the wall shows: the post's photos on the hero tiles, a filler on each other tile that comes into the
 *  frame (render/reels3d.PICTURES says the same). */
export const PICTURES = 63;
if (SHOWN.length !== PICTURES || HEROES.some((s) => !SHOWN.includes(s))) {
  throw new Error(`the wall shows ${SHOWN.length} tiles, the hero tiles among them; PICTURES says ${PICTURES}`);
}

const Cam: React.FC<{f: number}> = ({f}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    camera.position.set(0, 0, camZ(f)); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

export const Wall: React.FC<Props> = (p) => {
  const {photos, cuts, music} = p;
  if (photos.length > HEROES.length) throw new Error(`the wall lifts ${HEROES.length} photos; the props hold ${photos.length}`);
  checkFillers(p, PICTURES - photos.length, 'Wall');
  useFonts();
  const pics = usePictures(p);
  const {f, closing} = useFrameInfo(cuts);
  // the hero tiles hold the post's photos, in order; every other tile in the frame a filler of its own, in turn
  const slots = useMemo(() => {
    let k = 0;
    return SHOWN.map((s) => {
      const hero = HEROES.indexOf(s);
      return hero >= 0 && hero < photos.length ? {s, kind: 'photos' as const, index: hero} : {s, kind: 'fillers' as const, index: k++};
    });
  }, [p]);
  useMemo(() => reportPresence(p, slots.map(({s, kind, index}) => ({kind, index,
    inFrame: Array.from({length: TOTAL}, (_, f) => 2 * f <= FIRST_PASS[s].end && SEEN[2 * f][s] > 0)}))), [p]);
  const tiles = useMemo(() => (pics ? slots.map(({s, kind, index}) => {
    const it = kind === 'photos' ? photoAt(p, index) : fillerAt(p, index);
    return {s, tex: coverTex(kind === 'photos' ? pics.photo(index) : pics.filler(index), it.w / it.h, TILE_ASPECT)};
  }) : []), [pics]);
  const {pos: wallPos, q: wallQ} = wallAt(f);
  const out = (k: number) => {
    const a = cuts[k], next = k + 1 < cuts.length ? cuts[k + 1] : TOTAL - END;
    return Math.max(0, easeIO((f - a) / 22) - easeIO((f - (next - 6)) / 22));
  };
  const viewH = 2 * (CAM_Z - HERO_Z) * Math.tan((VFOV * Math.PI) / 360), viewW = viewH * (W / H);
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile(music)} />
      {pics && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, CAM_Z], near: 0.1, far: 50}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Cam f={f} />
          <group position={wallPos} quaternion={wallQ}>
            {tiles.map(({s, tex}) => {
              const k = HEROES.indexOf(s);
              if (k >= 0 && k < cuts.length && out(k) > 0) return null;
              if (Math.round(f * 2) > FIRST_PASS[s].end) return null;          // gone from the frame once: it stays dark
              return (
                <mesh key={s} position={slotLocal(s)}>
                  <planeGeometry args={[TW, TH]} />
                  <meshBasicMaterial map={tex} alphaMap={roundedMask()} transparent toneMapped={false} />
                </mesh>
              );
            })}
          </group>
          {HEROES.slice(0, cuts.length).map((slot, k) => {
            const o = out(k);
            if (o <= 0) return null;
            const it = photoAt(p, k), aspect = it.w / it.h;
            const from = slotLocal(slot).applyQuaternion(wallQ).add(wallPos);
            const pos = from.clone().lerp(new THREE.Vector3(0, 0.25, HERO_Z), o);
            const q = wallQ.clone().slerp(new THREE.Quaternion(), o);
            const fullW = aspect >= 1 ? viewW * 0.92 : viewH * 0.62 * aspect;
            const w = TW + (fullW - TW) * o, h = TH + (fullW / aspect - TH) * o;
            return (
              <mesh key={k} position={pos} quaternion={q} renderOrder={2}>
                <planeGeometry args={[w, h]} />
                <meshBasicMaterial map={coverTex(pics.photo(k), aspect, w / h)} alphaMap={roundedMask()} transparent
                                   toneMapped={false} depthTest={false} />
              </mesh>
            );
          })}
        </ThreeCanvas>
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.78)" />}
    </AbsoluteFill>
  );
};
