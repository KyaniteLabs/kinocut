"""Tests for the Hyperframes engine."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_video.hyperframes_engine import (
    _require_hyperframes_deps,
    _validate_project,
    add_block,
    benchmark,
    catalog,
    compositions,
    create_project,
    doctor,
    capture,
    info,
    inspect,
    preview,
    render,
    render_and_post,
    remove_background,
    snapshot,
    still,
    transcribe,
    tts,
    validate,
)
from mcp_video.errors import (
    HyperframesNotFoundError,
    HyperframesProjectError,
    HyperframesRenderError,
    MCPVideoError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Create a fake subprocess.CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=["npx", "hyperframes"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _hyperframes_subcommand(cmd: list[str]) -> str:
    return cmd[cmd.index("hyperframes") + 1]


def _mock_deps_ok():
    """Return a patcher that makes shutil.which find node and npx."""

    def _which(name: str):
        if name in ("node", "npx"):
            return f"/usr/bin/{name}"
        return None

    return patch("mcp_video.hyperframes_engine.shutil.which", side_effect=_which)


def _has_real_hyperframes_cli() -> bool:
    """Return True only when the no-install Hyperframes CLI path works."""
    try:
        result = subprocess.run(
            ["npx", "--yes", "--no-install", "hyperframes", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Test: _require_hyperframes_deps
# ---------------------------------------------------------------------------


class TestRequireHyperframesDeps:
    """Tests for _require_hyperframes_deps()."""

    @patch("mcp_video.hyperframes_engine.shutil.which", return_value=None)
    def test_raises_when_node_missing(self, mock_which):
        """Should raise HyperframesNotFoundError when node is not on PATH."""
        with pytest.raises(HyperframesNotFoundError, match="node not found"):
            _require_hyperframes_deps()
        mock_which.assert_called_with("node")

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_raises_when_npx_missing(self, mock_which):
        """Should raise HyperframesNotFoundError when npx is not on PATH."""

        def _which(name: str):
            if name == "node":
                return "/usr/bin/node"
            return None

        mock_which.side_effect = _which

        with pytest.raises(HyperframesNotFoundError, match="npx not found"):
            _require_hyperframes_deps()

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_passes_when_both_found(self, mock_which):
        """Should not raise when both node and npx are available."""

        def _which(name: str):
            return f"/usr/bin/{name}"

        mock_which.side_effect = _which

        _require_hyperframes_deps()  # should not raise

    def test_raises_with_correct_error_type(self):
        """HyperframesNotFoundError should have error_type='dependency_error'."""
        with patch("mcp_video.hyperframes_engine.shutil.which", return_value=None):
            with pytest.raises(HyperframesNotFoundError) as exc_info:
                _require_hyperframes_deps()
            assert exc_info.value.error_type == "dependency_error"
            assert exc_info.value.code == "hyperframes_not_found"


# ---------------------------------------------------------------------------
# Test: _validate_project
# ---------------------------------------------------------------------------


class TestValidateProject:
    """Tests for _validate_project()."""

    def test_raises_when_directory_missing(self, tmp_path):
        """Should raise HyperframesProjectError if directory does not exist."""
        missing = str(tmp_path / "nonexistent")
        with pytest.raises(HyperframesProjectError, match="Directory does not exist"):
            _validate_project(missing)

    def test_raises_when_no_html_entrypoint(self, tmp_path):
        """Should raise HyperframesProjectError when no HTML entry point is found."""
        with pytest.raises(HyperframesProjectError, match="entry point"):
            _validate_project(str(tmp_path))

    def test_returns_resolved_path_on_success(self, tmp_path):
        """Should return the resolved Path and entry point when project is valid."""
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html></html>")

        project_dir, entry_point = _validate_project(str(tmp_path))
        assert project_dir == tmp_path.resolve()
        assert isinstance(project_dir, Path)
        assert entry_point.name == "index.html"

    def test_finds_alternative_html_files(self, tmp_path):
        """Should find composition.html or demo.html as fallback."""
        (tmp_path / "demo.html").write_text("<!DOCTYPE html><html></html>")

        _project_dir, entry_point = _validate_project(str(tmp_path))
        assert entry_point.name == "demo.html"


# ---------------------------------------------------------------------------
# Test: render
# ---------------------------------------------------------------------------


class TestRender:
    """Tests for render()."""

    def test_builds_correct_cli_args(self, sample_hyperframes_project):
        """render() should invoke npx hyperframes with the right arguments."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="Rendered.")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run,
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024 * 1024),
        ):
            render(
                project,
                output_path="/tmp/out.mp4",
                fps=30,
                quality="standard",
                format="mp4",
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[0] == "npx"
            assert cmd[1:4] == ["--yes", "--no-install", "hyperframes"]
            assert "render" in cmd
            assert "/tmp/out.mp4" in cmd
            assert "--fps" in cmd
            idx = cmd.index("--fps")
            assert cmd[idx + 1] == "30"
            assert "--quality" in cmd
            idx = cmd.index("--quality")
            assert cmd[idx + 1] == "standard"

    def test_passes_all_optional_args(self, sample_hyperframes_project):
        """render() should forward render options supported by Hyperframes CLI."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="done")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run,
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=2 * 1024 * 1024),
        ):
            result = render(
                project,
                output_path="/tmp/out.mp4",
                fps=60,
                width=1080,
                height=1920,
                composition="compositions/intro.html",
                quality="high",
                format="webm",
                resolution="portrait",
                workers=4,
                crf=18,
            )

            assert result.output_path == "/tmp/out.mp4"
            assert result.codec == "webm"
            assert result.resolution == "1080x1920"
            cmd = mock_run.call_args[0][0]
            assert cmd[cmd.index("--composition") + 1] == "compositions/intro.html"
            assert cmd[cmd.index("--resolution") + 1] == "portrait"
            assert "--width" not in cmd
            assert "--height" not in cmd

    def test_raises_on_nonzero_exit(self, sample_hyperframes_project):
        """render() should raise HyperframesRenderError on non-zero exit."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(
            returncode=1,
            stderr="Something went wrong",
        )

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            pytest.raises(HyperframesRenderError, match="exit code 1"),
        ):
            render(project, output_path="/tmp/out.mp4")

    def test_sets_resolution_when_both_width_and_height(self, sample_hyperframes_project):
        """render() should map legacy 1920x1080 dimensions to Hyperframes resolution."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="ok")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run,
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
        ):
            result = render(
                project,
                output_path="/tmp/out.mp4",
                width=1920,
                height=1080,
            )
            assert result.resolution == "1920x1080"
            cmd = mock_run.call_args[0][0]
            assert cmd[cmd.index("--resolution") + 1] == "landscape"

    def test_rejects_unmapped_legacy_dimensions_instead_of_silent_noop(self, sample_hyperframes_project):
        """render() should not claim arbitrary dimensions that Hyperframes CLI cannot apply."""
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
            pytest.raises(MCPVideoError, match="only supports width/height pairs"),
        ):
            render(str(sample_hyperframes_project), output_path="/tmp/out.mp4", width=1280, height=720)

        mock_run.assert_not_called()

    def test_rejects_incomplete_legacy_dimensions(self, sample_hyperframes_project):
        """render() should not silently ignore a lone width or height."""
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
            pytest.raises(MCPVideoError, match="width and height must be provided together"),
        ):
            render(str(sample_hyperframes_project), output_path="/tmp/out.mp4", width=1920)

        mock_run.assert_not_called()

    def test_rejects_conflicting_dimensions_and_resolution(self, sample_hyperframes_project):
        """render() should not report dimensions that conflict with the requested preset."""
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
            pytest.raises(MCPVideoError, match="conflicts with resolution"),
        ):
            render(
                str(sample_hyperframes_project),
                output_path="/tmp/out.mp4",
                width=1920,
                height=1080,
                resolution="portrait",
            )

        mock_run.assert_not_called()

    def test_resolution_is_none_when_dimensions_missing(self, sample_hyperframes_project):
        """render() should return resolution=None when width/height are not set."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="ok")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
        ):
            result = render(
                project,
                output_path="/tmp/out.mp4",
            )
            assert result.resolution is None


