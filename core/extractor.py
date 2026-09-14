"""ytInitialData extractor.

Instead of the official Data API we read the state tree YouTube embeds in
the page. That tree changes constantly, so rather than following fixed
paths we walk it and collect every "renderer" node we recognise; a layout
change then degrades a field instead of breaking the parser outright.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Iterator

import config
from core import i18n
from core.http import INITIAL_DATA_RE, BlockedError, NotFoundError, session
from core.models import Channel, Video

log = logging.getLogger("ytplug.extractor")

# Shared with the fetch layer so the "is this a real page?" test and the parse
# agree; otherwise a body can pass the fetch check and then fail to parse with
# no retry left.
_INITIAL_DATA_RE = INITIAL_DATA_RE
_VIDEO_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")
_CHANNEL_ID_RE = re.compile(r"(UC[A-Za-z0-9_-]{22})")

SEARCH_URL = "https://www.youtube.com/results"
TRENDING_URL = "https://www.youtube.com/feed/trending"
OEMBED_URL = "https://www.youtube.com/oembed"

# Search filters (YouTube's "sp" parameter, a base64 protobuf)
FILTER_LIVE = "EgJAAQ%3D%3D"
FILTER_VIDEO = "EgIQAQ%3D%3D"
FILTER_CHANNEL = "EgIQAg%3D%3D"
# sort: view count + uploaded: this week + type: video — this is what makes the
# trending fallback below behave like a "what is big right now" feed.
FILTER_TOP_WEEK = "CAMSBAgDEAE%3D"

# Seeds live in config, per region: measured, `gl` alone barely changes the
# most-viewed-this-week results, but a seed word in the region's own language
# changes them completely. See config.trending_seeds().


def _locale(region: str | None) -> dict[str, str]:
    """Region code -> the hl/gl query pair every page fetch needs."""
    code = (region or config.DEFAULT_REGION).upper()
    return {"hl": config.language_of(code), "gl": code}


# --------------------------------------------------------------------------
# Raw JSON extraction
# --------------------------------------------------------------------------
def extract_initial_data(html: str) -> dict[str, Any]:
    """Returns the page's ytInitialData object as a dict."""
    match = _INITIAL_DATA_RE.search(html)
    if not match:
        raise BlockedError("ytInitialData not found")
    decoder = json.JSONDecoder()
    start = html.find("{", match.end())
    if start == -1:
        raise BlockedError("ytInitialData body is malformed")
    try:
        data, _ = decoder.raw_decode(html[start:])
    except json.JSONDecodeError as exc:
        raise BlockedError(f"ytInitialData could not be decoded: {exc}") from exc
    return data


def walk(node: Any, key: str) -> Iterator[dict[str, Any]]:
    """Yields every node in the tree carrying the given key, in order."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, dict):
                yield v
            else:
                yield from walk(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, key)


def walk_any(node: Any, keys: tuple[str, ...]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Multi-key version of walk(); yields the node together with its key."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in keys and isinstance(v, dict):
                yield k, v
            else:
                yield from walk_any(v, keys)
    elif isinstance(node, list):
        for item in node:
            yield from walk_any(item, keys)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def text_of(node: Any) -> str:
    """Flattens the simpleText / runs / content shapes into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(filter(None, (text_of(item) for item in node)))
    if isinstance(node, dict):
        # The viewModel headers keep their text two lists deep:
        # contentMetadataViewModel -> metadataRows[] -> metadataParts[] ->
        # text.content. Without these the node flattened to "" and the channel
        # header lost its subscriber count entirely.
        for rows in ("metadataRows", "metadataParts"):
            if rows in node:
                return text_of(node[rows])
        if "simpleText" in node:
            return str(node["simpleText"])
        if "content" in node and isinstance(node["content"], str):
            return node["content"]
        if "runs" in node and isinstance(node["runs"], list):
            return "".join(str(r.get("text", "")) for r in node["runs"])
        for wrapper in ("text", "title", "label", "accessibilityText"):
            if wrapper in node:
                return text_of(node[wrapper])
    return ""


