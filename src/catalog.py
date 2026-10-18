"""Exact metadata enrichment. A failed or ambiguous match is intentionally empty."""
import json
import os
from pathlib import Path
import sqlite3
import urllib.parse
import urllib.request
from collections import Counter
from core import normalized, cover_url


def resolve_matches(matches):
    if len(matches) == 1:
        return next(iter(matches.values()))
    # Reissues may have different track IDs but the same artwork. It is safe to
    # display that common image, without inventing a canonical track link.
    values = list(matches.values())
    covers = {item.get("cover", "") for item in values}
    if values and len(covers) == 1 and "" not in covers:
        result = dict(cover=covers.pop(), method="Одинаковая обложка у всех точных совпадений; ссылка не выбрана")
        albums = {item.get("album", "") for item in values}
        if len(albums) == 1:
            result["album"] = albums.pop()
        return result
    return {}


def same_artists(expected, names):
    actual = ", ".join(names)
    if normalized(actual) == normalized(expected):
        return True
    # SMTC and the public catalog can order collaborators differently.
    return Counter(normalized(n) for n in names) == Counter(normalized(n) for n in expected.split(","))

def local_match(track):
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages/A025C540.Yandex.Music_vfvw9svesycw6/LocalState"
    matches = {}
    for path in root.glob("musicdb_*.sqlite"):
        try:
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.4) as db:
                # Read only the current title and its public music metadata, never tokens/config/accounts.
                rows = db.execute('SELECT Id,Title,DurationMillis,CoverUri FROM T_Track WHERE Title=?', (track.title,)).fetchall()
                for ident, title, duration, cover in rows:
                    artists = [r[0] for r in db.execute('SELECT a.Name FROM T_Artist a JOIN T_TrackArtist ta ON a.Id=ta.ArtistId WHERE ta.TrackId=? ORDER BY ta.AutoId', (ident,))]
                    if not same_artists(track.artist, artists):
                        continue
                    albums = db.execute('SELECT a.Id,a.Title FROM T_Album a JOIN T_TrackAlbum ta ON a.Id=ta.AlbumId WHERE ta.TrackId=?', (ident,)).fetchall()
                    for aid, album in albums:
                        if track.album and normalized(album) != normalized(track.album):
                            continue
                        if not track.album and not track.duration:
                            continue
                        if track.duration and abs((duration or 0)/1000 - track.duration) > 2:
                            continue
                        tid = str(ident).split(":")[0]
                        if tid.isdecimal() and str(aid).isdecimal():
                            matches[(tid, str(aid))] = dict(cover=cover_url(cover), album=album,
                                duration=(duration or 0)/1000, url=f"https://music.yandex.ru/album/{aid}/track/{tid}",
                                method="Точное совпадение в локальном каталоге")
        except (OSError, sqlite3.Error):
            continue
    return resolve_matches(matches)

def select_exact(track, items):
    matches = {}
    for item in items:
        name = item.get("title", "")
        version = item.get("version", "")
        if version:
            name += " (" + version + ")"
        if normalized(name) != normalized(track.title):
            continue
        if not same_artists(track.artist, [a.get("name", "") for a in item.get("artists", [])]):
            continue
        if track.duration and abs(item.get("durationMs", 0)/1000 - track.duration) > 2:
            continue
        for album in item.get("albums", []):
            if track.album and normalized(album.get("title")) != normalized(track.album):
                continue
            if not track.album and not track.duration:
                continue
            tid, aid = str(item.get("id", "")), str(album.get("id", ""))
            if tid.isdecimal() and aid.isdecimal():
                matches[(tid, aid)] = dict(cover=cover_url(item.get("coverUri")) or cover_url(album.get("coverUri")), album=album.get("title", ""),
                    duration=item.get("durationMs", 0)/1000, url=f"https://music.yandex.ru/album/{aid}/track/{tid}",
                    method="Однозначное совпадение названия, исполнителей, длительности" + (" и альбома" if track.album else "; альбом взят из каталога"))
    return resolve_matches(matches)

def lookup(track, online=True):
    result = local_match(track)
    if result.get("cover") or not online:
        return result
    query = urllib.parse.urlencode({"text": f"{track.artist} {track.title}", "type": "track", "page": 0})
    # Only public catalog search. No Yandex or Discord user token is needed.
    for host in ("api.music.yandex.ru", "api.music.yandex.net"):
        request = urllib.request.Request("https://" + host + "/search?" + query,
                                         headers={"User-Agent": "YandexMusicPresence/1.1"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read(2_000_000))
            found = select_exact(track, data.get("result", {}).get("tracks", {}).get("results", []))
            if found.get("cover"):
                return {**result, **found}
            result = result or found
        except Exception:
            continue
    return result
