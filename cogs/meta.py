"""Help, status and diagnostics: !help, !commands, !credits, !ping, !selftest."""
from __future__ import annotations

import platform
import time

import discord
from discord.ext import commands

import config
from core import cache, extractor
from core.http import BlockedError
from cogs.common import GATE, prefix_of

START = time.monotonic()

VERSION = "Ghost Engine V11"
REPO_URL = "https://github.com/TheTakanosu"

# Shown at the bottom of !credits. Add contributors here — one per line, in the
# form the person wants to be named.
SECRET_HELPERS = (
    "iorceful - only audio",
)


def _search_and_discover(p: str) -> str:
    return (
        f"`{p}s <query>` - Search YouTube\n"
        f"`{p}cs <channel>` - Latest Videos from a Channel\n"
        f"`{p}home` - Discover Global Trending\n"
        f"`{p}p <num>` - Play a video directly\n"
        f"`{p}history` - View your playback history\n"
        f"`{p}clearhistory` - Wipe your playback history\n"
        f"`{p}next` / `{p}prev` - Change pages"
    )


def _playlist_vault(p: str) -> str:
    return (
        f"`{p}add <num>` or `{p}a 1-5` - Add multiple search results to queue\n"
        f"`{p}pa <link>` - Add external YouTube link or Playlist to queue\n"
        f"`{p}playlist` - View your queue\n"
        f"`{p}play` or `{p}play 5` - Start playlist\n"
        f"`{p}pn` - Play next video in queue\n"
        f"`{p}rm <num1> <num2>` - Remove specific videos\n"
        f"`{p}move <from> <to>` - Reorder a track\n"
        f"`{p}shuffle` - Randomize queue\n"
        f"`{p}clear` - Empty your queue\n"
        f"`{p}savepl <name>` - Save queue to vault\n"
        f"`{p}loadpl <name/num>` - Load queue from vault\n"
        f"`{p}rmpl <name/num>` - Delete from vault\n"
        f"`{p}renamepl <name/num> | <new>` - Rename a saved playlist\n"
        f"`{p}vault` - View saved playlists"
    )


def _cloud_backup(p: str) -> str:
    return (
        f"`{p}share` - Get a code to share your queue\n"
        f"`{p}import <code>` - Import someone's queue\n"
        f"`{p}restore` - Recover your queue from the database"
    )


def _export_systems(p: str) -> str:
    return (
        f"`{p}export` or `{p}exportvideo` - Download as Video .m3u\n"
        f"`{p}exportmp3` or `{p}exportaudio` - Download as Audio-Only .m3u\n"
        f"`{p}spotify <link>` - Export Spotify as Video M3U\n"
        f"`{p}spotifymp3 <link>` - Export Spotify as Audio-Only M3U\n\n"
        "⚠️ **Spotify Guide:** The bot now supports ANY public playlist or album "
        "globally using the Ghost Engine Scraper! *(max 100 songs per playlist)*"
    )


def _admin(p: str) -> str:
    return (
        f"`{p}setchannel` - Lock bot to channel\n"
        f"`{p}clearchannel` - Remove lock\n"
        f"`{p}setregion` - Change region\n"
        f"`{p}language <en/tr/de/fr>` - Change bot language\n"
        f"`{p}setprefix` - Change bot prefix\n"
        f"`{p}theme <dark/light/ash/onyx>` - Change UI theme"
    )


def _extra(p: str) -> str:
    return (
        f"`{p}live <query>` - Only what is streaming right now\n"
        f"`{p}cl <channel>` - A channel's live streams / broadcast archive\n"
        f"`{p}v <query>` - Send the first result's link directly\n"
        f"`{p}page <num>` - Jump straight to a page\n"
        f"`{p}ytlist <name> | <query>` - Build a vault list without queueing\n"
        f"`{p}show <name/num>` - Print a vault list\n"
        f"`{p}ping` - Latency, uptime, engine status"
    )


