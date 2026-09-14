/*
 * GhostPlay native side — runs in Electron's main process, where spawning a
 * local player is possible at all. Everything that reaches this file came out
 * of a Discord message, so it is treated as hostile input: the renderer's
 * allowlist decides *which* messages get a button, and the checks below decide
 * what is allowed to reach mpv's argv.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { spawn } from "child_process";
import { IpcMainInvokeEvent } from "electron";
import { existsSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

interface PlayRequest {
    kind: "m3u" | "video";
    url: string;
    mpvPath: string;
    richPresence: boolean;
}

type PlayResult = { ok: true; } | { ok: false; error: string; };

/** Discord's own CDN, and nothing else. An attachment URL from anywhere is a
 *  URL an attacker chose, and this one is about to be downloaded and played. */
const ATTACHMENT_HOSTS = new Set([
    "cdn.discordapp.com",
    "media.discordapp.net",
]);

const YOUTUBE_WATCH_RE = /^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/;

/** Whether one playlist entry may be handed to the player.
 *
 *  Checked by *scheme*, not by character. The first version of this filtered on
 *  a character class and rejected 19 of 28 entries in a real Spotify export:
 *  `ytdl://ytsearch1:MINESTYLE Vyzer, Lytra, wasty` is a perfectly ordinary
 *  track, and commas, brackets, `!` and non-ASCII letters are ordinary in music.
 *
 *  Shell metacharacters are not what makes an entry dangerous here — mpv is
 *  never started through a shell, so they are just text. What is dangerous is
 *  mpv's own protocol handlers: `file://`, `edl://`, `archive://`, `memory://`
 *  and friends read from the local disk. Naming the two shapes that are allowed
 *  excludes all of them without guessing at a blocklist.
 */
function entryAllowed(line: string): boolean {
    // Control characters have no business in a URL and can confuse a parser.
    if (/[\u0000-\u001f\u007f]/.test(line)) return false;

    // A direct media link.
    if (/^https?:\/\/\S/i.test(line)) return true;

    const rest = /^ytdl:\/\/(.+)$/i.exec(line)?.[1];
    if (!rest) return false;

    return /^ytsearch\d*:/i.test(rest)        // Spotify imports resolve at play time
        || /^[A-Za-z0-9_-]{11}$/.test(rest)   // a YouTube id
        || /^https?:\/\/\S/i.test(rest);      // a URL handed to yt-dlp
}

const MPV_CANDIDATES: Record<string, string[]> = {
    win32: [
        "C:\\mpv\\mpv.exe",
        "C:\\Program Files\\mpv\\mpv.exe",
        join(process.env.LOCALAPPDATA ?? "", "Programs", "mpv", "mpv.exe"),
        "mpv.exe",
    ],
    darwin: [
        "/opt/homebrew/bin/mpv",
        "/usr/local/bin/mpv",
        "/Applications/mpv.app/Contents/MacOS/mpv",
        "mpv",
    ],
    linux: [
        "/usr/bin/mpv",
        "/usr/local/bin/mpv",
        "/var/lib/flatpak/exports/bin/io.mpv.Mpv",
        "mpv",
    ],
};

/** The platform is read here rather than asked of the user: this file runs in
 *  Node, so `process.platform` is authoritative and cannot be set wrong. */
function findMpv(preferred: string): string | null {
    if (preferred) return existsSync(preferred) ? preferred : null;

    const candidates = MPV_CANDIDATES[process.platform] ?? MPV_CANDIDATES.linux;
    for (const candidate of candidates) {
        // The last candidate is the bare name, left for the OS to resolve on
        // PATH — existsSync cannot answer for it, so it is returned as-is.
        if (!candidate.includes("/") && !candidate.includes("\\")) return candidate;
        if (candidate && existsSync(candidate)) return candidate;
    }
    return null;
}

function validatePlaylist(text: string): string | null {
    const lines = text.split(/\r?\n/);
    if (!lines[0]?.startsWith("#EXTM3U")) return "That file is not an M3U playlist.";

    let entries = 0;
    for (const raw of lines) {
        const line = raw.trim();
        if (!line || line.startsWith("#")) continue;
        if (!entryAllowed(line)) {
            return "That playlist points somewhere unexpected, so it was not opened.";
        }
        entries++;
    }
    return entries ? null : "That playlist has no tracks.";
}

async function fetchPlaylist(url: string): Promise<string> {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !ATTACHMENT_HOSTS.has(parsed.hostname)) {
        throw new Error("That attachment is not hosted on Discord.");
    }

    const response = await fetch(url);
    if (!response.ok) throw new Error(`Discord returned ${response.status} for that file.`);

    const length = Number(response.headers.get("content-length") ?? 0);
    if (length > 1_000_000) throw new Error("That playlist is too large.");

    return await response.text();
}

export async function play(_event: IpcMainInvokeEvent, request: PlayRequest): Promise<PlayResult> {
    const mpv = findMpv(request.mpvPath);
    if (!mpv) {
        return {
            ok: false,
            error: request.mpvPath
                ? "No mpv at the path in GhostPlay's settings."
                : "mpv was not found. Install it, or set its path in GhostPlay's settings.",
        };
    }

    let target: string;
    try {
        if (request.kind === "m3u") {
            const text = await fetchPlaylist(request.url);
            const problem = validatePlaylist(text);
            if (problem) return { ok: false, error: problem };

            // Written out rather than piped: mpv reads the first 256 bytes of
            // the file to find the #GHOST_AUDIO marker that switches it to
            // audio-only, and scripts/ghost.lua needs a real path to do that.
            target = join(tmpdir(), "ghostplay-current.m3u");
            writeFileSync(target, text, "utf8");
        } else {
            if (!YOUTUBE_WATCH_RE.test(request.url)) {
                return { ok: false, error: "That link is not a YouTube video." };
            }
            target = request.url;
        }
    } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : "Could not read that playlist." };
    }

    try {
        // No shell, ever. mpv gets an argv array, so a video title full of
        // `&` or `;` is an argument and never a command.
        const child = spawn(mpv, ["--", target], {
            detached: true,
            stdio: "ignore",
            shell: false,
            env: request.richPresence
                ? process.env
                // Read by scripts/rpc_exporter.lua, which skips starting the
                // presence agent when it is set.
                : { ...process.env, GHOST_RPC_DISABLE: "1" },
        });
        child.on("error", () => { /* reported below via the spawn throw path */ });
        child.unref();
        return { ok: true };
    } catch {
        return { ok: false, error: "mpv could not be started." };
    }
}
