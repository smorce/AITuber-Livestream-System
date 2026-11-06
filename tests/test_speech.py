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
    runtime = SpeechRuntime(CONFIG['speech'], tmp_path)
    monkeypatch.setattr(runtime, 'executable', lambda:'speech')
    async def run():
        assert await asyncio.wait_for(runtime.synthesize('テスト'), 2) == b'wav'
        await runtime.stop()
    asyncio.run(run())


def test_gpu_failure_retries_cpu_once(monkeypatch, tmp_path):
    from server import CONFIG
    runtime = SpeechRuntime(CONFIG['speech'], tmp_path)
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
