"""Vault and cloud commands.

Vault: !savepl, !loadpl, !rmpl, !vault (plus the older !ytlist / !show /
!unvault). Cloud: !share, !import, !restore.

Every reference argument goes through store.resolve_playlist, so a list can
be named by its share code, its name, or its 1-based position in !vault —
the dual-input behaviour users already rely on.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core import extractor
from core.http import BlockedError
from cogs.common import prefix_of
from vault import store

log = logging.getLogger("ytplug.vault")


class VaultCog(commands.Cog, name="Vault"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- saving and loading ----------------------------------------------
    @commands.command(name="savepl")
    async def savepl(self, ctx: commands.Context, *, name: str) -> None:
        """`!savepl <name>` — save the current queue to your vault."""
        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply("❌ Your queue is empty! Nothing to save.", mention_author=False)
            return

        playlist = await store.save_playlist(ctx.author.id, name.strip()[:60], "manual", queue)
        await ctx.reply(
            f"💾 **Vault Locked!** Your current queue has been securely saved as "
            f"`{playlist.name}` — {len(playlist.items)} tracks.\n"
            f"Share code: `{playlist.share_code}`",
            mention_author=False,
        )

    @commands.command(name="loadpl")
    async def loadpl(self, ctx: commands.Context, *, ref: str) -> None:
        """`!loadpl <name/num>` — load a playlist from the vault into the queue."""
        playlists = await store.list_playlists(ctx.author.id)
        if not playlists:
            await ctx.reply("📭 **Your Vault is empty!**", mention_author=False)
            return

        playlist = await store.resolve_playlist(ctx.author.id, ref)
        if playlist is None:
            await ctx.reply(
                f"❌ Could not find a saved playlist by the name or number: `{ref}`!",
                mention_author=False,
            )
            return

        total = await store.append_queue(ctx.author.id, playlist.items)
        await ctx.reply(
            f"📂 **Vault Opened!** Playlist `{playlist.name}` has been inserted into "
            f"your queue — {len(playlist.items)} tracks. *(Queue: **{total}**)*",
            mention_author=False,
        )

    @commands.command(name="rmpl", aliases=["unvault", "sil"])
    async def rmpl(self, ctx: commands.Context, *, ref: str) -> None:
        """`!rmpl <name/num>` — delete a playlist from the vault."""
        playlists = await store.list_playlists(ctx.author.id)
        if not playlists:
            await ctx.reply("📭 **Your Vault is already empty!**", mention_author=False)
            return

        removed = await store.delete_playlist(ctx.author.id, ref)
        if removed is None:
            await ctx.reply(
                f"❌ Could not find a playlist to delete for: `{ref}`!", mention_author=False
            )
            return

        await ctx.reply(
            f"🗑️ **Data Erased!** Playlist `{removed}` has been permanently removed "
            "from your vault.",
            mention_author=False,
        )

    @commands.command(name="renamepl", aliases=["rename", "adlandir"])
    async def renamepl(self, ctx: commands.Context, *, spec: str) -> None:
        """`!renamepl <name/num> | <new name>` — rename a vault playlist."""
        ref, separator, new_name = (part.strip() for part in spec.partition("|"))
        if not separator or not new_name:
            await ctx.reply(
                f"⚠️ Usage: `{prefix_of(ctx)}renamepl <name/num> | <new name>`\n"
                f"Example: `{prefix_of(ctx)}renamepl 1 | evening mix`",
                mention_author=False,
            )
            return

        playlists = await store.list_playlists(ctx.author.id)
        if not playlists:
            await ctx.reply("📭 **Your Vault is empty!**", mention_author=False)
            return

        renamed = await store.rename_playlist(ctx.author.id, ref, new_name[:60])
        if renamed is None:
            await ctx.reply(
                f"❌ Could not find a playlist to rename for: `{ref}`!",
                mention_author=False,
            )
            return

        old, new = renamed
        await ctx.reply(
            f"✏️ **Renamed!** `{old}` is now `{new}`.\n"
            "*(Its share code did not change, so links already posted still work.)*",
            mention_author=False,
        )

    @commands.command(name="vault", aliases=["kasa"])
    async def vault(self, ctx: commands.Context) -> None:
        """`!vault` — view your saved playlists."""
        playlists = await store.list_playlists(ctx.author.id)
        if not playlists:
            await ctx.reply(
                f"📭 **Your Vault is empty!** Use `{prefix_of(ctx)}savepl <name>` to save "
                "your current queue.",
                mention_author=False,
            )
            return

        desc = "\n".join(
            f"**{i}.** `{p.name}` *(Tracks: {len(p.items)})*  •  code `{p.share_code}`"
            for i, p in enumerate(playlists[:25], 1)
        )
        if len(playlists) > 25:
            desc += f"\n*…and {len(playlists) - 25} more.*"

        embed = discord.Embed(
            title="🔐 Your Personal Vault", description=desc, colour=0x2B2D31
        )
        embed.set_footer(
            text=f"Type {prefix_of(ctx)}loadpl <name/num> to insert, "
                 f"or {prefix_of(ctx)}rmpl <name/num> to delete."
        )
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="show", aliases=["goster"])
    async def show(self, ctx: commands.Context, *, ref: str) -> None:
        """`!show <name|code|num>` — the contents of a playlist."""
        playlist = await store.resolve_playlist(ctx.author.id, ref)
        if playlist is None:
            playlist = await store.get_by_code(ref)
        if playlist is None:
            await ctx.reply(
                f"❌ `{ref}` not found. Try `{prefix_of(ctx)}vault` to list yours.",
                mention_author=False,
            )
            return

        # Shown the way !playlist shows the queue. Both commands answer the
        # same question - "what is in this list" - and a numbered title per
        # line answers it at a glance. This used to build a text dump with a
        # URL under every track, which doubled the height, pushed all but the
        # shortest lists past the message limit into an attachment nobody can
        # read without opening it, and was a worse version of !export: that
        # one hands over the links in a file a player can actually open.
        body = ""
        truncated = False
        for index, video in enumerate(playlist.items, 1):
            line = f"**{index}.** {video.title}\n"
            if len(body) + len(line) > 3800:
                truncated = True
                break
            body += line

        if truncated:
            body += (
                f"\n⚠️ *(Exceeds character limit. Use "
                f"`{prefix_of(ctx)}export {playlist.name}` for the whole list.)*"
            )

        embed = discord.Embed(
            title=f"📄 {playlist.name} ({len(playlist.items)} tracks)",
            description=body or "*(empty)*",
            colour=0x1E90FF,
        )
        embed.set_footer(text=f"Share code: {playlist.share_code}")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="ytlist")
    async def ytlist(self, ctx: commands.Context, *, spec: str) -> None:
        """`!ytlist <name> | <query|playlist URL>` — build a vault list from YouTube."""
        name, _, source = (part.strip() for part in spec.partition("|"))
        if not source:
            name, source = spec.strip()[:60], spec.strip()

        region = await store.get_region(ctx.author.id)
        async with ctx.typing():
            try:
                if "list=" in source or source.startswith("PL"):
                    playlist_id = source.split("list=")[-1].split("&")[0]
                    title, videos = await extractor.playlist_videos(
                        playlist_id, region=region
                    )
                    name = name or title
                else:
                    videos = await extractor.search(source, limit=25, region=region)
            except BlockedError as exc:
                await ctx.reply(f"⚠️ `{exc}`", mention_author=False)
                return

        if not videos:
            await ctx.reply("🔍 Found nothing to put in the list.", mention_author=False)
            return

        saved = await store.save_playlist(ctx.author.id, name[:60], "youtube", videos)
        await ctx.reply(
            f"✅ **{saved.name}** created — {len(saved.items)} tracks.\n"
            f"Share code: `{saved.share_code}`",
            mention_author=False,
        )

    # -- cloud ------------------------------------------------------------
    @commands.command(name="share", aliases=["paylas"])
    async def share(self, ctx: commands.Context, *, ref: str | None = None) -> None:
        """`!share` — get a code to share your queue (or `!share <name|code>`)."""
        if ref:
            playlist = await store.resolve_playlist(ctx.author.id, ref)
            if playlist is None:
                await ctx.reply(
                    f"❌ `{ref}` not found. Try `{prefix_of(ctx)}vault`.",
                    mention_author=False,
                )
                return
            await ctx.reply(
                f"🔗 **{playlist.name}** share code: `{playlist.share_code}`\n"
                f"Anyone can copy it with `{prefix_of(ctx)}import {playlist.share_code}`.",
                mention_author=False,
            )
            return

        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply(
                "❌ Your playlist is empty! Add videos before sharing.", mention_author=False
            )
            return

        token, reused = await store.create_share(ctx.author.id, queue)
        label = "Share Token (Already Active)" if reused else "Share Token Created!"
        await ctx.reply(
            f"🎫 **{label}**\n`{prefix_of(ctx)}import {token}`\n"
            f"*({len(queue)} tracks • valid for 48 hours)*",
            mention_author=False,
        )

    @commands.command(name="import", aliases=["ice"])
    async def import_cmd(self, ctx: commands.Context, code: str) -> None:
        """`!import <code>` — import someone's queue, or copy a vault list."""
        videos = await store.get_share(code)
        if videos is not None:
            if not videos:
                await ctx.reply(
                    "⚠️ That token points at an empty queue.", mention_author=False
                )
                return
            total = await store.append_queue(ctx.author.id, videos)
            await ctx.reply(
                f"✅ **Playlist Imported!** Added `{len(videos)}` tracks to your queue. "
                f"*(Queue: **{total}**)*",
                mention_author=False,
            )
            return

        # Not a queue token — maybe it is a vault share code.
        source = await store.get_by_code(code)
        if source is None:
            await ctx.reply("❌ **Invalid or Expired Token!**", mention_author=False)
            return
        if source.owner_id == ctx.author.id:
            await ctx.reply("ℹ️ That list is already in your vault.", mention_author=False)
            return

        copied = await store.save_playlist(
            ctx.author.id, source.name[:60], source.source, source.items
        )
        await ctx.reply(
            f"📥 **{copied.name}** copied into your vault — {len(copied.items)} tracks.\n"
            f"New code: `{copied.share_code}`",
            mention_author=False,
        )

    @commands.command(name="restore")
    async def restore(self, ctx: commands.Context) -> None:
        """`!restore` — recover your queue from the database."""
        queue = await store.get_queue(ctx.author.id)
        if not queue:
            await ctx.reply(
                "❌ No saved session found in the database.", mention_author=False
            )
            return

        await ctx.reply(
            f"🔄 **Session Restored!** `{len(queue)}` tracks are loaded in your queue.\n"
            f"*(Your queue is stored in the database, so it survives restarts — "
            f"check it any time with `{prefix_of(ctx)}playlist`.)*",
            mention_author=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VaultCog(bot))
