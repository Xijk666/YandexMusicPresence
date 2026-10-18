"""Pure state/timeline and Discord payload logic; no network or UI."""
from dataclasses import dataclass
import math
import re
import time
import unicodedata

DEFAULT_CLIENT_ID = "1269826362399522849"

def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())

def clock(seconds):
    if seconds is None or not math.isfinite(seconds):
        return "—:—"
    n = max(0, int(seconds))
    return f"{n//3600}:{n//60%60:02}:{n%60:02}" if n >= 3600 else f"{n//60}:{n%60:02}"

def clip(text, limit=128):
    text = " ".join(str(text or "").split())
    # Discord limits strings; count UTF-16 units as well as Python characters.
    while len(text.encode("utf-16-le")) // 2 > limit:
        text = text[:-1]
    return text if len(text) >= 2 else text + "\u200b"

def is_yandex(source):
    s = source.lower()
    return any(x in s for x in ("yandex.music", "yandexmusic", "yandex-music", "yandex music", "yandex.desktop.music", "y.music.exe", "яндекс музыка.exe"))

def cover_url(value):
    from urllib.parse import urlparse
    value = (value or "").replace("%%", "400x400")
    if value and not value.startswith("https://"):
        value = "https://" + value.removeprefix("http://").lstrip("/")
    u = urlparse(value)
    return value if u.scheme == "https" and u.hostname in ("avatars.yandex.net", "avatars.mds.yandex.net") else ""

@dataclass(frozen=True)
class Track:
    source: str
    title: str
    artist: str
    album: str
    status: str
    position: float | None
    duration: float | None
    observed: float
    rate: float = 1.0
    quality: str = "SMTC"

    @property
    def key(self):
        return (self.source, self.title, self.artist, self.album)

    def at(self, now=None):
        if self.position is None:
            return None
        value = self.position
        if self.status == "playing":
            value += max(0, (time.monotonic() if now is None else now) - self.observed) * self.rate
        return max(0, min(value, self.duration)) if self.duration else max(0, value)

class Timeline:
    """Treat LastUpdatedTime as an anchor, never as a continuously moving position.

    On pause without a new anchor freeze our last estimate. On resume with a stale
    anchor advance from the frozen point, excluding time spent paused.
    """
    def __init__(self):
        self.previous = None
        self.anchor = None

    def sample(self, *, source, title, artist, album, status, raw_position, duration,
               updated, rate=1.0, wall=None, mono=None):
        wall = time.time() if wall is None else wall
        mono = time.monotonic() if mono is None else mono
        rate = rate if rate is not None and math.isfinite(rate) and rate > 0 else 1.0
        duration = duration if duration and math.isfinite(duration) and duration > 0 else None
        key = (source, title, artist, album)
        valid = (duration is not None and math.isfinite(raw_position) and raw_position >= 0
                 and updated > 946684800 and updated <= wall + 5)
        anchor = (key, raw_position, updated, duration)
        previous = self.previous if self.previous and self.previous.key == key else None
        position = None
        if valid:
            if previous and self.anchor == anchor:
                position = previous.at(mono)
            else:
                position = raw_position
                if status == "playing":
                    position += max(0, wall - updated) * rate
            position = max(0, min(position, duration))
        result = Track(source, title, artist, album, status, position, duration, mono, rate,
                       "SMTC · системная позиция" if valid else "Плеер не передаёт позицию")
        self.previous, self.anchor = result, anchor
        return result

def activity(track, extra=None, show_album=True, wall=None, mono=None):
    if not track or not track.title or track.status not in ("playing", "paused"):
        return None
    extra = extra or {}
    wall = time.time() if wall is None else wall
    pos = track.at(mono)
    duration = track.duration or extra.get("duration")
    artist = track.artist or "Исполнитель не передан"
    state = artist
    if track.status == "paused":
        state = (f"⏸ Пауза · {clock(pos)} / {clock(duration)} · {artist}"
                 if pos is not None else f"⏸ Пауза · {artist}")
    # Keep Listening on pause: switching to Playing competes with the user's
    # running game and can make the music card disappear. Listening has no
    # frozen-timeline field; the accurate paused position stays in state text.
    # While playing the native progress bar is sufficient; do not duplicate it.
    result = {"type": 2,
              "details": clip(track.title), "state": clip(state), "instance": False}
    album = track.album or extra.get("album", "")
    artwork = cover_url(extra.get("cover"))
    # Shared public assets are optional; no data is uploaded to an image host.
    assets = {"large_image": artwork or "https://raw.githubusercontent.com/FozerG/WinYandexMusicRPC/main/assets/Playing.png",
              "large_text": clip(album if show_album and album else "Яндекс Музыка"),
              "small_image": "https://raw.githubusercontent.com/FozerG/WinYandexMusicRPC/main/assets/" + ("Paused.png" if track.status == "paused" else "Playing.png"),
              "small_text": clip("На паузе" if track.status == "paused" else "Воспроизводится")}
    result["assets"] = assets
    if pos is not None and duration and track.status == "playing" and abs(track.rate - 1) < .001:
        result["timestamps"] = {"start": int(wall - pos), "end": int(wall + duration - pos)}
    url = extra.get("url", "")
    if re.fullmatch(r"https://music\.yandex\.ru/album/\d+/track/\d+", url):
        result["buttons"] = [{"label": "Открыть трек", "url": url}]
        result["details_url"] = url
    return result

def signature(payload):
    if payload is None:
        return "null"
    import json
    p = dict(payload)
    p.pop("timestamps", None)
    return json.dumps(p, sort_keys=True, ensure_ascii=False)
