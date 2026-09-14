"""Pillow grid engine.

Renders search results as a single PNG in a 3x3 card layout that echoes the
YouTube home page. Thumbnails and channel avatars are fetched concurrently;
the drawing itself runs in a worker thread so the event loop never blocks.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config
from core import i18n
from core.http import session
from core.models import Video
from render.themes import Theme, get as get_theme

log = logging.getLogger("ytplug.grid")

# --- measurements (pixels) -------------------------------------------------
PAD = 26            # outer margin
GAP = 18            # gap between cards
CARD_W = 372
THUMB_H = 209       # 16:9
TEXT_H = 124
CARD_H = THUMB_H + TEXT_H
HEADER_H = 62
RADIUS = 12
AVATAR = 38         # channel avatar diameter
AVATAR_GAP = 12     # gap between avatar and the text column

# YouTube sets video titles in Roboto Medium and the channel / view-count line
# in Roboto Regular, so those are the two faces the grid asks for. The weight
# matters more than it sounds: a Bold face at title size reads heavy and
# over-wide next to the regular meta line under it, which is what made the
# earlier DejaVu-Bold titles look stretched.
#
# Each stack is tried in order and missing files are skipped, so one list
# covers Linux servers, Windows and macOS. Install Roboto where you can
# (`apt install fonts-roboto-unhinted`) — everything below it is a fallback.
FONT_STACKS: dict[str, tuple[str, ...]] = {
    "regular": (
        "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf",
        "/usr/share/fonts/truetype/roboto/hinted/Roboto-Regular.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    # Titles. Segoe UI Semibold and Liberation/DejaVu Bold stand in where no
    # true medium weight exists.
    "medium": (
        "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Medium.ttf",
        "/usr/share/fonts/truetype/roboto/hinted/Roboto-Medium.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Medium.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    # Header line and the index badge, where real weight is wanted.
    "bold": (
        "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf",
        "/usr/share/fonts/truetype/roboto/hinted/Roboto-Bold.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
}


@lru_cache(maxsize=64)
def load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    for path in FONT_STACKS.get(weight, FONT_STACKS["regular"]):
        if not Path(path).exists():
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    # Nothing in the requested weight exists: any real TrueType face beats the
    # bitmap default, which measures wrong and wrecks the wrapping.
    for stack in FONT_STACKS.values():
        for path in stack:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    log.warning("no TrueType font found; falling back to the bitmap default")
    return ImageFont.load_default(size)


def installed_fonts() -> dict[str, str]:
    """Which face each weight actually resolves to. Used by selftest."""
    return {
        weight: getattr(load_font(20, weight), "path", "bitmap fallback")
        for weight in FONT_STACKS
    }


# Segoe UI / DejaVu carry no emoji, so these ranges render as tofu boxes;
# we strip them from the title and leave a space behind.
_UNRENDERABLE = re.compile(
    "[🀀-🫿☀-➿︀-️"
    "🇦-🇿←-⇿⬀-⯿]+"
)


def sanitize(text: str) -> str:
    """Drops glyphs the font cannot draw and collapses runs of whitespace."""
    return re.sub(r"\s{2,}", " ", _UNRENDERABLE.sub(" ", text)).strip()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """Word wrapping; an overflowing last line is clipped with an ellipsis."""
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return [""]

    # Make the last line fit
    if len(lines) == max_lines:
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words) or _text_width(draw, lines[-1], font) > max_width:
            last = lines[-1]
            while last and _text_width(draw, last + "…", font) > max_width:
                last = last[:-1]
            lines[-1] = (last.rstrip() + "…") if last else "…"
    return lines


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)], radius, fill=255)
    return mask


def _circle_mask(size: int) -> Image.Image:
    """Anti-aliased circular mask: drawn at 4x then downsampled."""
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


def _fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Crop-and-fill while preserving aspect ratio (CSS object-fit: cover)."""
    target_w, target_h = size
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGB", size, (0, 0, 0))
    scale = max(target_w / src_w, target_h / src_h)
    new = img.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))), Image.LANCZOS)
    left = (new.width - target_w) // 2
    top = (new.height - target_h) // 2
    return new.crop((left, top, left + target_w, top + target_h))


