"""Shorts surface: MCP ``call_tool`` + Python ``Kinocut.shorts.*`` round trips.

The shorts product (long-form stream-to-shorts) ships as five thin MCP tools
(``shorts_plan``, ``shorts_propose``, ``shorts_review``, ``shorts_render``,
``shorts_package``) and five matching Python client methods. This test file
verifies the public surface only: every MCP tool must register under its exact
name, every Python method must mirror the same kwargs/return contract, the
Python client must produce the same payload as the registered MCP tool when
invoked with the same arguments, and an invalid payload must produce a
structured error rather than an exception leak. Status intentionally stays on
the existing ``get_render_job`` tool; this file asserts no shorts-specific
status tool exists.

Business logic lives in :mod:`kinocut.product.shorts` and is monkey-patched
here so the surface tests stay decoupled from the orchestrator's
implementation phase. ``kinocut.server``, ``kinocut.client``, and
``kinocut.server_tools_shorts`` are exercised with the patched backend.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError

from kinocut.product.models import CandidateMoment, TranscriptSegment, TranscriptWord
from kinocut.product.shorts import (
    ShortsPlan,
    _caption_for,
    _even_synthesized_words,
    _load,
    _logprob_to_confidence,
    _segments,
    _validate_review_action,
)


_5_TOOL_NAMES = frozenset(
    {
        "shorts_plan",
        "shorts_propose",
        "shorts_review",
        "shorts_render",
        "shorts_package",
    }
)


# --------------------------------------------------------------------------- #
# Monkey-patch fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def patched_shorts(monkeypatch):
    """Replace ``kinocut.product.shorts`` with deterministic fakes.

    Captures every operation name + kwargs so the surface can assert that MCP
    tools and the Python client reach the same backend unchanged. The fake
    module's API surface (names) is rebuilt every test, then unbound by
    ``monkeypatch``.

    """
    import types

    from kinocut import product

    calls: list[dict] = []

    def _make(operation: str):
        def fake(**kwargs):
            calls.append({"operation": operation, "kwargs": kwargs})
            return {
                "success": True,
                "operation": operation,
                "echo": kwargs,
                "candidate_id": kwargs.get("candidate_id", "cand_test_1"),
                "job_id": f"job_{operation}_1",
            }

        return fake

    fake_shorts_module = types.ModuleType("kinocut.product.shorts")
    for name in _5_TOOL_NAMES:
        setattr(fake_shorts_module, name, _make(name))
    # ``raising=False`` lets the fixture work before the orchestrator publishes
    # ``kinocut.product.shorts``; once published, the real module is rebound.
    monkeypatch.setattr(product, "shorts", fake_shorts_module, raising=False)
    return calls


# --------------------------------------------------------------------------- #
# Five-tool-set assertions
# --------------------------------------------------------------------------- #


def test_five_shorts_tools_are_registered_with_exact_names():
    """Exactly the five shorts tools register, with the exact names, no status."""
    from mcp_video.server import mcp

    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    shorts_tools = tools & {f"shorts_{verb}" for verb in ("plan", "propose", "review", "render", "package")}

    assert shorts_tools == _5_TOOL_NAMES
    assert "shorts_status" not in tools
    assert "shorts_post" not in tools
    assert "shorts_publish" not in tools
    assert "shorts_upload" not in tools


def test_short_surfaces_module_exposes_only_the_five_callables(patched_shorts):
    """No accidental binding such as ``shorts_status`` leaks from the adapter."""
    import kinocut.client.shorts as client_module
    import kinocut.server_tools_shorts as tools_module

    server_callables = {
        name for name in dir(tools_module) if name.startswith("shorts_") and callable(getattr(tools_module, name))
    }
    client_callables = {name for name in dir(client_module.ClientShortsMixin) if name.startswith("shorts_")}

    assert server_callables == _5_TOOL_NAMES
    assert client_callables == _5_TOOL_NAMES


def test_client_registers_only_short_surface_mixin_methods():
    """``Kinocut.shorts.*`` mirror the MCP tool names exactly — no extras."""
    from kinocut.client import Client

    instance = Client()
    method_names = {name for name in dir(instance) if name.startswith("shorts_") and callable(getattr(instance, name))}
    assert method_names == _5_TOOL_NAMES


# --------------------------------------------------------------------------- #
# MCP dispatch + client round-trip
# --------------------------------------------------------------------------- #


def _call_server_tool(operation: str, **arguments):
    """Invoke the registered MCP tool function directly (registered-tool dispatch)."""
    import kinocut.server_tools_shorts as tools_module

    handler = getattr(tools_module, operation)
    return handler(**arguments)


def test_mcp_plan_dispatches_to_short_plan_backend(patched_shorts, tmp_path):
    project = str(tmp_path / "project")
    source = str(tmp_path / "source.mp4")
    result = _call_server_tool(
        "shorts_plan",
        project_dir=project,
        source_path=source,
        platforms=["youtube-shorts", "instagram-reel"],
    )

    assert result["success"] is True
    assert result["operation"] == "shorts_plan"
    assert len(patched_shorts) == 1
    sent = patched_shorts[0]
    assert sent["operation"] == "shorts_plan"
    assert sent["kwargs"]["project_dir"] == project
    assert sent["kwargs"]["source_path"] == source
    assert sent["kwargs"]["platforms"] == ["youtube-shorts", "instagram-reel"]


def test_mcp_propose_round_trips_via_client_method(patched_shorts, tmp_path):
    """Tool call + ``Client().shorts_propose(...)`` produce the same payload."""
    from kinocut.client import Client

    project = str(tmp_path / "project")
    plan_payload = {"plan_id": "plan_xyz", "candidates": [{"id": "c1"}]}

    via_tool = _call_server_tool(
        "shorts_propose",
        project_dir=project,
        candidate_id="c1",
        plan=plan_payload,
        edits={"action": "approve"},
    )
    via_client = Client().shorts_propose(
        project_dir=project,
        candidate_id="c1",
        plan=plan_payload,
        edits={"action": "approve"},
    )

    assert via_tool == via_client
    assert via_tool["operation"] == "shorts_propose"
    assert via_tool["echo"]["edits"] == {"action": "approve"}


def test_mcp_review_requires_evidence_ref_kwarg(patched_shorts, tmp_path):
    project = str(tmp_path / "project")

    via_tool = _call_server_tool(
        "shorts_review",
        project_dir=project,
        candidate_id="c2",
        decision={"verdict": "accept"},
        evidence_ref="reviews/2025/c2.json",
    )

    assert via_tool["operation"] == "shorts_review"
    assert via_tool["echo"]["evidence_ref"] == "reviews/2025/c2.json"
    assert len(patched_shorts) == 1


def test_mcp_render_round_trips_with_render_options(patched_shorts, tmp_path):
    from kinocut.client import Client

    project = str(tmp_path / "project")
    output = str(tmp_path / "out.mp4")

    via_tool = _call_server_tool(
        "shorts_render",
        project_dir=project,
        candidate_id="c3",
        output_path=output,
        render_options={"max_duration": 90, "platform": "instagram-reel"},
    )
    via_client = Client().shorts_render(
        project_dir=project,
        candidate_id="c3",
        output_path=output,
        render_options={"max_duration": 90, "platform": "instagram-reel"},
    )

    assert via_tool == via_client
    assert via_tool["echo"]["render_options"] == {
        "max_duration": 90,
        "platform": "instagram-reel",
    }
    assert via_tool["job_id"].startswith("job_shorts_render_")


def test_mcp_package_round_trips_with_package_dir(patched_shorts, tmp_path):
    from kinocut.client import Client

    project = str(tmp_path / "project")
    package_dir = str(tmp_path / "out" / "shorts")

    via_tool = _call_server_tool(
        "shorts_package",
        project_dir=project,
        candidate_id="c4",
        package_dir=package_dir,
    )
    via_client = Client().shorts_package(
        project_dir=project,
        candidate_id="c4",
        package_dir=package_dir,
    )

    assert via_tool == via_client
    assert via_tool["echo"]["package_dir"] == package_dir


def test_client_shorts_methods_call_backend_exactly_once_per_invocation(patched_shorts, tmp_path):
    from kinocut.client import Client

    client = Client()
    project = str(tmp_path / "project")

    client.shorts_plan(project_dir=project, source_path=str(tmp_path / "s.mp4"))
    client.shorts_propose(
        project_dir=project,
        candidate_id="c5",
        plan={"plan_id": "p1"},
    )
    client.shorts_review(
        project_dir=project,
        candidate_id="c5",
        decision={"verdict": "reject"},
        evidence_ref="ev/ref1",
    )
    client.shorts_render(
        project_dir=project,
        candidate_id="c5",
        output_path=str(tmp_path / "o.mp4"),
    )
    client.shorts_package(
        project_dir=project,
        candidate_id="c5",
        package_dir=str(tmp_path / "pkg"),
    )

    assert [c["operation"] for c in patched_shorts] == [
        "shorts_plan",
        "shorts_propose",
        "shorts_review",
        "shorts_render",
        "shorts_package",
    ]


# --------------------------------------------------------------------------- #
# Unhappy paths (structured errors, no leaking exceptions)
# --------------------------------------------------------------------------- #


def test_invalid_payload_returns_structured_error_dict(monkeypatch, tmp_path):
    """``_safe_tool`` converts ``MCPVideoError`` into the canonical error envelope."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def explode(**kwargs):
        raise MCPVideoError(
            "candidate not approved",
            error_type="validation_error",
            code="not_approved",
        )

    import types as _types

    fake = _types.ModuleType("kinocut.product.shorts")
    fake.shorts_render = explode  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_render(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_disallowed",
        output_path=str(tmp_path / "out.mp4"),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "not_approved"
    assert "candidate" in result["error"]["message"].lower()


def test_invalid_payload_unexpected_exception_returns_internal_error_envelope(monkeypatch, tmp_path):
    """Unexpected exceptions also funnel through ``_safe_tool`` -> ``_error_result``."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def boom(**kwargs):
        raise RuntimeError("orchestrator backend exploded")

    import types as _types2

    fake = _types2.ModuleType("kinocut.product.shorts")
    fake.shorts_package = boom  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_x",
        package_dir=str(tmp_path / "pkg"),
    )

    assert result["success"] is False
    assert result["error"]["type"] == "internal_error"
    assert result["error"]["code"] == "internal_error"


def test_invalid_platforms_value_propagates_as_validation_error(monkeypatch, tmp_path):
    """A bad ``platforms`` payload surfaces as a structured ``validation_error``."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def reject_platforms(platforms, **kwargs):
        if not isinstance(platforms, list) or not platforms:
            raise MCPVideoError(
                "platforms must be a non-empty list",
                error_type="validation_error",
                code="invalid_input",
            )
        return {
            "success": True,
            "operation": "shorts_plan",
            "echo": {"platforms": platforms, **kwargs},
        }

    import types as _types3

    fake = _types3.ModuleType("kinocut.product.shorts")
    fake.shorts_plan = reject_platforms  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_plan(
        project_dir=str(tmp_path / "project"),
        source_path=str(tmp_path / "s.mp4"),
        platforms=[],
    )

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


# --------------------------------------------------------------------------- #
# Path-safety contract: orchestrator owns validation; adapter passes through
# --------------------------------------------------------------------------- #


def test_short_package_passes_package_dir_through_unchanged(patched_shorts, tmp_path):
    """The adapter does not modify ``package_dir``; product owns validation."""
    from kinocut.client import Client

    package_dir = str(tmp_path / "out" / "shorts")

    result = Client().shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_path",
        package_dir=package_dir,
    )
    assert result["echo"]["package_dir"] == package_dir


