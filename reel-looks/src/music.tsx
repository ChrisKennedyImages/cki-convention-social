import React from "react";
import { Audio, interpolate, staticFile, useVideoConfig } from "remotion";
import { FPS, Track } from "./look";

// The reel's music: the track the suite chose for it (convention_social/music.py: an active Pixabay track that suits the
// look, the one least recently used first), started on its own second and played at its own rate. It fades in over the
// first 6 frames and out over the last half second.

export const Music: React.FC<{ track?: Track }> = ({ track }) => {
  const { durationInFrames } = useVideoConfig();
  if (!track) return null;
  const volume = (f: number) => interpolate(f, [0, 6, durationInFrames - 15, durationInFrames], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  // a track locked to the grid (rate other than 1) is trimmed to the exact source time of its start, the downbeat the
  // look's climax is set on; any other track to the nearest frame
  const trim = track.rate !== 1 ? track.start * FPS : Math.round(track.start * FPS);
  return <Audio src={staticFile(track.src)} trimBefore={trim} playbackRate={track.rate} volume={volume} />;
};
