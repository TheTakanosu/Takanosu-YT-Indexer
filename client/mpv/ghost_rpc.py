# ==========================================
# GHOST ENGINE - DYNAMIC DISCORD RPC
# ==========================================
# Reads the bridge file scripts/rpc_exporter.lua writes every 2 seconds and
# mirrors it into Discord Rich Presence.
#
# Nothing needs to start this: rpc_exporter.lua launches it when mpv opens, and
# it exits once mpv is gone. Run it by hand only to watch what it is doing —
# `ghost_rpc.bat`, or `python ghost_rpc.py` — and it will step aside if the
# copy mpv started is already holding the lock.
#
# Environment overrides (all optional):
#   GHOST_RPC_CLIENT_ID  Discord application id used for the presence
#   GHOST_RPC_BRIDGE     path to ghost_rpc.txt, if it is not next to this file
#   GHOST_RPC_PIPE       force a specific discord-ipc-N socket (0-9)
#   GHOST_RPC_ACTIVITY   force one kind: playing / listening / watching / competing
import os
import re
import sys
import time
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode the emoji in these
# messages — and a redirected stdout (the launcher, or any autostart entry)
# inherits that codec. Printing "connected ✅" then raises UnicodeEncodeError
# and kills the agent at the exact moment it succeeds. Force UTF-8 and never
# let a character take the process down.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# mpv launches this with pythonw.exe, which has no console, so a missing
# dependency would otherwise be an agent that dies without ever saying why.
# The message is still worth printing: running ghost_rpc.bat by hand is the
# way to see it, and that launcher installs the dependency itself.
try:
    from pypresence import ActivityType, Presence  # noqa: E402
except ImportError:
    print("[!] pypresence is not installed. Run ghost_rpc.bat once, or:")
    print("    py -m pip install -r requirements.txt")
    sys.exit(1)

# Public Discord *application* id (not a bot token) — override it with your own
# via GHOST_RPC_CLIENT_ID if you are running your own build.
CLIENT_ID = os.getenv("GHOST_RPC_CLIENT_ID", "1540451413065469992")

# Which discord-ipc-N socket to talk to. Leave unset: pypresence then scans
# 0 through 9 and uses whichever Discord actually opened.
#
# Do not hardcode this. A single Discord client opens `discord-ipc-0`, so
# pinning pipe=1 (as this script used to) only connects when a *second* client
# — Canary, PTB — is already holding pipe 0. That is why the presence appeared
# to depend on having Canary open: with one client running there was nothing on
# pipe 1 and the agent reported "Discord not installed or running".
_pipe = os.getenv("GHOST_RPC_PIPE", "").strip()
PIPE: int | None = int(_pipe) if _pipe.isdigit() else None

# rpc_exporter.lua writes into the mpv config folder. Keeping this script in
# that same folder needs no configuration at all; otherwise point
# GHOST_RPC_BRIDGE at the file.
BRIDGE_FILE = Path(
    os.getenv("GHOST_RPC_BRIDGE") or (Path(__file__).resolve().parent / "ghost_rpc.txt")
)

# One agent at a time. mpv launches the agent itself, so opening a second mpv
# window would otherwise start a second agent pushing the same bridge file into
# the same Discord socket, and the two would fight over the card. The loser
# exits immediately; the winner goes on serving both players, since they write
# to the same bridge.
LOCK_FILE = BRIDGE_FILE.with_name("ghost_rpc.lock")

POLL_SECONDS = 2.0
# How long a freshly started agent waits for a player before giving up. mpv
# starts this agent itself and its exporter writes the bridge about two seconds
# later, so nothing by now means there is no player to mirror — and an agent
# with nothing to mirror is exactly the process this is meant never to become.
STARTUP_GRACE = 30.0
# The exporter refreshes every 2 s, so a file older than this means mpv is gone.
# Checking the timestamp replaces the old `tasklist` call, which spawned a
# process on every single tick, forever.
STALE_AFTER = 8.0
# A jump larger than this means a seek or a playlist loop, so the elapsed timer
# has to be re-synced rather than left running.
SEEK_THRESHOLD = 3.0
# How far Discord's clock may wander from mpv's before the timer is re-anchored.
# Anything past this is visible next to the player, and buffering mid-track is
# enough to cause it.
DRIFT_TOLERANCE = 3.0
RECONNECT_BACKOFF = (2, 5, 10, 30)

