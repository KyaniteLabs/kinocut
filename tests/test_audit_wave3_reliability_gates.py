"""Wave 3b audit remediation regression tests (reliability, fail-closed gates, portability)."""

from __future__ import annotations

import asyncio
import errno
import io
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from kinocut.errors import MCPVideoError


# ---------------------------------------------------------------------------
# 1. D5-004 + D5-007 + C1-021: direct speed bounds, unresolved questions, staged writer
# ---------------------------------------------------------------------------


def test_direct_quarter_speed_accepted_and_out_of_range_rejected(tmp_path: Path, monkeypatch) -> None:
    from kinocut import server_tools_direct as tools
    from kinocut.direct import executor
    from kinocut.direct_validation import validate_args

    source = tmp_path / "src.mp4"
    source.write_bytes(b"source-bytes")
    out = tmp_path / "quarter.mp4"
    monkeypatch.setattr(
        executor, "probe", lambda _: {"duration": 12.0, "width": 1280, "height": 720, "has_audio": True}
    )

    reviewed = tools.video_direct(str(source), "slow it down to quarter speed", output_path=str(out))
    assert reviewed["success"] is True
    assert reviewed["question"] is None
    assert reviewed["plan"]["steps"][0]["tool"] == "video_speed"
    assert reviewed["plan"]["steps"][0]["args"]["factor"] == 0.25

    def fake_run_step(tool: str, args: dict) -> dict:
        assert tool == "video_speed"
        assert args["factor"] == 0.25
        Path(args["output_path"]).write_bytes(b"slowed")
        return {"success": True, "output_path": args["output_path"]}

    monkeypatch.setattr(executor, "_run_step", fake_run_step)
    applied = tools.video_direct_apply(reviewed["plan"], confirm=True)
    assert applied["success"] is True, applied
    assert out.read_bytes() == b"slowed"

    # Bounds check: [0.25, 4.0] accepted; 0.24 and 4.01 rejected.
    validate_args("video_speed", {"input_path": str(source), "output_path": str(out), "factor": 0.25})
    validate_args("video_speed", {"input_path": str(source), "output_path": str(out), "factor": 4.0})
    for bad in (0.24, 4.01):
        with pytest.raises(MCPVideoError) as exc:
            validate_args("video_speed", {"input_path": str(source), "output_path": str(out), "factor": bad})
        assert exc.value.code == "invalid_direct_plan"


def test_direct_apply_refuses_unresolved_question_and_ambiguity(tmp_path: Path, monkeypatch) -> None:
    from kinocut import server_tools_direct as tools
    from kinocut.direct import executor

    source = tmp_path / "src.mp4"
    source.write_bytes(b"source-bytes")
    out = tmp_path / "out.mp4"
    monkeypatch.setattr(
        executor, "probe", lambda _: {"duration": 60.0, "width": 1920, "height": 1080, "has_audio": True}
    )

    reviewed = tools.video_direct(str(source), "purple banana spaceship", output_path=str(out))
    plan = reviewed["plan"]
    assert plan["question"]

    # Dry-run still succeeds so caller can inspect the plan.
    dry = tools.video_direct_apply(plan, confirm=False)
    assert dry["success"] is True
    assert dry["dry_run"] is True

    # Confirm=True refuses execution while question is unresolved.
    blocked = tools.video_direct_apply(plan, confirm=True)
    assert blocked["success"] is False
    assert blocked["error"]["code"] == "unresolved_direct_question"

    # Ambiguity entries also block confirm=True even if question is cleared.
    resolved_plan = dict(plan, question=None, ambiguities=["unclear trim boundary"])
    blocked_amb = tools.video_direct_apply(resolved_plan, confirm=True)
    assert blocked_amb["success"] is False
    assert blocked_amb["error"]["code"] == "unresolved_direct_question"

    # Clearing both allows execution.
    clean_plan = dict(plan, question=None)
    ok = tools.video_direct_apply(clean_plan, confirm=True)
    assert ok["success"] is True


