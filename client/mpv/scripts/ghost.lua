mp.add_hook("on_load", 50, function()
    local path = mp.get_property("path", "")
    
    if string.match(path, "%.m3u$") then
        local file = io.open(path, "r")
        if file then
            local content = file:read(256)
            file:close()
            
            if content and string.match(content, "#GHOST_AUDIO") then
                mp.set_property("vid", "no")
                mp.set_property("ytdl-format", "bestaudio")
                -- Without a video track mpv opens no window at all, which
                -- leaves an audio list playing with no way to seek, pause or
                -- change the volume except from a terminal nobody has open.
                -- force-window gives it the usual window and on-screen
                -- controls with the cover art in place of the video.
                mp.set_property("force-window", "yes")
                mp.msg.info("Ghost-Audio is online! Thanks for using our system.")
            end
        end
    end
end)