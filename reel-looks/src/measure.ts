import { useEffect, useState } from "react";
import { continueRender, delayRender } from "remotion";
import { fontsLoaded } from "./fonts";

// Type measured in the browser from the real font files, so every line is sized to fit before it is drawn, whatever
// words the suite writes for a reel. Widths are only cached once the fonts are in.

let ready = false;
fontsLoaded.then(() => { ready = true; });

/** Holds the frame until the fonts are in, then re-renders, so nothing is laid out with fallback metrics. */
export const useFontsReady = (): boolean => {
  const [ok, setOk] = useState(ready);
  const [handle] = useState(() => (ready ? null : delayRender("Waiting for the reel fonts to measure type")));
  useEffect(() => {
    if (ok) return;
    fontsLoaded.then(() => { setOk(true); if (handle !== null) continueRender(handle); });
  }, [ok, handle]);
  return ok;
};

export type Face = { family: string; weight?: number; italic?: boolean; stretch?: "normal" | "semi-expanded" | "expanded" | "condensed" | "semi-condensed" };

const cache = new Map<string, number>();
let ctx: CanvasRenderingContext2D | null = null;

/** Width of `text` in em in `face`, plus `track` em after every letter. */
export const emWidth = (text: string, face: Face, track = 0): number => {
  const font = `${face.italic ? "italic " : ""}${face.weight ?? 400} 100px ${face.family}`;
  const key = `${font}|${face.stretch ?? "normal"}|${text}`;
  let w = cache.get(key);
  if (w === undefined) {
    ctx = ctx ?? document.createElement("canvas").getContext("2d");
    if (!ctx) return text.length * 0.55 + track * text.length;
    ctx.font = font;
    (ctx as unknown as { fontStretch: string }).fontStretch = face.stretch ?? "normal";
    w = ctx.measureText(text).width / 100;
    if (ready) cache.set(key, w);
  }
  return w + track * [...text].length;
};

/** Width in px of `text` at `size`. */
export const textWidth = (text: string, face: Face, size: number, track = 0) => emWidth(text, face, track) * size;

/** The biggest size, up to `max`, at which `text` fits `width`. */
export const fitSize = (text: string, face: Face, width: number, max: number, track = 0) =>
  Math.min(max, width / Math.max(0.01, emWidth(text, face, track)));

const metricCache = new Map<string, { base: number; cap: number; xh: number }>();
/** Where the baseline sits in a box of line-height 1 (em from its top), and the cap and x heights (em). */
export const metrics = (face: Face): { base: number; cap: number; xh: number } => {
  const font = `${face.italic ? "italic " : ""}${face.weight ?? 400} 100px ${face.family}`;
  const hit = metricCache.get(font);
  if (hit) return hit;
  ctx = ctx ?? document.createElement("canvas").getContext("2d");
  if (!ctx) return { base: 0.8, cap: 0.65, xh: 0.45 };
  ctx.font = font;
  const m = ctx.measureText("H"), x = ctx.measureText("x");
  const fa = m.fontBoundingBoxAscent / 100, fd = m.fontBoundingBoxDescent / 100;
  const out = { base: (1 - (fa + fd)) / 2 + fa, cap: m.actualBoundingBoxAscent / 100, xh: x.actualBoundingBoxAscent / 100 };
  if (ready) metricCache.set(font, out);
  return out;
};
