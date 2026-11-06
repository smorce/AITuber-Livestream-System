import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
import io
import json
import logging
from pathlib import Path
import re
import tomllib
from uuid import uuid4
import wave

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from speech_runtime import SpeechRuntime

ROOT = Path(__file__).resolve().parent
CONFIG = tomllib.loads((ROOT / 'config.toml').read_text(encoding='utf-8'))
TV = 'ブラウン管TV_映像エディター_XYZデバッグ版.html'
log = logging.getLogger('aituber')


def split_text(text):
    parts = []
    for sentence in re.findall(r'[^。！？!?、\n]+[。！？!?、\n]*|[。！？!?、\n]+', text):
        parts.extend(sentence[i:i + 70] for i in range(0, len(sentence), 70))
    return [p for p in parts if p.strip()]


def join_wavs(chunks):
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        expected = None
        for chunk in chunks:
            with wave.open(io.BytesIO(chunk), 'rb') as source:
                params = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                if expected is None:
                    expected = params
                    target.setnchannels(params[0])
                    target.setsampwidth(params[1])
                    target.setframerate(params[2])
                if params != expected:
                    raise RuntimeError('Inconsistent speech WAV format')
                target.writeframes(source.readframes(source.getnframes()))
    return output.getvalue()


class Hub:
    def __init__(self):
        self.generation = 0
        self.jobs = asyncio.Queue()
        self.pending = deque()
        self.audio = {}
        self.owner = None
        self.ready = False
        self.current = None
        self.reserved = set()
        self.monitors = set()
        self.llm_lock = asyncio.Lock()
        self.llm_task = None
        self.synth_task = None
        self.speech = SpeechRuntime(CONFIG['speech'], ROOT / '.runtime')

    def clear_state(self):
        self.generation += 1
        self.pending.clear()
        self.audio.clear()
        self.reserved.clear()
        self.current = None
        while not self.jobs.empty():
            self.jobs.get_nowait()

    async def notify(self, event):
        for ws in list(self.monitors):
            try:
                await ws.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                self.monitors.discard(ws)

    async def dispatch(self):
        if self.owner and self.ready and self.current is None and self.pending:
            self.current = self.pending.popleft()
            await self.owner.send_json({'type': 'utterance', 'id': self.current,
                                        'generation': self.generation,
                                        'url': '/api/audio/' + self.current})

    async def worker(self):
        while True:
            item = await self.jobs.get()
            ident, generation, text = item
            if generation != self.generation:
                continue
            try:
                async def generate():
                    chunks = []
                    for part in split_text(text):
                        chunks.append(await self.speech.synthesize(part))
                    return join_wavs(chunks)
                self.synth_task = asyncio.create_task(generate())
                audio = await self.synth_task
                if generation == self.generation:
                    self.audio[ident] = audio
                    self.pending.append(ident)
                    await self.dispatch()
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception as exc:
                self.reserved.discard(ident)
                log.exception('Synthesis failed: %s', ident)
                await self.notify({'type': 'speech_error', 'id': ident, 'message': str(exc)})
            finally:
                self.synth_task = None


hub = Hub()


@asynccontextmanager
async def lifespan(app):
    global hub
    hub = Hub()
    worker = asyncio.create_task(hub.worker())
    yield
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
    await hub.speech.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])


@app.middleware('http')
async def same_origin(request, call_next):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        return Response('Cross-origin requests are not allowed', status_code=403)
    if request.headers.get('sec-fetch-site') == 'cross-site':
        return Response('Cross-site requests are not allowed', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/api/config')
async def config():
    return {'generation': hub.generation, **CONFIG['playback']}


@app.get('/health')
async def health():
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            r = await client.get(CONFIG['llm']['base_url'].removesuffix('/v1') + '/health')
            r.raise_for_status()
            data = r.json()
        return {**data, 'speech_device': hub.speech.actual_device or hub.speech.device, 'queue': len(hub.reserved)}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f'LLM unavailable: {exc}') from exc


@app.get('/v1/models')
async def models():
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            r = await client.get(CONFIG['llm']['base_url'] + '/models')
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f'LLM model discovery failed: {exc}') from exc


def sse(data):
    return 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'


