// Loop: how many fillers its grid lays, from the same layout the style draws with (src/loopGrid.ts). Reads a list of
// the style's props (photos and fillers with their w and h) as JSON on stdin, writes for each the number of fillers the
// grid lays (each once, in the order given), or null when it would lay more than the props hold, as JSON on stdout. A
// row holds only the cards that come into the frame, as many as the photos' shapes make: the suite gives the grid only
// the fillers it lays (convention_social/render/reels3d.py), so no photo is taken and never shown.
// Run: node --experimental-strip-types --no-warnings loop-fillers.mjs < props.json
import { VISITS, layout } from "./src/loopGrid.ts";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map((p) => {
  const extra = Math.max(0, p.photos.length - VISITS.length);
  try {
    return layout(p.photos, p.fillers).laid - extra;
  } catch (e) {
    if (String(e.message).startsWith("Loop's grid lays more cards than")) return null;
    throw e;
  }
});
process.stdout.write(JSON.stringify(out));
