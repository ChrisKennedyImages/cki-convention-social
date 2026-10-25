// Loop: a flat grid of photos and a loupe of liquid glass that crawls over it (Chris's reelfolio recording, 2026-10-23;
// his words of 2026-10-24: "there is no camera"; "the background moves in 2d with the loop crawling over the photos
// grid"; "the whole grid enlarges when the loop is over the image"; "it enlarges to make the photo bigger"; "the loop
// doesn't shrink but the grid should"; "the photo should never lift from the background"; "the loop and photo itself
// don't transition to anything else other than what they are"; "the loop move fluidly"; "do 4 images and go slower";
// "the grid is too small"; "when you put your eye to a loop there are no reflections inside of the loop itself, just
// on the edges"). So:
// - THE LOOP: one loupe of liquid glass, one size, that travels one smooth curve for the whole reel: in from beyond
//   the first photo, across each of the reel's four photos side to side, on to the next, out beyond the last. It is
//   slowest while it is wholly inside a photo ("it should slow on full bleed", the glass distorting what creeps
//   under it), a little quicker while its edge is crossing the photo's edge, quicker again between photos, the
//   speed changing smoothly; it never stops, never changes. Inside it only the photo under it, magnified mildly;
//   the glass shows only at its rim.
// - THE GRID: level rows of cards, every card its own shape (nothing cropped), tight even gaps of flat dark space;
//   a 3:2 card is two thirds of the width. The reel's photos are the four cards the loop visits, the grid photos
//   fill the rest. The grid is a flat picture: while the loop crosses a card it rests, enlarged a little around that
//   card so the photo is bigger, with the rest of the grid fallen back into the dark; as the loop leaves, it shrinks
//   back and slides, level, to bring the next card to the middle. Nothing moves in depth, nothing lifts.
// - The card's label sits under it while the loop crosses (the room, then its line, a counter at the right).
// Photos unlit and exact.
import React, {useMemo} from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import * as THREE from 'three';
import {Close, END, H, K, PAPER, Photo, Props, TOTAL, Tile, W, coverTex, easeIO, roundedMask, useFonts, useFrameInfo, useTextures} from './lib';

const FOV = 30, TAN = Math.tan((FOV * Math.PI) / 360), ASPECT = W / H;
const VIEW_W = 2 * TAN * ASPECT;                               // the width in view per unit of distance to the grid
const ROW_H = 1.5, GAP_X = 0.16, GAP_Y = 0.42;                 // rows of one height; a little more room under for the label
const ROW_W = 15, ROWS = 11;                                   // each row filled to about this width, centred
const PITCH_Y = ROW_H + GAP_Y;
const Z = (ROW_H * 1.5) / (0.66 * VIEW_W);                    // the grid at rest: a 3:2 card is two thirds of the width
const ENLARGE = 1.2;                                           // the whole grid, while the loop crosses a card: that photo bigger
const SWELL = 14;                                              // in 30ths: the grid's enlarging, once the loop is on the card
// where the four visited cards sit: (row, x) in the middle rows, each a step or two from the last, so the slide reads
const VISITS: [number, number][] = [[5, 0], [4, 1.6], [3, 0.2], [4, -1.8]];
const BEYOND = 1.2;                                            // where the loop comes in from and leaves to, past the first and last card
const EDGE_PACE = 2, MOVE_PACE = 4;                            // the loop's speed over a photo's edge, and between photos, as multiples of its full-bleed creep
const GLASS_DEPTH = 0.3, GLASS_THICKNESS = 0.6;              // flat enough never to invert, thick enough to magnify a little
const LOOP_W = 0.6, LOOP_H = 0.74;                             // the loupe's half-size on the screen: about a third of the view wide

