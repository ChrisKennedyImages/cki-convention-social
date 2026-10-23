import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Gallery} from './Gallery';
import {Orbit} from './Orbit';
import {Ring} from './Ring';
import {Wall} from './Wall';
import {WallLift} from './WallLift';
import {FPS, H, Props, TOTAL, W} from './lib';

// The sample set: six of Chris's approved photos, one per room, and cuts on the track's beats (reel_styles.beats).
const SAMPLE: Props = {
  photos: [
    {src: 'photos/p1.jpg', room: 'MAIN STAGE', line: 'The keynote, from the room.', w: 2400, h: 1465},
    {src: 'photos/p2.jpg', room: 'THE CROWD', line: 'In the moment.', w: 2400, h: 1602},
    {src: 'photos/p3.jpg', room: 'AFTER DARK', line: 'After the last session.', w: 2400, h: 1602},
    {src: 'photos/p4.jpg', room: 'PORTRAITS', line: 'Speakers and guests, backstage.', w: 1600, h: 2400},
    {src: 'photos/p5.jpg', room: 'EXPO FLOOR', line: 'On the exhibition floor.', w: 2400, h: 1600},
    {src: 'photos/p6.jpg', room: 'BACKSTAGE', line: 'The minutes before the doors open.', w: 2400, h: 1601},
  ],
  cuts: [8, 74, 140, 194, 254, 326],
};

// Five photos for the reels that name each one, so every line stays up long enough to read (2026-10-23).
const SAMPLE5: Props = {photos: SAMPLE.photos.slice(0, 5), cuts: [8, 74, 146, 218, 308]};

const Root: React.FC = () => (
  <>
    {/* 60 fps: the timeline counts 30ths of a second (lib.useFrameInfo), so each frame is drawn twice as often */}
    <Composition id="Wall" component={WallLift} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={{cuts: SAMPLE.cuts}} />
    <Composition id="Loop" component={Wall} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={{cuts: SAMPLE.cuts}} />
    <Composition id="Ring" component={Ring} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={{cuts: SAMPLE.cuts}} />
    <Composition id="Gallery" component={Gallery} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE5} />
    <Composition id="Orbit" component={Orbit} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE5} />
  </>
);

registerRoot(Root);
