"""No picture twice in a reel, proved on a render of the look (`ccs reel-check`).

Chris, 2026-11-08, night, on the Axis reel: "there are duplicates! The women in red at the end you just used is also in
the gallery on the left side! The masters wouldt be this sloppy!" and "I need the agents to know this shit!" The option
he took (its words, not his): "a code test that renders each look with numbered cards and fails if any picture shows
twice".

`check(look)` renders the look as the suite makes it (render/reel_looks.props), every picture a black card in the shapes
his photos come in (wide, upright, 4:5), small (SCALE) and as frames:
  1. a probe: the look says on the console, for each slot, every place in its code that asks for it (reel-looks/src
     slots.ts, `check.probe`);
  2. the look all black;
  3. for each slot and each of its places, the look with that one slot's card white at that one place (`check.light`).
Each white render is compared with the black one frame by frame: where they differ, that slot is on screen from that
place. A slot is on screen in a frame when any of its places is; its passes on screen are its runs of such frames, a gap
of FLICKER frames or less closed unless another picture is on screen only inside it, and a gap of any length closed
while the slot still shows more than STILL_THERE (a card sliding past the frame's edge, a wall in Axis's corridor
fading in from the fog, a tile of Powers of Ten's mosaic shrinking as the camera pulls back: one pass; a cut to another
picture and back, as in Chiaroscuro's montage, is two). Then:
  - a repeat: a picture back on screen after another picture was shown;
  - twice at once: a picture on screen from two places in one frame (Split Screen's hero in the triptych and the resolve
    while the strip moved); one place drawing a picture cut by a band or into pieces is one place, so it is never taken
    for two;
  - never shown: a slot the look takes and never puts on screen (a photo taken and recorded as used, never seen);
  - back with nothing between, listed and not failed: a picture off screen and back with no other picture shown in the
    gap, only cards, black or drawing (Axis's hero, the cover then the doorway), for Chris to rule on.
A repeat, twice at once, never shown, or a look that will not render fails the check: exit 1 (fail closed). One line
of code that draws one slot twice is one place, so that it does not catch; tests/test_reel_slots.py keeps the looks from
taking a slot round again.

It runs where Remotion runs, on the Mini; CI cannot render, so tests/test_reel_slots.py pins the rule there from the
sources (no look cycles its photos, each look's slots are the suite's, a slot it is not given stops its render). It runs
once for a look, not for each reel: `--record` writes a passing look's sources' hash to reel-looks/card-checks.json
(REGISTRY), and that test fails for a look added or changed without a passing check recorded on its sources.

The five 3D styles (reels3d/, Chris's word of 2026-11-09 for the fix) are checked the same way, with numbered cards in
the literal sense: a style's slots are its textures (reels3d/src/slots.ts drawnFrom), the probe hears every place a
slot is drawn, every slot at every place gets a number, and each render shows the white card of every place whose
number has a given bit set, then the same with the bit cleared (its inverse). Where a pixel is brighter in one render
of a pair than in the other by more than CHANGED_3D, that bit of the number of the place on it is read; a pixel read in
every pair names its place; a pixel two places share half and half reads in neither and names none. So 2 x BITS renders
see every place, where one a place would take a hundred for the wall, and the passes, repeats and the rest are found as
for a look. The styles' thresholds are lower (ON_3D, CHANGED_3D): the loop's grid dims to an eighth while the loupe
holds a card, and a wall's tile can come in at the frame's edge as small as the 0.1 % a style draws (lib.tsx SHOWN_PX).
In 3D a card can be hidden behind another card in front of it without leaving the frame: the ring's next card slides
over it to its place, the wall's tiles go behind the lifted photo. So the probe also says, from the style's own geometry,
the frames each slot's card is inside the frame whatever covers it (slots.ts reportPresence), and a gap in which it never
left the frame is one pass, as STILL_THERE is for a look; a card that leaves the frame and comes back is two. The loop's
grid is one still plane: the probe says each card's cell on it (reportCells), the camera passing back over a cell whose
place is unchanged is one picture in one place (the coordinator's ruling, 2026-11-09, pending Chris; the alternative, a
new picture for each pass of a cell, is named in FOUNDER_DECISIONS), and a picture in two cells fails the check.
Their registry is reels3d/card-checks.json (REGISTRY_3D, tests/test_reels3d.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import wave
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageChops

from .. import music
from . import motion, reel_looks, reels3d
from .reels3d import node_tool, run_remotion

SCALE = 0.2                     # a fifth of 1080 x 1920: 216 x 384, ample to see a card
PROBE_SCALE = 0.1               # the probe's frames are never looked at
FLICKER = 5                     # frames off screen that still leave one pass, unless a cut to another picture is in them
CHANGED = 40                    # a pixel differs when its grey moves by more than this between the black and white render
ON = 0.004                      # a slot is on screen when that share of the frame differs
STILL_THERE = ON / 4            # and has not left it while it shows more than this (a tile shrinking with the move)
SHAPES = ((1500, 1000), (1000, 1500), (1200, 1500))     # the cards: wide 3:2, upright 2:3 and 4:5, as his photos come
UPRIGHT = ((1000, 1500), (1200, 1500))                  # Axis's portraits
ROOMS = ("main_stage", "breakout", "reception", "candid", "backstage", "stage_panel")
RENDER_TIMEOUT = 30 * 60
PROBED = re.compile(r"REELCHECK (photos|fillers) (\d+) (\S+)")
PRESENT = re.compile(r"REELIN (photos|fillers) (\d+) ([01]+)")         # a 3D slot's frames inside the frame
CELLS = re.compile(r"REELCELL (photos|fillers) (\d+) (\S+)")          # a card's cell on a still grid
REGISTRY = reel_looks.REEL_LOOKS / "card-checks.json"     # each look's last passing check, on the hash of its sources
REGISTRY_3D = reels3d.REELS3D / "card-checks.json"      # and each 3D style's
PHOTOS_3D = 6                   # a 3D reel's photos at the most (agents/content TAKES "reel"): every slot a reel can hold
CHANGED_3D = 16                 # the loop's dimmed grid is an eighth of white: 32 grey
ON_3D = 0.0005                  # a 3D slot is on screen when it shows half the 0.1 % a style draws at the least
STILL_THERE_3D = ON_3D / 4


def sources(look: str) -> list[Path]:
    """The files that make what a look shows: its own TSX, the props it reads (look.ts), its slots (slots.ts), and Powers
    of Ten's mosaic layout. A 3D style's: its own TSX, the shared pieces and props (lib.tsx), its slots (slots.ts), the
    compositions (Root.tsx), and the loop's grid."""
    if look in reels3d.STYLES:
        src = reels3d.REELS3D / "src"
        own = [src / f"{reels3d.COMPOSITION[look]}.tsx", src / "lib.tsx", src / "slots.ts", src / "Root.tsx"]
        return own + ([src / "loopGrid.ts"] if look == "loop" else [])
    src = reel_looks.REEL_LOOKS / "src"
    own = [src / "looks" / f"{reel_looks.COMPOSITION[look]}.tsx", src / "look.ts", src / "slots.ts"]
    return own + ([src / "looks" / "powersOfTenLayout.ts"] if look == "powersoften" else [])


