$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 required' }
}
& .venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name YandexMusicPresence --icon (Join-Path $PSScriptRoot 'assets\app.ico') --add-data ((Join-Path $PSScriptRoot 'assets\app.ico') + ';assets') --collect-all winrt --collect-all pystray --collect-all customtkinter --distpath build\dist --workpath build\temp --specpath build src\app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Write-Host 'Ready: build\dist\YandexMusicPresence.exe'
