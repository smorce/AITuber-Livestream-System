"""末尾のパディングフレームを除いて元の音声と結合する。"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import wave


def encode(artifacts, audio, output):
    files = sorted(Path(artifacts).glob('soulx_flashhead_video_*.json'),
                   key=lambda path: int(path.stem.rsplit('_', 1)[1]))
    if not files:
        raise RuntimeError('No SoulX video artifacts found')
    first = json.loads(files[0].read_text(encoding='utf-8'))['meta']
    with wave.open(str(audio)) as source:
        duration = source.getnframes() / source.getframerate()
    remaining = math.ceil(duration * float(first['fps']))
    frame_size = int(first['width']) * int(first['height']) * 3
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24',
               '-video_size', f'{first["width"]}x{first["height"]}', '-framerate', str(first['fps']),
               '-i', 'pipe:0', '-i', str(audio), '-c:a', 'aac', '-c:v', 'libx264', '-crf', '18',
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        for file in files:
            artifact = json.loads(file.read_text(encoding='utf-8'))
            meta = artifact['meta']
            if meta['format'] != 'rgb24' or any(meta[k] != first[k] for k in ('width', 'height', 'fps')):
                raise RuntimeError('Inconsistent SoulX video format')
            payload = bytes.fromhex(artifact['payload_hex'])
            if len(payload) != frame_size * int(meta['frames']):
                raise RuntimeError('Invalid SoulX video byte count')
            frames = min(remaining, int(meta['frames']))
            process.stdin.write(payload[:frames * frame_size])
            remaining -= frames
            if remaining == 0:
                break
        process.stdin.close()
        if process.wait() or remaining:
            raise RuntimeError('Incomplete SoulX video encoding')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    encode(args.input, args.audio, args.output)
