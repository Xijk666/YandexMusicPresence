@echo off
chcp 65001 >nul
if exist "%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe" (
  start "" "%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe"
) else (
  start "" "https://music.yandex.ru/download/"
)
