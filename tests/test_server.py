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