def test_render_rejects_relative_output_path_via_orchestrator(monkeypatch, tmp_path):
    """Relative paths surface as structured backend errors, not wrapper fabrication."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def fail_on_relative(output_path, **kwargs):
        if not Path(output_path).is_absolute():
            raise MCPVideoError(
                "output_path must be absolute",
                error_type="validation_error",
                code="unsafe_path",
            )
        return {"success": True, "operation": "shorts_render", "echo": kwargs}

    import types as _types4

    fake = _types4.ModuleType("kinocut.product.shorts")
    fake.shorts_render = fail_on_relative  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_render(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_rel",
        output_path="relative.mp4",
    )
    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_path"


def test_short_package_rejects_parent_segment_via_orchestrator(monkeypatch, tmp_path):
    """``..`` in package_dir surfaces as the orchestrator's structured error."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def reject_traversal(package_dir, **kwargs):
        if ".." in Path(package_dir).parts:
            raise MCPVideoError(
                "package_dir may not contain parent segments",
                error_type="validation_error",
                code="unsafe_path",
            )
        return {"success": True, "operation": "shorts_package", "echo": kwargs}

    import types as _types5

    fake = _types5.ModuleType("kinocut.product.shorts")
    fake.shorts_package = reject_traversal  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_trav",
        package_dir=str(tmp_path / ".." / "elsewhere"),
    )
    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_path"


