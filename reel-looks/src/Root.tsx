import React from "react";
import { Composition } from "remotion";
import { DURATION, FPS, H, ReelProps, W } from "./look";
import { Axis, AXIS_FRAMES } from "./looks/Axis";
import { Chiaroscuro, CHIAROSCURO_FRAMES } from "./looks/Chiaroscuro";
import { Darkroom } from "./looks/Darkroom";
import { Manifesto } from "./looks/Manifesto";
import { PowersOfTen } from "./looks/PowersOfTen";
import { Section } from "./looks/Section";
import { SplitScreen } from "./looks/SplitScreen";
import { Stillness } from "./looks/Stillness";
import { Titles } from "./looks/Titles";
import { Weather } from "./looks/Weather";

// Event Caliber's ten reel looks, approved by Chris on 2026-11-08: one composition each, its id the look's name
// (convention_social/render/reel_looks.COMPOSITION). The suite renders one with its own props (the reel's photos, words,
// track) in a public dir of its own: `npx remotion render src/index.ts <Look> out.mp4 --props=... --public-dir=...`.
export const LOOKS: Record<string, React.FC<ReelProps>> = {
  PowersOfTen, Manifesto, Darkroom, Titles, Section, SplitScreen, Weather, Stillness, Chiaroscuro, Axis,
};
/** Every look runs 16 s except these two, which run 25 s (Chris, 2026-11-08). */
export const FRAMES: Record<string, number> = { Chiaroscuro: CHIAROSCURO_FRAMES, Axis: AXIS_FRAMES };

// Only the words a reel always carries; the suite gives every reel its photos, words and track.
const DEFAULTS: ReelProps = {
  business: "Event Caliber", kicker: "event & conference photography", town: "DC · MD · VA", phone: "eventcaliber.com",
  cta: "Request a quote", accent: "#00E1FF", accent2: "#F3F3F1",
  photos: [], open: ["Every", "room."], openSub: "every moment.", line1: ["Step", "back."], line2: ["Then", "the room."],
  stackLabel: "Stage · portraits · reception", marquee: "Seen", counter: { label: "Every moment", value: "1", unit: "take" },
  words: ["Stage.", "Portrait.", "Reception."],
};

export const RemotionRoot: React.FC = () => (
  <>
    {Object.entries(LOOKS).map(([id, C]) => (
      <Composition key={id} id={id} component={C} width={W} height={H} fps={FPS} durationInFrames={FRAMES[id] ?? DURATION} defaultProps={DEFAULTS} />
    ))}
  </>
);
