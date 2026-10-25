// Loop: a flat grid of photos and a loupe of liquid glass that crawls over it (Chris's reelfolio recording, 2026-10-23;
// his words of 2026-10-24: "there is no camera"; "the background moves in 2d with the loop crawling over the photos
// grid"; "the photo zooms in a little BUT on a flat 2d surface. the whole grid enlarges when the loop is over the
// image"; "it enlarges to make the photo bigger"; "the loop doesn't shrink but the grid should"; "the photo should
// never lift from the background"; "the loop and photo itself don't transition to anything else other than what they
// are"; "we pick the images the loop is going to on the grid and they are the reel's 5-6 images"). So:
// - THE GRID: level rows of cards, every card its own shape (nothing cropped), tight even gaps of flat dark space;
//   the reel's photos are the cards the loop visits, the grid photos fill the rest. It slides in two dimensions to
//   bring the next visited card to the middle, and the whole grid enlarges while the loop rests on a card, so that
//   photo is bigger, then shrinks back as it slides on. Nothing moves in depth, nothing lifts.
// - THE LOOP: a loupe of liquid glass, always the same size on the screen, that crawls across each visited photo
//   while the grid rests on it, then on to the next; it magnifies what is under it, mildly, and shows the glass only
//   at its rim. It never stops, never changes into anything else.
// - HOLD: while the loop crosses a card the rest of the grid falls back into the dark; the card's label sits under
//   it (the room, then its line) with a counter at the right.
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
const Z = 4.3 / VIEW_W;                                        // the grid at rest: about two and a half cards across
const ENLARGE = 1.3;                                           // the whole grid, while the loop rests on a card: that photo bigger
const FIRST = 24, MOVE_SHARE = 0.35;                           // in 30ths of a second: the lead-in, and how much of each card's time is the slide
// where the visited cards sit: (row, x) in the middle rows, each a step or two from the last, so the slide reads
const VISITS: [number, number][] = [[5, 0], [4, 1.6], [3, 0.2], [4, -1.8], [5, -2.4], [6, -0.8]];
const GLASS_DEPTH = 0.3, GLASS_THICKNESS = 0.6;              // flat enough never to invert, thick enough to magnify a little
const LOOP_W = 0.55, LOOP_H = 0.68;                            // the loupe's half-size on the screen: about a third of the view wide
const CRAWL = 0.3;                                             // the loop crosses this much of a held card's width, side to side

