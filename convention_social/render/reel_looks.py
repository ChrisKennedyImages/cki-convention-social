"""The ten reel looks (reel-looks/, Remotion): Event Caliber's reels made by the suite from Chris's approved photos.

Chris approved ten looks on 2026-11-08 as preview reels and said "Yes, build it.": Powers of Ten, Manifesto, Darkroom,
Titles, Section, Split Screen, Weather, Stillness, Chiaroscuro and Axis. They join the five 3D styles
(render/reels3d.py) in the reel rotation only while REEL_LOOKS is on in .env (`enabled`, off by default; the content
agent's reel_style reads it), and only a look with a track that suits it is chosen (`music.for_look`).

A reel in a look is made the way a 3D reel is: everything the render needs goes into a public dir of its own beside the
mp4 (the photos as JPEG with their size, the track, links to the looks' fonts and textures), Remotion renders the
look's composition with props.json, the mp4 is the product and the dir is removed. No Node, no reel: the draft falls
back to a carousel of the same photos (content.make_renderer), as a 3D reel does.

No picture is shown twice in a reel (Chris, 2026-11-08, night, on the Axis reel: "there are duplicates! The women in red
at the end you just used is also in the gallery on the left side! The masters wouldt be this sloppy!"; the option he
took: "each look takes as many different photos as it shows (the design itself unchanged)"). Each look shows SLOTS: its
photo slots take the post's own photos (TAKES, the photos the picker takes and the post records), each seen once in a
moment of its own (the cover, its word, its scene); its filler slots (a contact sheet, a gallery, a montage, a mosaic's
rings) take fillers, more of his approved photos drawn as a 3D reel's wall is (`fillers`). The looks had cycled a few
photos round many slots; a slot the props do not hold now stops the render (reel-looks/src/slots.ts), and
`ccs reel-check` (render/reel_check.py) renders a look with a card in each slot to prove no picture comes back.

The photos come through the content agent's picker under the look's rule (`photo_rule`). Chris, 2026-11-08: "it's
event photography mainly - the gallery in the last one should remain all portraits. It's also fine to have one or two
portrait other ones": at most two portraits in any look but Axis, and Axis takes portraits only, its last two the
closing burst (Chris chose a burst of two: the second to last shown a beat, the last held). His photos render exactly
as shot in eight looks; Chiaroscuro and Axis alone grade and light them ("Keep the photos from any color changes except
for only the last two I mentioned"). A face is never cut by a crop: the hero keeps the art director's focus point,
every other photo (0.5, 0.42), as every design here does.

The words: reel_lines.py. The cover is frame 0 of every look, its hook readable (COVER_FRAME, the frame Instagram shows);
the stills the art director looks at are the frames where the three beat words are on screen with their photos
(STILL_FRAMES), and it is told what the look puts on the frame on purpose and that each beat word must name what its own
photo plainly shows (`brief`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image

from .. import reel_lines
from ..core import config
from ..core.config import REPO_ROOT
from ..music import LookTrack
from .meta import ImageMeta, save_jpeg
from .reels3d import Filler, copy_photo, frame_at, node_tool, run_remotion

SWITCH = "REEL_LOOKS"                                     # .env: "on" adds the ten looks to the reel rotation
LOOKS = ("powersoften", "manifesto", "darkroom", "titles", "section", "splitscreen", "weather", "stillness",
         "chiaroscuro", "axis")
NAMES = {"powersoften": "Powers of Ten", "manifesto": "Manifesto", "darkroom": "Darkroom", "titles": "Titles",
         "section": "Section", "splitscreen": "Split Screen", "weather": "Weather", "stillness": "Stillness",
         "chiaroscuro": "Chiaroscuro", "axis": "Axis"}
COMPOSITION = {"powersoften": "PowersOfTen", "manifesto": "Manifesto", "darkroom": "Darkroom", "titles": "Titles",
               "section": "Section", "splitscreen": "SplitScreen", "weather": "Weather", "stillness": "Stillness",
               "chiaroscuro": "Chiaroscuro", "axis": "Axis"}          # the Remotion composition ids (reel-looks/src/Root.tsx)
REEL_LOOKS = REPO_ROOT / "reel-looks"
FPS = 30
FRAMES = {look: 750 if look in ("chiaroscuro", "axis") else 480 for look in LOOKS}     # 16 s; those two 25 s
COVER_FRAME = {look: 0 for look in LOOKS}                 # the hook is readable on every look's first frame
COVER_MS = {look: round(COVER_FRAME[look] * 1000 / FPS) for look in LOOKS}
# the frames where the three beat words are on screen, each with its own photo (checked on the approved reels): all
# three at once in most looks; Axis puts one word a beat across its own portrait. Powers of Ten's words come one after
# another, each held at least 1.5 s beside its photo, when depends on the photos' shapes: a render gives the frames
# (frames_of); these two serve a Powers of Ten reel made before (ccs queue-reel), the approved one's words all on at 120
STILL_FRAMES = {"powersoften": (60, 120), "manifesto": (295,), "darkroom": (352,), "titles": (330,), "section": (335,),
                "splitscreen": (340,), "weather": (340,), "stillness": (320,), "chiaroscuro": (232,),
                "axis": (188, 203, 218)}
GRADED = ("chiaroscuro", "axis")                          # the two looks that grade and light his photos
PORTRAIT = "portrait"                                     # classifications.shot_type
PORTRAITS_ONLY = ("axis",)
MOST_PORTRAITS = 2                                        # in any other look
ENDING = 2                                                # Axis's closing burst


@dataclass(frozen=True)
class Slots:
    """The pictures a look shows, each once (its TSX exports the same SLOTS): `photos`, slots for the post's own, the
    hero or the first word's photo first, then the word photos, then its other moments; `fillers`, every other slot.
    `fillers_from`: a look whose layout places as many fillers as its photos' shapes allow (Powers of Ten's mosaic)
    takes from that many to `fillers`, exactly the ones it places (fit_mosaic)."""
    photos: int
    fillers: int
    fillers_from: Optional[int] = None


SLOTS = {
    "powersoften": Slots(6, 40, 8),  # the six nearest the hero; the mosaic's outer rings, as many as it places (with
    #                                  fewer than 8 the move is too short for every word to hold beside its photo)
    "manifesto": Slots(7, 2),        # the shout, the three wedges, the climax, the manifesto, the number; the photomontage
    "darkroom": Slots(8, 8),         # the hero (the first print on the line), two more prints on the line, the tray's
    #                                  print, the enlarger's, the frame cut from the sheet, two more on the sheet; the sheet
    "titles": Slots(7, 2),           # the cover, the three bars, the climax, the end title, the number; Psycho bars, symbol
    "section": Slots(6, 3),          # the hero (the exploded view), the three word rooms (A seen on its stop), the attic,
    #                                  the first floor's other; the plates
    "splitscreen": Slots(8, 6),      # the resolve (the hero), the triptych, the split, the counterpoint; the sheet
    "weather": Slots(7, 0),          # the storm, the three words, the clearing, the long lens, the gale
    "stillness": Slots(7, 0),        # the rise (the hero), the three words, the level line, the pair
    "chiaroscuro": Slots(7, 12),     # the calling, the three arches, the climax, the night watch, the double exposure;
    #                                  the picture under the number, the studies and the montage
    "axis": Slots(8, 13),            # the doorway, the three words, the first and last doors, the burst; the gallery's
    #                                  eleven walls and the two middle doors (as the hand-fixed Axis sent to Chris, v5)
}
# The looks whose first photo carries the first word and is seen on in one pass (Powers of Ten's one move; Darkroom's hero,
# first seen on the line): their words go on their first three photos. In the others the hero has a moment of its own
# (the cover; Split Screen's resolve, Stillness's rise, Section's exploded view) and is seen there only, and the words go
# on the three photos after it. A picture is never carried on from one moment into another through a wipe or a dissolve:
# that is two moments, and shown in two places at once.
FIRST_WORD_LEADS = ("powersoften", "darkroom")
TAKES = {look: s.photos for look, s in SLOTS.items()}    # the post's own photos a look takes: as many as it shows
# fewer and the look is not made: its lead and its three word photos (Axis's burst of two besides); a photo slot the post
# has no photo for takes a filler, the least of the look's moments first (each look numbers its slots so)
LEAST = {look: 6 if look in PORTRAITS_ONLY else 4 for look in LOOKS}
MOSAIC_PORTRAITS = 8                                      # Powers of Ten's mosaic: mostly not portraits (2026-11-08)
DEFAULT_FOCUS = (0.5, 0.42)
RENDER_TIMEOUT = 30 * 60
ASSET_WAIT_MS = 120_000                                   # Remotion's wait for fonts and photos (its default is 30 s)
CONCURRENCY = 4                                           # the approved previews were rendered so on the Mini
WORD_HOLD = 45                                            # every Powers of Ten word holds 1.5 s beside its photo (2026-11-08)
BRIEF_WORDS = "Each beat word must name what its own photo plainly shows; a word that does not match its photo is a fault."
# Axis's three words are Chris's own for every portrait (reel_lines.FIXED_WORDS), not a room: the director judges the photos
FIXED_BRIEF_WORDS = ("Its three beat words ({words}) are the photographer's own, the same on every reel in this look: a word "
                     "is a fault only where its own portrait plainly contradicts it.")
# What each look puts on the frame on purpose, for the art director: it judges the words and the design, never the photos
# (2026-11-08: his approval is final), and nothing named here is a fault. Each look's own elements that a picky eye could
# take for one are named: the Darkroom reel was turned back three times (drafts 81, 88 and 89) for "an empty white cell
# in position 1", "duplicate frames" and frames "underexposed to near black" on its contact sheet, which are the roll's
# fogged leader, the same pictures twice on the sheet (as the look then drew it; since 2026-11-08, night, every frame is a
# picture of its own), and his own photos as shot sitting in the film's black.
ON_PURPOSE = {
    "powersoften": "the camera pulls back without a cut from the hero over one plane of the photographer's photos laid "
                   "edge to edge with small dark gaps, ring after ring, into a night map of the region; each beat word "
                   "sits in a dark band beside its own photo, the hook and lines in a dark strip at the top, a readout "
                   "at the foot. Photos small and far off as the camera pulls back, the dark gaps between them and the "
                   "dark map around the mosaic are the design.",
    "manifesto": "a constructivist poster: hard diagonals, cyan wedges and beams on white paper and black, big slanted "
                 "capitals; every photo whole at its own shape, beside the shapes; each beat word runs along the wedge "
                 "that points at its own photo. Nothing sits level: the slanted words and shapes, photos of different "
                 "sizes side by side and the bare paper and black around them are the design.",
    "darkroom": "a darkroom under a red safelight. The cover is a contact sheet on a light box: a roll of twelve frames "
                "in black film strips with their edge numbers. The first frame, top left, is the roll's fogged leader, "
                "white fading to grey and empty on purpose, as the first frame of every roll is. The other eleven are "
                "small prints of the photographer's own photos exactly as shot, eleven different pictures; each sits whole "
                "in the film's black, so a dark or narrow photo makes a dark frame. Then one frame is cut from the sheet, "
                "the enlarger lays a picture on the easel and a print develops in from paper white in the tray: three "
                "different photos on purpose, since no picture is shown twice in the reel. Then prints pegged on lines "
                "with a word pencilled on each print's border, the hero first. The fogged leader, the film's black, the "
                "red room around the prints and the white paper borders are the design.",
    "titles": "film opening titles in cut paper: ragged, hand cut bars of cyan and white paper on black, letters cut by "
              "hand and set a little off their neighbours, bars that slide across and split the frame; each photo whole "
              "at its own shape, standing on its bar, its beat word on the bar beneath it. The ragged edges, the uneven "
              "letters, the bars and the black around the photos are the design.",
    "section": "an architect's section drawing: a house cut through on drafting paper, the cut walls, floors and roof "
               "solid black and hatched, every room the shape of its photo, numbered callouts and a legend. A room is "
               "drawn empty in thin line whenever its photo is not up in it, so empty rooms on the drawing are the design. The "
               "small photos in the drawing's rooms and the legend's numbers, which tie each beat word to its room, are "
               "the design. When the legend comes up, the first word's room stays drawn empty on purpose: its photo was up "
               "in it on the camera's earlier stop and is not shown twice; its word names that photo. In the exploded view the photos hang apart below the hero on a dashed axis, skewed flat as "
               "plates in an axonometric drawing, then snap together into the hero straight on: that skew is the design.",
    "splitscreen": "split screen: the frame divided into panels on a fine gutter, the photos whole in their panels, the "
                   "words on solid cyan, paper or black fields beside them; each beat word on the field beside its own "
                   "photo. Panels of solid colour with no photo, the gutters and photos of different sizes side by side "
                   "are the design.",
    "weather": "a storm: dark sky, fog, grain and blown leaves around the photos, thin rain streaks crossing them in "
               "layers, slate bands for the words; each beat word on the band beside its own photo. The rain crossing a "
               "photo is the design; between the drops the photo is as shot. The dark sky and the fog are around the "
               "photos, never on them.",
    "stillness": "quiet paper and ink: the photos stand whole on a level line on warm paper, large serif words beside "
                 "them, slow dissolves; each beat word stands beside its own photo. The cover is the intertitle, the hook "
                 "alone on the paper with no photo. The wide empty paper around the photos is the design.",
    "chiaroscuro": "an old master's gallery in the dark: one warm light from above finds each photo and everything else "
                   "falls to near black, the photos graded warm and lit like paintings with a canvas weave, gilt lines "
                   "and arches; each beat word under its own arched panel. The cover is a close detail of the hero in "
                   "the beam, the start of a slow pull back to the whole photo, so its close crop is the design. The "
                   "darkness, a photo half in shadow outside the pool of light, the warm grade and the canvas weave are "
                   "the design.",
    "axis": "a black corridor on one cyan line: portraits in silver black and white, doors parting on the line, heavy "
            "white capitals on a black band across the photo, and at the climax one portrait floods back into colour; "
            "each beat word across its own portrait. The black and white until the climax, the black band across a "
            "portrait, the dark corridor and the cyan line are the design.",
}


def enabled() -> bool:
    """REEL_LOOKS=on in .env: the ten looks are in the rotation. Off (blank, anything else) by default."""
    return (config.getenv(SWITCH) or "").strip().lower() == "on"


def photo_rule(look: str) -> Callable[[dict, Sequence[dict]], bool]:
    """`rule(row, taken)`: may this photo join a reel in `look` that has taken these so far. Axis takes portraits only;
    every other look at most MOST_PORTRAITS of them (Chris, 2026-11-08)."""
    def rule(row: dict, taken: Sequence[dict]) -> bool:
        portrait = row.get("shot_type") == PORTRAIT
        if look in PORTRAITS_ONLY:
            return portrait
        return not portrait or sum(1 for r in taken if r.get("shot_type") == PORTRAIT) < MOST_PORTRAITS
    return rule


def parts(look: str, items: Sequence) -> tuple[list, list, list]:
    """The post's photos (or their rooms), in its order, as the look takes them: (its lead, the rest its words are found
    among, Axis's burst). A FIRST_WORD_LEADS look finds its words among all of them; any other leads with the hero."""
    burst = list(items[-ENDING:]) if look in PORTRAITS_ONLY else []
    body = list(items[:-ENDING]) if look in PORTRAITS_ONLY else list(items)
    lead = [] if look in FIRST_WORD_LEADS else body[:1]
    return lead, body[len(lead):], burst


