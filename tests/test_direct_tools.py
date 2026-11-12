"""Boundary tests mock transcription, never loading or downloading a model."""

import json
import subprocess

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    from kinocut import server_tools_direct as api

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(api, "probe", lambda _: {"duration": 120, "width": 1920, "height": 1080, "has_audio": True})
    return api, str(source), str(tmp_path / "out.mp4")


def test_direct_is_review_only_and_stable(api, tmp_path):
    tools, src, out = api
    first = tools.video_direct(src, "make it 30 seconds louder", output_path=out)
    assert first["success"]
    assert first["question"] is None
    assert first["assumptions"] == first["plan"]["assumptions"]
    assert first["plan_id"] == tools.video_direct(src, "make it 30 seconds louder", output_path=out)["plan_id"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.mp4"]


def test_default_output_chooses_a_free_name_on_a_second_plan(api):
    tools, src, _ = api
    first = tools.video_direct(src, "make it louder")
    assert first["success"]
    first_output = first["plan"]["output_path"]
    from pathlib import Path

    Path(first_output).write_bytes(b"first render")
    second = tools.video_direct(src, "make it louder")
    assert second["success"]
    assert second["plan"]["output_path"] != first_output


def test_voice_memo_only_when_text_is_empty(api, monkeypatch, tmp_path):
    tools, src, out = api
    from kinocut import ai_engine

    memo = tmp_path / "memo.wav"
    memo.write_bytes(b"audio")

    def transcribe(path, output_srt=None, model="base", language=None):
        assert path == str(memo)
        assert output_srt is None
        return {"transcript": "make it louder", "segments": [], "language": "en"}

    monkeypatch.setattr(ai_engine, "ai_transcribe", transcribe)
    result = tools.video_direct(src, "  ", audio_path=str(memo), output_path=out)
    assert result["transcript"] == "make it louder"
    assert [s["tool"] for s in result["plan"]["steps"]] == ["video_normalize_audio"]
    result = tools.video_direct(src, "thumbnail", audio_path=str(memo), output_path=out)
    assert "transcript" not in result


def test_direct_validates_paths(api):
    tools, src, _ = api
    assert not tools.video_direct(src + ".missing", "louder")["success"]
    assert not tools.video_direct(src, "louder", output_path="/etc/out.mp4")["success"]
    assert not tools.video_direct(src, "louder", audio_path="/missing.wav")["success"]


def test_dry_run_does_not_execute(api, monkeypatch):
    tools, src, out = api
    plan = tools.video_direct(src, "louder captions thumbnail", output_path=out)["plan"]
    monkeypatch.setattr(tools, "_run_step", lambda *_: pytest.fail("dry-run executed a tool"))
    result = tools.video_direct_apply(plan)
    assert result["success"] and result["dry_run"]
    assert result["step_count"] == 4
    assert result["receipts"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_tool",
        "traversal",
        "outside",
        "speed",
        "negative_speed",
        "nan",
        "bool",
        "length",
        "zero_length",
        "unexpected_arg",
        "input_traversal",
        "source_overwrite",
        "bad_final",
        "symlink",
        "bad_enum",
    ],
)
def test_edited_plan_is_rejected_before_any_step_runs(api, monkeypatch, tmp_path, mutation):
    tools, src, out = api
    plan = tools.video_direct(src, "30s faster louder", output_path=out)["plan"]
    # Change the later step to prove admission covers the entire plan before rendering.
    step = plan["steps"][1]
    if mutation == "unknown_tool":
        step["tool"] = "shell_exec"
    elif mutation == "traversal":
        step["args"]["output_path"] = str(tmp_path / ".." / "escape.mp4")
    elif mutation == "outside":
        step["args"]["output_path"] = "/etc/escape.mp4"
    elif mutation in {"speed", "negative_speed", "nan", "bool"}:
        plan["steps"][0]["args"]["factor"] = {"speed": 2.1, "negative_speed": 0.4, "nan": float("nan"), "bool": True}[
            mutation
        ]
    elif mutation in {"length", "zero_length"}:
        step["args"]["duration"] = 14401 if mutation == "length" else 0
    elif mutation == "unexpected_arg":
        step["args"]["filter_complex"] = "movie=/etc/passwd"
    elif mutation == "input_traversal":
        plan["input_path"] = str(tmp_path / "sub" / ".." / "source.mp4")
    elif mutation == "source_overwrite":
        step["args"]["output_path"] = src
    elif mutation == "bad_final":
        plan["output_path"] = str(tmp_path / "other.mp4")
    elif mutation == "symlink":
        link = tmp_path / "link.mp4"
        link.symlink_to(src)
        step["args"]["output_path"] = str(link)
    elif mutation == "bad_enum":
        step["tool"] = "video_resize"
        step["args"] = {"input_path": src, "output_path": out, "width": 1080, "height": 1920, "quality": "run rm -rf"}
    monkeypatch.setattr(tools, "_run_step", lambda *_: pytest.fail("invalid plan executed"))
    assert not tools.video_direct_apply(plan, confirm=True)["success"]


