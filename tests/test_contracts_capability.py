"""``CapabilityReport`` and advisory-only ``NextAction`` (design §4.10, Task 6).

A capability report is a *structured* contract — closed availability state,
per-surface booleans, bounded capability/format/dependency codes — not free help
text. A next-action is advisory only: it carries at most one bounded, sanitized
command *template* that can never execute, plus the record ids blocking it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._errors import INVALID_RECORD, UNKNOWN_RECORD_FIELD
from kinocut.contracts.capability import (
    AvailabilityState,
    CapabilityReport,
    NextAction,
    SurfaceAvailability,
)
from kinocut.errors import MCPVideoError
from kinocut.receipts_ai_video import read_ai_video_section  # noqa: F401  (adapter smoke)

_SHA = "sha256:" + "0" * 64


_COHERENT_SURFACES = {
    "available": SurfaceAvailability(mcp=True, python=True, cli=True),
    "unavailable": SurfaceAvailability(mcp=False, python=False, cli=False),
    "degraded": SurfaceAvailability(mcp=True, python=False, cli=True),
}
_COHERENT_EVIDENCE = {
    "available": {"reason_code": None, "remediation": None},
    "unavailable": {"reason_code": "missing_dependency", "remediation": "Install ffmpeg and retry."},
    "degraded": {"reason_code": "slow_host", "remediation": "Retry on a faster host."},
}


def _report(**overrides) -> CapabilityReport:
    availability = overrides.get("availability", "available")
    data = {
        "capability_id": "inspect.temporal",
        "surfaces": _COHERENT_SURFACES[availability],
        "supported_formats": ("mp4", "mov"),
        "required_deps": ("ffmpeg",),
        "optional_deps": (),
        "availability": availability,
        **_COHERENT_EVIDENCE[availability],
    }
    data.update(overrides)
    return CapabilityReport(**data)


def test_capability_report_is_structured_not_help_text():
    report = _report()
    assert report.surfaces.mcp is True
    assert report.availability is AvailabilityState.AVAILABLE
    assert report.supported_formats == ("mp4", "mov")


def test_availability_states_are_closed():
    assert {s.value for s in AvailabilityState} == {"available", "unavailable", "degraded"}


def test_unavailable_requires_reason_code():
    with pytest.raises(ValidationError):
        _report(availability="unavailable", reason_code=None)
    ok = _report(
        availability="unavailable",
        reason_code="missing_dependency",
        remediation="Install ffmpeg and retry.",
        surfaces=SurfaceAvailability(mcp=False, python=False, cli=False),
    )
    assert ok.reason_code == "missing_dependency"


def test_available_must_not_carry_reason_code():
    with pytest.raises(ValidationError):
        _report(availability="available", reason_code="missing_dependency")


def test_capability_id_and_codes_are_bounded():
    with pytest.raises(ValidationError):
        _report(capability_id="not a code with spaces")
    with pytest.raises(ValidationError):
        _report(supported_formats=("mp4", "/etc/passwd"))
    with pytest.raises(ValidationError):
        _report(required_deps=("ffmpeg; rm -rf /",))


def test_remediation_rejects_host_paths_and_urls():
    with pytest.raises(ValidationError):
        _report(availability="degraded", reason_code="slow", remediation="see /Users/victim/notes for the fix")
    with pytest.raises(ValidationError):
        _report(availability="degraded", reason_code="slow", remediation="visit http://evil.test/fix")


def test_next_action_command_template_is_advisory_only():
    action = NextAction(
        action_code="ingest_first",
        summary="Ingest the source asset before verdict.",
        command_template="kino assets ingest --source <path>",
        blocking_record_ids=(),
    )
    assert action.command_template.startswith("kino ")  # advisory string only


def test_next_action_command_template_cannot_carry_a_real_path():
    with pytest.raises(ValidationError):
        NextAction(
            action_code="ingest_first",
            summary="do it",
            command_template="kino assets ingest --source /Users/victim/clip.mov",
        )
    with pytest.raises(ValidationError):
        NextAction(
            action_code="ingest_first", summary="do it", command_template="rm -rf /"
        )  # not a bounded kino template


def test_next_action_blocking_ids_are_hashes():
    action = NextAction(action_code="review_first", summary="Await review.", blocking_record_ids=(_SHA,))
    assert action.blocking_record_ids == (_SHA,)
    with pytest.raises(ValidationError):
        NextAction(action_code="review_first", summary="x", blocking_record_ids=("not-a-hash",))


def test_capability_and_next_action_reject_unknown_fields():
    with pytest.raises(ValidationError):
        _report(surprise=True)
    with pytest.raises(ValidationError):
        NextAction(action_code="x", summary="y", surprise=True)


def test_capability_report_via_adapter_maps_errors():
    from kinocut.contracts.adapter import validate_record

    good = validate_record(CapabilityReport, _report().model_dump(mode="json"))
    assert isinstance(good, CapabilityReport)
    bad = _report().model_dump(mode="json")
    bad["surprise"] = True
    with pytest.raises(MCPVideoError) as excinfo:
        validate_record(CapabilityReport, bad)
    assert excinfo.value.code == UNKNOWN_RECORD_FIELD
    worse = _report().model_dump(mode="json")
    worse["capability_id"] = "bad code!"
    with pytest.raises(MCPVideoError) as excinfo:
        validate_record(CapabilityReport, worse)
    assert excinfo.value.code == INVALID_RECORD


def test_surface_availability_booleans_are_strict():
    for bad in (1, 0, "true"):
        with pytest.raises(ValidationError):
            SurfaceAvailability(mcp=bad, python=True, cli=True)


def test_available_carries_neither_reason_nor_remediation():
    with pytest.raises(ValidationError):
        _report(availability="available", remediation="Install ffmpeg.")
    with pytest.raises(ValidationError):
        _report(availability="available", reason_code="missing_dependency")


def test_unavailable_requires_reason_and_remediation():
    with pytest.raises(ValidationError):
        _report(availability="unavailable", reason_code="missing_dependency", remediation=None)
    with pytest.raises(ValidationError):
        _report(availability="degraded", reason_code=None, remediation="Retry later.")
    ok = _report(availability="degraded", reason_code="slow_host", remediation="Retry on a faster host.")
    assert ok.remediation == "Retry on a faster host."


def test_duplicate_or_overlapping_dependency_codes_rejected():
    with pytest.raises(ValidationError):
        _report(required_deps=("ffmpeg", "ffmpeg"))
    with pytest.raises(ValidationError):
        _report(required_deps=("ffmpeg",), optional_deps=("ffmpeg",))  # overlap is ambiguous


def test_command_template_requires_a_placeholder():
    # A fully concrete, runnable command is rejected; only a template is advisory.
    with pytest.raises(ValidationError):
        NextAction(action_code="inspect", summary="Inspect it.", command_template="kino inspect")
    ok = NextAction(
        action_code="ingest_first", summary="Ingest first.", command_template="kino assets ingest --source <path>"
    )
    assert "<" in ok.command_template and ">" in ok.command_template


def test_next_action_exposes_no_execution_hook():
    action = NextAction(action_code="ingest_first", summary="Ingest first.")
    for hook in ("run", "execute", "__call__", "apply", "invoke"):
        assert not callable(getattr(action, hook, None))


def test_surface_state_coherence():
    all_true = SurfaceAvailability(mcp=True, python=True, cli=True)
    all_false = SurfaceAvailability(mcp=False, python=False, cli=False)
    mixed = SurfaceAvailability(mcp=True, python=False, cli=True)
    # available => all surfaces true
    with pytest.raises(ValidationError):
        _report(availability="available", surfaces=mixed)
    # unavailable => all surfaces false
    with pytest.raises(ValidationError):
        _report(availability="unavailable", surfaces=mixed)
    # degraded => mixed (neither all true nor all false)
    with pytest.raises(ValidationError):
        _report(availability="degraded", surfaces=all_true)
    with pytest.raises(ValidationError):
        _report(availability="degraded", surfaces=all_false)
    assert _report(availability="degraded", surfaces=mixed).surfaces.python is False


def test_reject_duplicate_supported_formats():
    with pytest.raises(ValidationError):
        _report(supported_formats=("mp4", "mp4"))


def test_reject_duplicate_blocking_record_ids():
    with pytest.raises(ValidationError):
        NextAction(action_code="review_first", summary="Await review.", blocking_record_ids=(_SHA, _SHA))


@pytest.mark.parametrize(
    "template",
    [
        "kino inspect",  # no placeholder
        "kino x <a> stray>",  # stray closing bracket
        "kino x <a><b>",  # adjacent, unseparated brackets
        "kino x <a>b",  # trailing chars glued to placeholder
        "kino x <>",  # empty placeholder name
        "kino x <A>",  # non-lowercase placeholder
    ],
)
def test_command_template_rejects_stray_or_missing_placeholders(template):
    with pytest.raises(ValidationError):
        NextAction(action_code="x", summary="do it", command_template=template)


def test_command_template_accepts_multiple_named_placeholders():
    ok = NextAction(action_code="x", summary="do it", command_template="kino render --in <src> --out <dst>")
    assert ok.command_template.count("<") == 2


def test_capability_contracts_are_exported():
    import kinocut.contracts as contracts

    for name in ("CapabilityReport", "NextAction", "SurfaceAvailability", "AvailabilityState"):
        assert getattr(contracts, name, None) is not None
        assert name in contracts.__all__
