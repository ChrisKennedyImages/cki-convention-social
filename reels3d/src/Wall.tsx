// Wall: a tilted wall of Chris's photos drifts past the camera; on every beat one photo lifts out of the wall, turns
// to face the camera at its full shape (never cropped), holds, and settles back as the next one rises. One continuous
// move, no cuts, no words until the close. Chris, 2026-10-23: "I do still like the wall one you created", kept beside
// Loop (Loop.tsx). Photos unlit, exact.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number};
const ITEMS = wall as Item[];
const COLS = 9, ROWS = 11, TW = 0.9, TH = 0.62, GAP = 0.08, VFOV = 40, CAM_Z = 8, HERO_Z = 3.4;
const TILE_ASPECT = TW / TH;
const photoOf = (slot: number) => (slot * 7 + Math.floor(slot / COLS) * 3) % ITEMS.length;
const HEROES = [4 * COLS + 4, 5 * COLS + 3, 4 * COLS + 5, 6 * COLS + 4, 5 * COLS + 5, 6 * COLS + 3];
const WALL_ROT = new THREE.Euler(-0.38, 0.24, 0.14);

const slotLocal = (slot: number) => {
  const c = slot % COLS, r = Math.floor(slot / COLS);
  return new THREE.Vector3((c - (COLS - 1) / 2) * (TW + GAP), ((ROWS - 1) / 2 - r) * (TH + GAP), 0);
};

const Cam: React.FC<{f: number}> = ({f}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    const back = easeIO((f - (TOTAL - END)) / 40);
    camera.position.set(0, 0, CAM_Z + 2.2 * back); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

export const Wall: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, closing} = useFrameInfo(cuts);
  const tiles = useMemo(() => (tex ? Array.from({length: COLS * ROWS}, (_, s) => {
    const it = ITEMS[photoOf(s)];
    return coverTex(tex[photoOf(s)], it.w / it.h, TILE_ASPECT);
  }) : []), [tex]);
  const drift = f / TOTAL;
  const wallPos = new THREE.Vector3(0.55 - 1.1 * drift, -0.45 + 0.9 * drift, 0);
  const wallQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(WALL_ROT.x, WALL_ROT.y, WALL_ROT.z + 0.04 * Math.sin(f / 90)));
  const out = (k: number) => {
    const a = cuts[k], next = k + 1 < cuts.length ? cuts[k + 1] : TOTAL - END;
    return Math.max(0, easeIO((f - a) / 22) - easeIO((f - (next - 6)) / 22));
  };
  const viewH = 2 * (CAM_Z - HERO_Z) * Math.tan((VFOV * Math.PI) / 360), viewW = viewH * (W / H);
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, CAM_Z], near: 0.1, far: 50}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Cam f={f} />
          <group position={wallPos} quaternion={wallQ}>
            {tiles.map((t, s) => {
              const k = HEROES.indexOf(s);
              if (k >= 0 && out(k) > 0) return null;
              return (
                <mesh key={s} position={slotLocal(s)}>
                  <planeGeometry args={[TW, TH]} />
                  <meshBasicMaterial map={t} alphaMap={roundedMask()} transparent toneMapped={false} />
                </mesh>
              );
            })}
          </group>
          {HEROES.slice(0, cuts.length).map((slot, k) => {
            const o = out(k);
            if (o <= 0) return null;
            const it = ITEMS[photoOf(slot)], aspect = it.w / it.h;
            const from = slotLocal(slot).applyQuaternion(wallQ).add(wallPos);
            const pos = from.clone().lerp(new THREE.Vector3(0, 0.25, HERO_Z), o);
            const q = wallQ.clone().slerp(new THREE.Quaternion(), o);
            const fullW = aspect >= 1 ? viewW * 0.92 : viewH * 0.62 * aspect;
            const w = TW + (fullW - TW) * o, h = TH + (fullW / aspect - TH) * o;
            return (
              <mesh key={k} position={pos} quaternion={q} renderOrder={2}>
                <planeGeometry args={[w, h]} />
                <meshBasicMaterial map={coverTex(tex[photoOf(slot)], aspect, w / h)} alphaMap={roundedMask()} transparent
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
