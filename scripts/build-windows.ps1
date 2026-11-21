$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Join-Path $PSScriptRoot '..')
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
python -m pip install -r requirements-build.txt
python -m playwright install chromium
$env:THEODORO_BROWSER_TEST = "1"
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean --windowed --name Theodoro `
    --add-data "theodoro/assets:theodoro/assets" `
    --hidden-import keyring.backends.Windows desktop.py
