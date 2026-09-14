"""Takanosu YT-Indexer — quota-free YouTube indexing / search bot.

Run with:  python bot.py
"""
from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands, tasks

import config
from core import cache, i18n
from core.http import BlockedError, session
from core.ratelimit import RateLimited, RateLimiter
from vault import store

# Windows consoles default to cp1252 and a redirected stdout inherits it, so a
# log line carrying a video title — which is arbitrary Unicode from YouTube —
# raises UnicodeEncodeError inside the handler. selftest.py and the RPC agent
# already pin UTF-8; the bot itself was the one place left that did not.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ytplug")

COGS = (
    "cogs.search",
    "cogs.channel",
    "cogs.queue",
    "cogs.vaultcog",
    "cogs.exportcog",
    "cogs.admin",
    "cogs.meta",
)

# Commands that must keep working outside a locked channel — otherwise a
# lock set on the wrong channel would be impossible to undo.
LOCK_EXEMPT = frozenset({"setchannel", "clearchannel", "setprefix"})


class YtPlug(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=self._resolve_prefix,
            intents=intents,
            help_command=None,
            # Video and playlist titles are attacker-controlled text that ends
            # up in bot messages. Today they are all wrapped in code spans or
            # embeds, which Discord does not resolve mentions inside — but that
            # is a property of every call site staying careful forever. Denying
            # mass mentions at the client makes it a property of the bot.
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
            activity=discord.Activity(
                type=discord.ActivityType.watching, name=f"{config.COMMAND_PREFIX}commands"
            ),
        )
        self.limiter = RateLimiter(config.USER_RATE, config.GUILD_RATE)
        # guild id -> settings row. Every message would otherwise hit SQLite
        # just to learn the prefix.
        self._guild_cache: dict[int, dict[str, object]] = {}

    # -- guild settings ---------------------------------------------------
    async def guild_settings(self, guild_id: int | None) -> dict[str, object]:
        if guild_id is None:
            return {"locked_channel": None, "prefix": config.COMMAND_PREFIX}
        cached = self._guild_cache.get(guild_id)
        if cached is None:
            cached = await store.get_guild_settings(guild_id)
            self._guild_cache[guild_id] = cached
        return cached

    def invalidate_guild_cache(self, guild_id: int) -> None:
        self._guild_cache.pop(guild_id, None)

    async def _resolve_prefix(self, bot: commands.Bot, message: discord.Message) -> list[str]:
        settings = await self.guild_settings(message.guild.id if message.guild else None)
        prefix = str(settings.get("prefix") or config.COMMAND_PREFIX)
        return commands.when_mentioned_or(prefix)(bot, message)

    # -- lifecycle --------------------------------------------------------
    async def setup_hook(self) -> None:
        await store.init()
        await session.start()
        for cog in COGS:
            await self.load_extension(cog)
            log.info("cog loaded: %s", cog)
        self.housekeeping.start()

    async def close(self) -> None:
        self.housekeeping.cancel()
        await session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("connected: %s (%d guilds)", self.user, len(self.guilds))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        await self.process_commands(message)

    @tasks.loop(minutes=30)
    async def housekeeping(self) -> None:
        self.limiter.prune()
        cache.searches.prune()
        removed = await store.gc_shares()
        if removed:
            log.info("garbage collector: %d expired share token(s) dropped", removed)


bot = YtPlug()


@bot.check
async def channel_lock_check(ctx: commands.Context) -> bool:
    """Silently ignores commands sent outside a guild's locked channel."""
    if ctx.guild is None or ctx.command is None:
        return True
    if ctx.command.name in LOCK_EXEMPT:
        return True

    settings = await bot.guild_settings(ctx.guild.id)
    locked = settings.get("locked_channel")
    if locked and ctx.channel.id != locked:
        raise commands.CheckFailure("channel locked")
    return True


@bot.check
async def rate_limit_check(ctx: commands.Context) -> bool:
    """Charges the command's own cost, not a flat 1 per message.

    A search fans out to several YouTube requests, nine thumbnail
    downloads and a full-page render; !ping does none of that. Charging
    them the same meant the only way to stop search floods was a limit
    tight enough to make the cheap commands annoying.
    """
    guild_id = ctx.guild.id if ctx.guild else None
    name = ctx.command.name if ctx.command else ""
    cost = config.COMMAND_COST.get(name, config.DEFAULT_COMMAND_COST)
    try:
        bot.limiter.check(ctx.author.id, guild_id, cost)
    except RateLimited as exc:
        raise commands.CommandOnCooldown(
            commands.Cooldown(*config.USER_RATE), exc.retry_after, commands.BucketType.user
        ) from exc
    return True


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure) and str(error) == "channel locked":
        return
    lang = await store.get_language(ctx.author.id)

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(
            i18n.t("rate_limited", lang, user=ctx.author.id,
                   seconds=max(1, int(error.retry_after))),
            mention_author=False,
            delete_after=6.0,
        )
        return
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.reply(i18n.t("guild_only", lang), mention_author=False)
        return
    if isinstance(error, commands.NotOwner):
        await ctx.reply(i18n.t("owner_only", lang), mention_author=False)
        return
    if isinstance(error, commands.MissingRequiredArgument):
        prefix = ctx.prefix if ctx.prefix and not ctx.prefix.startswith("<@") else config.COMMAND_PREFIX
        await ctx.reply(
            i18n.t("missing_arg", lang,
                   usage=f"{prefix}{ctx.command.qualified_name} {ctx.command.signature}"),
            mention_author=False,
        )
        return

    original = getattr(error, "original", error)
    if isinstance(original, BlockedError):
        await ctx.reply(
            i18n.t("blocked", lang, error=original), mention_author=False
        )
        return

    log.exception("command error: %s", ctx.command, exc_info=original)
    await ctx.reply(i18n.t("unexpected", lang), mention_author=False)


def main() -> None:
    if not config.DISCORD_TOKEN:
        print("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)
    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
