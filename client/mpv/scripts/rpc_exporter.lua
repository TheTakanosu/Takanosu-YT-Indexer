-- ==========================================
-- GHOST ENGINE - RPC EXPORTER AGENT
-- ==========================================
-- Writes what mpv is doing to a small bridge file every 2 seconds; ghost_rpc.py
-- reads it and pushes Discord Rich Presence.
--
-- Bridge format, one value per line:
--   1  media-title
--   2  pause        yes / no
--   3  time-pos     seconds
--   4  vid          video track, or "no" for audio-only
--   5  core-idle    yes / no  -- yes while loading, buffering or paused
--   6  duration     seconds, or empty when unknown
--   7  path         source URL, so the reader can recover the video id
--   8  uploader     channel name, when the source carries one
--
-- Lines 5-8 were added later; the reader treats a shorter file as "playing,
-- unknown duration, no id, no channel", so an old bridge still works.
--
-- `core-idle` is the important one. A YouTube track takes several seconds to
-- resolve through yt-dlp, and during that gap mpv already knows the title but
-- has not started playing. Reporting it lets the presence anchor its timer to
-- the moment audio actually starts instead of the moment the track was picked
-- — which is what made the Discord timer run a few seconds ahead.
--
-- The bridge path is resolved from the config folder rather than hardcoded, so
-- this works wherever the mpv folder lives.

local utils = require 'mp.utils'

local BRIDGE = mp.command_native({"expand-path", "~~/ghost_rpc.txt"})

function export_advanced_presence()
    local title = mp.get_property("media-title", "Standing by...")
    local is_paused = mp.get_property("pause", "false")
    local time_pos = mp.get_property("time-pos", "0")
    local vid = mp.get_property("vid", "no")
    local core_idle = mp.get_property("core-idle", "no")
    local duration = mp.get_property("duration", "")
    local path = mp.get_property("path", "")
    -- yt-dlp passes the channel through as an "uploader" tag.
    local uploader = mp.get_property("metadata/by-key/uploader", "")

    local file = io.open(BRIDGE, "w")
    if file then
        file:write(title .. "\n")
        file:write(is_paused .. "\n")
        file:write(time_pos .. "\n")
        file:write(vid .. "\n")
        file:write(core_idle .. "\n")
        file:write(duration .. "\n")
        file:write(path .. "\n")
        file:write(uploader .. "\n")
        file:close()
    end
end

mp.add_periodic_timer(2, export_advanced_presence)

-- ==========================================
--  Starting the agent
-- ==========================================
-- mpv launches ghost_rpc.py itself, so Rich Presence needs no installation
-- step and leaves nothing behind in Windows' Startup folder. The agent's life
-- is tied to the player: it starts here and exits on its own once this bridge
-- file goes stale, which is what mpv closing looks like from its side.
--
-- The previous design put a shortcut in the Startup folder instead. It worked,
-- but it ran the agent from sign-in to shut-down to serve a player that is
-- usually closed, and Task Manager's Startup tab listed it as `pythonw.exe` —
-- the tab names the program being launched, not the shortcut, and there is no
-- way to change that short of renaming the interpreter, which is a malware
-- technique antivirus software flags.
--
-- `detach` matters: without it mpv kills the agent on shutdown, and a killed
-- agent never clears the presence. Detached, it notices mpv is gone and tidies
-- up after itself. Two mpv windows are safe — the second agent finds the first
-- holding the lock file and exits immediately.

local AGENT = mp.command_native({"expand-path", "~~/ghost_rpc.py"})

-- pythonw first: python.exe would flash a console window on every launch.
local INTERPRETERS = package.config:sub(1, 1) == "\\"
    and {"pythonw.exe", "pyw.exe", "python.exe"}
    or {"python3", "python"}

local function start_agent(index)
    if index > #INTERPRETERS then
        mp.msg.warn("Rich Presence off: no Python on PATH. Install it from "
                    .. "python.org with 'Add Python to PATH' ticked.")
        return
    end

    mp.command_native_async({
        name = "subprocess",
        args = {INTERPRETERS[index], "-u", AGENT},
        playback_only = false,
        detach = true,
    }, function(ok)
        if ok then
            mp.msg.info("Rich Presence agent started (" .. INTERPRETERS[index] .. ").")
        else
            start_agent(index + 1)
        end
    end)
end

-- GHOST_RPC_DISABLE is set by whoever launched mpv when they want playback
-- without a presence. The GhostPlay Vencord plugin sets it from its own
-- toggle; setting it by hand works just as well. The bridge file is still
-- written either way, so an agent already running keeps working.
if (os.getenv("GHOST_RPC_DISABLE") or "") ~= "" then
    mp.msg.info("Rich Presence off: GHOST_RPC_DISABLE is set.")
    return
end

-- Skip silently when the agent is not installed: the exporter is useful on its
-- own, and someone who only wants the bridge file should not be nagged.
local agent_file = io.open(AGENT, "r")
if agent_file then
    agent_file:close()
    start_agent(1)
end