def words_fit(look: str, rooms: Sequence[Optional[str]]) -> bool:
    """The post's photos, with these confirmed rooms (in its order), give the look its three words, each on a photo whose
    room it names (reel_lines.beats)."""
    _, rest, _ = parts(look, rooms)
    try:
        reel_lines.beats(rest, look)
    except ValueError:                      # reel_lines.TooFewRooms among them
        return False
    return True


def fillers_needed(look: str, photos: int) -> int:
    """The fewest fillers a reel in `look` of that many of the post's photos can be made with."""
    s = SLOTS[look]
    return (s.fillers if s.fillers_from is None else s.fillers_from) + max(0, s.photos - photos)


class Supply:
    """The approved photos with a copy here a draft's fillers are drawn from (reels3d.wall_candidates, the slow part of a
    pick), read once however many looks the draft weighs."""
    def __init__(self, conn):
        self.conn = conn

    @cached_property
    def candidates(self) -> list[dict]:
        from . import reels3d
        return reels3d.wall_candidates(self.conn)

    def enough(self, look: str, rows: Sequence[dict], photos: int) -> bool:
        """Fillers enough for a reel in `look` of `photos` of the post's own, these (`rows`) kept off them."""
        need = fillers_needed(look, photos)
        return not need or len(fillers(self.conn, look, rows, n=need, candidates=self.candidates)) >= need


