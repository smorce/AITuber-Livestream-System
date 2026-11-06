$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:UV_LINK_MODE = 'copy'
Push-Location $PSScriptRoot
try {
    uv run --link-mode=copy server.py
} finally {
    Pop-Location
}
