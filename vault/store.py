"""Persistent state on SQLite: queues, vault playlists, history, shares, settings.

The original Ghost Engine kept all of this in JSON files (`sessions.json`,
`user_history.json`, `shared_playlists.json`, `guild_settings.json`) with the
live queue in RAM. Here SQLite is the single source of truth, so a queue
survives a bot restart on its own.

sqlite3 is synchronous, so every call runs in a worker thread via
asyncio.to_thread and the bot's event loop never blocks.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import string
import time
from datetime import datetime, timezone

import config
from core.models import Playlist, Video

_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
_SHARE_ALPHABET = string.ascii_uppercase + string.digits

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'manual',
    share_code  TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    video_id    TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    channel     TEXT    NOT NULL DEFAULT '',
    duration    TEXT    NOT NULL DEFAULT '',
    seconds     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (playlist_id, position)
);
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER PRIMARY KEY,
    theme   TEXT NOT NULL DEFAULT 'dark'
);
CREATE TABLE IF NOT EXISTS queue (
    user_id   INTEGER NOT NULL,
    position  INTEGER NOT NULL,
    video_id  TEXT    NOT NULL,
    title     TEXT    NOT NULL,
    channel   TEXT    NOT NULL DEFAULT '',
    avatar    TEXT    NOT NULL DEFAULT '',
    thumbnail TEXT    NOT NULL DEFAULT '',
    duration  TEXT    NOT NULL DEFAULT '',
    seconds   INTEGER NOT NULL DEFAULT 0,
    views     TEXT    NOT NULL DEFAULT '',
    published TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, position)
);
CREATE TABLE IF NOT EXISTS history (
    user_id    INTEGER NOT NULL,
    position   INTEGER NOT NULL,
    title      TEXT    NOT NULL,
    url        TEXT    NOT NULL,
    watched_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, position)
);
CREATE TABLE IF NOT EXISTS shares (
    token      TEXT    PRIMARY KEY,
    owner_id   INTEGER NOT NULL,
    payload    TEXT    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id       INTEGER PRIMARY KEY,
    locked_channel INTEGER,
    prefix         TEXT
);
CREATE INDEX IF NOT EXISTS idx_playlists_owner ON playlists(owner_id);
CREATE INDEX IF NOT EXISTS idx_shares_owner ON shares(owner_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _new_code(conn: sqlite3.Connection) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        if not conn.execute("SELECT 1 FROM playlists WHERE share_code = ?", (code,)).fetchone():
            return code


# --------------------------------------------------------------------------
# Synchronous bodies
# --------------------------------------------------------------------------
def _init() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        # `settings` predates per-user regions; add the column in place so
        # existing theme choices are not thrown away.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
        if "region" not in columns:
            conn.execute(
                "ALTER TABLE settings ADD COLUMN region TEXT NOT NULL DEFAULT "
                f"'{config.DEFAULT_REGION}'"
            )
        if "language" not in columns:
            conn.execute(
                "ALTER TABLE settings ADD COLUMN language TEXT NOT NULL DEFAULT ''"
            )


# -- vault playlists -------------------------------------------------------
def _save(owner_id: int, name: str, source: str, videos: list[Video]) -> Playlist:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        code = _new_code(conn)
        cur = conn.execute(
            "INSERT INTO playlists (owner_id, name, source, share_code, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (owner_id, name, source, code, now),
        )
        playlist_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO items (playlist_id, position, video_id, title, channel, duration, seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (playlist_id, i, v.video_id, v.title, v.channel, v.duration, v.duration_seconds)
                for i, v in enumerate(videos)
            ],
        )
    return Playlist(playlist_id, owner_id, name, source, code, now, list(videos))


def _rows_to_videos(rows: list[sqlite3.Row]) -> list[Video]:
    return [
        Video(
            video_id=r["video_id"],
            title=r["title"],
            channel=r["channel"],
            duration=r["duration"],
            duration_seconds=r["seconds"],
        )
        for r in rows
    ]


def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> Playlist:
    items = conn.execute(
        "SELECT * FROM items WHERE playlist_id = ? ORDER BY position", (row["id"],)
    ).fetchall()
    return Playlist(
        playlist_id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        source=row["source"],
        share_code=row["share_code"],
        created_at=row["created_at"],
        items=_rows_to_videos(items),
    )


def _list(owner_id: int) -> list[Playlist]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM playlists WHERE owner_id = ? ORDER BY id DESC", (owner_id,)
        ).fetchall()
        return [_hydrate(conn, r) for r in rows]


def _get(owner_id: int, ref: str) -> Playlist | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM playlists WHERE share_code = ?", (ref.upper(),)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM playlists WHERE owner_id = ? AND lower(name) = lower(?) "
                "ORDER BY id DESC LIMIT 1",
                (owner_id, ref),
            ).fetchone()
        return _hydrate(conn, row) if row else None


def _get_by_code(code: str) -> Playlist | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM playlists WHERE share_code = ?", (code.upper(),)
        ).fetchone()
        return _hydrate(conn, row) if row else None


def _resolve_ref(owner_id: int, ref: str) -> Playlist | None:
    """Dual input: a share code, a playlist name, or its 1-based vault position.

    The Ghost Engine let `!loadpl 2` mean "the second entry in !vault", and
    users lean on that, so the numeric form is resolved against the same
    newest-first ordering `!vault` prints.
    """
    ref = ref.strip()
    if ref.isdigit():
        playlists = _list(owner_id)
        index = int(ref) - 1
        return playlists[index] if 0 <= index < len(playlists) else None
    return _get(owner_id, ref)


def _delete(owner_id: int, ref: str) -> str | None:
    """Deletes by code / name / position; returns the deleted name."""
    playlist = _resolve_ref(owner_id, ref)
    if playlist is None or playlist.owner_id != owner_id:
        return None
    with _connect() as conn:
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist.playlist_id,))
        conn.execute("DELETE FROM items WHERE playlist_id = ?", (playlist.playlist_id,))
    return playlist.name


def _rename(owner_id: int, ref: str, new_name: str) -> tuple[str, str] | None:
    """Renames by code / name / position; returns (old name, new name).

    Renaming rather than delete-and-save keeps the share code, so a
    `GHOST-XXXXXX` already posted in chat still resolves after a typo is fixed.
    """
    playlist = _resolve_ref(owner_id, ref)
    if playlist is None or playlist.owner_id != owner_id:
        return None
    with _connect() as conn:
        conn.execute(
            "UPDATE playlists SET name = ? WHERE id = ?",
            (new_name, playlist.playlist_id),
        )
    return playlist.name, new_name


def _append(owner_id: int, ref: str, videos: list[Video]) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM playlists WHERE owner_id = ? AND (share_code = ? OR lower(name) = lower(?)) "
            "ORDER BY id DESC LIMIT 1",
            (owner_id, ref.upper(), ref),
        ).fetchone()
        if row is None:
            return -1
        start = conn.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) AS n FROM items WHERE playlist_id = ?",
            (row["id"],),
        ).fetchone()["n"]
        conn.executemany(
            "INSERT OR IGNORE INTO items "
            "(playlist_id, position, video_id, title, channel, duration, seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (row["id"], start + i, v.video_id, v.title, v.channel, v.duration, v.duration_seconds)
                for i, v in enumerate(videos)
            ],
        )
        return len(videos)


# -- queue -----------------------------------------------------------------
_QUEUE_COLUMNS = (
    "video_id", "title", "channel", "avatar", "thumbnail",
    "duration", "seconds", "views", "published",
)


def _queue_row(user_id: int, position: int, video: Video) -> tuple:
    return (
        user_id, position, video.video_id, video.title, video.channel,
        video.avatar, video.thumbnail, video.duration, video.duration_seconds,
        video.views, video.published,
    )


def _get_queue(user_id: int) -> list[Video]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM queue WHERE user_id = ? ORDER BY position", (user_id,)
        ).fetchall()
    return [
        Video(
            video_id=r["video_id"],
            title=r["title"],
            channel=r["channel"],
            avatar=r["avatar"],
            thumbnail=r["thumbnail"],
            duration=r["duration"],
            duration_seconds=r["seconds"],
            views=r["views"],
            published=r["published"],
        )
        for r in rows
    ]


def _set_queue(user_id: int, videos: list[Video]) -> None:
    """Rewrites the whole queue. Positions stay dense, so reorder/remove
    operations never leave gaps for the next append to trip over."""
    placeholders = ", ".join(["?"] * (len(_QUEUE_COLUMNS) + 2))
    with _connect() as conn:
        conn.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))
        conn.executemany(
            f"INSERT INTO queue (user_id, position, {', '.join(_QUEUE_COLUMNS)}) "
            f"VALUES ({placeholders})",
            [_queue_row(user_id, i, v) for i, v in enumerate(videos)],
        )


def _append_queue(user_id: int, videos: list[Video]) -> int:
    current = _get_queue(user_id)
    _set_queue(user_id, current + list(videos))
    return len(current) + len(videos)


# -- history ---------------------------------------------------------------
def _log_history(user_id: int, title: str, url: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT title, url, watched_at FROM history WHERE user_id = ? ORDER BY position",
            (user_id,),
        ).fetchall()
        kept = [(title, url, stamp)] + [
            (r["title"], r["url"], r["watched_at"]) for r in rows
        ][: config.HISTORY_LIMIT - 1]
        conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO history (user_id, position, title, url, watched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(user_id, i, t, u, w) for i, (t, u, w) in enumerate(kept)],
        )


def _clear_history(user_id: int) -> int:
    """Wipes one user's history and reports how many records went."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        return cur.rowcount


