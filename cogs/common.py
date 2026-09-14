"""UI pieces shared by the cogs.

Search results are collected in one shot and split into pages of nine; the
grid image is rendered once per page and cached, and navigating forward or
back edits the same message instead of posting a new one.

The view that produced a user's most recent result set is kept in LAST_VIEW,
which is what lets the text commands (!p, !add, !next, !prev, !page) act on
the same message the buttons drive.
"""
from __future__ import annotations

import contextlib
import io
import logging
from typing import AsyncIterator

import discord
from discord.ext import commands

import config
from core import i18n
from core.models import Video
from core.ratelimit import Busy, Gate
from render.grid import render_grid
from vault import export, store

log = logging.getLogger("ytplug.ui")

PAGE_SIZE = config.RESULTS_PER_PAGE

# user id -> the ResultView behind their latest search
LAST_VIEW: dict[int, "ResultView"] = {}

# Shared ceiling on searches and renders. Rate limits bound how often one user
# asks; this bounds how much work is in flight across everyone, which is the
# limit that actually matters on a small box.
GATE = Gate(config.MAX_CONCURRENT_RENDERS, config.RENDER_WAIT_TIMEOUT)


@contextlib.asynccontextmanager
async def heavy(lang: str = config.DEFAULT_LANGUAGE) -> AsyncIterator[bool]:
    """Holds a slot in the heavy-work gate.

    Yields True when a slot was taken and False when the gate stayed full past
    its timeout, so a command can answer "busy, try again" instead of piling
    onto work the box cannot absorb:

        async with heavy(lang) as ok:
            if not ok:
                ...tell the user...
                return
            ...expensive work...
    """
    try:
        async with GATE:
            yield True
    except Busy:
        log.info(
            "heavy gate full (%d running, %d waiting)", GATE.in_flight, GATE.waiting
        )
        yield False


def prefix_of(ctx: commands.Context) -> str:
    """The prefix actually in use, so help text never lies after !setprefix."""
    invoked = ctx.prefix or config.COMMAND_PREFIX
    # A mention prefix is unusable in copy-paste hints; fall back to the text one.
    return config.COMMAND_PREFIX if invoked.startswith("<@") else invoked


class SaveModal(discord.ui.Modal, title="Save to vault"):
    name = discord.ui.TextInput(
        label="List name", placeholder="e.g. evening mix", max_length=60
    )

    def __init__(self, videos: list[Video], default_name: str) -> None:
        super().__init__()
        self.videos = videos
        self.name.default = default_name[:60]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        playlist = await store.save_playlist(
            interaction.user.id, str(self.name), "youtube", self.videos
        )
        await interaction.response.send_message(
            f"✅ **{playlist.name}** saved to your vault — {len(playlist.items)} tracks.\n"
            f"Share code: `{playlist.share_code}`  •  Export: "
            f"`{config.COMMAND_PREFIX}export {playlist.share_code}`",
            ephemeral=True,
        )


