// C: Orbit. The photos are thick cards on a tilted ring that spins in fast for the hook; on every beat the ring turns
// the next card to the front and it slides forward to fill the frame, the others glowing at their edges behind it
// (reference: KAMI Circuit, Vercel's studio film). No picture twice (Chris, 2026-11-08, night; his choice for Orbit,
// 2026-11-09): the spin turns every card past the front once or twice before its beat, and the close backs away from a
// ring whose cards come round again. So a card shows its photo on its pass at its beat only; each pass of the spin before
// it shows a filler of its own, and a pass after it nothing, the face left dark. The motion is as approved.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, H, K, Label, Props, TOTAL, END, W, easeIO, faceAt, facesOf, handheld, holdOf, holdsPicture, passAt, passesOf,
        pixelsOnScreen, segmentAt, useFonts, useFrameInfo, usePictures} from './lib';
import {Slot, checkFillers, photoAt} from './slots';

const R = 3, CARD_H = 1.3, THICK = 0.06, VFOV = 36, CAM_Z = 12;
// the front card comes forward until it fills 95% of the frame's width
const TAN_H = Math.tan((VFOV * Math.PI) / 360) * (1080 / 1920);
const fillAt = (w: number) => CAM_Z - (w / 2) / TAN_H / 0.95;

const camAt = (f: number) => {
  const [hx, hy] = handheld(f, 0.02);
  const t = f >= TOTAL - END ? easeIO((f - (TOTAL - END)) / 30) : 0;
  return new THREE.Vector3(hx, 0.6 + hy + 3.2 * t, CAM_Z + 4 * t);
};
const Cam: React.FC<{f: number}> = ({f}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    camera.position.copy(camAt(f));
    camera.lookAt(0, 0.2, 0);
    camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

// the ring at frame f: the card at the front (i), its turn, and how far the front card has come out of it
const ringAt = (cuts: number[], f: number) => {
  const {i, a, local} = segmentAt(cuts, f);
  const closing = f >= TOTAL - END, step = (Math.PI * 2) / cuts.length;
  // the ring's turn: card i to the front, eased on each cut; the hook spins it in from a full turn and a half
  const turnTo = (k: number) => -k * step;
  const t = easeIO(Math.min(1, (f - a) / 18));
  let angle = i > 0 ? turnTo(i - 1) + (turnTo(i) - turnTo(i - 1)) * t : turnTo(0);
  if (f < cuts[0] + 20) angle = turnTo(0) + Math.PI * 3 * (1 - easeIO(f / (cuts[0] + 20)));
  if (closing) angle += ((f - (TOTAL - END)) / END) * 0.9;
  // the front card comes out of the ring to fill the frame while it holds
  const out = closing ? 0 : easeIO(Math.min(1, (f - a - 6) / 16)) * (1 - easeIO(Math.max(0, (local - 0.88) / 0.12)));
  return {i, angle, out, step};
};
// card k's place on the ring (in the ring's turn), w wide
const cardAt = (k: number, w: number, ring: ReturnType<typeof ringAt>) => {
  const front = k === ring.i ? ring.out : 0, ang = k * ring.step;
  const r = R + front * Math.max(0, fillAt(w) - R);
  return {pos: new THREE.Vector3(Math.sin(ang) * r, 0.2 * front, Math.cos(ang) * r), ang};
};

// Every card's passes through the frame, its face toward the camera (render the same math as the JSX below), and what each
// shows: its photo on the pass at its beat, a filler of its own on each pass before it that holds a picture, in the order
// they come, nothing on the others.
const plan = (cuts: number[], widths: number[]) => {
  const cam = new THREE.PerspectiveCamera(VFOV, W / H, 0.1, 80);
  const passes = passesOf(widths.length, (f) => {
    cam.position.copy(camAt(f)); cam.lookAt(0, 0.2, 0); cam.updateMatrixWorld();
    const ring = ringAt(cuts, f);
    const tilt = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0.24 * (1 - ring.out), 0, -0.06 * (1 - ring.out)))
      .multiply(new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0, ring.angle, 0)));
    return widths.map((w, k) => {
      const {pos, ang} = cardAt(k, w, ring);
      const m = tilt.clone().multiply(new THREE.Matrix4().compose(pos, new THREE.Quaternion().setFromEuler(new THREE.Euler(0, ang, 0)), new THREE.Vector3(1, 1, 1)));
      const face = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => new THREE.Vector3((x * w) / 2, (y * CARD_H) / 2, THICK / 2).applyMatrix4(m));
      const toward = new THREE.Vector3(0, 0, 1).transformDirection(m).dot(cam.position.clone().sub(new THREE.Vector3(0, 0, THICK / 2).applyMatrix4(m))) > 0;
      return toward ? pixelsOnScreen(face, cam) : 0;
    });
  });
  const beat = passes.map((ps, k) => {
    const n = passAt(ps, holdOf(cuts, k));
    if (n < 0) throw new Error(`Orbit's card ${k} is not in the frame at its own beat`);
    return n;
  });
  const flashes = passes.flatMap((ps, k) => ps.slice(0, beat[k]).flatMap((p, n) => (holdsPicture(p) ? [{k, n, from: p.from}] : [])))
    .sort((x, y) => x.from - y.from || x.k - y.k);
  const faces = facesOf(passes, (k, n): Slot | null => {
    if (n === beat[k]) return {kind: 'photos', index: k};
    const flash = flashes.findIndex((x) => x.k === k && x.n === n);
    return flash >= 0 ? {kind: 'fillers', index: flash} : null;
  });
  return {faces, fillers: flashes.length};
};

export const Orbit: React.FC<Props> = (props) => {
  const widths = useMemo(() => props.photos.map((_, k) => { const ph = photoAt(props, k); return CARD_H * (ph.w / ph.h); }), [props]);
  const {faces, fillers} = useMemo(() => plan(props.cuts, widths), [props]);
  checkFillers(props, fillers, 'Orbit');
  useFonts();
  const pics = usePictures(props);
  const {f, i, a, b, closing} = useFrameInfo(props.cuts);
  const n = props.photos.length;
  const ring = ringAt(props.cuts, f), {angle, out} = ring;
  const p = photoAt(props, i);
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile(props.music)} />
      {pics && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, position: [0, 0.6, CAM_Z], near: 0.1, far: 80}}
                     gl={{antialias: true, toneMapping: THREE.ACESFilmicToneMapping}}>
          <color attach="background" args={[K]} />
          <fog attach="fog" args={[K, 11, 26]} />
          <ambientLight intensity={0.25} />
          <directionalLight position={[3, 5, 6]} intensity={1.6} />
          <Cam f={f} />
          <group rotation={[0.24 * (1 - out), 0, -0.06 * (1 - out)]}>
            <group rotation={[0, angle, 0]}>
              {widths.map((w, k) => {
                const {pos, ang} = cardAt(k, w, ring);
                const face = faceAt(faces, k, f);
                return (
                  <group key={k} position={pos} rotation={[0, ang, 0]}>
                    <mesh>
                      <boxGeometry args={[w, CARD_H, THICK]} />
                      <meshStandardMaterial attach="material-0" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-1" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-2" color="#111" metalness={0.9} roughness={0.25} />
                      <meshStandardMaterial attach="material-3" color="#111" metalness={0.9} roughness={0.25} />
                      {face
                        ? <meshBasicMaterial attach="material-4" map={face.kind === 'photos' ? pics.photo(face.index) : pics.filler(face.index)} toneMapped={false} />
                        : <meshStandardMaterial attach="material-4" color="#0d0d0f" roughness={0.6} />}
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