# ---------------------------------------------------------------------------
# Test: compositions
# ---------------------------------------------------------------------------


class TestCompositions:
    """Tests for compositions()."""

    def test_parses_json_output(self, sample_hyperframes_project):
        """compositions() should parse JSON output from Hyperframes CLI."""
        project = str(sample_hyperframes_project)
        comp_json = json.dumps(
            [
                {
                    "id": "Main",
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "durationInFrames": 150,
                    "defaultProps": {"title": "Hello"},
                },
                {
                    "id": "Second",
                    "width": 1280,
                    "height": 720,
                    "fps": 60,
                    "durationInFrames": 300,
                },
            ]
        )
        fake_cp = _make_completed_process(stdout=comp_json)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            result = compositions(project)
            assert len(result.compositions) == 2
            assert result.compositions[0].id == "Main"
            assert result.compositions[0].width == 1920
            assert result.compositions[1].id == "Second"
            assert result.compositions[1].fps == 60

    def test_parses_single_composition_dict(self, sample_hyperframes_project):
        """compositions() should handle a single composition dict (not wrapped in a list)."""
        project = str(sample_hyperframes_project)
        comp_json = json.dumps(
            {
                "id": "Solo",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "durationInFrames": 90,
            }
        )
        fake_cp = _make_completed_process(stdout=comp_json)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            result = compositions(project)
            assert len(result.compositions) == 1
            assert result.compositions[0].id == "Solo"

    def test_parses_compositions_key_wrapper(self, sample_hyperframes_project):
        """compositions() should handle {"compositions": [...]} wrapper format."""
        project = str(sample_hyperframes_project)
        comp_json = json.dumps(
            {
                "compositions": [
                    {"id": "A", "width": 1920, "height": 1080, "fps": 30, "durationInFrames": 60},
                ]
            }
        )
        fake_cp = _make_completed_process(stdout=comp_json)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            result = compositions(project)
            assert len(result.compositions) == 1
            assert result.compositions[0].id == "A"

    def test_handles_invalid_json(self, sample_hyperframes_project):
        """compositions() should return empty list when JSON is invalid."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="not json at all")

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            result = compositions(project)
            assert result.compositions == []

    def test_raises_on_nonzero_exit(self, sample_hyperframes_project):
        """compositions() should raise HyperframesRenderError on failure."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(returncode=1, stderr="error")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            pytest.raises(HyperframesRenderError),
        ):
            compositions(project)

    def test_uses_composition_id_alias(self, sample_hyperframes_project):
        """compositions() should handle 'compositionId' key in JSON output."""
        project = str(sample_hyperframes_project)
        comp_json = json.dumps(
            [
                {"compositionId": "Alias", "width": 1280, "height": 720},
            ]
        )
        fake_cp = _make_completed_process(stdout=comp_json)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            result = compositions(project)
            assert result.compositions[0].id == "Alias"