def test_confirm_requires_real_boolean(api):
    tools, src, out = api
    plan = tools.video_direct(src, "louder", output_path=out)["plan"]
    assert not tools.video_direct_apply(plan, confirm="false")["success"]


def test_stop_first_failure_preserves_receipts(api, monkeypatch):
    tools, src, out = api
    plan = tools.video_direct(src, "faster louder thumbnail", output_path=out)["plan"]

    def execute(name, args):
        if name == "video_speed":
            from pathlib import Path

            Path(args["output_path"]).write_bytes(b"edited")
            return {"success": True, "output_path": args["output_path"]}
        if name == "video_normalize_audio":
            return {"success": False, "error": {"message": "loudness failed"}}
        pytest.fail("executed past the first failure")

    monkeypatch.setattr(tools, "_run_step", execute)
    result = tools.video_direct_apply(plan, confirm=True)
    assert not result["success"]
    assert result["failed_step"] == 2
    assert len(result["receipts"]) == 2
    assert result["produced"] == [plan["steps"][0]["args"]["output_path"]]
    assert result["output_path"] == result["produced"][0]


def test_captions_no_speech_publish_planned_output_and_thumbnail_uses_actual_final(api, monkeypatch):
    tools, src, out = api
    from kinocut import ai_engine
    from pathlib import Path

    plan = tools.video_direct(src, "captions thumbnail", output_path=out)["plan"]
    monkeypatch.setattr(
        ai_engine, "ai_transcribe", lambda *a, **kw: {"transcript": "", "segments": [], "language": "en"}
    )

    def thumbnail(name, args):
        assert name == "video_thumbnail"
        assert args["input_path"] == src
        from pathlib import Path

        Path(args["output_path"]).write_bytes(b"jpg")
        return {"success": True, "frame_path": args["output_path"]}

    original = tools._run_step
    monkeypatch.setattr(
        tools,
        "_run_step",
        lambda name, args: original(name, args) if name == "video_ai_transcribe" else thumbnail(name, args),
    )
    result = tools.video_direct_apply(plan, confirm=True)
    assert result["success"]
    assert result["output_path"] == out
    assert result["produced"][-1] == out
    assert Path(out).read_bytes() == Path(src).read_bytes()
    assert result["receipts"][1]["skipped"] == "No speech was transcribed."


def test_captions_without_speech_still_publish_the_requested_output(api, monkeypatch):
    tools, src, out = api
    from kinocut import ai_engine
    from pathlib import Path

    plan = tools.video_direct(src, "captions", output_path=out)["plan"]
    monkeypatch.setattr(
        ai_engine, "ai_transcribe", lambda *a, **kw: {"transcript": "", "segments": [], "language": "en"}
    )
    result = tools.video_direct_apply(plan, confirm=True)
    assert result["success"]
    assert result["output_path"] == out
    assert Path(out).read_bytes() == Path(src).read_bytes()


def test_async_trim_receives_overwrite_consent_from_apply(api, monkeypatch):
    tools, src, out = api
    from kinocut import server_tools_basic
    from kinocut.output_policy import _OVERWRITE
    from pathlib import Path

    plan = tools.video_direct(src, "skip the first 1 second", output_path=out)["plan"]
    stale = Path(plan["steps"][0]["args"]["output_path"])
    stale.write_bytes(b"stale intermediate")

    async def trim(**args):
        assert _OVERWRITE.get() is True
        Path(args["output_path"]).write_bytes(b"new intermediate")
        return {"success": True, "output_path": args["output_path"]}

    monkeypatch.setattr(server_tools_basic, "video_trim", trim)
    blocked = tools.video_direct_apply(plan, confirm=True)
    assert not blocked["success"]
    assert blocked["error"]["code"] == "output_exists"
    assert not blocked.get("produced"), blocked
    result = tools.video_direct_apply(plan, confirm=True, overwrite=True)
    assert result["success"], result
    assert result["produced"] == [str(stale)]