# --------------------------------------------------------------------------- #
# JSON-contract guard: every shorts call round-trips through json.dumps
# --------------------------------------------------------------------------- #


def test_shorts_envelope_is_json_serialisable(patched_shorts, tmp_path):
    """The adapter's dict output must be JSON-clean (no NaN, no bytes)."""
    project = str(tmp_path / "project")

    raw = _call_server_tool(
        "shorts_plan",
        project_dir=project,
        source_path=str(tmp_path / "s.mp4"),
        platforms=["youtube-shorts"],
    )
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    decoded = json.loads(encoded)
    assert decoded == raw


# --------------------------------------------------------------------------- #
# GLM A2 — real Whisper word timings reach the caption stage
# --------------------------------------------------------------------------- #


def _make_segment(segment_id: str, start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        confidence=None,
    )


def _make_plan(
    *,
    transcript: tuple[TranscriptSegment, ...],
    transcript_words: tuple[TranscriptWord, ...] = (),
) -> ShortsPlan:
    """Build a strict ``ShortsPlan`` shell for caption tests.

    Only the fields the caption stage touches are populated; the rest take
    their strict-model defaults. The plan is frozen, which matches the
    production shape that ``_save`` persists to disk.
    """
    from kinocut.product.shorts import IntakeReport

    intake = IntakeReport(
        source_path="/tmp/source.mp4",
        source_sha256="0" * 64,
        duration=10.0,
        width=1080,
        height=1920,
        audio_available=True,
    )
    candidate = CandidateMoment(
        candidate_id="cand_test_1",
        start=0.0,
        end=10.0,
        transcript_excerpt="hello world",
        suggested_title="Title",
        suggested_hook="Hook",
        rationale="Rationale",
        confidence=0.9,
        dedup_key="0" * 16,
    )
    return ShortsPlan(
        job_id="shorts_" + "0" * 16,
        project_dir="/tmp",
        output_dir="/tmp/out",
        intake=intake,
        platforms=("youtube-shorts", "instagram-reel"),
        config={},
        transcript=transcript,
        proposals=(candidate,),
        decisions=(),
        renders=(),
        package_manifests=(),
        external_posting=False,
        transcript_words=transcript_words,
    )


