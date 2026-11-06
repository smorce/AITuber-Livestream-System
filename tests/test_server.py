import io
import wave
import asyncio
import json

import httpx
import server

from fastapi.testclient import TestClient
from server import app, split_text, join_wavs, Hub


def test_split_long_japanese():
    parts = split_text('あ' * 180 + '。短文です。')
    assert all(len(p) <= 70 for p in parts)
    assert ''.join(parts) == 'あ' * 180 + '。短文です。'


def test_wav_join():
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        w.writeframes(b'\0\0' * 480)
    data = join_wavs([buf.getvalue(), buf.getvalue()])
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() == 960


def test_clear_invalidates_generation():
    h = Hub()
    h.audio['old'] = b'a'
    h.clear_state()
    assert h.generation == 1
    assert not h.audio


def test_speech_progress_and_failure_are_reported(monkeypatch):
    async def run():
        h = Hub()
        events = []
        finished = asyncio.Event()
        async def notify(event):
            events.append(event)
            if event.get('phase') in ('waiting', 'failed'):
                finished.set()
        monkeypatch.setattr(h, 'notify', notify)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            w.writeframes(b'\0\0' * 480)
        async def synthesize(text):
            if text == '失敗。':
                raise RuntimeError('Synthesis timeout')
            return buf.getvalue()
        monkeypatch.setattr(h.speech, 'synthesize', synthesize)
        await h.set_speech_status('one', 'queued', 0)
        h.reserved.add('one')
        h.jobs.put_nowait(('one', 0, '一文。二文。'))
        worker = asyncio.create_task(h.worker())
        try:
            await asyncio.wait_for(finished.wait(), 2)
            progress = [e for e in events if e.get('phase') == 'synthesizing']
            assert [e['completed'] for e in progress] == [1, 2]
            assert all(e['total'] == 2 for e in progress)
            assert h.speech_states['one']['phase'] == 'waiting'
            finished.clear()
            h.reserved.add('two')
            h.jobs.put_nowait(('two', 0, '失敗。'))
            await asyncio.wait_for(finished.wait(), 2)
            assert h.speech_states['two']['phase'] == 'failed'
            assert 'Synthesis timeout' in h.speech_states['two']['message']
            h.clear_state()
            await h.set_speech_status('two', 'waiting', 0)
            assert not h.speech_states
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
    asyncio.run(run())


def test_chat_monitor_receives_current_speech_snapshot():
    with TestClient(app) as client:
        with client.websocket_connect('/ws?role=chat', headers={'Origin':'http://testserver'}) as monitor:
            assert monitor.receive_json()['type'] == 'hello'
            snapshot = monitor.receive_json()
            assert snapshot == {'type':'speech_snapshot', 'generation':0, 'states':[], 'tv':{'connected':False, 'ready':False}}


def test_playback_status_includes_audio_end_and_failure_reason():
    headers = {'Origin':'http://testserver'}
    with TestClient(app) as client:
        with client.websocket_connect('/ws', headers=headers) as tv:
            tv.receive_json()
            with client.websocket_connect('/ws?role=chat', headers=headers) as monitor:
                monitor.receive_json()
                monitor.receive_json()
                server.hub.current = 'speech-id'
                for event, phase in [('started','playing'), ('audio_ended','finishing'), ('failed','failed')]:
                    tv.send_json({'type':event, 'id':'speech-id', 'generation':0, 'message':'Video decode failed'})
                    status = monitor.receive_json()
                    assert status['type'] == 'speech_status'
                    assert status['phase'] == phase
                assert status['message'] == 'Video decode failed'
                assert server.hub.current is None


def test_only_public_assets_served():
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/server.py').status_code == 404
        assert client.get('/pyproject.toml').status_code == 404
        assert client.get('/web/playback-core.js').status_code == 200


def test_reject_cross_origin_clear():
    with TestClient(app) as client:
        assert client.post('/api/clear', headers={'Origin':'https://example.com'}).status_code == 403