# Localised magnitude suffixes: en K/M/B, tr B/Mn/Mr, de Tsd/Mio/Mrd, fr k/M/Md.
_VIEW_SUFFIXES = (
    ("mrd", 1_000_000_000), ("mio", 1_000_000), ("tsd", 1_000),
    ("bn", 1_000_000_000), ("mn", 1_000_000), ("md", 1_000_000_000),
    ("b", 1_000_000_000), ("m", 1_000_000), ("k", 1_000),
)
_VIEW_NUMBER_RE = re.compile(r"([\d][\d.,   ]*)\s*([A-Za-zÄäÖöÜüß]*)")


def parse_view_count(text: str) -> int:
    """'146M views' / '1,2 Mn görüntüleme' / '1.3K watching' -> 146000000 / 1200000 / 1300.

    Needed because view counts only ever arrive as localised strings, and the
    trending fallback has to rank videos coming from several searches against
    each other. Anything unparseable scores 0 and simply sorts last.
    """
    match = _VIEW_NUMBER_RE.search(text or "")
    if not match:
        return 0

    digits = re.sub(r"[   ]", "", match.group(1)).strip()
    word = match.group(2).lower()
    multiplier = next((m for prefix, m in _VIEW_SUFFIXES if word.startswith(prefix)), 1)

    if multiplier > 1:
        # "1,2 Mn" and "1.2M" both mean 1.2 — with a suffix present the final
        # separator is a decimal point, never a thousands grouper.
        normalised = digits.replace(",", ".")
        if normalised.count(".") > 1:
            head, _, tail = normalised.rpartition(".")
            normalised = head.replace(".", "") + "." + tail
        try:
            return int(float(normalised) * multiplier)
        except ValueError:
            return 0

    # No suffix: every separator is a thousands grouper.
    plain = re.sub(r"[^\d]", "", digits)
    return int(plain) if plain else 0


def duration_to_seconds(value: str) -> int:
    """'1:02:03' -> 3723. Returns 0 when unparseable."""
    value = value.strip()
    if not value or not re.fullmatch(r"[\d:]+", value):
        return 0
    parts = [int(p) for p in value.split(":") if p != ""]
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def absolute(url: str) -> str:
    """YouTube hands out protocol-relative URLs; make them fetchable."""
    url = str(url or "")
    return f"https:{url}" if url.startswith("//") else url


def _images_in(node: Any) -> list[dict[str, Any]]:
    """Every image candidate under a node, old and new layout alike."""
    images: list[dict[str, Any]] = []
    # Old layout: thumbnail.thumbnails[]  /  new layout: image.sources[]
    for key, field in (("thumbnail", "thumbnails"), ("image", "sources")):
        for holder in walk(node, key):
            candidates = holder.get(field)
            if isinstance(candidates, list):
                images.extend(c for c in candidates if isinstance(c, dict) and c.get("url"))
    return images


def best_thumbnail(node: Any) -> str:
    """Picks the widest thumbnail URL."""
    thumbs = _images_in(node)
    if not thumbs:
        return ""
    best = max(thumbs, key=lambda t: t.get("width", 0) or 0)
    return absolute(best["url"])


# Avatar holders, in order of preference. The first two are the old search
# layout, the rest cover the lockup/view-model rewrite.
_AVATAR_KEYS = (
    "channelThumbnailWithLinkRenderer",
    "channelThumbnailSupportedRenderers",
    "decoratedAvatarViewModel",
    "avatarViewModel",
    "channelAvatar",
)


def channel_avatar(node: Any) -> str:
    """Channel avatar URL for a video node; empty when the node carries none.

    The plain thumbnail walk cannot be reused here: it would happily return
    the video still. So the search is scoped to the avatar holders, and any
    image wider than 200 px is rejected as "that's the video, not a face".
    """
    for key in _AVATAR_KEYS:
        for holder in walk(node, key):
            images = [i for i in _images_in(holder) if (i.get("width") or 0) <= 200]
            if not images:
                images = _images_in(holder)
            if images:
                best = max(images, key=lambda t: t.get("width", 0) or 0)
                return absolute(best["url"])
    return ""