_VIDEO_ID_RE = re.compile(r"(?:v=|/|^)([A-Za-z0-9_-]{11})(?:[?&]|$)")

DISCORD_INVITE = "https://discord.gg/ghostengine"

# mqdefault, not hqdefault. Measured across several videos: default (120x90),
# hqdefault (480x360) and sddefault (640x480) are all 4:3, and YouTube pads the
# 16:9 frame into them with black bars baked into the JPEG — which Discord then
# letterboxes again inside its own box, giving the doubled bars.
#
# mqdefault is 320x180, a clean 16:9, and is one of the sizes YouTube generates
# for every video. hq720 and maxresdefault are also clean at 1280x720 but are
# not guaranteed to exist, and a missing image means no artwork at all — not
# worth the risk for a picture Discord draws about 120 px wide.
THUMBNAIL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

# Button labels. Discord fits two buttons on one row only while the pair is
# short enough; past that it stacks them, and the API offers no way to ask for
# a row. Measured against the real client, holding everything else constant:
#
#   32 chars  "▶ Watch on YouTube" + "Discord Server"   stacked
#   30 chars  "Watch on YouTube"   + "Discord Server"   one row
#   27 chars  "Watch YouTube"      + "Discord Server"   one row
#   14 chars  "YouTube"            + "Discord"          one row
#
# So the ceiling sits between 30 and 32, and a leading emoji is drawn wider
# than the single character it counts as — dropping "▶" is what bought the row.
# Shortening further to "Watch YouTube" would add margin but reads as watching
# the site rather than the video, so 30 is where this stops.
BUTTON_WATCH = "Watch on YouTube"
BUTTON_DISCORD = "Discord Server"

# Second line of the card. The first is the track title and the third is the
# channel, so this is where the project name goes.
BRAND = "Ghost Engine"

# A media player should not report "Playing" — audio is "Listening to", video
# is "Watching".
#
# These must be the enum members, not their integers: pypresence reads
# `.value` off whatever it is handed, so a bare int raises
# "'int' object has no attribute 'value'" on the first update.
ACTIVITY_LISTENING = ActivityType.LISTENING
ACTIVITY_WATCHING = ActivityType.WATCHING

_ACTIVITY_NAMES = {
    "playing": ActivityType.PLAYING,
    "listening": ACTIVITY_LISTENING,
    "watching": ACTIVITY_WATCHING,
    "competing": ActivityType.COMPETING,
}

# Force one activity kind for everything, instead of picking per track.
#
# Worth having because some setups filter by activity kind rather than by
# application: Vencord's IgnoreActivities, for instance, can be configured to
# hide "Listening" but allow "Watching". On such a client an audio track
# reported honestly as Listening simply never appears, and the only way to see
# it is to report it as something the filter lets through.
FORCED_ACTIVITY = _ACTIVITY_NAMES.get(
    os.getenv("GHOST_RPC_ACTIVITY", "").strip().lower()
)


def activity_for(has_video: bool):
    if FORCED_ACTIVITY is not None:
        return FORCED_ACTIVITY
    return ACTIVITY_WATCHING if has_video else ACTIVITY_LISTENING


def compose(state: dict, status: str, anchor: int = 0) -> dict:
    """Builds the presence card.

    Discord lays the card out as: details, then state, then large_text. So the
    three lines are the track, the project, and the channel — and the artwork
    is the video's own thumbnail rather than a static logo.

    `status` is "playing", "paused" or "loading". Only "playing" carries
    timestamps: a timer next to a paused or still-loading track counts time the
    listener is not hearing.
    """
    payload: dict = {
        "activity_type": activity_for(state["has_video"]),
        "details": state["title"],
        "state": BRAND,
    }

    if state["channel"]:
        payload["large_text"] = state["channel"]

    # No large_image falls back to the application's own icon, which is the
    # right look for a local file with no thumbnail to show.
    if state["video_id"]:
        payload["large_image"] = THUMBNAIL.format(video_id=state["video_id"])

    buttons = []
    if state["video_id"]:
        buttons.append({
            "label": BUTTON_WATCH,
            "url": f"https://www.youtube.com/watch?v={state['video_id']}",
        })
    buttons.append({"label": BUTTON_DISCORD, "url": DISCORD_INVITE})
    payload["buttons"] = buttons

    if status == "paused":
        payload["state"] = f"⏸️ Paused at {format_timestamp(state['position'])}"
    elif status == "loading":
        payload["state"] = "⏳ Loading…"
    else:
        payload["start"] = anchor
        # With an end as well as a start, Discord draws a progress bar and the
        # track's real length instead of an open-ended counter.
        if state["duration"] > 0:
            payload["end"] = anchor + int(state["duration"])

    return payload


