// C: Orbit. The photos are thick cards on a tilted ring that spins in fast for the hook; on every beat the ring turns
// the next card to the front and it slides forward to fill the frame, the others glowing at their edges behind it
// (reference: KAMI Circuit, Vercel's studio film).
import React, {useLayoutEffect} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, CYAN, H, K, Label, Props, TOTAL, END, W, easeIO, handheld, useFonts, useFrameInfo, useTextures} from './lib';

const R = 3, CARD_H = 1.3, THICK = 0.06, VFOV = 36, CAM_Z = 12;
// the front card comes forward until it fills 95% of the frame's width
const TAN_H = Math.tan((VFOV * Math.PI) / 360) * (1080 / 1920);
const fillAt = (w: number) => CAM_Z - (w / 2) / TAN_H / 0.95;

const Cam: React.FC<{f: number; closing: boolean}> = ({f, closing}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    const [hx, hy] = handheld(f, 0.02);
    const t = closing ? easeIO((f - (TOTAL - END)) / 30) : 0;
    camera.position.set(hx, 0.6 + hy + 3.2 * t, CAM_Z + 4 * t);
    camera.lookAt(0, 0.2, 0);
    camera.updateProjectionMatrix();
  }, [f, closing]);
  return null;
};

export const Orbit: React.FC<Props> = (props) => {
  useFonts();
  const tex = useTextures(props.photos.map((p) => p.src));
  const {f, i, a, b, local, closing} = useFrameInfo(props.cuts);
  const n = props.photos.length, step = (Math.PI * 2) / n;
  // the ring's turn: card i to the front, eased on each cut; the hook spins it in from a full turn and a half
  const turnTo = (k: number) => -k * step;
  const t = easeIO(Math.min(1, (f - a) / 18));
  let angle = i > 0 ? turnTo(i - 1) + (turnTo(i) - turnTo(i - 1)) * t : turnTo(0);
  if (f < props.cuts[0] + 20) angle = turnTo(0) + Math.PI * 3 * (1 - easeIO(f / (props.cuts[0] + 20)));
  if (closing) angle += ((f - (TOTAL - END)) / END) * 0.9;
  // the front card comes out of the ring to fill the frame while it holds
  const out = closing ? 0 : easeIO(Math.min(1, (f - a - 6) / 16)) * (1 - easeIO(Math.max(0, (local - 0.88) / 0.12)));
  const p = props.photos[i];
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile('music.mp4')} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0.6, CAM_Z], near: 0.1, far: 80}}
                     gl={{antialias: true, toneMapping: THREE.ACESFilmicToneMapping}}>
          <color attach="background" args={[K]} />
          <fog attach="fog" args={[K, 11, 26]} />
          <ambientLight intensity={0.25} />
          <directionalLight position={[3, 5, 6]} intensity={1.6} />
          <Cam f={f} closing={closing} />
          <group rotation={[0.24 * (1 - out), 0, -0.06 * (1 - out)]}>
            <group rotation={[0, angle, 0]}>
              {props.photos.map((ph, k) => {
                const w = CARD_H * (ph.w / ph.h);
                const front = k === i ? out : 0;
                const ang = k * step;
                const r = R + front * Math.max(0, fillAt(w) - R);
                return (
                  <group key={k} position={[Math.sin(ang) * r, 0.2 * front, Math.cos(ang) * r]} rotation={[0, ang, 0]}
                         scale={1}>
                    <mesh>
                      <boxGeometry args={[w, CARD_H, THICK]} />
                      <meshStandardMaterial attach="material-0" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-1" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-2" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-3" color="#111" metalness={0.9} roughness={0.25} />
                      <meshBasicMaterial attach="material-4" map={tex[k]} toneMapped={false} />
                      <meshStandardMaterial attach="material-5" color="#0d0d0f" roughness={0.6} />
                    </mesh>
                  </group>
                );
              })}
            </group>
          </group>
        </ThreeCanvas>
      )}
      {!closing && f >= props.cuts[0] && (
        <Label room={p.room} line={p.line} index={i} count={n} f={f} a={a + 8} b={b} />
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.82)" />}
    </AbsoluteFill>
  );
};