// The grid: photos laid row by row in their own shape (aspect kept between 2:3 and 16:9), each row centred, so
// columns fall where they fall, as in the recording; the grid photos cycle, so none repeats within view, and the
// reel's photos take the visited cells.
type Card = {x: number; y: number; w: number; h: number; p: Tile};
const shape = (p: Tile) => Math.min(16 / 9, Math.max(2 / 3, p.w / p.h));
const rowY = (r: number) => ((ROWS - 1) / 2 - r) * PITCH_Y;
const layout = (photos: Photo[], grid: Tile[]) => {
  const visited = photos.slice(0, VISITS.length);
  const rest = [...photos.slice(VISITS.length), ...grid];     // a fifth or sixth photo is in the grid, not lost
  const fill = rest.length ? rest : photos;
  const cards: Card[] = [], visit: Card[] = [];
  let k = 0;
  for (let r = 0; r < ROWS; r++) {
    const row: Tile[] = [];
    for (let x = 0; x < ROW_W; k++) {
      const p = fill[k % fill.length];
      row.push(p);
      x += ROW_H * shape(p) + GAP_X;
    }
    const place = (tiles: Tile[]) => {               // the row's cards, centred
      let x = 0;
      const placed = tiles.map((p) => { const w = ROW_H * shape(p); const c = {x: x + w / 2, y: rowY(r), w, h: ROW_H, p}; x += w + GAP_X; return c; });
      return placed.map((c) => ({...c, x: c.x - (x - GAP_X) / 2}));
    };
    let placed = place(row);
    const taken: [number, number][] = [];            // (visit, cell) in this row
    VISITS.forEach(([vr, at], v) => {                // each visited photo takes the cell nearest its spot
      if (vr !== r || v >= visited.length) return;
      const n = placed.reduce((best, c, i) => (Math.abs(c.x - at) < Math.abs(placed[best].x - at) ? i : best), 0);
      row[n] = visited[v];
      placed = place(row);
      taken.push([v, n]);
    });
    for (const [v, n] of taken) visit[v] = placed[n];   // the row's final cards, so a visited card is the one drawn
    cards.push(...placed);
  }
  return {cards, visit};
};

// Distance along the curve as a smooth function of time through given (frame, distance) points: a monotone cubic
// (Fritsch and Carlson), so the speed changes smoothly between creeping and moving and never drops to a stop.
const smooth = (T: number[], S: number[]) => {
  const n = T.length, d = T.slice(0, -1).map((t, i) => (S[i + 1] - S[i]) / (T[i + 1] - t)), m = new Array<number>(n).fill(0);
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    const a = m[i] / d[i], b = m[i + 1] / d[i], h = Math.hypot(a, b);
    if (h > 3) { m[i] = (3 * a / h) * d[i]; m[i + 1] = (3 * b / h) * d[i]; }
  }
  return (t: number) => {
    if (t <= T[0]) return S[0];
    if (t >= T[n - 1]) return S[n - 1];
    let i = 0;
    while (T[i + 1] < t) i++;
    const h = T[i + 1] - T[i], x = (t - T[i]) / h, x2 = x * x, x3 = x2 * x;
    return (2 * x3 - 3 * x2 + 1) * S[i] + (x3 - 2 * x2 + x) * h * m[i] + (-2 * x3 + 3 * x2) * S[i + 1] + (x3 - x2) * h * m[i + 1];
  };
};

