// A: Gallery. The photos hang like lit prints at different depths in a dark room with a glossy floor; on every beat
// the camera swoops from one print to the next and pushes in slowly while it holds (reference: "Look 00", Runway Labs).
// No picture twice (Chris, 2026-11-08, night; his choice for Gallery, 2026-11-09): the prints further down the room are
// seen far off in the hook and in every swoop, and the close backs away to show every print again. So a print shows its
// photo on its pass through the frame at its beat only, and hangs dark (its frame, no picture) before and after. The
// motion is as approved.
import React, {useLayoutEffect, useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {MeshReflectorMaterial} from '@react-three/drei';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Close, END, H, K, Label, Pictures, Props, TOTAL, W, easeIO, faceAt, facesOf, handheld, holdOf, passAt, passesOf,
        pixelsOnScreen, segmentAt, useFonts, useFrameInfo, usePictures} from './lib';
import {Slot, checkFillers, photoAt} from './slots';

const VFOV = 38, ASPECT = W / H;
const HFOV = 2 * Math.atan(Math.tan((VFOV * Math.PI) / 360) * ASPECT);
const PRINT_H = 2.2;

const layout = (n: number) => Array.from({length: n}, (_, i) => ({
  pos: new THREE.Vector3(i % 2 ? 2.6 : -2.6, 1.3 + 0.18 * ((i % 3) - 1), -i * 13),
  rotY: i % 2 ? -0.32 : 0.32,
}));

// Where the camera stands to show print i whole, with a margin, `push` closer. The fit is read from the real camera
// (its aspect is the canvas's), never assumed.
let FIT = {hf: HFOV, vf: (VFOV * Math.PI) / 180};
const viewOf = (p: {pos: THREE.Vector3; rotY: number}, width: number, push: number) => {
  const byW = (width / 2) / Math.tan(FIT.hf / 2), byH = (PRINT_H / 2) / Math.tan(FIT.vf / 2);
  const dist = Math.max(byW, byH) / 0.97 * (1 - push);
  const normal = new THREE.Vector3(Math.sin(p.rotY), 0, Math.cos(p.rotY));
  return {eye: p.pos.clone().add(normal.multiplyScalar(dist)), look: p.pos.clone()};
};

// where the camera stands at frame f and what it looks at
const cameraAt = (cuts: number[], widths: number[], spots: ReturnType<typeof layout>, f: number) => {
  const {i, a, local} = segmentAt(cuts, f);
  const cur = viewOf(spots[i], widths[i], 0.13 * easeIO(local));
  let eye = cur.eye, look = cur.look;
  const swoop = Math.min(1, (f - a) / 26);
  if (f < cuts[0] + 16) {
    // the hook: the camera is already flying in from deep in the room
    const t = easeIO(f / (cuts[0] + 16));
    eye = new THREE.Vector3(0, 2.6, 9).lerp(cur.eye, t); look = new THREE.Vector3(0, 1.2, -6).lerp(cur.look, t);
  } else if (i > 0 && swoop < 1) {
    const prev = viewOf(spots[i - 1], widths[i - 1], 0.13);
    const t = easeIO(swoop);
    eye = prev.eye.clone().lerp(cur.eye, t); eye.y += Math.sin(t * Math.PI) * 0.9;
    look = prev.look.clone().lerp(cur.look, t);
  }
  if (f >= TOTAL - END) {
    // the close: the camera rises and backs away to show every print at once
    const t = easeIO((f - (TOTAL - END)) / 30);
    eye = eye.clone().lerp(new THREE.Vector3(0, 6.5, 12), t);
    look = look.clone().lerp(new THREE.Vector3(0, 1, -30), t);
  }
  const [hx, hy] = handheld(f);
  return {eye: new THREE.Vector3(eye.x + hx, eye.y + hy, eye.z), look};
};

const Rig: React.FC<{props: Props; widths: number[]}> = ({props, widths}) => {
  const {camera} = useThree();
  const {f} = useFrameInfo(props.cuts);
  const spots = useMemo(() => layout(props.photos.length), [props.photos.length]);
  useLayoutEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    FIT = {vf: (cam.fov * Math.PI) / 180, hf: 2 * Math.atan(Math.tan((cam.fov * Math.PI) / 360) * cam.aspect)};
    const {eye, look} = cameraAt(props.cuts, widths, spots, f);
    camera.position.copy(eye);
    camera.lookAt(look);
    camera.updateProjectionMatrix();
  }, [f]);
  return null;
};