@app.post('/v1/chat/completions')
async def chat(request: Request):
    body = await request.json()
    if not isinstance(body.get('messages'), list) or not body['messages']:
        raise HTTPException(400, 'messages must be a nonempty list')
    if hub.llm_lock.locked():
        raise HTTPException(409, 'Another LLM request is active')
    generation = hub.generation

    async def stream():
        async with hub.llm_lock:
            hub.llm_task = asyncio.current_task()
            content, finish, truncated = '', None, False
            try:
                async with httpx.AsyncClient(trust_env=False, timeout=CONFIG['llm']['timeout_seconds']) as client:
                    model_data = await client.get(CONFIG['llm']['base_url'] + '/models')
                    model_data.raise_for_status()
                    payload = dict(body)
                    payload['model'] = model_data.json()['data'][0]['id']
                    payload['stream'] = True
                    payload.pop('generation', None)
                    async with client.stream('POST', CONFIG['llm']['base_url'] + '/chat/completions', json=payload) as upstream:
                        upstream.raise_for_status()
                        async for line in upstream.aiter_lines():
                            if generation != hub.generation:
                                return
                            if not line.startswith('data:'):
                                continue
                            raw = line[5:].strip()
                            if raw == '[DONE]':
                                break
                            obj = json.loads(raw)
                            truncated = truncated or bool(obj.get('truncated'))
                            if obj.get('error'):
                                yield sse(obj)
                                return
                            choices = obj.get('choices') or []
                            if choices:
                                choice = choices[0]
                                content += choice.get('delta', {}).get('content') or ''
                                finish = choice.get('finish_reason') or finish
                            yield sse(obj)
                if generation == hub.generation and finish == 'stop' and not truncated and content.strip():
                    if len(hub.reserved) >= CONFIG['playback']['queue_limit']:
                        yield sse({'speech_error': 'Speech queue is full; reply was not queued'})
                    else:
                        ident = uuid4().hex
                        hub.reserved.add(ident)
                        hub.jobs.put_nowait((ident, generation, content))
                yield 'data: [DONE]\n\n'
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception('LLM request failed')
                yield sse({'error': {'message': f'LLM request failed: {exc}'}})
            finally:
                hub.llm_task = None
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})


@app.post('/api/clear')
async def clear():
    hub.clear_state()
    if hub.llm_task:
        hub.llm_task.cancel()
    if hub.synth_task:
        hub.synth_task.cancel()
    if hub.owner:
        await hub.owner.send_json({'type': 'clear', 'generation': hub.generation})
    return {'generation': hub.generation}


@app.get('/api/audio/{ident}')
async def audio(ident: str):
    if ident not in hub.audio:
        raise HTTPException(404, 'Audio expired or unavailable')
    return Response(hub.audio[ident], media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.websocket('/ws')
async def websocket(ws: WebSocket):
    origin = ws.headers.get('origin')
    if origin != 'http://' + ws.headers.get('host', ''):
        await ws.close(code=1008)
        return
    await ws.accept()
    monitor = ws.query_params.get('role') == 'chat'
    owner = not monitor and ws.query_params.get('preview') != '1' and hub.owner is None
    if monitor:
        hub.monitors.add(ws)
    if owner:
        hub.owner = ws
        hub.ready = False
    await ws.send_json({'type': 'hello', 'owner': owner, 'generation': hub.generation, **CONFIG['playback']})
    try:
        while True:
            event = await ws.receive_json()
            if event.get('type') == 'ping':
                await ws.send_json({'type': 'pong'})
                continue
            if event.get('type') == 'claim':
                if monitor or ws.query_params.get('preview') == '1':
                    await ws.send_json({'type': 'claim_denied', 'message': 'Preview cannot play audio'})
                elif hub.owner is ws:
                    await ws.send_json({'type': 'role', 'owner': True})
                elif hub.current is not None:
                    await ws.send_json({'type': 'claim_denied', 'message': 'Another TV is playing speech'})
                else:
                    previous = hub.owner
                    hub.owner = ws
                    hub.ready = False
                    if previous:
                        try:
                            await previous.send_json({'type': 'role', 'owner': False})
                        except (WebSocketDisconnect, RuntimeError):
                            pass
                    await ws.send_json({'type': 'role', 'owner': True})
                continue
            if hub.owner is not ws:
                continue
            if event.get('type') == 'ready':
                hub.ready = bool(event.get('ready'))
            if event.get('id') == hub.current and event.get('generation') == hub.generation:
                if event.get('type') in ('started', 'ended', 'failed', 'cancelled'):
                    log.info('Speech %s: %s', event['type'], hub.current)
                if event.get('type') in ('ended', 'failed', 'cancelled'):
                    ident = hub.current
                    hub.audio.pop(ident, None)
                    hub.reserved.discard(ident)
                    hub.current = None
                    await hub.notify({'type': 'speech_status', **event})
            await hub.dispatch()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.monitors.discard(ws)
        if hub.owner is ws:
            hub.owner = None
            hub.ready = False
            if hub.current:
                hub.audio.pop(hub.current, None)
                hub.reserved.discard(hub.current)
                await hub.notify({'type': 'speech_error', 'message': 'TV disconnected; active speech cancelled'})
                hub.current = None


PUBLIC = {'web/index.html', 'web/playback-core.js', 'web/tv-controller.js', 'web/chat-bridge.js', TV}
PUBLIC.update(p.name for p in ROOT.iterdir() if p.suffix.lower() in ('.mp4', '.png'))


@app.get('/')
async def index():
    return FileResponse(ROOT / 'web/index.html')


@app.get('/{path:path}')
async def assets(path: str):
    if path not in PUBLIC:
        raise HTTPException(404, 'Asset not found')
    return FileResponse(ROOT / path)


if __name__ == '__main__':
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    uvicorn.run(app, host='127.0.0.1', port=17863, access_log=False)