def _video_id_from(node: dict[str, Any]) -> str:
    for field in ("videoId", "contentId"):
        value = node.get(field)
        if isinstance(value, str) and len(value) == 11:
            return value
    for endpoint in walk(node, "watchEndpoint"):
        vid = endpoint.get("videoId")
        if isinstance(vid, str):
            return vid
    for meta in walk(node, "commandMetadata"):
        url = meta.get("webCommandMetadata", {}).get("url", "")
        found = _VIDEO_ID_RE.search(str(url))
        if found:
            return found.group(1)
    return ""


def _badges_text(node: dict[str, Any]) -> str:
    chunks: list[str] = []
    for badge in walk(node, "metadataBadgeRenderer"):
        chunks.append(text_of(badge.get("label")))
        chunks.append(str(badge.get("style", "")))
    for overlay in walk(node, "thumbnailOverlayTimeStatusRenderer"):
        chunks.append(str(overlay.get("style", "")))
        chunks.append(text_of(overlay.get("text")))
    for badge in walk(node, "badgeViewModel"):
        chunks.append(str(badge.get("badgeStyle", "")))
    for badge in walk(node, "thumbnailBadgeViewModel"):
        chunks.append(str(badge.get("badgeStyle", "")))
        chunks.append(text_of(badge.get("text")))
    return " ".join(c for c in chunks if c).upper()


def _urls_in(node: dict[str, Any]) -> str:
    parts: list[str] = []
    for meta in walk(node, "commandMetadata"):
        parts.append(str(meta.get("webCommandMetadata", {}).get("url", "")))
    for endpoint in walk(node, "reelWatchEndpoint"):
        parts.append("/shorts/" + str(endpoint.get("videoId", "")))
    return " ".join(parts)


def _channel_of(node: dict[str, Any]) -> tuple[str, str]:
    """Best effort (channel name, channel id) pair."""
    for key in ("ownerText", "longBylineText", "shortBylineText"):
        holder = node.get(key)
        if holder:
            name = text_of(holder)
            if name:
                cid = ""
                for endpoint in walk(holder, "browseEndpoint"):
                    cid = str(endpoint.get("browseId", ""))
                    if cid:
                        break
                return name, cid
    for byline in walk(node, "lockupMetadataViewModel"):
        name = text_of(byline.get("metadata"))
        if name:
            return name.split("\n")[0], ""
    return "", ""


# --------------------------------------------------------------------------
# Renderer -> Video
# --------------------------------------------------------------------------
_VIEW_WORDS = ("view", "görüntüleme", "izlenme", "aufrufe", "vues", "vue")
_AGO_WORDS = ("ago", "önce", "vor ", "il y a")


def parse_video_node(
    kind: str, node: dict[str, Any], lang: str = config.DEFAULT_LANGUAGE
) -> Video | None:
    """videoRenderer / gridVideoRenderer / reelItemRenderer / lockupViewModel."""
    video_id = _video_id_from(node)
    if not video_id:
        return None

    title = text_of(node.get("title")) or text_of(node.get("headline"))
    if not title:
        for vm in walk(node, "lockupMetadataViewModel"):
            title = text_of(vm.get("title"))
            if title:
                break
    if not title:
        for access in walk(node, "accessibilityData"):
            title = str(access.get("label", "")).strip()
            if title:
                break

    badges = _badges_text(node)
    urls = _urls_in(node)

    duration = text_of(node.get("lengthText"))
    if not duration:
        # Old layout: thumbnailOverlayTimeStatusRenderer
        # New layout (lockupViewModel): thumbnailBadgeViewModel
        for key in ("thumbnailOverlayTimeStatusRenderer", "thumbnailBadgeViewModel"):
            for overlay in walk(node, key):
                candidate = text_of(overlay.get("text")).strip()
                if re.fullmatch(r"[\d:]+", candidate):
                    duration = candidate
                    break
            if duration:
                break
    seconds = duration_to_seconds(duration)

    # Badge text is localised, so match the label in every region we serve
    # alongside the style constant (which is always English).
    is_live = any(word in badges for word in ("LIVE", "CANLI", "DIRECT"))
    is_upcoming = any(word in badges for word in ("UPCOMING", "YAKINDA", "DEMNÄCHST"))

    channel_name, channel_id = _channel_of(node)

    if not title:
        if is_live and channel_name:
            # Broadcasters often leave a 24/7 stream untitled. Dropping the node
            # made the stream vanish from results with no explanation, so name
            # it after its channel instead — localised to the search region.
            title = i18n.t("live_stream_title", lang, channel=channel_name)
        else:
            # A node we cannot name (ad / promo box) should not take a grid slot.
            return None

    views = text_of(node.get("shortViewCountText")) or text_of(node.get("viewCountText"))
    published = text_of(node.get("publishedTimeText"))
    if not views or not published:
        for row in walk(node, "contentMetadataViewModel"):
            for part in walk(row, "text"):
                content = text_of(part)
                low = content.lower()
                if not views and any(w in low for w in _VIEW_WORDS):
                    views = content
                elif not published and any(w in low for w in _AGO_WORDS):
                    published = content

    video = Video(
        video_id=video_id,
        title=title,
        channel=channel_name,
        channel_id=channel_id,
        duration="" if is_live else duration,
        duration_seconds=seconds,
        views=views,
        published=published,
        thumbnail=best_thumbnail(node) or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        avatar=channel_avatar(node),
        is_live=is_live,
        is_upcoming=is_upcoming,
    )
    video.is_short = is_shorts(kind, node, video, badges, urls)
    return video


