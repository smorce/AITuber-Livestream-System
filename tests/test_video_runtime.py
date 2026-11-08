import asyncio
import io
import wave

import pytest

from video_runtime import VideoRuntime


def wav(seconds=1):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(b'\0\0' * int(seconds * 16000))
    return stream.getvalue()


def test_duration_limit_precedes_native_execution(tmp_path):
    runtime = VideoRuntime({'max_audio_seconds': 1}, tmp_path, tmp_path / 'work')
    with pytest.raises(RuntimeError, match='duration limit'):
        asyncio.run(runtime.generate('a' * 32, wav(2)))


def test_cleanup_rejects_paths_outside_work_root(tmp_path):
    runtime = VideoRuntime({}, tmp_path, tmp_path / 'work')
    with pytest.raises(ValueError, match='Invalid utterance'):
        runtime.cleanup('../outside')
    assert tmp_path.exists()


def test_cancel_terminates_process(tmp_path):
    async def run():
        import sys
        runtime = VideoRuntime({}, tmp_path, tmp_path / 'work')
        task = asyncio.create_task(runtime.run([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path / 'native.log'))
        await asyncio.sleep(.2)
        process = runtime.process
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode is not None
    asyncio.run(run())


def test_render_uses_original_audio_and_publishes_only_validated_video(tmp_path, monkeypatch):
    import json
    kit = tmp_path / 'kit'
    (kit / 'runtime').mkdir(parents=True)
    (kit / 'runtime/audiocpp_cli.exe').touch()
    model = kit / 'audio.cpp/models/SoulX-FlashHead-GGUF/SoulX-FlashHead-Lite-Q8_0.gguf'
    model.parent.mkdir(parents=True)
    model.touch()
    runtime = VideoRuntime({'kit': 'kit', 'disk_reserve_gib': 0}, tmp_path, tmp_path / 'work')
    commands = []
    async def run(args, logfile, env=None):
        commands.append([str(arg) for arg in args])
        if args[0] == 'ffprobe':
            logfile.write_text(json.dumps({'streams': [
                {'codec_type': 'video', 'codec_name': 'h264', 'duration': '1'},
                {'codec_type': 'audio', 'codec_name': 'aac', 'duration': '1'}]}))
        elif '--output' in args:
            from pathlib import Path
            Path(args[-1]).write_bytes(b'validated mp4')
    monkeypatch.setattr(runtime, 'run', run)
    ident = 'a' * 32
    result = asyncio.run(runtime.generate(ident, wav()))
    render = next(command for command in commands if '--output' in command)
    assert render[render.index('--audio') + 1].endswith('original.wav')
    assert result.name == 'ready.mp4'
    assert not (result.parent / 'artifacts').exists()
    runtime.cleanup(ident)
    assert not result.exists()
    assert (tmp_path / '.runtime/review/latest.mp4').read_bytes() == b'validated mp4'
