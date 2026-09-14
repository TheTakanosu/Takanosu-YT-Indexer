"""Spotify import via the Ghost Engine embed scraper.

There is no Client Credentials flow here on purpose: the Spotify developer
portal is unavailable to this deployment, so instead of the Web API we read
the public embed player at `open.spotify.com/embed/<type>/<id>`. That page
ships its whole track list inside a `__NEXT_DATA__` script tag, which means:

  * no API keys, no token refresh, nothing to expire
  * albums work as well as playlists
  * any *public* list in any market can be read

The trade-off is that a Spotify markup change breaks the scraper, so every
failure mode is reported to the user with a specific message rather than a
generic error.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit

import config
from core.http import BlockedError, session

log = logging.getLogger("ytplug.spotify")

EMBED_URL = "https://open.spotify.com/embed"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', re.DOTALL
)
_PLAYLIST_RE = re.compile(r"playlist[/:]([a-zA-Z0-9]+)")
_ALBUM_RE = re.compile(r"album[/:]([a-zA-Z0-9]+)")

# Failure codes surfaced to the command layer.
ERR_NOT_FOUND = "404_NOT_FOUND"
ERR_PRIVATE = "PRIVATE_PLAYLIST"
ERR_EMPTY = "EMPTY_PLAYLIST"
ERR_NO_JSON = "JSON_NOT_FOUND"
ERR_SYSTEM = "SYSTEM_ERROR"


class SpotifyError(RuntimeError):
    """Carries one of the ERR_* codes above."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def enabled() -> bool:
    """The scraper needs no credentials, so it is always available."""
    return True


def parse_link(value: str) -> tuple[str, str] | None:
    """`(entity_type, id)` from a Spotify playlist or album link."""
    text = value.strip()
    match = _PLAYLIST_RE.search(text)
    if match:
        return "playlist", match.group(1)
    match = _ALBUM_RE.search(text)
    if match:
        return "album", match.group(1)
    return None


def is_private_share(url: str) -> bool:
    """True when the link is the kind Spotify hands out for a *private* list.

    Measured: Spotify answers the embed endpoint with a plain 404 for a private
    playlist, exactly as it does for one that does not exist — the payload
    carries an empty entity and nothing else to tell them apart. So the one
    usable signal is on the link itself: sharing a private list adds a `pt=`
    playlist token, and sharing a public one does not.

    It only chooses the wording of a failure, so a wrong guess costs a slightly
    less precise message and never a working import.
    """
    return "pt=" in urlsplit(url).query


def parse_playlist_id(value: str) -> str | None:
    """Kept for callers that only care about playlists."""
    parsed = parse_link(value)
    return parsed[1] if parsed and parsed[0] == "playlist" else None


async def fetch_tracks(
    entity_id: str,
    entity_type: str = "playlist",
    limit: int = config.SPOTIFY_MAX_TRACKS,
    *,
    private_hint: bool = False,
) -> tuple[str, list[tuple[str, str]]]:
    """`(list name, [(artist, track), ...])` scraped from the embed player."""
    url = f"{EMBED_URL}/{entity_type}/{entity_id}"
    log.info("scraping spotify %s %s", entity_type, entity_id)

    try:
        html = await session.get_raw_text(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                          "image/avif,image/webp,*/*;q=0.8",
            },
        )
    except BlockedError as exc:
        log.warning("spotify embed fetch failed: %s", exc)
        raise SpotifyError(ERR_SYSTEM) from exc

    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise SpotifyError(ERR_NO_JSON)

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        log.warning("spotify __NEXT_DATA__ is not valid JSON: %s", exc)
        raise SpotifyError(ERR_NO_JSON) from exc

    page_props = data.get("props", {}).get("pageProps", {})
    if page_props.get("status") == 404:
        # Private and non-existent are the same 404 here; the caller's link is
        # what separates them. See is_private_share().
        raise SpotifyError(ERR_PRIVATE if private_hint else ERR_NOT_FOUND)

    entity = page_props.get("state", {}).get("data", {}).get("entity", {})
    name = entity.get("name") or entity_id
    track_list = entity.get("trackList") or []
    if not track_list:
        raise SpotifyError(ERR_EMPTY)

    tracks: list[tuple[str, str]] = []
    for item in track_list[:limit]:
        if not isinstance(item, dict):
            continue
        track = str(item.get("title") or "Unknown Track")
        artist = str(item.get("subtitle") or "Unknown Artist")
        tracks.append((artist, track))

    return str(name), tracks
