# GhostPlay — Vencord plugin

Adds one button to a Takanosu YT-Indexer result in Discord: click it and the
track, or the whole playlist, opens in the mpv on your own machine. No download,
no double-click.

**Strictly optional.** The bot, the exports and Rich Presence all work without
it. Nothing in the bot imports anything from this folder, and nothing here is
needed to run the bot — see *No client mod is required for anything* in the
[main README](../../README.md).

---

## What the button appears on

| Message | Button | What mpv gets |
|---|---|---|
| `!export` / `!exportmp3` / `!spotify` / `!spotifymp3` | ✅ | the attached `.m3u` |
| `!p` / `!v` / `!play` / `!pn`, and the **1-9** grid buttons | ✅ | the YouTube link in the message |
| `!playlist` / `!show` | ❌ | nothing — those are titles, not links |

That last row is deliberate rather than missing. `!show` answers *what is in
this list* and prints titles only; `!export <name>` answers *give it to me* and
produces a file. The button belongs on the answer that contains something to
play. Run `!export <name>` and the button appears on that message.

---

## Security

This plugin takes something out of a Discord message and hands it to a process
on your computer. That is worth being careful about, so the design starts from
the assumption that **every message is hostile** and narrows from there.

**The sender is an allowlist, not a filter.** The button is rendered only for
messages whose author id is in `botIds` — by default, the one bot this was built
for. Anyone in a server can upload a file called `playlist.m3u`; on a message
from anyone else, the button does not exist to be clicked.

**The playlist is read before it is played.** An `.m3u` is a list of things a
player will open, so the file is fetched, parsed and checked first:

- it must be served over HTTPS from `cdn.discordapp.com` / `media.discordapp.net`
- it must be under 1 MB and start with `#EXTM3U`
- every entry must be `ytdl://…`, `ytsearch1:…` or `http(s)://…`

Anything else — a local path, a UNC share, `file://`, a shell metacharacter —
fails the check and nothing is launched.

**mpv is never started through a shell.** `spawn(mpv, ["--", target], { shell: false })`
passes an argv array, so a video title full of `&`, `;` or backticks is an
argument and can never become a command. The `--` guards against a target that
starts with a dash being read as an option.

**The native half is as small as it can be.** Only `native.ts` runs with Node
privileges, and its entire surface is one function that takes a URL and a couple
of settings. Everything else — deciding which messages qualify, reading
settings, drawing the button — stays in the renderer, where it cannot spawn
anything.

---

## Settings

| Setting | Default | What it does |
|---|---|---|
| `botIds` | the Takanosu bot's id | Whose messages get the button. Comma-separated |
| `mpvPath` | *(empty)* | Full path to mpv. Empty means search the usual places, then `PATH` |
| `richPresence` | on | Whether mpv may start the Ghost Engine presence agent |

`richPresence` works through an environment variable rather than a flag: with it
off, mpv is launched with `GHOST_RPC_DISABLE=1`, and
[`scripts/rpc_exporter.lua`](../mpv/scripts/rpc_exporter.lua) reads that and
skips starting the agent. The bridge file is still written, so an agent you
started yourself keeps working. Setting the variable by hand does the same thing.

**Your operating system is detected, not configured.** `native.ts` runs in Node,
so `process.platform` is authoritative — there is no "pick your OS" setting to
get wrong. Windows, macOS and Linux each have their own list of places to look
for mpv before falling back to `PATH`.

---

## Installing

Vencord has no runtime plugin installation: plugins are compiled in, so a custom
one means building Vencord from source. This is Vencord's own documented
workflow for user plugins, and it is an advanced-user path — their words.

```bash
git clone https://github.com/Vendicated/Vencord
cd Vencord
pnpm i
mkdir -p src/userplugins
cp -r <path-to>/Takanosu-YT-Indexer/client/vencord/ghostPlay src/userplugins/
pnpm build
pnpm inject          # pick your Discord install; asks before changing anything
```

Then restart Discord and enable **GhostPlay** in Vencord's plugin list.

> Build into **Discord Canary** if you already run Vencord on your normal
> Discord. The two installs are independent, so a dev build cannot disturb the
> one you use every day.

`pnpm uninject` undoes it. You also need [mpv](https://mpv.io/) with `yt-dlp`
next to it — see [../mpv/README.md](../mpv/README.md), which is the same setup
the `.m3u` exports need anyway.

### Why it is not on the Vencord plugin list

Vencord rejects submissions that serve one specific bot or service as *too
niche*, and that is a fair description of this one. So it lives here, installed
by the people who use the bot, rather than shipping to every Vencord user who
would never have a use for it.