class Meta(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help", aliases=["yardim"])
    async def help_cmd(self, ctx: commands.Context) -> None:
        prefix = prefix_of(ctx)
        embed = discord.Embed(
            title="🚀 Takanosu YT-Indexer | System Info",
            description="A high-performance, ad-free YouTube search engine built for Discord.",
            colour=0xDC1E1E,
        )
        embed.add_field(
            name="🛠️ Troubleshooting & Usage Guide",
            value=f"Check out our guide on GitHub:\n👉 **[Takanosu YT-Indexer Repository]({REPO_URL})**",
            inline=False,
        )
        embed.add_field(
            name="👨‍💻 Lead Developer",
            value=f"[TheTakanosu]({REPO_URL})",
            inline=False,
        )
        embed.add_field(
            name="🤖 Command Center",
            value=f"`{prefix}commands` - Shows all command menu.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="commands", aliases=["komutlar"])
    async def commands_cmd(self, ctx: commands.Context) -> None:
        prefix = prefix_of(ctx)
        embed = discord.Embed(title="📋 Command Center", colour=0x2B2D31)
        embed.add_field(name="🔍 Search & Discover", value=_search_and_discover(prefix), inline=False)
        embed.add_field(name="🎵 Playlist Vault & Queue", value=_playlist_vault(prefix), inline=False)
        embed.add_field(name="☁️ Cloud & Backup", value=_cloud_backup(prefix), inline=False)
        embed.add_field(name="🎬 Export Systems", value=_export_systems(prefix), inline=False)
        embed.add_field(name="⚙️ Admin Configurations", value=_admin(prefix), inline=False)
        embed.add_field(name="✨ Extra", value=_extra(prefix), inline=False)
        embed.set_footer(text=VERSION)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="credits")
    async def credits(self, ctx: commands.Context) -> None:
        embed = discord.Embed(title="✨ Credits", colour=0xFFD700)
        embed.add_field(name="👑 Lead Architect", value="TheTakanosu", inline=False)
        embed.add_field(name="🤖 Cyber Co-Pilot", value="Kaptan (AI System)", inline=False)
        embed.add_field(
            name="✨ The Secret Helpers",
            value="The masterminds behind the Ghost Engine architecture\n\n"
                  + "\n".join(SECRET_HELPERS),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="ping", aliases=["durum"])
    async def ping(self, ctx: commands.Context) -> None:
        uptime = int(time.monotonic() - START)
        hours, rem = divmod(uptime, 3600)
        minutes, seconds = divmod(rem, 60)
        embed = discord.Embed(title="Status", colour=0x57F287)
        embed.add_field(name="Latency", value=f"{self.bot.latency * 1000:.0f} ms")
        embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Python", value=platform.python_version())
        embed.add_field(name="Spotify", value="Ghost Scraper: active")
        embed.add_field(name="Cached queries", value=str(len(cache.searches)))
        embed.add_field(
            name="Load",
            value=f"{GATE.in_flight}/{GATE.limit} running, {GATE.waiting} queued",
        )
        embed.add_field(name="Languages", value=", ".join(config.LANGUAGES))
        embed.set_footer(text=VERSION)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="selftest", aliases=["tani"])
    @commands.is_owner()
    async def selftest(self, ctx: commands.Context) -> None:
        """`!selftest` — verifies the extractor still works (bot owner only)."""
        lines: list[str] = []
        async with ctx.typing():
            checks = (
                ("search", extractor.search("lofi hip hop", limit=3)),
                ("live", extractor.search("news", limit=3, live_only=True)),
                ("channel", extractor.channel_videos("@YouTube", limit=3)),
                ("trending", extractor.trending(limit=3)),
            )
            for label, coro in checks:
                try:
                    result = await coro
                    items = result if isinstance(result, list) else result.videos
                    avatars = sum(1 for v in items if v.avatar)
                    lines.append(f"✅ {label}: {len(items)} records ({avatars} with avatar)")
                except (BlockedError, LookupError) as exc:
                    lines.append(f"❌ {label}: {exc}")
        await ctx.reply("\n".join(lines), mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meta(bot))