def fits(look: str, rows: Sequence[dict], *, rooms: Optional[dict] = None, supply: Optional[Supply] = None) -> bool:
    """These photos, already chosen, can make a reel in `look`: enough of them and no more than it shows, each allowed in
    turn; with `rooms` ({photo id: the room its final check confirmed}), its three words each on a photo naming them; with
    `supply`, the fillers it needs are here. A look that cannot be made is not chosen, so no reel falls back to a carousel
    for a reason the suite could see first."""
    rule = photo_rule(look)
    if not (LEAST[look] <= len(rows) <= TAKES[look] and all(rule(r, rows[:k]) for k, r in enumerate(rows))):
        return False
    if rooms is not None and not words_fit(look, [rooms.get(r["id"]) for r in rows]):
        return False
    return supply is None or supply.enough(look, rows, len(rows))


def can_fill(look: str, pool: Sequence[dict], supply: Optional[Supply] = None) -> bool:
    """The pool holds photos enough for the look (Axis its eight portraits, any other look its least) and, with `supply`,
    the fillers a full reel in it needs are here (Axis's thirteen portraits, one a shoot)."""
    if look in PORTRAITS_ONLY:
        enough = sum(1 for r in pool if r.get("shot_type") == PORTRAIT) >= TAKES[look]
    else:
        enough = len(pool) >= LEAST[look]
    return enough and (supply is None or supply.enough(look, [], TAKES[look]))


