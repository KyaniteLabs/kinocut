"""Regression coverage for the Slice C artifact and render boundaries."""

from pathlib import Path
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError


@pytest.mark.parametrize("trusted", [None, "environment-browser"])
def test_bridge_browser_selection_ignores_job_settings(tmp_path, monkeypatch, trusted):
    from tests.test_revideo_format import _stub_bridge

    if trusted is None:
        monkeypatch.delenv("KINOCUT_REVIDEO_EXECUTABLE_PATH", raising=False)
    else:
        monkeypatch.setenv("KINOCUT_REVIDEO_EXECUTABLE_PATH", trusted)
    run = _stub_bridge(tmp_path, "private.mp4", job={"puppeteer": {"executablePath": "job-setting"}})
    assert run.returncode == 0, run.stderr
    options = json.loads(
        next(line.removeprefix("CAPTURE:") for line in run.stdout.splitlines() if line.startswith("CAPTURE:"))
    )
    assert options["settings"].get("puppeteer", {}).get("executablePath") == trusted


def test_session_rejects_invalid_updates_without_changing_file(tmp_path):
    from kinocut.te.edit_session import session_close, session_open, session_step

    path = Path(session_open(str(tmp_path), "goal")["path"])
    original = path.read_bytes()
    for score in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(MCPVideoError):
            session_step(str(path), action="edit", score=score)
        assert path.read_bytes() == original
    session_close(str(path))
    closed = path.read_bytes()
    with pytest.raises(MCPVideoError):
        session_step(str(path), action="edit", score=2)
    assert path.read_bytes() == closed


def test_temporal_boundary_uses_three_samples():
    from PIL import Image

    from kinocut.object_matte.temporal import median_window

    masks = [Image.new("L", (1, 1), value) for value in (255, 0, 255)]
    assert median_window(masks)[-1].getpixel((0, 0)) == 255


@pytest.mark.parametrize(("logit", "expected"), [(-30, 0), (30, 255)])
def test_flat_mask_preserves_confidence(logit, expected):
    import numpy as np

    from kinocut.object_matte.infer import postprocess

    assert postprocess(np.full((2, 2), logit), (2, 2)).getextrema() == (expected, expected)


def test_background_noise_is_not_stretched_to_opaque():
    import numpy as np

    from kinocut.object_matte.infer import postprocess

    mask = postprocess(np.array([[-10, -5]]), (2, 1))
    assert mask.getextrema()[1] < 2


def test_otio_rejects_remote_file_authority():
    from kinocut.multipliers.otio_io import _url_to_local_path

    assert _url_to_local_path("file://other.example/asset.mov") is None
    assert _url_to_local_path("file://localhost/a%20b.mov") == "/a b.mov"


@pytest.mark.parametrize("key", ["receipt_name", "contact_sheet_name"])
@pytest.mark.parametrize("bad", ["../outside.png", "/outside.png", "child/name.png", r"child\name.png", "symlink.png"])
def test_gate_requires_confined_output_names(tmp_path, key, bad):
    from PIL import Image

    from kinocut.still_plates.gate import still_gate

    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2)).save(source)
    (tmp_path / "symlink.png").symlink_to(source)
    before = source.read_bytes()
    with pytest.raises(MCPVideoError):
        still_gate(inputs=[source], output_dir=tmp_path, **{key: bad})
    assert source.read_bytes() == before
    assert not (tmp_path / "contact_sheet.png").exists()


def test_still_self_overwrite_and_duplicate_beats(tmp_path, overwrite_consent):
    from PIL import Image

    from kinocut.still_plates.gate import still_gate
    from kinocut.still_plates.package import still_package

    original = tmp_path / "shot.png"
    Image.new("RGB", (4, 4)).save(original)
    other = tmp_path / "shot.jpg"
    Image.new("RGB", (4, 4)).save(other)
    before = original.read_bytes()
    with pytest.raises(MCPVideoError, match="aliases an input"):
        still_gate(inputs=[original], output_dir=tmp_path, contact_sheet_name=original.name)
    with pytest.raises(MCPVideoError, match="stems"):
        still_package(establish=original, beats=[original, other], output_dir=tmp_path)
    assert original.read_bytes() == before
    assert not (tmp_path / "edits").exists()


