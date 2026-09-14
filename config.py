"""Central settings. Every module reads its values from here."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
# Fallback prefix. Guilds can override it with !setprefix (stored in the vault DB).
COMMAND_PREFIX: str = os.getenv("COMMAND_PREFIX", "!")

DATA_DIR: Path = ROOT / os.getenv("DATA_DIR", "data")
EXPORT_DIR: Path = DATA_DIR / "exports"
DB_PATH: Path = DATA_DIR / "vault.db"

# --- Network ------------------------------------------------------------
REQUEST_TIMEOUT = 15          # seconds
MAX_CONCURRENT_REQUESTS = 8   # ceiling on simultaneous outbound requests
MIN_REQUEST_INTERVAL = 0.20   # minimum gap between consecutive requests (s)
MAX_RETRIES = 3

# --- Rate limiter -------------------------------------------------------
# Budgets are in tokens, not commands: COMMAND_COST below charges an expensive
# command more than a cheap one, so `!playlist` stays comfortable while nobody
# can flood the server with `!s`.
USER_RATE = (9, 10.0)    # 9 tokens per 10 s per user  -> 3 searches or 9 cheap commands
GUILD_RATE = (40, 15.0)  # 40 tokens per 15 s per guild

# What each command costs. A search fans out to as many as six YouTube requests,
# nine thumbnail downloads and a full-page Pillow render; !ping costs nothing
# like that, and charging them the same was the wrong shape.
DEFAULT_COMMAND_COST = 1
COMMAND_COST: dict[str, int] = {
    "s": 3, "cs": 3, "home": 3, "live": 3, "cl": 3, "v": 3,
    "spotify": 3, "spotifymp3": 3, "pa": 3, "ytlist": 3,
    "selftest": 3,
}

# --- Heavy-work gate ----------------------------------------------------
# The real ceiling on a 1 GB box is memory, not YouTube. One search holds nine
# decoded JPEGs plus a ~1200x1150 canvas while it renders, so a burst of them
# is what would actually take the bot down. Past this many at once, callers are
# told to come back instead of everyone thrashing.
MAX_CONCURRENT_RENDERS = 3
RENDER_WAIT_TIMEOUT = 20.0   # seconds a command will queue before giving up

# --- Region and language ------------------------------------------------
# Region drives *search results* (YouTube's `gl`); language drives the *bot's
# own text*. They are separate axes on purpose: someone in Türkiye may want
# Turkish results with an English interface, and US/GB share one language.
DEFAULT_REGION = "US"
DEFAULT_LANGUAGE = "en"

# The regions offered in !setregion, with the language each one implies.
REGION_LANGS: dict[str, str] = {
    "TR": "tr",
    "US": "en",
    "DE": "de",
    "GB": "en",
    "FR": "fr",
}

# Interface languages the bot is translated into.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "tr": "Türkçe",
    "de": "Deutsch",
    "fr": "Français",
}

# YouTube's `gl` expects an ISO 3166-1 alpha-2 *country* code. Anything else is
# silently ignored and the results fall back to the server's own geography —
# which is exactly how "EN" (a language code, not a country) got accepted and
# quietly broke region-aware results. Beyond the five offered above, these are
# accepted so users elsewhere are not locked out.
EXTRA_REGIONS = frozenset({
    "AE", "AR", "AT", "AU", "AZ", "BA", "BE", "BG", "BR", "CA", "CH", "CL",
    "CO", "CZ", "DK", "EE", "EG", "ES", "FI", "GE", "GR", "HR", "HU", "ID",
    "IE", "IL", "IN", "IQ", "IR", "IS", "IT", "JP", "KR", "KZ", "LT", "LU",
    "LV", "MA", "MD", "MK", "MT", "MX", "MY", "NG", "NL", "NO", "NZ", "PE",
    "PH", "PK", "PL", "PT", "QA", "RO", "RS", "RU", "SA", "SE", "SG", "SI",
    "SK", "TH", "TW", "UA", "US", "UY", "UZ", "VN", "ZA",
})

# Common mistakes worth correcting by name instead of just rejecting.
REGION_MISTAKES: dict[str, str] = {
    "EN": "GB",   # English is a language; the country people mean is usually GB
    "UK": "GB",   # not an ISO code, but everyone types it
    "TU": "TR",
    "GE": "GE",   # Georgia — kept so it is not "corrected" to Germany
}


def valid_region(code: str | None) -> bool:
    region = (code or "").strip().upper()
    return region in REGION_LANGS or region in EXTRA_REGIONS


def normalise_region(code: str | None) -> str:
    """Usable region code, falling back to the default rather than breaking.

    Stored values are run through this on read, so a bad code saved before the
    validation existed repairs itself instead of silently disabling `gl`.
    """
    region = (code or "").strip().upper()
    return region if valid_region(region) else DEFAULT_REGION


def language_of(region: str | None) -> str:
    """Region code -> the language it implies. Unknown regions mean English."""
    return REGION_LANGS.get(normalise_region(region), DEFAULT_LANGUAGE)


def normalise_language(code: str | None) -> str:
    language = (code or "").strip().lower()
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


# --- Visuals ------------------------------------------------------------
GRID_COLUMNS = 3
GRID_ROWS = 3
RESULTS_PER_PAGE = GRID_COLUMNS * GRID_ROWS
DEFAULT_THEME = "dark"

# --- Pagination ---------------------------------------------------------
MAX_SEARCH_PAGES = 5                        # max pages to walk on YouTube
MAX_RESULTS = RESULTS_PER_PAGE * 6          # max videos collected per command

# --- Trending -----------------------------------------------------------
# YouTube retired the anonymous /feed/trending page, so !home is assembled from
# "most viewed this week" searches instead. Measured: `gl` alone barely moves
# those results (US, TR and DE all led with the same global videos), but a seed
# word in the region's own language changes them completely — gl=TR + "türkiye"
# surfaces Turkish channels, gl=DE + "deutschland" surfaces WELT and DW. So the
# seeds, not the country code, are what make !home regional.
TRENDING_SEEDS: dict[str, tuple[str, ...]] = {
    "TR": ("türkiye", "video", "müzik"),
    "DE": ("deutschland", "video", "musik"),
    "FR": ("france", "vidéo", "musique"),
    "US": ("the", "video", "a"),
    "GB": ("the", "video", "uk"),
}
DEFAULT_TRENDING_SEEDS: tuple[str, ...] = ("the", "video", "a")


def trending_seeds(region: str | None) -> tuple[str, ...]:
    return TRENDING_SEEDS.get(normalise_region(region), DEFAULT_TRENDING_SEEDS)


# --- Caches and retention ----------------------------------------------
SEARCH_CACHE_TTL = 900       # smart cache lifetime for a query (s)
HISTORY_LIMIT = 50           # playback records kept per user
HISTORY_SHOW = 10            # records shown by !history
SHARE_TTL = 172800           # share token lifetime (48 h)
SPOTIFY_MAX_TRACKS = 100     # tracks read per Spotify playlist/album
# YouTube's own ceiling, not ours: measured on a 194-video list, the anonymous
# playlist page serves 100 items and offers no continuation token to go further.
PLAYLIST_MAX_ITEMS = 100

# --- Authorisation ------------------------------------------------------
# Admin commands: guild administrators plus anyone holding one of these roles.
AUTHORIZED_ROLES = ("Developer", "Community Manager", "Higher Staff")

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