def brief(look: str, *, card: bool = True, stills: Optional[int] = None) -> str:
    """What the art director is told before it looks at a reel in `look`: what it sees (the cover, the 2:3 card when
    there is one, `stills` frames of its words, the look's STILL_FRAMES when not said), what the look puts on the frame
    on purpose, and the rule of the words."""
    stills = stills or len(STILL_FRAMES[look])
    seen = ["its cover frame"] + (["the first photo on a 2:3 card"] if card else []) + \
           [f"{('one', 'two', 'three')[stills - 1]} frame{'s' if stills > 1 else ''} where its three beat words are on screen, "
            "each with its own photo"]
    photos = ("The grade and the light on the photos are the look." if look in GRADED else
              "Nothing in the render changes a photo's colour or light: each photo is as Chris shot and approved it.")
    words = (FIXED_BRIEF_WORDS.format(words=" ".join(reel_lines.FIXED_WORDS[look])) if look in reel_lines.FIXED_WORDS
             else BRIEF_WORDS)
    return (f"{1 + int(card) + stills} pictures of a {FRAMES[look] // FPS} second reel in the {NAMES[look]} look: "
            f"{', '.join(seen[:-1])} and {seen[-1]}. In the reel {ON_PURPOSE[look]} {photos} No approved photo is a fault "
            f"in itself; a face cut by a crop is. {words}")