// Every print's passes through the frame, from the same camera; its photo on the pass at its beat, nothing on the others.
const plan = (cuts: number[], widths: number[]) => {
  const spots = layout(widths.length);
  const cam = new THREE.PerspectiveCamera(VFOV, ASPECT, 0.1, 120);
  const prints = spots.map((s, k) => {
    const m = new THREE.Matrix4().compose(s.pos, new THREE.Quaternion().setFromEuler(new THREE.Euler(0, s.rotY, 0)), new THREE.Vector3(1, 1, 1));
    return {corners: [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => new THREE.Vector3((x * widths[k]) / 2, (y * PRINT_H) / 2, 0).applyMatrix4(m)),
            centre: s.pos, normal: new THREE.Vector3(Math.sin(s.rotY), 0, Math.cos(s.rotY))};
  });
  const passes = passesOf(widths.length, (f) => {
    const {eye, look} = cameraAt(cuts, widths, spots, f);
    cam.position.copy(eye); cam.lookAt(look); cam.updateMatrixWorld();
    const ahead = (v: THREE.Vector3) => v.clone().applyMatrix4(cam.matrixWorldInverse).z < 0;
    return prints.map((pr) => (pr.normal.dot(eye.clone().sub(pr.centre)) > 0 && pr.corners.every(ahead) ? pixelsOnScreen(pr.corners, cam) : 0));
  });
  const beat = passes.map((ps, k) => {
    const n = passAt(ps, holdOf(cuts, k));
    if (n < 0) throw new Error(`Gallery's print ${k} is not in the frame at its own beat`);
    return n;
  });
  return facesOf(passes, (k, n): Slot | null => (n === beat[k] ? {kind: 'photos', index: k} : null));
};

const Prints: React.FC<{props: Props; pics: Pictures; widths: number[]; faces: (Slot | null)[][]}> = ({props, pics, widths, faces}) => {
  const spots = useMemo(() => layout(props.photos.length), [props.photos.length]);
  const {f} = useFrameInfo(props.cuts);
  return (
    <>
      {spots.map((s, k) => {
        const face = faceAt(faces, k, f);
        return (
          <group key={k} position={s.pos} rotation={[0, s.rotY, 0]}>
            <mesh position={[0, 0, -0.06]}>
              <boxGeometry args={[widths[k] + 0.08, PRINT_H + 0.08, 0.1]} />
              <meshStandardMaterial color="#050505" roughness={0.4} />
            </mesh>
            <mesh>
              <planeGeometry args={[widths[k], PRINT_H]} />
              {/* each its own material: a photo never takes on the dark print's colour, nor the dark print the photo */}
              {face ? <meshBasicMaterial key="photo" map={pics.photo(face.index)} toneMapped={false} />
                    : <meshBasicMaterial key="dark" color="#050505" toneMapped={false} />}
            </mesh>
          </group>
        );
      })}
    </>
  );
};

export const Gallery: React.FC<Props> = (props) => {
  checkFillers(props, 0, 'Gallery');
  useFonts();
  const pics = usePictures(props);
  const widths = useMemo(() => props.photos.map((_, k) => { const ph = photoAt(props, k); return PRINT_H * (ph.w / ph.h); }), [props]);
  const faces = useMemo(() => plan(props.cuts, widths), [props]);
  const {f, i, a, b: segB, closing} = useFrameInfo(props.cuts);
  const p = photoAt(props, i);
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile(props.music)} />
      {pics && (
        <ThreeCanvas width={W} height={H} camera={{fov: VFOV, near: 0.1, far: 120, position: [0, 2.6, 9]}}
                     gl={{antialias: true, toneMapping: THREE.ACESFilmicToneMapping}}>
          <color attach="background" args={[K]} />
          <fog attach="fog" args={[K, 16, 70]} />
          <ambientLight intensity={0.55} />
          <Rig props={props} widths={widths} />
          <Prints props={props} pics={pics} widths={widths} faces={faces} />
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.25, -14]}>
            <planeGeometry args={[60, 80]} />
            <MeshReflectorMaterial resolution={1024} mixBlur={1.2} mixStrength={2.2} blur={[300, 80]} roughness={0.85}
                                   depthScale={1} minDepthThreshold={0.4} maxDepthThreshold={1.2} color="#0c0c0e"
                                   metalness={0.6} mirror={0.6} />
          </mesh>
        </ThreeCanvas>
      )}
      {!closing && f >= props.cuts[0] && (
        <Label room={p.room} line={p.line} index={i} count={props.photos.length} f={f} a={a} b={segB} />
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.86)" />}
    </AbsoluteFill>
  );
};
