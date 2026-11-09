// Powers of Ten: how many of its fillers the mosaic places, from the same layout the look draws with
// (src/looks/powersOfTenLayout.ts). Reads a list of the look's props (photos and fillers with their w and h) as JSON on
// stdin, writes the count for each as JSON on stdout. The mosaic lays as many rings as cover the frame, so with photos of
// some shapes it places fewer than it is given: the suite gives it only the fillers it places
// (convention_social/render/reel_looks.py fit_mosaic), so no photo is taken and never shown.
// Run: node --experimental-strip-types --no-warnings mosaic-fillers.mjs < props.json
import { world } from "./src/looks/powersOfTenLayout.ts";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map((p) => {
  const given = new Set(p.fillers.map((f) => f.src));
  return world(p, (pic) => pic.w / pic.h).mosaic.cells.filter((c) => given.has(c.src)).length;
});
process.stdout.write(JSON.stringify(out));