@dataclass
class LookPhoto:
    """One of the reel's photos: the picture, the room its final check confirmed (None: none), its focus point."""
    image: Image.Image
    room: Optional[str]
    focus: tuple[float, float] = DEFAULT_FOCUS


@dataclass(frozen=True)
class Plan:
    """What a reel in a look takes besides its photos: its set of lines (reel_lines.SETS) and its track."""
    lines: int
    track: LookTrack


@dataclass
class Arranged:
    photos: list[LookPhoto]             # the look's photo slots: the post's own in the look's order, then fillers for any
    #                                     slot it had no photo for (Axis's burst stays last)
    beats: reel_lines.Beats             # its photo indexes point into `photos`
    fillers: list[Filler]               # the look's filler slots


def arrange(look: str, photos: Sequence[LookPhoto], fillers: Sequence[Filler]) -> Arranged:
    """The post's photos (in its order, the hero first) and the fillers as the look shows them, each picture once.
    FIRST_WORD_LEADS looks lead with the three word photos (the first carries the first word: Powers of Ten's hero); the
    others lead with the hero, in a moment of its own, and the three word photos come after it. Then the rest of the post's photos;
    a photo slot the post had no photo for takes the first fillers, the rest fill the look's filler slots. Axis's last
    two photos are its closing burst, the last of them held. Too few or too many of either stops the reel."""
    slots = SLOTS[look]
    if not LEAST[look] <= len(photos) <= slots.photos:
        raise ValueError(f"the {NAMES[look]} look takes {LEAST[look]} to {slots.photos} of the post's photos; {len(photos)} came")
    short = slots.photos - len(photos)
    least = slots.fillers if slots.fillers_from is None else slots.fillers_from
    if not least + short <= len(fillers) <= slots.fillers + short:
        wanted = slots.fillers + short if least == slots.fillers else f"{least + short} to {slots.fillers + short}"
        raise ValueError(f"the {NAMES[look]} look needs {wanted} more approved photos with a copy here "
                         f"(fillers, never the post's own); {len(fillers)} came")
    lead, rest, burst = parts(look, photos)
    found = reel_lines.beats([p.room for p in rest], look)
    ordered = lead + [rest[i] for i in found.photos] + [p for i, p in enumerate(rest) if i not in found.photos]
    filled = []
    for f in fillers[:short]:
        with Image.open(f.path) as im:
            filled.append(LookPhoto(im.convert("RGB"), None))
    beats = reel_lines.Beats(photos=tuple(len(lead) + k for k in range(3)), words=found.words, stack=found.stack)
    return Arranged(ordered + filled + burst, beats, list(fillers[short:]))