// The loop's one curve: in from beyond the first card; for each visited card, in the direction of travel, its near
// edge, where full bleed begins (the loop wholly inside the photo), where it ends, its far edge; on to the next;
// out beyond the last; a smooth spline through those points. Its pace: the full-bleed creep is the unit, a photo's
// edge is crossed at EDGE_PACE times that, the moves run at MOVE_PACE times that, the whole fitting the reel, and
// the speed changes smoothly between them. The grid's rests and slides are read off it: a card is held from the
// frame the loop reaches its near edge to the frame it leaves the far edge.
type Path = {curve: THREE.CatmullRomCurve3; total: number; along: (f: number) => number; entries: number[]; exits: number[]};
const path = (visit: Card[]): Path => {
  const pts: THREE.Vector3[] = [];
  visit.forEach((c, k) => {
    const from = visit[k - 1]?.x ?? c.x - 1, to = visit[k + 1]?.x ?? c.x + 1;
    const dir = Math.sign(to - from) || 1, half = c.w / 2, bleed = Math.max(0, half - LOOP_W);
    for (const d of [-half, -bleed, bleed, half]) pts.push(new THREE.Vector3(c.x + dir * d, c.y, 0));
  });
  pts.unshift(pts[0].clone().add(new THREE.Vector3(-BEYOND, -0.3, 0)));
  pts.push(pts[pts.length - 1].clone().add(new THREE.Vector3(BEYOND, 0.3, 0)));
  const curve = new THREE.CatmullRomCurve3(pts, false, 'centripetal');
  const lengths = curve.getLengths(800), total = lengths[800];
  const S = pts.map((_, i) => lengths[Math.round((i / (pts.length - 1)) * 800)]);   // distance to each point
  const pace = (i: number) => (i === 0 ? MOVE_PACE : [EDGE_PACE, 1, EDGE_PACE, MOVE_PACE][(i - 1) % 4]);   // the stretch from point i
  const units = S.slice(0, -1).reduce((sum, s0, i) => sum + (S[i + 1] - s0) / pace(i), 0);   // the reel in creep-time
  const creep = units / (TOTAL - END);                          // distance per frame at full bleed
  const T = [0];
  for (let i = 0; i < pts.length - 1; i++) T.push(T[i] + (S[i + 1] - S[i]) / (creep * pace(i)));
  const entries: number[] = [], exits: number[] = [];
  visit.forEach((_, k) => { entries.push(T[1 + 4 * k]); exits.push(T[4 + 4 * k]); });
  return {curve, total, along: smooth(T, S), entries, exits};
};
const loopAt = (p: Path, f: number) => p.curve.getPointAt(Math.min(1, Math.max(0, p.along(f) / p.total)));

// Where the grid is at frame f: resting on the card the loop is crossing (enlarged once the loop is on it), or
// sliding, level, from the card just left to the next; and which card that is.
const gridAt = (visit: Card[], p: Path, f: number) => {
  let k = 0;
  for (let j = 0; j < visit.length; j++) if (f >= (j ? p.exits[j - 1] : 0)) k = j;
  const c = visit[k];
  if (f < p.entries[k] && k > 0) {                             // sliding from the card just left
    const a = visit[k - 1], u = easeIO((f - p.exits[k - 1]) / (p.entries[k] - p.exits[k - 1]));
    return {x: a.x + (c.x - a.x) * u, y: a.y + (c.y - a.y) * u, scale: ENLARGE - (ENLARGE - 1) * u, resting: false, k};
  }
  return {x: c.x, y: c.y, scale: 1 + (ENLARGE - 1) * easeIO((f - p.entries[k]) / SWELL), resting: f >= p.entries[k], k};
};

// The loupe's rim: the liquid-glass look lives only where the eye looks through the edge (a Fresnel term on the
// silhouette), never inside the glass, where there is only the magnified photo.
const rimMaterial = () => new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `varying vec3 vN; varying vec3 vV;
    void main() { vN = normalize(normalMatrix * normal); vec4 p = modelViewMatrix * vec4(position, 1.0); vV = normalize(-p.xyz);
                  gl_Position = projectionMatrix * p; }`,
  fragmentShader: `varying vec3 vN; varying vec3 vV;
    void main() { float f = pow(1.0 - clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0), 5.0); gl_FragColor = vec4(vec3(1.0), f * 0.9); }`,
});

