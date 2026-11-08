"""実モデルを使う手動検証。通常のpytestからは実行しない。"""
import asyncio
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time
import tomllib
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_runtime import VideoRuntime


async def main():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / 'config.toml').read_text(encoding='utf-8'))
    runtime = VideoRuntime(config['video'], root, root / '.runtime/video')
    results = []
    for duration in (3, 5, 10):
        audio = root / f'.runtime/sample-{duration}.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-stream_loop', '-1', '-i',
                        str(root / '.runtime/lipsync-sample.wav'), '-t', str(duration),
                        '-c:a', 'pcm_s16le', str(audio)], check=True)
        peak = 0
        async def monitor():
            nonlocal peak
            while True:
                process = await asyncio.create_subprocess_exec('nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits', stdout=asyncio.subprocess.PIPE, creationflags=0x08000000)
                value, _ = await process.communicate()
                peak = max(peak, int(value.decode().strip().splitlines()[0]))
                await asyncio.sleep(.5)
        monitor_task = asyncio.create_task(monitor())
        started = time.monotonic()
        try:
            target = await runtime.generate(uuid4().hex, audio.read_bytes())
            saved = root / f'.runtime/soulx-{duration}s.mp4'
            shutil.copyfile(target, saved)
            runtime.cleanup(target.parent.name)
            result = {'audio_seconds': duration, 'generation_seconds': round(time.monotonic()-started, 2),
                      'peak_total_vram_mib': peak, 'video': str(saved), 'device': 'CUDA'}
            results.append(result)
            print(json.dumps(result), flush=True)
            (root / '.runtime/soulx-verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass


if __name__ == '__main__':
    asyncio.run(main())
