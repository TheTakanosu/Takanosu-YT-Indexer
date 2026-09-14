"""Export systems: !export, !exportmp3 and the Spotify bridge.

`!export` with no argument writes the live queue; given a name, code or vault
position it writes that saved playlist instead.
"""
from __future__ import annotations

import io
import logging

import discord
from discord.ext import commands

import config
from cogs.common import prefix_of
from vault import export, spotify, store

log = logging.getLogger("ytplug.export")

# Wording taken from the Ghost Engine so failures stay recognisable.
SPOTIFY_ERRORS = {
    spotify.ERR_NOT_FOUND: (
        "❌ **Not Found (404):** Spotify has no public list at that link. Either the "
        "link is wrong, the list is **private**, or it is brand new — a new list can "
        "take 15-30 mins to be indexed."
    ),
    spotify.ERR_PRIVATE: (
        "🔒 **That list is private.** Spotify only serves public playlists to "
        "anyone who is not signed in as you, so there is nothing here to read — no "
        "bot can import it, this one included.\n"
        "Open it in Spotify → **…** → *Edit details* → make it public (or use "
        "*Share* on a public list), then paste the link again."
    ),
    spotify.ERR_EMPTY: (
        "⚠️ **Warning:** Connection successful, but the playlist/album appears to be empty."
    ),
    spotify.ERR_NO_JSON: (
        "❌ **Scraper Blocked:** Spotify did not return the embed payload. "
        "Make sure the link is a *public* playlist or album, then try again."
    ),
    spotify.ERR_SYSTEM: (
        "❌ **System Error:** An internal process failed during extraction. "
        "The development team has been notified."
    ),
}


class ExportCog(commands.Cog, name="Export"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- YouTube M3U ------------------------------------------------------
    @commands.command(name="export", aliases=["exportvideo", "disaaktar"])
    async def export_video(self, ctx: commands.Context, *, ref: str | None = None) -> None:
        """`!export` — download the queue as a video .m3u."""
        await self._export(ctx, ref, audio_only=False)

    @commands.command(name="exportmp3", aliases=["exportaudio"])
    async def export_audio(self, ctx: commands.Context, *, ref: str | None = None) -> None:
        """`!exportmp3` — download the queue as an audio-only .m3u."""
        await self._export(ctx, ref, audio_only=True)

    async def _export(
        self, ctx: commands.Context, ref: str | None, *, audio_only: bool
    ) -> None:
        if ref:
            playlist = await store.resolve_playlist(ctx.author.id, ref)
            if playlist is None:
                playlist = await store.get_by_code(ref)
            if playlist is None:
                await ctx.reply(
                    f"❌ `{ref}` not found. Try `{prefix_of(ctx)}vault` to list yours.",
                    mention_author=False,
                )
                return
            videos, title = playlist.items, playlist.name
            filename = (
                f"{export.safe_name(playlist.name)}_"
                f"{'audio' if audio_only else 'video'}.m3u"
            )
        else:
            videos = await store.get_queue(ctx.author.id)
            if not videos:
                await ctx.reply(
                    "❌ Your playlist is empty! Add videos before exporting.",
                    mention_author=False,
                )
                return
            title = "your queue"
            filename = export.queue_filename(audio_only=audio_only)

        content = export.build_m3u(title, videos, audio_only=audio_only)
        file = discord.File(io.BytesIO(content.encode("utf-8")), filename=filename)

        if audio_only:
            message = (
                f"🎧 **Your Audio-Only Playlist is here!**\nFile: `{filename}` — "
                f"{len(videos)} tracks\n"
                f"*(No plugin needed — MPV opens this straight in pure audio mode.)*\n"
                f"`{export.mpv_hint(audio_only=True)} {filename}`"
            )
        else:
            message = (
                f"🎬 **Your MPV-Ready Video Playlist is here!**\nFile: `{filename}` — "
                f"{len(videos)} tracks\n`{export.mpv_hint(audio_only=False)} {filename}`"
            )

        await ctx.reply(message, file=file, mention_author=False)

    # -- Spotify M3U ------------------------------------------------------
    @commands.command(name="spotify", aliases=["sp"])
    async def spotify_video(self, ctx: commands.Context, *, url: str | None = None) -> None:
        """`!spotify <link>` — export a Spotify list as a video M3U."""
        await self._spotify(ctx, url, audio_only=False)

    @commands.command(name="spotifymp3", aliases=["spotifyaudio"])
    async def spotify_audio(self, ctx: commands.Context, *, url: str | None = None) -> None:
        """`!spotifymp3 <link>` — export a Spotify list as an audio-only M3U."""
        await self._spotify(ctx, url, audio_only=True)

    async def _spotify(
        self, ctx: commands.Context, url: str | None, *, audio_only: bool
    ) -> None:
        if not url:
            await ctx.reply(
                "❌ **Error:** Please provide a valid Spotify link!", mention_author=False
            )
            return

        parsed = spotify.parse_link(url)
        if parsed is None:
            await ctx.reply(
                "❌ **Error:** Could not extract Spotify ID from link!", mention_author=False
            )
            return

        entity_type, entity_id = parsed
        mode = "AUDIO" if audio_only else "VIDEO"
        status = await ctx.reply(
            f"🔄 **Infiltrating Spotify ({mode} Mode)...** Extracting tracks via "
            "Embed Scraper.",
            mention_author=False,
        )

        try:
            name, tracks = await spotify.fetch_tracks(
                entity_id, entity_type, limit=config.SPOTIFY_MAX_TRACKS,
                private_hint=spotify.is_private_share(url),
            )
        except spotify.SpotifyError as exc:
            await status.edit(content=SPOTIFY_ERRORS.get(exc.code, SPOTIFY_ERRORS[spotify.ERR_SYSTEM]))
            return

        content = export.build_search_m3u(tracks, audio_only=audio_only)
        filename = export.spotify_filename(name, audio_only=audio_only)
        file = discord.File(io.BytesIO(content.encode("utf-8")), filename=filename)

        if audio_only:
            message = (
                f"🎧 **Spotify Audio Export Successful!**\nFile: `{filename}`\n"
                f"*(🎧 Pure Audio Mode — successfully extracted **{len(tracks)}** tracks "
                f"via Embed Bypass!)*\n`{export.mpv_hint(audio_only=True)} {filename}`"
            )
        else:
            message = (
                f"🎬 **Spotify Export Successful!**\nFile: `{filename}`\n"
                f"*(✅ Successfully extracted **{len(tracks)}** tracks via Embed Bypass!)*\n"
                f"`{export.mpv_hint(audio_only=False)} {filename}`"
            )

        await status.delete()
        await ctx.send(message, file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExportCog(bot))
