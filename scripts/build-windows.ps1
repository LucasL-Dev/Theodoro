$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Join-Path $PSScriptRoot '..')
$staging = New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) (
    'Theodoro-' + [Guid]::NewGuid().ToString('N')
))
$browserCache = Join-Path $staging.FullName 'browsers'
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = $browserCache
    Remove-Item Env:THEODORO_CHROMIUM -ErrorAction SilentlyContinue
    python -m pip install -r requirements-build.txt
    python -m playwright install --no-shell chromium
    $env:THEODORO_BROWSER_TEST = '1'
    python -m unittest discover -s tests -v

    python -m PyInstaller --noconfirm --clean --windowed --name Theodoro `
        --add-data "theodoro/assets:theodoro/assets" `
        --hidden-import keyring.backends.Windows desktop.py

    $distribution = (Resolve-Path 'dist/Theodoro').Path
    $bundledBrowsers = Join-Path $distribution '_internal/browsers'
    Copy-Item -LiteralPath $browserCache -Destination $bundledBrowsers -Recurse
    if (-not (Get-ChildItem -LiteralPath $bundledBrowsers -Filter 'chrome.exe' -File -Recurse)) {
        throw 'Theodoro.exe foi compilado, mas chrome.exe está ausente de _internal/browsers.'
    }

    # Test the final layout with no build-time browser cache available.
    Remove-Item -LiteralPath $browserCache -Recurse -Force
    Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH
    $reportPath = Join-Path $staging.FullName 'smoke-report.json'
    $process = Start-Process -FilePath (Join-Path $distribution 'Theodoro.exe') `
        -WorkingDirectory $staging.FullName `
        -ArgumentList '--smoke-test', ('"{0}"' -f $reportPath) -PassThru
    if (-not $process.WaitForExit(60000)) {
        $process.Kill($true)
        throw 'Theodoro.exe não terminou o teste do Chromium em 60 segundos.'
    }
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw "Theodoro.exe não produziu o relatório do teste (saída $($process.ExitCode))."
    }
    $report = Get-Content -LiteralPath $reportPath -Encoding utf8 -Raw
    Write-Host $report
    if ($process.ExitCode -ne 0 -or ($report | ConvertFrom-Json).status -ne 'passed') {
        throw 'O Chromium não iniciou com o pacote final do Theodoro.'
    }
}
finally {
    Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $staging.FullName -Recurse -Force
}