def is_shorts(kind: str, node: dict[str, Any], video: Video, badges: str, urls: str) -> bool:
    """Shorts detection: combines several hints rather than trusting one."""
    if kind in ("reelItemRenderer", "shortsLockupViewModel"):
        return True
    if "/shorts/" in urls:
        return True
    if "SHORTS" in badges:
        return True
    if "REEL" in json.dumps(node.get("navigationEndpoint", {}))[:400].upper():
        return True

    # Duration hint: anything up to 3 minutes could be a Short, but that alone
    # is not enough — we only decide once a vertical thumbnail agrees.
    if 0 < video.duration_seconds <= 180:
        for key, field in (("thumbnail", "thumbnails"), ("image", "sources")):
            for holder in walk(node, key):
                for thumb in holder.get(field, []) or []:
                    if not isinstance(thumb, dict):
                        continue
                    width, height = thumb.get("width") or 0, thumb.get("height") or 0
                    if width and height and height > width:
                        return True
    return False


VIDEO_KINDS = (
    "videoRenderer",
    "gridVideoRenderer",
    "compactVideoRenderer",
    "playlistVideoRenderer",
    # The queue panel beside a video. This is the only place a YouTube Mix
    # (list=RD...) exists — the /playlist page returns nothing for those.
    "playlistPanelVideoRenderer",
    "reelItemRenderer",
    "shortsLockupViewModel",
    "lockupViewModel",
)


def collect_videos(data: Any, lang: str = config.DEFAULT_LANGUAGE) -> list[Video]:
    """Collects every video node in the tree, preserving page order."""
    seen: set[str] = set()
    videos: list[Video] = []
    for kind, node in walk_any(data, VIDEO_KINDS):
        video = parse_video_node(kind, node, lang)
        if video is None or video.video_id in seen:
            continue
        seen.add(video.video_id)
        videos.append(video)
    return videos


# --------------------------------------------------------------------------
# General search
# --------------------------------------------------------------------------
def continuation_token(data: Any) -> str:
    """Continuation token for the next page (empty when there is none)."""
    for holder in walk(data, "continuationItemRenderer"):
        for command in walk(holder, "continuationCommand"):
            token = command.get("token")
            if isinstance(token, str) and token:
                return token
    return ""


