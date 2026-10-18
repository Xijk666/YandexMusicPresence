import argparse
import ctypes
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from types import SimpleNamespace
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk
import pystray
from core import Track
from engine import Engine, DATA, load_config, save_json
from interface import PlayerView, icon_image, dark_titlebar, BG

TITLE = "Я · Presence"

def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            return bool(winreg.QueryValueEx(k, "YandexMusicPresence")[0])
    except OSError:
        return False

def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
        if enabled:
            command = f'"{sys.executable}" --tray' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}" --tray'
            winreg.SetValueEx(k, "YandexMusicPresence", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(k, "YandexMusicPresence")
            except FileNotFoundError:
                pass

class App:
    def __init__(self, tray=False, preview=False):
        self.preview = preview
        self.config = load_config()
        self.engine = Engine(self.config) if not preview else None
        self.state = {}
        self.closed = False
        self.ui_actions = queue.Queue()
        ctk.set_appearance_mode('dark')
        self.root = ctk.CTk(fg_color=BG)
        self.root.title(TITLE + (' — просмотр дизайна' if preview else ''))
        self.root.geometry('460x660')
        self.root.minsize(440, 650)
        self.icon = ImageTk.PhotoImage(icon_image())
        self.root.iconphoto(True, self.icon)
        asset_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        icon_path = asset_root / 'assets/app.ico'
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.view = PlayerView(self.root, self)
        self.root.after(100, lambda: dark_titlebar(self.root))
        self.auto_hide_pending = not preview
        self.tray = None
        if preview:
            self.prepare_preview()
        else:
            self.tray = pystray.Icon("YandexMusicPresence", icon_image(), TITLE,
                menu=pystray.Menu(pystray.MenuItem("Открыть", lambda *_: self.ui_actions.put("show"), default=True),
                                 pystray.MenuItem("Показать / скрыть статус", lambda *_: self.ui_actions.put("toggle")),
                                 pystray.MenuItem("Выйти", lambda *_: self.ui_actions.put("exit"))))
            threading.Thread(target=self.tray.run, daemon=True).start()
            self.engine.thread.start()
            self.root.after(8000, self.auto_hide)
        if tray:
            self.root.withdraw()
        self.tick_job = self.root.after(200, self.tick)

    def autostart(self):
        return autostart_enabled()

    def prepare_preview(self):
        # Isolated UI sample: no engine thread, network lookup or Discord IPC.
        art = Image.new('RGB', (700, 700), '#557278')
        draw = ImageDraw.Draw(art)
        draw.rectangle((0, 0, 700, 270), fill='#cad2c4')
        draw.ellipse((-200, 195, 860, 920), fill='#d7bd84')
        draw.ellipse((80, 195, 620, 735), fill='#293e42')
        draw.ellipse((155, 270, 545, 660), outline='#648184', width=3)
        draw.ellipse((165, 280, 535, 650), outline='#648184', width=3)
        draw.ellipse((285, 400, 415, 530), fill='#d7bd84')
        buffer = io.BytesIO()
        art.save(buffer, 'PNG')
        self.state = dict(track=dict(source='Design preview', title='После полуночи', artist='Северный берег',
            album='Тихий океан', status='paused', position=72., duration=225., observed=time.monotonic(), rate=1.),
            connected=True, ack=time.time(), thumbnail=buffer.getvalue(),
            extra={}, discord='Просмотр дизайна — данные не отправляются в Discord', sessions=[])
        self.config['enabled'] = True

    def save_settings(self):
        view = self.view
        client = view.client_id.get().strip()
        if not client.isdecimal() or not 17 <= len(client) <= 20:
            messagebox.showerror(TITLE, 'Application ID должен состоять из 17–20 цифр.')
            return
        config = {**self.config, **{key: var.get() for key, var in view.vars.items()},
                  'client_id': client, 'source': view.source.get().strip()}
        try:
            if not self.preview:
                set_autostart(view.startup.get())
                save_json(DATA / 'settings.json', config)
        except OSError as exc:
            messagebox.showerror(TITLE, f'Не удалось сохранить настройки: {exc}')
            return
        self.config = config
        if self.engine:
            self.engine.commands.put(('config', config))
        view.saved.configure(text='Сохранено')

    def toggle(self):
        self.config['enabled'] = not self.config['enabled']
        self.view.vars['enabled'].set(self.config['enabled'])
        if not self.preview:
            save_json(DATA / 'settings.json', self.config)
            self.engine.commands.put(('config', self.config))

    def control(self, action):
        if self.preview:
            if action == 'toggle':
                track = self.state['track']
                track['position'] = Track(**track).at()
                track['status'] = 'playing' if track['status'] == 'paused' else 'paused'
                track['observed'] = time.monotonic()
            return
        self.engine.commands.put(('control', action))

    def open_data(self):
        os.startfile(DATA)

    def open_player(self):
        if self.preview:
            return
        local = Path(os.environ.get('LOCALAPPDATA', ''))
        for path in (local / 'Programs/YandexMusic/Яндекс Музыка.exe', local / 'Programs/YandexMusic/Yandex Music.exe'):
            if path.exists():
                subprocess.Popen([str(path)], creationflags=0x08000000)
                return
        try:
            os.startfile('yandexmusic://')
        except OSError:
            webbrowser.open('https://music.yandex.ru/download/')

    def open_track(self):
        if self.preview:
            return
        url = self.state.get('extra', {}).get('url')
        if url:
            webbrowser.open(url)
        else:
            self.open_player()

    def tick(self):
        if self.closed:
            return
        while not self.ui_actions.empty():
            action = self.ui_actions.get_nowait()
            if action == 'show':
                self.show()
            elif action == 'toggle':
                self.toggle()
            elif action == 'exit':
                self.exit()
                return
        if not self.preview:
            event_path = DATA / 'show.request'
            if event_path.exists():
                try:
                    event_path.unlink()
                except OSError:
                    pass
                self.show()
            try:
                while True:
                    self.state = self.engine.events.get_nowait()
            except queue.Empty:
                pass
        self.view.render(self.state, self.config)
        if self.preview:
            self.view.hint.configure(text='Просмотр дизайна · без подключения к Discord')
        self.tick_job = self.root.after(250, self.tick)
        if not self.preview and time.monotonic() - getattr(self, 'ui_saved_at', 0) > 2:
            try:
                save_json(DATA / 'ui.json', {'running': True, 'window': self.root.state(),
                    'page': self.view.page, 'tray_visible': bool(self.tray.visible),
                    'auto_background': self.config['auto_background'],
                    'window_size': [self.root.winfo_width(), self.root.winfo_height()],
                    'updated': time.time()})
            except OSError:
                pass
            self.ui_saved_at = time.monotonic()

    def show(self):
        self.auto_hide_pending = False
        self.root.deiconify()
        self.root.lift()

    def auto_hide(self):
        if self.closed or not self.auto_hide_pending or not self.config['auto_background']:
            return
        if self.view.page != 'player' or not self.tray.visible:
            self.root.after(1000, self.auto_hide)
            return
        self.auto_hide_pending = False
        self.hide()

    def hide(self):
        self.root.withdraw()

    def on_close(self):
        if self.preview:
            self.exit()
        else:
            self.hide() if self.config['close_to_tray'] else self.exit()

    def exit(self):
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self.tick_job)
        self.root.withdraw()
        if self.engine:
            self.engine.stop.set()
            self.tray.stop()
            self.engine.thread.join(timeout=7)
            try:
                save_json(DATA / 'ui.json', {'running': False, 'tray_visible': False, 'updated': time.time()})
            except OSError:
                pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--preview", action="store_true", help="Isolated design preview; never sends Discord activity")
    args = parser.parse_args()
    if args.preview:
        app = App(preview=True)
        app.root.mainloop()
        return
    DATA.mkdir(parents=True, exist_ok=True)
    if args.diagnose:
        import asyncio
        from media import MediaSource
        from dataclasses import asdict
        async def diagnose():
            source = MediaSource()
            track = await source.sample()
            source.detach()
            save_json(DATA / "diagnostic.json", {"track": asdict(track) if track else None, "sessions": source.sessions})
        asyncio.run(diagnose())
        return
    if args.stop:
        (DATA / "stop.request").touch()
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "Local\\YandexMusicPresence.Personal.v1")
    if ctypes.get_last_error() == 183:
        (DATA / "show.request").touch()
        return
    for name in ("show.request", "stop.request"):
        (DATA / name).unlink(missing_ok=True)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App(args.tray)
    def check_stop():
        if (DATA / "stop.request").exists():
            (DATA / "stop.request").unlink(missing_ok=True)
            app.exit()
        elif not app.closed:
            app.root.after(500, check_stop)
    app.root.after(500, check_stop)
    app.root.mainloop()
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle(mutex)

if __name__ == "__main__":
    main()