def _get_history(user_id: int, limit: int) -> list[dict[str, str]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT title, url, watched_at FROM history WHERE user_id = ? "
            "ORDER BY position LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{"title": r["title"], "url": r["url"], "time": r["watched_at"]} for r in rows]


# -- share tokens ----------------------------------------------------------
def _serialise(videos: list[Video]) -> str:
    return json.dumps([v.to_dict() for v in videos], ensure_ascii=False)


def _deserialise(payload: str) -> list[Video]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return [Video.from_dict(item) for item in raw if isinstance(item, dict)]


def _create_share(owner_id: int, videos: list[Video]) -> tuple[str, bool]:
    """Returns (token, reused). An unchanged queue keeps its existing token
    instead of littering the table with duplicates."""
    payload = _serialise(videos)
    now = time.time()
    with _connect() as conn:
        conn.execute("DELETE FROM shares WHERE created_at < ?", (now - config.SHARE_TTL,))
        existing = conn.execute(
            "SELECT token FROM shares WHERE owner_id = ? AND payload = ?",
            (owner_id, payload),
        ).fetchone()
        if existing:
            return existing["token"], True

        while True:
            token = "GHOST-" + "".join(secrets.choice(_SHARE_ALPHABET) for _ in range(6))
            if not conn.execute("SELECT 1 FROM shares WHERE token = ?", (token,)).fetchone():
                break
        conn.execute(
            "INSERT INTO shares (token, owner_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (token, owner_id, payload, now),
        )
    return token, False


def _get_share(token: str) -> list[Video] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload, created_at FROM shares WHERE token = ?", (token.upper(),)
        ).fetchone()
    if row is None or time.time() - row["created_at"] > config.SHARE_TTL:
        return None
    return _deserialise(row["payload"])