def test_direct_executor_uses_open_staged_writer_for_srt_and_silent_copy(tmp_path: Path, monkeypatch) -> None:
    from kinocut import ai_engine, server_tools_direct as tools
    from kinocut.direct import executor
    from kinocut.publication import open_staged_writer as real_open_staged_writer

    source = tmp_path / "src.mp4"
    source.write_bytes(b"video-payload")
    out_srt_video = tmp_path / "captioned.mp4"
    out_silent = tmp_path / "silent.mp4"
    monkeypatch.setattr(
        executor, "probe", lambda _: {"duration": 10.0, "width": 1280, "height": 720, "has_audio": True}
    )

    staged_calls: list[str] = []

    @contextmanager
    def spy_open_staged_writer(staged: str):
        staged_calls.append(staged)
        with real_open_staged_writer(staged) as handle:
            yield handle

    monkeypatch.setattr(executor, "open_staged_writer", spy_open_staged_writer)

    # 1) SRT sidecar write uses open_staged_writer
    plan_speech = tools.video_direct(str(source), "captions", output_path=str(out_srt_video))["plan"]
    monkeypatch.setattr(
        ai_engine,
        "ai_transcribe",
        lambda *a, **kw: {
            "transcript": "Hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}],
            "language": "en",
        },
    )
    orig_run_step = executor._run_step

    def run_speech(tool: str, args: dict) -> dict:
        if tool == "video_ai_transcribe":
            return orig_run_step(tool, args)
        Path(args["output_path"]).write_bytes(b"burned")
        return {"success": True, "output_path": args["output_path"]}

    monkeypatch.setattr(executor, "_run_step", run_speech)
    res_speech = tools.video_direct_apply(plan_speech, confirm=True)
    assert res_speech["success"] is True
    assert len(staged_calls) == 1

    # 2) Silent fallback copy uses open_staged_writer
    plan_silent = tools.video_direct(str(source), "captions", output_path=str(out_silent))["plan"]
    monkeypatch.setattr(
        ai_engine,
        "ai_transcribe",
        lambda *a, **kw: {"transcript": "", "segments": [], "language": "en"},
    )
    monkeypatch.setattr(executor, "_run_step", orig_run_step)
    res_silent = tools.video_direct_apply(plan_silent, confirm=True)
    assert res_silent["success"] is True
    assert out_silent.read_bytes() == b"video-payload"
    assert len(staged_calls) == 2


# ---------------------------------------------------------------------------
# 2. D5-024 + D5-026: Cutfile YAML round-trip & no literal CAPTIONS watermark
# ---------------------------------------------------------------------------


def test_cutfile_yaml_non_empty_parses_and_roundtrips_without_corruption(tmp_path: Path) -> None:
    from kinocut.te.cutfile import load_cutfile, validate_cutfile

    yaml_text = """\
name: podcast-cut
version: 1
sources:
  - id: hero
    path: media/hero.mp4
  - id: broll
    path: media/broll.mp4
ops:
  - op: trim
    start: 2.5
    duration: 15
  - op: resize
    width: 1080
    height: 1920
"""
    p = tmp_path / "cutfile.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    cf = load_cutfile(str(p))
    assert cf.name == "podcast-cut"
    assert cf.version == 1
    assert cf.sources == [
        {"id": "hero", "path": "media/hero.mp4"},
        {"id": "broll", "path": "media/broll.mp4"},
    ]
    assert cf.ops == [
        {"op": "trim", "start": 2.5, "duration": 15},
        {"op": "resize", "width": 1080, "height": 1920},
    ]

    # Round-trip through to_yaml()
    p2 = tmp_path / "roundtrip.yaml"
    p2.write_text(cf.to_yaml(), encoding="utf-8")
    cf2 = load_cutfile(str(p2))
    assert cf2 == cf

    # Strict version validation (D5-024)
    for bad_version in ("abc", False, 0, 2):
        with pytest.raises(MCPVideoError) as exc:
            validate_cutfile({"name": "bad", "version": bad_version, "sources": [], "ops": []})
        assert exc.value.code == "cutfile_version"


