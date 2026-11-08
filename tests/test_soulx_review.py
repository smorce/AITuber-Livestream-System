from fastapi.testclient import TestClient

import server


def test_review_exposes_only_named_soulx_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'soulx-5s.mp4').write_bytes(b'0123456789')
    (runtime / 'obs-check.mp4').write_bytes(b'private recording')
    with TestClient(server.app) as client:
        response = client.get('/api/soulx-review/videos')
        assert response.status_code == 200
        videos = response.json()['videos']
        assert [video['id'] for video in videos] == ['soulx-5s']
        response = client.get(videos[0]['url'], headers={'Range': 'bytes=2-5'})
        assert response.status_code == 206
        assert response.content == b'2345'
        assert client.get('/api/soulx-review/video/obs-check').status_code == 404
        assert client.get('/api/soulx-review/video/missing').status_code == 404


def test_review_page_is_public():
    with TestClient(server.app) as client:
        assert client.get('/web/soulx-review.html').status_code == 200
