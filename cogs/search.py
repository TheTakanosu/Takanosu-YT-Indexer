"""Search and discovery: !s, !v, !live, !home, !p, page navigation, !history."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from core import cache, extractor, i18n
from core.http import BlockedError
from cogs.common import LAST_VIEW, heavy, prefix_of, send_results
from vault import store

log = logging.getLogger("ytplug.search")


class Search(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- global search ----------------------------------------------------
    @commands.command(name="s", aliases=["yt", "ara", "search"])
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """`!s <query>` — search YouTube, 3x3 grid."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        key = cache.search_key(query, region)
        cached = cache.searches.get(key)

        status = await ctx.reply(
            i18n.t("smart_cache" if cached else "searching", lang, query=query),
            mention_author=False,
        )

        if cached:
            videos = cached
        else:
            # Gate only the uncached path: a cache hit does no network or
            # render work worth queueing behind.
            async with heavy(lang) as ok:
                if not ok:
                    await status.edit(content=i18n.t("busy", lang))
                    return
                try:
                    videos = await extractor.search(
                        query,
                        limit=config.MAX_RESULTS,
                        region=region,
                        max_pages=config.MAX_SEARCH_PAGES,
                    )
                except BlockedError as exc:
                    await status.edit(content=i18n.t("blocked", lang, error=exc))
                    return
            if videos:
                cache.searches.set(key, videos)

        if not videos:
            await status.edit(content=i18n.t("no_results", lang, query=query))
            return

        await send_results(
            ctx,
            videos,
            header=query[:60],
            note=i18n.t("grid_shorts_filtered", lang),
            list_name=query[:60],
            status=status,
        )

    # -- trending ---------------------------------------------------------
    @commands.command(name="home", aliases=["discover", "trending"])
    async def home(self, ctx: commands.Context) -> None:
        """`!home` — discover trending for your region."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        status = await ctx.reply(
            i18n.t("trending_connecting", lang), mention_author=False
        )

        async with heavy(lang) as ok:
            if not ok:
                await status.edit(content=i18n.t("busy", lang))
                return
            try:
                videos = await extractor.trending(region, limit=config.MAX_RESULTS)
            except BlockedError:
                await status.edit(content=i18n.t("trending_failed", lang))
                return

        if not videos:
            await status.edit(content=i18n.t("trending_failed", lang))
            return

        await send_results(
            ctx,
            videos,
            header=f"Trending {region}",
            note=i18n.t("grid_shorts_filtered", lang),
            list_name=f"trending-{region}",
            status=status,
        )

    # -- live -------------------------------------------------------------
    @commands.command(name="live", aliases=["canli"])
    async def live(self, ctx: commands.Context, *, query: str) -> None:
        """`!live <query>` — only what is streaming right now."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        async with ctx.typing():
            try:
                videos = await extractor.search(
                    query, limit=config.RESULTS_PER_PAGE, region=region, live_only=True
                )
            except BlockedError as exc:
                await ctx.reply(
                    i18n.t("blocked", lang, error=exc), mention_author=False
                )
                return

        if not videos:
            await ctx.reply(i18n.t("no_live", lang, query=query), mention_author=False)
            return

        await send_results(
            ctx,
            videos,
            header=f"🔴 {query[:55]}",
            note=i18n.t("grid_live", lang),
            list_name=f"live-{query[:50]}",
        )

    # -- single link ------------------------------------------------------
    @commands.command(name="v", aliases=["link"])
    async def single(self, ctx: commands.Context, *, query: str) -> None:
        """`!v <query>` — posts the first result's link directly."""
        region = await store.get_region(ctx.author.id)
        lang = await store.get_language(ctx.author.id)
        async with ctx.typing():
            try:
                videos = await extractor.search(query, limit=1, region=region)
            except BlockedError as exc:
                await ctx.reply(i18n.t("blocked", lang, error=exc), mention_author=False)
                return
        if not videos:
            await ctx.reply(i18n.t("no_results", lang, query=query), mention_author=False)
            return
        video = videos[0]
        await store.log_history(ctx.author.id, video.title, video.url)
        await ctx.reply(
            f"**{video.title}** — {video.channel or '—'}\n{video.url}", mention_author=False
        )

    # -- play from the current page ---------------------------------------
    @commands.command(name="p")
    async def play_result(self, ctx: commands.Context, number: str) -> None:
        """`!p <num>` — play a video from the current page directly."""
        lang = await store.get_language(ctx.author.id)
        view = LAST_VIEW.get(ctx.author.id)
        if view is None:
            await ctx.reply(
                i18n.t("no_search_memory", lang, prefix=prefix_of(ctx)),
                mention_author=False,
            )
            return

        if not number.isdigit():
            await ctx.reply(
                i18n.t("usage", lang, usage=f"{prefix_of(ctx)}p <num>"),
                mention_author=False,
            )
            return

        items = view.current()
        index = int(number) - 1
        if not 0 <= index < len(items):
            await ctx.reply(
                i18n.t("pick_from_page", lang, count=len(items)),
                mention_author=False,
            )
            return

        video = items[index]
        await store.log_history(ctx.author.id, video.title, video.url)
        await ctx.send(f"<@{ctx.author.id}> "
                       + i18n.t("selected", lang, index=index + 1, url=video.url))

    # -- page navigation --------------------------------------------------
    async def _turn(self, ctx: commands.Context, page: int) -> None:
        lang = await store.get_language(ctx.author.id)
        view = LAST_VIEW.get(ctx.author.id)
        if view is None:
            await ctx.reply(
                i18n.t("no_search_memory", lang, prefix=prefix_of(ctx)),
                mention_author=False,
            )
            return
        if not 0 <= page < view.pages:
            await ctx.reply(
                i18n.t("no_such_page", lang, page=page + 1, pages=view.pages),
                mention_author=False,
            )
            return
        if not await view.goto_page(page):
            await ctx.reply(
                i18n.t("message_gone", lang), mention_author=False
            )

    @commands.command(name="next")
    async def next_page(self, ctx: commands.Context) -> None:
        """`!next` — next page of results."""
        view = LAST_VIEW.get(ctx.author.id)
        await self._turn(ctx, (view.page + 1) if view else 0)

    @commands.command(name="prev", aliases=["previous"])
    async def prev_page(self, ctx: commands.Context) -> None:
        """`!prev` — previous page of results."""
        view = LAST_VIEW.get(ctx.author.id)
        await self._turn(ctx, (view.page - 1) if view else 0)

    @commands.command(name="page")
    async def goto_page(self, ctx: commands.Context, number: str) -> None:
        """`!page <num>` — jump straight to a page."""
        if not number.isdigit():
            lang = await store.get_language(ctx.author.id)
            await ctx.reply(
                i18n.t("usage", lang, usage=f"{prefix_of(ctx)}page <num>"),
                mention_author=False,
            )
            return
        await self._turn(ctx, int(number) - 1)

    # -- history ----------------------------------------------------------
    @commands.command(name="history", aliases=["gecmis"])
    async def history(self, ctx: commands.Context) -> None:
        """`!history` — view your playback history."""
        lang = await store.get_language(ctx.author.id)
        records = await store.get_history(ctx.author.id, config.HISTORY_SHOW)
        if not records:
            await ctx.reply(
                i18n.t("history_empty", lang), mention_author=False
            )
            return

        desc = "\n".join(
            f"**{i}.** [{item['title'][:70]}]({item['url']}) *({item['time']})*"
            for i, item in enumerate(records, 1)
        )
        embed = discord.Embed(
            title=i18n.t("history_title", lang, count=len(records)),
            description=desc,
            colour=0x2B2D31,
        )
        embed.set_footer(text=i18n.t("history_footer", lang, prefix=prefix_of(ctx)))
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="clearhistory", aliases=["gecmissil"])
    async def clear_history(self, ctx: commands.Context) -> None:
        """`!clearhistory` — wipe your playback history."""
        lang = await store.get_language(ctx.author.id)
        removed = await store.clear_history(ctx.author.id)
        if not removed:
            await ctx.reply(i18n.t("history_already_empty", lang), mention_author=False)
            return
        await ctx.reply(
            i18n.t("history_cleared", lang, count=removed), mention_author=False
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Search(bot))
