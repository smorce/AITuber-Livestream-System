"""Optional microphone recording into japanese.wav (6 seconds by default).

Usage:
  uv run --python 3.11 --with numpy --with sounddevice python record.py
  uv run --python 3.11 --with numpy --with sounddevice python record.py --seconds 10
"""
import argparse
from pathlib import Path
import wave

import sounddevice as sd

p = argparse.ArgumentParser()
p.add_argument('--seconds', type=float, default=6.0)
p.add_argument('--rate', type=int, default=16000)
p.add_argument('--out', type=Path, default=Path(__file__).parent / 'japanese.wav')
a = p.parse_args()
if a.seconds <= 0:
    raise SystemExit('--seconds must be positive')
frames = int(a.seconds * a.rate)
print(f'マイクから {a.seconds:g} 秒間録音します。日本語で話してください。')
recording = sd.rec(frames, samplerate=a.rate, channels=1, dtype='int16')
sd.wait()
a.out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(a.out), 'wb') as fp:
    fp.setnchannels(1)
    fp.setsampwidth(2)
    fp.setframerate(a.rate)
    fp.writeframes(recording.tobytes())
print(f'保存しました: {a.out.resolve()}')
