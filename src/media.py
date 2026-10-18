"""Read-only Windows media session source. Does not inspect account credentials."""
import asyncio
import time
from core import Timeline, is_yandex
import winrt.windows.foundation
import winrt.windows.foundation.collections
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
from winrt.windows.storage.streams import DataReader

STATUS = {0: "closed", 1: "closed", 2: "stopped", 3: "buffering", 4: "playing", 5: "paused"}

class MediaSource:
    def __init__(self):
        self.manager = None
        self.timeline = Timeline()
        self.sessions = []
        self.selected = None
        self.props = None
        self.metadata_at = 0
        self.dirty = True
        self.subscription = None
        self.thumbnail_key = None
        self.thumbnail = None
        self.thumbnail_attempt_at = -100

    def changed(self, *_):
        self.dirty = True

    def detach(self):
        if self.selected and self.subscription is not None:
            try:
                self.selected.remove_media_properties_changed(self.subscription)
            except Exception:
                pass
        self.subscription = None

    async def sample(self, override=""):
        if self.manager is None:
            self.manager = await asyncio.wait_for(Manager.request_async(), 4)
        sessions = list(self.manager.get_sessions())
        self.sessions = [s.source_app_user_model_id for s in sessions]
        candidates = [s for s in sessions if (s.source_app_user_model_id == override if override else
                      is_yandex(s.source_app_user_model_id) and not s.source_app_user_model_id.startswith("A025C540."))]
        if not candidates:
            self.detach()
            self.selected = self.props = None
            return None
        current = self.manager.get_current_session()
        current_id = current.source_app_user_model_id if current else ""
        candidates.sort(key=lambda s: (int(s.get_playback_info().playback_status) == 4,
                                       s.source_app_user_model_id == current_id), reverse=True)
        session = candidates[0]
        # WinRT objects returned by GetSessions may be new wrappers of the same session.
        if self.selected is None or self.selected != session:
            self.detach()
            self.selected = session
            self.dirty = True
            self.subscription = session.add_media_properties_changed(self.changed)
        if self.dirty or time.monotonic() - self.metadata_at >= 2:
            self.dirty = False
            self.props = await asyncio.wait_for(session.try_get_media_properties_async(), 3)
            self.metadata_at = time.monotonic()
        p = self.props
        if not p or not p.title:
            return None
        info = session.get_playback_info()
        t = session.get_timeline_properties()
        begin = t.start_time.total_seconds()
        track = self.timeline.sample(source=session.source_app_user_model_id, title=p.title,
            artist=p.artist, album=p.album_title, status=STATUS.get(int(info.playback_status), "unknown"),
            raw_position=t.position.total_seconds() - begin,
            duration=t.end_time.total_seconds() - begin,
            updated=t.last_updated_time.timestamp(), rate=info.playback_rate)
        if track.key != self.thumbnail_key:
            self.thumbnail_key, self.thumbnail = track.key, None
            self.thumbnail_attempt_at = -100
        if self.thumbnail is None and time.monotonic() - self.thumbnail_attempt_at >= 2:
            self.thumbnail_attempt_at = time.monotonic()
            if p.thumbnail:
                try:
                    stream = await asyncio.wait_for(p.thumbnail.open_read_async(), 2)
                    try:
                        if 0 < stream.size <= 4_000_000:
                            reader = DataReader(stream)
                            try:
                                await asyncio.wait_for(reader.load_async(stream.size), 2)
                                self.thumbnail = bytes(reader.read_buffer(stream.size))
                            finally:
                                reader.detach_stream()
                                reader.close()
                    finally:
                        stream.close()
                except Exception:
                    self.thumbnail = None
        return track

    async def control(self, action):
        if not self.selected:
            return False
        method = {"toggle": self.selected.try_toggle_play_pause_async,
                  "next": self.selected.try_skip_next_async,
                  "previous": self.selected.try_skip_previous_async}.get(action)
        return await asyncio.wait_for(method(), 3) if method else False
