import { Easing, interpolate } from "remotion";

// What every look shares: the frame, the beat, the props the suite gives a reel (convention_social/render/reel_looks.py
// writes them), and the small easing helpers the looks are built with.

export const FPS = 30;                  // on the 120 BPM grid a beat is 15 frames and a bar 60
export const DURATION = 480;            // 16 s; Chiaroscuro and Axis run 25 s (their own *_FRAMES)
export const W = 1080, H = 1920;

/** One of the reel's photos: its file in the render's public dir, the focus point a crop keeps (the face), its size. */
export type Photo = { src: string; fx: number; fy: number; w?: number; h?: number };
/** The reel's track: its file in the public dir, the second of the track the reel starts on, and the playback rate (a
 *  track locked to the 120 BPM grid plays at grid/bpm, its pitch kept, so its beats land on the cuts). */
export type Track = { src: string; start: number; rate: number };

export type ReelProps = {
  business: string; kicker: string; town: string; phone: string; cta: string;
  accent: string; accent2: string;
  photos: Photo[];          // the hero first; four to six
  open: [string, string]; openSub: string;
  line1: [string, string]; line2: [string, string];
  stackLabel: string; marquee: string;
  counter: { label: string; value: string; unit: string };
  words: [string, string, string];
  wordPhotos?: [number, number, number];   // which photo goes with each word (indexes into photos)
  music?: Track;            // the suite always gives one: a reel never goes out silent
  tiles?: { src: string; w: number; h: number }[];   // Powers of Ten: more approved photos for the mosaic's outer rings
  ending?: Photo[];         // Axis: the closing burst, one photo a beat, the last held
  climax?: number;          // the photo shown whole at the climax (an index into photos); without it, the hero
};

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
/** 0 to 1 between frames a and b, eased (expo out unless told), held at each end. */
export const ramp = (f: number, a: number, b: number, e = expoOut) => interpolate(f, [a, b], [0, 1], { ...clamp, easing: e });

/** The photo shown whole at the climax: props.climax when it names one of the reel's photos, else 0, the hero. */
export const climaxIndex = (p: ReelProps): number =>
  p.climax !== undefined && Number.isInteger(p.climax) && p.climax > 0 && p.climax < p.photos.length ? p.climax : 0;
/** True for photo i when the climax keeps it for itself (any photo but the hero): it is held back from the rest of the
 *  reel and the hero takes its place there, so it is first seen at the climax. */
export const heldForClimax = (p: ReelProps, i: number): boolean => {
  const c = climaxIndex(p);
  return c !== 0 && ((i % p.photos.length) + p.photos.length) % p.photos.length === c;
};
