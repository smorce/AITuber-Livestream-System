import asyncio
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import wave


class VideoRuntime:
    def __init__(self, config, root, work):
        self.config = config
        self.root = Path(root)
        self.work = Path(work).resolve()
        self.process = None
        self.on_status = None

    def directory(self, ident):
        if not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('Invalid utterance ID')
        path = (self.work / ident).resolve()
        if path.parent != self.work:
            raise ValueError('Invalid utterance path')
        return path

    def cleanup(self, ident):
        path = self.directory(ident)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError:
                # Windowsの配信中ファイルは次回の起動で回収する。
                pass

    async def status(self, phase):
        if self.on_status:
            await self.on_status(phase)

    async def run(self, args, logfile, env=None):
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        with open(logfile, 'ab') as output:
            process = await asyncio.create_subprocess_exec(*map(str, args), stdout=output, stderr=output,
                                                           env=env, creationflags=flags)
            self.process = process
            try:
                await asyncio.wait_for(process.wait(), self.config.get('timeout_seconds', 600))
                if process.returncode:
                    raise RuntimeError(f'Video command failed ({process.returncode}); see {logfile}')
            finally:
                if process.returncode is None:
                    if os.name == 'nt':
                        killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=flags)
                        await killer.wait()
                    else:
                        process.kill()
                    await process.wait()
                self.process = None

    async def generate(self, ident, audio):
        with wave.open(io.BytesIO(audio)) as source:
            duration = source.getnframes() / source.getframerate()
        if duration <= 0 or duration > self.config.get('max_audio_seconds', 180):
            raise RuntimeError('Speech exceeds video duration limit')
        kit = self.root / self.config.get('kit', 'soulx_flashhead_windows_rtx4090_quickstart')
        runtime = kit / 'runtime'
        cli = next(runtime.rglob('audiocpp_cli.exe'), None)
        repo = kit / 'audio.cpp'
        model = repo / 'models/SoulX-FlashHead-GGUF/SoulX-FlashHead-Lite-Q8_0.gguf'
        if not cli or not model.is_file():
            raise RuntimeError('SoulX runtime or model is not installed')
        size = self.config.get('size', 512)
        self.work.mkdir(parents=True, exist_ok=True)
        reserve = self.config.get('disk_reserve_gib', 10) * 1024**3
        if shutil.disk_usage(self.work).free < reserve + duration * size * size * 25 * 6:
            raise RuntimeError('Insufficient disk space for video generation')
        directory = self.directory(ident)
        directory.mkdir()
        log = directory / 'generation.log'
        original, normalized, portrait = (directory / p for p in ('original.wav', 'speech16k.wav', 'portrait.png'))
        original.write_bytes(audio)
        env = os.environ.copy()
        env['PATH'] = os.pathsep.join([str(runtime), str(cli.parent), *(str(p) for p in runtime.rglob('*') if p.is_dir()), env.get('PATH', '')])
        try:
            async with asyncio.timeout(self.config.get('timeout_seconds', 600)):
                await self.status('video_loading')
                await self.run(['ffmpeg', '-v', 'error', '-y', '-i', original, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', normalized], log)
                await self.run(['ffmpeg', '-v', 'error', '-y', '-i', kit / 'avatar.jpg', '-frames:v', '1', portrait], log)
                artifacts = directory / 'artifacts'
                artifacts.mkdir()
                await self.status('video_generating')
                await self.run([cli, '--family', 'soulx_flashhead', '--task', 'gen', '--model', model,
                    '--backend', 'cuda', '--threads', '8', '--audio', normalized,
                    '--request-option', f'reference_image_file={portrait}', '--request-option', f'height={size}',
                    '--request-option', f'width={size}', '--request-option', f'num_inference_steps={self.config.get("steps", 4)}',
                    '--request-option', f'seed={self.config.get("seed", 42)}', '--out-dir', artifacts], log, env)
                await self.status('video_encoding')
                temporary = directory / 'encoding.mp4'
                await self.run([sys.executable, self.root / 'encode_soulx.py',
                    '--input', artifacts, '--audio', original, '--output', temporary], log)
                probe_log = directory / 'probe.json'
                await self.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', temporary], probe_log)
                streams = json.loads(probe_log.read_text(encoding='utf-8'))['streams']
                video = next((s for s in streams if s['codec_type'] == 'video'), {})
                sound = next((s for s in streams if s['codec_type'] == 'audio'), {})
                if video.get('codec_name') != 'h264' or sound.get('codec_name') != 'aac' or float(sound.get('duration', 0)) < duration - .1 or float(video.get('duration', 0)) < duration - .1:
                    raise RuntimeError('Generated video is incomplete or has invalid streams')
                target = directory / 'ready.mp4'
                temporary.replace(target)
                shutil.rmtree(artifacts)
                review = self.root / '.runtime/review'
                try:
                    review.mkdir(parents=True, exist_ok=True)
                    saved = review / 'latest.partial.mp4'
                    shutil.copyfile(target, saved)
                    saved.replace(review / 'latest.mp4')
                except OSError:
                    logging.getLogger(__name__).exception('Could not save review video')
                return target
        except BaseException:
            if log.is_file():
                shutil.copyfile(log, self.work / 'last-error.log')
            self.cleanup(ident)
            raise
