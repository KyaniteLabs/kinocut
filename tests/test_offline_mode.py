"""Exercise configured AI families with outbound sockets forbidden."""

import ipaddress
import json
import shutil
import socket
import subprocess
import sys
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kinocut import image_engine
from kinocut.aesthetic import NimaScorer
from kinocut.ai_engine import lfm3_audio, transcribe, upscale
from kinocut.ai_engine._longform_models import LongformChunk
from kinocut.ai_engine.download import _resolve_video_source
from kinocut.ai_engine.stem import ai_stem_separation
from kinocut.doctor import run_diagnostics
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _get_video_duration
from kinocut.object_matte.weights import ensure_weights
from kinocut.offline import is_loopback_url, is_offline_mode
from kinocut.te.sphere_assembly import propose_360_assembly
from kinocut.validation import object_matte_cache_path
from kinocut.watching import vision_provider


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("KINOCUT_OFFLINE", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.1:6543")
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:6543")
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    def check(address):
        assert isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback, address

    def connect(sock, address):
        check(address)
        return original_connect(sock, address)

    def create(address, *args, **kwargs):
        check(address)
        return original_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create)


@pytest.fixture
def loopback():
    records = []

    class ModelHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            records.append((self.path, payload, self.headers.get("Authorization")))
            if payload["model"] == "LFM3-1.7B":
                content = payload["messages"][1]["content"]
            elif payload["messages"][0]["role"] == "system":
                content = json.dumps({"verdict": "pass", "summary": "Sample looks clean", "findings": []})
            else:
                content = "<think>scratchpad</think>A blue cup."
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", records
        finally:
            server.shutdown()
            worker.join()


@pytest.mark.parametrize("url", ["http://127.0.0.1", "https://LOCALHOST:8900/v1", "http://[::1]:1"])
def test_loopback_accepts_exact_hosts(url):
    assert is_loopback_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.2",
        "http://[::ffff:127.0.0.1]",
        "http://localhost.evil.test",
        "http://localhost@evil.test",
        "http://@localhost",
        "http://evil.test@localhost",
        "http:///v1",
        "//localhost",
        "http://[::1]evil.test",
        "http://localhost:99999",
        "http://localhost\\@evil.test",
        "http://local\nhost",
        "https://remote.test",
    ],
)
def test_loopback_rejects_ambiguous_hosts(url):
    assert not is_loopback_url(url)


@pytest.mark.parametrize("value", ["1", "true", "YeS", " on "])
def test_offline_toggle(value):
    assert is_offline_mode({"KINOCUT_OFFLINE": value})
    assert not is_offline_mode({})