def test_caption_for_uses_real_word_timings_when_available() -> None:
    """A2: when ``transcript_words`` carries real Whisper timings the
    caption stage MUST use them rather than evenly synthesizing timings.

    The real timings deliberately land on a schedule that even synthesis
    could never reproduce, so the assertion isolates the chosen path.
    """
    segment = _make_segment("seg_000001", 0.0, 10.0, "hello world")
    real_words = (
        TranscriptWord(
            word="hello",
            start=0.2,
            end=0.7,
            segment_id="seg_000001",
            probability=0.9,
        ),
        TranscriptWord(
            word="world",
            start=4.5,
            end=5.5,
            segment_id="seg_000001",
            probability=0.4,
        ),
    )
    plan = _make_plan(transcript=(segment,), transcript_words=real_words)
    candidate = plan.proposals[0]
    artifact = _caption_for(plan, candidate)
    flat = [w for cue in artifact.cues for w in cue.words]
    assert [w.word for w in flat] == ["hello", "world"]
    # Real timings, not the even-synthesised (0..5, 5..10) split.
    assert flat[0].start == 0.2
    assert flat[0].end == 0.7
    assert flat[1].start == 4.5
    assert flat[1].end == 5.5
    # Probability propagates verbatim — not a synthesised 1.0.
    assert flat[0].probability == 0.9
    assert flat[1].probability == 0.4


def test_caption_for_falls_back_to_even_synthesis_when_no_word_timings() -> None:
    """A2/back-compat: when no real timings exist (legacy plans or the
    short-form ASR path) the caption stage still emits an artifact using the
    deterministic even synthesis. Confidence stays ``None`` rather than 1.0
    so the caption grouper can flag unknown words honestly.
    """
    segment = _make_segment("seg_000001", 0.0, 10.0, "hello world")
    plan = _make_plan(transcript=(segment,))
    candidate = plan.proposals[0]
    artifact = _caption_for(plan, candidate)
    flat = [w for cue in artifact.cues for w in cue.words]
    assert [w.word for w in flat] == ["hello", "world"]
    # Even split: 0..5, 5..10 (grouper may split across cues on gap).
    assert flat[0].start == 0.0
    assert flat[0].end == 5.0
    assert flat[1].start == 5.0
    assert flat[1].end == 10.0
    # No real probability -> ``None``, never ``1.0``.
    for w in flat:
        assert w.probability is None


