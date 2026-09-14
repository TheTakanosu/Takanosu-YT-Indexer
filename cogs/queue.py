"""Queue engine: !add, !pa, !playlist, !play, !pn, !rm, !move, !shuffle, !clear.

The queue lives in SQLite (see vault/store.py), so it survives a restart
without the JSON session files the original Ghost Engine needed.
"""
from __future__ import annotations

import logging
import random

import discord
from discord.ext import commands

import config
from core import extractor, i18n
from core.http import BlockedError
from cogs.common import LAST_VIEW, heavy, parse_indices, prefix_of
from vault import store

log = logging.getLogger("ytplug.queue")

# Where !pn should resume from, per user. Deliberately in memory: a pointer
# only means anything while the queue it points into is being played.
PLAY_POINTERS: dict[int, int] = {}


class Queue(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- adding -----------------------------------------------------------
    @commands.command(name="add", aliases=["a"])
    async def add(self, ctx: commands.Context, *args: str) -> None:
        """`!add <num>` or `!a 1-5` — add search results to the queue."""
        lang = await store.get_language(ctx.author.id)
        if not args:
            await ctx.reply(
                i18n.t("usage", lang,
                       usage=f"{prefix_of(ctx)}add <num>  |  {prefix_of(ctx)}a 1-5"),
                mention_author=False,
            )
            return

        view = LAST_VIEW.get(ctx.author.id)
        if view is None:
            await ctx.reply(
                i18n.t("no_search_memory", lang, prefix=prefix_of(ctx)),
                mention_author=False,
            )
            return

        page = view.current()
        indices = parse_indices(list(args), len(page))
        if not indices:
            await ctx.reply(
                i18n.t("invalid_numbers", lang), mention_author=False
            )
            return

        picked = [page[i] for i in indices]
        total = await store.append_queue(ctx.author.id, picked)

        if len(picked) == 1:
            await ctx.reply(
                i18n.t("added_one", lang, title=picked[0].title, total=total),
                mention_author=False,
            )
        else:
            await ctx.reply(
                i18n.t("added_many", lang, count=len(picked), total=total),
                mention_author=False,
            )

    @commands.command(name="pa")
    async def add_external(self, ctx: commands.Context, *, url: str) -> None:
        """`!pa <link>` — add an external YouTube link or playlist to the queue."""
        url = url.strip()
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)

        if "list=" in url or url.startswith(("PL", "RD", "UL")):
            status = await ctx.reply(
                i18n.t("analyzing_playlist", lang), mention_author=False
            )
            playlist_id = url.split("list=")[-1].split("&")[0]

            async with heavy(lang) as ok:
                if not ok:
                    await status.edit(content=i18n.t("busy", lang))
                    return
                try:
                    _, videos = await extractor.playlist_videos(
                        playlist_id, region=region
                    )
                except extractor.PrivatePlaylist:
                    await status.edit(content=i18n.t("playlist_private", lang))
                    return
                except BlockedError as exc:
                    await status.edit(content=i18n.t("blocked", lang, error=exc))
                    return

            if not videos:
                await status.edit(content=i18n.t("playlist_failed", lang))
                return

            total = await store.append_queue(ctx.author.id, videos)
            message = i18n.t("playlist_added", lang, count=len(videos), total=total)
            # YouTube stops at 100 for an anonymous session and offers no
            # continuation, so say so rather than looking like we truncated.
            if len(videos) >= config.PLAYLIST_MAX_ITEMS:
                message += "\n" + i18n.t(
                    "playlist_capped", lang, cap=config.PLAYLIST_MAX_ITEMS
                )
            await status.edit(content=message)
            return

        try:
            video = await extractor.video_from_link(url)
        except BlockedError as exc:
            await ctx.reply(i18n.t("blocked", lang, error=exc), mention_author=False)
            return

        if video is None:
            await ctx.reply(i18n.t("invalid_link", lang), mention_author=False)
            return

        total = await store.append_queue(ctx.author.id, [video])
        await ctx.reply(
            i18n.t("link_added", lang, title=video.title, total=total),
            mention_author=False,
        )

    # -- viewing ----------------------------------------------------------
    @commands.command(name="playlist", aliases=["pl", "queue"])
    async def show_queue(self, ctx: commands.Context) -> None:
        """`!playlist` — view your queue."""
        lang = await store.get_language(ctx.author.id)
        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply(i18n.t("queue_empty", lang), mention_author=False)
            return

        body = ""
        truncated = False
        for index, video in enumerate(queue, 1):
            line = f"**{index}.** {video.title}\n"
            if len(body) + len(line) > 3800:
                truncated = True
                break
            body += line

        if truncated:
            body += (
                f"\n⚠️ *(Exceeds character limit. Use `{prefix_of(ctx)}export` "
                "to download the full list.)*"
            )

        embed = discord.Embed(
            title=f"🎵 Your Current Playlist ({len(queue)} tracks)",
            description=body,
            colour=0x1E90FF,
        )
        await ctx.reply(embed=embed, mention_author=False)

    # -- playback ---------------------------------------------------------
    @commands.command(name="play", aliases=["start"])
    async def play(self, ctx: commands.Context, number: str | None = None) -> None:
        """`!play` or `!play 5` — start the playlist."""
        await self._pop_and_send(ctx, number, skipping=False)

    @commands.command(name="pn")
    async def play_next(self, ctx: commands.Context) -> None:
        """`!pn` — play the next video in the queue."""
        await self._pop_and_send(ctx, None, skipping=True)

    async def _pop_and_send(
        self, ctx: commands.Context, number: str | None, *, skipping: bool
    ) -> None:
        lang = await store.get_language(ctx.author.id)
        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply(i18n.t("queue_empty_action", lang), mention_author=False)
            PLAY_POINTERS.pop(ctx.author.id, None)
            return

        if skipping:
            index = PLAY_POINTERS.get(ctx.author.id, 0)
        elif number and number.isdigit():
            index = int(number) - 1
        else:
            index = 0

        if not 0 <= index < len(queue):
            if skipping:
                await ctx.reply(
                    i18n.t("no_more_tracks", lang), mention_author=False
                )
                PLAY_POINTERS.pop(ctx.author.id, None)
            else:
                await ctx.reply(i18n.t("invalid_track", lang), mention_author=False)
            return

        video = queue.pop(index)
        await store.set_queue(ctx.author.id, queue)
        # The popped slot now holds whatever followed it, so !pn keeps walking
        # forward from the same index.
        PLAY_POINTERS[ctx.author.id] = index
        await store.log_history(ctx.author.id, video.title, video.url)

        label = i18n.t("skipping" if skipping else "starting", lang)
        await ctx.send(
            f"<@{ctx.author.id}> {label} {video.url}\n"
            + i18n.t("remaining", lang, count=len(queue))
        )

    # -- editing ----------------------------------------------------------
    @commands.command(name="rm", aliases=["remove"])
    async def remove(self, ctx: commands.Context, *args: str) -> None:
        """`!rm <num1> <num2>` or `!rm 1-5` — remove tracks from the queue."""
        lang = await store.get_language(ctx.author.id)
        if not args:
            await ctx.reply(
                i18n.t("usage", lang,
                       usage=f"{prefix_of(ctx)}rm <num1> <num2>  |  {prefix_of(ctx)}rm 1-5"),
                mention_author=False,
            )
            return

        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply(i18n.t("queue_empty", lang), mention_author=False)
            return

        indices = parse_indices(list(args), len(queue))
        if not indices:
            await ctx.reply(
                i18n.t("invalid_tracks", lang, count=len(queue)),
                mention_author=False,
            )
            return

        drop = set(indices)
        kept = [v for i, v in enumerate(queue) if i not in drop]
        await store.set_queue(ctx.author.id, kept)
        PLAY_POINTERS.pop(ctx.author.id, None)
        await ctx.reply(
            i18n.t("removed", lang, count=len(drop), total=len(kept)),
            mention_author=False,
        )

    @commands.command(name="move")
    async def move(self, ctx: commands.Context, source: str, target: str) -> None:
        """`!move <from> <to>` — reorder a track in the queue."""
        lang = await store.get_language(ctx.author.id)
        if not (source.isdigit() and target.isdigit()):
            await ctx.reply(
                i18n.t("usage", lang, usage=f"{prefix_of(ctx)}move <from> <to>"),
                mention_author=False,
            )
            return

        queue = await store.get_queue(ctx.author.id)
        if len(queue) < 2:
            await ctx.reply(
                i18n.t("move_too_few", lang), mention_author=False
            )
            return

        origin, destination = int(source) - 1, int(target) - 1
        if not (0 <= origin < len(queue) and 0 <= destination < len(queue)):
            await ctx.reply(i18n.t("invalid_track_numbers", lang), mention_author=False)
            return

        video = queue.pop(origin)
        queue.insert(destination, video)
        await store.set_queue(ctx.author.id, queue)
        PLAY_POINTERS.pop(ctx.author.id, None)
        await ctx.reply(
            i18n.t("moved", lang, title=video.title, position=destination + 1),
            mention_author=False,
        )

    @commands.command(name="shuffle")
    async def shuffle(self, ctx: commands.Context) -> None:
        """`!shuffle` — randomize the queue order."""
        lang = await store.get_language(ctx.author.id)
        queue = await store.get_queue(ctx.author.id)
        if len(queue) < 2:
            await ctx.reply(
                i18n.t("shuffle_too_few", lang), mention_author=False
            )
            return

        random.shuffle(queue)
        await store.set_queue(ctx.author.id, queue)
        PLAY_POINTERS.pop(ctx.author.id, None)
        await ctx.reply(
            i18n.t("shuffled", lang, count=len(queue)), mention_author=False
        )

    @commands.command(name="clear")
    async def clear(self, ctx: commands.Context) -> None:
        """`!clear` — empty your queue."""
        lang = await store.get_language(ctx.author.id)
        await store.clear_queue(ctx.author.id)
        PLAY_POINTERS.pop(ctx.author.id, None)
        await ctx.reply(i18n.t("cleared", lang), mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Queue(bot))