def test_vision_and_qc_use_loopback_openai(loopback, tmp_path, monkeypatch):
    base, requests = loopback
    monkeypatch.setenv("KINOCUT_VISION_MODE", "local")
    monkeypatch.setenv("LFM3_VL_URL", base + "/v1/chat/completions")
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"test sample")
    assert image_engine._describe_product_with_vision(str(image)) == "A blue cup."
    path, body, auth = requests[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "LFM3-VL-2B"
    assert auth is None
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    model = vision_provider.configured_vision_model()
    assert model is not None
    result = vision_provider.assess_keyframes(model, [{"time": 0.5, "path": str(image)}])
    assert result.verdict == "pass"
    assert requests[1][1]["messages"][1]["content"][1]["type"] == "image_url"


def test_vision_blocks_cloud_before_loading_image(monkeypatch):
    monkeypatch.setenv("KINOCUT_VISION_MODE", "remote")
    with pytest.raises(MCPVideoError, match="loopback LFM3-VL-2B") as caught:
        image_engine._describe_product_with_vision("does-not-exist.jpg", "https://remote.test")
    assert caught.value.code == "offline_network_blocked"
    with pytest.raises(MCPVideoError, match="loopback OpenAI-compatible") as caught:
        vision_provider.assess_keyframes("claude", [])
    assert caught.value.code == "offline_network_blocked"


def test_360_director_uses_explicit_loopback(loopback, tmp_path, monkeypatch):
    base, requests = loopback
    source = tmp_path / "sphere.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=640x320:r=2:d=1",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    monkeypatch.setenv("KINOCUT_360_DIRECTOR", "openai_compat")
    monkeypatch.setenv("KINOCUT_360_DIRECTOR_BASE_URL", base + "/v1")
    plan = propose_360_assembly(str(source))
    assert plan["writer"]["kind"] == "model"
    assert plan["writer"]["model"] == "LFM3-1.7B"
    assert requests[0][0] == "/v1/chat/completions"
    with pytest.raises(MCPVideoError, match=r"loopback LFM3-1\.7B") as caught:
        propose_360_assembly(str(source), base_url="https://remote.test", allow_cloud=True)
    assert caught.value.code == "offline_network_blocked"
    assert len(requests) == 1


def test_whisper_single_and_longform_only_load_paths(tmp_path, monkeypatch):
    from kinocut.ai_engine import _longform_runtime

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    model_path = tmp_path / "whisper" / "base.pt"
    media = tmp_path / "clip.mp4"
    media.touch()
    loaded = []

    def load(name, *, download_root):
        loaded.append((name, download_root))
        return SimpleNamespace(transcribe=lambda *args, **kwargs: {"text": " hello ", "language": "en"})

    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=load))
    monkeypatch.setattr(transcribe, "_validate_transcribe_duration", lambda path: 1.0)
    monkeypatch.setattr(transcribe, "_extract_transcription_audio", lambda *args: None)
    monkeypatch.setattr(
        _longform_runtime, "_extract_audio_segment", lambda *args, **kwargs: str(tmp_path / "audio.wav")
    )
    chunk = LongformChunk(index=0, start=0.0, end=1.0, duration=1.0)
    for call in (
        lambda: transcribe.ai_transcribe(str(media)),
        lambda: _longform_runtime._transcribe_chunk(
            str(media), chunk, model="base", language=None, work_dir=str(tmp_path)
        ),
    ):
        with pytest.raises(MCPVideoError) as caught:
            call()
        assert caught.value.code == "offline_model_missing"
        assert str(model_path) in str(caught.value)
    assert not loaded
    model_path.parent.mkdir()
    model_path.touch()
    assert transcribe.ai_transcribe(str(media))["transcript"] == "hello"
    assert (
        _longform_runtime._transcribe_chunk(str(media), chunk, model="base", language=None, work_dir=str(tmp_path))[
            "transcript"
        ]
        == "hello"
    )
    assert loaded == [(str(model_path), str(model_path.parent))] * 2


def test_lfm3_audio_runs_from_local_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KINOCUT_LFM3_AUDIO_DIR", str(tmp_path))
    monkeypatch.setenv("KINOCUT_ASR_BACKEND", "lfm3-audio")
    media = tmp_path / "clip.mp4"
    media.touch()
    monkeypatch.setattr(transcribe, "_validate_transcribe_duration", lambda path: 1.0)
    with pytest.raises(MCPVideoError) as missing:
        transcribe.ai_transcribe(str(media))
    assert missing.value.code == "offline_model_missing"
    assert str(tmp_path / "model.safetensors") in str(missing.value)
    for path in lfm3_audio.snapshot_files(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), float32="fp32", inference_mode=nullcontext),
    )
    with pytest.raises(MCPVideoError, match="lfm3-audio") as missing:
        transcribe.ai_transcribe(str(media), backend="lfm3-audio")
    assert missing.value.code == "missing_lfm3_audio"
    processor_loader, model_loader = MagicMock(), MagicMock()
    processor = processor_loader.from_pretrained.return_value
    processor.apply_chat_template.return_value.to.return_value = {"input_ids": SimpleNamespace(shape=(1, 3))}
    processor.decode.return_value = " LFM3 speech. "
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoProcessor=processor_loader, AutoModelForMultimodalLM=model_loader),
    )
    monkeypatch.setattr(lfm3_audio, "_extract_audio_segment", lambda *args, **kwargs: str(tmp_path / "chunk.wav"))
    assert transcribe.ai_transcribe(str(media), language="en")["transcript"] == "LFM3 speech."
    processor_loader.from_pretrained.assert_called_once_with(
        str(tmp_path), local_files_only=True, trust_remote_code=True
    )
    model_loader.from_pretrained.assert_called_once_with(
        str(tmp_path),
        local_files_only=True,
        trust_remote_code=True,
        use_safetensors=True,
        device_map="cpu",
        dtype="fp32",
    )


