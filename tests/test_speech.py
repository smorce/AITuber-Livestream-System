import asyncio
import httpx

from speech_runtime import SpeechRuntime


def test_catalog_alias_differs_from_server_model_id(monkeypatch, tmp_path):
    import speech_runtime
    from server import CONFIG
    real_client = httpx.AsyncClient
    def upstream(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data':[{'id':'Irodori-TTS-v4.1-Small-MF','speech':{'task':'synthesis','device':'Vulkan0'}}]})
        import json
        assert json.loads(request.content)['model'] == 'Irodori-TTS-v4.1-Small-MF'
        return httpx.Response(200, content=b'wav')
    monkeypatch.setattr(speech_runtime.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(upstream)))
    class Process:
        returncode = None
        def terminate(self):
            self.returncode = 0
        async def wait(self):
            return 0
    async def spawn(*args, **kwargs):
        return Process()
    monkeypatch.setattr(speech_runtime.asyncio, 'create_subprocess_exec', spawn)
    runtime = SpeechRuntime({**CONFIG['speech'], 'reference_audio': ''}, tmp_path)
    monkeypatch.setattr(runtime, 'executable', lambda:'speech')
    async def run():
        assert await asyncio.wait_for(runtime.synthesize('テスト'), 2) == b'wav'
        await runtime.stop()
    asyncio.run(run())


def test_gpu_failure_retries_cpu_once(monkeypatch, tmp_path):
    from server import CONFIG
    runtime = SpeechRuntime({**CONFIG['speech'], 'reference_audio': ''}, tmp_path)
    attempts = []
    async def start(device):
        attempts.append(device)
        if device == 'gpu':
            raise RuntimeError('Vulkan out of memory')
        runtime.device = device
        runtime.model_id = 'Irodori-TTS-v4.1-Small-MF'
    monkeypatch.setattr(runtime, 'start', start)
    real_client = httpx.AsyncClient
    import speech_runtime
    monkeypatch.setattr(speech_runtime.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'cpu-wav'))))
    assert asyncio.run(runtime.synthesize('テスト')) == b'cpu-wav'
    assert attempts == ['gpu', 'cpu']


def test_reference_is_loaded_once_and_used_for_each_sentence(monkeypatch, tmp_path):
    import json
    import speech_runtime
    from server import CONFIG
    reference = tmp_path / '基準音声.wav'
    reference.write_bytes(b'reference-wav')
    config = {**CONFIG['speech'], 'reference_audio': reference.name}
    runtime = SpeechRuntime(config, tmp_path / '.runtime')
    commands, voices = [], []
    real_client = httpx.AsyncClient
    def upstream(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data':[{'id':'Irodori-TTS-v4.1-Small-MF','speech':{'task':'synthesis','device':'Vulkan0'}}]})
        body = json.loads(request.content)
        voices.append(body['voice'])
        assert body['instructions'] == config['instructions']
        return httpx.Response(200, content=b'wav')
    monkeypatch.setattr(speech_runtime.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(upstream)))
    class Process:
        returncode = None
        def terminate(self):
            self.returncode = 0
        async def wait(self):
            return 0
    async def spawn(*args, **kwargs):
        commands.append(args)
        return Process()
    monkeypatch.setattr(speech_runtime.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(runtime, 'executable', lambda:'speech')
    async def run():
        try:
            await runtime.synthesize('一文目です。')
            await runtime.synthesize('二文目です。')
        finally:
            await runtime.stop()
    asyncio.run(run())
    assert voices == ['reference', 'reference']
    assert len(commands) == 1
    assert commands[0][-2:] == ('--add-voice', 'reference=' + str(reference))


def test_missing_reference_does_not_fall_back_to_random_voice(tmp_path):
    import pytest
    from server import CONFIG
    runtime = SpeechRuntime({**CONFIG['speech'], 'reference_audio':'missing.wav'}, tmp_path / '.runtime')
    with pytest.raises(FileNotFoundError, match='Reference audio not found'):
        asyncio.run(runtime.synthesize('テスト'))
