"""The four logo options as SVG (Chris picks one; BRAND_MARK, default viewfinder).

Each is drawn for a dark ground; `fill` swaps the light parts for a light ground.
The wordmark text uses the site's own Michroma / Big Shoulders / Syne / Unbounded faces.
"""
from __future__ import annotations

from html import escape

CYAN = "#00E1FF"
GREY = "#8C8C93"


def _viewfinder(name: str, light: str, size: int, word: bool) -> str:
    first, _, rest = name.upper().partition(" ")
    corners = (f'<g fill="none" stroke="{light}" stroke-width="7" stroke-linecap="square">'
               '<path d="M24 64 V24 H64"/><path d="M136 24 H176 V64"/><path d="M24 136 V176 H64"/><path d="M176 136 V176 H136"/></g>'
               f'<circle cx="128" cy="72" r="11" fill="{CYAN}"/>')
    if not word:
        return f'<svg viewBox="0 0 200 200" width="{size}" height="{size}" role="img" aria-label="{escape(name)}">{corners}</svg>'
    return (f'<svg viewBox="0 0 640 200" height="{size}" role="img" aria-label="{escape(name)}">{corners}'
            f'<text x="222" y="96" font-family="Michroma" font-size="44" fill="{GREY}" letter-spacing="10">{escape(first)}</text>'
            f'<text x="222" y="152" font-family="Michroma" font-size="44" fill="{light}" letter-spacing="10">{escape(rest or first)}</text></svg>')


def _aperture(name: str, light: str, size: int, word: bool) -> str:
    ring = (f'<path d="M150 52 A62 62 0 1 0 150 148" fill="none" stroke="{light}" stroke-width="20"/>'
            f'<path d="M150 52 A62 62 0 0 1 162 66" fill="none" stroke="{GREY}" stroke-width="20"/><circle cx="104" cy="100" r="13" fill="{CYAN}"/>')
    first, _, rest = name.upper().partition(" ")
    if not word:
        return f'<svg viewBox="20 20 170 160" width="{size}" height="{size}" role="img" aria-label="{escape(name)}">{ring}</svg>'
    return (f'<svg viewBox="0 0 560 200" height="{size}" role="img" aria-label="{escape(name)}">{ring}'
            f'<text x="220" y="94" font-family="Unbounded" font-size="40" fill="{light}" letter-spacing="2">{escape(first)}</text>'
            f'<text x="220" y="146" font-family="Unbounded" font-size="40" fill="{GREY}" letter-spacing="2">{escape(rest or first)}</text></svg>')


MARKS = {"viewfinder": _viewfinder, "aperture": _aperture}


def mark(key: str, name: str, *, light: str = "#F3F3F1", size: int = 40, word: bool = True) -> str:
    return MARKS.get(key, _viewfinder)(name, light, size, word)
