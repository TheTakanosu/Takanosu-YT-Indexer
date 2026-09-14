"""Resilient HTTP layer.

To stay clear of YouTube's bot / cookie wall:
  * a rotating User-Agent plus matching sec-ch-ua headers on every request
  * consent cookies stamped up front -> the "Before you continue" wall is skipped
  * retries with exponential backoff
  * Throttle for concurrency and pacing
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import aiohttp
from yarl import URL

import config
from core.ratelimit import Throttle

log = logging.getLogger("ytplug.http")

# Profiles that match real browser builds. A UA that contradicts sec-ch-ua is
# a bot signal on its own, so the two are always kept in sync.
BROWSER_PROFILES: list[dict[str, str]] = [
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "ch_ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        "platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "ch_ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "platform": '"macOS"',
    },
    {
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "platform": '"Linux"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) "
              "Gecko/20100101 Firefox/127.0",
        "ch_ua": "",
        "platform": '"Windows"',
    },
]

# Values that clear the cookie wall. SOCS means "the consent screen was shown
# and answered"; CONSENT=YES does the same job for the older flow.
CONSENT_COOKIES = {
    "CONSENT": "YES+cb.20240101-00-p0.en+FX+000",
    "SOCS": "CAISNQgQEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjQwMTA5LjA2X3AxGgJlbiACGgYIgLfrrwY",
    "PREF": "f6=40000000",
}

INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"  # public key of the WEB client
INNERTUBE_CLIENT_VERSION = "2.20240701.00.00"

# YouTube ships the state tree as `var ytInitialData = {...}` on most responses
# and as `window["ytInitialData"] = {...}` on others, so both are accepted.
#
# Matching the *assignment* rather than the bare name matters: a block or
# consent page can mention the name without assigning it, and checking only for
# the name let such a page through as a success — the parse then failed outside
# the retry loop, turning a transient block into a hard command failure.
INITIAL_DATA_RE = re.compile(
    r"""(?:var\s+)?(?:window\s*\[\s*["']ytInitialData["']\s*\]|ytInitialData)\s*=\s*"""
)


def innertube_context(region: str | None = None) -> dict[str, Any]:
    """Client context for youtubei/v1, localised to the caller's region."""
    code = (region or config.DEFAULT_REGION).upper()
    return {
        "client": {
            "clientName": "WEB",
            "clientVersion": INNERTUBE_CLIENT_VERSION,
            "hl": config.language_of(code),
            "gl": code,
        }
    }


class BlockedError(RuntimeError):
    """YouTube refused the request (429 / captcha / unexpected body)."""


class NotFoundError(BlockedError):
    """The resource does not exist. Retrying will never help."""


# Statuses that mean "this will never work", as opposed to "try again with a
# different identity". Retrying these burns three requests and several seconds
# of backoff to arrive at the same answer, and hands the user a message about
# giving up instead of one about the thing not existing.
PERMANENT_STATUSES = frozenset({404, 410})


class YouTubeSession:
    """Wraps a single aiohttp session and the evasion tactics around it."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._throttle = Throttle(config.MAX_CONCURRENT_REQUESTS, config.MIN_REQUEST_INTERVAL)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._session and not self._session.closed:
            return
        async with self._lock:
            if self._session and not self._session.closed:
                return
            jar = aiohttp.CookieJar()
            jar.update_cookies(CONSENT_COOKIES, response_url=URL("https://www.youtube.com"))
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT),
                connector=aiohttp.TCPConnector(
                    limit=config.MAX_CONCURRENT_REQUESTS * 2, ttl_dns_cache=300
                ),
                cookie_jar=jar,
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # -- headers ----------------------------------------------------------
    def _headers(
        self, extra: dict[str, str] | None = None, *, lang: str = "en"
    ) -> dict[str, str]:
        profile = random.choice(BROWSER_PROFILES)
        accept_language = f"{lang},{lang};q=0.9,en-US;q=0.7,en;q=0.6"
        headers = {
            "User-Agent": profile["ua"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": accept_language,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
            "sec-ch-ua-platform": profile["platform"],
        }
        if profile["ch_ua"]:
            headers["sec-ch-ua"] = profile["ch_ua"]
            headers["sec-ch-ua-mobile"] = "?0"
        if extra:
            headers.update(extra)
        return headers

    # -- core requests ----------------------------------------------------
    async def _get_body(
        self,
        url: str,
        params: dict[str, Any] | None,
        *,
        lang: str,
        require: re.Pattern[str] | None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        await self.start()
        assert self._session is not None
        last_error: Exception | None = None

        for attempt in range(config.MAX_RETRIES):
            try:
                async with self._throttle:
                    async with self._session.get(
                        url,
                        params=params,
                        headers=self._headers(extra_headers, lang=lang),
                    ) as resp:
                        if resp.status in PERMANENT_STATUSES:
                            raise NotFoundError(f"HTTP {resp.status}")
                        if resp.status in (429, 403):
                            raise BlockedError(f"HTTP {resp.status}")
                        resp.raise_for_status()
                        body = await resp.text()
                if require is not None and not require.search(body):
                    # Retryable on purpose: a fresh identity often gets a real
                    # page on the next attempt.
                    raise BlockedError("ytInitialData assignment missing (blocked?)")
                return body
            except NotFoundError:
                raise
            except (aiohttp.ClientError, BlockedError, asyncio.TimeoutError) as exc:
                last_error = exc
                backoff = (2 ** attempt) + random.random()
                log.warning("GET %s failed (%s), retrying in %.1fs", url, exc, backoff)
                if attempt + 1 < config.MAX_RETRIES:
                    await asyncio.sleep(backoff)

        raise BlockedError(f"gave up after {config.MAX_RETRIES} attempts: {last_error}")

    async def get_text(
        self, url: str, params: dict[str, Any] | None = None, *, lang: str = "en"
    ) -> str:
        """YouTube page fetch; retries when the body carries no state tree."""
        return await self._get_body(url, params, lang=lang, require=INITIAL_DATA_RE)

    async def get_raw_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        lang: str = "en",
        headers: dict[str, str] | None = None,
    ) -> str:
        """Plain HTML fetch with no YouTube-specific body check (Spotify, oEmbed)."""
        return await self._get_body(
            url, params, lang=lang, require=None, extra_headers=headers
        )

    async def innertube(
        self, endpoint: str, payload: dict[str, Any], *, region: str | None = None
    ) -> dict[str, Any]:
        """POST to youtubei/v1. Used for continuation (pagination)."""
        await self.start()
        assert self._session is not None
        url = f"https://www.youtube.com/youtubei/v1/{endpoint}"
        context = innertube_context(region)
        body = {"context": context, **payload}
        headers = self._headers(
            {
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Origin": "https://www.youtube.com",
                "Referer": "https://www.youtube.com/",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "same-origin",
                "Sec-Fetch-Site": "same-origin",
                "X-YouTube-Client-Name": "1",
                "X-YouTube-Client-Version": INNERTUBE_CLIENT_VERSION,
            },
            lang=context["client"]["hl"],
        )

        last_error: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            try:
                async with self._throttle:
                    async with self._session.post(
                        url,
                        params={"key": INNERTUBE_KEY, "prettyPrint": "false"},
                        json=body,
                        headers=headers,
                    ) as resp:
                        if resp.status in (429, 403):
                            raise BlockedError(f"HTTP {resp.status}")
                        resp.raise_for_status()
                        return await resp.json(content_type=None)
            except (aiohttp.ClientError, BlockedError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < config.MAX_RETRIES:
                    await asyncio.sleep((2 ** attempt) + random.random())

        raise BlockedError(f"innertube/{endpoint} failed: {last_error}")

    async def get_bytes(self, url: str) -> bytes | None:
        """For small binary assets (thumbnails, avatars); errors are swallowed."""
        await self.start()
        assert self._session is not None
        try:
            async with self._throttle:
                async with self._session.get(
                    url, headers=self._headers({"Accept": "image/*"})
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None


session = YouTubeSession()
