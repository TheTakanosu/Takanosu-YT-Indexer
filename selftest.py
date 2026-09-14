"""Verifies the extractor + grid engine without connecting to Discord.

Usage:  python selftest.py
Output: data/exports/selftest_<theme>.png
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Video titles are full of emoji and the Windows console defaults to cp1252,
# where a single "☕" aborts the whole run. Force UTF-8 and never let a
# character stop a diagnostic.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core import extractor, i18n
from core.http import BlockedError, session
from render import themes
from render.grid import installed_fonts, render_grid
from vault import export as m3u_export
from vault import spotify

# A well-known public playlist, used only to confirm the embed scraper still
# finds Spotify's __NEXT_DATA__ payload.
SPOTIFY_PROBE = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


def _check_m3u_contract(videos: list) -> int:
    """Guards the two rules the client-side mpv setup depends on.

    Both were broken before: audio entries carried a `?ytdl_format=bestaudio`
    query that yt-dlp rejects outright, which made every track in every audio
    export unplayable. A silent regression here breaks playback with no error
    the bot can see, so it is asserted rather than eyeballed.
    """
    problems: list[str] = []
    audio = m3u_export.build_m3u("selftest", videos, audio_only=True)

    # 1. ghost.lua only reads the first 256 bytes looking for the marker.
    head = audio.encode("utf-8")[:256]
    if b"#GHOST_AUDIO" not in head:
        problems.append("#GHOST_AUDIO is not inside the first 256 bytes")

    # 2. mpv passes everything after ytdl:// to yt-dlp verbatim.
    for line in audio.splitlines():
        if line.startswith("ytdl://") and "?" in line:
            problems.append(f"audio entry carries a query string: {line}")
            break

    for spotify_line in m3u_export.build_search_m3u(
        [("Artist", "Track")], audio_only=True
    ).splitlines():
        if spotify_line.startswith("ytdl://") and not spotify_line.startswith(
            "ytdl://ytsearch1:"
        ):
            problems.append(f"spotify entry is not a ytsearch1 query: {spotify_line}")

    for problem in problems:
        print(f"-> m3u contract FAILED: {problem}")
    if not problems:
        print("-> m3u contract: marker in range, no query strings, ytsearch1 intact")
    return len(problems)


async def main() -> int:
    failures = 0

    # Which face each weight resolved to. Worth printing every run: a missing
    # Roboto silently drops titles onto a heavier fallback, which is a visible
    # regression with no error attached.
    print("-> fonts")
    for weight, path in installed_fonts().items():
        name = Path(path).name if path != "bitmap fallback" else path
        print(f"   {weight:8} {name}")
        if path == "bitmap fallback":
            failures += 1

    # A key missing from a language degrades to English silently, so the gap is
    # only ever visible if something checks for it.
    print("-> translations")
    gaps = i18n.coverage()
    print(f"   {len(i18n.STRINGS)} keys x {len(config.LANGUAGES)} languages")
    if gaps:
        for language, keys in gaps.items():
            print(f"   {language}: {len(keys)} missing -> {', '.join(keys[:5])}")
        failures += 1
    else:
        print("   no gaps")

    try:
        print("-> search: 'lofi hip hop radio'")
        videos = await extractor.search(
            "lofi hip hop radio", limit=config.RESULTS_PER_PAGE
        )
        with_avatar = sum(1 for v in videos if v.avatar)
        print(f"   {len(videos)} results, Shorts filtered, {with_avatar} with avatar")
        for v in videos[:3]:
            print(f"    - [{v.duration or 'LIVE':>7}] {v.title[:52]} — {v.channel}")
        if not videos:
            failures += 1

        print("-> channel feed: '@YouTube'")
        channel = await extractor.channel_videos("@YouTube", limit=config.RESULTS_PER_PAGE)
        print(f"   {channel.name} ({channel.subscribers or 'no subscriber info'}) "
              f"-> {len(channel.videos)} long-form videos")
        escaped = [v for v in channel.videos if v.is_short]
        print(f"   Shorts that slipped through the filter: {len(escaped)}")

        print("-> trending feed")
        try:
            trending = await extractor.trending(limit=config.RESULTS_PER_PAGE)
            print(f"   {len(trending)} trending videos")
            if not trending:
                failures += 1
        except BlockedError as exc:
            print(f"   FAILED: {exc}")
            failures += 1

        print("-> live search: 'news'")
        try:
            live = await extractor.search("news", limit=9, live_only=True)
            print(f"   {len(live)} live streams")
        except BlockedError as exc:
            print(f"   skipped: {exc}")

        print("-> external link (oEmbed)")
        if videos:
            resolved = await extractor.video_from_link(videos[0].url)
            print(f"   {resolved.title[:60] if resolved else 'FAILED'}")
            if resolved is None:
                failures += 1

        print("-> spotify embed scraper")
        try:
            parsed = spotify.parse_link(SPOTIFY_PROBE)
            name, tracks = await spotify.fetch_tracks(parsed[1], parsed[0], limit=5)
            print(f"   '{name}' -> {len(tracks)} tracks, first: "
                  f"{tracks[0][0]} - {tracks[0][1]}" if tracks else "   no tracks")
        except spotify.SpotifyError as exc:
            print(f"   FAILED: {exc.code}")
            failures += 1

        if videos:
            for theme in themes.names():
                png = await render_grid(
                    videos, theme_key=theme,
                    header="lofi hip hop radio",
                    subheader=f"{len(videos)} results  •  theme: {theme}",
                )
                path = config.EXPORT_DIR / f"selftest_{theme}.png"
                path.write_bytes(png)
                print(f"-> grid [{theme:5}] {len(png) / 1024:6.1f} KB  {path}")

            for audio in (False, True):
                m3u = m3u_export.build_m3u("selftest", videos, audio_only=audio)
                kind = "audio" if audio else "video"
                first = m3u.splitlines()[2 if audio else 1]
                print(f"-> m3u [{kind}] {len(m3u.splitlines())} lines, first entry: {first[:60]}")

            failures += _check_m3u_contract(videos)
    except Exception as exc:  # noqa: BLE001 - diagnostic entry point
        print(f"ERROR: {type(exc).__name__}: {exc}")
        failures += 1
    finally:
        await session.close()

    print("RESULT:", "passed" if failures == 0 else f"{failures} step(s) failed")
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
