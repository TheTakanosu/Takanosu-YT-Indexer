"""Export: turns queues and vault playlists into .m3u files MPV/VLC can play.

The format matches the Ghost Engine output the client-side MPV setup expects.

Audio-only lists are switched to pure audio by the `#GHOST_AUDIO` marker on
line two, which `client/mpv/scripts/ghost.lua` looks for in the first 256
bytes of the file before setting `vid=no` and `ytdl-format=bestaudio`. Keep
that marker within those 256 bytes.

The entry URLs themselves must stay plain: mpv hands everything after
`ytdl://` to yt-dlp verbatim, so a query string like `?ytdl_format=bestaudio`
becomes part of the video id and yt-dlp rejects the whole entry with
"is not a valid URL". Verified against mpv directly.
"""
from __future__ import annotations

import datetime
import random
import re
import string
from pathlib import Path

import config
from core.models import Playlist, Video

_SAFE = re.compile(r"[^\w\-. ]+", re.UNICODE)
_COLLAPSE = re.compile(r"_+")


def safe_name(name: str, default: str = "playlist") -> str:
    """Filesystem-safe file stem for a list name."""
    cleaned = _SAFE.sub("", str(name)).strip().replace(" ", "_")
    cleaned = _COLLAPSE.sub("_", cleaned).strip("_")
    return cleaned[:60] or default


def build_m3u(name: str, videos: list[Video], *, audio_only: bool = False) -> str:
    lines = ["#EXTM3U"]
    if audio_only:
        lines.append("#GHOST_AUDIO")

    for video in videos:
        title = video.title.replace("\n", " ").strip()
        lines.append(f"#EXTINF:-1, {title}")
        if audio_only:
            # No query string here — see the module docstring. ghost.lua is what
            # forces audio-only, driven by the #GHOST_AUDIO marker above.
            lines.append(f"ytdl://{video.video_id}")
        else:
            lines.append(video.url)

    return "\n".join(lines) + "\n"


def build_search_m3u(queries: list[tuple[str, str]], *, audio_only: bool = False) -> str:
    """M3U for tracks that have no video id yet — Spotify imports.

    Each entry is handed to the player as a `ytsearch1:` query, so resolution
    happens at playback time instead of costing one YouTube request per track
    up front. yt-dlp accepts `ytsearch1:` as a URL scheme of its own, so unlike
    a query string this form survives the `ytdl://` handoff.
    """
    lines = ["#EXTM3U"]
    if audio_only:
        lines.append("#GHOST_AUDIO")

    for artist, track in queries:
        lines.append(f"#EXTINF:-1, {artist} - {track}")
        lines.append(f"ytdl://ytsearch1:{track} {artist}")

    return "\n".join(lines) + "\n"


def queue_filename(*, audio_only: bool) -> str:
    kind = "audio" if audio_only else "video"
    stamp = datetime.datetime.now().strftime("%Y.%m.%d-%H.%M")
    return f"t-playlist-{kind}-{stamp}.m3u"


def spotify_filename(playlist_name: str, *, audio_only: bool) -> str:
    kind = "audio" if audio_only else "video"
    token = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return f"t-{safe_name(playlist_name, 'Playlist')}-{kind}-{token}.m3u"


def mpv_hint(*, audio_only: bool) -> str:
    return (
        "mpv --no-video --ytdl-format=bestaudio" if audio_only else "mpv --ytdl-format=best"
    )


def write_m3u(playlist: Playlist, *, audio_only: bool = False) -> Path:
    suffix = "audio" if audio_only else "video"
    path = config.EXPORT_DIR / f"{safe_name(playlist.name)}_{playlist.share_code}_{suffix}.m3u"
    path.write_text(
        build_m3u(playlist.name, playlist.items, audio_only=audio_only), encoding="utf-8"
    )
    return path
