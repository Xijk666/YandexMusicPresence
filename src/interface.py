"""Compact player surface. Rendering is independent from the playback engine."""
import ctypes
import io
import math
import time
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps
from core import Track, clock

BG = '#191a1d'
SURFACE = '#24262a'
HOVER = '#303237'
FG = '#f3f1ec'
MUTED = '#a0a1a6'
ACCENT = '#f0c65b'
GREEN = '#92c9a7'
FONT = 'Segoe UI'


def icon_image():
    image = Image.new('RGBA', (256, 256), BG)
    draw = ImageDraw.Draw(image)
    draw.arc((51, 42, 205, 196), 180, 360, fill=ACCENT, width=24)
    draw.rounded_rectangle((40, 113, 88, 210), 21, fill=ACCENT)
    draw.rounded_rectangle((168, 113, 216, 210), 21, fill=ACCENT)
    draw.ellipse((190, 187, 244, 241), fill=BG)
    draw.ellipse((198, 195, 236, 233), fill=GREEN)
    return image


def symbol(name, color=FG, size=22):
    scale = 4
    image = Image.new('RGBA', (size*scale, size*scale))
    d = ImageDraw.Draw(image)
    def points(items):
        return [(x*size*scale/24, y*size*scale/24) for x, y in items]
    def line(items, width=2):
        d.line(points(items), fill=color, width=round(width*size*scale/24), joint='curve')
    if name == 'play':
        d.polygon(points([(8, 5), (19, 12), (8, 19)]), fill=color)
    elif name == 'pause':
        for x in (7, 14):
            d.rounded_rectangle((x*size*scale/24, 5*size*scale/24, (x+3)*size*scale/24, 19*size*scale/24), scale, fill=color)
    elif name in ('previous', 'next'):
        p = [(16, 6), (7, 12), (16, 18)] if name == 'previous' else [(8, 6), (17, 12), (8, 18)]
        d.polygon(points(p), fill=color)
        x = 5 if name == 'previous' else 19
        line([(x, 6), (x, 18)])
    elif name == 'back':
        line([(14, 6), (8, 12), (14, 18)])
    elif name == 'settings':
        factor = size*scale/24
        d.ellipse((7*factor, 7*factor, 17*factor, 17*factor), outline=color, width=round(2*factor))
        for n in range(8):
            a = n*math.pi/4
            line([(12+6*math.cos(a), 12+6*math.sin(a)), (12+9*math.cos(a), 12+9*math.sin(a))])
        d.ellipse((10*factor, 10*factor, 14*factor, 14*factor), fill=color)
    elif name == 'tray':
        line([(5, 15), (5, 19), (19, 19), (19, 15)])
        line([(12, 4), (12, 14)])
        line([(8, 10), (12, 14), (16, 10)])
    return ctk.CTkImage(image, size=(size, size))


def dark_titlebar(root):
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        enabled = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), 4)
        rgb = int(BG[5:7]+BG[3:5]+BG[1:3], 16)
        value = ctypes.c_int(rgb)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(value), 4)
    except (AttributeError, OSError):
        pass


def display_text(value, measure, width, lines=2):
    remaining = ' '.join(str(value or '').split())
    result = []
    for index in range(lines):
        if measure(remaining) <= width:
            result.append(remaining)
            break
        low, high = 0, len(remaining)
        suffix = '…' if index == lines-1 else ''
        while low < high:
            middle = (low+high+1)//2
            if measure(remaining[:middle]+suffix) <= width:
                low = middle
            else:
                high = middle-1
        split = remaining.rfind(' ', 0, low+1)
        split = split if split > low//2 else max(1, low)
        result.append(remaining[:split].rstrip()+suffix)
        remaining = remaining[split:].lstrip()
    return '\n'.join(result)


class IconButton(ctk.CTkButton):
    def _create_grid(self):
        super()._create_grid()
        # Image-only controls have no text that needs a rounded end-cap inset.
        self.grid_columnconfigure((0, 4), minsize=0)

    def focus_set(self):
        return tk.Frame.focus_set(self)