def test_still_writers_validate_before_making_directories(tmp_path):
    import numpy as np

    from kinocut.still_plates.io import save_rgb_array, write_receipt

    parent = tmp_path / "unexpected" / ".." / "output"
    with pytest.raises(MCPVideoError):
        write_receipt(parent / "receipt.json", {})
    with pytest.raises(MCPVideoError):
        save_rgb_array(np.zeros((1, 1, 3)), parent / "still.png")
    assert list(tmp_path.iterdir()) == []


def test_review_writers_refuse_symlink_leaves(tmp_path):
    from kinocut.multipliers.review_ui import write_review_surface
    from kinocut.te.edit_session import session_close, session_open, session_step

    sentinel = tmp_path / "unrelated"
    sentinel.write_text("untouched")
    session = tmp_path / "session.json"
    session.symlink_to(sentinel)
    (tmp_path / "review.html").symlink_to(sentinel)
    for write in (
        lambda: session_open(str(tmp_path), "goal"),
        lambda: session_step(str(session), action="a"),
        lambda: session_close(str(session)),
        lambda: write_review_surface(str(tmp_path)),
    ):
        with pytest.raises(MCPVideoError):
            write()
    assert sentinel.read_text() == "untouched"


def test_generated_review_page_only_uses_safe_local_filenames(tmp_path):
    from kinocut.multipliers.review_ui import write_review_surface

    with pytest.raises(MCPVideoError):
        write_review_surface(str(tmp_path), timeline_name="../bad.json")
    result = write_review_surface(str(tmp_path), timeline_name="custom.json")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise generated review-page JavaScript")
    script = Path(result["html_path"]).read_text().split("<script>")[1].split("</script>")[0]
    setup = """const location = {search: process.argv[1]}; const playerNode = {};
    const document = {getElementById: key => key === 'player' ? playerNode : {}};
    const fetch = async url => {console.log(JSON.stringify([url.split('?')[0], playerNode.src || null])); return {json: async () => ({})};};
    const setInterval = () => {};"""
    for query, expected in [
        ("?timeline=https://remote.test/t&media=//remote.test/m", ["custom.json", None]),
        ("?timeline=%2e%2e%2foutside&media=a%5cfile", ["custom.json", None]),
        ("?timeline=local.json&media=clip.mp4", ["local.json", "clip.mp4"]),
    ]:
        run = subprocess.run([node, "-e", setup + script, query], capture_output=True, text=True, check=True)
        assert json.loads(run.stdout) == expected


@pytest.mark.parametrize("png_key", ["output_path", "background_output_path"])
def test_multiframe_png_refused_before_model_load(tmp_path, monkeypatch, png_key):
    from kinocut.object_matte import api, media

    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(api, "require_object_matte_deps", lambda: None)
    monkeypatch.setattr(api, "ensure_weights", lambda: pytest.fail("loaded the model"))
    monkeypatch.setattr(media, "refuse_overlong_video", lambda source: (30, 3, 16, 16))
    with pytest.raises(MCPVideoError, match="PNG"):
        api.run_object_matte(input_path=str(source), **{png_key: str(tmp_path / "out.png")})


def test_equipment_rejection_only_writes_diagnostic(tmp_path, monkeypatch):
    from PIL import Image

    from kinocut.object_matte import api, infer

    source, cut, hole = (tmp_path / name for name in ("source.png", "cut.png", "hole.png"))
    overlay = tmp_path / "new" / "overlay.png"
    Image.new("RGB", (4, 4)).save(source)
    monkeypatch.setattr(api, "require_object_matte_deps", lambda: None)
    monkeypatch.setattr(api, "ensure_weights", lambda: (None, True))
    monkeypatch.setattr(api, "make_session", lambda *_: (None, []))
    monkeypatch.setattr(infer, "infer_mask", lambda _, image: Image.new("L", image.size, 255))
    with pytest.raises(MCPVideoError) as error:
        api.run_object_matte(
            input_path=str(source),
            output_path=str(cut),
            background_output_path=str(hole),
            equipment_overlay=str(overlay),
            fail_if_equipment_on_subject=True,
        )
    assert error.value.code == "equipment_on_subject"
    assert overlay.is_file() and not cut.exists() and not hole.exists()