class ResultView(discord.ui.View):
    """Number buttons, page navigation and vault shortcuts under the grid."""

    def __init__(
        self,
        videos: list[Video],
        owner_id: int,
        list_name: str,
        *,
        theme_key: str,
        header: str,
        note: str = "",
        prefix: str = config.COMMAND_PREFIX,
        lang: str = config.DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(timeout=600)
        self.videos = videos
        self.owner_id = owner_id
        self.list_name = list_name
        self.theme_key = theme_key
        self.header = header
        self.note = note
        self.prefix = prefix
        self.lang = lang

        self.page = 0
        self.pages = max(1, -(-len(videos) // PAGE_SIZE))
        self.message: discord.Message | None = None
        self._cache: dict[int, bytes] = {}

        for index in range(min(PAGE_SIZE, len(videos))):
            self.add_item(_PickButton(index))

        if self.pages > 1:
            self.prev_button = _NavButton("◀ Previous", -1)
            self.page_label = _PageLabel()
            self.next_button = _NavButton("Next ▶", +1)
            self.add_item(self.prev_button)
            self.add_item(self.page_label)
            self.add_item(self.next_button)

        self.add_item(_SaveButton())
        self.add_item(_ExportButton())
        self.add_item(_LinksButton())
        self._sync()

    # -- page data --------------------------------------------------------
    def current(self) -> list[Video]:
        start = self.page * PAGE_SIZE
        return self.videos[start : start + PAGE_SIZE]

    def subheader(self) -> str:
        parts = [i18n.t("grid_results", self.lang, count=len(self.videos))]
        if self.pages > 1:
            parts.append(
                i18n.t("grid_page", self.lang, page=self.page + 1, pages=self.pages)
            )
        if self.note:
            parts.append(self.note)
        return "  •  ".join(parts)

    def caption(self) -> str:
        return i18n.t(
            "grid_caption", self.lang,
            header=self.header, page=self.page + 1, pages=self.pages,
            prefix=self.prefix,
        )

    async def file_for_page(self, page: int) -> discord.File:
        if page not in self._cache:
            start = page * PAGE_SIZE
            self._cache[page] = await render_grid(
                self.videos[start : start + PAGE_SIZE],
                theme_key=self.theme_key,
                header=self.header,
                subheader=self.subheader(),
                lang=self.lang,
            )
        return discord.File(io.BytesIO(self._cache[page]), filename=f"page{page + 1}.png")

    # -- button state -----------------------------------------------------
    def _sync(self) -> None:
        shown = len(self.current())
        for child in self.children:
            if isinstance(child, _PickButton):
                child.disabled = child.index >= shown
        if self.pages > 1:
            self.prev_button.disabled = self.page == 0
            self.next_button.disabled = self.page >= self.pages - 1
            self.page_label.label = f"{self.page + 1}/{self.pages}"

    async def show_page(self, interaction: discord.Interaction, page: int) -> None:
        self.page = max(0, min(page, self.pages - 1))
        await interaction.response.defer()
        file = await self.file_for_page(self.page)
        self._sync()
        await interaction.edit_original_response(
            content=self.caption(), attachments=[file], view=self
        )

    async def goto_page(self, page: int) -> bool:
        """Page turn driven by a text command; edits the original message.

        Returns False when the message is gone (deleted, or the view outlived
        it), so the caller can fall back to posting a fresh grid.
        """
        if self.message is None:
            return False
        target = max(0, min(page, self.pages - 1))
        if target == self.page and self.page in self._cache:
            return True
        self.page = target
        file = await self.file_for_page(self.page)
        self._sync()
        try:
            await self.message.edit(content=self.caption(), attachments=[file], view=self)
        except discord.HTTPException:
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if LAST_VIEW.get(self.owner_id) is self:
            del LAST_VIEW[self.owner_id]
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class _PickButton(discord.ui.Button):
    """Posts the nth video of the current page to the channel."""

    def __init__(self, index: int) -> None:
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.primary,
                         row=index // 5)
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ResultView = self.view  # type: ignore[assignment]
        items = view.current()
        if self.index >= len(items):
            await interaction.response.send_message("No video in that slot.", ephemeral=True)
            return
        video = items[self.index]
        await store.log_history(interaction.user.id, video.title, video.url)
        await interaction.response.send_message(
            i18n.t("selected", view.lang, index=self.index + 1, url=video.url)
        )


class _NavButton(discord.ui.Button):
    """Page navigation; only the user who ran the command may turn pages."""

    def __init__(self, label: str, delta: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=2)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ResultView = self.view  # type: ignore[assignment]
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                i18n.t("nav_not_owner", view.lang, prefix=view.prefix),
                ephemeral=True,
            )
            return
        await view.show_page(interaction, view.page + self.delta)


class _PageLabel(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="1/1", style=discord.ButtonStyle.secondary,
                         row=2, disabled=True)


class _SaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Save to vault", style=discord.ButtonStyle.success, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ResultView = self.view  # type: ignore[assignment]
        await interaction.response.send_modal(SaveModal(view.videos, view.list_name))


class _ExportButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Download M3U", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ResultView = self.view  # type: ignore[assignment]
        content = export.build_m3u(view.list_name, view.videos, audio_only=True)
        file = discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename=f"{export.safe_name(view.list_name)}.m3u",
        )
        await interaction.response.send_message(
            f"🎧 {len(view.videos)} tracks (all pages)\n"
            f"`{export.mpv_hint(audio_only=True)} <file>.m3u`",
            file=file,
            ephemeral=True,
        )


class _LinksButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Links", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ResultView = self.view  # type: ignore[assignment]
        items = view.current()
        body = "\n".join(f"`{i + 1}.` [{_clip(v.title)}]({v.url})" for i, v in enumerate(items))
        embed = discord.Embed(
            title=f"{view.list_name} — page {view.page + 1}/{view.pages}",
            description=body,
            colour=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _clip(text: str, limit: int = 60) -> str:
    text = text.replace("[", "(").replace("]", ")")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_indices(args: list[str], upper: int) -> list[int]:
    """`['1-3', '7']` -> `[0, 1, 2, 6]`.

    Accepts space-separated numbers, comma-separated lists and `a-b` ranges in
    any mix, which is how the Ghost Engine's !add and !rm behaved. Out-of-range
    values are dropped rather than rejected, and the result is sorted and
    de-duplicated.

    Commas are split on rather than stripped. Discord hands `!add 1,5,7` over
    as a single argument, and trimming only the outer commas left `1,5,7` —
    which is neither a digit nor a range, so every index was dropped and the
    command answered "enter valid numbers" for a list the help text advertises.
    """
    wanted: set[int] = set()
    for arg in args:
        for piece in arg.replace(",", " ").split():
            if "-" in piece[1:]:
                start_raw, _, end_raw = piece.partition("-")
                if start_raw.isdigit() and end_raw.isdigit():
                    start, end = int(start_raw), int(end_raw)
                    if start <= end:
                        wanted.update(range(start, end + 1))
            elif piece.isdigit():
                wanted.add(int(piece))
    return sorted(i - 1 for i in wanted if 1 <= i <= upper)


async def send_results(
    ctx: commands.Context,
    videos: list[Video],
    *,
    header: str,
    note: str = "",
    list_name: str | None = None,
    status: discord.Message | None = None,
) -> ResultView:
    """Renders the first page's grid and posts it with the navigation buttons.

    When `status` is given the placeholder message is edited in place, so the
    "Searching…" line becomes the result instead of leaving two messages.
    """
    theme = await store.get_theme(ctx.author.id)
    lang = await store.get_language(ctx.author.id)
    view = ResultView(
        videos,
        ctx.author.id,
        list_name or header,
        theme_key=theme,
        header=header,
        note=note,
        prefix=prefix_of(ctx),
        lang=lang,
    )
    file = await view.file_for_page(0)

    if status is not None:
        await status.edit(content=view.caption(), attachments=[file], view=view)
        view.message = status
    else:
        view.message = await ctx.reply(
            content=view.caption(), file=file, view=view, mention_author=False
        )

    LAST_VIEW[ctx.author.id] = view
    return view