def props(look: str, photos: Sequence[LookPhoto], *, plan: Plan, fillers: Sequence[Filler], public: Path,
          placed: Optional[Callable] = None) -> dict:
    """The render's props (reel-looks/src/look.ts ReelProps), with every file they name written under `public`. A
    look whose layout places what fits (`fillers_from`) keeps only the fillers it places (fit_mosaic, `placed` its seam)."""
    shaped = arrange(look, photos, fillers)
    (public / "photos").mkdir(parents=True)
    for name in ("fonts", "textures"):
        (public / name).symlink_to(REEL_LOOKS / "public" / name)

    def placed_at(p: LookPhoto, name: str) -> dict:
        w, h = copy_photo(p.image, public / "photos" / f"{name}.jpg")
        return {"src": f"photos/{name}.jpg", "fx": round(p.focus[0], 4), "fy": round(p.focus[1], 4), "w": w, "h": h}

    out = {**reel_lines.props(plan.lines, shaped.beats),
           "photos": [placed_at(p, f"p{k}") for k, p in enumerate(shaped.photos)], "fillers": []}
    for k, f in enumerate(shaped.fillers):
        with Image.open(f.path) as im:
            out["fillers"].append(placed_at(LookPhoto(im, None), f"f{k}"))
    least = SLOTS[look].fillers_from
    if least is not None:
        kept = fit_mosaic(out, placed or mosaic_fillers)
        for gone in out["fillers"][kept:]:
            (public / gone["src"]).unlink()
        out["fillers"] = out["fillers"][:kept]
        if kept < least:
            raise ValueError(f"the {NAMES[look]} mosaic places {kept} fillers for these photos; it needs {least}")
    track = public / f"music{plan.track.path.suffix.lower()}"
    shutil.copyfile(plan.track.path, track)
    out["music"] = {"src": track.name, "start": plan.track.start, "rate": plan.track.rate}
    return out


