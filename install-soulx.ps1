# 公式配布物のチェックサムを検証してローカルに導入する。
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$kit = Join-Path $PSScriptRoot 'soulx_flashhead_windows_rtx4090_quickstart'
$repo = Join-Path $kit 'audio.cpp'
$runtime = Join-Path $kit 'runtime'
$downloads = Join-Path $kit 'downloads'
New-Item -ItemType Directory -Force -Path $runtime,$downloads | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $repo 'tools/model_manager_v2.py'))) {
    & git clone --depth 1 --branch v0.9.4 https://github.com/0xShug0/audio.cpp.git $repo
    if ($LASTEXITCODE -ne 0) { throw 'SoulX source download failed' }
}
$assets = @{
    'audio-v0.9.4-bin-windows-x64-cuda12.4.zip' = 'E85D829E121A424A960D9AD293536B7ADA74EA845B1C12FCF2991EC09A224D1E'
    'audio-v0.9.4-cudart-windows-x64-cuda12.4.zip' = 'EFB58667B95BCB32E89DDF87811664E6FFDCED3FE7015DDCC077599ED5F44BB2'
}
foreach ($asset in $assets.GetEnumerator()) {
    $zip = Join-Path $downloads $asset.Name
    if (-not (Test-Path -LiteralPath $zip)) {
        & curl.exe -L --fail --retry 2 --output $zip "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.4/$($asset.Name)"
        if ($LASTEXITCODE -ne 0) { throw 'SoulX runtime download failed' }
    }
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $asset.Value) { throw "Runtime checksum mismatch: $zip" }
    Expand-Archive -LiteralPath $zip -DestinationPath $runtime -Force
}
$modelDir = Join-Path $repo 'models/SoulX-FlashHead-GGUF'
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
$model = Join-Path $modelDir 'SoulX-FlashHead-Lite-Q8_0.gguf'
$expected = '29F186F666A4B1EE8AF257A2163D521545D94C600C46D97998C57D6FEFC95751'
if (-not (Test-Path -LiteralPath $model)) {
    $partial = "$model.partial"
    & curl.exe -L --fail --retry 2 --output $partial 'https://huggingface.co/audio-cpp/SoulX-FlashHead-GGUF/resolve/cc83157045008de647a4ba11ca5ed19e66caa575/SoulX-FlashHead-Lite-Q8_0.gguf?download=true'
    if ($LASTEXITCODE -ne 0) { throw 'SoulX model download failed' }
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $expected) { throw 'Model checksum mismatch' }
    Move-Item -LiteralPath $partial -Destination $model
}
if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne $expected) { throw 'Installed model checksum mismatch' }
Write-Host 'SoulX Lite Q8 CUDA 12.4 installation verified.'