def registry_of(look: str) -> Path:
    """Where a look's passing check is recorded: the looks' registry, or the 3D styles'."""
    return REGISTRY_3D if look in reels3d.STYLES else REGISTRY


def source_hash(look: str) -> str:
    h = hashlib.sha256()
    for path in sources(look):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def record(found: dict, source: str, *, registry: Optional[Path] = None, on: Optional[str] = None) -> bool:
    """A passing check (`found`, Report.as_dict) of the look's sources as they were (`source`, their hash then) written
    to the registry; a failed one, or sources changed since, writes nothing. True when written."""
    look = found["look"]
    if not found["ok"] or source != source_hash(look):
        return False
    registry = registry or registry_of(look)
    book = json.loads(registry.read_text()) if registry.exists() else {}
    book[look] = {"source": source, "checked": on or date.today().isoformat(), "slots": found["slots"],
                  "repeats": 0, "twice_at_once": 0, "never_shown": 0,
                  "back_with_nothing_between": found["back_with_nothing_between"]}
    registry.write_text(json.dumps(dict(sorted(book.items())), indent=1) + "\n")
    return True


def runs_of(frames: Sequence[int]) -> list[tuple[int, int]]:
    """[first, last] of each run of consecutive frame numbers (sorted)."""
    out: list[tuple[int, int]] = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1] = (out[-1][0], f)
        else:
            out.append((f, f))
    return out