class PlayerView:
    def __init__(self, root, app):
        self.root, self.app = root, app
        self.page = 'player'
        self.last_cover = object()
        self.last_diagnostic = ''
        self.buttons = []
        self.shell = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
        self.shell.pack(fill='both', expand=True)
        self.header = ctk.CTkFrame(self.shell, fg_color='transparent', height=44)
        self.header.pack(fill='x', padx=24, pady=(10, 6))
        self.back = self.icon_button(self.header, 'back', lambda: self.navigate('settings' if self.page == 'diagnostics' else 'player'))
        self.wordmark = self.label(self.header, 'Я · Presence', 20, weight='bold')
        self.wordmark.pack(side='left')
        self.settings = self.icon_button(self.header, 'settings', lambda: self.navigate('settings'))
        self.settings.pack(side='right')
        self.hide_button = self.icon_button(self.header, 'tray', app.hide)
        self.hide_button.pack(side='right', padx=(0, 6))
        self.body = ctk.CTkFrame(self.shell, fg_color='transparent', corner_radius=0)
        self.body.pack(fill='both', expand=True)
        self.pages = {}
        for name in ('player', 'settings', 'diagnostics'):
            self.pages[name] = ctk.CTkFrame(self.body, fg_color='transparent', corner_radius=0)
        self.build_player(self.pages['player'])
        self.build_settings(self.pages['settings'])
        self.build_diagnostics(self.pages['diagnostics'])
        self.navigate('player')

    def label(self, parent, text, size=13, color=FG, weight='normal', **kwargs):
        return ctk.CTkLabel(parent, text=text, height=size+6, font=(FONT, size, weight), text_color=color, **kwargs)

    def button(self, parent, text, command, primary=False, **kwargs):
        options = dict(font=(FONT, 13), fg_color=ACCENT if primary else SURFACE,
            hover_color='#ffdc80' if primary else HOVER, text_color=BG if primary else FG,
            corner_radius=10, height=38, border_width=0)
        widget = IconButton if kwargs.pop('icon_only', False) else ctk.CTkButton
        button = widget(parent, text=text, command=command, **{**options, **kwargs})
        self.keyboard_button(button)
        return button

    def keyboard_button(self, button):
        tk.Frame.configure(button, takefocus=1)
        tk.Frame.bind(button, '<FocusIn>', lambda _: button.configure(border_width=2, border_color=ACCENT))
        tk.Frame.bind(button, '<FocusOut>', lambda _: button.configure(border_width=0))
        tk.Frame.bind(button, '<Return>', lambda _: button.invoke())
        tk.Frame.bind(button, '<space>', lambda _: button.invoke())
        self.buttons.append(button)

    def icon_button(self, parent, name, command, primary=False, size=36):
        return self.button(parent, '', command, primary, icon_only=True, width=size, height=size,
                           image=symbol(name, BG if primary else FG, 25 if primary else 19), corner_radius=size//2)

    def navigate(self, page):
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[page].pack(fill='both', expand=True)
        self.page = page
        self.back.pack_forget()
        if page == 'player':
            self.wordmark.configure(text='Я · Presence')
            self.settings.pack(side='right')
            self.hide_button.pack(side='right', padx=(0, 6))
        else:
            self.back.pack(side='left', before=self.wordmark, padx=(0, 8))
            self.wordmark.configure(text='Настройки' if page == 'settings' else 'Диагностика')
            self.settings.pack_forget()
            self.hide_button.pack_forget()

    def build_player(self, frame):
        status = ctk.CTkFrame(frame, fg_color='transparent')
        status.pack(fill='x', padx=28, pady=(0, 10))
        self.status = self.label(status, 'Подключаемся к Discord', 12, MUTED)
        self.status.pack(side='left')
        self.sharing = ctk.CTkSwitch(status, text='', width=36, switch_width=34, switch_height=18,
            progress_color=ACCENT, button_color=FG, fg_color=HOVER, command=self.app.toggle)
        self.sharing.pack(side='right')
        self.art_image = ctk.CTkImage(icon_image(), size=(248, 248))
        self.cover = ctk.CTkLabel(frame, text='', image=self.art_image, width=248, height=248)
        self.cover.pack(pady=(0, 12))
        meta = ctk.CTkFrame(frame, fg_color='transparent')
        meta.pack(fill='x', padx=28)
        self.track_title = self.label(meta, 'Включите музыку', 23, weight='bold', anchor='w', justify='left', wraplength=390)
        self.title_font = ctk.CTkFont(family=FONT, size=23, weight='bold')
        self.artist_font = ctk.CTkFont(family=FONT, size=14)
        self.album_font = ctk.CTkFont(family=FONT, size=11)
        self.track_title.pack(fill='x')
        self.artist = self.label(meta, 'Трек появится здесь автоматически', 14, MUTED, anchor='w', justify='left', wraplength=390)
        self.artist.pack(fill='x', pady=(2, 0))
        self.album = self.label(meta, '', 11, MUTED, anchor='w', wraplength=390)
        self.album.pack(fill='x', pady=(4, 0))
        self.progress = ctk.CTkProgressBar(frame, height=4, corner_radius=2, fg_color=HOVER, progress_color=ACCENT)
        self.progress.pack(fill='x', padx=28, pady=(10, 3))
        self.progress.set(0)
        timing = ctk.CTkFrame(frame, fg_color='transparent')
        timing.pack(fill='x', padx=28)
        self.position = self.label(timing, '—:— / —:—', 12, MUTED)
        self.position.pack(side='left')
        self.remaining = self.label(timing, '', 12, MUTED)
        self.remaining.pack(side='right')
        controls = ctk.CTkFrame(frame, fg_color='transparent')
        controls.pack(pady=(10, 10))
        self.icon_button(controls, 'previous', lambda: self.app.control('previous'), size=40).pack(side='left', padx=18)
        self.play = self.icon_button(controls, 'play', lambda: self.app.control('toggle'), primary=True, size=56)
        self.play.pack(side='left')
        self.icon_button(controls, 'next', lambda: self.app.control('next'), size=40).pack(side='left', padx=18)
        self.open_link = self.button(frame, 'Открыть Яндекс Музыку', self.app.open_player, width=230)
        self.open_link.pack(pady=(0, 4))
        self.hint = self.label(frame, 'Крестик свернёт приложение в трей', 11, MUTED, wraplength=390)
        self.hint.pack(side='bottom', pady=(4, 8))

    def build_settings(self, frame):
        scroll = ctk.CTkScrollableFrame(frame, fg_color='transparent', corner_radius=0, scrollbar_button_color=HOVER)
        scroll.pack(fill='both', expand=True, padx=15)
        self.vars = {}
        rows = [('enabled', 'Показывать музыку в Discord', 'Название, исполнитель и обложка'),
                ('show_album', 'Название альбома', 'Показывать при наведении на обложку'),
                ('online_covers', 'Обложки из каталога', 'Публичный поиск по названию и исполнителю'),
                ('hide_paused', 'Скрывать музыку на паузе', 'По умолчанию карточка остаётся видимой'),
                ('auto_background', 'Уходить в фон после запуска', 'Через 8 секунд, если открыта музыка'),
                ('close_to_tray', 'Сворачивать при закрытии', 'Приложение продолжит работать в трее')]
        for key, title, detail in rows:
            variable = self.vars[key] = tk.BooleanVar(value=self.app.config[key])
            self.setting_row(scroll, title, detail, variable)
        self.startup = tk.BooleanVar(value=self.app.autostart())
        self.setting_row(scroll, 'Запускать вместе с Windows', 'Сразу в фоне, без открытого окна', self.startup)
        self.label(scroll, 'Подключение', 15, weight='bold', anchor='w').pack(fill='x', padx=10, pady=(24, 4))
        self.label(scroll, 'Общий Application ID уже настроен.\nМеняйте его только для своего приложения Discord.', 12, MUTED, justify='left', anchor='w').pack(fill='x', padx=10, pady=(0, 10))
        self.client_id = tk.StringVar(value=self.app.config['client_id'])
        self.entry(scroll, self.client_id, 'Application ID')
        self.label(scroll, 'Источник плеера', 12, MUTED, anchor='w').pack(fill='x', padx=10, pady=(12, 4))
        self.source = tk.StringVar(value=self.app.config['source'])
        self.entry(scroll, self.source, 'Автоматически')
        self.button(scroll, 'Диагностика подключения', lambda: self.navigate('diagnostics')).pack(fill='x', padx=10, pady=(16, 12))
        footer = ctk.CTkFrame(frame, fg_color=BG)
        footer.pack(fill='x', padx=26, pady=(10, 16))
        self.saved = self.label(footer, '', 12, GREEN)
        self.saved.pack(side='left')
        self.button(footer, 'Сохранить', self.app.save_settings, primary=True, width=126).pack(side='right')

    def setting_row(self, frame, title, detail, variable):
        row = ctk.CTkFrame(frame, fg_color='transparent')
        row.pack(fill='x', padx=10, pady=9)
        text = ctk.CTkFrame(row, fg_color='transparent')
        text.pack(side='left', fill='x', expand=True)
        self.label(text, title, 13, anchor='w', wraplength=320, justify='left').pack(fill='x')
        self.label(text, detail, 11, MUTED, anchor='w', wraplength=320, justify='left').pack(fill='x', pady=(2, 0))
        ctk.CTkSwitch(row, text='', variable=variable, width=36, switch_width=34, switch_height=18,
            progress_color=ACCENT, button_color=FG, fg_color=HOVER).pack(side='right', padx=(10, 0))

    def entry(self, frame, variable, placeholder):
        ctk.CTkEntry(frame, textvariable=variable, placeholder_text=placeholder, fg_color=SURFACE,
            border_width=0, height=36, corner_radius=8, text_color=FG, font=(FONT, 12)).pack(fill='x', padx=10)

    def build_diagnostics(self, frame):
        self.diagnostic = ctk.CTkTextbox(frame, fg_color=SURFACE, text_color=FG,
            corner_radius=12, wrap='word', font=(FONT, 12))
        self.diagnostic.pack(fill='both', expand=True, padx=24, pady=(0, 12))
        self.button(frame, 'Открыть папку данных', self.app.open_data).pack(pady=(0, 18))

    def render(self, state, config):
        track = Track(**state['track']) if state.get('track') else None
        enabled = config['enabled']
        self.sharing.select() if enabled else self.sharing.deselect()
        if not enabled:
            status, color = 'Статус скрыт', MUTED
        elif not state.get('connected'):
            status, color = 'Ожидаем Discord', MUTED
        elif not track:
            status, color = 'Discord подключён', GREEN
        elif track.status == 'paused':
            status, color = ('На паузе · скрыто' if config['hide_paused'] else 'На паузе · в Discord'), MUTED
        else:
            status, color = 'Сейчас играет · в Discord', GREEN
        self.status.configure(text=status, text_color=color)
        if track:
            self.track_title.configure(text=display_text(track.title, self.title_font.measure, 360))
            self.artist.configure(text=display_text(track.artist or 'Исполнитель не передан', self.artist_font.measure, 360))
            album = track.album or state.get('extra', {}).get('album', '')
            self.album.configure(text=display_text(album if album.casefold() != track.title.casefold() else '', self.album_font.measure, 360, 1))
            pos, duration = track.at(), track.duration or state.get('extra', {}).get('duration')
            self.position.configure(text=f'{clock(pos)} / {clock(duration)}')
            left = max(0, duration-pos) if duration and pos is not None else None
            self.remaining.configure(text=f'Осталось {clock(left)}' if left is not None else '')
            self.progress.set(pos/duration if pos is not None and duration else 0)
            kind = 'pause' if track.status == 'playing' else 'play'
            self.hint.configure(text='Плеер не передаёт позицию трека' if pos is None else
                ('Крестик свернёт приложение в трей' if config['close_to_tray'] else 'Закрытие окна завершит приложение'))
        else:
            self.track_title.configure(text='Включите музыку')
            self.artist.configure(text='Откройте Яндекс Музыку и выберите трек')
            self.album.configure(text='')
            self.position.configure(text='—:— / —:—')
            self.remaining.configure(text='')
            self.progress.set(0)
            kind = 'play'
            self.hint.configure(text='Приложение ждёт музыку в фоне')
        if kind != getattr(self, 'play_kind', None):
            self.play.configure(image=symbol(kind, BG, 25))
            self.play_kind = kind
        key = (track.key, state.get('thumbnail')) if track else None
        if key != self.last_cover:
            self.last_cover = key
            try:
                data = state.get('thumbnail')
                art = Image.open(io.BytesIO(data)).convert('RGB') if data else icon_image().convert('RGB')
                art = ImageOps.fit(art, (696, 696), method=Image.Resampling.LANCZOS)
                mask = Image.new('L', art.size)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, 695, 695), radius=30, fill=255)
                rounded = Image.new('RGB', art.size, BG)
                rounded.paste(art, mask=mask)
                self.art_image.configure(light_image=rounded, dark_image=rounded)
            except (OSError, ValueError):
                self.art_image.configure(light_image=icon_image(), dark_image=icon_image())
        has_url = bool(state.get('extra', {}).get('url'))
        self.open_link.configure(text='Открыть трек в Музыке' if has_url else 'Открыть Яндекс Музыку',
                                 command=self.app.open_track if has_url else self.app.open_player)
        if self.page == 'diagnostics':
            self.render_diagnostics(state, track)

    def render_diagnostics(self, state, track):
        ack = state.get('ack', 0)
        lines = ['Подключение к Discord', state.get('discord', 'Ожидание'),
            'Подтверждение: ' + (time.strftime('%H:%M:%S', time.localtime(ack)) if ack else 'ещё нет'),
            '', 'Медиасессия', track.source if track else 'Источник не найден',
            track.quality if track else 'Включите трек в приложении Яндекс Музыки',
            '', 'Доступные источники', *state.get('sessions', []), '', 'Обложка',
            state.get('extra', {}).get('method', 'Точное совпадение пока не найдено'),
            '', 'Синхронизация', 'Опрос плеера: 0,5 с. Метаданные: по событию и каждые 2 с.',
            'Discord: не чаще раза в 3 с, контрольное обновление каждые 15 с.',
            'Тип активности — Listening, в том числе на паузе.', '', 'Ограничения',
            'Подтверждение означает приём данных локальным Discord. Видимость у друзей зависит от настроек активности.',
            'Если плеер не передаёт время, позиция не подставляется из каталога.',
            '', state.get('error', '')]
        text = '\n'.join(lines)
        if text != self.last_diagnostic:
            self.diagnostic.configure(state='normal')
            self.diagnostic.delete('1.0', 'end')
            self.diagnostic.insert('1.0', text)
            self.diagnostic.configure(state='disabled')
            self.last_diagnostic = text