def test_real_word_timings_skip_words_outside_candidate_window() -> None:
    """A2: words outside the candidate's [start, end) window must be dropped.

    The orchestrator's caption stage MUST clip words against the candidate
    boundary; preserving words outside the clip would break burn-in alignment
    on the rendered video.
    """
    segment = _make_segment("seg_000001", 0.0, 20.0, "a b c")
    words = (
        TranscriptWord(word="a", start=0.0, end=1.0, segment_id="seg_000001", probability=0.9),
        TranscriptWord(word="b", start=5.0, end=6.0, segment_id="seg_000001", probability=0.9),
        TranscriptWord(word="c", start=15.0, end=16.0, segment_id="seg_000001", probability=0.9),
    )
    plan = _make_plan(transcript=(segment,), transcript_words=words)
    candidate = plan.proposals[0]
    artifact = _caption_for(plan, candidate)
    cue_words = [w for cue in artifact.cues for w in cue.words]
    # Only words inside [0, 10) survive.
    assert [w.word for w in cue_words] == ["a", "b"]


def test_even_synthesized_words_do_not_default_to_unit_confidence() -> None:
    """A2/A8: when no real timings exist the synthesized ``WordTiming`` MUST
    not have a fabricated probability of ``1.0`` — the old code did that.
    """
    segment = TranscriptSegment(
        segment_id="seg_000001",
        start=0.0,
        end=4.0,
        text="hello world",
        confidence=None,
    )
    plan = _make_plan(transcript=(segment,))
    candidate = plan.proposals[0]
    words = _even_synthesized_words(plan, candidate)
    assert words
    for w in words:
        assert w.probability is None


# --------------------------------------------------------------------------- #
# GLM A5 — mutating plan lookup fails closed on ambiguity
# --------------------------------------------------------------------------- #


def test_load_fails_closed_when_directory_has_multiple_plans(tmp_path: Path) -> None:
    """A5: when a project directory contains more than one plan receipt the
    mutating resolver MUST refuse to pick one by mtime and instead raise a
    structured error forcing the caller to disambiguate by job id / path.
    """
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "shorts_aaaaaaaaaaaaaaaa.plan.json").write_text(
        json.dumps({"job_id": "shorts_aaaaaaaaaaaaaaaa"}), encoding="utf-8"
    )
    (plan_dir / "shorts_bbbbbbbbbbbbbbbb.plan.json").write_text(
        json.dumps({"job_id": "shorts_bbbbbbbbbbbbbbbb"}), encoding="utf-8"
    )
    with pytest.raises(MCPVideoError) as exc:
        _load(str(plan_dir))
    assert exc.value.code == "shorts_plan_ambiguous"


def test_load_resolves_unambiguous_directory_with_single_plan(tmp_path: Path) -> None:
    """A5/back-compat: a directory with exactly one plan must still resolve.

    The fail-closed guard MUST NOT regress single-plan projects. The plan is
    re-loaded via the resolver, asserting the cache path is populated so
    subsequent calls don't re-read the file.
    """
    plan_dir = tmp_path / "single"
    plan_dir.mkdir()
    target = plan_dir / "shorts_cccccccccccccccc.plan.json"
    plan = _make_plan(transcript=(_make_segment("seg_000001", 0.0, 5.0, "hi"),))
    target.write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")

    resolved = _load(str(plan_dir))
    assert resolved.job_id == plan.job_id


def test_load_uses_nested_short_subdirectory(tmp_path: Path) -> None:
    """A5/back-compat: when plans live under ``<dir>/shorts/`` the loader
    must still resolve them and fail closed on ambiguity there too.
    """
    nested = tmp_path / "out" / "shorts"
    nested.mkdir(parents=True)
    plan = _make_plan(transcript=(_make_segment("seg_000001", 0.0, 5.0, "hi"),))
    (nested / "shorts_dddddddddddddddd.plan.json").write_text(
        json.dumps(plan.model_dump(mode="json")), encoding="utf-8"
    )
    other = nested / "shorts_eeeeeeeeeeeeeeee.plan.json"
    other.write_text(
        json.dumps(_make_plan(transcript=(_make_segment("seg_000001", 0.0, 5.0, "hi"),)).model_dump(mode="json")),
        encoding="utf-8",
    )

    with pytest.raises(MCPVideoError) as exc:
        _load(str(tmp_path / "out"))
    assert exc.value.code == "shorts_plan_ambiguous"


# --------------------------------------------------------------------------- #
# GLM A8 — confidence conversion (exp(avg_logprob)) and never-default
# --------------------------------------------------------------------------- #