@dataclass
class Slot:
    """One slot of a look: its name ("photo 3", "filler 0"), the frames it is on screen from each place in the look's code
    that asks for it, and what the check found."""
    name: str
    places: dict[str, list[bool]]
    seen: dict[str, list[float]] = field(default_factory=dict)  # each place's share of each frame, for the frame map
    stretches: list[tuple[int, int]] = field(default_factory=list)
    back_at: list[int] = field(default_factory=list)            # back after another picture was shown: a repeat
    back_alone: list[int] = field(default_factory=list)         # back with no other picture between: listed for Chris
    twice: list[tuple[int, int]] = field(default_factory=list)  # on screen from two places at once
    present: Optional[list[bool]] = None                        # 3D: each frame its card is inside the frame, covered or not
    cells: set[str] = field(default_factory=set)                # 3D on a still grid: the cells its card has

    @property
    def on(self) -> list[bool]:
        sites = list(self.places.values())
        return [any(s[f] for s in sites) for f in range(len(sites[0]))] if sites else []


@dataclass
class Report:
    look: str
    slots: list[Slot]
    error: str = ""

    @property
    def repeats(self) -> list[tuple[str, int]]:
        return [(s.name, f) for s in self.slots for f in s.back_at]

    @property
    def twice(self) -> list[tuple[str, tuple[int, int]]]:
        return [(s.name, r) for s in self.slots for r in s.twice]

    @property
    def never_shown(self) -> list[str]:
        return [s.name for s in self.slots if not s.stretches]

    @property
    def back_alone(self) -> list[tuple[str, int]]:
        return [(s.name, f) for s in self.slots for f in s.back_alone]

    @property
    def in_two_cells(self) -> list[str]:
        return [s.name for s in self.slots if len(s.cells) > 1]

    @property
    def ok(self) -> bool:
        return (not self.error and bool(self.slots) and not self.repeats and not self.twice and not self.never_shown
                and not self.in_two_cells)

    def as_dict(self) -> dict:
        fps = reel_looks.FPS

        def at(f: int) -> str:
            return f"{f / fps:.2f} s"
        return {"look": self.look, "ok": self.ok, "error": self.error, "slots": len(self.slots),
                "appearances": sum(len(s.stretches) for s in self.slots),
                "repeats": [f"{n} back at {at(f)}" for n, f in self.repeats],
                "twice_at_once": [f"{n} in two places from {at(a)} to {at(b)}" for n, (a, b) in self.twice],
                "never_shown": self.never_shown,
                "in_two_cells": self.in_two_cells,
                "back_with_nothing_between": [f"{n} back at {at(f)}" for n, f in self.back_alone],
                "places": {s.name: len(s.places) for s in self.slots},
                "stretches": {s.name: [[round(a / fps, 2), round(b / fps, 2)] for a, b in s.stretches] for s in self.slots},
                "frames": {s.name: {site: "".join("1" if v else "0" for v in on) for site, on in s.places.items()}
                           for s in self.slots},           # each place's frames on screen, to read again without a render
                "shares": {s.name: {site: [round(v * 10000) for v in seen] for site, seen in s.seen.items()}
                           for s in self.slots}}           # how much of each frame each place showed, in 1/10000


def find_repeats(slots: Sequence[Slot], flicker: int = FLICKER, still_there: float = STILL_THERE) -> None:
    """Each slot's passes on screen, the frames it came back on (after another picture: a repeat; after none: listed),
    and the frames it was on screen from two places at once."""
    ons = {id(s): s.on for s in slots}

    def others_on(s: Slot, a: int, b: int) -> bool:
        """Another slot on screen in frames a to b (inclusive)."""
        return a <= b and any(any(ons[id(o)][a:b + 1]) for o in slots if o is not s)

    def cut_to_another(s: Slot, end: int, back: int) -> bool:
        """Another slot on screen in the gap between frames `end` and `back` and in neither of them: a cut to it."""
        return any(any(ons[id(o)][end + 1:back]) and not ons[id(o)][end] and not ons[id(o)][back] for o in slots if o is not s)
    for s in slots:
        seen = list(s.seen.values())

        def stayed(a: int, b: int) -> bool:
            """The slot never left the screen in frames a to b: from some place it showed more than STILL_THERE, or (3D)
            its card stayed inside the frame, covered by another, or it is the one card of one still cell."""
            if len(s.cells) == 1 or (s.present is not None and all(s.present[a:b + 1])):
                return True
            return bool(seen) and all(any(v[f] > still_there for v in seen) for f in range(a, b + 1))
        merged: list[tuple[int, int]] = []
        for a, b in runs_of([f for f, v in enumerate(ons[id(s)]) if v]):
            end = merged[-1][1] if merged else -1
            if merged and (stayed(end + 1, a - 1) or (a - end - 1 <= flicker and not cut_to_another(s, end, a))):
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        s.stretches = merged
        for (_, end), (back, _) in zip(merged, merged[1:]):
            (s.back_at if others_on(s, end + 1, back - 1) else s.back_alone).append(back)
        sites = list(s.places.values())
        s.twice = runs_of([f for f in range(len(ons[id(s)])) if sum(1 for site in sites if site[f]) >= 2])