def test_missing_upscale_matte_and_nima_report_local_files(tmp_path, monkeypatch):
    monkeypatch.setenv("KINOCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("kinocut.aesthetic.WEIGHTS_SEARCH", [])
    monkeypatch.setattr("kinocut.aesthetic.WEIGHTS_PATH", str(tmp_path / "nima.pth"))
    for call, path in (
        (lambda: upscale._download_fsrcnn_model(2), tmp_path / "cache/models/FSRCNN_x2.pb"),
        (ensure_weights, object_matte_cache_path()),
        (object.__new__(NimaScorer)._find_weights, tmp_path / "nima.pth"),
    ):
        with pytest.raises(MCPVideoError) as caught:
            call()
        assert caught.value.code == "offline_model_missing"
        assert str(path) in str(caught.value)


def test_font_resolver_never_fetches_when_missing(monkeypatch):
    from kinocut import engine_runtime_utils

    monkeypatch.setattr(engine_runtime_utils.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(engine_runtime_utils, "_fontconfig_sans_font", lambda: None)
    with pytest.raises(MCPVideoError, match="local TrueType/OpenType font path") as caught:
        engine_runtime_utils._default_font()
    assert caught.value.code == "font_not_found"


def test_optional_downloaders_fail_before_dns_or_dependency_loading():
    with pytest.raises(MCPVideoError, match="local video file") as caught:
        _resolve_video_source("https://remote.test/video.mp4")
    assert caught.value.code == "offline_network_blocked"
    with pytest.raises(MCPVideoError, match="local stem WAVs") as caught:
        ai_stem_separation("clip.mp4", "stems")
    assert caught.value.code == "offline_network_blocked"


def test_doctor_reports_offline_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_VISION_MODE", "local")
    monkeypatch.setenv("KINOCUT_VISION_BASE_URL", "http://127.0.0.1:50911/v1/chat/completions")
    monkeypatch.setenv("KINOCUT_360_DIRECTOR", "openai_compat")
    monkeypatch.setenv("KINOCUT_360_DIRECTOR_BASE_URL", "http://127.0.0.1:50912/v1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    report = run_diagnostics(find_spec=lambda name: object())
    details = next(check for check in report["checks"] if check["name"] == "offline_readiness")["details"]
    assert details["enabled"]
    features = details["features"]
    assert set(features) == {
        "vision_product_description",
        "vision_semantic_qc",
        "director_360",
        "transcription_whisper",
        "transcription_lfm3_audio",
        "object_matte",
        "upscale",
    }
    for feature in ("vision_product_description", "vision_semantic_qc"):
        assert features[feature]["ready"] and features[feature]["model"] == "LFM3-VL-2B"
    assert features["director_360"]["ready"] and features["director_360"]["model"] == "LFM3-1.7B"
    assert not features["transcription_whisper"]["ready"]


@pytest.mark.skipif(not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")), reason="needs FFmpeg and ffprobe")
@pytest.mark.parametrize("operation", ["probe", "full_audio", "chunk_audio"])
def test_offline_media_subprocess_refuses_playlist_http(tmp_path, operation):
    playlist = tmp_path / "input.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://192.0.2.1/sample.ts\n#EXT-X-ENDLIST\n"
    )
    with pytest.raises(ProcessingError) as caught:
        if operation == "probe":
            _get_video_duration(str(playlist))
        elif operation == "full_audio":
            transcribe._extract_transcription_audio(playlist, str(tmp_path / "audio.wav"))
        else:
            transcribe._extract_audio_segment(str(playlist), 0.0, 1.0, output_dir=str(tmp_path))
    assert "Protocol 'http' not on whitelist 'file,pipe'" in caught.value.full_stderr
    assert not list(tmp_path.glob("*.wav"))