def test_goal_and_constraint_solve_never_emit_literal_captions_watermark() -> None:
    from kinocut.te.constraint_solve import solve_publish_cutfile
    from kinocut.te.cutfile import validate_cutfile
    from kinocut.te.cutfile_render import compile_cutfile_to_workflow
    from kinocut.te.goal_cutfile import compile_goal_to_cutfile

    goal_no_srt = compile_goal_to_cutfile("15s vertical short with captions", source="media/hero.mp4")
    assert all(op.get("text") != "CAPTIONS" for op in goal_no_srt["ops"])
    assert all(op["op"] != "add_text" for op in goal_no_srt["ops"])
    assert goal_no_srt["requires_transcription"] is True
    assert goal_no_srt["warnings"]

    goal_with_srt = compile_goal_to_cutfile(
        "15s vertical short with captions", source="media/hero.mp4", subtitle_source="media/captions.srt"
    )
    assert all(op.get("text") != "CAPTIONS" for op in goal_with_srt["ops"])
    burn_ops = [op for op in goal_with_srt["ops"] if op["op"] == "burn_in"]
    assert len(burn_ops) == 1
    assert "subtitles" in burn_ops[0]["srcs"]
    spec_goal = compile_cutfile_to_workflow(validate_cutfile(goal_with_srt))
    assert spec_goal["steps"][-1]["op"] == "burn_in"

    solved_no_srt = solve_publish_cutfile("youtube_shorts", source="media/hero.mp4", captions=True)
    assert all(op.get("text") != "CAPTIONS" for op in solved_no_srt["ops"])
    assert all(op["op"] != "add_text" for op in solved_no_srt["ops"])
    assert solved_no_srt["requires_transcription"] is True
    assert solved_no_srt["warnings"]

    solved_with_srt = solve_publish_cutfile(
        "youtube_shorts", source="media/hero.mp4", captions=True, subtitle_source="media/captions.srt"
    )
    assert all(op.get("text") != "CAPTIONS" for op in solved_with_srt["ops"])
    assert solved_with_srt["ops"][-1]["op"] == "burn_in"
    spec_solved = compile_cutfile_to_workflow(validate_cutfile(solved_with_srt))
    assert spec_solved["steps"][-1]["op"] == "burn_in"


# ---------------------------------------------------------------------------
# 3. D1-003 / C4-008 + C2-009: CLI batch exit code & __main__ redaction / install hint
# ---------------------------------------------------------------------------


def test_cli_batch_exits_nonzero_when_batch_fails() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "batch",
            "/nonexistent-wave3b-audit-file.mp4",
            "--operation",
            "trim",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["success"] is False
    assert payload["failed"] == 1


def test_cli_main_redacts_json_errors_and_avoids_hardcoded_201_pin(monkeypatch, capsys) -> None:
    from kinocut import __main__ as cli_main
    from kinocut._install_hints import pip_install_hint

    # 1) Unexpected exception in --format json mode must redact secrets and paths.
    monkeypatch.setattr(
        sys,
        "argv",
        ["kino", "--format", "json", "trim", "/tmp/in.mp4", "--start", "0", "--duration", "1"],
    )

    def exploding_dispatch(*_a, **_kw):
        raise RuntimeError("Failed with Bearer supersecrettoken12345 on /home/alice/private/secret.mp4")

    monkeypatch.setattr(cli_main, "_dispatch_cli", exploding_dispatch)
    with pytest.raises(SystemExit) as exc:
        cli_main.main()
    assert exc.value.code == 1
    err_payload = json.loads(capsys.readouterr().err)
    msg = err_payload["error"]["message"]
    assert "supersecrettoken12345" not in msg
    assert "/home/alice/private/secret.mp4" not in msg

    # 2) Missing mcp package hint uses pip_install_hint rather than hardcoded 2.0.1.
    def missing_mcp():
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    with pytest.raises(SystemExit) as exc2:
        cli_main._run_mcp_mode(import_server=missing_mcp)
    assert exc2.value.code == 1
    captured_err = capsys.readouterr().err
    assert pip_install_hint(quoted=False) in captured_err
    source_text = Path(cli_main.__file__).read_text(encoding="utf-8")
    assert "==2.0.1" not in source_text