def cards(look: str) -> tuple[list[reel_looks.LookPhoto], int]:
    """The post's photos as black cards (as many as the look takes, in the shapes its photos come in: Axis's upright, any
    other look's wide, upright and 4:5 in turn) and how many fillers it takes."""
    slots = reel_looks.SLOTS[look]
    if look in reel_looks.PORTRAITS_ONLY:
        shapes, rooms = [UPRIGHT[k % len(UPRIGHT)] for k in range(slots.photos)], [reel_looks.PORTRAIT] * slots.photos
    else:
        shapes = [SHAPES[k % len(SHAPES)] for k in range(slots.photos)]
        rooms = [ROOMS[k % len(ROOMS)] for k in range(slots.photos)]
    return [reel_looks.LookPhoto(Image.new("RGB", wh, "black"), room) for wh, room in zip(shapes, rooms)], slots.fillers


def silence(path: Path, seconds: int = 30) -> Path:
    """A silent track the length of any look: the props carry one, and the check renders no sound."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * seconds)
    return path


def frames_of(folder: Path) -> list[Image.Image]:
    return [Image.open(p).convert("L") for p in sorted(folder.glob("*.png"))]


def shares(base: Sequence[Image.Image], lit: Sequence[Image.Image]) -> list[float]:
    """For each frame, the share of it where the white render differs from the black one: how much of the card shows."""
    if len(base) != len(lit) or not base:
        raise RuntimeError(f"the renders differ in length ({len(base)} and {len(lit)} frames)")
    out = []
    for a, b in zip(base, lit):
        d = ImageChops.difference(a, b).point(lambda v: 255 if v > CHANGED else 0)
        out.append(d.histogram()[255] / (a.width * a.height))
    return out


def on_screen(base: Sequence[Image.Image], lit: Sequence[Image.Image]) -> list[bool]:
    """For each frame: does the white card show (more than ON of the frame differs)?"""
    return [s > ON for s in shares(base, lit)]


def places_of(said: str) -> dict[tuple[str, int], set[str]]:
    """{(kind, slot): the places in the look's code that asked for it}, from the probe's console."""
    out: dict[tuple[str, int], set[str]] = {}
    for kind, k, site in PROBED.findall(said):
        out.setdefault((kind, int(k)), set()).add(site)
    return out


def presence_of(said: str) -> dict[tuple[str, int], list[bool]]:
    """{(kind, slot): each frame its card is inside the frame}, from a 3D style's probe (the same from every tab)."""
    return {(kind, int(k)): [c == "1" for c in bits] for kind, k, bits in PRESENT.findall(said)}


def cells_of(said: str) -> dict[tuple[str, int], set[str]]:
    """{(kind, slot): the cells its card has on a still grid}, from a 3D style's probe."""
    out: dict[tuple[str, int], set[str]] = {}
    for kind, k, at in CELLS.findall(said):
        out.setdefault((kind, int(k)), set()).add(at)
    return out


def check(look: str, *, work: Path, run: Callable = run_remotion, log: Callable[[str], None] = print,
          keep: bool = False) -> Report:
    """Render `look` with a card in every slot and report each slot's passes, its repeats, any slot shown in two places at
    once or never shown, and the slots back with nothing between. `work` holds the renders; a look that will not render
    is a failed report, said why. `keep`: leave each render's frames in `work`, for a frame map."""
    if look in reels3d.STYLES:
        return check_style(look, work=work, run=run, log=log, keep=keep)
    if look not in reel_looks.LOOKS:
        raise ValueError(f"no reel look {look!r}; one of {', '.join(reel_looks.LOOKS)}")
    work = Path(work) / look
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    photos, n_fillers = cards(look)
    filler_dir = work / "filler-cards"
    filler_dir.mkdir()
    fillers = []
    for k in range(n_fillers):
        path = filler_dir / f"f{k}.jpg"
        Image.new("RGB", SHAPES[k % len(SHAPES)], "black").save(path, "JPEG")
        fillers.append(reel_looks.Filler(k, path))
    public = work / "public"
    track = music.LookTrack(silence(work / "silence.wav"), 0.0, 1.0)
    try:
        props = reel_looks.props(look, photos, plan=reel_looks.Plan(lines=1, track=track), fillers=fillers, public=public)
    except Exception as e:  # noqa: BLE001  the suite's own props refused the look: the check fails, said why
        return Report(look, [], f"the props could not be made: {type(e).__name__}: {e}")
    for x in props["photos"] + props["fillers"]:          # each slot's white card, beside its black one
        with Image.open(public / x["src"]) as im:
            Image.new("RGB", im.size, "white").save(public / x["src"].replace(".jpg", "-lit.jpg"), "JPEG")

    def render(name: str, check_: Optional[dict], *, scale: float = SCALE, verbose: bool = False):
        given = public / f"props-{name}.json"
        given.write_text(json.dumps({**props, **({"check": check_} if check_ else {})}))
        out = work / name
        cmd = [node_tool("npx"), "remotion", "render", "src/index.ts", reel_looks.COMPOSITION[look], str(out),
               f"--props={given}", f"--public-dir={public}", "--sequence", "--image-format=png", f"--scale={scale}",
               f"--concurrency={reel_looks.CONCURRENCY}", f"--log={'verbose' if verbose else 'error'}",
               f"--timeout={reel_looks.ASSET_WAIT_MS}"]
        r = run(cmd, cwd=str(reel_looks.REEL_LOOKS), timeout=RENDER_TIMEOUT)
        if r.returncode != 0:
            said = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError(f"remotion stopped with code {r.returncode}: {' '.join(said[-3:])[:400]}")
        if verbose:
            shutil.rmtree(out, ignore_errors=True)
            return (r.stdout or "") + (r.stderr or "")
        got = frames_of(out)
        if not keep:
            shutil.rmtree(out, ignore_errors=True)
        if len(got) != reel_looks.FRAMES[look]:
            raise RuntimeError(f"the render left {len(got)} frames; the look runs {reel_looks.FRAMES[look]}")
        return got

    names = [("photos", k, f"photo {k}") for k in range(len(props["photos"]))] + \
            [("fillers", k, f"filler {k}") for k in range(len(props["fillers"]))]
    slots: list[Slot] = []
    try:
        log(f"{look}: {len(names)} slots; the probe")
        asked = places_of(render("probe", {"probe": True}, scale=PROBE_SCALE, verbose=True))
        if not asked:
            raise RuntimeError("the probe heard from no slot: the look's console did not reach the check")
        log(f"{look}: the black render")
        base = render("black", None)
        for kind, k, name in names:
            places, seen = {}, {}
            for n, site in enumerate(sorted(asked.get((kind, k), ()))):
                log(f"{look}: {name} white at {site}")
                seen[site] = shares(base, render(f"{kind}-{k}-{n}", {"light": {"kind": kind, "index": k, "site": site}}))
                places[site] = [v > ON for v in seen[site]]
            slots.append(Slot(name, places, seen))
    except Exception as e:  # noqa: BLE001  a look that will not render fails the check, said why
        return Report(look, slots, f"{type(e).__name__}: {e}")
    find_repeats(slots)
    return Report(look, slots)


def style_cards(style: str, work: Path) -> tuple[list[motion.Shot], list[reels3d.Filler]]:
    """A 3D style's slots as black cards: the post's photos (as many as a reel takes at the most, in the shapes his
    photos come in) and the fillers the style shows with them (the loop is offered LOOP_OFFER; its grid keeps the ones
    it lays)."""
    shots = [motion.Shot(Image.new("RGB", SHAPES[k % len(SHAPES)], "black"), ROOMS[k % len(ROOMS)].upper(), "A line.")
             for k in range(PHOTOS_3D)]
    wanted = reels3d.fillers_wanted(style, len(shots))
    folder = work / "filler-cards"
    folder.mkdir(parents=True)
    fillers = []
    for k in range(reels3d.LOOP_OFFER if wanted is None else wanted):
        path = folder / f"f{k}.jpg"
        Image.new("RGB", SHAPES[(k * 5 + 1) % len(SHAPES)], "black").save(path, "JPEG")
        fillers.append(reels3d.Filler(k, path))
    return shots, fillers


def bit_planes(lit: Sequence[Image.Image], inverse: Sequence[Image.Image], bit: int,
               codes: list[Image.Image], valid: list[Image.Image]) -> None:
    """One bit of every pixel's number, from a render and its inverse (grey frames), added into `codes` and `valid` (one
    of each a frame): a pixel brighter in the render by more than CHANGED_3D reads 1, darker 0; one that reads neither (no
    card, or two cards half and half) is no longer valid."""
    if len(lit) != len(inverse) or len(lit) != len(codes):
        raise RuntimeError(f"the renders differ in length ({len(lit)}, {len(inverse)} and {len(codes)} frames)")
    for f, (a, b) in enumerate(zip(lit, inverse)):
        one = ImageChops.subtract(a, b).point(lambda v: 255 if v > CHANGED_3D else 0)
        zero = ImageChops.subtract(b, a).point(lambda v: 255 if v > CHANGED_3D else 0)
        codes[f] = ImageChops.add(codes[f], one.point(lambda v, w=1 << bit: w if v else 0))
        valid[f] = ImageChops.multiply(valid[f], ImageChops.lighter(one, zero))


def check_style(style: str, *, work: Path, run: Callable = run_remotion, log: Callable[[str], None] = print,
                keep: bool = False) -> Report:
    """`check` for a 3D style: its slots numbered, every place found from 2 x bits renders (the module's note)."""
    work = Path(work) / style
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shots, fillers = style_cards(style, work)
    public = work / "public"
    try:
        props, fillers = reels3d.staged(style, shots, fillers=fillers, music=silence(work / "silence.wav"), public=public)
    except Exception as e:  # noqa: BLE001  the suite's own props refused the style: the check fails, said why
        return Report(style, [], f"the props could not be made: {type(e).__name__}: {e}")
    for x in props["photos"] + props["fillers"]:          # each slot's white card, beside its black one
        with Image.open(public / x["src"]) as im:
            Image.new("RGB", im.size, "white").save(public / x["src"].replace(".jpg", "-lit.jpg"), "JPEG")

    def render(name: str, check_: dict, *, scale: float = SCALE, verbose: bool = False):
        given = public / f"props-{name}.json"
        given.write_text(json.dumps({**props, "check": check_}))
        out = work / name
        cmd = [node_tool("npx"), "remotion", "render", "src/Root.tsx", reels3d.COMPOSITION[style], str(out),
               f"--props={given}", f"--public-dir={public}", "--sequence", "--image-format=png", f"--scale={scale}",
               "--gl=angle", f"--concurrency={reel_looks.CONCURRENCY}", f"--log={'verbose' if verbose else 'error'}",
               f"--timeout={reels3d.ASSET_WAIT_MS}"]
        r = run(cmd, cwd=str(reels3d.REELS3D), timeout=RENDER_TIMEOUT)
        if r.returncode != 0:
            said = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError(f"remotion stopped with code {r.returncode}: {' '.join(said[-3:])[:400]}")
        if verbose:
            shutil.rmtree(out, ignore_errors=True)
            return (r.stdout or "") + (r.stderr or "")
        got = frames_of(out)
        if not keep:
            shutil.rmtree(out, ignore_errors=True)
        if len(got) != reels3d.TOTAL:
            raise RuntimeError(f"the render left {len(got)} frames; the style runs {reels3d.TOTAL}")
        return got

    try:
        log(f"{style}: {len(props['photos'])} photos and {len(props['fillers'])} fillers; the probe")
        said = render("probe", {"probe": True}, scale=PROBE_SCALE, verbose=True)
        asked, present, cells = places_of(said), presence_of(said), cells_of(said)
        if not asked:
            raise RuntimeError("the probe heard from no slot: the style's console did not reach the check")
        places = sorted((kind, k, site) for (kind, k), sites in asked.items() for site in sites)
        if len(places) > 255:
            raise RuntimeError(f"{len(places)} places: more than a frame's grey can number")
        numbers = {f"{kind} {k} {site}": n for n, (kind, k, site) in enumerate(places)}
        bits = max(1, (len(places) - 1).bit_length())
        codes: list[Image.Image] = []
        valid: list[Image.Image] = []
        for bit in range(bits):
            log(f"{style}: {len(places)} places, bit {bit + 1} of {bits}")
            lit = render(f"bit{bit}", {"codes": numbers, "bit": bit})
            inverse = render(f"bit{bit}-inverse", {"codes": numbers, "bit": bit, "inverse": True})
            if not codes:
                codes = [Image.new("L", im.size, 0) for im in lit]
                valid = [Image.new("L", im.size, 255) for im in lit]
            bit_planes(lit, inverse, bit, codes, valid)
    except Exception as e:  # noqa: BLE001  a style that will not render fails the check, said why
        return Report(style, [], f"{type(e).__name__}: {e}")
    area = codes[0].width * codes[0].height
    counts = [c.histogram(mask=v) for c, v in zip(codes, valid)]
    slots: list[Slot] = []
    for kind, k in sorted({(kind, k) for kind, k, _ in places}, key=lambda x: (x[0] != "photos", x[1])):
        seen = {site: [n[numbers[f"{kind} {k} {site}"]] / area for n in counts] for kind_, k_, site in places
                if (kind_, k_) == (kind, k)}
        slots.append(Slot(f"{'photo' if kind == 'photos' else 'filler'} {k}", {site: [v > ON_3D for v in on] for site, on in seen.items()},
                          seen, present=present.get((kind, k)), cells=cells.get((kind, k), set())))
    shown = {(kind, k) for kind, k, _ in places}
    slots += [Slot(f"{'photo' if kind == 'photos' else 'filler'} {k}", {}) for kind, n in (("photos", len(props["photos"])), ("fillers", len(fillers)))
              for k in range(n) if (kind, k) not in shown]          # a slot the probe never heard: never shown
    find_repeats(slots, still_there=STILL_THERE_3D)
    return Report(style, slots)


def table(reports: Sequence[Report]) -> str:
    """One line a look: its slots, how often pictures came on screen, its repeats, the pictures it showed twice at once
    and the slots it never showed; under it each failure, and the pictures back with nothing between (for Chris)."""
    lines = [f"{'look':<12} {'slots':>5} {'shown':>5} {'repeats':>7} {'twice':>5}  never shown  result"]
    for r in reports:
        d = r.as_dict()
        lines.append(f"{r.look:<12} {d['slots']:>5} {d['appearances']:>5} {len(r.repeats):>7} {len(r.twice):>5}  "
                     f"{', '.join(r.never_shown) or '-':<11}  {'pass' if r.ok else 'FAIL'}")
        for text in d["repeats"] + d["twice_at_once"] + [f"{n} in two cells of the grid" for n in d["in_two_cells"]]:
            lines.append(f"{'':<12} {text}")
        for text in d["back_with_nothing_between"]:
            lines.append(f"{'':<12} for Chris: {text}, no other picture between")
        if r.error:
            lines.append(f"{'':<12} {r.error}")
    return "\n".join(lines)


def run_checks(looks: Sequence[str], *, work: Path, keep: bool = False, run: Callable = run_remotion,
               log: Callable[[str], None] = print, recording: bool = False) -> list[Report]:
    """Check each look (or 3D style) in turn; the reports, also written to `work`/reel-check.json. The renders are removed
    unless kept. `recording`: each one that passes recorded in its registry (registry_of) on the hash its sources had
    when its check began."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    reports = []
    for look in looks:
        source = source_hash(look)
        reports.append(check(look, work=work, run=run, log=log, keep=keep))
        if recording and record(reports[-1].as_dict(), source):
            log(f"{look}: recorded in {registry_of(look).relative_to(reel_looks.REEL_LOOKS.parent)}")
        (work / "reel-check.json").write_text(json.dumps([r.as_dict() for r in reports], indent=1))
        if not keep:
            shutil.rmtree(work / look, ignore_errors=True)
    return reports


def looks_named(names: Optional[Sequence[str]]) -> list[str]:
    """The looks and 3D styles asked for, every one of them when none is named; an unknown name is an error."""
    every = [*reel_looks.LOOKS, *reels3d.STYLES]
    if not names:
        return every
    unknown = [n for n in names if n not in every]
    if unknown:
        raise ValueError(f"no reel look or 3D style {', '.join(unknown)}; one of {', '.join(every)}")
    return list(names)