# ---------------------------------------------------------------------------
# Test: preview
# ---------------------------------------------------------------------------


class TestPreview:
    """Tests for preview()."""

    def test_returns_url_with_correct_port(self, sample_hyperframes_project):
        """preview() should return a URL with the specified port."""
        project = str(sample_hyperframes_project)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.Popen", return_value=mock_proc):
            result = preview(project, port=3002)
            assert result.url == "http://localhost:3002"
            assert result.port == 3002

    def test_custom_port(self, sample_hyperframes_project):
        """preview() should accept a custom port."""
        project = str(sample_hyperframes_project)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.Popen", return_value=mock_proc):
            result = preview(project, port=8080)
            assert result.url == "http://localhost:8080"
            assert result.port == 8080

    def test_launches_popen_with_correct_command(self, sample_hyperframes_project):
        """preview() should launch npx hyperframes preview with --port."""
        project = str(sample_hyperframes_project)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            preview(project, port=3001)

            call_args = mock_popen.call_args
            cmd = call_args[0][0]
            assert cmd[0] == "npx"
            assert cmd[1:4] == ["--yes", "--no-install", "hyperframes"]
            assert "preview" in cmd
            assert "--port" in cmd
            idx = cmd.index("--port")
            assert cmd[idx + 1] == "3001"
            assert call_args.kwargs["stdout"] is subprocess.DEVNULL
            assert call_args.kwargs["stderr"] is subprocess.DEVNULL
            assert call_args.kwargs["start_new_session"] is True

    def test_raises_when_process_exits_immediately(self, sample_hyperframes_project):
        """preview() should raise HyperframesProjectError if the process crashes on startup."""
        project = str(sample_hyperframes_project)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.Popen", return_value=mock_proc),
            pytest.raises(HyperframesProjectError),
        ):
            preview(project, port=3002)


