import asyncio
import logging
import os
from pathlib import Path
import shutil
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)


class SpeechRuntime:
    def __init__(self, config, runtime_dir):
        self.config = config
        self.runtime_dir = runtime_dir
        self.process = None
        self.device = 'uninitialized'
        self.lock = asyncio.Lock()
        self.log_file = None
        self.model_id = None
        self.actual_device = None
        self.on_status = None

    async def report(self, phase, **details):
        if self.on_status:
            await self.on_status(phase, **details)

    def executable(self):
        configured = self.config.get('executable')
        installed = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/speech.cpp/0.10.1/speech.exe'
        binary = configured or shutil.which('speech') or (str(installed) if installed.exists() else None)
        if not binary:
            raise RuntimeError('speech executable not found; install speech.cpp or set speech.executable')
        return binary

    async def start(self, device):
        await self.stop()
        voice_args = []
        if self.config.get('reference_audio'):
            reference = (self.runtime_dir.parent / self.config['reference_audio']).resolve()
            if not reference.is_file():
                raise FileNotFoundError(f'Reference audio not found: {reference}')
            voice_args = ['--add-voice', 'reference=' + str(reference)]
        self.runtime_dir.mkdir(exist_ok=True)
        self.log_file = (self.runtime_dir / 'speech.log').open('ab')
        port = urlsplit(self.config['base_url']).port or 17864
        self.process = await asyncio.create_subprocess_exec(
            self.executable(), 'serve', self.config['model'], '--host', '127.0.0.1',
            '--port', str(port), '--device', device, *voice_args,
            stdout=self.log_file, stderr=self.log_file,
            creationflags=0x08000000 if os.name == 'nt' else 0,
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(600):
                if self.process.returncode is not None:
                    raise RuntimeError(f'speech server exited on {device}; see .runtime/speech.log')
                try:
                    r = await client.get(self.config['base_url'] + '/v1/models', timeout=1)
                    r.raise_for_status()
                    models = [m for m in r.json()['data'] if m.get('speech', {}).get('task') == 'synthesis']
                    if models:
                        self.model_id = models[0]['id']
                        self.actual_device = models[0]['speech'].get('device', device)
                        self.device = device
                        log.info('Speech ready: %s', device)
                        return
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError('speech startup timeout')

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    async def synthesize(self, text):
        async with self.lock:
            for device in ([self.device] if self.device == 'cpu' else ['gpu', 'cpu']):
                try:
                    if not self.process or self.process.returncode is not None or self.device != device:
                        await self.report('loading', device=device)
                        await self.start(device)
                    await self.report('synthesizing', device=self.actual_device or device)
                    async with httpx.AsyncClient(trust_env=False, timeout=self.config['timeout_seconds']) as client:
                        r = await client.post(self.config['base_url'] + '/v1/audio/speech', json={
                            'model': self.model_id,
                            'voice': 'reference' if self.config.get('reference_audio') else 'none',
                            'input': text,
                            'instructions': self.config['instructions'], 'seed': self.config['seed'],
                            'response_format': 'wav',
                        })
                        r.raise_for_status()
                        if r.headers.get('X-Speech-Stop', 'complete') != 'complete':
                            raise RuntimeError('speech generation was truncated')
                        return r.content
                except (httpx.HTTPError, RuntimeError):
                    log.exception('Speech failed on %s', device)
                    await self.stop()
                    if device == 'cpu':
                        raise
                    await self.report('retrying_cpu', device='cpu')
