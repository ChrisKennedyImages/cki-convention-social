// Loop (Chris's favourite, his first reelfolio recording, 2026-10-23): a tilted wall of his photos scrolls past
// without end; one photo sits in front at its full shape; on every beat a liquid glass lens slides across, bending
// the wall and the photo behind it, and the next photo grows out of the lens. The glass is there only while it
// passes: nothing stays on a photo after it (the rule: no light or effect left over an image). Photos unlit, exact.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {MeshTransmissionMaterial} from '@react-three/drei';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import wall from './wall.json';
import {Close, END, H, K, TOTAL, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

type Item = {src: string; w: number; h: number};
const ITEMS = wall as Item[];
const COLS = 11, ROWS = 14, TW = 0.9, TH = 0.62, GAP = 0.08, VFOV = 40, CAM_Z = 8, HERO_Z = 3.6;
const PITCH_X = TW + GAP, PITCH_Y = TH + GAP;
const SPAN_X = COLS * PITCH_X, SPAN_Y = ROWS * PITCH_Y;
const TILE_ASPECT = TW / TH;
const photoOf = (slot: number) => (slot * 7 + Math.floor(slot / COLS) * 3) % ITEMS.length;
const HEROES = [3, 11, 17, 22, 26, 8];                 // which photos come to the front, in turn
const WALL_Q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.4, 0.26, 0.16));
const LENS = 22;                                      // frames (30ths of a second) the lens takes to cross

const wrap = (v: number, span: number) => ((((v + span / 2) % span) + span) % span) - span / 2;

const Cam: React.FC<{f: number}> = ({f}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    const back = easeIO((f - (TOTAL - END)) / 40);
    camera.position.set(0, 0, CAM_Z + 1.8 * back); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

export const Wall: React.FC<{cuts: number[]}> = ({cuts}) => {
  useFonts();
  const tex = useTextures(ITEMS.map((p) => p.src));
  const {f, i, a, closing} = useFrameInfo(cuts);
  const tiles = useMemo(() => (tex ? Array.from({length: COLS * ROWS}, (_, s) => {
    const it = ITEMS[photoOf(s)];
    return coverTex(tex[photoOf(s)], it.w / it.h, TILE_ASPECT);
  }) : []), [tex]);
  // the loop: the wall scrolls up and across at a steady pace; tiles that leave one edge come back at the other
  const scrollX = -f * 0.006, scrollY = f * 0.011;
  const viewH = 2 * (CAM_Z - HERO_Z) * Math.tan((VFOV * Math.PI) / 360), viewW = viewH * (W / H);
  // the photo in front: the current beat's; the first one rises out of the wall at the start
  const heroIdx = HEROES[i % HEROES.length];
  const it = ITEMS[heroIdx], aspect = it.w / it.h;
  const fullW = aspect >= 1 ? viewW * 0.9 : viewH * 0.6 * aspect, fullH = fullW / aspect;
  const grow = i === 0 ? easeIO((f - a) / 20) : easeIO((f - a) / 14);
  const start = i === 0 ? 0.25 : 0.5;
  const hw = fullW * (start + (1 - start) * grow), hh = hw / aspect;
  const leave = closing ? easeIO((f - (TOTAL - END)) / 24) : 0;
  // the lens: crosses the frame centred on each cut after the first, right to left, a little high to low
  const lensT = i > 0 ? (f - (a - LENS / 2)) / LENS : -1;
  const next = i + 1 < cuts.length ? cuts[i + 1] : -999;
  const nextT = (f - (next - LENS / 2)) / LENS;
  const t = lensT >= 0 && lensT <= 1 ? lensT : nextT >= 0 && nextT <= 1 ? nextT : -1;
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0, CAM_Z], near: 0.1, far: 50}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          <Cam f={f} />
          <ambientLight intensity={1} />
          <group quaternion={WALL_Q}>
            {tiles.map((tile, s) => {
              const c = s % COLS, r = Math.floor(s / COLS);
              const x = wrap((c - (COLS - 1) / 2) * PITCH_X + scrollX, SPAN_X);
              const y = wrap(((ROWS - 1) / 2 - r) * PITCH_Y + scrollY, SPAN_Y);
              return (
                <mesh key={s} position={[x, y, 0]}>
                  <planeGeometry args={[TW, TH]} />
                  <meshBasicMaterial map={tile} alphaMap={roundedMask()} transparent toneMapped={false} />
                </mesh>
              );
            })}
          </group>
          {!closing || leave < 1 ? (
            <mesh position={[0, 0.2, HERO_Z]} scale={1 - 0.15 * leave} renderOrder={2}>
              <planeGeometry args={[hw, hh]} />
              <meshBasicMaterial map={tex[heroIdx]} alphaMap={roundedMask()} transparent opacity={1 - leave}
                                 toneMapped={false} depthTest={false} />
            </mesh>
          ) : null}
          {t >= 0 && (
            <mesh position={[2.6 - 5.2 * easeIO(t), 0.55 - 0.7 * easeIO(t), HERO_Z + 0.6]} scale={[1.05, 1.05, 0.38]}
                  rotation={[0.2, -0.4 + 0.8 * t, 0.3]} renderOrder={3}>
              <sphereGeometry args={[1, 64, 64]} />
              <MeshTransmissionMaterial transmission={1} thickness={0.9} roughness={0.02} ior={1.35} chromaticAberration={0.035}
                                        anisotropicBlur={0.05} distortion={0.15} distortionScale={0.3} temporalDistortion={0}
                                        samples={8} resolution={1024} backside={false} color="#ffffff" />
            </mesh>
          )}
        </ThreeCanvas>
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.8)" />}
    </AbsoluteFill>
  );
};