# ---------------------------------------------------------------------------
# 4. D1-004: File-backed MCP resources handle absolute & percent-encoded paths safely
# ---------------------------------------------------------------------------


def test_mcp_file_backed_resources_support_absolute_paths_and_block_traversal(monkeypatch) -> None:
    from kinocut import server_resources
    from kinocut.models import VideoInfo
    from kinocut.server_app import mcp

    seen_paths: list[str] = []

    def fake_probe(path: str) -> VideoInfo:
        decoded = server_resources._decode_resource_path(path)
        seen_paths.append(decoded)
        return VideoInfo(
            path=decoded,
            duration=12.0,
            width=1920,
            height=1080,
            fps=30.0,
            codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
        )

    monkeypatch.setattr(server_resources, "_probe", fake_probe)

    async def read_text(uri: str) -> str:
        items = await mcp.read_resource(uri)
        return "".join(getattr(item, "content", "") for item in items)

    # Raw absolute POSIX path across all 3 resource templates
    info_raw = json.loads(asyncio.run(read_text("mcp-video://video//tmp/my dir/clip.mp4/info")))
    assert info_raw["path"] == "/tmp/my dir/clip.mp4"

    preview_raw = asyncio.run(read_text("mcp-video://video//tmp/clip.mp4/preview"))
    assert "Frame 1:" in preview_raw

    audio_raw = asyncio.run(read_text("mcp-video://video//tmp/clip.mp4/audio"))
    assert "Audio codec: aac" in audio_raw

    # Percent-encoded absolute POSIX path (including spaces and Unicode)
    info_enc = json.loads(asyncio.run(read_text("mcp-video://video/%2Ftmp%2Fcaf%C3%A9%20clip.mp4/info")))
    assert info_enc["path"] == "/tmp/café clip.mp4"

    # Windows drive path (both raw forward-slash and percent-encoded backslash)
    info_win = json.loads(asyncio.run(read_text("mcp-video://video/C:/Users/alice/clip.mp4/info")))
    assert info_win["path"] == "C:/Users/alice/clip.mp4"
    info_win_enc = json.loads(asyncio.run(read_text("mcp-video://video/C%3A%5CUsers%5Calice%5Cclip.mp4/info")))
    assert info_win_enc["path"] == r"C:\Users\alice\clip.mp4"

    # Traversal, control bytes, and URL schemes fail closed
    for bad_uri in (
        "mcp-video://video//tmp/../etc/passwd/info",
        "mcp-video://video/%2Ftmp%2F..%2Fetc%2Fpasswd/info",
        "mcp-video://video/..%2Fsecret.mp4/preview",
        "mcp-video://video/http%3A%2F%2F169.254.169.254%2Flatest/audio",
        "mcp-video://video/%2Ftmp%2Fclip%00.mp4/info",
    ):
        payload = json.loads(asyncio.run(read_text(bad_uri)))
        assert payload["success"] is False
        assert payload["error"]["code"] == "unsafe_path"


# ---------------------------------------------------------------------------
# 5. D1-013: Doctor fails closed on unrecognized / empty required binary versions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("banner", ["unrecognized banner", "", "   ", "ffmpeg version test", "not ffmpeg 9.0"])
def test_doctor_fails_closed_on_unrecognized_or_empty_ffmpeg_version(banner: str) -> None:
    from kinocut.doctor import run_diagnostics

    report = run_diagnostics(
        which=lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=lambda _cmd: banner,
        find_spec=lambda _name: None,
    )
    checks = {c["name"]: c for c in report["checks"]}
    assert checks["ffmpeg"]["ok"] is False
    assert checks["ffprobe"]["ok"] is False
    assert report["summary"]["required_ok"] is False
    assert checks["ffmpeg"]["install_hint"]
    assert checks["ffprobe"]["install_hint"]