def format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _line(lines: list[str], index: int, default: str = "") -> str:
    return lines[index].strip() if index < len(lines) else default


def _number(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def read_bridge():
    """Current player state, or None when mpv is not running.

    Freshness is judged by the file's mtime: the exporter rewrites it every
    2 seconds while mpv lives, and stops the moment it exits.

    Lines past the fourth were added later, so a bridge written by an older
    exporter still reads — it just reports "playing, unknown length, no id".
    """
    try:
        if time.time() - BRIDGE_FILE.stat().st_mtime > STALE_AFTER:
            return None
        lines = BRIDGE_FILE.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    if len(lines) < 4:
        return None

    paused = _line(lines, 1).lower() in ("true", "yes")
    core_idle = _line(lines, 4, "no").lower() in ("true", "yes")

    return {
        "title": lines[0][:128],
        "paused": paused,
        # The exporter can be caught mid-write; treat a bad value as the start.
        "position": _number(_line(lines, 2)),
        "has_video": _line(lines, 3, "no") != "no",
        # Idle while not paused means loading or buffering: mpv has the title
        # but no audio is coming out yet.
        "loading": core_idle and not paused,
        "duration": _number(_line(lines, 5)),
        "video_id": video_id_from(_line(lines, 6)),
        "channel": _line(lines, 7),
    }


_lock_fd: int | None = None


def claim_single_instance() -> bool:
    """True if this process is the only agent, False if another already runs.

    An advisory byte lock, not a pid file: the operating system releases it the
    moment the holder dies, so an agent killed from Task Manager or lost with a
    crashed mpv does not leave a stale claim that blocks every later start.
    """
    global _lock_fd
    try:
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT)
    except OSError:
        # A read-only or missing folder is not a reason to refuse to run; the
        # lock is a convenience, not a correctness requirement.
        return True

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False

    # Held for the life of the process — closing the descriptor drops the lock.
    _lock_fd = fd
    return True


def video_id_from(path: str) -> str:
    """Recovers the YouTube id from whatever mpv was handed."""
    match = _VIDEO_ID_RE.search(path or "")
    return match.group(1) if match else ""


class PresenceAgent:
    """Owns the Discord connection and survives Discord restarting.

    pypresence raises on a dropped pipe, and the previous version swallowed
    that in a bare `except: pass` — so once Discord restarted the loop kept
    spinning against a dead socket and the presence never came back. Here the
    connection state is tracked explicitly and re-established on failure.
    """

    def __init__(self) -> None:
        self.rpc: Presence | None = None
        self._attempt = 0

    def ensure_connected(self) -> bool:
        if self.rpc is not None:
            return True
        try:
            rpc = Presence(CLIENT_ID, pipe=PIPE) if PIPE is not None else Presence(CLIENT_ID)
            rpc.connect()
        except Exception as exc:
            delay = RECONNECT_BACKOFF[min(self._attempt, len(RECONNECT_BACKOFF) - 1)]
            self._attempt += 1
            print(f"[!] Discord not reachable ({exc}). Retrying in {delay}s.")
            time.sleep(delay)
            return False

        self.rpc = rpc
        self._attempt = 0
        print("[+] Ghost Engine RPC Module successfully connected! ✅")
        return True

    def _drop(self, exc: Exception) -> None:
        print(f"[-] Discord connection lost ({exc}). Will reconnect.")
        try:
            if self.rpc is not None:
                self.rpc.close()
        except Exception:
            pass
        self.rpc = None

    def update(self, **fields) -> bool:
        try:
            self.rpc.update(**fields)
            return True
        except Exception as exc:
            self._drop(exc)
            return False

    def close(self) -> None:
        """Hands the socket back before exit.

        Leaving it to the interpreter means pypresence's asyncio transport is
        collected during shutdown, which prints an "I/O operation on closed
        pipe" traceback over the agent's last line.
        """
        if self.rpc is None:
            return
        try:
            self.rpc.close()
        except Exception:
            pass
        self.rpc = None

    def clear(self) -> bool:
        if self.rpc is None:
            return False
        try:
            self.rpc.clear()
            return True
        except Exception as exc:
            self._drop(exc)
            return False


