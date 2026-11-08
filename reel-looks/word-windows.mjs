// Powers of Ten: the frames each beat word is on screen, from the same layout the look draws with
// (src/looks/powersOfTenLayout.ts). Reads a list of the look's props (photos and tiles with their w and h) as JSON on
// stdin, writes the list of their word windows ([first, last] frame, by word) as JSON on stdout. The suite runs it to cut
// the frames the art director sees (convention_social/render/reel_looks.py) and its tests to check every word holds.
// Run: node --experimental-strip-types --no-warnings word-windows.mjs < props.json
import { world } from "./src/looks/powersOfTenLayout.ts";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map((p) => world(p, (pic) => pic.w / pic.h).windows.map((w) => w ?? [0, -1]));
process.stdout.write(JSON.stringify(out));