@pytest.mark.parametrize(
    "ffmpeg_banner,ffprobe_banner",
    [
        (
            "ffmpeg version n7.1.1 Copyright (c) 2000-2025 the FFmpeg developers",
            "ffprobe version n7.1.1 Copyright (c) 2007-2025 the FFmpeg developers",
        ),
        (
            "ffmpeg version N-118200-gabcdef1234 Copyright (c) 2000-2025",
            "ffprobe version N-118200-gabcdef1234 Copyright (c) 2007-2025",
        ),
    ],
)
def test_doctor_accepts_distro_n_prefix_and_git_snapshot_banners(ffmpeg_banner: str, ffprobe_banner: str) -> None:
    from kinocut.doctor import run_diagnostics

    report = run_diagnostics(
        which=lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=lambda cmd: ffprobe_banner if "ffprobe" in cmd[0] else ffmpeg_banner,
        find_spec=lambda _name: None,
    )
    checks = {c["name"]: c for c in report["checks"]}
    assert checks["ffmpeg"]["ok"] is True
    assert checks["ffprobe"]["ok"] is True


# ---------------------------------------------------------------------------
# 6. C4-004 + C4-005: effect_vignette smoothness & layout_grid gap/padding/background
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires FFmpeg")
def test_effect_vignette_smoothness_changes_filter_and_rendered_falloff(tmp_path: Path) -> None:
    from kinocut.effects_engine import effect_vignette

    src = tmp_path / "gray.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xC0C0C0:s=160x96:r=10:d=0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    out_hard = tmp_path / "vignette_hard.mp4"
    out_soft = tmp_path / "vignette_soft.mp4"
    effect_vignette(str(src), str(out_hard), intensity=0.7, radius=0.8, smoothness=0.0)
    effect_vignette(str(src), str(out_soft), intensity=0.7, radius=0.8, smoothness=1.0)

    def read_frame(path: Path) -> np.ndarray:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(96, 160, 3)

    hard = read_frame(out_hard)
    soft = read_frame(out_soft)

    # Center stays bright and unchanged for both; corners darken with neutral chroma.
    assert abs(float(hard[48, 80].mean()) - float(soft[48, 80].mean())) <= 4
    assert np.ptp(hard[4, 4].astype(int)) <= 3
    assert np.ptp(soft[4, 4].astype(int)) <= 3

    # Mid-ring pixel (between center and corner) must be significantly darker on smoothness=1.0
    # than on crisp smoothness=0.0.
    mid_hard = float(hard[18, 30].mean())
    mid_soft = float(soft[18, 30].mean())
    assert mid_hard - mid_soft > 15, f"Expected hard mid-ring ({mid_hard}) > soft ({mid_soft})"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires FFmpeg")
def test_layout_grid_renders_gap_padding_background_and_rejects_bad_color(tmp_path: Path) -> None:
    from kinocut.effects_engine import layout_grid
    from kinocut.engine_probe import probe
    from kinocut.server_tools_effects import video_layout_grid

    c1 = tmp_path / "c1.mp4"
    c2 = tmp_path / "c2.mp4"
    for clip, color in ((c1, "white"), (c2, "white")):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=320x240:r=10:d=0.4",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(clip),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

    out = tmp_path / "grid.mp4"
    layout_grid([str(c1), str(c2)], "2x2", str(out), gap=20, padding=30, background="#0000FF")
    info = probe(str(out))
    # 2 cols * 640 + 20 gap + 2*30 padding = 1360; 1 row * 480 + 2*30 padding = 540
    assert (info.width, info.height) == (1360, 540)

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(540, 1360, 3)
    # Outer padding pixel (5, 5) and gap pixel (y=270, x=30+640+10=680) must be blue (#0000FF).
    pad_px = frame[5, 5]
    gap_px = frame[270, 680]
    assert pad_px[2] > 180 and pad_px[0] < 40, pad_px
    assert gap_px[2] > 180 and gap_px[0] < 40, gap_px

    # Rejects unsafe/malformed background color via MCP surface too.
    bad = video_layout_grid([str(c1), str(c2)], "2x2", str(tmp_path / "bad.mp4"), background="red;movie=/etc/passwd")
    assert bad["success"] is False
    assert bad["error"]["code"] == "invalid_parameter"


