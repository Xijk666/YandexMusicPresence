import asyncio
from dataclasses import asdict
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import threading
import time
from core import DEFAULT_CLIENT_ID, activity, signature
from discord_ipc import DiscordIPC
from media import MediaSource
from catalog import lookup

DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "YandexMusicPresence"
DEFAULTS = dict(client_id=DEFAULT_CLIENT_ID, source="", enabled=True, show_album=True,
                online_covers=True, hide_paused=False, close_to_tray=True, auto_background=True)

def load_config():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads((DATA / "settings.json").read_text("utf-8"))
        return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    except (OSError, ValueError, TypeError):
        return DEFAULTS.copy()

def save_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temp, path)

class Engine:
    def __init__(self, config):
        self.config = config.copy()
        self.events = queue.Queue(maxsize=4)
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="MusicPresence", daemon=True)
        self.log = logging.getLogger("presence")
        if not self.log.handlers:
            handler = RotatingFileHandler(DATA / "app.log", maxBytes=250_000, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(handler)
            self.log.setLevel(logging.INFO)

    def run(self):
        try:
            asyncio.run(self.loop())
        except Exception:
            self.log.exception("Ошибка рабочего цикла")

    def emit(self, value):
        if self.events.full():
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
        self.events.put_nowait(value)

    async def loop(self):
        media, rpc = MediaSource(), DiscordIPC()
        previous_key, extra, pending = None, {}, None
        artwork_retry_at, artwork_attempts = 0, 0
        last_sig, last_start, sent_at, reconnect_at, saved_at = "", None, -100, 0, 0
        discord, error, ack = "Ожидание Discord", "", 0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                while not self.commands.empty():
                    cmd, value = self.commands.get_nowait()
                    if cmd == "config":
                        old = self.config
                        self.config = value.copy()
                        if old["client_id"] != value["client_id"]:
                            if rpc.handle:
                                try:
                                    rpc.update(None)
                                except Exception:
                                    pass
                            rpc.close()
                            reconnect_at = 0
                        if old["online_covers"] != value["online_covers"]:
                            previous_key = None
                        last_sig = ""
                    elif cmd == "control":
                        try:
                            if not await media.control(value):
                                error = "Плеер не поддержал команду"
                        except Exception:
                            error = "Плеер не ответил на команду"
                try:
                    track = await media.sample(self.config["source"])
                    error = ""
                except Exception as exc:
                    track = None
                    error = "Не удалось прочитать плеер: " + str(exc)
                    # Drop stale metadata immediately. Retry initializing the manager.
                    media.detach()
                    media = MediaSource()
                key = track.key if track else None
                if key != previous_key:
                    previous_key, extra = key, {}
                    artwork_retry_at, artwork_attempts = 0, 0
                    if pending:
                        pending.cancel()
                    pending = None
                if track and pending is None and not extra.get("cover") and now >= artwork_retry_at:
                    pending = asyncio.create_task(asyncio.to_thread(lookup, track, self.config["online_covers"]))
                if pending and pending.done():
                    try:
                        extra = {**extra, **pending.result()}
                    except Exception:
                        pass
                    pending = None
                    artwork_attempts += 1
                    artwork_retry_at = now + min(60, 5 * 2 ** min(artwork_attempts - 1, 4))
                payload = activity(track, extra, self.config["show_album"])
                if not self.config["enabled"] or (track and track.status == "paused" and self.config["hide_paused"]):
                    payload = None
                if not rpc.handle and now >= reconnect_at:
                    try:
                        await asyncio.to_thread(rpc.connect, self.config["client_id"])
                        discord, last_sig = "Discord подключён", ""
                        self.log.info("Discord READY")
                    except Exception as exc:
                        discord = str(exc)
                        reconnect_at = time.monotonic() + 5
                        rpc.close()
                if rpc.handle:
                    try:
                        await asyncio.to_thread(rpc.pump)
                        sig = signature(payload)
                        start = (payload or {}).get("timestamps", {}).get("start")
                        seeked = start is not None and (last_start is None or abs(start - last_start) >= 2)
                        # Native timestamps tick in Discord. Send state/seek changes, not every second.
                        if now - sent_at >= 3 and (sig != last_sig or seeked or now - sent_at >= 15):
                            await asyncio.to_thread(rpc.update, payload)
                            sent_at, last_sig, last_start, ack = time.monotonic(), sig, start, rpc.last_ack
                            discord = "Discord подтвердил статус" if payload else "Статус в Discord скрыт"
                    except Exception as exc:
                        discord = str(exc)
                        self.log.warning("RPC: %s", discord)
                        rpc.close()
                        reconnect_at = time.monotonic() + 5
                state = dict(track=asdict(track) if track else None, extra=extra, discord=discord,
                             connected=bool(rpc.handle), ack=ack, error=error, sessions=media.sessions,
                             payload=payload, sent_signature=last_sig,
                             enabled=self.config["enabled"], updated=time.time())
                self.emit({**state, "thumbnail": media.thumbnail if track else None})
                if now - saved_at >= 1:
                    try:
                        save_json(DATA / "status.json", state)
                    except OSError:
                        pass
                    saved_at = now
                await asyncio.sleep(.5)
        finally:
            if pending:
                pending.cancel()
            media.detach()
            if rpc.handle:
                try:
                    await asyncio.to_thread(rpc.update, None)
                except Exception:
                    pass
            rpc.close()
            try:
                save_json(DATA / "status.json", {"running": False, "updated": time.time(), "payload": None})
            except OSError:
                pass
            self.log.info("Приложение завершено")
