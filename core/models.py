"""Data types produced by the extractor."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class Video:
    video_id: str
    title: str
    channel: str = ""
    channel_id: str = ""
    duration: str = ""          # like "12:04"; empty for live streams
    duration_seconds: int = 0
    views: str = ""             # raw text, e.g. "1.2M views"
    published: str = ""         # "3 days ago"
    thumbnail: str = ""
    avatar: str = ""            # channel avatar, drawn on the grid card
    is_live: bool = False
    is_short: bool = False
    is_upcoming: bool = False

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Video":
        allowed = {f for f in cls.__slots__}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


@dataclass(slots=True)
class Channel:
    channel_id: str
    name: str
    handle: str = ""
    subscribers: str = ""
    avatar: str = ""
    videos: list[Video] = field(default_factory=list)

    @property
    def url(self) -> str:
        if self.handle:
            return f"https://www.youtube.com/{self.handle}"
        return f"https://www.youtube.com/channel/{self.channel_id}"


@dataclass(slots=True)
class Playlist:
    playlist_id: int
    owner_id: int
    name: str
    source: str                 # youtube | spotify | manual
    share_code: str
    created_at: str
    items: list[Video] = field(default_factory=list)