# ---------------------------------------------------------------------------
# 7. C4-006: kinocut_sound.qa.build_metadata title validator fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_title",
    [
        "",
        "   ",
        "https://evil.example.com/secret/path",
        "/home/alice/private/episode",
        "x" * 200,
        "Title\nwith newline",
        "Tïtlé ✓ <script>",
        "'); DROP TABLE episodes; --",
        "123_starts_with_digit",
    ],
)
def test_sound_build_metadata_rejects_all_non_bounded_titles(bad_title: str) -> None:
    from kinocut_sound.qa import QaError, build_metadata

    with pytest.raises(QaError) as exc:
        build_metadata(title=bad_title, duration_seconds=60.0)
    assert exc.value.code == "qa_input_invalid"


def test_sound_build_metadata_accepts_bounded_titles() -> None:
    from kinocut_sound.qa import build_metadata

    m1 = build_metadata(title="Episode_One", duration_seconds=60.0)
    assert m1.title == "Episode_One"
    m2 = build_metadata(title="Episode One", duration_seconds=60.0)
    assert m2.title == "Episode One"


# ---------------------------------------------------------------------------
# 8. C2-014 + C2-010/C2-013: Cross-OS portability & Hyperframes hardening
# ---------------------------------------------------------------------------


def test_render_control_linux_hidepid_and_windows_portability(tmp_path: Path, monkeypatch) -> None:
    from kinocut.projectstore import render_control

    # Simulate /proc with one foreign PID raising PermissionError (hidepid=1) and one readable zombie.
    class FakeStat:
        def __init__(self, text=None, exc=None):
            self._text = text
            self._exc = exc

        def read_text(self):
            if self._exc is not None:
                raise self._exc
            return self._text

    class FakeProcEntry:
        def __init__(self, name, stat_obj):
            self.name = name
            self._stat = stat_obj

        def __truediv__(self, other):
            assert other == "stat"
            return self._stat

    class FakeProcRoot:
        def __init__(self, entries):
            self._entries = entries

        def iterdir(self):
            return iter(self._entries)

    entries = [
        FakeProcEntry("1", FakeStat(exc=PermissionError("hidepid"))),
        FakeProcEntry("2", FakeStat(exc=ProcessLookupError("ESRCH"))),
        FakeProcEntry("555", FakeStat(text="555 (worker) Z 1 555 555 0 -1")),
    ]
    monkeypatch.setattr(render_control, "Path", lambda _p: FakeProcRoot(entries))
    assert render_control._linux_group_quiescent(555) is True

    # If a live member exists alongside PermissionError, still returns False.
    live_entries = [
        FakeProcEntry("1", FakeStat(exc=PermissionError("hidepid"))),
        FakeProcEntry("555", FakeStat(text="555 (worker) S 1 555 555 0 -1")),
    ]
    monkeypatch.setattr(render_control, "Path", lambda _p: FakeProcRoot(live_entries))
    assert render_control._linux_group_quiescent(555) is False

    # Windows dispatch uses _windows_pid_quiescent instead of failing unconditionally.
    monkeypatch.setattr(render_control, "os", SimpleNamespace(name="nt", getpid=lambda: 10))
    monkeypatch.setattr(render_control, "_windows_pid_quiescent", lambda pid: pid == 999)
    assert render_control.group_quiescent(999) is True
    assert render_control.group_quiescent(888) is False
    assert render_control.stop_runner_group(999, lambda: False) == "stopped"