// The grid: photos laid row by row in their own shape (aspect kept between 2:3 and 16:9), each row centred, so
// columns fall where they fall, as in the recording; the grid photos cycle, so none repeats within view, and the
// reel's photos take the visited cells.
type Card = {x: number; y: number; w: number; h: number; p: Tile};
const shape = (p: Tile) => Math.min(16 / 9, Math.max(2 / 3, p.w / p.h));
const rowY = (r: number) => ((ROWS - 1) / 2 - r) * PITCH_Y;
const layout = (photos: Photo[], grid: Tile[]) => {
  const visited = photos.slice(0, VISITS.length);
  const rest = [...photos.slice(VISITS.length), ...grid];     // a seventh photo is in the grid, not lost
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

// The timing: the reel's photos share the time before the close, each a hold with the slide to it in front.
const timing = (n: number) => {
  const per = (TOTAL - END - FIRST) / n, move = Math.round(per * MOVE_SHARE), hold = Math.round(per) - move;
  return {hold, move, arrivals: Array.from({length: n}, (_, k) => FIRST + k * (hold + move))};
};

const SWELL = 14;                                              // in 30ths: the grid's enlarging, once the loop has arrived
// Where the grid is at frame f: resting on a card, or sliding, level, to the next; and how much it is enlarged. It
// enlarges once the loop has crawled onto the card ("the grid enlarges to make the photo bigger when the loop has
// crawled to that image") and shrinks back as it slides on.
const gridAt = (visit: Card[], t: ReturnType<typeof timing>, f: number) => {
  let k = 0;
  for (let j = 0; j < t.arrivals.length; j++) if (f >= t.arrivals[j] - (j ? t.move : 0)) k = j;
  const slide = k > 0 ? (f - (t.arrivals[k] - t.move)) / t.move : 1;
  const c = visit[k];
  if (slide < 1) {
    const a = visit[k - 1], u = easeIO(slide);
    return {x: a.x + (c.x - a.x) * u, y: a.y + (c.y - a.y) * u, scale: ENLARGE - (ENLARGE - 1) * u, slide, k};
  }
  return {x: c.x, y: c.y, scale: 1 + (ENLARGE - 1) * easeIO((f - t.arrivals[k]) / SWELL), slide: -1, k};
};

// Where the loop is at frame f, in the grid's own units: it crawls across each held card while the grid rests (in
// at one side as the hold begins, out at the other as it ends), then on to the next card's near side while the
// grid slides; in from beyond the first card, out beyond the last. It never stops.
const loopAt = (visit: Card[], t: ReturnType<typeof timing>, f: number) => {
  const P: THREE.Vector2[] = [], T: number[] = [];
  visit.forEach((c, k) => {
    const from = visit[k - 1]?.x ?? c.x - 1, to = visit[k + 1]?.x ?? c.x + 1;
    const dir = Math.sign(to - from) || 1;                   // across the card in the direction of travel
    P.push(new THREE.Vector2(c.x - dir * CRAWL * c.w, c.y)); T.push(t.arrivals[k]);
    P.push(new THREE.Vector2(c.x + dir * CRAWL * c.w, c.y)); T.push(t.arrivals[k] + t.hold);
  });
  P.unshift(P[0].clone().add(new THREE.Vector2(-2, -0.3))); T.unshift(0);
  P.push(P[P.length - 1].clone().add(new THREE.Vector2(2, 0.3))); T.push(TOTAL);
  let i = 0;
  while (i < T.length - 2 && f >= T[i + 1]) i++;
  const u = (f - T[i]) / (T[i + 1] - T[i]);
  return P[i].clone().lerp(P[i + 1], i % 2 ? u : easeIO(u));   // steady across a card, eased between cards
};

// The loupe's rim: the liquid-glass look lives only where the eye looks through the edge (a Fresnel term on the
// silhouette), never inside the glass, where there is only the magnified photo (Chris, 2026-10-24: "when you put
// your eye to a loop there are no reflections inside of the loop itself, just on the edges").
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
  const rim = useMemo(rimMaterial, []);
  const t = timing(visit.length);
  const cardTex = useMemo(() => (tex ? cards.map((c) => coverTex(tex[items.indexOf(c.p)], c.p.w / c.p.h, c.w / c.h)) : []), [tex, cards]);
  const at = gridAt(visit, t, f);
  const card = visit[at.k], photo = card.p as Photo;
  // the hold: the grid darkens as the loop arrives, lights again before it slides on
  const since = f - t.arrivals[at.k], until = (at.k + 1 < visit.length ? t.arrivals[at.k + 1] - t.move : TOTAL - END) - f;
  const held = at.slide < 0 && !closing ? easeIO(Math.min(1, (since + 14) / 18, (until + 4) / 14)) : 0;
  const grey = Math.round(255 - (255 - 32) * held);
  const dimmed = `rgb(${grey},${grey},${grey})`;
  const scale = closing ? at.scale / (1 + 0.2 * easeIO((f - (TOTAL - END)) / 36)) : at.scale;   // the close: the grid shrinks back, slowly
  const labelOn = at.slide < 0 && !closing ? Math.min(1, since / 10, until / 8) : 0;
  const px = (W / (Z * VIEW_W)) * scale;                       // screen pixels per grid unit, as the grid stands now
  const loop = loopAt(visit, t, f);                            // in grid units; drawn where the grid puts that spot
  return (
    <AbsoluteFill style={{background: K}}>
      <Audio src={staticFile(music)} />
      {tex && (
        <ThreeCanvas width={W} height={H} camera={{fov: FOV, position: [0, 0, Z], near: 0.1, far: 100}} gl={{antialias: true}}>
          <color attach="background" args={[K]} />
          {/* the flat grid, slid so the visited card is in the middle, and enlarged while the loop rests on it */}
          <group position={[-at.x * scale, -at.y * scale, 0]} scale={[scale, scale, 1]}>
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
            <group position={[(loop.x - at.x) * scale, (loop.y - at.y) * scale, 1]}
                   scale={[LOOP_W + 0.03 * Math.sin(f / 7), LOOP_H - 0.03 * Math.sin(f / 7), GLASS_DEPTH]}
                   rotation={[0, 0, 0.4 + 0.08 * Math.sin(f / 11)]}>
              {/* the loupe, its own size whatever the grid does: clear glass that only magnifies what is under it (no
                  reflection inside: no light, no specular), flat enough never to invert; it breathes a little, as liquid does */}
              <mesh>
                <sphereGeometry args={[1, 64, 64]} />
                <meshPhysicalMaterial transmission={1} thickness={GLASS_THICKNESS} roughness={0} ior={1.5} dispersion={2.5}
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
