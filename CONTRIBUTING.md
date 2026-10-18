# Contributing / Участие в разработке

English and Russian issues and pull requests are welcome.

1. Fork the repository and make a focused branch.
2. Use Windows x64 and Python 3.12. Run `./build.ps1` to install pinned dependencies, execute tests and build the EXE.
3. For pure changes, run `.venv/Scripts/python.exe -m unittest discover -s tests -v`.
4. Run `python scripts/check_project.py` after editing documentation or project files.
5. Keep `README.md` and `README.ru.md` consistent. Describe behavior and limitations without claiming unverified support.
6. Use public catalog data and the documented Windows media session interface. Do not add account-token collection.
7. Include regression tests for changes to timeline calculations, metadata matching or the IPC protocol.

Tests use isolated named pipes and mocked catalog responses. A running Discord client, a Yandex account and network access are not required to run them.

---

Принимаются задачи и pull request на русском и английском.

Используйте Windows x64 и Python 3.12. `./build.ps1` установит зависимости, запустит тесты и соберёт EXE. Обновляйте обе версии README; для изменений времени, сопоставления метаданных и IPC добавляйте проверки, воспроизводящие исправляемую ошибку. Не добавляйте сбор токенов аккаунтов. Автоматические тесты не требуют Discord, аккаунта Яндекса или доступа к сети.