def test_stale_intermediate_is_not_reported_as_produced(api, monkeypatch):
    tools, src, out = api
    from pathlib import Path

    plan = tools.video_direct(src, "skip the first 1 second and make it louder", output_path=out)["plan"]
    stale = Path(plan["steps"][0]["args"]["output_path"])
    stale.write_bytes(b"old intermediate")
    monkeypatch.setattr(
        tools,
        "_run_step",
        lambda *_: {"success": False, "error": {"code": "render_failed", "message": "failed"}},
    )
    result = tools.video_direct_apply(plan, confirm=True, overwrite=True)
    assert not result["success"]
    assert result["produced"] == []


def test_cli_direct_review_and_apply(api, capsys, monkeypatch):
    tools, src, out = api
    from kinocut.cli.parser import build_parser
    from kinocut.cli.handlers_direct import handle_direct_command

    args = build_parser().parse_args(["direct", "make it louder", "-i", src, "-o", out])
    assert handle_direct_command(args, use_json=True)
    result = json.loads(capsys.readouterr().out)
    assert result["plan"]["steps"][0]["tool"] == "video_normalize_audio"

    def apply(plan, confirm=False, overwrite=False):
        assert confirm is True
        assert overwrite is False
        return {"success": True, "output_path": out, "receipts": []}

    monkeypatch.setattr(tools, "video_direct_apply", apply)
    args = build_parser().parse_args(["direct", "louder", "-i", src, "-o", out, "--apply"])
    assert handle_direct_command(args, use_json=True)
    assert json.loads(capsys.readouterr().out)["output_path"] == out


def test_cli_direct_accepts_overwrite_after_command(api):
    _, src, _ = api
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(["direct", "skip the first 1 second", "-i", src, "--overwrite", "--apply"])
    assert args.overwrite is True


def test_cli_direct_passes_overwrite_to_apply(api, monkeypatch, capsys):
    tools, src, out = api
    from kinocut.cli.parser import build_parser
    from kinocut.cli.handlers_direct import handle_direct_command

    monkeypatch.setattr(tools, "video_direct", lambda *a, **kw: {"success": True, "plan": {}, "question": None})

    def apply(plan, confirm=False, overwrite=False):
        assert confirm is True
        assert overwrite is True
        return {"success": True, "output_path": out, "receipts": []}

    monkeypatch.setattr(tools, "video_direct_apply", apply)
    args = build_parser().parse_args(["direct", "louder", "-i", src, "-o", out, "--overwrite", "--apply"])
    assert handle_direct_command(args, use_json=True)
    assert json.loads(capsys.readouterr().out)["output_path"] == out


def test_end_to_end_silence_vertical_loudness(tmp_path, monkeypatch):
    from kinocut import server_tools_direct as tools
    from kinocut import ai_engine
    from kinocut.engine import probe

    monkeypatch.setattr(ai_engine, "ai_transcribe", lambda *a, **kw: pytest.fail("inference forbidden"))
    source = tmp_path / "gap.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10:d=1.9",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(between(t\\,0.5\\,1.3)\\,0\\,0.1*sin(2*PI*440*t)):s=48000:d=1.9",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = tools.video_direct(
        str(source), "cut the dead air make it vertical for tiktok and louder", output_path=str(tmp_path / "final.mp4")
    )
    assert result["success"]
    applied = tools.video_direct_apply(result["plan"], confirm=True)
    assert applied["success"], applied
    info = probe(applied["output_path"])
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration < 1.9
    assert [r["tool"] for r in applied["receipts"]] == [
        "video_ai_remove_silence",
        "video_resize",
        "video_normalize_audio",
    ]


def test_direct_maps_real_probe_no_audio(api, monkeypatch):
    tools, src, out = api
    from kinocut.models import VideoInfo

    monkeypatch.setattr(
        tools,
        "probe",
        lambda _: VideoInfo(path=src, duration=2, width=160, height=90, fps=10, codec="h264", audio_codec=None),
    )
    result = tools.video_direct(src, "louder captions", output_path=out)
    assert result["success"] and result["plan"]["steps"] == []


def test_real_caption_sidecar_from_mocked_speech(api, monkeypatch):
    tools, src, out = api
    from kinocut import ai_engine
    from pathlib import Path

    plan = tools.video_direct(src, "captions", output_path=out)["plan"]
    monkeypatch.setattr(
        ai_engine,
        "ai_transcribe",
        lambda *a, **kw: {
            "transcript": "Hello",
            "segments": [{"start": 0, "end": 1, "text": "Hello"}],
            "language": "en",
        },
    )
    original = tools._run_step

    def run(name, args):
        if name == "video_ai_transcribe":
            return original(name, args)
        assert name == "video_subtitles"
        assert "00:00:00,000 --> 00:00:01,000\nHello" in Path(args["subtitle_path"]).read_text()
        Path(args["output_path"]).write_bytes(b"captioned")
        return {"success": True, "output_path": args["output_path"]}

    monkeypatch.setattr(tools, "_run_step", run)
    result = tools.video_direct_apply(plan, confirm=True)
    assert result["success"] and result["output_path"] == out
    assert len(result["produced"]) == 2


