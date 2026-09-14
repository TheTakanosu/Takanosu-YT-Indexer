# Takanosu YT-Indexer

An ad-free YouTube indexing / search engine for Discord that needs **no official
YouTube Data API key and no quota**. Search results come back as a 3×3 PNG that
mimics the YouTube home page and matches Discord's Dark / Light / Ash / Onyx themes.

This is the Ghost Engine: a resilient tree-walking parser, innertube pagination and an
async HTTP layer underneath, with the full command surface (queue, vault, share tokens,
M3U/Spotify export, admin configuration, history, trending) on top — plus an mpv client
that plays the exports and mirrors them into Discord Rich Presence.

**46 commands · 4 interface languages · no API key · no client mod required.**

---

## Contents

- [How it works](#how-it-works)
- [Setup](#setup)
- [Commands](#commands)
- [Client-side playback (mpv)](#client-side-playback-mpv)
- [Spotify](#spotify)
- [Resilience and load](#resilience-and-load)
- [Deploying](#deploying)
- [File layout](#file-layout)
- [What YouTube actually does](#what-youtube-actually-does) — measured findings
- [Design decisions](#design-decisions) — and why the obvious alternative was rejected
- [Roadmap](#roadmap)
- [Limits](#limits)

---

## How it works

Instead of the official API we read the `ytInitialData` state tree YouTube embeds
in the page:

```
GET youtube.com/results?search_query=…   →  ytInitialData  →  renderer nodes  →  Video[]
```

That tree changes constantly, so no fixed JSON path is ever followed; the tree is
walked and every recognised renderer node (`videoRenderer`, `gridVideoRenderer`,
`playlistPanelVideoRenderer`, the newer `lockupViewModel`, `shortsLockupViewModel` …)
is collected. When the layout shifts, the parser degrades one field instead of
breaking outright.

The cookie wall (`Before you continue`) is cleared with `CONSENT` / `SOCS` cookies
stamped into the session up front, and every request goes out with a different
browser profile (User-Agent plus consistent `sec-ch-ua` headers).

### Shorts filter

No single signal is trusted; several hints are combined:

| Hint | Source |
|---|---|
| Renderer type | `reelItemRenderer`, `shortsLockupViewModel` |
| Link | `commandMetadata` → `/shorts/…` |
| Badge | `THUMBNAIL_OVERLAY_BADGE_STYLE_SHORTS` |
| Duration + aspect | ≤ 3 min **and** a vertical thumbnail |

Measured: on `@MrBeast`'s Shorts tab 48/48 records were flagged as Shorts, with no
false positives on the `videos` tab.

---

## Setup

Python **3.10+** (developed on 3.14).

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then paste your token
```

`.env`:

```
DISCORD_TOKEN=...
COMMAND_PREFIX=!
DATA_DIR=data
```

Discord Developer Portal → Bot → **Message Content Intent** must be enabled.

```bash
python bot.py
```

Verify the parser, fonts, translations and grid engine **without connecting to
Discord**:

```bash
python selftest.py
```

It prints which font each weight resolved to, checks all four languages for missing
keys, exercises search / channel / trending / oEmbed / Spotify, renders all four
themes into `data/exports/`, and asserts the M3U contract. Expect `RESULT: passed`.

**No Spotify credentials are needed** — see [Spotify](#spotify).

---

## Commands

### 🔍 Search & Discover
| Command | What it does |
|---|---|
| `!s <query>` | search YouTube — 3×3 grid, up to 54 results, paged with **◀ ▶** |
| `!cs <channel>` | latest long-form videos from a channel; falls back to the broadcast archive when the channel only ever streams |
| `!home` | trending for your region (`!discover` also works) |
| `!p <num>` | play a video from the current page directly |
| `!history` | your playback history (last 10) |
| `!clearhistory` | wipe your playback history |
| `!next` / `!prev` | change pages by text command |

### 🎵 Playlist Vault & Queue
| Command | What it does |
|---|---|
| `!add <num>` or `!a 1-5` | add search results to the queue (ranges and lists both work) |
| `!pa <link>` | add an external YouTube link, playlist or **Mix** to the queue |
| `!playlist` | view your queue |
| `!play` or `!play 5` | start the playlist from the top or a given track |
| `!pn` | play the next video in the queue |
| `!rm <num1> <num2>` | remove specific videos (`!rm 1-5` also works) |
| `!move <from> <to>` | reorder a track |
| `!shuffle` | randomize the queue |
| `!clear` | empty your queue |
| `!savepl <name>` | save the queue to your vault |
| `!loadpl <name/num>` | load a playlist from the vault |
| `!rmpl <name/num>` | delete from the vault |
| `!renamepl <name/num> \| <new name>` | rename a saved playlist, keeping its share code |
| `!vault` | view saved playlists |

Anywhere a list is referenced you can pass its **name**, its **share code**, or its
**position in `!vault`** — `!loadpl 2` and `!loadpl evening mix` do the same thing.

### ☁️ Cloud & Backup
| Command | What it does |
|---|---|
| `!share` | get a `GHOST-XXXXXX` code that shares your queue (valid 48 h) |
| `!import <code>` | import someone's queue — also accepts a vault share code |
| `!restore` | recover your queue from the database |

### 🎬 Export Systems
| Command | What it does |
|---|---|
| `!export` / `!exportvideo` | download the queue as a video `.m3u` |
| `!exportmp3` / `!exportaudio` | download the queue as an audio-only `.m3u` |
| `!spotify <link>` | export a Spotify playlist/album as a video M3U |
| `!spotifymp3 <link>` | export a Spotify playlist/album as an audio-only M3U |

`!export <name/code>` exports that saved vault playlist instead of the live queue.

### ⚙️ Settings and Admin
| Command | What it does |
|---|---|
| `!setregion <code>` | change **whose search results** you get (ISO *country* code) |
| `!language <en/tr/de/fr>` | change **what language the bot speaks** to you |
| `!theme <dark/light/ash/onyx>` | change the grid theme |
| `!setchannel` / `!clearchannel` | lock the bot to one channel |
| `!setprefix` | change the bot prefix for this server |

`setchannel`, `clearchannel` and `setprefix` need a guild administrator or one of the
`Developer` / `Community Manager` / `Higher Staff` roles. They stay usable **outside**
a locked channel, so a lock set on the wrong channel can always be undone.

**Region and language are separate on purpose.** Region is YouTube's `gl` and must be
an ISO *country* code; language is what the bot says to you. See
[Design decisions](#design-decisions).

### ✨ Extra
| Command | What it does |
|---|---|
| `!live <query>` | only what is streaming right now |
| `!cl <channel>` | a channel's live streams / broadcast archive |
| `!v <query>` | send the first result's link directly |
| `!page <num>` | jump straight to a page |
| `!ytlist <name> \| <query>` | build a vault list without queueing |
| `!show <name/num>` | print a vault list, numbered like `!playlist` |
| `!help` / `!commands` / `!credits` | menus |
| `!ping` | latency, uptime, load, cached queries |
| `!selftest` | parser health check (bot owner only) |

The **1–9** buttons under the grid post that video to the channel. **◀ ▶** turn the
page — the same message is edited, so the channel does not fill with new messages, and
only the person who ran the search can turn it. **Save to vault** and **Download M3U**
cover *all pages*; **Links** covers the current page.

### How pagination works

The first page is read from HTML, then `continuationCommand.token` is used against the
`youtubei/v1/search` endpoint to pull up to 5 more pages — 54 videos in about 1.5
seconds, de-duplicated by id. If YouTube refuses a request mid-page, the results
already gathered are kept. Limits live in [config.py](config.py) as `MAX_SEARCH_PAGES`
and `MAX_RESULTS`.

Each page's PNG is rendered once and cached for the life of the view (10 min).
Identical queries also hit a 15-minute smart cache and answer instantly.

---

## Client-side playback (mpv)

The player side is its own project: **[Ghost-Engine-MPV-Setup](https://github.com/TheTakanosu/Ghost-Engine-MPV-Setup)**.
One download and one double-click sets up mpv, yt-dlp and the Rich Presence
agent — no binaries are shipped, and yt-dlp is verified against its published
checksum before it is installed.

```
bot → .m3u → mpv.conf + scripts/ghost.lua → rpc_exporter.lua
                                          → ghost_rpc.txt (bridge, every 2 s)
                                          → ghost_rpc.py → Discord Rich Presence
```

Once it is installed, an audio export switches itself to audio-only — just open the
file, no flags. mpv starts the Rich Presence agent itself and the agent exits with the
player, so there is nothing to launch and no Windows startup entry. The card shows the
video's own thumbnail, the title, the channel and a real progress bar, reporting
**Listening** for audio and **Watching** for video.

### The `#GHOST_AUDIO` contract

Audio exports carry a marker on line two:

```
#EXTM3U
#GHOST_AUDIO
#EXTINF:-1, Some Track
ytdl://dQw4w9WgXcQ
```

`ghost.lua` reads the **first 256 bytes**, and on finding `#GHOST_AUDIO` sets `vid=no`
and `ytdl-format=bestaudio`. That marker is the only thing that switches audio mode, so
the entry URLs stay plain deliberately — see
[What YouTube actually does](#what-youtube-actually-does). `selftest.py` asserts both
halves of this contract.

### The bridge file

`rpc_exporter.lua` writes eight lines every two seconds; anything shorter is treated as
an older exporter and degrades gracefully:

```
1 media-title   2 pause   3 time-pos   4 vid
5 core-idle     6 duration   7 path     8 uploader
```

⚠️ **`cookies.txt` is personal.** If you create one it holds live Google session
cookies — never commit or share it. It is gitignored and no example copy is kept.

---

## Spotify

**No API keys, no developer portal.** The public embed player at
`open.spotify.com/embed/<type>/<id>` ships its whole track list inside a `__NEXT_DATA__`
script tag, and that is what the scraper reads. Any **public** playlist or album works,
in any market; albums are supported as well as playlists; nothing expires.

Each track is written into the M3U as a `ytsearch1:` query, so resolution happens at
playback time rather than costing one YouTube request per track up front.

**The 100-track limit is Spotify's, not a setting here.** Measured against four editorial
playlists that each hold more than that — Rock Classics, All Out 80s, All Out 2000s, Hot
Hits Türkiye — the embed payload carried exactly 100 every time, while shorter lists came
back whole. `SPOTIFY_MAX_TRACKS` matches that ceiling rather than imposing one.

**A private list answers 404, exactly like one that does not exist.** The embed payload
for a private playlist carries `status: 404` and an empty entity, with nothing to tell the
two apart — Spotify serves public lists to anonymous clients and nothing else. The one
usable signal is the link: sharing a *private* list adds a `pt=` playlist token to the
URL and sharing a public one does not, so `is_private_share()` reads that and picks the
wording. It only chooses a message, so a wrong guess costs precision and never an import.

---

## Resilience and load

| Layer | Measure |
|---|---|
| Identity | UA rotated across 4 browser profiles with matching `sec-ch-ua` |
| Cookie wall | `CONSENT` / `SOCS` / `PREF` stamped at session start |
| Pace | `Throttle`: 8 concurrent requests, ≥ 200 ms apart |
| Errors | 3 attempts with exponential backoff and jitter |
| Permanent errors | 404/410 are **not** retried — a missing playlist answers in 0.1 s instead of 8 |
| Command flood | cost-weighted token bucket: 9 tokens / 10 s per user, 40 / 15 s per guild |
| Expensive work | at most **3** searches or renders in flight globally; past that the caller is told to retry |
| Mass mentions | denied at the client, so a hostile video title can never ping a server |
| Event loop | Pillow drawing and SQLite calls run in `asyncio.to_thread` |
| Housekeeping | every 30 min: prune rate buckets, sweep the query cache, GC expired share tokens |

A search costs 3 tokens, a cheap command 1 — so nobody can flood the server with `!s`
while `!playlist` stays comfortable. If the guild bucket refuses, the user's tokens are
refunded rather than burned on a command that never ran.

Everything is configured in one place: [config.py](config.py).

---

## Deploying

Ready-made systemd unit and a step-by-step walkthrough live in
**[deploy/](deploy/)**. Short version:

```bash
sudo apt install -y python3-venv fonts-roboto-unhinted fonts-dejavu-core
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env && chmod 600 .env
sudo cp deploy/takanosu-bot.service /etc/systemd/system/
sudo systemctl enable --now takanosu-bot && journalctl -u takanosu-bot -f
```

The bot opens **no ports** — outbound only — so a restrictive default firewall needs no
changes. A TrueType font is required or the grid renderer measures text wrong and titles
clip; install Roboto for the real YouTube look.

**Coming from the old single-file bot?** `deploy/migrate_from_json.py` imports
`sessions.json`, `saved_custom_playlists.json`, `shared_playlists.json`,
`user_settings.json` and `guild_settings.json` into the SQLite vault. It only reads the
JSON, is safe to re-run, and share tokens keep their original `GHOST-XXXXXX` codes so
links already posted in chat keep working.

---

## File layout

```
bot.py                 entry point, dynamic prefix, channel lock, cost-weighted limits
config.py              every setting
selftest.py            Discord-free health check
core/
  http.py              session, UA rotation, consent, retry, innertube
  extractor.py         ytInitialData parsing, Shorts filter, trending, Mixes, oEmbed
  i18n.py              76 strings × 4 languages, falls back instead of failing
  cache.py             15-minute smart cache for searches
  models.py            Video / Channel / Playlist
  ratelimit.py         token bucket, throttle, heavy-work gate
render/
  grid.py              Pillow 3×3 grid, channel avatars, Roboto weights
  themes.py            Discord Dark / Light / Ash / Onyx palettes
vault/
  store.py             SQLite: queue, vault, history, share tokens, settings
  export.py            .m3u and plain-text export
  spotify.py           Ghost Engine embed scraper
cogs/
  search.py            !s !v !live !home !p !next !prev !page !history !clearhistory
  channel.py           !cs !cl
  queue.py             !add !pa !playlist !play !pn !rm !move !shuffle !clear
  vaultcog.py          !savepl !loadpl !rmpl !renamepl !vault !share !import !restore
                       !ytlist !show
  exportcog.py         !export !exportmp3 !spotify !spotifymp3
  admin.py             !setregion !language !theme !setchannel !clearchannel !setprefix
  meta.py              !help !commands !credits !ping !selftest
  common.py            grid view, buttons, pagination, index parsing, heavy-work gate
(the player side — mpv config, Lua scripts, the Rich Presence agent and the
 GhostPlay Vencord plugin — lives in Ghost-Engine-MPV-Setup)
deploy/                systemd unit, deployment guide, JSON→SQLite migration
```

### State

Everything persists in `data/vault.db` (SQLite, WAL). The queue lives there too, so it
survives a restart on its own — no JSON session files. It is the only file worth backing
up. New tables and columns are created on start, so a `git pull` + restart never drops
anything.

---

## What YouTube actually does

Findings from testing against the live site, not documentation. They explain why parts
of this code look the way they do, and re-deriving them is expensive.

**Trending is gone for anonymous sessions.** `/feed/trending` redirects to the
personalised home feed (`FEwhat_to_watch`), which is empty without a watch history, and
the `FEtrending` browse id answers HTTP 400. Tested in TR, DE, GB, FR and US — all
empty. So `!home` tries the real page first and otherwise builds a feed from
*most-viewed-this-week* searches.

**`gl` alone barely changes results, seeds do.** US, TR and DE all led with the same
global videos. But `gl=TR` + the seed `türkiye` surfaces Turkish channels, and
`gl=DE` + `deutschland` surfaces WELT and DW. Region-specific seeds live in
`config.TRENDING_SEEDS`.

**Ranking a merged pool defeats the seeds.** Sorting everything by view count buries a
local channel's 2 M views under a global 66 M hit, which is how `!home` showed the same
worldwide videos everywhere. Each seed is ranked separately and then interleaved
round-robin; region overlap with US dropped from 5/9 to 3/9.

**mpv passes everything after `ytdl://` to yt-dlp verbatim.** A query string like
`ytdl://<id>?ytdl_format=bestaudio` becomes part of the video id and yt-dlp rejects the
whole entry with `is not a valid URL` — every track in every audio export was
unplayable, silently, because `loop-playlist=inf` just cycles a failing list.
`ytdl://<id>` and `ytdl://ytsearch1:…` both work.

**Playlists cap at 100 for anonymous sessions.** On a 194-video list the page serves 100
items and offers no continuation token, so requesting more changes nothing. That is
YouTube's ceiling, not a setting here.

**Mixes have no playlist page.** `list=RD…` returns 0 items from `/playlist`, but the
watch page carries the queue as 25 `playlistPanelVideoRenderer` nodes.

**Channel avatars moved.** `c4TabbedHeaderRenderer` is no longer sent for channel pages;
the avatar sits at 160×160 under `pageHeaderViewModel` → `decoratedAvatarViewModel`.
Reading only the old location made every `!cs` card fall back to a drawn initial.

**Playlist titles moved too.** `playlistHeaderRenderer` is gone and
`pageHeaderViewModel.title` comes back empty; the title is in the `microformat` block.

**The channel header's text moved into a two-deep list.** `contentMetadataViewModel` is
still sent, but its text now sits at `metadataRows[] -> metadataParts[] -> text.content`
rather than in a `runs`/`simpleText` node. Flattening it returned an empty string, so
`!cs` silently lost the subscriber count on every channel in every language. `text_of`
now walks lists and those two wrappers, and the header reads each part separately so the
count does not arrive glued to the handle and the video count.

**`hqdefault.jpg` has black bars baked in.** It is 480×360 (4:3) with the 16:9 frame
padded into it — as are `default` and `sddefault`. `mqdefault` (320×180) and
`hq720` / `maxresdefault` (1280×720) are clean 16:9. Only `default`, `mqdefault` and
`hqdefault` are generated for every video, so `mqdefault` is the safe clean choice.

**A page can pass a substring check and still fail to parse.** Checking the body for the
*name* `ytInitialData` let block pages through as successes, and the parse then failed
outside the retry loop. The check matches the *assignment* — both `var ytInitialData =`
and `window["ytInitialData"] =` — so a miss retries with a fresh identity instead of
failing the command.

---

## Design decisions

Places where the obvious choice was rejected, and why.

**Region and language are two commands.** Folding them together let `!setregion EN` be
accepted — "EN" is a language, so YouTube ignored the `gl` and silently fell back to the
server's own geography, which is why trending looked identical everywhere. `!setregion`
now validates against real country codes and suggests a correction; a bad value already
stored repairs itself on read.

**`!cs` does not merge the broadcast archive.** Measured: `!s` *already* includes live
streams — 8 of 54 results for "lofi hip hop" — and dropping the video-type filter makes
results *worse* (54 → 31) because Shorts and channel cards fill the pages. The real gap
was channels that only ever stream, whose `/videos` tab is empty; `!cs` now falls back to
`/streams` instead of erroring.

**A vault list is renamed, not rebuilt.** Fixing a typo in a saved list's name used to
mean deleting it and saving the queue again — which mints a new share code and breaks
every `GHOST-XXXXXX` already posted in chat. `!renamepl <name/num> | <new name>` changes
the name in place and leaves the code alone.

**`!show` prints the list, it does not attach it.** Both `!playlist` and `!show` answer
the same question — what is in this list — so they render the same way: numbered titles,
no URLs. The old version built a text dump with a link under every track, which doubled
the height and pushed all but the shortest lists past the message limit into a `.txt`
nobody can read without opening it. Someone who wants the links is better served by
`!export`, which hands them over in a file a player can actually open.

**Untitled live streams are named, not dropped.** Broadcasters often leave a 24/7 stream
untitled, and returning `None` made the stream vanish with no explanation. It is now
named after its channel, localised to the search region.

**The embed scraper is not a workaround for the Developer API — it outlives it.** The
portal's Development Mode caps an app at 25 manually added users, and Extended Quota
Mode is an application written for companies, so a community bot cannot serve arbitrary
people through it. Approval would not even solve the case people ask about: reading
someone's *private* playlist needs that person's own OAuth consent, which no quota tier
grants. The anonymous route the web player itself uses is closed too — measured,
`open.spotify.com/get_access_token` answers 403 and `/api/token` answers 400. The embed
needs no key, no allowlist, no consent screen and nothing that expires; what it costs is
the 100-track ceiling above and a dependency on Spotify's markup.

The player side has its own decisions — why mpv starts the presence agent instead of
Windows, why the interpreter is not renamed, why an audio playlist still gets a
window — written down in [Ghost-Engine-MPV-Setup](https://github.com/TheTakanosu/Ghost-Engine-MPV-Setup#design-decisions).

**No client mod is required for anything.** Vencord and BetterDiscord are client
modifications, which Discord's terms of service prohibit; they are widely tolerated, but
a project should not make its users adopt one to get the core working. Everything here
runs on the stock client.

**Mass mentions are denied at the client, not by careful call sites.** Video and playlist
titles are attacker-controlled text that ends up in bot messages. Today every one is
wrapped in a code span or an embed, which Discord does not resolve mentions inside — but
that is a property of every call site staying careful forever. `AllowedMentions` makes it
a property of the bot.

**Console output is forced to UTF-8.** Windows consoles default to cp1252, and a
redirected stdout inherits it — printing `✅` then raises `UnicodeEncodeError` and kills
the process at the exact moment it succeeds. Both `selftest.py` and the RPC agent pin
UTF-8 with `errors="replace"`.

---

## Roadmap

- **Vencord plugin** — shipped, and living in [Ghost-Engine-MPV-Setup](https://github.com/TheTakanosu/Ghost-Engine-MPV-Setup/tree/main/vencord-plugin): a play button on
  the bot's messages that hands the list straight to your local mpv. It reads the
  sender against an allowlist, validates every entry in a playlist before opening
  it, and never starts mpv through a shell. Strictly optional — nothing here
  depends on it.
- **Per-command maintenance switch** — a runtime kill switch (`!disable spotify
  "under maintenance"`) so a broken module can answer with a notice instead of failing.
  About 50 lines and no second bot; the full CI/CD shadow-bot idea is a lot of
  infrastructure for one server.

---

## Limits

- If the YouTube layout changes a parser field may come back empty; `!selftest` catches
  it early.
- Heavy use from one IP can earn a 429 — reported with a `⚠️` message rather than failing
  silently. `Throttle` is tuned for one instance per IP.
- `.m3u` files are link lists, not media; resolution is left to the player (yt-dlp).
- A Spotify markup change would break the embed scraper. Each failure mode has its own
  message so the cause is obvious.
- Playlists stop at 100 items and Mixes at ~25 — both YouTube's ceilings.
