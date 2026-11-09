"""The type-name trust boundary: identity, not names.

A class's ``__name__`` is mutable, caller-controlled data; a numeric
subclass can override ``__repr__`` and ``__str__``. These tests pin the
Gate 18 repair at every layer:

* the shipped identity helpers never publish a caller-chosen name;
* the numeric rendering of a subclass is coerced to the builtin first;
* the retry placeholder cannot be spoofed by a renamed subclass;
* a foreign exception is the fixed ``<foreign-exception>`` label, by
  identity — even a subclass of our own error class is foreign;
* the provenance mark survives exactly what it wrapped, and concatenation
  downgrades it back to plain caller data;
* the analyzer's total ``__name__`` rule and the conditional
  ``own_reason`` rule catch what the helpers exist to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError, ValidationError, _argument_type, retry_context, retry_message
from kinocut.type_names import builtin_type_name, exception_kind, number_text, type_label
from kinocut.validation_errors import likely_cause, own_reason, reason, rejected_value
from kinocut_sound._validation_errors import rejected_value as sound_rejected_value
from kinocut_sound._validation_errors import exception_kind as sound_exception_kind

HOSTILE_NAME = "«redacted:dynamic-type»"
FOREIGN_NAME = "«redacted:foreign-exception»"


class Sneaky:
    __name__ = HOSTILE_NAME


class FakeStr(str):
    pass


FakeStr.__name__ = "str"


class HostileInt(int):
    def __repr__(self) -> str:  # pragma: no cover - must never be called
        return "sk-secret-repr"

    def __str__(self) -> str:  # pragma: no cover - must never be called
        return "sk-secret-str"


class ExplodingInt(int):
    def __int__(self) -> int:
        raise ValueError("sk-secret-int")


class HugeInt(int):
    def __int__(self) -> int:
        return 10**100


class CraftedError(Exception):
    pass


CraftedError.__name__ = FOREIGN_NAME


# --------------------------------------------------------------------------
# the identity helpers
# --------------------------------------------------------------------------


def test_rejected_value_never_publishes_a_caller_chosen_class_name() -> None:
    assert HOSTILE_NAME not in rejected_value(Sneaky())
    assert rejected_value(Sneaky()) == "<object>"


def test_rejected_value_publishes_shipped_categories() -> None:
    assert rejected_value("sk-secret") == "str"
    assert rejected_value(b"x") == "bytes"
    assert rejected_value([1]) == "list"
    assert rejected_value(True) == "bool"
    assert rejected_value(None) == "NoneType"


def test_rejected_value_repeats_only_builtin_numbers() -> None:
    assert rejected_value(30) == "30"
    assert rejected_value(1.5) == "1.5"


def test_a_numeric_subclass_cannot_override_its_rendering() -> None:
    assert "sk-secret" not in rejected_value(HostileInt(7))
    assert rejected_value(HostileInt(7)) == "7"


def test_a_failing_numeric_coercion_publishes_the_fixed_label() -> None:
    assert rejected_value(ExplodingInt(3)) == "<number>"


def test_an_overlong_numeric_coercion_publishes_the_fixed_label() -> None:
    assert rejected_value(HugeInt(1)) == "<number>"


def test_type_label_and_builtin_type_name_are_identity_keyed() -> None:
    assert type_label(Sneaky()) == "<object>"
    assert type_label(FakeStr("x")) == "<object>"
    assert type_label("x") == "str"
    assert builtin_type_name(Sneaky()) is None
    assert builtin_type_name("x") == "str"


def test_number_text_treats_subclasses_as_untrusted() -> None:
    assert number_text(HostileInt(9)) == "9"
    assert number_text("30") is None
    assert number_text(True) is None


# --------------------------------------------------------------------------
# the retry placeholder
# --------------------------------------------------------------------------


def test_a_renamed_subclass_cannot_spoof_a_shipped_placeholder_category() -> None:
    assert _argument_type(FakeStr("x")) == "<object>"
    assert _argument_type("x") == "<str>"
    assert _argument_type(1) == "<int>"
    assert _argument_type(None) == "<NoneType>"


def test_the_retry_message_never_carries_a_hostile_key_or_type_name() -> None:
    class HostileKey:
        def __str__(self) -> str:  # pragma: no cover - must never be called
            return HOSTILE_NAME

    with retry_context("video_edit", {HostileKey(): Sneaky()}):
        message = retry_message("refused", "invalid_parameter")
    assert HOSTILE_NAME not in message
    assert "<non-string-key>" in message
    assert "<object>" in message


# --------------------------------------------------------------------------
# exception kinds: identity, not inheritance
# --------------------------------------------------------------------------


def test_registered_exception_kinds_publish_their_names() -> None:
    assert exception_kind(ValueError("x")) == "ValueError"
    assert exception_kind(json.JSONDecodeError("x", "doc", 0)) == "JSONDecodeError"
    assert exception_kind(MCPVideoError("x")) == "MCPVideoError"
    assert exception_kind(ValidationError("field", "must be set")) == "ValidationError"


def test_a_foreign_exception_is_a_fixed_label_whatever_its_class_is_called() -> None:
    assert exception_kind(CraftedError("boom")) == "<foreign-exception>"
    assert FOREIGN_NAME not in exception_kind(CraftedError("boom"))


def test_a_subclass_of_our_own_error_is_foreign_by_identity() -> None:
    class OursSub(MCPVideoError):
        pass

    OursSub.__name__ = FOREIGN_NAME
    assert exception_kind(OursSub("x")) == "<foreign-exception>"


def test_the_sound_package_copy_holds_the_same_boundary() -> None:
    assert sound_rejected_value(Sneaky()) == "<object>"
    assert sound_rejected_value(HostileInt(5)) == "5"
    assert sound_exception_kind(CraftedError("x")) == "<foreign-exception>"
    assert sound_exception_kind(ValueError("x")) == "ValueError"


# --------------------------------------------------------------------------
# the provenance mark
# --------------------------------------------------------------------------


def test_a_marked_cause_survives_and_an_unmarked_cause_collapses() -> None:
    assert likely_cause(own_reason("the value is not a ShortsPlan instance.")) == (
        "the value is not a ShortsPlan instance."
    )
    assert likely_cause("/caller/path.mp4") == "str"


def test_concatenation_downgrades_the_mark_back_to_caller_data() -> None:
    concatenated = own_reason("package phrase") + "/caller/path"
    assert likely_cause(concatenated) == "str"


def test_the_foreign_exception_label_is_ours_to_mark() -> None:
    # The only sanctioned wrap of a foreign failure is its fixed label.
    assert likely_cause(own_reason(exception_kind(CraftedError("x")))) == "<foreign-exception>"


# --------------------------------------------------------------------------
# end-to-end: the reviewer's probes through the public adapter surface
# --------------------------------------------------------------------------


def test_the_stems_refusal_never_carries_a_hostile_class_name() -> None:
    from kinocut.server_tools_ai import video_ai_stem_separation

    result = video_ai_stem_separation(input_path="in.mp4", output_dir="out", stems=Sneaky())
    rendered = json.dumps(result, default=str)
    assert HOSTILE_NAME not in rendered
    assert "<object>" in rendered


def test_the_audio_sequence_refusal_names_a_non_numeric_at_by_category() -> None:
    from kinocut.server_tools_audio import audio_sequence

    result = audio_sequence(
        output_path="out.wav",
        sequence=[{"type": "tone", "at": Sneaky(), "params": {"frequency": 440}}],
    )
    rendered = json.dumps(result, default=str)
    assert HOSTILE_NAME not in rendered
    assert "<object>" in rendered


def test_the_shorts_plan_refusal_publishes_the_foreign_label_not_the_class_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kinocut.product import shorts_plan as plan_module
    from kinocut.product.shorts_plan import load_shorts_plan

    plan_file = tmp_path / "plan.json"
    plan_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        plan_module.ShortsPlan,
        "model_validate",
        staticmethod(lambda _p: (_ for _ in ()).throw(CraftedError("sk-secret"))),
    )

    with pytest.raises(MCPVideoError) as raised:
        load_shorts_plan(str(plan_file))
    message = str(raised.value)
    serialized = str(raised.value.to_dict())
    assert FOREIGN_NAME not in message
    assert FOREIGN_NAME not in serialized
    assert "<foreign-exception>" in message
    assert "sk-secret" not in serialized


# --------------------------------------------------------------------------
# the analyzer's rules: total __name__, conditional own_reason
# --------------------------------------------------------------------------


def _taint_of(source: str, tainted_names: set[str]) -> bool:
    """What the analyzer concludes about the first f-string field in a synthetic module."""
    import ast

    from tests.error_value_analysis import Function, _is_tainted_expr

    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    function = Function(Path("probe.py"), node)
    function.tainted.update(tainted_names)
    joined = next(candidate for candidate in ast.walk(node) if isinstance(candidate, ast.JoinedStr))
    field = next(part for part in joined.values if isinstance(part, ast.FormattedValue))
    return _is_tainted_expr(field.value, function)


def test_the_analyzer_flags_a_message_that_publishes_a_type_name() -> None:
    source = 'def refuse(value):\n    return f"got {type(value).__name__}"\n'
    assert _taint_of(source, {"value"}) is True


def test_the_analyzer_accepts_the_shipped_type_label_helper() -> None:
    source = 'def refuse(value):\n    return f"got {type_label(value)}"\n'
    assert _taint_of(source, {"value"}) is False


def test_the_analyzer_flags_caller_data_wrapped_in_the_provenance_mark() -> None:
    source = 'def refuse(value):\n    return f"cause: {own_reason(value)}"\n'
    assert _taint_of(source, {"value"}) is True


def test_the_analyzer_accepts_a_literal_wrapped_in_the_provenance_mark() -> None:
    # Single quotes inside the f-string: nested same-quote f-strings only parse on 3.12+.
    source = "def refuse(value):\n    return f\"cause: {own_reason('fixed phrase')}\"\n"
    assert _taint_of(source, {"value"}) is False


def test_the_analyzer_treats_the_cause_renderer_as_safe_on_any_input() -> None:
    source = 'def refuse(value):\n    return f"cause: {likely_cause(value)}"\n'
    assert _taint_of(source, {"value"}) is False


# --- Gate 19: the boundary closes its remaining edges ---------------------


def test_reason_rejects_a_hostile_mcpvideoerror_subclass() -> None:
    """reason() republishes by exact identity: a caller's subclass is foreign.

    A subclass of our own error class inherits nothing publishable — its
    name and text are its author's strings — so it is published only as
    the fixed foreign label, at the raised and the serialized layer.
    """

    class Sneaky(MCPVideoError):
        pass

    Sneaky.__name__ = "«redacted:sk-error»"
    hostile = Sneaky("«redacted:sk-text»")
    assert reason(hostile) == "<foreign-exception>"
    assert "«redacted:sk-error»" not in reason(hostile)
    assert "«redacted:sk-text»" not in json.dumps({"r": reason(hostile)})
    # The exact classes this package ships still republish.
    assert reason(MCPVideoError("Unknown preset.")) == "Unknown preset."


def test_likely_cause_rejects_a_provenance_marker_subclass() -> None:
    """Provenance is exact type plus private token, never isinstance."""
    from kinocut.validation_errors import PackageReason

    class Forged(PackageReason):
        def __str__(self) -> str:
            return "«redacted:sk-cause»"

    forged = Forged("«redacted:sk-cause»")
    assert likely_cause(forged) == "<object>"
    assert "«redacted:sk-cause»" not in likely_cause(forged)
    # A genuine mark still republishes verbatim.
    assert likely_cause(own_reason("the value is not a ShortsPlan instance.")) == (
        "the value is not a ShortsPlan instance."
    )


def test_a_numeric_subclass_whose_coercion_raises_stays_value_free() -> None:
    """Any coercion failure publishes <number> — including RuntimeError."""

    class Boom(int):
        def __int__(self) -> int:
            raise RuntimeError("«redacted:sk-int»")

    assert number_text(Boom(5)) == "<number>"
    from kinocut_sound._validation_errors import _number_text as sound_number_text

    assert sound_number_text(Boom(5)) == "<number>"


def test_the_exception_registry_has_no_public_mutator() -> None:
    """The registry is a closed anchor: no public name re-keys it."""
    import kinocut.type_names as type_names_module

    assert "register_exception_kinds" not in type_names_module.__all__

    class Foreign(Exception):
        pass

    Foreign.__name__ = "«redacted:sk-kind»"
    assert exception_kind(Foreign("x")) == "<foreign-exception>"
    assert "«redacted:sk-kind»" not in exception_kind(Foreign("x"))


def test_the_doctor_payload_names_a_renamed_foreign_exception_only_by_kind() -> None:
    """The MCP-server-import check publishes exception_kind, never __name__."""
    from kinocut.doctor import _check_mcp_server_import

    class Renamed(Exception):
        pass

    Renamed.__name__ = "«redacted:sk-import»"

    def exploding(name: str):
        raise Renamed("«redacted:sk-path»")

    check = _check_mcp_server_import(exploding)
    assert check["ok"] is False
    assert check["detail"] == "<foreign-exception>"
    assert "«redacted:sk-import»" not in str(check)
    assert "«redacted:sk-path»" not in str(check)


# --- Gate 20: keyword laundering, the sound copy's identity, total coercion ---


def test_the_analyzer_flags_a_keyword_formatted_caller_value() -> None:
    """`"{v}".format(v=value)` launders through a keyword the old scan missed."""
    source = "def refuse(value):\n    return f'cause: {\"{value}\".format(value=value)}'\n"
    assert _taint_of(source, {"value"}) is True


def test_the_analyzer_flags_a_format_map_caller_mapping() -> None:
    """`format_map(mapping)` carries the mapping's values into the message."""
    source = "def refuse(mapping):\n    return f\"cause: {'{x}'.format_map(mapping)}\"\n"
    assert _taint_of(source, {"mapping"}) is True