def test_exception_still_reports_failed_step(api, monkeypatch):
    tools, src, out = api
    plan = tools.video_direct(src, "louder thumbnail", output_path=out)["plan"]

    def fail(*_):
        raise RuntimeError("worker failed")

    monkeypatch.setattr(tools, "_run_step", fail)
    result = tools.video_direct_apply(plan, confirm=True)
    assert not result["success"] and result["failed_step"] == 1
    assert result["produced"] == []


def test_cli_question_prevents_apply(api, monkeypatch, capsys):
    tools, src, out = api
    from kinocut.cli.parser import build_parser
    from kinocut.cli.handlers_direct import handle_direct_command

    monkeypatch.setattr(tools, "video_direct_apply", lambda *a, **kw: pytest.fail("unanswered question applied"))
    args = build_parser().parse_args(["direct", "vertical and square", "-i", src, "-o", out, "--apply"])
    handle_direct_command(args, use_json=True)
    assert json.loads(capsys.readouterr().out)["question"]


def test_cli_ambiguous_time_prevents_apply(api, monkeypatch, capsys):
    tools, src, out = api
    from kinocut.cli.parser import build_parser
    from kinocut.cli.handlers_direct import handle_direct_command

    monkeypatch.setattr(tools, "video_direct_apply", lambda *a, **kw: pytest.fail("unanswered question applied"))
    args = build_parser().parse_args(["direct", "make it 5 seconds shorter", "-i", src, "-o", out, "--apply"])
    handle_direct_command(args, use_json=True)
    assert json.loads(capsys.readouterr().out)["question"]


def test_successful_apply_removes_intermediate_video_renders(api, monkeypatch, tmp_path):
    tools, src, out = api
    from pathlib import Path

    plan = tools.video_direct(src, "skip the first 1 second and make it louder", output_path=out)["plan"]
    intermediate = Path(plan["steps"][0]["args"]["output_path"])

    def render(tool, args, current):
        Path(args["output_path"]).write_bytes(b"rendered")
        return {"success": True, "output_path": args["output_path"]}

    monkeypatch.setattr(tools, "_execute_step", render)
    result = tools.video_direct_apply(plan, confirm=True)

    assert result["success"]
    assert Path(out).is_file()
    assert not intermediate.exists()
    assert result["produced"] == [out]


def test_success_without_artifact_is_a_reported_failure(api, monkeypatch):
    tools, src, out = api
    plan = tools.video_direct(src, "louder", output_path=out)["plan"]
    monkeypatch.setattr(tools, "_run_step", lambda *a: {"success": True})
    result = tools.video_direct_apply(plan, confirm=True)
    assert not result["success"] and result["failed_step"] == 1
    assert result["produced"] == []


def test_default_output_is_disclosed(api):
    tools, src, _ = api
    result = tools.video_direct(src, "louder")
    assert result["plan"]["output_path"].endswith("source_direct.mp4")
    assert any("output" in a.lower() and "default" in a.lower() for a in result["assumptions"])


def test_emitted_tools_exist_and_accept_their_concrete_args():
    import asyncio
    import inspect
    from kinocut.direct import parse_direction, plan_direction
    from kinocut.direct.planner import ALLOWED_TOOLS
    from kinocut.server import mcp
    from kinocut.tool_discovery import discover_tools

    catalog = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert catalog.keys() >= ALLOWED_TOOLS
    plan = plan_direction(
        parse_direction("skip first 5 seconds tighten faster square keep face in frame louder captions mute thumbnail"),
        {"duration": 60, "width": 1920, "height": 1080},
    ).to_dict()
    for step in plan["steps"]:
        inspect.signature(mcp._tool_manager.get_tool(step["tool"]).fn).bind(**step["args"])
    assert "video_direct" in catalog and "video_direct_apply" in catalog
    result = discover_tools("spoken direction", [{"name": name} for name in catalog])
    assert result["tools"][0]["name"] == "video_direct"


def test_mcp_confirmation_cannot_be_coerced_from_a_string(api):
    import asyncio
    from kinocut.server import mcp

    tools, src, out = api
    plan = tools.video_direct(src, "louder", output_path=out)["plan"]
    rejected = asyncio.run(mcp.call_tool("video_direct_apply", {"plan": plan, "confirm": "true"}))
    assert getattr(rejected, "isError", False)
    assert rejected.structuredContent["error"]["code"] == "invalid_parameter"