def word_windows(props_list: Sequence[dict]) -> list[list[list[int]]]:
    """Powers of Ten: [first, last] frame each beat word is on screen, for each of these props, from the layout the look
    draws with (reel-looks/word-windows.mjs on powersOfTenLayout.ts, by Node)."""
    r = subprocess.run([node_tool("node"), "--experimental-strip-types", "--no-warnings", str(REEL_LOOKS / "word-windows.mjs")],
                       input=json.dumps(list(props_list)), capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"the word windows could not be worked out: {(r.stderr or r.stdout).strip()[-300:]}")
    return json.loads(r.stdout)


def mosaic_fillers(props_list: Sequence[dict]) -> list[int]:
    """Powers of Ten: how many of its fillers the mosaic places, for each of these props, from the layout the look draws
    with (reel-looks/mosaic-fillers.mjs on powersOfTenLayout.ts, by Node)."""
    r = subprocess.run([node_tool("node"), "--experimental-strip-types", "--no-warnings", str(REEL_LOOKS / "mosaic-fillers.mjs")],
                       input=json.dumps(list(props_list)), capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"the mosaic could not be laid out: {(r.stderr or r.stdout).strip()[-300:]}")
    return json.loads(r.stdout)


def fit_mosaic(props_: dict, placed: Callable = mosaic_fillers) -> int:
    """How many of the props' fillers (in order) the mosaic shows every one of. It lays as many rings as cover the frame,
    so with photos of some shapes it places fewer than it is given (22 to 40 of 40 on photos of every camera shape), and
    with fewer it may lay a ring less: laid out again on the ones it placed until it places all it is given."""
    k = len(props_["fillers"])
    while True:
        [got] = placed([{**props_, "fillers": props_["fillers"][:k]}])
        if got >= k:
            return k
        k = got


@dataclass(frozen=True)
class Reel:
    """A rendered reel: its mp4, the frames the art director sees after the cover (its words with their photos), and the
    fillers it showed (to be recorded on the wall: reels3d.record_wall)."""
    video: Path
    word_frames: tuple[int, ...]
    fillers: tuple[Filler, ...] = ()