def test_the_analyzer_still_passes_a_literal_keyword_format() -> None:
    source = "def refuse(value):\n    return f\"cause: {'{x}'.format(x='fixed phrase')}\"\n"
    assert _taint_of(source, {"value"}) is False


def test_the_sound_reason_rejects_a_hostile_contract_subclass() -> None:
    """The sound copy republishes by exact identity, like the main package."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound._validation_errors import reason as sound_reason

    class Sneaky(SoundContractError):
        pass

    Sneaky.__name__ = "«redacted:sk-sound»"
    hostile = Sneaky("«redacted:sk-sound-text»", code="contract")
    assert sound_reason(hostile) == "<foreign-exception>"
    assert "«redacted:sk-sound»" not in sound_reason(hostile)
    assert "«redacted:sk-sound-text»" not in json.dumps({"r": sound_reason(hostile)})
    # The exact class still republishes.
    assert sound_reason(SoundContractError("contract refused", code="contract")) == "contract refused"


def test_a_base_exception_from_the_coercion_still_publishes_the_label() -> None:
    """The coercion catch is deliberately total: BaseException included."""
    import math

    class Halt(BaseException):
        pass

    class BoomBoom(int):
        def __int__(self) -> int:
            raise Halt("«redacted:sk-halt»")

    assert number_text(BoomBoom(5)) == "<number>"
    from kinocut_sound._validation_errors import _number_text as sound_number_text

    assert sound_number_text(BoomBoom(5)) == "<number>"
    # The total catch did not widen: ordinary values still render.
    assert number_text(math.pi) == repr(math.pi)
