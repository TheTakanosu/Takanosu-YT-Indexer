"""One-shot migration: Ghost Engine JSON state -> the SQLite vault.

The original single-file bot kept everything in JSON next to `main.py`. This
reads those files and writes the same content into `data/vault.db` so a
deployment of the rewritten bot keeps users' queues, saved playlists, share
tokens and preferences instead of starting empty.

Usage:
    .venv/bin/python deploy/migrate_from_json.py <folder with the .json files>

It is safe to re-run: every table is keyed, and existing rows for a user are
replaced rather than duplicated. The source JSON files are only ever read.

Field mapping for the video dicts (old -> new):
    id     -> video_id        time -> published
    title, channel, url, thumbnail, avatar, views  ->  unchanged
Duration was never captured by the old bot, so it lands empty; the renderer
and the M3U writer both already treat an empty duration as "live/unknown".
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core.models import Video  # noqa: E402
from vault import store  # noqa: E402

FILES = {
    "queues": "sessions.json",
    "playlists": "saved_custom_playlists.json",
    "shares": "shared_playlists.json",
    "users": "user_settings.json",
    "guilds": "guild_settings.json",
    "history": "user_history.json",
}


def load(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  ! {name}: unreadable ({exc}) - skipped")
        return {}
    return data if isinstance(data, dict) else {}


def to_video(raw: dict) -> Video | None:
    """Old-format track dict -> Video. Returns None if there is no id to keep."""
    if not isinstance(raw, dict):
        return None

    video_id = str(raw.get("id") or raw.get("video_id") or "").strip()
    if not video_id:
        # Some rows only carry a URL; recover the id from it.
        url = str(raw.get("url") or "")
        if "v=" in url:
            video_id = url.split("v=")[-1].split("&")[0]
    if not video_id:
        return None

    return Video(
        video_id=video_id,
        title=str(raw.get("title") or "Unknown Title"),
        channel=str(raw.get("channel") or ""),
        views=str(raw.get("views") or ""),
        published=str(raw.get("time") or raw.get("published") or ""),
        thumbnail=str(raw.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
        avatar=str(raw.get("avatar") or ""),
    )


def to_videos(rows: object) -> list[Video]:
    if not isinstance(rows, list):
        return []
    return [v for v in (to_video(r) for r in rows) if v is not None]


async def main(folder: Path) -> int:
    print(f"source : {folder}")
    print(f"target : {config.DB_PATH}\n")
    await store.init()

    total = {"queues": 0, "tracks": 0, "playlists": 0, "items": 0,
             "shares": 0, "users": 0, "guilds": 0, "history": 0}
    skipped = 0

    # -- queues (sessions.json) -------------------------------------------
    for user_id, rows in load(folder, FILES["queues"]).items():
        videos = to_videos(rows)
        skipped += (len(rows) if isinstance(rows, list) else 0) - len(videos)
        if not videos:
            continue
        await store.set_queue(int(user_id), videos)
        total["queues"] += 1
        total["tracks"] += len(videos)
        print(f"  queue    {user_id}  {len(videos)} tracks")

    # -- saved playlists (saved_custom_playlists.json) --------------------
    for user_id, lists in load(folder, FILES["playlists"]).items():
        if not isinstance(lists, dict):
            continue
        existing = {p.name.lower() for p in await store.list_playlists(int(user_id))}
        for name, rows in lists.items():
            videos = to_videos(rows)
            if not videos or name.lower() in existing:
                continue
            saved = await store.save_playlist(int(user_id), str(name)[:60], "manual", videos)
            total["playlists"] += 1
            total["items"] += len(videos)
            print(f"  playlist {user_id}  '{saved.name}' {len(videos)} tracks "
                  f"-> code {saved.share_code}")

    # -- share tokens (shared_playlists.json) ----------------------------
    # The old file keyed tokens by string and stored {playlist, timestamp};
    # very old entries were a bare list. Both shapes are accepted.
    shares = load(folder, FILES["shares"])
    if shares:
        rows = []
        now = time.time()
        for token, payload in shares.items():
            if isinstance(payload, dict):
                videos = to_videos(payload.get("playlist"))
                created = float(payload.get("timestamp") or now)
            else:
                videos = to_videos(payload)
                created = now
            if not videos:
                continue
            if now - created > config.SHARE_TTL:
                print(f"  share    {token} expired - skipped")
                continue
            rows.append((str(token).upper(), videos, created))

        if rows:
            await asyncio.to_thread(_insert_shares, rows)
            total["shares"] = len(rows)
            for token, videos, _ in rows:
                print(f"  share    {token}  {len(videos)} tracks")

    # -- user settings ----------------------------------------------------
    for user_id, settings in load(folder, FILES["users"]).items():
        if not isinstance(settings, dict):
            continue
        uid = int(user_id)
        theme = str(settings.get("theme") or "").lower()
        region = str(settings.get("region") or "").upper()
        if theme:
            await store.set_theme(uid, theme)
        if region:
            await store.set_region(uid, region)
        total["users"] += 1
        print(f"  user     {uid}  theme={theme or '-'} region={region or '-'}")

    # -- guild settings ---------------------------------------------------
    for guild_id, settings in load(folder, FILES["guilds"]).items():
        if not isinstance(settings, dict):
            continue
        gid = int(guild_id)
        prefix = settings.get("prefix")
        locked = settings.get("locked_channel")
        if prefix:
            await store.set_guild_prefix(gid, str(prefix))
        if locked:
            await store.set_locked_channel(gid, int(locked))
        total["guilds"] += 1
        print(f"  guild    {gid}  prefix={prefix or config.COMMAND_PREFIX} "
              f"locked_channel={locked or '-'}")

    # -- history (optional; the old bot did not always create this) -------
    for user_id, rows in load(folder, FILES["history"]).items():
        if not isinstance(rows, list):
            continue
        uid = int(user_id)
        # log_history prepends, so replay oldest-first to preserve order.
        for row in reversed(rows[: config.HISTORY_LIMIT]):
            if isinstance(row, dict) and row.get("title") and row.get("url"):
                await store.log_history(uid, str(row["title"]), str(row["url"]))
                total["history"] += 1

    print("\n--- migrated ---")
    print(f"  queues     {total['queues']} users, {total['tracks']} tracks")
    print(f"  playlists  {total['playlists']} lists, {total['items']} tracks")
    print(f"  shares     {total['shares']} tokens")
    print(f"  users      {total['users']} preference rows")
    print(f"  guilds     {total['guilds']} server rows")
    print(f"  history    {total['history']} records")
    if skipped:
        print(f"  skipped    {skipped} track(s) with no recoverable video id")
    return 0


def _insert_shares(rows: list[tuple[str, list[Video], float]]) -> None:
    """Writes share tokens with their original values intact.

    store.create_share() mints a fresh random token, but these tokens are
    already out in the wild in people's chat history, so they are inserted
    verbatim through the same serialiser the store uses.
    """
    import sqlite3

    with sqlite3.connect(config.DB_PATH, timeout=10) as conn:
        for token, videos, created in rows:
            conn.execute(
                "INSERT OR REPLACE INTO shares (token, owner_id, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (token, 0, store._serialise(videos), created),
            )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.is_dir():
        print(f"not a directory: {source}")
        sys.exit(2)
    sys.exit(asyncio.run(main(source)))
