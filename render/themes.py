"""Discord theme palettes.

The values come from the Discord client's own interface variables. Card,
background and text colours are kept separate so the grid image sits in the
chat window at the same tone as everything around it.
"""
from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    label: str
    background: RGB      # chat background
    card: RGB            # video card
    card_hover: RGB      # thin card border
    text: RGB            # title
    muted: RGB           # channel / meta line
    accent: RGB          # highlights, index badge
    live: RGB            # live badge
    pill_bg: RGB         # duration pill background
    pill_text: RGB


THEMES: dict[str, Theme] = {
    "dark": Theme(
        key="dark",
        label="Dark",
        background=(49, 51, 56),
        card=(43, 45, 49),
        card_hover=(60, 63, 69),
        text=(242, 243, 245),
        muted=(181, 186, 193),
        accent=(88, 101, 242),
        live=(237, 66, 69),
        pill_bg=(0, 0, 0),
        pill_text=(255, 255, 255),
    ),
    "light": Theme(
        key="light",
        label="Light",
        background=(255, 255, 255),
        card=(242, 243, 245),
        card_hover=(227, 229, 232),
        text=(6, 6, 7),
        muted=(78, 80, 88),
        accent=(88, 101, 242),
        live=(217, 45, 32),
        pill_bg=(0, 0, 0),
        pill_text=(255, 255, 255),
    ),
    "ash": Theme(
        key="ash",
        label="Ash",
        background=(35, 36, 40),
        card=(30, 31, 34),
        card_hover=(43, 45, 49),
        text=(219, 222, 225),
        muted=(148, 155, 164),
        accent=(110, 122, 247),
        live=(242, 63, 67),
        pill_bg=(0, 0, 0),
        pill_text=(255, 255, 255),
    ),
    "onyx": Theme(
        key="onyx",
        label="Onyx",
        background=(11, 12, 14),
        card=(19, 20, 22),
        card_hover=(31, 33, 36),
        text=(230, 232, 235),
        muted=(138, 143, 152),
        accent=(122, 133, 255),
        live=(255, 78, 82),
        pill_bg=(0, 0, 0),
        pill_text=(255, 255, 255),
    ),
}

DEFAULT = "dark"


def get(key: str | None) -> Theme:
    if not key:
        return THEMES[DEFAULT]
    return THEMES.get(key.strip().lower(), THEMES[DEFAULT])


def names() -> list[str]:
    return list(THEMES)
