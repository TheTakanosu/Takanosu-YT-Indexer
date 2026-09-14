"""Everything that can be checked without touching YouTube.

Deliberately network-free, so it is the same answer in CI as on a laptop and a
failure always means the code changed rather than the internet did. The live
checks that do need YouTube live in selftest.py, which is run by hand.

Run it:  python -m unittest discover tests
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core import i18n  # noqa: E402
from core.models import Video  # noqa: E402


def sample_videos() -> list[Video]:
    return [
        Video(video_id="dQw4w9WgXcQ", title="Test Track", channel="Chan", duration="3:32"),
        # A title with the things that actually turn up in music: brackets,
        # punctuation, non-ASCII, and something that would be a mention.
        Video(video_id="BxFJBeqHlAQ", title="ON HER KNEES! (Remix) — Pröz & co @everyone",
              channel="C2", duration="2:16"),
    ]


class Regions(unittest.TestCase):
    """`!setregion` takes ISO country codes, and language codes are the trap."""

    def test_country_codes_accepted(self):
        self.assertTrue(config.valid_region("TR"))
        self.assertTrue(config.valid_region("de"))
        self.assertTrue(config.valid_region(" tr "))

    def test_language_code_rejected(self):
        # "EN" is a language, not a country. YouTube ignores an unknown `gl`
        # and quietly falls back to its own geography, which is how trending
        # looked identical everywhere.
        self.assertFalse(config.valid_region("EN"))

    def test_nonsense_rejected(self):
        for bad in ("ZZ", "XYZ", "", None, "123"):
            self.assertFalse(config.valid_region(bad), bad)

    def test_common_mistakes_get_a_suggestion(self):
        self.assertEqual(config.REGION_MISTAKES.get("EN"), "GB")
        self.assertEqual(config.REGION_MISTAKES.get("UK"), "GB")

    def test_georgia_is_not_corrected_to_germany(self):
        self.assertEqual(config.REGION_MISTAKES.get("GE"), "GE")

    def test_bad_stored_value_repairs_itself_on_read(self):
        self.assertEqual(config.normalise_region("EN"), config.DEFAULT_REGION)
        self.assertEqual(config.normalise_region(None), config.DEFAULT_REGION)

    def test_offered_regions_are_all_valid(self):
        for region in config.REGION_LANGS:
            self.assertTrue(config.valid_region(region), region)

    def test_every_region_has_trending_seeds(self):
        for region in list(config.REGION_LANGS) + ["JP", None, "ZZ"]:
            self.assertTrue(config.trending_seeds(region), region)


class Translations(unittest.TestCase):
    def test_no_language_has_gaps(self):
        self.assertEqual(i18n.coverage(), {})

    def test_all_four_languages_present(self):
        self.assertEqual(set(config.LANGUAGES), {"en", "tr", "de", "fr"})

    def test_placeholders_match_across_languages(self):
        """A `{prefix}` present in English must exist in every translation.

        `t()` catches a formatting error and returns the raw template, so a
        mismatch degrades to a user seeing a literal `{seconds}` rather than
        crashing — which is exactly the kind of thing nobody notices without a
        test.
        """
        holders = lambda text: set(re.findall(r"\{(\w+)", text))
        for key, entry in i18n.STRINGS.items():
            reference = entry.get("en")
            if reference is None:
                continue
            for language, text in entry.items():
                self.assertEqual(holders(reference), holders(text),
                                 f"{key} / {language}")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(i18n.t("rate_limited", "zz", user=1, seconds=1),
                         i18n.t("rate_limited", "en", user=1, seconds=1))

    def test_unknown_key_does_not_raise(self):
        self.assertIsInstance(i18n.t("no_such_key_anywhere", "en"), str)


class M3UContract(unittest.TestCase):
    """The rules ghost.lua and mpv depend on. Breaking these is silent."""

    def setUp(self):
        from vault import export
        self.export = export
        self.videos = sample_videos()

    def test_audio_marker_is_inside_the_first_256_bytes(self):
        # ghost.lua reads exactly that much looking for the marker.
        audio = self.export.build_m3u("list", self.videos, audio_only=True)
        self.assertIn(b"#GHOST_AUDIO", audio.encode("utf-8")[:256])

    def test_video_export_has_no_audio_marker(self):
        video = self.export.build_m3u("list", self.videos, audio_only=False)
        self.assertNotIn("#GHOST_AUDIO", video)

    def test_entries_carry_no_query_string(self):
        """mpv hands everything after `ytdl://` to yt-dlp verbatim.

        `ytdl://<id>?ytdl_format=bestaudio` becomes part of the video id and
        yt-dlp rejects the whole entry — silently, because `loop-playlist=inf`
        just cycles a failing list. Every track in every audio export was
        unplayable when this was wrong.
        """
        audio = self.export.build_m3u("list", self.videos, audio_only=True)
        for line in audio.splitlines():
            if line.startswith("ytdl://"):
                self.assertNotIn("?", line)
                self.assertNotIn("&", line)

    def test_spotify_entries_stay_as_search_queries(self):
        m3u = self.export.build_search_m3u(
            [("Vyzer, Lytra, wasty", "MINESTYLE"), ("Pröz", "ON HER KNEES!")],
            audio_only=True,
        )
        self.assertIn("ytdl://ytsearch1:", m3u)
        self.assertIn(b"#GHOST_AUDIO", m3u.encode("utf-8")[:256])

    def test_one_entry_per_track(self):
        audio = self.export.build_m3u("list", self.videos, audio_only=True)
        self.assertEqual(audio.count("#EXTINF"), len(self.videos))

    def test_titles_never_break_the_line_format(self):
        audio = self.export.build_m3u("list", self.videos, audio_only=True)
        for line in audio.splitlines():
            self.assertNotIn("\n", line)


class Filenames(unittest.TestCase):
    """List names are user input and end up in a path."""

    def setUp(self):
        from vault import export
        self.safe_name = export.safe_name

    def test_separators_are_stripped(self):
        for hostile in ("../../etc/passwd", r"..\..\windows\system32",
                        "C:/Windows/x", r"\\server\share"):
            cleaned = self.safe_name(hostile)
            self.assertNotIn("/", cleaned)
            self.assertNotIn("\\", cleaned)

    def test_result_stays_inside_the_export_folder(self):
        for hostile in ("../../..", "..", ".", "", "  ", "a" * 300):
            path = config.EXPORT_DIR / f"{self.safe_name(hostile)}_CODE_audio.m3u"
            self.assertTrue(
                str(path.resolve()).startswith(str(config.EXPORT_DIR.resolve())),
                hostile,
            )

    def test_length_is_capped(self):
        self.assertLessEqual(len(self.safe_name("a" * 500)), 60)

    def test_empty_name_gets_a_default(self):
        self.assertTrue(self.safe_name(""))
        self.assertTrue(self.safe_name("   "))


class IndexParsing(unittest.TestCase):
    """`!add 1,5,7` — Discord hands a comma list over as one argument.

    Trimming only the outer commas left `1,5,7`, which is neither a digit nor a
    range, so every index was dropped and the command answered "enter valid
    numbers" for a list the help text advertises. 19 of 28 entries in a real
    Spotify export hit the same class of bug in the plugin's validator.
    """

    def setUp(self):
        from cogs.common import parse_indices
        self.parse = parse_indices

    def test_comma_list_in_one_argument(self):
        self.assertEqual(self.parse(["1,5,7"], 9), [0, 4, 6])

    def test_comma_list_split_across_arguments(self):
        self.assertEqual(self.parse(["1,", "5,", "7"], 9), [0, 4, 6])

    def test_range_and_single_mixed_with_commas(self):
        self.assertEqual(self.parse(["1-3,5"], 9), [0, 1, 2, 4])

    def test_plain_range(self):
        self.assertEqual(self.parse(["2-4"], 9), [1, 2, 3])

    def test_out_of_range_is_dropped_not_rejected(self):
        self.assertEqual(self.parse(["99"], 9), [])
        self.assertEqual(self.parse(["1-100"], 9), list(range(9)))

    def test_garbage_yields_nothing(self):
        for junk in (["abc"], [",,,"], ["-5"], ["1-"], ["3-1"]):
            self.assertEqual(self.parse(junk, 9), [], junk)


class Storage(unittest.IsolatedAsyncioTestCase):
    """Queues, vault and settings — against a throwaway database."""

    USER = 999_000_000_000_000_001
    OTHER = 999_000_000_000_000_002

    async def asyncSetUp(self):
        from vault import store
        self.store = store
        self._tmp = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        await store.init()
        self.videos = sample_videos()

    async def asyncTearDown(self):
        self._tmp.cleanup()

    async def test_queue_round_trip(self):
        await self.store.append_queue(self.USER, self.videos)
        self.assertEqual(len(await self.store.get_queue(self.USER)), 2)

    async def test_one_users_queue_is_not_anothers(self):
        await self.store.append_queue(self.USER, self.videos)
        self.assertEqual(await self.store.get_queue(self.OTHER), [])

    async def test_playlist_resolves_by_name_code_and_position(self):
        saved = await self.store.save_playlist(self.USER, "evening mix", "manual", self.videos)
        for ref in ("evening mix", "1", saved.share_code):
            self.assertIsNotNone(await self.store.resolve_playlist(self.USER, ref), ref)

    async def test_another_user_cannot_reach_it(self):
        await self.store.save_playlist(self.USER, "evening mix", "manual", self.videos)
        for ref in ("evening mix", "1"):
            self.assertIsNone(await self.store.resolve_playlist(self.OTHER, ref), ref)

    async def test_bad_references_return_none(self):
        await self.store.save_playlist(self.USER, "evening mix", "manual", self.videos)
        for ref in ("nope", "0", "-1", "9999"):
            self.assertIsNone(await self.store.resolve_playlist(self.USER, ref), ref)

    async def test_rename_keeps_the_share_code(self):
        """Renaming rather than delete-and-save is the whole point.

        A new code would break every `GHOST-XXXXXX` already posted in chat.
        """
        saved = await self.store.save_playlist(self.USER, "typo", "manual", self.videos)
        result = await self.store.rename_playlist(self.USER, "typo", "fixed")
        self.assertEqual(result, ("typo", "fixed"))
        after = await self.store.resolve_playlist(self.USER, "fixed")
        self.assertEqual(after.share_code, saved.share_code)
        self.assertEqual(len(after.items), len(saved.items))

    async def test_another_user_cannot_rename_it(self):
        await self.store.save_playlist(self.USER, "mine", "manual", self.videos)
        self.assertIsNone(await self.store.rename_playlist(self.OTHER, "mine", "theirs"))

    async def test_share_token_shape_and_reuse(self):
        token, reused = await self.store.create_share(self.USER, self.videos)
        self.assertTrue(token.startswith("GHOST-"))
        self.assertEqual(len(token), 12)
        self.assertFalse(reused)
        again, reused_again = await self.store.create_share(self.USER, self.videos)
        self.assertEqual(token, again)
        self.assertTrue(reused_again)

    async def test_share_token_is_case_insensitive_and_unknown_ones_are_none(self):
        token, _ = await self.store.create_share(self.USER, self.videos)
        self.assertIsNotNone(await self.store.get_share(token.lower()))
        self.assertIsNone(await self.store.get_share("GHOST-ZZZZZZ"))

    async def test_settings_repair_themselves_on_read(self):
        await self.store.set_region(self.USER, "EN")
        self.assertEqual(await self.store.get_region(self.USER), config.DEFAULT_REGION)
        await self.store.set_language(self.USER, "klingon")
        self.assertEqual(await self.store.get_language(self.USER), config.DEFAULT_LANGUAGE)


class ShareCodes(unittest.TestCase):
    def test_generated_with_secrets_not_random(self):
        """Share codes hand out access to someone's list.

        `random` is a Mersenne Twister: predictable to anyone who sees enough
        output. The module must not fall back to it.
        """
        source = (Path(__file__).resolve().parent.parent / "vault" / "store.py").read_text(encoding="utf-8")
        self.assertIn("import secrets", source)
        self.assertNotIn("random.choice", source)
        self.assertNotIn("import random", source)

    def test_codes_do_not_collide(self):
        import secrets
        from vault.store import _SHARE_ALPHABET
        seen = {"".join(secrets.choice(_SHARE_ALPHABET) for _ in range(6)) for _ in range(5000)}
        self.assertGreater(len(seen), 4990)


class CommandSurface(unittest.IsolatedAsyncioTestCase):
    """Every cog loads and no two commands answer to the same word."""

    async def test_no_name_or_alias_collides(self):
        import discord
        from discord.ext import commands

        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
        for cog in ("search", "channel", "queue", "vaultcog", "exportcog", "admin", "meta"):
            await bot.load_extension(f"cogs.{cog}")

        words = [c.name for c in bot.commands] + [a for c in bot.commands for a in c.aliases]
        duplicates = {w for w in words if words.count(w) > 1}
        self.assertEqual(duplicates, set())
        self.assertGreaterEqual(len(bot.commands), 46)

    async def test_channel_lock_cannot_lock_itself_out(self):
        """A lock set on the wrong channel has to be undoable."""
        import bot as bot_module
        for name in ("setchannel", "clearchannel", "setprefix"):
            self.assertIn(name, bot_module.LOCK_EXEMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