@pytest.mark.parametrize(
    "bad",
    [
        [None],
        [{"op": "resize", "params": []}],
        [{"op": "resize", "params": {"output_path": "out.mp4"}}],
        [{"op": "unknown"}],
    ],
)
def test_invalid_post_pipeline_never_starts_render(monkeypatch, bad):
    from kinocut import hyperframes_ops

    monkeypatch.setattr(hyperframes_ops, "render", lambda *a, **k: pytest.fail("render started"))
    with pytest.raises(MCPVideoError):
        hyperframes_ops.render_and_post("project", bad)


def test_release_recipe_redacts_invalid_payload(tmp_path):
    from kinocut.aivideo.release_surfaces import _run_recipe_capture
    from kinocut.projectstore import open_project

    project = open_project(tmp_path)
    with pytest.raises(MCPVideoError) as error:
        _run_recipe_capture(str(project.root), {"private_field": "private_value"})
    assert error.value.code == "invalid_workflow_recipe"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("state", ["rejected", "invalidated"])
def test_parallel_rejection_blocks_later_approval(tmp_path, state):
    from kinocut.aivideo.review import evaluate_publish_gate, record_approval_state
    from kinocut.contracts.review import ApprovalState
    from kinocut.projectstore import open_project
    from tests.contracts_fixtures import approval_state_kwargs
    from tests.test_review_gate_regressions import _approved, _ASSET

    project = open_project(tmp_path)
    record_approval_state(
        project,
        ApprovalState(**approval_state_kwargs(project_id=project.project_id, candidate_artifact=_ASSET, state=state)),
    )
    _approved(project)
    assert not evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable


def test_default_benchmark_preserves_probed_version(monkeypatch):
    from kinocut.aivideo import benchmark

    monkeypatch.setattr(
        benchmark, "run_diagnostics", lambda: {"checks": [{"name": "ffmpeg", "ok": True, "version": "fixture-version"}]}
    )
    assert benchmark.run_aivideo_benchmark().ffmpeg_version == "fixture-version"


@pytest.mark.parametrize("sensitive", [False, True])
def test_clearing_unsuitable_keeps_explicit_sensitivity(sensitive):
    from kinocut.product.shorts_plan import ReviewDecision
    from kinocut.product.shorts_review import _apply_review_decisions

    decisions = [
        ReviewDecision(candidate_id="clip", action="sensitive_unsuitable", **fields)
        for fields in ({"unsuitable": True}, {"sensitive": sensitive}, {"unsuitable": False})
    ]
    updates, _ = _apply_review_decisions(SimpleNamespace(decisions=decisions), "clip")
    assert updates == {"unsuitable": False, "sensitivity": "sensitive" if sensitive else "none"}


@pytest.mark.parametrize("audio_available", [True, False])
def test_shorts_render_discards_private_intermediates(tmp_path, monkeypatch, overwrite_consent, audio_available):
    from kinocut.product import shorts_render
    from kinocut.product.shorts_plan import load_shorts_plan, save_shorts_plan
    from kinocut.product.shorts_review import review_shorts_plan
    from tests.test_shorts_render import _plan, _stub

    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media fixture")
    plan_path = _plan(tmp_path, source)
    plan = load_shorts_plan(plan_path)
    save_shorts_plan(
        plan.model_copy(update={"intake": plan.intake.model_copy(update={"audio_available": audio_available})})
    )
    review_shorts_plan(plan_path, candidate_id="candidate_01", decision="approve")
    _stub(monkeypatch, source)
    scratch_dirs = []
    trim = shorts_render.trim

    def capture_trim(*args, output_path, **kwargs):
        scratch_dirs.append(Path(output_path).parent)
        return trim(*args, output_path=output_path, **kwargs)

    monkeypatch.setattr(shorts_render, "trim", capture_trim)
    if not audio_available:
        monkeypatch.setattr(shorts_render, "normalize_audio", lambda *a, **k: pytest.fail("normalized absent audio"))
        monkeypatch.setattr(shorts_render, "_run_ffmpeg", lambda *a, **k: pytest.fail("faded absent audio"))
    result = shorts_render.render_approved_candidate(plan_path, candidate_id="candidate_01")
    assert result["status"] == "rendered" and scratch_dirs
    assert all(not path.exists() for path in scratch_dirs)
    assert all(Path(item["output_path"]).is_file() for item in result["renders"])
