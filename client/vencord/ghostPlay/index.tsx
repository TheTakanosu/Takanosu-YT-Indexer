/*
 * GhostPlay — hands a Takanosu YT-Indexer result to your local mpv.
 * Part of Takanosu YT-Indexer. Strictly optional; the bot works without it.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

import { definePluginSettings } from "@api/Settings";
import definePlugin, { OptionType, PluginNative } from "@utils/types";
import { Message } from "@vencord/discord-types";
import { ChannelStore, showToast, Toasts } from "@webpack/common";

const Native = VencordNative.pluginHelpers.GhostPlay as PluginNative<typeof import("./native")>;

// The bot this plugin is built for. The button appears on messages from these
// authors and nowhere else — see the threat model in ../README.md. Anyone in a
// server can post a .m3u, and this plugin's whole job is handing a file to a
// local process, so "which messages count" is the security boundary and it is
// deliberately an allowlist rather than a blocklist.
const DEFAULT_BOT_IDS = "1530546215303909518";

const YOUTUBE_RE =
    /https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/watch\?(?:[^\s]*&)?v=([A-Za-z0-9_-]{11})|youtu\.be\/([A-Za-z0-9_-]{11}))/;

const settings = definePluginSettings({
    botIds: {
        type: OptionType.STRING,
        description:
            "Comma-separated user IDs whose messages get the play button. Leave the default unless you run your own bot.",
        default: DEFAULT_BOT_IDS,
    },
    mpvPath: {
        type: OptionType.STRING,
        description:
            "Full path to mpv. Leave empty to search the usual places and your PATH.",
        default: "",
    },
    richPresence: {
        type: OptionType.BOOLEAN,
        description:
            "Let mpv start the Ghost Engine Rich Presence agent, so what you play shows on your Discord profile.",
        default: true,
    },
});

function allowedAuthors(): Set<string> {
    return new Set(
        settings.store.botIds
            .split(",")
            .map(id => id.trim())
            .filter(id => /^\d{5,25}$/.test(id))
    );
}

/** What, if anything, this message can hand to mpv. */
function playableTarget(message: Message) {
    const m3u = message.attachments?.find(a =>
        a.filename?.toLowerCase().endsWith(".m3u")
    );
    if (m3u) return { kind: "m3u" as const, url: m3u.url, label: m3u.filename };

    const match = YOUTUBE_RE.exec(message.content ?? "");
    if (match) {
        const id = match[1] ?? match[2];
        return { kind: "video" as const, url: `https://www.youtube.com/watch?v=${id}`, label: id };
    }

    return null;
}

function GhostIcon(props: any) {
    return (
        <svg viewBox="0 0 24 24" width={24} height={24} aria-hidden {...props}>
            <path
                fill="currentColor"
                d="M12 2a8 8 0 0 0-8 8v10.3c0 1.1 1.2 1.7 2.1 1.2l1.6-1a1 1 0 0 1 1 0l1.8 1a1 1 0 0 0 1 0l1.8-1a1 1 0 0 1 1 0l1.6 1c.9.5 2.1-.1 2.1-1.2V10a8 8 0 0 0-8-8Z"
            />
            <path fill="var(--background-primary, #000)" d="M10 8.6v5.2l4.4-2.6L10 8.6Z" />
        </svg>
    );
}

export default definePlugin({
    name: "GhostPlay",
    description:
        "Adds a play button to Takanosu YT-Indexer results that opens them in your local mpv.",
    authors: [{ name: "TheTakanosu", id: 0n }],
    settings,

    messagePopoverButton: {
        icon: GhostIcon,
        render(message: Message) {
            if (!allowedAuthors().has(message.author?.id)) return null;

            const target = playableTarget(message);
            if (!target) return null;

            return {
                label: target.kind === "m3u" ? "Play playlist in mpv" : "Play in mpv",
                icon: GhostIcon,
                message,
                channel: ChannelStore.getChannel(message.channel_id),
                onClick: async () => {
                    const result = await Native.play({
                        kind: target.kind,
                        url: target.url,
                        mpvPath: settings.store.mpvPath.trim(),
                        richPresence: settings.store.richPresence,
                    });

                    if (result.ok) {
                        showToast(`Playing ${target.label} in mpv`, Toasts.Type.SUCCESS);
                    } else {
                        showToast(result.error, Toasts.Type.FAILURE);
                    }
                },
            };
        },
    },
});
