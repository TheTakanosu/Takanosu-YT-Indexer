"""Channel feeds: latest long-form videos (!cs) and the stream archive (!cl)."""
from __future__ import annotations

import logging

from discord.ext import commands

import config
from core import extractor, i18n
from core.http import BlockedError
from cogs.common import heavy, send_results
from vault import store

log = logging.getLogger("ytplug.channel")


class ChannelFeed(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="cs", aliases=["kanal"])
    async def channel_stream(self, ctx: commands.Context, *, query: str) -> None:
        """`!cs <@handle | channel name | URL>` — latest videos from a channel."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        status = await ctx.reply(
            i18n.t("channel_scanning", lang, query=query), mention_author=False
        )

        async with heavy(lang) as ok:
            if not ok:
                await status.edit(content=i18n.t("busy", lang))
                return
            try:
                channel = await extractor.channel_videos(
                    query, limit=config.MAX_RESULTS, region=region
                )
            except LookupError as exc:
                await status.edit(
                    content=i18n.t("channel_not_found", lang, error=exc)
                )
                return
            except BlockedError as exc:
                await status.edit(content=i18n.t("blocked", lang, error=exc))
                return

        meta = [i18n.t("grid_shorts_filtered", lang)]
        if channel.subscribers:
            meta.insert(0, channel.subscribers)

        await send_results(
            ctx,
            channel.videos,
            header=f"📡 {channel.name[:55]}",
            note="  •  ".join(meta),
            list_name=channel.name[:60],
            status=status,
        )

    @commands.command(name="cl", aliases=["kanalcanli"])
    async def channel_live(self, ctx: commands.Context, *, query: str) -> None:
        """`!cl <channel>` — the channel's live streams / broadcast archive."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        async with ctx.typing():
            try:
                channel = await extractor.channel_live(
                    query, limit=config.RESULTS_PER_PAGE, region=region
                )
            except LookupError as exc:
                await ctx.reply(
                    i18n.t("channel_not_found", lang, error=exc), mention_author=False
                )
                return
            except BlockedError as exc:
                await ctx.reply(i18n.t("blocked", lang, error=exc), mention_author=False)
                return

        if not channel.videos:
            await ctx.reply(
                f"📡 No broadcast records found on the **{channel.name}** channel.",
                mention_author=False,
            )
            return

        await send_results(
            ctx,
            channel.videos,
            header=f"🔴 {channel.name[:55]}",
            note="broadcast archive",
            list_name=f"{channel.name[:50]}-live",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelFeed(bot))