def test_websocket_single_owner_and_clear():
    headers = {'Origin': 'http://testserver'}
    with TestClient(app) as client:
        with client.websocket_connect('/ws', headers=headers) as first:
            assert first.receive_json()['owner'] is True
            with client.websocket_connect('/ws', headers=headers) as second:
                assert second.receive_json()['owner'] is False
                first.send_json({'type':'ping'})
                assert first.receive_json()['type'] == 'pong'
                response = client.post('/api/clear')
                assert response.status_code == 200
                assert first.receive_json()['type'] == 'clear'
        with client.websocket_connect('/ws?preview=1', headers=headers) as preview:
            assert preview.receive_json()['owner'] is False


def test_reject_foreign_websocket():
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'Origin':'https://example.com'}):
                pass


def test_play_claim_moves_idle_owner_but_never_interrupts_active_speech():
    headers = {'Origin': 'http://testserver'}
    with TestClient(app) as client:
        with client.websocket_connect('/ws', headers=headers) as first:
            assert first.receive_json()['owner']
            with client.websocket_connect('/ws', headers=headers) as second:
                assert not second.receive_json()['owner']
                second.send_json({'type':'claim'})
                assert first.receive_json() == {'type':'role', 'owner':False}
                assert second.receive_json() == {'type':'role', 'owner':True}
                second.send_json({'type':'ready', 'ready':True})
                second.send_json({'type':'ping'})
                assert second.receive_json()['type'] == 'pong'
                assert server.hub.ready
                first.send_json({'type':'ready', 'ready':False})
                first.send_json({'type':'ping'})
                assert first.receive_json()['type'] == 'pong'
                assert server.hub.ready
                server.hub.current = 'playing-id'
                first.send_json({'type':'claim'})
                denied = first.receive_json()
                assert denied['type'] == 'claim_denied'
                assert server.hub.current == 'playing-id'


def test_preview_cannot_claim_playback():
    with TestClient(app) as client:
        with client.websocket_connect('/ws?preview=1', headers={'Origin':'http://testserver'}) as preview:
            assert not preview.receive_json()['owner']
            preview.send_json({'type':'claim'})
            assert preview.receive_json()['type'] == 'claim_denied'


def test_llm_only_completed_content_is_queued(monkeypatch):
    real_client = httpx.AsyncClient
    async def synthesize(text):
        await asyncio.sleep(60)
    def upstream(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data':[{'id':'test-model'}]})
        obj = json.loads(request.content)
        assert obj['model'] == 'test-model'
        finish = obj['messages'][0]['content']
        events = [
            {'choices':[{'delta':{'reasoning_content':'PRIVATE THOUGHT'}}]},
            {'choices':[{'delta':{'content':'本文です。'}}]},
            {'choices':[{'delta':{},'finish_reason':'stop' if finish == 'truncated' else finish}], 'truncated':finish == 'truncated'},
        ]
        return httpx.Response(200, text=''.join(server.sse(e) for e in events)+'data: [DONE]\n\n')
    monkeypatch.setattr(server.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(upstream)))
    with TestClient(app) as client:
        monkeypatch.setattr(server.hub.speech, 'synthesize', synthesize)
        for finish in ['length', 'truncated', 'stop']:
            r = client.post('/v1/chat/completions', json={'messages':[{'role':'user','content':finish}]})
            assert r.status_code == 200
            assert '本文です。' in r.text
            assert len(server.hub.reserved) == (1 if finish == 'stop' else 0)
        server.hub.reserved.update(str(i) for i in range(9))
        r = client.post('/v1/chat/completions', json={'messages':[{'role':'user','content':'stop'}]})
        assert 'Speech queue is full' in r.text
        assert len(server.hub.reserved) == 10
        assert client.post('/api/clear').status_code == 200
        assert not server.hub.reserved
