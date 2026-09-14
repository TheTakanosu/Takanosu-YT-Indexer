# Client-side playback (mpv)

The bot hands you a `.m3u` file. This folder is the player side that turns it
into audio or video, with optional Discord Rich Presence showing what you are
listening to.

Everything here is portable: put the `mpv` folder wherever you like.

---

## ⚠️ Read this first: cookies.txt

`cookies.txt` is **optional** and **never shared**.

If you create one, it holds live Google session cookies — `SID`, `HSID`,
`SSID`, `APISID`, `SAPISID`, `LOGIN_INFO`. Anyone who gets that file can sign
into your Google account. So:

- **never commit it, never upload it, never paste it in a Discord channel**
- it is already in this repo's `.gitignore`, and no example copy is kept here
  on purpose
- you do not need it for normal playback — add one only if you hit
  age-restricted videos or rate limiting

To create your own: install a `cookies.txt` browser extension, log into
YouTube, export **youtube.com** cookies in Netscape format, and save the file
as `cookies.txt` next to `mpv.conf`. `scripts/cookies.lua` picks it up
automatically, and skips it when it is absent.

---

## Setup (Windows)

**1. Get mpv.** Download a portable build from
[mpv.io](https://mpv.io/installation/) and unpack it into a folder, e.g.
`C:\mpv`. You should have `mpv.exe` in there.

**2. Copy this folder's contents into it.** Afterwards `C:\mpv` looks like:

```
C:\mpv\
  mpv.exe
  mpv.conf                  <- from here
  yt-dlp.exe                <- step 3
  node.exe                  <- step 4 (optional)
  scripts\
    cookies.lua             <- from here
    ghost.lua               <- from here
    rpc_exporter.lua        <- from here
  ghost_rpc.py              <- from here (optional, Rich Presence)
  requirements.txt          <- from here (optional, Rich Presence)
```

**3. Add yt-dlp.** Put [`yt-dlp.exe`](https://github.com/yt-dlp/yt-dlp/releases)
next to `mpv.exe`. This is what actually resolves YouTube links — mpv cannot
play them without it.

**4. Add node (optional but recommended).** `mpv.conf` asks yt-dlp for the
`node` JS runtime, which YouTube increasingly needs to solve its player
challenges. Drop [`node.exe`](https://nodejs.org/en/download) next to
`mpv.exe`, or have Node on your `PATH`. Without it some videos fail to
resolve.

**5. Play a list.** Drag the `.m3u` onto `mpv.exe`, or:

```bat
mpv t-playlist-audio-2026.09.09-05.03.m3u
```

Audio lists switch themselves to audio-only — no flags needed. You should see
`Ghost-Audio is online!` in the console.

---

## Discord Rich Presence

Keep `ghost_rpc.py`, `ghost_rpc.bat` and `requirements.txt` **inside the mpv
folder** and install the one dependency, once:

```powershell
cd C:\mpv
py -m pip install -r requirements.txt
```

That is the whole setup. From then on **mpv starts the agent itself**:
`scripts/rpc_exporter.lua` launches it with `pythonw.exe` when the player opens,
and it exits by itself a few seconds after mpv closes. Nothing runs while you
are not playing anything, nothing is placed in Windows' Startup folder, and
there is nothing to uninstall.

Opening a second mpv window is safe. The second agent finds the first one
holding `ghost_rpc.lock` and closes immediately, so a single agent serves both
players — they write to the same bridge file.

**`ghost_rpc.bat` is what you use when something is wrong.** It runs the agent
in a visible console, installs `pypresence` if it is missing, and prints why it
cannot reach Discord. If mpv already has an agent running, this one reports the
lock and closes rather than fighting it; with no mpv open at all it waits 30
seconds for a player and then leaves. The agent is only ever meant to live for
one mpv session, so there is no state in which it sits waiting indefinitely.

### Why there is no autostart script

There used to be an `install-autostart.bat` that put a shortcut in the Startup
folder. It worked, but it ran the agent from sign-in to shut-down to serve a
player that is closed most of the day — and Task Manager's Startup tab labelled
the row `pythonw.exe`, because that tab names the *program being launched*,
Python, rather than the shortcut. There is no way to change that label.

The obvious workaround is the wrong one. Copying `pythonw.exe` to a nicer name
like `GhostEngineRPC.exe` does produce a prettier row — it was tested, and it
runs — but renaming an interpreter to disguise what it is happens to be a
textbook malware technique, and antivirus software flags it as such. Shipping a
compiled `.exe` instead trades a readable Python file for an unsigned binary,
which a stranger should trust *less*.

Letting mpv start the agent settles it without picking either: there is no
startup row to label, because there is no startup entry.

While something is playing, the card looks like this:

```
Ghost Engine — Listening

 ┌───────────┐   Onur Can Özcan- Yalnızlığın Ezgisi (Cover) | Tuanna
 │ thumbnail │   Ghost Engine
 │  of the   │   Tuanna
 │   video   │   01:56 ─────────────── 02:16
 └───────────┘   [ Watch on YouTube ]  [ Discord Server ]
```

Every field comes from mpv: the title and channel from its metadata, the
artwork from the video's own thumbnail, and the bar from the track's real
length. Audio reports as **Listening**, video as **Watching**. Pausing swaps
the bar for `⏸️ Paused at 01:56`, and a local file with no thumbnail falls back
to the application icon and drops the YouTube button.

Running it from somewhere else? Point it at the bridge file. Note these are
**PowerShell** commands — `cmd`'s `set VAR=value` and Bash's `&&` are both
parse errors in PowerShell 5.1, which is what Windows opens by default:

```powershell
$env:GHOST_RPC_BRIDGE = "C:\mpv\ghost_rpc.txt"
py ghost_rpc.py
```

Leave it running next to mpv. It reports **Listening to** for audio and
**Watching** for video (not "Playing" — this is a media player), shows the
current title, keeps an accurate elapsed timer across seeks and playlist loops,
freezes at the right timestamp when you pause, and clears itself when mpv exits.

It is safe to start before Discord: it waits and connects when Discord shows
up, and reconnects on its own if Discord restarts.

To run it under your own Discord application instead of the default one:

```powershell
$env:GHOST_RPC_CLIENT_ID = "your_application_id"
py ghost_rpc.py
```

### If the presence does not appear

**Nothing shows, and the console says "Discord not reachable".**
No Discord client has an IPC socket open. Start the desktop client — the
browser version cannot do Rich Presence. You can see the sockets yourself:

```powershell
[System.IO.Directory]::GetFiles("\\.\pipe\") | Where-Object { $_ -match 'discord-ipc' }
```

One running client gives you `discord-ipc-0`. The agent scans 0–9 and uses
whichever it finds, so this normally just works.

**It connects, but the presence appears on the wrong client.**
Running stable and Canary together means two sockets, and the agent takes the
lowest-numbered one. Which client owns which socket depends on start order, so
find out rather than guess — this posts a labelled presence to each, so you can
read the answer off the two clients:

```powershell
py -c "import time;from pypresence import ActivityType,Presence;rs=[];[rs.append((n,Presence('1540451413065469992',pipe=n))) for n in (0,1)];[ (r.connect(), r.update(activity_type=ActivityType.WATCHING, details=f'>>> PIPE {n} <<<')) for n,r in rs];time.sleep(25);[ (r.clear(),r.close()) for n,r in rs]"
```

Then pin the one you want:

```powershell
$env:GHOST_RPC_PIPE = "1"    # whichever showed on the client you care about
py ghost_rpc.py
```

**It connects and says nothing is wrong, but nobody sees the activity.**
Three things gate it, in order:

1. **Discord → Settings → Activity Privacy → *Share my activity*** must be on.
   With it off Discord shows no activity at all, including Rich Presence pushed
   by an app. Ghost Engine is not a "detected game", so it never appears in the
   Registered Games list — that list does not control it.

2. **Client mods filter by activity kind.** Vencord's *IgnoreActivities*, for
   example, can hide "Listening" while allowing "Watching", and in Whitelist
   mode it hides every application id that is not in its filter list. An audio
   track reported honestly as *Listening* then never shows. Either add
   `1540451413065469992` to that plugin's filter list, or report everything as
   the kind your filter lets through:

   ```powershell
   $env:GHOST_RPC_ACTIVITY = "watching"   # playing / listening / watching / competing
   py ghost_rpc.py
   ```

3. **The agent has to actually be running.** It is a foreground process — if
   you closed the window, nothing is pushing anything. Check:

   ```powershell
   Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
     Where-Object { $_.CommandLine -like '*ghost_rpc*' }
   ```

If stable and Canary behave differently, check Activity Privacy in each: they
do not always agree, and a client mod installed in one is not installed in the
other.

---

## What each file does

| File | Job |
|---|---|
| `mpv.conf` | quality cap (1080p), 75 MB cache, `loop-playlist=inf`, volume 50 |
| `scripts/ghost.lua` | reads the `#GHOST_AUDIO` marker in a `.m3u` and switches mpv to audio-only |
| `scripts/cookies.lua` | resolves `cookies.txt` at runtime so the folder stays portable |
| `scripts/rpc_exporter.lua` | writes player state to `ghost_rpc.txt` every 2 seconds, and starts the agent when mpv opens |
| `ghost_rpc.py` | reads that bridge file and drives Discord Rich Presence; exits when mpv goes away |
| `ghost_rpc.bat` | runs the agent in a visible console for troubleshooting; installs `pypresence` on first run |

### Nothing here requires a client mod

Everything above works on the stock Discord desktop client. Vencord and
BetterDiscord are client modifications, which Discord's terms of service
prohibit — tolerated in practice, but not something a project should *require*
of the people who install it. So Rich Presence, the M3U exports and every bot
command are built against vanilla Discord, and a client mod is only ever an
optional extra on top.

### The `#GHOST_AUDIO` contract

The bot's audio exports carry a marker on line two:

```
#EXTM3U
#GHOST_AUDIO
#EXTINF:-1, Some Track
ytdl://dQw4w9WgXcQ
```

`ghost.lua` reads the **first 256 bytes** of the file, and on finding
`#GHOST_AUDIO` sets `vid=no` and `ytdl-format=bestaudio`. That marker is the
only thing that switches audio mode — the entry URLs stay plain on purpose.

Do not add a query string to those `ytdl://` lines. mpv passes everything after
`ytdl://` to yt-dlp verbatim, so `ytdl://<id>?ytdl_format=bestaudio` becomes
part of the video id and yt-dlp rejects it with
`'<id>?ytdl_format=bestaudio' is not a valid URL`. With `loop-playlist=inf`
mpv then cycles through a list where nothing plays and prints no obvious
failure.

---

## Troubleshooting

**Nothing plays, and yt-dlp says "is not a valid URL".**
An entry has a query string on its `ytdl://` line. See the contract above.

**Some videos fail but others work.**
Usually a missing JS runtime — add `node.exe` (step 4). Failing that, an
age-restricted video may need your own `cookies.txt`.

**`ERROR: Unable to download webpage` on everything.**
`yt-dlp.exe` is missing, or too old. Replace it with the latest release.

**Audio lists play with video.**
`scripts/ghost.lua` is not loading. Confirm it sits in a `scripts` folder
*next to* `mpv.conf`, and run mpv from a console to look for
`Ghost-Audio is online!`.

**yt-dlp errors about a cookies file.**
A `cookies=` path is pointing at a file that does not exist. Delete the
`ytdl-raw-options` line from `mpv.conf` if you re-added it by hand —
`scripts/cookies.lua` handles this and skips cookies when absent.

**Rich Presence shows nothing.**
Check `ghost_rpc.txt` appears in the mpv folder while playing. If it does not,
`rpc_exporter.lua` is not loading. If it does, make sure Discord is running
and that Activity Privacy → "Share your detected activities" is enabled.
