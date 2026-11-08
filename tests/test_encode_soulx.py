import json
import subprocess

from encode_soulx import encode
from test_video_runtime import wav


def test_padding_frames_do_not_truncate_original_audio(tmp_path):
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    (artifacts / 'soulx_flashhead_video_0.json').write_text(json.dumps({
        'meta': {'width': '32', 'height': '32', 'frames': '24', 'fps': '25', 'format': 'rgb24'},
        'payload_hex': (bytes([40, 80, 120]) * 32 * 32 * 24).hex()}))
    audio = tmp_path / 'original.wav'
    audio.write_bytes(wav(.08))
    output = tmp_path / 'ready.mp4'
    encode(artifacts, audio, output)
    data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(output)]))
    video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
    sound = next(stream for stream in data['streams'] if stream['codec_type'] == 'audio')
    assert int(video['nb_frames']) == 2
    assert float(sound['duration']) >= .079
