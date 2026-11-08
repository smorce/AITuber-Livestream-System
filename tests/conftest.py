import pytest

import server
from video_runtime import VideoRuntime


@pytest.fixture(autouse=True)
def isolate_server_video_work(monkeypatch, tmp_path):
    # TestClientの起動時回収が、稼働中サーバーの動画を消さないようにする。
    monkeypatch.setattr(server, 'VideoRuntime', lambda config, root, work: VideoRuntime(config, root, tmp_path / 'video'))