def _gc_shares() -> int:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM shares WHERE created_at < ?", (time.time() - config.SHARE_TTL,)
        )
        return cur.rowcount


# -- user settings ---------------------------------------------------------
def _get_theme(user_id: int) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT theme FROM settings WHERE user_id = ?", (user_id,)).fetchone()
        return row["theme"] if row else config.DEFAULT_THEME


def _set_theme(user_id: int, theme: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (user_id, theme) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET theme = excluded.theme",
            (user_id, theme),
        )


def _get_region(user_id: int) -> str:
    """Stored region, normalised on the way out.

    Validation was added after the fact, so codes like "EN" (a language, not a
    country) are already in the database silently disabling YouTube's `gl`.
    Normalising here repairs those reads without a migration.
    """
    with _connect() as conn:
        row = conn.execute("SELECT region FROM settings WHERE user_id = ?", (user_id,)).fetchone()
    return config.normalise_region(row["region"] if row else None)


def _set_region(user_id: int, region: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (user_id, theme, region) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET region = excluded.region",
            (user_id, config.DEFAULT_THEME, region.upper()),
        )


def _get_language(user_id: int) -> str:
    """Explicit !language choice, else the language the region implies."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT language, region FROM settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return config.DEFAULT_LANGUAGE
    chosen = (row["language"] or "").strip().lower()
    if chosen in config.LANGUAGES:
        return chosen
    return config.language_of(row["region"])


def _set_language(user_id: int, language: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (user_id, theme, language) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET language = excluded.language",
            (user_id, config.DEFAULT_THEME, config.normalise_language(language)),
        )


# -- guild settings --------------------------------------------------------
def _get_guild(guild_id: int) -> dict[str, object]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT locked_channel, prefix FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return {"locked_channel": None, "prefix": config.COMMAND_PREFIX}
    return {
        "locked_channel": row["locked_channel"],
        "prefix": row["prefix"] or config.COMMAND_PREFIX,
    }


def _set_guild_field(guild_id: int, field: str, value: object) -> None:
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO guild_settings (guild_id, {field}) VALUES (?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {field} = excluded.{field}",
            (guild_id, value),
        )


# --------------------------------------------------------------------------
# Async surface
# --------------------------------------------------------------------------
async def init() -> None:
    await asyncio.to_thread(_init)


# -- vault ---
async def save_playlist(owner_id: int, name: str, source: str, videos: list[Video]) -> Playlist:
    return await asyncio.to_thread(_save, owner_id, name, source, videos)


async def list_playlists(owner_id: int) -> list[Playlist]:
    return await asyncio.to_thread(_list, owner_id)


async def get_playlist(owner_id: int, ref: str) -> Playlist | None:
    return await asyncio.to_thread(_get, owner_id, ref)


async def resolve_playlist(owner_id: int, ref: str) -> Playlist | None:
    """Accepts a share code, a name, or a 1-based position in !vault."""
    return await asyncio.to_thread(_resolve_ref, owner_id, ref)


async def get_by_code(code: str) -> Playlist | None:
    return await asyncio.to_thread(_get_by_code, code)


async def delete_playlist(owner_id: int, ref: str) -> str | None:
    return await asyncio.to_thread(_delete, owner_id, ref)


async def rename_playlist(owner_id: int, ref: str, new_name: str) -> tuple[str, str] | None:
    return await asyncio.to_thread(_rename, owner_id, ref, new_name)


async def append_items(owner_id: int, ref: str, videos: list[Video]) -> int:
    return await asyncio.to_thread(_append, owner_id, ref, videos)


# -- queue ---
async def get_queue(user_id: int) -> list[Video]:
    return await asyncio.to_thread(_get_queue, user_id)


async def set_queue(user_id: int, videos: list[Video]) -> None:
    await asyncio.to_thread(_set_queue, user_id, videos)


async def append_queue(user_id: int, videos: list[Video]) -> int:
    return await asyncio.to_thread(_append_queue, user_id, videos)


async def clear_queue(user_id: int) -> None:
    await asyncio.to_thread(_set_queue, user_id, [])


# -- history ---
async def log_history(user_id: int, title: str, url: str) -> None:
    await asyncio.to_thread(_log_history, user_id, title, url)


async def get_history(user_id: int, limit: int = config.HISTORY_SHOW) -> list[dict[str, str]]:
    return await asyncio.to_thread(_get_history, user_id, limit)


async def clear_history(user_id: int) -> int:
    return await asyncio.to_thread(_clear_history, user_id)


# -- shares ---
async def create_share(owner_id: int, videos: list[Video]) -> tuple[str, bool]:
    return await asyncio.to_thread(_create_share, owner_id, videos)


async def get_share(token: str) -> list[Video] | None:
    return await asyncio.to_thread(_get_share, token)


async def gc_shares() -> int:
    return await asyncio.to_thread(_gc_shares)


# -- user settings ---
async def get_theme(user_id: int) -> str:
    return await asyncio.to_thread(_get_theme, user_id)


async def set_theme(user_id: int, theme: str) -> None:
    await asyncio.to_thread(_set_theme, user_id, theme)


async def get_region(user_id: int) -> str:
    return await asyncio.to_thread(_get_region, user_id)


async def set_region(user_id: int, region: str) -> None:
    await asyncio.to_thread(_set_region, user_id, region)


async def get_language(user_id: int) -> str:
    return await asyncio.to_thread(_get_language, user_id)


async def set_language(user_id: int, language: str) -> None:
    await asyncio.to_thread(_set_language, user_id, language)


# -- guild settings ---
async def get_guild_settings(guild_id: int) -> dict[str, object]:
    return await asyncio.to_thread(_get_guild, guild_id)


async def set_guild_prefix(guild_id: int, prefix: str) -> None:
    await asyncio.to_thread(_set_guild_field, guild_id, "prefix", prefix)


async def set_locked_channel(guild_id: int, channel_id: int) -> None:
    await asyncio.to_thread(_set_guild_field, guild_id, "locked_channel", channel_id)


async def clear_locked_channel(guild_id: int) -> None:
    await asyncio.to_thread(_set_guild_field, guild_id, "locked_channel", None)