export const Loop: React.FC<Props> = ({photos, cuts, grid, music}) => {
  useFonts();
  const items = useMemo(() => [...photos, ...grid], [photos, grid]);
  const tex = useTextures(items.map((p) => p.src));
  const {f, closing} = useFrameInfo(cuts);
  const {cards, visit} = useMemo(() => layout(photos, grid), [photos, grid]);
  const p = useMemo(() => path(visit), [visit]);
  const rim = useMemo(rimMaterial, []);
  const cardTex = useMemo(() => (tex ? cards.map((c) => coverTex(tex[items.indexOf(c.p)], c.p.w / c.p.h, c.w / c.h)) : []), [tex, cards]);
  const at = gridAt(visit, p, f);
  const card = visit[at.k], photo = card.p as Photo;
  // while the loop crosses a card the rest of the grid falls back into the dark, and the label is up
  const since = f - p.entries[at.k], until = p.exits[at.k] - f;
  const held = at.resting && !closing ? easeIO(Math.min(1, (since + 4) / 14, (until + 4) / 14)) : 0;
  const grey = Math.round(255 - (255 - 32) * held);
  const dimmed = `rgb(${grey},${grey},${grey})`;
  const labelOn = at.resting && !closing ? Math.min(1, since / 10, until / 8) : 0;
  const px = (W / (Z * VIEW_W)) * at.scale;                    // screen pixels per grid unit, as the grid stands now
  const loop = loopAt(p, f);                                   // in grid units; drawn where the grid puts that spot
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile(music)} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: FOV, position: [0, 0, Z], near: 0.1, far: 100}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          {/* the flat grid, slid so the visited card is in the middle, and enlarged while the loop crosses it */}
          <group position={[-at.x * at.scale, -at.y * at.scale, 0]} scale={[at.scale, at.scale, 1]}>
            <mesh position={[0, 0, -0.02]}>                     {/* the field: a real surface, so the glass sees it */}
              <planeGeometry args={[100, 100]} />
              <meshBasicMaterial color={K} toneMapped={false} />
            </mesh>
            {cards.map((c, s) => (
              <mesh key={s} position={[c.x, c.y, 0]}>
                <planeGeometry args={[c.w, c.h]} />
                <meshBasicMaterial map={cardTex[s]} alphaMap={roundedMask()} alphaTest={0.5} toneMapped={false}
                                   color={c === card ? '#ffffff' : dimmed} />
              </mesh>
            ))}
          </group>
          {!closing && (
            <group position={[(loop.x - at.x) * at.scale, (loop.y - at.y) * at.scale, 1]} scale={[LOOP_W, LOOP_H, GLASS_DEPTH]}
                   rotation={[0, 0, 0.4]}>
              {/* the loupe, its own size and shape whatever the grid does: clear glass that only magnifies what is under
                  it (no reflection inside: no light, no specular), flat enough never to invert */}
              <mesh>
                <sphereGeometry args={[1, 64, 64]} />
                <meshPhysicalMaterial transmission={1} thickness={GLASS_THICKNESS} roughness={0} ior={1.5} dispersion={1.2}
                                      envMapIntensity={0} specularIntensity={0} color="#ffffff" />
              </mesh>
              <mesh material={rim} scale={1.01}>
                <sphereGeometry args={[1, 64, 64]} />
              </mesh>
            </group>
          )}
        </ThreeCanvas>
      )}
      {labelOn > 0 && (
        <div style={{position: 'absolute', left: W / 2 - (card.w / 2) * px, width: card.w * px, top: H / 2 + (card.h / 2) * px + 18,
                     display: 'flex', justifyContent: 'space-between', color: PAPER, opacity: labelOn}}>
          <div style={{lineHeight: 1.3}}>
            <div style={{fontFamily: 'body', fontSize: 32}}>{photo.room}</div>
            <div style={{fontFamily: 'body', fontSize: 25, color: '#8c8c93'}}>{photo.line}</div>
          </div>
          <div style={{fontFamily: 'mono', fontSize: 22, color: '#8c8c93', paddingTop: 8}}>
            {String(at.k + 1).padStart(2, '0')} / {String(visit.length).padStart(2, '0')}
          </div>
        </div>
      )}
      {closing && <Close f={f} field="rgba(10,10,11,0.82)" />}
    </AbsoluteFill>
  );
};
