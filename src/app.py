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
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
import winreg
from PIL import Image, ImageDraw, ImageTk
import pystray
from core import Track, clock, DEFAULT_CLIENT_ID
from engine import Engine, DATA, load_config, save_json

TITLE = "Я · Presence"
BG, PANEL, FG, MUTED, ACCENT = "#101116", "#1c1e27", "#f4f4f8", "#9b9dac", "#ffce3a"

def icon_image():
    im = Image.new("RGBA", (128, 128), (16, 17, 22, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((5, 5, 123, 123), 30, fill=ACCENT)
    for x, h in ((29, 24), (45, 54), (61, 78), (77, 46), (93, 30)):
        d.rounded_rectangle((x, 64-h//2, x+8, 64+h//2), 4, fill=BG)
    return im

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
    def __init__(self, tray=False):
        self.config = load_config()
        self.engine = Engine(self.config)
        self.state = {}
        self.closed = False
        self.cover_key = None
        self.ui_actions = queue.Queue()
        self.root = tk.Tk()
        self.root.title(TITLE + " — Яндекс Музыка в Discord")
        self.root.geometry("880x740")
        self.root.minsize(760, 660)
        self.root.configure(bg=BG)
        if tray:
            self.root.withdraw()
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.root.option_add("*Background", PANEL)
        self.root.option_add("*Foreground", FG)
        self.icon = ImageTk.PhotoImage(icon_image())
        self.root.iconphoto(True, self.icon)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()
        self.root.update_idletasks()
        self.root.minsize(max(760, self.root.winfo_reqwidth()), max(660, self.root.winfo_reqheight()))
        self.tray = pystray.Icon("YandexMusicPresence", icon_image(), TITLE,
            menu=pystray.Menu(pystray.MenuItem("Открыть", lambda *_: self.ui_actions.put("show"), default=True),
                             pystray.MenuItem("Показать / скрыть статус", lambda *_: self.ui_actions.put("toggle")),
                             pystray.MenuItem("Выход", lambda *_: self.ui_actions.put("exit"))))
        self.tray_thread = threading.Thread(target=self.tray.run, daemon=True)
        self.tray_thread.start()
        self.engine.thread.start()
        self.root.after(200, self.tick)
        self.auto_hide_pending = True
        self.root.after(8000, self.auto_hide)
        if tray:
            self.root.withdraw()

    def label(self, parent, text, size=10, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, fg=color, bg=parent.cget("bg"),
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=ACCENT if primary else "#2a2d39",
                         fg=BG if primary else FG, relief="flat", bd=0, cursor="hand2",
                         activebackground="#ead06d" if primary else "#373b4d", activeforeground=BG if primary else FG,
                         padx=14, pady=9)

    def build_ui(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=30, pady=(24, 18))
        self.label(head, "Я · Presence", 26, bold=True).pack(side="left")
        self.label(head, "ЛИЧНАЯ МУЗЫКАЛЬНАЯ АКТИВНОСТЬ", 9, MUTED).pack(side="right", pady=12)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(20, 10))
        style.map("TNotebook.Tab", background=[("selected", "#30323c")], foreground=[("selected", FG)])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#353744", borderwidth=0)
        notebook = self.notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        live, settings, info = [tk.Frame(notebook, bg=PANEL) for _ in range(3)]
        for frame, name in ((live, "Сейчас играет"), (settings, "Настройки"), (info, "Диагностика")):
            notebook.add(frame, text=name)
        top = tk.Frame(live, bg=PANEL)
        top.pack(fill="x", padx=24, pady=(22, 14))
        self.badge = self.label(top, "●  ИЩЕМ ПЛЕЕР", 10, ACCENT, True)
        self.badge.pack(side="left")
        self.toggle_btn = self.button(top, "Скрыть статус", self.toggle)
        self.toggle_btn.pack(side="right")
        card = tk.Frame(live, bg=PANEL)
        card.pack(fill="x", padx=24, pady=10)
        self.placeholder = ImageTk.PhotoImage(icon_image().resize((152,152)))
        self.cover = tk.Label(card, image=self.placeholder, bd=0, bg=PANEL)
        self.cover.pack(side="left", padx=(0, 22), anchor="n")
        meta = tk.Frame(card, bg=PANEL)
        meta.pack(side="left", fill="both", expand=True)
        self.track_title = self.label(meta, "Включите Яндекс Музыку", 20, bold=True, anchor="w", justify="left", wraplength=520)
        self.track_title.pack(fill="x", pady=(5, 8))
        self.artist = self.label(meta, "Трек появится здесь автоматически", 13, MUTED, anchor="w", justify="left", wraplength=520)
        self.artist.pack(fill="x")
        self.album = self.label(meta, "", 10, MUTED, anchor="w", justify="left", wraplength=520)
        self.album.pack(fill="x", pady=(12, 0))
        timeline = tk.Frame(live, bg=PANEL)
        timeline.pack(fill="x", padx=24, pady=(18, 5))
        self.position = self.label(timeline, "—:—", 18, bold=True)
        self.position.pack(side="left")
        self.duration = self.label(timeline, "—:—", 13, MUTED)
        self.duration.pack(side="right")
        self.progress = ttk.Progressbar(live, maximum=100, mode="determinate")
        self.progress.pack(fill="x", padx=24, pady=(0, 10))
        self.quality = self.label(live, "Читаем системную медиасессию Windows", 10, MUTED, wraplength=740, justify="left", anchor="w")
        self.quality.pack(fill="x", padx=24)
        controls = tk.Frame(live, bg=PANEL)
        controls.pack(pady=18)
        for name, action in (("⏮ Назад", "previous"), ("▶ / ⏸", "toggle"), ("Вперёд ⏭", "next")):
            self.button(controls, name, lambda a=action: self.engine.commands.put(("control", a)), action == "toggle").pack(side="left", padx=5)
        bottom = tk.Frame(live, bg="#252834")
        bottom.pack(fill="x", padx=24, pady=(0, 18))
        self.connection = self.label(bottom, "Ожидание Discord…", 11, FG, True, anchor="w")
        self.connection.pack(fill="x", padx=14, pady=(10, 3))
        self.sync = self.label(bottom, "", 9, MUTED, anchor="w", wraplength=720, justify="left")
        self.sync.pack(fill="x", padx=14, pady=(0, 12))
        links = tk.Frame(live, bg=PANEL)
        links.pack(fill="x", padx=24)
        self.button(links, "Яндекс Музыка", self.open_player).pack(side="left")
        self.button(links, "Открыть трек", self.open_track).pack(side="left", padx=8)
        self.button(links, "В трей", self.hide).pack(side="right")
        self.build_settings(settings)
        self.diagnostic = tk.Text(info, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", wrap="word", padx=20, pady=20)
        self.diagnostic.pack(fill="both", expand=True)
        self.button(info, "Открыть папку настроек и журнала", lambda: os.startfile(DATA)).pack(pady=12)
        self.label(self.root, "После запуска окно уйдёт в трей через 8 секунд · Двойной щелчок по значку возвращает окно", 9, MUTED).pack(pady=(0, 14))

    def build_settings(self, frame):
        self.vars = {}
        self.label(frame, "Ваш статус — ваши настройки", 18, bold=True).pack(anchor="w", padx=24, pady=(20, 14))
        fields = [("enabled", "Передавать текущий трек в Discord"),
                  ("show_album", "Показывать название альбома при наведении на обложку"),
                  ("online_covers", "Искать точную обложку и ссылку в публичном каталоге Яндекса"),
                  ("hide_paused", "Скрывать активность на паузе"),
                  ("auto_background", "Автоматически уходить в фон через 8 секунд после запуска"),
                  ("close_to_tray", "Сворачивать в трей при закрытии окна")]
        for key, text in fields:
            var = self.vars[key] = tk.BooleanVar(value=self.config[key])
            tk.Checkbutton(frame, text=text, variable=var, bg=PANEL, fg=FG, selectcolor=BG,
                           activebackground=PANEL, activeforeground=FG, anchor="w").pack(fill="x", padx=22, pady=5)
        self.startup = tk.BooleanVar(value=autostart_enabled())
        tk.Checkbutton(frame, text="Запускать вместе с Windows", variable=self.startup, bg=PANEL, fg=FG,
                       selectcolor=BG, activebackground=PANEL, activeforeground=FG).pack(anchor="w", padx=22, pady=5)
        self.label(frame, "Application ID Discord", 11, bold=True).pack(anchor="w", padx=24, pady=(17, 5))
        self.client_id = tk.StringVar(value=self.config["client_id"])
        tk.Entry(frame, textvariable=self.client_id, bg=BG, fg=FG, insertbackground=FG, relief="flat", width=32).pack(anchor="w", padx=24, ipady=7)
        self.label(frame, "Готовый общий ID показывает «Слушает Яндекс Музыку». Можно указать ID своего приложения.\nЭто публичный номер приложения, не токен. Пароли не нужны.", 9, MUTED, justify="left", wraplength=730).pack(anchor="w", padx=24, pady=6)
        self.label(frame, "Источник (пусто — современное приложение Яндекс Музыки)", 10).pack(anchor="w", padx=24, pady=(10, 4))
        self.source = tk.StringVar(value=self.config["source"])
        tk.Entry(frame, textvariable=self.source, bg=BG, fg=FG, insertbackground=FG, relief="flat").pack(fill="x", padx=24, ipady=7)
        self.button(frame, "Сохранить настройки", self.save_settings, True).pack(anchor="w", padx=24, pady=16)

    def save_settings(self):
        client = self.client_id.get().strip()
        if not client.isdecimal() or not 17 <= len(client) <= 20:
            messagebox.showerror(TITLE, "Application ID должен состоять из 17–20 цифр.")
            return
        config = {**self.config, **{k: v.get() for k, v in self.vars.items()}, "client_id": client, "source": self.source.get().strip()}
        try:
            set_autostart(self.startup.get())
            save_json(DATA / "settings.json", config)
        except OSError as exc:
            messagebox.showerror(TITLE, f"Не удалось сохранить настройки: {exc}")
            return
        self.config = config
        self.engine.commands.put(("config", self.config))
        messagebox.showinfo(TITLE, "Настройки сохранены и применены.")

    def toggle(self):
        self.config["enabled"] = not self.config["enabled"]
        self.vars["enabled"].set(self.config["enabled"])
        save_json(DATA / "settings.json", self.config)
        self.engine.commands.put(("config", self.config))

    def open_player(self):
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for path in (local / "Programs/YandexMusic/Яндекс Музыка.exe", local / "Programs/YandexMusic/Yandex Music.exe"):
            if path.exists():
                subprocess.Popen([str(path)], creationflags=0x08000000)
                return
        try:
            os.startfile("yandexmusic://")
        except OSError:
            webbrowser.open("https://music.yandex.ru/download/")

    def open_track(self):
        url = self.state.get("extra", {}).get("url")
        if url:
            webbrowser.open(url)
        else:
            messagebox.showinfo(TITLE, "Точная ссылка на этот трек пока не найдена.")

    def tick(self):
        if self.closed:
            return
        while not self.ui_actions.empty():
            action = self.ui_actions.get_nowait()
            if action == "show":
                self.show()
            elif action == "toggle":
                self.toggle()
            elif action == "exit":
                self.exit()
                return
        event_path = DATA / "show.request"
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
        state = self.state
        t = Track(**state["track"]) if state.get("track") else None
        self.toggle_btn.configure(text="Скрыть статус" if self.config["enabled"] else "Показывать статус")
        if t:
            self.track_title.configure(text=t.title)
            self.artist.configure(text=t.artist or "Исполнитель не передан")
            self.album.configure(text=t.album or state.get("extra", {}).get("album") or "Альбом не передан")
            pos, duration = t.at(), t.duration or state.get("extra", {}).get("duration")
            self.position.configure(text=f"{clock(pos)} / {clock(duration)}")
            remaining = max(0, duration-pos) if duration and pos is not None else None
            self.duration.configure(text=f"Осталось {clock(remaining)}")
            self.progress["value"] = pos / duration * 100 if pos is not None and duration else 0
            self.quality.configure(text=t.quality + (". Точная секунда недоступна в этой версии плеера." if pos is None else ". Синхронизация каждые 0,5 с; изменения в Discord отправляются не чаще 3 с."))
            self.badge.configure(text={"playing": "●  СЕЙЧАС ИГРАЕТ", "paused": "Ⅱ  НА ПАУЗЕ", "buffering": "◌  ЗАГРУЗКА", "stopped": "■  ОСТАНОВЛЕНО"}.get(t.status, "ОЖИДАНИЕ"))
        else:
            self.track_title.configure(text="Включите Яндекс Музыку")
            self.artist.configure(text="Ожидание трека в приложении для Windows")
            self.album.configure(text="")
            self.position.configure(text="—:—")
            self.duration.configure(text="—:—")
            self.progress["value"] = 0
            self.badge.configure(text="●  ОЖИДАНИЕ ПЛЕЕРА")
            self.quality.configure(text=state.get("error") or "Когда музыка остановлена или приложение закрыто, активность скрывается.")
        key = (t.key, state.get("thumbnail")) if t else None
        if self.cover_key != key:
            self.cover_key = key
            try:
                data = state.get("thumbnail")
                cover = Image.open(io.BytesIO(data)).convert("RGB") if data else icon_image()
                self.cover_photo = ImageTk.PhotoImage(cover.resize((152,152), Image.Resampling.LANCZOS))
                self.cover.configure(image=self.cover_photo)
            except Exception:
                self.cover.configure(image=self.placeholder)
        self.connection.configure(text=state.get("discord", "Подключаемся к Discord…"), fg="#84dfb3" if state.get("connected") else ACCENT)
        ack = state.get("ack", 0)
        self.sync.configure(text=(f"Последнее подтверждение: {time.strftime('%H:%M:%S', time.localtime(ack))}. " if ack else "") + "В Discord должна быть включена демонстрация активности.")
        lines = ["СОСТОЯНИЕ ПОДКЛЮЧЕНИЯ", state.get("discord", "Запуск…"), "", "ИСТОЧНИК", t.source if t else "Не выбран", "", "ДОСТУПНЫЕ МЕДИАСЕССИИ", *state.get("sessions", []), "", "ТОЧНОСТЬ", t.quality if t else "Ожидание", "", "ОБЛОЖКА И ССЫЛКА", state.get("extra", {}).get("method", "Однозначное совпадение не найдено; данные не подменяются."), "", "ОБМЕН С DISCORD", "Всегда Listening: при воспроизведении штатная полоса; на паузе точная позиция в строке статуса.", "Изменения: минимум 3 с между отправками; контрольное обновление: 15 с.", "Подтверждение IPC означает принятие данных клиентом Discord, а не проверку видимости у друзей.", "", "ОГРАНИЧЕНИЯ", "Старое приложение Microsoft Store 4.x может не передавать время. В этом случае показывается —:—.", "Современный плеер должен публиковать системную шкалу времени. При нестандартной скорости бегущий таймер Discord скрывается.", "Название сервиса зависит от Application ID. Кнопка своего статуса может быть видна только другим пользователям.", "", "ДАННЫЕ", str(DATA), "Хранятся настройки, только текущий статус и ограниченный журнал технических ошибок.", "Пароли, токены и история прослушивания не собираются.", state.get("error", "")]
        text = "\n".join(lines)
        if getattr(self, "last_diagnostic", None) != text:
            self.diagnostic.configure(state="normal")
            self.diagnostic.delete("1.0", "end")
            self.diagnostic.insert("1.0", text)
            self.diagnostic.configure(state="disabled")
            self.last_diagnostic = text
        self.root.after(250, self.tick)
        if time.monotonic() - getattr(self, "ui_saved_at", 0) > 2:
            try:
                save_json(DATA / "ui.json", {"running": True, "window": self.root.state(),
                    "tray_visible": bool(self.tray.visible), "auto_background": self.config["auto_background"],
                    "window_size": [self.root.winfo_width(), self.root.winfo_height()],
                    "updated": time.time()})
            except OSError:
                pass
            self.ui_saved_at = time.monotonic()

    def show(self):
        self.auto_hide_pending = False
        self.root.deiconify()
        self.root.lift()

    def auto_hide(self):
        if self.closed or not self.auto_hide_pending or not self.config["auto_background"]:
            return
        # Leave settings/diagnostics visible while the user is using them.
        if self.notebook.index("current") != 0 or not self.tray.visible:
            self.root.after(1000, self.auto_hide)
            return
        self.auto_hide_pending = False
        self.hide()

    def hide(self):
        self.root.withdraw()

    def on_close(self):
        self.hide() if self.config["close_to_tray"] else self.exit()

    def exit(self):
        if self.closed:
            return
        self.closed = True
        self.engine.stop.set()
        self.root.withdraw()
        self.tray.stop()
        self.engine.thread.join(timeout=7)
        try:
            save_json(DATA / "ui.json", {"running": False, "tray_visible": False, "updated": time.time()})
        except OSError:
            pass
        self.root.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
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
