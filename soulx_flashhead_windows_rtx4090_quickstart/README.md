# SoulX-FlashHead 動画生成クイックスタート (audio.cpp v0.9.4)

対象: Windows 10/11 x64 / NVIDIA RTX 4090 (24GB) / PowerShell。**このキットは動画生成のみ**で、リアルタイム会話・音声認識・音声合成は行いません。画像は依頼時に提供されたものを `avatar.jpg` として同梱しています。日本語音声は同梱していません。

## 1. 前提ソフト

- 最新の NVIDIA GPU ドライバー（`nvidia-smi` で確認）
- `git`、`uv`（すでにある場合は再インストール不要）
- `ffmpeg`。ない場合: `winget install -e --id Gyan.FFmpeg`。インストール後にPowerShellを再起動。
- Windows の通常の PowerShell。管理者権限は原則不要。

以下は**このZIPを展開したフォルダー内**で実行してください。

## 2. モデル・CUDA実行環境を導入

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

このスクリプトは audio.cpp v0.9.4 を `audio.cpp/` に取得し、対応する配布版 CUDA 12.4 実行ファイル・CUDAランタイムを `runtime/` に展開します。また、公式モデル管理ツールを使って `SoulX-FlashHead Lite Q8_0` を取得します。ダウンロードサイズが大きいため空き容量を十分に確保してください。

NVIDIAドライバーが新しく CUDA 13.3 を選ぶ場合は `-Cuda 13.3` と指定します（セットアップ時に混在したバージョンを上書きする使い方は推奨しません）。標準は CUDA 12.4 です。

## 3. 音声を用意

**方法A: 既存の日本語音声**（推奨）。3～10秒程度の発話がある WAV、M4A、MP3 を `japanese.wav` などの名前でこのフォルダーに置きます。拡張子が M4A などの場合、`-Audio` で正しいファイル名を指定してください。

**方法B: マイクで6秒録音**（任意）。

```powershell
uv run --python 3.11 --with numpy --with sounddevice python .\record.py
```

録音ファイル `japanese.wav` が生成されます。録音は固定秒数です。変更は `--seconds 10` などを使います。

## 4. 動画生成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Audio .\japanese.wav
```

M4Aや他の画像を指定する場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Audio 'D:\Audio\voice.m4a' -Portrait '.\avatar.jpg'
```

出力: `output/character_talking.mp4`。音声が同期した動画を作ります。内部では音声を16kHzモノラルに、参照画像をPNGに変換→公式audio.cpp CLIでアニメーション生成→公式render_video.pyとFFmpegでMP4化を実行します。

## 5. 推奨と限界

- 最初は512×512、生成4ステップ（標準設定）で試してください。`-Size 512 -Steps 4 -Seed 42`。
- SoulX-FlashHeadは中央を基準に画像を切り出します。添付画像は顔が中央にあるため、そのまま使います。長い髪や服の一部は画面外になりえます。
- アニメ調の画像では、口元・目・髪・輪郭が多少崩れる場合があります。品質は実機で要確認。
- Windows v0.9.4 **配布バイナリにはcuDNN Conv3D最適化が入りません**。このキットは標準経路（ggml）を使用します。RTX 4090で常にリアルタイムに動くことは保証しません。
- モデルは実験的な機能です。失敗した場合は `output/flashhead.log` を確認します。
- 必要なら `setup.ps1` から **ダウンロード処理だけ** を手作業に切り替えられます。配布物: https://github.com/0xShug0/audio.cpp/releases/tag/v0.9.4
- 動画ができない場合は `runtime/` 内に `audiocpp_cli.exe` があるか、NVIDIA ドライバーが対応しているか、`ffmpeg -version` と `uv --version` が動くかを確認してください。

## 公式根拠

- https://github.com/0xShug0/audio.cpp/blob/v0.9.4/docs/models/soulx_flashhead.md
- https://github.com/0xShug0/audio.cpp/blob/v0.9.4/model_specs/soulx_flashhead.json
- https://github.com/0xShug0/audio.cpp/blob/v0.9.4/docs/build/windows.md
- https://github.com/0xShug0/audio.cpp/blob/v0.9.4/tools/models/soulx_flashhead/render_video.py

## 構成

```
soulx_flashhead_quickstart/
  avatar.jpg          ← 添付キャラクター画像（変更なし）
  setup.ps1           ← リポジトリ、実行ファイル、モデルの取得
  run.ps1             ← 画像＋音声→MP4
  record.py           ← 任意のマイク録音
  README.md
  japanese.wav        ← ユーザー側で用意・録音する
  audio.cpp/          ← setup.ps1が取得
  runtime/            ← setup.ps1が取得
  output/             ← run.ps1が生成
```