async def search(
    query: str,
    limit: int = 9,
    *,
    region: str | None = None,
    live_only: bool = False,
    include_shorts: bool = False,
    max_pages: int = 1,
    sp: str | None = None,
) -> list[Video]:
    """Search results.

    The first page comes from HTML; if `limit` is not filled we page through
    innertube/search with the continuation token. `max_pages` caps both the
    request count and any runaway loop. `sp` overrides the search filter for
    callers that need their own sort or date window (see `trending`).
    """
    locale = _locale(region)
    params: dict[str, str] = {"search_query": query, **locale}
    if sp:
        params["sp"] = sp
    elif live_only:
        params["sp"] = FILTER_LIVE
    elif not include_shorts:
        params["sp"] = FILTER_VIDEO

    def keep(items: list[Video]) -> list[Video]:
        if live_only:
            items = [v for v in items if v.is_live]
        if not include_shorts:
            items = [v for v in items if not v.is_short]
        return items

    html = await session.get_text(SEARCH_URL, params=params, lang=locale["hl"])
    data = extract_initial_data(html)

    seen: set[str] = set()
    videos: list[Video] = []
    for video in keep(collect_videos(data, locale["hl"])):
        if video.video_id not in seen:
            seen.add(video.video_id)
            videos.append(video)

    token = continuation_token(data)
    page = 1
    while len(videos) < limit and token and page < max_pages:
        try:
            data = await session.innertube(
                "search", {"continuation": token}, region=locale["gl"]
            )
        except BlockedError as exc:
            # Even when pagination fails we keep the results already in hand.
            log.warning("pagination stopped at page %s: %s", page + 1, exc)
            break

        fresh = [v for v in keep(collect_videos(data, locale["hl"])) if v.video_id not in seen]
        if not fresh:
            break
        for video in fresh:
            seen.add(video.video_id)
            videos.append(video)

        token = continuation_token(data)
        page += 1

    return videos[:limit]


# --------------------------------------------------------------------------
# Trending (!home / !discover)
# --------------------------------------------------------------------------
async def _trending_page(region: str | None) -> list[Video]:
    """The real /feed/trending page, if YouTube still serves one."""
    locale = _locale(region)
    html = await session.get_text(TRENDING_URL, params=locale, lang=locale["hl"])
    data = extract_initial_data(html)
    return [v for v in collect_videos(data, locale["hl"]) if not v.is_short]


async def _top_of_week(region: str | None, limit: int) -> list[Video]:
    """Most-watched videos of the week, assembled from broad seed searches.

    Each seed is a language-neutral stop-word, so with FILTER_TOP_WEEK applied
    it returns a slice of this week's most-viewed videos rather than a topic.
    The slices are merged, de-duplicated by id and re-ranked by parsed view
    count, which is what makes one coherent chart out of several searches.
    """
    per_seed = max(limit, config.RESULTS_PER_PAGE)
    seeds = config.trending_seeds(region)
    results = await asyncio.gather(
        *(
            search(seed, limit=per_seed, region=region, sp=FILTER_TOP_WEEK, max_pages=2)
            for seed in seeds
        ),
        return_exceptions=True,
    )

    # Rank inside each seed, then interleave — do NOT rank the merged pool.
    # Ranking everything together defeats the whole point: the region seed
    # returns local channels with a few million views, and a global blockbuster
    # with sixty million buries all of them, which is how !home ended up
    # showing the same worldwide videos in every region. Round-robin keeps the
    # region's own seed at the top while the broad seeds still contribute.
    lanes: list[list[Video]] = []
    for seed, result in zip(seeds, results):
        if isinstance(result, BaseException):
            log.warning("trending seed %r failed: %s", seed, result)
            continue
        lanes.append(
            sorted(result, key=lambda v: parse_view_count(v.views), reverse=True)
        )

    merged: list[Video] = []
    seen: set[str] = set()
    for row in range(max((len(lane) for lane in lanes), default=0)):
        for lane in lanes:
            if row >= len(lane):
                continue
            video = lane[row]
            if video.video_id in seen:
                continue
            seen.add(video.video_id)
            merged.append(video)
            if len(merged) >= limit:
                return merged
    return merged


async def trending(region: str | None = None, limit: int = 54) -> list[Video]:
    """A trending feed for the region, Shorts filtered out.

    YouTube retired the anonymous /feed/trending page — it now redirects to the
    personalised home feed, which is empty without a watch history, and the
    `FEtrending` browse id answers 400. So the page is still tried first (if it
    ever comes back we get the real thing for free) and otherwise the feed is
    built from this week's most-viewed videos.
    """
    try:
        videos = await _trending_page(region)
        if videos:
            return videos[:limit]
        log.info("trending page returned nothing; falling back to top-of-week")
    except BlockedError as exc:
        log.info("trending page unavailable (%s); falling back to top-of-week", exc)

    return await _top_of_week(region, limit)


