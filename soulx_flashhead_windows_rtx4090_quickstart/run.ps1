# Generate a portrait talking-head MP4 from a local image + Japanese speech.
param(
    [string]$Audio = 'japanese.wav',
    [string]$Portrait = 'avatar.jpg',
    [ValidateRange(32, 2048)][int]$Size = 512,
    [ValidateRange(1, 100)][int]$Steps = 4,
    [uint32]$Seed = 42
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$repo = Join-Path $root 'audio.cpp'
$runtime = Join-Path $root 'runtime'
function AbsoluteFile([string]$item) {
    if (-not [System.IO.Path]::IsPathRooted($item)) { $item = Join-Path $root $item }
    if (-not (Test-Path -LiteralPath $item -PathType Leaf)) { throw "File does not exist: $item" }
    return (Resolve-Path -LiteralPath $item).Path
}
$audioFile = AbsoluteFile $Audio
$portraitFile = AbsoluteFile $Portrait
$model = AbsoluteFile (Join-Path $repo 'models\SoulX-FlashHead-GGUF\SoulX-FlashHead-Lite-Q8_0.gguf')
$cliInfo = Get-ChildItem -Path $runtime -Filter 'audiocpp_cli.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $cliInfo) { throw 'audiocpp_cli.exe not found. Run setup.ps1 first.' }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw 'ffmpeg is missing. Run: winget install -e --id Gyan.FFmpeg' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is missing.' }
# Both the exe and the separately released CUDA runtime may live in nested dirs.
$runtimeDirs = @(Get-ChildItem -Path $runtime -Directory -Recurse | ForEach-Object FullName) + @($runtime, $cliInfo.DirectoryName)
$env:PATH = (($runtimeDirs | Select-Object -Unique) -join ';') + ';' + $env:PATH
$out = Join-Path $root 'output'
$artifacts = Join-Path $out 'flashhead'
New-Item -ItemType Directory -Force -Path $out | Out-Null
if (Test-Path $artifacts) { Remove-Item -Recurse -Force $artifacts }
New-Item -ItemType Directory -Force -Path $artifacts | Out-Null
$normalized = Join-Path $out 'speech_16k_mono.wav'
$normalizedPortrait = Join-Path $out 'portrait.png'
$video = Join-Path $out 'character_talking.mp4'
Write-Host '[1/3] Converting input speech to mono 16 kHz WAV...' -ForegroundColor Cyan
& ffmpeg -hide_banner -loglevel error -y -i $audioFile -vn -ac 1 -ar 16000 -c:a pcm_s16le $normalized
if ($LASTEXITCODE -ne 0) { throw 'ffmpeg audio conversion failed' }
& ffmpeg -hide_banner -loglevel error -y -i $portraitFile -frames:v 1 $normalizedPortrait
if ($LASTEXITCODE -ne 0) { throw 'ffmpeg portrait conversion failed' }
Write-Host '[2/3] Generating SoulX-FlashHead video artifacts...' -ForegroundColor Cyan
Push-Location $repo
try {
    & $cliInfo.FullName --family soulx_flashhead --task gen --model $model --backend cuda --threads 8 --audio $normalized --request-option "reference_image_file=$normalizedPortrait" --request-option "height=$Size" --request-option "width=$Size" --request-option "num_inference_steps=$Steps" --request-option "seed=$Seed" --out-dir $artifacts --log --log-file (Join-Path $out 'flashhead.log')
    if ($LASTEXITCODE -ne 0) { throw "SoulX CLI failed. See $(Join-Path $out 'flashhead.log')" }
} finally { Pop-Location }
Write-Host '[3/3] Encoding MP4 with original speech...' -ForegroundColor Cyan
& uv run --python 3.11 (Join-Path $repo 'tools\models\soulx_flashhead\render_video.py') --input $artifacts --audio $normalized --output $video
if ($LASTEXITCODE -ne 0) { throw 'MP4 rendering failed. Inspect output/flashhead and ffmpeg.' }
Write-Host ''
Write-Host "Finished: $video" -ForegroundColor Green