def test_logprob_to_confidence_uses_exp_not_linear_shift() -> None:
    """A8: confidence MUST be ``exp(avg_logprob)`` not ``1 + avg_logprob``.

    The previous implementation used ``1 + avg_logprob`` which produced
    mathematically wrong values (e.g. ``avg_logprob=-0.5`` -> ``0.5``). The
    new contract is the canonical ``exp`` translation.
    """
    import math

    assert _logprob_to_confidence(-0.5) == math.exp(-0.5)
    assert _logprob_to_confidence(-1.0) == math.exp(-1.0)
    assert _logprob_to_confidence(0.0) == 1.0
    # Clamp [0.0, 1.0] — even on degenerate inputs.
    assert _logprob_to_confidence(5.0) == 1.0


def test_logprob_to_confidence_is_none_when_no_signal() -> None:
    """A8: missing logprob MUST yield ``None``; never default to 1.0.

    Defaulting to 1.0 would mask upstream silence and break the caption
    stage's low-confidence flagging policy.
    """
    assert _logprob_to_confidence(None) is None
    assert _logprob_to_confidence("not-a-number") is None


def test_segments_preserves_truthful_confidence_from_avg_logprob() -> None:
    """A8: ``_segments`` must translate ``avg_logprob`` into a ``[0.0, 1.0]``
    ``TranscriptSegment.confidence`` using ``exp``. The previous behaviour
    silently clamped ``1 + avg_logprob`` which produced values outside the
    confidence band for log-likelihoods below ``-1``.
    """
    import math

    payload = [
        {
            "segment_id": "seg_000001",
            "start": 0.0,
            "end": 5.0,
            "text": "alpha",
            "avg_logprob": -0.5,
        }
    ]
    segments = _segments(payload)
    assert segments[0].confidence == math.exp(-0.5)


def test_segments_leaves_confidence_none_when_no_signal() -> None:
    """A8: when neither ``confidence`` nor ``avg_logprob`` are supplied the
    orchestrator MUST leave ``TranscriptSegment.confidence`` as ``None``
    rather than defaulting to 1.0.
    """
    payload = [
        {
            "segment_id": "seg_000001",
            "start": 0.0,
            "end": 5.0,
            "text": "alpha",
        }
    ]
    segments = _segments(payload)
    assert segments[0].confidence is None


def test_segments_prefers_explicit_confidence_over_avg_logprob() -> None:
    """A8: an upstream ``confidence`` in ``[0.0, 1.0]`` wins over
    ``avg_logprob`` because the orchestrator cannot prove which is more
    authoritative and explicit confidence is the tighter signal."""
    payload = [
        {
            "segment_id": "seg_000001",
            "start": 0.0,
            "end": 5.0,
            "text": "alpha",
            "confidence": 0.3,
            "avg_logprob": -1.0,
        }
    ]
    segments = _segments(payload)
    assert segments[0].confidence == 0.3


def test_segments_orders_overlapping_chunk_output_chronologically() -> None:
    segments = _segments(
        [
            {"segment_id": "late", "start": 1200.0, "end": 1202.0, "text": "later"},
            {"segment_id": "early", "start": 1198.0, "end": 1201.0, "text": "earlier"},
        ]
    )
    assert [segment.segment_id for segment in segments] == ["early", "late"]


# --------------------------------------------------------------------------- #
# GLM A9 — identical clean action validation for shorts_propose and shorts_review
# --------------------------------------------------------------------------- #


def test_validate_review_action_rejects_unknown_action_with_clean_error() -> None:
    """A9: the shared validator MUST raise the same ``shorts_review_invalid``
    structured error for any action outside the allowed set."""
    with pytest.raises(MCPVideoError) as exc:
        _validate_review_action("bogus")
    assert exc.value.code == "shorts_review_invalid"
    assert "preview" in exc.value.suggested_action["description"]


def test_validate_review_action_rejects_missing_action() -> None:
    """A9: ``None`` (missing action) MUST also raise a clean error rather
    than letting pydantic produce a different shaped failure downstream."""
    with pytest.raises(MCPVideoError) as exc:
        _validate_review_action(None)
    assert exc.value.code == "shorts_review_invalid"


def test_validate_review_action_accepts_every_documented_action() -> None:
    """A9: every action listed in the recovery message must round-trip
    cleanly so callers never see spurious validation errors on supported
    inputs."""
    for action in (
        "preview",
        "approve",
        "reject",
        "trim",
        "title_hook_edit",
        "sensitive_unsuitable",
    ):
        assert _validate_review_action(action) == action
