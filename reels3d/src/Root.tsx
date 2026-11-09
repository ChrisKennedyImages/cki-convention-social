import React from 'react';
import {CalculateMetadataFunction, Composition, registerRoot} from 'remotion';
import {Gallery} from './Gallery';
import {Orbit} from './Orbit';
import {Ring} from './Ring';
import {Loop} from './Loop';
import {Wall} from './Wall';
import wall from './wall.json';
import {H, Props, TOTAL, W} from './lib';

// The sample set, for the studio and the stills Chris is shown: six of his approved photos, one per room, cuts on
// the track's beats, and the approved photos of wall.json as fillers (a style shows exactly its own count of them and
// says so when a sample holds another). A post gives its own props (render/reels3d.py).
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
  fillers: wall,
  music: 'music.mp4',
};

// Five photos for the reels that name each one, so every line stays up long enough to read (2026-10-23).
const SAMPLE5: Props = {...SAMPLE, photos: SAMPLE.photos.slice(0, 5), cuts: [8, 74, 146, 218, 308], fillers: []};

// 60 fps: the timeline counts 30ths of a second (lib.useFrameInfo), so each frame is drawn twice as often. The card check
// (slots.ts) renders the timeline's own 30ths.
const rate: CalculateMetadataFunction<Props> = ({props}) => (props.check ? {fps: 30, durationInFrames: TOTAL} : {});

const Root: React.FC = () => (
  <>
    <Composition id="Wall" component={Wall} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE} calculateMetadata={rate} />
    <Composition id="Loop" component={Loop} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE} calculateMetadata={rate} />
    <Composition id="Ring" component={Ring} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE} calculateMetadata={rate} />
    <Composition id="Gallery" component={Gallery} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE5} calculateMetadata={rate} />
    <Composition id="Orbit" component={Orbit} width={W} height={H} fps={60} durationInFrames={TOTAL * 2} defaultProps={SAMPLE5} calculateMetadata={rate} />
  </>
);

registerRoot(Root);
