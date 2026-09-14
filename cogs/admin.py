"""Per-user preferences and per-server configuration.

Preferences (`!setregion`, `!language`, `!theme`) are anyone's to set for
themselves. The server-wide switches (`!setchannel`, `!clearchannel`,
`!setprefix`) need authority — a guild administrator, or a member holding one
of `config.AUTHORIZED_ROLES`.

Region and language are deliberately separate commands. Region is YouTube's
`gl`, which decides *whose search results* you get and must be an ISO country
code; language decides *what the bot says* to you. Folding them together is
what let `!setregion EN` be accepted — "EN" is a language, so YouTube ignored
it and quietly fell back to the server's own geography.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from core import i18n
from cogs.common import prefix_of
from render import themes
from vault import store

log = logging.getLogger("ytplug.admin")

REGION_FLAGS = {
    "US": "🇺🇸 **US** - United States",
    "TR": "🇹🇷 **TR** - Türkiye",
    "DE": "🇩🇪 **DE** - Germany",
    "GB": "🇬🇧 **GB** - United Kingdom",
    "FR": "🇫🇷 **FR** - France",
}

LANGUAGE_FLAGS = {
    "en": "🇬🇧 **en** - English",
    "tr": "🇹🇷 **tr** - Türkçe",
    "de": "🇩🇪 **de** - Deutsch",
    "fr": "🇫🇷 **fr** - Français",
}

# Friendly spellings accepted for each theme key.
THEME_ALIASES = {
    "dark": "dark",
    "light": "light", "white": "light",
    "ash": "ash", "gray": "ash", "grey": "ash",
    "onyx": "onyx", "black": "onyx",
}


def is_authorized(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.name in config.AUTHORIZED_ROLES for role in member.roles)


class Admin(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- channel lock -----------------------------------------------------
    @commands.command(name="setchannel")
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context) -> None:
        """`!setchannel` — lock the bot to a channel."""
        lang = await store.get_language(ctx.author.id)
        if not is_authorized(ctx.author):
            await ctx.reply(i18n.t("denied", lang), mention_author=False)
            return

        target = ctx.message.channel_mentions[0] if ctx.message.channel_mentions else ctx.channel
        await store.set_locked_channel(ctx.guild.id, target.id)
        self.bot.invalidate_guild_cache(ctx.guild.id)
        await ctx.reply(
            f"✅ **Command Center Locked!** Channel: {target.mention}.", mention_author=False
        )

    @commands.command(name="clearchannel")
    @commands.guild_only()
    async def clearchannel(self, ctx: commands.Context) -> None:
        """`!clearchannel` — remove the channel lock."""
        lang = await store.get_language(ctx.author.id)
        if not is_authorized(ctx.author):
            await ctx.reply(i18n.t("denied", lang), mention_author=False)
            return

        await store.clear_locked_channel(ctx.guild.id)
        self.bot.invalidate_guild_cache(ctx.guild.id)
        await ctx.reply("🔓 **Channel Lock Removed!**", mention_author=False)

    # -- prefix -----------------------------------------------------------
    @commands.command(name="setprefix")
    @commands.guild_only()
    async def setprefix(self, ctx: commands.Context, new_prefix: str | None = None) -> None:
        """`!setprefix <prefix>` — change the bot prefix for this server."""
        lang = await store.get_language(ctx.author.id)
        if not is_authorized(ctx.author):
            await ctx.reply(i18n.t("denied", lang), mention_author=False)
            return

        if not new_prefix:
            await ctx.reply(
                i18n.t("usage", lang, usage=f"{prefix_of(ctx)}setprefix <new_prefix>"),
                mention_author=False,
            )
            return

        if len(new_prefix) > 5 or new_prefix.isspace():
            await ctx.reply(
                "❌ A prefix has to be 1-5 non-space characters.", mention_author=False
            )
            return

        await store.set_guild_prefix(ctx.guild.id, new_prefix)
        self.bot.invalidate_guild_cache(ctx.guild.id)
        await ctx.reply(
            f"✅ **Prefix Updated!** Your new command prefix is: `{new_prefix}`\n"
            f"*(Try `{new_prefix}commands`.)*",
            mention_author=False,
        )

    # -- region -----------------------------------------------------------
    @commands.command(name="setregion", aliases=["bolge"])
    async def setregion(self, ctx: commands.Context, code: str | None = None) -> None:
        """`!setregion <code>` — change whose search results you get."""
        lang = await store.get_language(ctx.author.id)
        current = await store.get_region(ctx.author.id)

        if not code:
            embed = discord.Embed(
                title="🌍 Personal Region Selection",
                description=i18n.t(
                    "region_current", lang,
                    region=current, prefix=prefix_of(ctx),
                    list="\n".join(REGION_FLAGS.values()),
                ),
                colour=0x2B2D31,
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        region = code.strip().upper()

        # A language code where a country belongs is the single most common
        # mistake here, and silently accepting it disables `gl` — so name it.
        if region in config.REGION_MISTAKES and not config.valid_region(region):
            await ctx.reply(
                i18n.t(
                    "region_did_you_mean", lang, code=region,
                    suggestion=config.REGION_MISTAKES[region], prefix=prefix_of(ctx),
                ),
                mention_author=False,
            )
            return

        if not config.valid_region(region):
            await ctx.reply(
                i18n.t("region_invalid", lang, code=region), mention_author=False
            )
            return

        await store.set_region(ctx.author.id, region)
        await ctx.reply(
            i18n.t("region_set", lang, user=ctx.author.id, region=region),
            mention_author=False,
        )

    # -- language ---------------------------------------------------------
    @commands.command(name="language", aliases=["lang", "dil"])
    async def language(self, ctx: commands.Context, code: str | None = None) -> None:
        """`!language <en/tr/de/fr>` — change what language the bot speaks."""
        current = await store.get_language(ctx.author.id)

        if not code:
            embed = discord.Embed(
                title="🗣️ Interface Language",
                description=i18n.t(
                    "language_current", current,
                    language=f"{code_name(current)} ({current})",
                    prefix=prefix_of(ctx),
                    list="\n".join(LANGUAGE_FLAGS.values()),
                ),
                colour=0x2B2D31,
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        wanted = code.strip().lower()
        if wanted not in config.LANGUAGES:
            await ctx.reply(
                i18n.t(
                    "language_invalid", current, code=wanted,
                    list=", ".join(f"`{c}`" for c in config.LANGUAGES),
                ),
                mention_author=False,
            )
            return

        await store.set_language(ctx.author.id, wanted)
        # Confirm in the language just chosen — the quickest proof it took.
        await ctx.reply(
            i18n.t("language_set", wanted, language=code_name(wanted)),
            mention_author=False,
        )

    # -- theme ------------------------------------------------------------
    @commands.command(name="theme", aliases=["tema"])
    async def theme(self, ctx: commands.Context, name: str | None = None) -> None:
        """`!theme <dark/light/ash/onyx>` — change the grid theme."""
        lang = await store.get_language(ctx.author.id)
        current = await store.get_theme(ctx.author.id)

        if name is None:
            embed = discord.Embed(
                title="UI Theme Selection",
                description=(
                    f"🎨 **Current theme:** `{current}`\n\n"
                    + "\n".join(
                        f"`{prefix_of(ctx)}theme {key}`" for key in themes.names()
                    )
                ),
                colour=0x2B2D31,
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        key = THEME_ALIASES.get(name.strip().lower())
        if key is None:
            await ctx.reply(
                i18n.t(
                    "theme_invalid", lang,
                    list=", ".join(f"`{n}`" for n in themes.names()),
                ),
                mention_author=False,
            )
            return

        await store.set_theme(ctx.author.id, key)
        await ctx.reply(
            i18n.t("theme_set", lang, theme=themes.THEMES[key].label.upper()),
            mention_author=False,
        )


def code_name(code: str) -> str:
    return config.LANGUAGES.get(code, code)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