# ---------------------------------------------------------------------------
# Test: still
# ---------------------------------------------------------------------------


class TestStill:
    """Tests for still()."""

    def test_renders_single_frame(self, sample_hyperframes_project):
        """still() should render one snapshot frame with correct args."""
        project = Path(sample_hyperframes_project)
        actual = project / "snapshots" / "frame-00-at-1.4s.png"
        fake_cp = _make_completed_process(stdout="Rendered frame.")

        def fake_run(*_args, **_kwargs):
            actual.parent.mkdir(exist_ok=True)
            actual.write_bytes(b"png")
            return fake_cp

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", side_effect=fake_run) as mock_run:
            result = still(
                str(project),
                output_path="/tmp/frame.png",
                frame=42,
            )

            assert result.output_path == str(actual)
            assert result.frame == 42

            cmd = mock_run.call_args[0][0]
            assert "snapshot" in cmd
            assert "--at" in cmd
            idx = cmd.index("--at")
            assert cmd[idx + 1] == "1.4"


class TestSnapshot:
    """Tests for Hyperframes 0.5 snapshot path handling."""

    def test_returns_actual_snapshot_files(self, sample_hyperframes_project):
        project = Path(sample_hyperframes_project)
        snapshot_dir = project / "snapshots"
        snapshot_dir.mkdir()
        expected = snapshot_dir / "frame-00-at-0.0s.png"
        fake_cp = _make_completed_process(stdout="captured")

        def fake_run(*_args, **_kwargs):
            expected.write_bytes(b"png")
            return fake_cp

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", side_effect=fake_run):
            result = snapshot(str(project), frames=1)

        assert result.frame_paths == [str(expected)]
        assert result.output_dir == str(snapshot_dir)
        assert Path(result.frame_paths[0]).is_file()

    def test_builds_at_timestamps(self, sample_hyperframes_project):
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="captured")

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run:
            snapshot(project, at=[0.5, 1.25])

        cmd = mock_run.call_args[0][0]
        assert "snapshot" in cmd
        assert "--at" in cmd
        assert cmd[cmd.index("--at") + 1] == "0.5,1.25"

    def test_still_returns_actual_snapshot_path_not_requested_path(self, sample_hyperframes_project):
        project = Path(sample_hyperframes_project)
        snapshot_dir = project / "snapshots"
        snapshot_dir.mkdir()
        actual = snapshot_dir / "frame-00-at-0.0s.png"

        def fake_run(*_args, **_kwargs):
            actual.write_bytes(b"png")
            return _make_completed_process(stdout="captured")

        requested = str(project / "requested.png")
        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", side_effect=fake_run):
            result = still(str(project), output_path=requested, frame=0)

        assert result.output_path == str(actual)
        assert result.output_path != requested
        assert Path(result.output_path).is_file()


