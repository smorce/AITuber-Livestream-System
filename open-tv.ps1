$ErrorActionPreference = 'Stop'

# 通常のChromeと分離した配信用プロファイルで自動再生を許可する。
$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chromePath = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chromePath) { throw 'Google Chrome was not found.' }

try {
    $null = Invoke-RestMethod 'http://127.0.0.1:17863/health' -TimeoutSec 3
} catch {
    throw 'AITuber server is not running. Start server.py or start.ps1 first.'
}

$profilePath = Join-Path $env:LOCALAPPDATA 'AITuber-Livestream-System\Chrome-TV'
$tvFile = [Uri]::EscapeDataString('ブラウン管TV_映像エディター_XYZデバッグ版.html')
$tvUrl = "http://127.0.0.1:17863/$($tvFile)?autoplay=1&v=lipsync-1"
$chromeArguments = @(
    "--user-data-dir=`"$profilePath`"",
    '--autoplay-policy=no-user-gesture-required',
    '--no-first-run',
    '--no-default-browser-check',
    '--new-window',
    $tvUrl
)
Start-Process -FilePath $chromePath -ArgumentList $chromeArguments -WindowStyle Hidden