def test_cas_device_trusted_ctime_supports_overlay_btrfs_subvolume_darwin_and_windows(
    tmp_path: Path, monkeypatch
) -> None:
    from kinocut.projectstore import cas

    # 1) Overlayfs & btrfs subvolume path fallback on Linux mountinfo
    fake_mountinfo = (
        b"30 1 0:42 / / rw,relatime - overlay overlay rw\n"
        b"31 30 0:99 /@subvol /data/btrfs rw,relatime - btrfs /dev/sda1 rw\n"
        b"32 30 0:100 / /mnt/nfs rw,relatime - nfs4 server:/share rw\n"
    )
    monkeypatch.setattr(cas.sys, "platform", "linux")
    monkeypatch.setattr(cas.os, "name", "posix")
    monkeypatch.setattr(cas.os, "major", lambda _d: 0)
    monkeypatch.setattr(cas.os, "minor", lambda d: d)
    monkeypatch.setattr("builtins.open", lambda *_a, **_kw: io.BytesIO(fake_mountinfo))

    assert cas._device_has_trusted_ctime(42) is True  # overlay direct dev_id match
    # btrfs subvolume with synthetic 0:250 minor falls back to longest-prefix mountpoint
    monkeypatch.setattr(cas.os.path, "realpath", lambda p: str(p))
    assert cas._device_has_trusted_ctime(250, path=Path("/data/btrfs/proj/blob")) is True
    # NFS mount still rejected!
    assert cas._device_has_trusted_ctime(250, path=Path("/mnt/nfs/proj/blob")) is False

    # 2) Darwin dispatches to _darwin_has_trusted_ctime
    monkeypatch.setattr(cas.sys, "platform", "darwin")
    monkeypatch.setattr(cas, "_darwin_has_trusted_ctime", lambda p: p is not None)
    assert cas._device_has_trusted_ctime(1, path=tmp_path) is True

    # 3) Windows dispatches to _windows_has_trusted_ctime
    monkeypatch.setattr(cas.os, "name", "nt")
    monkeypatch.setattr(cas, "_windows_has_trusted_ctime", lambda p: p is not None)
    assert cas._device_has_trusted_ctime(1, path=tmp_path) is True


def test_hyperframes_runner_windows_guard_secret_blocklist_and_offline_npx_block(tmp_path: Path, monkeypatch) -> None:
    from kinocut.hyperframes import runner

    # 1) Windows terminate_process_group does not call os.killpg
    proc = MagicMock()
    proc.pid = 4321
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("hf", 5), 0]
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    runner.terminate_process_group(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()

    # Restore os for remaining checks
    monkeypatch.undo()

    # 2) Expanded secret blocklist strips credentials, proxies, and NODE_OPTIONS
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "false")
    leaked_vars = {
        "KINOCUT_VISION_API_KEY": "vis-secret",
        "HF_TOKEN": "hf_secret",
        "HUGGING_FACE_HUB_TOKEN": "hf_hub_secret",
        "AWS_ACCESS_KEY_ID": "AKIA123",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "AWS_SESSION_TOKEN": "aws-sess",
        "GITHUB_TOKEN": "ghp_secret",
        "GH_TOKEN": "ghp_secret2",
        "NPM_TOKEN": "npm_secret",
        "NODE_OPTIONS": "--require /tmp/hook.js",
        "HTTP_PROXY": "http://proxy.invalid:8080",
        "HTTPS_PROXY": "http://proxy.invalid:8080",
        "https_proxy": "http://proxy.invalid:8080",
        "ALL_PROXY": "socks5://proxy.invalid:1080",
    }
    for k, v in leaked_vars.items():
        monkeypatch.setenv(k, v)
    env = runner._hyperframes_environment()
    for k in leaked_vars:
        assert k not in env, f"{k} leaked into hyperframes subprocess env"

    # 3) Offline mode blocks npx / package manager resolvers at runtime
    monkeypatch.setenv("KINOCUT_OFFLINE", "1")
    monkeypatch.setenv("MCP_VIDEO_HYPERFRAMES_COMMAND", "npx --yes hyperframes")
    with pytest.raises(MCPVideoError) as exc:
        runner._run_hyperframes(["--version"], cwd=tmp_path)
    assert exc.value.code == "offline_network_blocked"