class TestHyperframes05Tools:
    """Tests for high-value Hyperframes 0.5 CLI wrappers."""

    def test_catalog_parses_json(self):
        payload = json.dumps([{"name": "tiktok-follow", "type": "block", "tags": ["social"]}])
        fake_cp = _make_completed_process(stdout=payload)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run:
            result = catalog(tag="social", item_type="block")

        assert result.items[0]["name"] == "tiktok-follow"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "npx"
        assert _hyperframes_subcommand(cmd) == "catalog"
        assert "--json" in cmd
        assert "--tag" in cmd
        assert cmd[cmd.index("--tag") + 1] == "social"
        assert "--type" in cmd
        assert cmd[cmd.index("--type") + 1] == "block"

    def test_inspect_returns_json_report(self, sample_hyperframes_project):
        payload = json.dumps({"issues": [], "samples": 3})
        fake_cp = _make_completed_process(stdout=payload)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run:
            result = inspect(str(sample_hyperframes_project), samples=3, strict=True)

        assert result.data["samples"] == 3
        cmd = mock_run.call_args[0][0]
        assert "inspect" in cmd
        assert "--json" in cmd
        assert "--samples" in cmd
        assert "--strict" in cmd

    def test_capture_forwards_url_and_json(self, tmp_path):
        payload = json.dumps({"projectPath": str(tmp_path / "captured")})
        fake_cp = _make_completed_process(stdout=payload)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run:
            result = capture("https://example.com", output=str(tmp_path / "captured"))

        assert result.data["projectPath"].endswith("captured")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "npx"
        assert _hyperframes_subcommand(cmd) == "capture"
        assert "https://example.com" in cmd
        assert "--json" in cmd

    def test_tts_and_transcribe_parse_json(self, tmp_path):
        tts_payload = json.dumps({"output": str(tmp_path / "speech.wav")})
        transcribe_payload = json.dumps({"words": [{"word": "hello", "start": 0.0}]})

        with (
            _mock_deps_ok(),
            patch(
                "mcp_video.hyperframes_engine.subprocess.run",
                side_effect=[
                    _make_completed_process(stdout=tts_payload),
                    _make_completed_process(stdout=transcribe_payload),
                ],
            ) as mock_run,
        ):
            speech = tts("hello", output_path=str(tmp_path / "speech.wav"), voice="af_heart")
            transcript = transcribe("/tmp/video.mp4", project_path=str(tmp_path), model="base.en")

        assert speech.data["output"].endswith("speech.wav")
        assert transcript.data["words"][0]["word"] == "hello"
        assert _hyperframes_subcommand(mock_run.call_args_list[0][0][0]) == "tts"
        assert _hyperframes_subcommand(mock_run.call_args_list[1][0][0]) == "transcribe"

    def test_tts_list_voices_does_not_require_text(self):
        payload = json.dumps({"voices": [{"id": "af_heart"}]})

        with (
            _mock_deps_ok(),
            patch(
                "mcp_video.hyperframes_engine.subprocess.run", return_value=_make_completed_process(stdout=payload)
            ) as mock_run,
        ):
            result = tts(list_voices=True)

        assert result.data["voices"][0]["id"] == "af_heart"
        cmd = mock_run.call_args[0][0]
        assert _hyperframes_subcommand(cmd) == "tts"
        assert "--list" in cmd
        assert "" not in cmd

    def test_tts_requires_text_unless_listing_voices(self):
        with pytest.raises(MCPVideoError, match="text_or_file is required"):
            tts()

    def test_remove_background_doctor_info_and_benchmark(self, sample_hyperframes_project):
        responses = [
            _make_completed_process(stdout=json.dumps({"output": "/tmp/cutout.webm"})),
            _make_completed_process(stdout=json.dumps({"version": "0.5.0"})),
            _make_completed_process(stdout=json.dumps({"name": "project"})),
            _make_completed_process(stdout=json.dumps({"runs": []})),
        ]

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", side_effect=responses) as mock_run:
            cutout = remove_background("/tmp/input.mp4", output_path="/tmp/cutout.webm")
            health = doctor()
            meta = info(str(sample_hyperframes_project))
            bench = benchmark(str(sample_hyperframes_project), runs=5, json_output=True)

        assert cutout.data["output"] == "/tmp/cutout.webm"
        assert health.data["version"] == "0.5.0"
        assert meta.data["name"] == "project"
        assert bench.data["runs"] == []
        assert [_hyperframes_subcommand(call[0][0]) for call in mock_run.call_args_list] == [
            "remove-background",
            "doctor",
            "info",
            "benchmark",
        ]
        benchmark_cmd = mock_run.call_args_list[-1][0][0]
        assert benchmark_cmd[benchmark_cmd.index("--runs") + 1] == "5"

    def test_raises_on_failure(self, sample_hyperframes_project):
        """still() should raise HyperframesRenderError on non-zero exit."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(returncode=1, stderr="still failed")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            pytest.raises(HyperframesRenderError, match="still failed"),
        ):
            still(project, output_path="/tmp/out.png")


# ---------------------------------------------------------------------------
# Test: create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    """Tests for create_project()."""

    def test_rejects_invalid_project_name_at_engine_boundary(self, tmp_path):
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=_make_completed_process()),
            pytest.raises(MCPVideoError, match="Invalid name"),
        ):
            create_project("../escape", output_dir=str(tmp_path))

    def test_rejects_invalid_output_dir_at_engine_boundary(self):
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=_make_completed_process()),
            pytest.raises(MCPVideoError, match="null bytes"),
        ):
            create_project("safe-name", output_dir="bad\x00dir")

    def test_runs_hyperframes_init(self, tmp_path):
        """create_project() should run npx hyperframes init with correct args."""
        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(stdout="initialized")

            create_project(
                "test-project",
                output_dir=str(tmp_path),
                template="blank",
                video="/tmp/source.mp4",
                audio="/tmp/source.wav",
                skip_transcribe=True,
                model="base.en",
                language="en",
                tailwind=True,
                resolution="portrait",
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[0] == "npx"
            assert cmd[1:4] == ["--yes", "--no-install", "hyperframes"]
            assert "init" in cmd
            assert "test-project" in cmd
            assert "--example" in cmd
            idx = cmd.index("--example")
            assert cmd[idx + 1] == "blank"
            assert cmd[cmd.index("--video") + 1] == "/tmp/source.mp4"
            assert cmd[cmd.index("--audio") + 1] == "/tmp/source.wav"
            assert "--skip-transcribe" in cmd
            assert cmd[cmd.index("--model") + 1] == "base.en"
            assert cmd[cmd.index("--language") + 1] == "en"
            assert "--tailwind" in cmd
            assert cmd[cmd.index("--resolution") + 1] == "portrait"
            assert "--non-interactive" in cmd

    def test_returns_project_result(self, tmp_path):
        """create_project() should return a HyperframesProjectResult."""
        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=_make_completed_process()),
        ):
            result = create_project("proj", output_dir=str(tmp_path), template="blank")
            assert result.template == "blank"
            assert "proj" in result.project_path


# ---------------------------------------------------------------------------
# Test: validate
# ---------------------------------------------------------------------------


class TestValidate:
    """Tests for validate()."""

    def test_detects_missing_directory(self, tmp_path):
        """validate() should report when project directory doesn't exist."""
        missing = str(tmp_path / "ghost")
        result = validate(missing)
        assert result.valid is False
        assert "does not exist" in result.issues[0]

    def test_detects_missing_html_entrypoint(self, tmp_path):
        """validate() should report missing HTML entry point."""
        with _mock_deps_ok():
            result = validate(str(tmp_path))
        assert result.valid is False
        assert any("HTML" in i or "entry point" in i for i in result.issues)

    def test_detects_missing_node(self, tmp_path):
        """validate() should report when Node.js is not on PATH."""
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html></html>")

        with patch("mcp_video.hyperframes_engine.shutil.which", return_value=None):
            result = validate(str(tmp_path))

        assert result.valid is False
        assert any("Node.js" in i for i in result.issues)
        assert any("npx" in i for i in result.issues)

    def test_valid_project(self, tmp_path):
        """validate() should return valid=True for a well-formed project."""
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html></html>")

        with (
            _mock_deps_ok(),
            patch(
                "mcp_video.hyperframes_engine._run_hyperframes",
                return_value=_make_completed_process(stdout='{"errors": [], "warnings": []}'),
            ),
        ):
            result = validate(str(tmp_path))

        assert result.valid is True
        assert result.issues == []

    def test_invalid_project_with_lint_errors(self, tmp_path):
        """validate() should mark invalid when lint reports errors."""
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html></html>")
        lint_json = '{"errors": ["missing data-composition-id"], "warnings": ["missing meta viewport"]}'

        with (
            _mock_deps_ok(),
            patch(
                "mcp_video.hyperframes_engine._run_hyperframes",
                return_value=_make_completed_process(returncode=1, stdout=lint_json),
            ),
        ):
            result = validate(str(tmp_path))

        assert result.valid is False
        assert any("composition-id" in i for i in result.issues)
        assert any("viewport" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Test: add_block
# ---------------------------------------------------------------------------


class TestAddBlock:
    """Tests for add_block()."""

    def test_adds_block_with_correct_args(self, sample_hyperframes_project):
        """add_block() should invoke npx hyperframes add with the block name."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout='{"files": ["blocks/test.tsx"]}')

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp) as mock_run:
            result = add_block(project, "claude-code-window", no_clipboard=True)

            assert result.block_name == "claude-code-window"
            assert "blocks/test.tsx" in result.files_added

            cmd = mock_run.call_args[0][0]
            assert "add" in cmd
            assert "claude-code-window" in cmd
            assert "--dir" in cmd
            assert "--no-clipboard" in cmd

    def test_raises_on_failure(self, sample_hyperframes_project):
        """add_block() should raise HyperframesRenderError on non-zero exit."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(returncode=1, stderr="block not found")

        with (
            _mock_deps_ok(),
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            pytest.raises(HyperframesRenderError),
        ):
            add_block(project, "nonexistent-block")


# ---------------------------------------------------------------------------
# Test: render_and_post
# ---------------------------------------------------------------------------


class TestRenderAndPost:
    """Tests for render_and_post()."""

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_chains_render_and_resize(self, mock_which, sample_hyperframes_project):
        """render_and_post() should render then apply resize."""

        def _which(name: str):
            if name in ("node", "npx"):
                return f"/usr/bin/{name}"
            if name in ("ffmpeg", "ffprobe"):
                return f"/usr/bin/{name}"
            return None

        mock_which.side_effect = _which

        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="rendered")

        mock_resize_result = MagicMock()
        mock_resize_result.output_path = "/tmp/resized.mp4"

        with (
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
            patch("mcp_video.engine.resize", return_value=mock_resize_result),
        ):
            result = render_and_post(
                project,
                post_process=[
                    {"op": "resize", "params": {"width": 640, "height": 480}},
                ],
                output_path="/tmp/resized.mp4",
            )

            assert result.operations == ["resize"]
            assert result.final_output == "/tmp/resized.mp4"
            assert result.hyperframes_output  # should be set from the render step

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_chains_multiple_operations(self, mock_which, sample_hyperframes_project):
        """render_and_post() should chain multiple post-processing ops."""

        def _which(name: str):
            if name in ("node", "npx", "ffmpeg", "ffprobe"):
                return f"/usr/bin/{name}"
            return None

        mock_which.side_effect = _which

        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="ok")

        mock_result = MagicMock()
        mock_result.output_path = "/tmp/final.mp4"

        with (
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
            patch("mcp_video.engine.convert", return_value=mock_result),
            patch("mcp_video.engine.add_audio", return_value=mock_result),
        ):
            result = render_and_post(
                project,
                post_process=[
                    {"op": "convert", "params": {"format": "webm"}},
                    {"op": "add_audio", "params": {"audio_path": "/tmp/audio.mp3"}},
                ],
            )

            assert result.operations == ["convert", "add_audio"]

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_unknown_operation(self, mock_which, sample_hyperframes_project):
        """render_and_post() should raise MCPVideoError for unknown operations."""

        def _which(name: str):
            if name in ("node", "npx"):
                return f"/usr/bin/{name}"
            return None

        mock_which.side_effect = _which

        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="ok")

        with (
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
            pytest.raises(MCPVideoError, match=r"Unknown post-processing operation.*nonexistent_op"),
        ):
            render_and_post(
                project,
                post_process=[
                    {"op": "nonexistent_op", "params": {}},
                ],
            )

    @patch("mcp_video.hyperframes_engine.shutil.which")
    def test_type_alias_for_op(self, mock_which, sample_hyperframes_project):
        """render_and_post() should accept 'type' key as alias for 'op'."""

        def _which(name: str):
            if name in ("node", "npx", "ffmpeg", "ffprobe"):
                return f"/usr/bin/{name}"
            return None

        mock_which.side_effect = _which

        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(stdout="ok")

        mock_result = MagicMock()
        mock_result.output_path = "/tmp/out.mp4"

        with (
            patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp),
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=1024),
            patch("mcp_video.engine.normalize_audio", return_value=mock_result),
        ):
            result = render_and_post(
                project,
                post_process=[
                    {"type": "normalize_audio", "params": {"target_lufs": -14}},
                ],
            )

            assert result.operations == ["normalize_audio"]


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_render_timeout(self, sample_hyperframes_project):
        """render() should raise HyperframesRenderError on timeout."""
        project = str(sample_hyperframes_project)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="npx", timeout=600)

            with pytest.raises(HyperframesRenderError, match="timed out"):
                render(project, output_path="/tmp/out.mp4")

    def test_render_npx_not_found(self, sample_hyperframes_project):
        """render() should raise HyperframesNotFoundError when npx binary is missing."""
        project = str(sample_hyperframes_project)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("npx not found")

            with pytest.raises(HyperframesNotFoundError, match="npx command not found"):
                render(project, output_path="/tmp/out.mp4")

    def test_render_error_has_command_and_returncode(self, sample_hyperframes_project):
        """HyperframesRenderError should carry command and returncode info."""
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(returncode=42, stderr="Bad error")

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            with pytest.raises(HyperframesRenderError) as exc_info:
                render(project, output_path="/tmp/out.mp4")

            err = exc_info.value
            assert err.returncode == 42
            assert "42" in err.code  # code should be hyperframes_exit_42

    def test_render_error_truncates_long_stderr(self, sample_hyperframes_project):
        """HyperframesRenderError should preserve full_stderr but truncate message."""
        long_stderr = "x" * 1000
        project = str(sample_hyperframes_project)
        fake_cp = _make_completed_process(returncode=1, stderr=long_stderr)

        with _mock_deps_ok(), patch("mcp_video.hyperframes_engine.subprocess.run", return_value=fake_cp):
            with pytest.raises(HyperframesRenderError) as exc_info:
                render(project, output_path="/tmp/out.mp4")

            assert exc_info.value.full_stderr == long_stderr
            assert len(str(exc_info.value)) < len(long_stderr) + 50  # message is truncated

    def test_missing_deps_before_project_validation(self):
        """All public functions should check deps before project validation."""
        with (
            patch("mcp_video.hyperframes_engine.shutil.which", return_value=None),
            pytest.raises(HyperframesNotFoundError),
        ):
            render("/some/project")

    def test_preview_missing_deps(self):
        """preview() should raise HyperframesNotFoundError when deps are missing."""
        with (
            patch("mcp_video.hyperframes_engine.shutil.which", return_value=None),
            pytest.raises(HyperframesNotFoundError),
        ):
            preview("/some/project")

    def test_still_missing_deps(self):
        """still() should raise HyperframesNotFoundError when deps are missing."""
        with (
            patch("mcp_video.hyperframes_engine.shutil.which", return_value=None),
            pytest.raises(HyperframesNotFoundError),
        ):
            still("/some/project")

    def test_create_project_missing_deps(self):
        """create_project() should raise HyperframesNotFoundError when deps are missing."""
        with (
            patch("mcp_video.hyperframes_engine.shutil.which", return_value=None),
            pytest.raises(HyperframesNotFoundError),
        ):
            create_project("test")


# ---------------------------------------------------------------------------
# Integration tests (require real Node.js)
# ---------------------------------------------------------------------------


@pytest.mark.hyperframes
@pytest.mark.skipif(
    not _has_real_hyperframes_cli(),
    reason="requires a locally installed Hyperframes CLI available via npx --no-install",
)
class TestHyperframesIntegration:
    """Integration tests that require a real Node.js/Hyperframes installation."""

    def test_require_hyperframes_deps_with_real_node(self):
        """Verify deps check passes with a real Node.js install."""
        _require_hyperframes_deps()  # should not raise

    def test_validate_real_project(self, tmp_path):
        """Validate a well-formed project structure."""
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html><div data-composition-id='test'></div></html>")
        result = validate(str(tmp_path))
        assert result.valid is True