def run_advanced_ghost_presence() -> None:
    agent = PresenceAgent()

    last_title = ""
    last_pause_state = None
    last_loading = None
    last_position = 0.0
    anchor = 0          # the epoch Discord is counting from
    is_cleared = True
    seen_mpv = False
    started = time.monotonic()

    while True:
        # Read the player before requiring Discord, not after. The reconnect
        # backoff below ends in `continue`, so with Discord shut down the agent
        # would never reach this line — and would sit in that backoff forever
        # waiting to report a player that had already closed. Which is exactly
        # the leftover process this agent is meant not to become.
        state = read_bridge()

        # Both questions about whether this process should still exist are
        # settled here, before Discord is involved at all: an unreachable
        # Discord sends the loop back around from the reconnect backoff below,
        # so anything placed after it is unreachable exactly when the agent has
        # the most reason to leave.
        if state is not None:
            seen_mpv = True
        elif seen_mpv:
            # A failed clear means the socket is already gone, and that takes
            # the presence with it, so there is nothing left to show either way.
            if not is_cleared and agent.clear():
                print("[-] MPV process terminated. RPC cleared.")
            print("[*] mpv closed. Agent exiting.")
            agent.close()
            return
        elif time.monotonic() - started > STARTUP_GRACE:
            # Run by hand with no mpv open. The agent's whole life is one mpv
            # session, so there is nothing here worth waiting around for.
            print(f"[*] No mpv within {int(STARTUP_GRACE)}s. Nothing to mirror.")
            agent.close()
            return

        if not agent.ensure_connected():
            continue

        if state is None:
            time.sleep(POLL_SECONDS)
            continue

        # Has Discord's clock wandered away from the player's? mpv is the truth;
        # anything past the tolerance gets re-anchored. This is what keeps the
        # timer honest through buffering, and it is why the anchor is checked
        # every poll rather than only when the track changes.
        drifted = False
        if anchor and not state["paused"] and not state["loading"]:
            shown = time.time() - anchor
            drifted = abs(shown - state["position"]) > DRIFT_TOLERANCE

        time_jumped = abs(state["position"] - last_position) > SEEK_THRESHOLD
        changed = (
            state["title"] != last_title
            or state["paused"] != last_pause_state
            or state["loading"] != last_loading
            or time_jumped
            or drifted
            or is_cleared
        )

        if changed:
            if state["paused"] or state["loading"]:
                # Wipe the old presence first: Discord keeps a running timer
                # alive otherwise, so a paused track would still tick upward.
                #
                # "loading" is the one that mattered — mpv has the title while
                # yt-dlp is still resolving the stream, and anchoring a timer
                # there counted the whole load, which is what put the clock
                # several seconds ahead of the audio.
                if not agent.clear():
                    continue
                time.sleep(0.3)
                status = "paused" if state["paused"] else "loading"
                ok = agent.update(**compose(state, status))
                anchor = 0
            else:
                anchor = int(time.time() - state["position"])
                if drifted:
                    print(f"[~] Re-anchored timer to {format_timestamp(state['position'])}")
                ok = agent.update(**compose(state, "playing", anchor))

            if ok:
                last_title = state["title"]
                last_pause_state = state["paused"]
                last_loading = state["loading"]
                is_cleared = False
            else:
                anchor = 0

        last_position = state["position"]
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if not claim_single_instance():
        print("[*] Another agent already has the lock. Nothing to do.")
        sys.exit(0)

    print(f"[*] Bridge file: {BRIDGE_FILE}")
    try:
        run_advanced_ghost_presence()
    except KeyboardInterrupt:
        print("\n[*] Stopped.")
