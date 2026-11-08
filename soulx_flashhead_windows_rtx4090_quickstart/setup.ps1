# SoulX-FlashHead Lite v0.9.4 / Windows x64 CUDA 12.4
param(
    [ValidateSet('12.4', '13.3')][string]$Cuda = '12.4'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$repo = Join-Path $root 'audio.cpp'
$runtime = Join-Path $root 'runtime'
$cache = Join-Path $root 'downloads'
New-Item -ItemType Directory -Force -Path $runtime, $cache | Out-Null
function Need($program) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) {
        throw "$program is not installed or is not on PATH. See README.md"
    }
}
Need 'git'
Need 'uv'
Need 'ffmpeg'
if (-not (Test-Path (Join-Path $repo 'tools\model_manager_v2.py'))) {
    Write-Host '[1/3] Cloning audio.cpp v0.9.4...' -ForegroundColor Cyan
    & git clone --depth 1 --branch v0.9.4 https://github.com/0xShug0/audio.cpp.git $repo
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }
} else {
    Write-Host '[1/3] Repository already present.' -ForegroundColor Green
}
$base = 'https://github.com/0xShug0/audio.cpp/releases/download/v0.9.4'
$cudaLabel = 'cuda' + $Cuda
$assets = @(
    "audio-v0.9.4-bin-windows-x64-$cudaLabel.zip",
    "audio-v0.9.4-cudart-windows-x64-$cudaLabel.zip"
)
foreach ($asset in $assets) {
    $marker = Join-Path $runtime ('.extracted-' + $asset)
    if (Test-Path $marker) { continue }
    $zip = Join-Path $cache $asset
    if (-not (Test-Path $zip)) {
        Write-Host "[2/3] Downloading $asset" -ForegroundColor Cyan
        Invoke-WebRequest -Uri "$base/$asset" -OutFile $zip
    }
    Write-Host "Extracting $asset" -ForegroundColor Cyan
    Expand-Archive -Path $zip -DestinationPath $runtime -Force
    New-Item -ItemType File -Path $marker -Force | Out-Null
}
$exe = Get-ChildItem -Path $runtime -Filter 'audiocpp_cli.exe' -Recurse -File | Select-Object -First 1
if (-not $exe) { throw "audiocpp_cli.exe not found in $runtime" }
Write-Host '[3/3] Downloading SoulX-FlashHead Lite Q8_0 model...' -ForegroundColor Cyan
Push-Location $repo
try {
    & uv python install 3.11
    if ($LASTEXITCODE -ne 0) { throw 'uv python install failed' }
    & uv run --python 3.11 tools/model_manager_v2.py install soulx_flashhead_lite_q8_0
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
} finally { Pop-Location }
$model = Join-Path $repo 'models\SoulX-FlashHead-GGUF\SoulX-FlashHead-Lite-Q8_0.gguf'
if (-not (Test-Path $model)) { throw "Model not found at $model" }
Write-Host ''
Write-Host 'Setup completed. Record speech or supply an audio file, then run:' -ForegroundColor Green
Write-Host '  powershell -ExecutionPolicy Bypass -File .\run.ps1 -Audio .\japanese.wav'
Write-Host 'To record microphone audio first:'
Write-Host '  uv run --python 3.11 --with numpy --with sounddevice python .\record.py'