def frames_of(look: str, props_: dict, windows: Callable = word_windows) -> tuple[int, ...]:
    """The frames a reel's words are on: STILL_FRAMES, but for Powers of Ten, whose words come when its photos' shapes
    let them, the middle of each word's window. Fails closed: a word that would not hold WORD_HOLD frames beside its own
    photo stops the reel (Chris, 2026-11-08: no word is ever left off)."""
    if look != "powersoften":
        return STILL_FRAMES[look]
    [found] = windows([props_])
    if len(found) < 3 or any(b - a < WORD_HOLD for a, b in found[:3]):
        raise RuntimeError(f"a Powers of Ten word would not hold {WORD_HOLD} frames beside its photo: {found}")
    return tuple(sorted({(a + b) // 2 for a, b in found[:3]}))


def render(look: str, photos: Sequence[LookPhoto], *, plan: Optional[Plan], out: Path, fillers: Sequence[Filler] = (),
           run: Callable = run_remotion, windows: Callable = word_windows, placed: Callable = mosaic_fillers) -> Reel:
    """The reel as an mp4 at `out`: 1080 x 1920, 30 fps, 16 s (Chiaroscuro and Axis 25 s), with its track, and the frames
    its words are on, and the fillers it showed. `fillers`: the look's (`fillers`)."""
    if look not in LOOKS:
        raise ValueError(f"no reel look {look!r}; one of {', '.join(LOOKS)}")
    if plan is None:
        raise ValueError("a reel needs its track")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    public = out.with_name(f"{out.stem}-public")
    shutil.rmtree(public, ignore_errors=True)
    try:
        p = props(look, photos, plan=plan, fillers=fillers, public=public, placed=placed)
        shown = tuple(fillers[:SLOTS[look].photos - len(photos) + len(p["fillers"])])
        word_frames = frames_of(look, p, windows)
        (public / "props.json").write_text(json.dumps(p))
        cmd = [node_tool("npx"), "remotion", "render", "src/index.ts", COMPOSITION[look], str(out),
               f"--props={public / 'props.json'}", f"--public-dir={public}", f"--timeout={ASSET_WAIT_MS}",
               f"--concurrency={CONCURRENCY}", "--log=error"]
        r = run(cmd, cwd=str(REEL_LOOKS), timeout=RENDER_TIMEOUT)
        if r.returncode != 0:
            said = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError(f"remotion stopped with code {r.returncode}: {' '.join(said[-3:])[:400]}")
        if not out.is_file():
            raise RuntimeError("remotion finished but left no video")
    finally:
        shutil.rmtree(public, ignore_errors=True)
    return Reel(out, word_frames, shown)


def take_video(video: Path, out: Path) -> Path:
    """A reel rendered before (`ccs queue-reel`) as this post's mp4: copied in beside the post's other renders."""
    video, out = Path(video), Path(out)
    if not video.is_file() or video.stat().st_size == 0:
        raise RuntimeError(f"no reel at {video}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if video.resolve() != out.resolve():
        shutil.copyfile(video, out)
    return out


def stills(look: str, video: Path, *, out_dir: Path, meta: Optional[ImageMeta] = None,
           frames: Optional[Sequence[int]] = None) -> list[Path]:
    """The reel's cover (first) and the frames where its beat words are on screen (`frames`, from its render; else the
    look's STILL_FRAMES), cut from the reel itself and saved as JPEGs with the company's metadata."""
    out_dir = Path(out_dir)
    return [save_jpeg(frame_at(video, f / FPS), out_dir / f"{look}-{f:03d}.jpg", meta, quality=92)
            for f in (COVER_FRAME[look], *(frames or STILL_FRAMES[look]))]


def fillers(conn, look: str, rows: Sequence[dict], *, n: Optional[int] = None,
            candidates: Optional[list[dict]] = None) -> list[Filler]:
    """The fillers a reel in `look` of these photos of the post's own (`rows`) needs: its filler slots, and a photo slot
    for each photo the post has fewer than the look shows. More approved photos with a copy on this machine, by the rule
    Powers of Ten's mosaic and a 3D reel's wall are filled by (reels3d.wall_picks: in rotation, one per room per shoot,
    never a copy of the post's pictures, a frame of its moments, or a sitting the camera's clock cannot tell apart; the
    ones a reel shows are recorded as a use on the wall so the next reel reaches for others, never counted against the
    post's repeat window). Axis's are portraits, one a shoot; the mosaic's at most MOSAIC_PORTRAITS portraits; any other
    look's no more than keep the reel at MOST_PORTRAITS. Fewer than it needs and the reel is not made (`arrange`). `n`: that many at most instead; `candidates`:
    reels3d.wall_candidates read once for the draft (Supply)."""
    from . import reels3d
    need = SLOTS[look].fillers + max(0, TAKES[look] - len(rows)) if n is None else n
    if not need:
        return []
    ids = [r["id"] for r in rows]
    if look in PORTRAITS_ONLY:
        picked = reels3d.wall_picks(conn, exclude=ids, n=need, only=PORTRAIT, candidates=candidates)
    else:
        portraits = sum(1 for r in rows if r["shot_type"] == PORTRAIT)
        most = MOSAIC_PORTRAITS if look == "powersoften" else max(0, MOST_PORTRAITS - portraits)
        picked = reels3d.wall_picks(conn, exclude=ids, n=need, most_portraits=most, candidates=candidates)
    return [Filler(r["id"], r["path"]) for r in picked]