def test_process_observation_handles_seccomp_waitid_enosys_and_eperm(monkeypatch) -> None:
    from kinocut import process_observation

    monkeypatch.setattr(process_observation.sys, "platform", "linux")

    def raise_enosys(*_a, **_kw):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(process_observation.os, "waitid", raise_enosys)
    assert process_observation.supports_nonreaping_wait() is False

    def raise_eperm(*_a, **_kw):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(process_observation.os, "waitid", raise_eperm)
    assert process_observation.supports_nonreaping_wait() is False


def test_process_windows_handles_edr_injected_thread() -> None:
    from kinocut.process_windows import WindowsJob

    class EDRKernel:
        def __init__(self, suspend_counts: dict[int, int]):
            self.suspend_counts = suspend_counts
            self.tids = list(suspend_counts.keys())
            self._idx = 0
            self.resumed: list[int] = []

        def CreateJobObjectW(self, *_a):
            return 100

        def SetInformationJobObject(self, *_a):
            return 1

        def AssignProcessToJobObject(self, *_a):
            return 1

        def CreateToolhelp32Snapshot(self, *_a):
            return 200

        def Thread32First(self, _snap, entry):
            self._idx = 0
            if not self.tids:
                return 0
            entry._obj.owner_pid = 123
            entry._obj.thread_id = self.tids[0]
            return 1

        def Thread32Next(self, _snap, entry):
            self._idx += 1
            if self._idx >= len(self.tids):
                return 0
            entry._obj.owner_pid = 123
            entry._obj.thread_id = self.tids[self._idx]
            return 1

        def OpenThread(self, _rights, _inherit, tid):
            return 1000 + tid

        def ResumeThread(self, handle):
            tid = handle - 1000
            self.resumed.append(tid)
            return self.suspend_counts[tid]

        def CloseHandle(self, _h):
            return 1

    # Two threads: primary suspended (count=1) + EDR injected (count=0) -> succeeds!
    kernel = EDRKernel({456: 1, 789: 0})
    job = WindowsJob(kernel)
    job.attach(SimpleNamespace(pid=123, _handle=99))
    assert 456 in kernel.resumed

    # Two threads, neither suspended (counts 0 and 0) -> fails closed!
    bad_kernel = EDRKernel({456: 0, 789: 0})
    bad_job = WindowsJob(bad_kernel)
    with pytest.raises(MCPVideoError) as exc:
        bad_job.attach(SimpleNamespace(pid=123, _handle=99))
    assert exc.value.code == "process_ownership_unavailable"


def test_mix_process_portable_threaded_fallback_and_non_posix_guards(monkeypatch) -> None:
    from kinocut_sound.mix._errors import MixError
    from kinocut_sound.public import mix_process, mix_process_async

    # Exercise threaded fallback directly (identical to Windows path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1])"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        rc, out = mix_process._exchange_threaded(proc, b"kinocut", mix_process.time.monotonic() + 5.0, None, 1024)
        assert rc == 0
        assert out == b"tuconik"
    finally:
        mix_process._cleanup(proc)

    # Non-POSIX non-empty pass_fds fails cleanly in sync and async workers
    monkeypatch.setattr(mix_process.os, "name", "nt")
    with pytest.raises(MixError) as sync_exc:
        mix_process.run_worker_sync([sys.executable, "-c", "pass"], b"", (5,), timeout=5.0)
    assert sync_exc.value.code == "mix_worker_failed"

    monkeypatch.setattr(mix_process_async.os, "name", "nt")
    with pytest.raises(MixError) as async_exc:
        asyncio.run(mix_process_async.run_worker_async([sys.executable, "-c", "pass"], b"", (5,), timeout=5.0))
    assert async_exc.value.code == "mix_worker_failed"
