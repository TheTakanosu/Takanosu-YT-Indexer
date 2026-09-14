-- ==========================================
-- GHOST ENGINE - PORTABLE COOKIE RESOLVER
-- ==========================================
-- mpv hands `ytdl-raw-options` to yt-dlp as literal text, so mpv's own "~~/"
-- shorthand is never expanded there and an absolute path has to be baked in.
-- Hardcoding one in mpv.conf makes the folder machine-specific, and pointing
-- at a cookies.txt that does not exist makes yt-dlp fail on every entry.
--
-- So the path is built here instead: whatever folder this config lives in is
-- resolved at load time, and cookies are only requested when the file is
-- actually there.

local utils = require 'mp.utils'

local function is_file(path)
    local info = utils.file_info(path)
    return info ~= nil and info.is_file
end

local function resolve_raw_options()
    local config_dir = mp.command_native({"expand-path", "~~/"})
    local cookies = utils.join_path(config_dir, "cookies.txt")

    -- node is needed for YouTube's JS challenges; ship node.exe next to mpv.
    local options = "js-runtimes=node"

    if is_file(cookies) then
        options = "cookies=" .. cookies .. "," .. options
        mp.msg.info("cookies.txt found, using " .. cookies)
    else
        mp.msg.info("no cookies.txt in " .. config_dir .. " - continuing without cookies")
    end

    mp.set_property("ytdl-raw-options", options)
end

-- Priority 40 runs ahead of ghost.lua's 50; they touch different properties,
-- but resolving cookies before format selection keeps the order obvious.
mp.add_hook("on_load", 40, resolve_raw_options)
