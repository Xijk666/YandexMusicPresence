# Validation / Проверки

## Automated regression suite

The current suite contains **36 tests**. The live [Windows workflow](https://github.com/Xijk666/YandexMusicPresence/actions/workflows/windows.yml) is the source of truth for the latest commit.

| Area | Checks |
| --- | --- |
| Timeline | Position anchors, extrapolation, no double counting, pause/resume, seeks, track changes, end clamping, missing/invalid data, playback rate |
| Discord payload | Listening type, pause text, timestamps, no duplicated playing timer, Unicode length, trusted image URLs, source filtering |
| Metadata | Exact title/version/artist/album/duration, missing album, ambiguous releases, common artwork, album fallback, collaborator order |
| Network | Alternate catalog endpoint, temporary failure followed by success, no request when online lookup is disabled |
| IPC | Fragmented frames, PING/PONG, explicit error handling, remote disconnect |

The IPC tests create isolated local named pipes. They do not change the user's real Discord presence. Catalog tests use mocked responses and do not need a Yandex account or network access.

```powershell
python -m unittest discover -s tests -v
python scripts/check_project.py
```

Run on Windows: IPC code depends on `kernel32` and media-session code uses WinRT. The build workflow installs the pinned dependencies before executing the tests.

## Manual checks

`python scripts/check_ui.py` also creates an isolated preview and checks compact-window bounds with long titles, play/pause and empty states, page navigation and keyboard focus. It runs in the Windows workflow and never starts the Discord engine.

With current Yandex Music and Discord desktop apps open:

1. Start a song and compare title, artist and elapsed/total time.
2. Pause: the card stays Listening, with a fixed position in the pause text.
3. Resume, then seek forward/backward: timestamps should follow the player.
4. Switch songs: metadata and cover should change together; allow for catalog/network delay.
5. Briefly disconnect the network: local metadata should continue; artwork lookup should retry after reconnecting.
6. Close/reopen Discord: the connection should recover automatically.
7. Close the app window: the tray icon should remain; use its Exit command for a full shutdown.

An IPC acknowledgement proves that the local Discord client accepted the payload. It does **not** prove that a friend sees the card; check visibility separately with activity privacy settings enabled.

## Limits of validation

Windows and player versions may expose different SMTC metadata. Automatic tests cannot guarantee future player versions, advertisements, crossfade or every Discord UI variant. No percentage coverage claim is made. CI builds are not code-signed.

---

## По-русски

В проекте **36 тестов**: время и перемотка, пауза/возобновление, формат активности, точное сопоставление треков, обложки и резервный API, обработка ошибок и именованные каналы Discord. Результат последнего коммита показан в GitHub Actions.

Тесты работают в Windows и используют изолированные каналы и подменённые сетевые ответы. Реальный Discord, аккаунт Яндекса и сеть для них не нужны. Проверяйте вручную воспроизведение, паузу, перемотку, смену песни, повторную загрузку обложек после сетевого сбоя, переподключение Discord и уход в трей.

Подтверждение IPC означает принятие данных локальным Discord. Видимость карточки у друга требует отдельной проверки. Процент покрытия кода не заявляется; сборки не имеют цифровой подписи.