# --------------------------------------------------------------------------
# Single external link (!pa)
# --------------------------------------------------------------------------
def video_id_from_url(url: str) -> str:
    """Pulls the 11-character id out of any YouTube URL shape."""
    found = _VIDEO_ID_RE.search(url)
    if found:
        return found.group(1)
    bare = url.strip()
    return bare if re.fullmatch(r"[A-Za-z0-9_-]{11}", bare) else ""


async def video_from_link(url: str) -> Video | None:
    """Resolves a plain watch link into a Video via the oEmbed endpoint.

    oEmbed needs no API key and answers in one round trip. If it refuses we
    still return a usable Video so the link can be queued — only the title
    degrades.
    """
    video_id = video_id_from_url(url)
    if not video_id:
        return None

    title = f"External YouTube Video ({video_id})"
    channel = ""
    try:
        raw = await session.get_raw_text(
            OEMBED_URL,
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
        )
        payload = json.loads(raw)
        title = str(payload.get("title") or title)
        channel = str(payload.get("author_name") or "")
    except (BlockedError, json.JSONDecodeError, ValueError) as exc:
        log.debug("oembed failed for %s: %s", video_id, exc)

    return Video(
        video_id=video_id,
        title=title,
        channel=channel,
        thumbnail=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )


# --------------------------------------------------------------------------
# Channel resolution and feeds
# --------------------------------------------------------------------------
async def resolve_channel_url(query: str, *, region: str | None = None) -> str:
    """Turns a handle / URL / channel name into a channel page URL."""
    query = query.strip()

    if query.startswith("http"):
        base = query.split("?")[0].rstrip("/")
        for suffix in ("/videos", "/streams", "/shorts", "/featured", "/about"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base

    if query.startswith("@"):
        return f"https://www.youtube.com/{query}"

    found = _CHANNEL_ID_RE.fullmatch(query)
    if found:
        return f"https://www.youtube.com/channel/{query}"

    # Search by name: take the first channel result
    locale = _locale(region)
    html = await session.get_text(
        SEARCH_URL,
        params={"search_query": query, "sp": FILTER_CHANNEL, **locale},
        lang=locale["hl"],
    )
    data = extract_initial_data(html)
    for kind in ("channelRenderer", "gridChannelRenderer"):
        for node in walk(data, kind):
            for endpoint in walk(node, "browseEndpoint"):
                canonical = endpoint.get("canonicalBaseUrl")
                if canonical:
                    return f"https://www.youtube.com{canonical}"
                browse_id = endpoint.get("browseId", "")
                if browse_id.startswith("UC"):
                    return f"https://www.youtube.com/channel/{browse_id}"
    raise LookupError(f"no channel found for `{query}`")


def _channel_header(data: Any, fallback_url: str) -> Channel:
    name = ""
    handle = ""
    subs = ""
    channel_id = ""
    avatar = ""

    for header in walk(data, "pageHeaderViewModel"):
        name = name or text_of(header.get("title"))
        # The avatar used to be read only out of c4TabbedHeaderRenderer, which
        # YouTube no longer sends for channel pages — so every !cs card fell
        # back to the drawn initial. The new header carries it at 160x160 under
        # decoratedAvatarViewModel, which channel_avatar() already knows how to
        # find; it just was never asked.
        avatar = avatar or channel_avatar(header)
        for row in walk(header, "contentMetadataViewModel"):
            # Each part is read on its own, so the subscriber count does not
            # arrive glued to the handle and the video count. The flattened row
            # is the fallback: if YouTube reshapes this again, the field
            # degrades to one long string instead of disappearing.
            parts = [text_of(part)
                     for group in row.get("metadataRows", [])
                     for part in group.get("metadataParts", [])]
            for blob in parts or [text_of(row)]:
                if "@" in blob and not handle:
                    match = re.search(r"@[\w.\-]+", blob)
                    if match:
                        handle = match.group(0)
                low = blob.lower()
                # tr "abone", de "Abonnenten", fr "abonnés" — "abonn" covers
                # the last two, "abone" the Turkish one.
                if not subs and ("subscriber" in low or "abone" in low
                                 or "abonn" in low):
                    subs = blob.strip()
    for header in walk(data, "c4TabbedHeaderRenderer"):
        name = name or text_of(header.get("title"))
        handle = handle or text_of(header.get("channelHandleText"))
        subs = subs or text_of(header.get("subscriberCountText"))
        channel_id = channel_id or str(header.get("channelId", ""))
        avatar = avatar or best_thumbnail(header.get("avatar", {}))

    if not channel_id:
        found = _CHANNEL_ID_RE.search(fallback_url)
        if found:
            channel_id = found.group(1)
        else:
            for meta in walk(data, "metadata"):
                found = _CHANNEL_ID_RE.search(str(meta.get("externalId", "")))
                if found:
                    channel_id = found.group(1)
                    break
    if not name:
        for meta in walk(data, "channelMetadataRenderer"):
            name = text_of(meta.get("title"))
            if name:
                break
    if not handle and "/@" in fallback_url:
        handle = "@" + fallback_url.split("/@", 1)[1].split("/")[0]

    return Channel(
        channel_id=channel_id,
        name=name or handle or "Unknown channel",
        handle=handle,
        subscribers=subs,
        avatar=avatar,
    )


def _stamp_channel(channel: Channel, videos: list[Video]) -> None:
    """Fills in the per-video channel fields the tab page leaves empty."""
    for video in videos:
        if not video.channel:
            video.channel = channel.name
        if not video.channel_id:
            video.channel_id = channel.channel_id
        if not video.avatar:
            video.avatar = channel.avatar


async def channel_videos(query: str, limit: int = 9, *, region: str | None = None) -> Channel:
    """The channel's newest long-form videos (Shorts filtered out)."""
    locale = _locale(region)
    base = await resolve_channel_url(query, region=region)
    html = await session.get_text(f"{base}/videos", params=locale, lang=locale["hl"])
    data = extract_initial_data(html)

    channel = _channel_header(data, base)
    videos = [v for v in collect_videos(data, locale["hl"]) if not v.is_short]

    # The /videos tab sometimes returns few results; YouTube already hands it
    # to us in reverse-chronological order, so we do not re-sort.
    _stamp_channel(channel, videos)

    if not videos:
        # Channels that only ever go live (24/7 radios, stream-only creators)
        # have an empty /videos tab. Falling back to the broadcast archive is
        # the difference between a useful answer and "no videos found".
        log.info("%s has an empty /videos tab, falling back to /streams", base)
        html = await session.get_text(f"{base}/streams", params=locale, lang=locale["hl"])
        stream_data = extract_initial_data(html)
        videos = [v for v in collect_videos(stream_data, locale["hl"]) if not v.is_short]
        _stamp_channel(channel, videos)

    channel.videos = videos[:limit]
    if not channel.videos:
        raise LookupError(f"no videos or broadcasts on the **{channel.name}** channel")
    return channel


async def channel_live(query: str, limit: int = 9, *, region: str | None = None) -> Channel:
    """The channel's live / past-broadcast tab."""
    locale = _locale(region)
    base = await resolve_channel_url(query, region=region)
    html = await session.get_text(f"{base}/streams", params=locale, lang=locale["hl"])
    data = extract_initial_data(html)
    channel = _channel_header(data, base)
    videos = [v for v in collect_videos(data, locale["hl"]) if not v.is_short]
    _stamp_channel(channel, videos)
    channel.videos = videos[:limit]
    return channel


class PrivatePlaylist(LookupError):
    """The playlist exists but is private or unlisted, so it cannot be read."""


# Auto-generated "Mix" / radio lists. These have no static playlist page — the
# only place they exist is the queue panel next to a video, so they are read
# from the watch page instead.
_MIX_PREFIXES = ("RD", "UL", "PU")

def _unavailable_reason(data: Any) -> str:
    """The page's own error text, if YouTube put one there.

    Read from `alertRenderer` rather than by searching the raw HTML: those
    phrases also live in the page's localised JS string tables, so a substring
    match reports "private" for pages that are merely empty.
    """
    for alert in walk(data, "alertRenderer"):
        text = text_of(alert.get("text"))
        if text:
            return text
    for alert in walk(data, "alertWithButtonRenderer"):
        text = text_of(alert.get("text"))
        if text:
            return text
    return ""


def is_mix_id(playlist_id: str) -> bool:
    return playlist_id.upper().startswith(_MIX_PREFIXES)


def _playlist_title(data: Any, fallback: str) -> str:
    """Playlist title, from wherever YouTube is putting it this week.

    `playlistHeaderRenderer` is no longer sent and `pageHeaderViewModel.title`
    comes back empty, so the microformat block is the one that still carries it.
    """
    for meta in walk(data, "microformatDataRenderer"):
        title = str(meta.get("title") or "").strip()
        if title:
            return title
    for header in walk(data, "playlistHeaderRenderer"):
        title = text_of(header.get("title"))
        if title:
            return title
    for header in walk(data, "pageHeaderViewModel"):
        title = text_of(header.get("title"))
        if title:
            return title
    return fallback


async def _mix_videos(
    playlist_id: str, limit: int, locale: dict[str, str]
) -> tuple[str, list[Video]]:
    """Reads a Mix from the watch page's queue panel."""
    # RD<videoId> mixes are seeded by a video; anything else still needs a `v`,
    # so the id's tail is the best guess available.
    seed = playlist_id[2:] if len(playlist_id) >= 13 else ""
    params = {"list": playlist_id, **locale}
    if len(seed) == 11:
        params["v"] = seed

    html = await session.get_text(
        "https://www.youtube.com/watch", params=params, lang=locale["hl"]
    )
    data = extract_initial_data(html)

    title = ""
    for panel in walk(data, "playlistPanelRenderer"):
        title = text_of(panel.get("title"))
        if title:
            break
    if not title:
        for panel in walk(data, "playlist"):
            title = text_of(panel.get("title"))
            if title:
                break

    videos: list[Video] = []
    seen: set[str] = set()
    for _, node in walk_any(data, ("playlistPanelVideoRenderer",)):
        video = parse_video_node("playlistPanelVideoRenderer", node, locale["hl"])
        if video is None or video.video_id in seen:
            continue
        seen.add(video.video_id)
        videos.append(video)

    return title or playlist_id, videos[:limit]


async def playlist_videos(
    playlist_id: str,
    limit: int = config.PLAYLIST_MAX_ITEMS,
    *,
    region: str | None = None,
) -> tuple[str, list[Video]]:
    """Title and videos for a playlist id.

    Handles both real playlists (PL…) and auto-generated Mixes (RD…). An empty
    result is retried: YouTube sometimes serves a page that parses fine but
    carries no items, and giving up on the first try was what produced the
    "Could not extract videos" reports.
    """
    playlist_id = playlist_id.strip()
    locale = _locale(region)

    if is_mix_id(playlist_id):
        return await _mix_videos(playlist_id, limit, locale)

    reason = ""
    for attempt in range(config.MAX_RETRIES):
        try:
            html = await session.get_text(
                "https://www.youtube.com/playlist",
                params={"list": playlist_id, **locale},
                lang=locale["hl"],
            )
        except NotFoundError as exc:
            # A 404 is the answer, not a failure to get one.
            raise PrivatePlaylist(f"playlist not found ({exc})") from exc
        data = extract_initial_data(html)
        videos = collect_videos(data, locale["hl"])
        if videos:
            return _playlist_title(data, playlist_id), videos[:limit]

        # Nothing parsed. An alert on the page means it will never parse, so
        # stop rather than burning retries on a private or deleted list.
        reason = _unavailable_reason(data)
        if reason:
            log.info("playlist %s unavailable: %s", playlist_id, reason)
            break
        log.info("playlist %s came back empty, retrying (%s)", playlist_id, attempt + 1)

    if reason:
        raise PrivatePlaylist(reason)
    return playlist_id, []