def _placeholder(theme: Theme, size: tuple[int, int], lang: str) -> Image.Image:
    img = Image.new("RGB", size, theme.card_hover)
    draw = ImageDraw.Draw(img)
    font = load_font(28, "medium")
    label = i18n.t("grid_no_preview", lang)
    w = _text_width(draw, label, font)
    draw.text(((size[0] - w) // 2, size[1] // 2 - 18), label, font=font, fill=theme.muted)
    return img


def _initial_avatar(theme: Theme, channel: str) -> Image.Image:
    """Fallback avatar: the channel's first letter on an accent disc."""
    img = Image.new("RGB", (AVATAR, AVATAR), theme.accent)
    draw = ImageDraw.Draw(img)
    letter = (sanitize(channel)[:1] or "?").upper()
    font = load_font(21, "medium")
    w = _text_width(draw, letter, font)
    draw.text(((AVATAR - w) // 2, AVATAR // 2 - 14), letter, font=font, fill=(255, 255, 255))
    return img


# --------------------------------------------------------------------------
# Card drawing
# --------------------------------------------------------------------------
def _draw_card(
    canvas: Image.Image,
    origin: tuple[int, int],
    index: int,
    video: Video,
    thumb: Image.Image | None,
    avatar: Image.Image | None,
    theme: Theme,
    lang: str,
) -> None:
    x, y = origin
    card = Image.new("RGB", (CARD_W, CARD_H), theme.card)
    draw = ImageDraw.Draw(card)

    # thumbnail
    thumb_img = _fit_cover(thumb, (CARD_W, THUMB_H)) if thumb else _placeholder(theme, (CARD_W, THUMB_H), lang)
    card.paste(thumb_img, (0, 0))

    # duration / live pill
    pill_font = load_font(19, "medium")
    if video.is_live:
        pill_text, pill_bg = i18n.t("grid_live", lang), theme.live
    elif video.is_upcoming:
        pill_text, pill_bg = i18n.t("grid_upcoming", lang), theme.accent
    elif video.duration:
        pill_text, pill_bg = video.duration, theme.pill_bg
    else:
        pill_text, pill_bg = "", theme.pill_bg

    if pill_text:
        tw = _text_width(draw, pill_text, pill_font)
        pw, ph = tw + 16, 26
        px, py = CARD_W - pw - 10, THUMB_H - ph - 10
        overlay = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            [(0, 0), (pw - 1, ph - 1)], 6, fill=(*pill_bg, 235 if video.is_live else 190)
        )
        card.paste(overlay, (px, py), overlay)
        draw.text((px + 8, py + 3), pill_text, font=pill_font, fill=theme.pill_text)

    # index badge
    badge_font = load_font(20, "bold")
    badge = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(badge).rounded_rectangle([(0, 0), (31, 31)], 8, fill=(*theme.accent, 230))
    card.paste(badge, (10, 10), badge)
    label = str(index)
    draw.text((10 + (32 - _text_width(draw, label, badge_font)) // 2, 14), label,
              font=badge_font, fill=(255, 255, 255))

    # channel avatar, bottom-left of the text block
    margin = 14
    avatar_img = avatar or _initial_avatar(theme, video.channel)
    card.paste(avatar_img, (margin, THUMB_H + 16), _circle_mask(AVATAR))
    text_x = margin + AVATAR + AVATAR_GAP

    # text block
    # Medium, not bold: this is the line that looked stretched before.
    title_font = load_font(21, "medium")
    meta_font = load_font(18, "regular")
    text_w = CARD_W - text_x - margin
    cursor = THUMB_H + 12

    for line in wrap(draw, sanitize(video.title), title_font, text_w, 2):
        draw.text((text_x, cursor), line, font=title_font, fill=theme.text)
        cursor += 26

    channel = sanitize(video.channel) or "—"
    if _text_width(draw, channel, meta_font) > text_w:
        channel = wrap(draw, channel, meta_font, text_w, 1)[0]
    draw.text((text_x, cursor + 2), channel, font=meta_font, fill=theme.muted)
    cursor += 24

    meta_parts = [p for p in (video.views, video.published) if p]
    meta = "  •  ".join(meta_parts)
    if meta:
        meta = wrap(draw, meta, meta_font, text_w, 1)[0]
        draw.text((text_x, cursor + 2), meta, font=meta_font, fill=theme.muted)

    # rounded-corner mask, then drop onto the background
    canvas.paste(card, (x, y), _rounded_mask((CARD_W, CARD_H), RADIUS))


def _render_sync(videos: list[Video], thumbs: list[Image.Image | None],
                 avatars: list[Image.Image | None], theme: Theme,
                 header: str, subheader: str, lang: str) -> bytes:
    cols, rows = config.GRID_COLUMNS, config.GRID_ROWS
    used_rows = max(1, -(-len(videos) // cols))
    width = PAD * 2 + cols * CARD_W + (cols - 1) * GAP
    height = PAD * 2 + HEADER_H + used_rows * CARD_H + (used_rows - 1) * GAP

    canvas = Image.new("RGB", (width, height), theme.background)
    draw = ImageDraw.Draw(canvas)

    draw.text((PAD, PAD - 4), sanitize(header), font=load_font(30, "bold"), fill=theme.text)
    if subheader:
        draw.text((PAD, PAD + 30), sanitize(subheader), font=load_font(18, "regular"), fill=theme.muted)
    draw.line([(PAD, PAD + HEADER_H - 12), (width - PAD, PAD + HEADER_H - 12)],
              fill=theme.card_hover, width=2)

    for i, video in enumerate(videos):
        col, row = i % cols, i // cols
        x = PAD + col * (CARD_W + GAP)
        y = PAD + HEADER_H + row * (CARD_H + GAP)
        _draw_card(canvas, (x, y), i + 1, video, thumbs[i], avatars[i], theme, lang)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def _fetch_image(url: str) -> Image.Image | None:
    raw = await session.get_bytes(url) if url else None
    if raw is None:
        return None
    try:
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # corrupt / unsupported image
        log.debug("could not open image %s: %s", url, exc)
        return None


async def _fetch_thumb(video: Video) -> Image.Image | None:
    img = await _fetch_image(video.thumbnail)
    if img is None:
        img = await _fetch_image(f"https://i.ytimg.com/vi/{video.video_id}/hqdefault.jpg")
    return img


async def _fetch_avatars(videos: list[Video]) -> list[Image.Image | None]:
    """Fetches each distinct avatar once.

    A channel feed (!cs) is nine videos from one channel — deduplicating by
    URL turns nine downloads into one.
    """
    urls = {v.avatar for v in videos if v.avatar}
    if not urls:
        return [None] * len(videos)

    ordered = list(urls)
    images = await asyncio.gather(*(_fetch_image(u) for u in ordered))
    by_url = dict(zip(ordered, images))
    resized = {
        url: img.resize((AVATAR, AVATAR), Image.LANCZOS)
        for url, img in by_url.items()
        if img is not None
    }
    return [resized.get(v.avatar) for v in videos]


async def render_grid(
    videos: list[Video],
    *,
    theme_key: str = config.DEFAULT_THEME,
    header: str = "Results",
    subheader: str = "",
    lang: str = config.DEFAULT_LANGUAGE,
) -> bytes:
    """Renders the videos into a PNG byte string."""
    videos = videos[: config.RESULTS_PER_PAGE]
    theme = get_theme(theme_key)
    thumbs, avatars = await asyncio.gather(
        asyncio.gather(*(_fetch_thumb(v) for v in videos)),
        _fetch_avatars(videos),
    )
    return await asyncio.to_thread(
        _render_sync, videos, list(thumbs), list(avatars), theme, header,
        subheader, lang,
    )
