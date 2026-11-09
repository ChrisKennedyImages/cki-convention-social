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
  photos: Photo[];          // the look's slots for the post's own photos, in the look's order, each a different picture
  fillers: Photo[];         // the look's other slots, each a different picture again
  open: [string, string]; openSub: string;
  line1: [string, string]; line2: [string, string];
  stackLabel: string; marquee: string;
  counter: { label: string; value: string; unit: string };
  words: [string, string, string];
  wordPhotos: [number, number, number];    // which photo goes with each word (indexes into photos)
  music?: Track;            // the suite always gives one: a reel never goes out silent
  check?: Check;            // the card check's seam (slots.ts); never in a reel the suite makes
};
/** The card check (convention_social/render/reel_check.py): `probe` says on the console which line of the look asks for
 *  each slot; `light` shows one slot's white card (its file with "-lit" before ".jpg") where one line asks for it, so
 *  each place a slot is drawn is seen on its own. */
export type Check = { probe?: boolean; light?: { kind: "photos" | "fillers"; index: number; site: string } };

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
/** 0 to 1 between frames a and b, eased (expo out unless told), held at each end. */
export const ramp = (f: number, a: number, b: number, e = expoOut) => interpolate(f, [a, b], [0, 1], { ...clamp, easing: e });
