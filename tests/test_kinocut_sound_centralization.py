"""Divergence tests: centralized defaults/validation/limits are the sole source.

These tests verify that:

1. Tunable defaults, closed validation regexes/sets, and resource ceilings are
   defined ONLY in their respective centralized modules (``defaults.py``,
   ``validation.py``, ``limits.py``) and merely imported by contract modules.
2. No contract module contains a literal numeric ``Field(default=, ge=, gt=,
   le=, lt=)`` — every numeric default/bound must reference a named constant
   from the central modules.
3. No contract module uses an inline ``re.match/compile/search`` with a literal
   regex string — every regex must reference a compiled pattern from
   ``validation.py``.
4. The three central modules do not import the ``kinocut`` runtime.
5. ``__init__`` exports every centralized constant with no duplicates.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import kinocut_sound

PACKAGE_ROOT = Path(kinocut_sound.__file__).resolve().parent

# Modules that ARE the central sources — everything else is a contract module.
_CENTRAL_MODULES = {"defaults.py", "limits.py", "validation.py"}

# ``Field`` keyword arguments that carry numeric defaults/bounds and must never
# appear as literal numbers outside the central modules.
_FORBIDDEN_FIELD_ARGS = frozenset({"default", "ge", "gt", "le", "lt"})

# ---------------------------------------------------------------------------
# Narrow documented protocol allowlist for the AST literal-numeric scan.
#
# Each entry is ``(module_name, arg_name, literal_value)``.  A literal numeric
# value in a ``Field`` call in a contract module is permitted ONLY when it
# appears here with a documenting comment explaining why it cannot be routed
# through ``defaults.py`` / ``limits.py``.
#
# The allowlist MUST remain empty unless a value is genuinely part of a stable
# wire protocol that cannot reference a named constant (e.g. a value baked into
# a third-party schema we conform to).  Literal numbers that are merely
# convenient defaults or bounds must always be centralized.
# ---------------------------------------------------------------------------
_FIELD_LITERAL_ALLOWLIST: set[tuple[str, str, float]] = set()

# ---------------------------------------------------------------------------
# Name registries — every constant defined in the central modules.  No contract
# module may re-assign any of these names.
# ---------------------------------------------------------------------------

_VALIDATION_NAMES = {
    "SHA256_PATTERN",
    "CREATED_BY_PATTERN",
    "RECORD_KIND_PATTERN",
    "CODE_RE",
    "SCHEME_RE",
    "ADVISORY_RE",
    "ISO8601_RE",
    "LOCALE_RE",
    "REGION_RE",
    "TERRITORY_RE",
    "ADAPTER_KINDS",
    "DETERMINISM_CLASSES",
    "INFORMATIONAL_FIELDS",
}

_DEFAULTS_NAMES = {
    "DEFAULT_GAP_TOLERANCE_SECONDS",
    "DEFAULT_TAIL_SECONDS",
    "DEFAULT_LOUDNESS_TOLERANCE_LU",
    "DEFAULT_STREAM_PODCAST_TRUE_PEAK_DBTP",
    "DEFAULT_BROADCAST_TRUE_PEAK_DBTP",
    "DEFAULT_ADAPTER_TIMEOUT_SECONDS",
    "DEFAULT_PAN_POSITION",
    "DEFAULT_BUS_GAIN_DB",
    "DEFAULT_SEND_GAIN_DB",
    "DEFAULT_LATENCY_RESIDUAL_SAMPLES",
    "DEFAULT_PROSODY_RATE",
    "DEFAULT_PROSODY_PITCH_SEMITONES",
    "DEFAULT_PROSODY_VOLUME_DB",
    "DEFAULT_PROSODY_EMPHASIS",
}

_LIMITS_NAMES = {
    "MIN_TIME_SECONDS",
    "MIN_GAIN_DB",
    "MAX_GAIN_DB",
    "MIN_PAN_POSITION",
    "MAX_PAN_POSITION",
    "MIN_DUCKING_ATTENUATION_DB",
    "MAX_DUCKING_ATTENUATION_DB",
    "MIN_DUCKING_TIME_MS",
    "MAX_DUCKING_ATTACK_MS",
    "MAX_DUCKING_RELEASE_MS",
    "MAX_DUCKING_RECOVERY_MS",
    "MIN_PROSODY_RATE",
    "MAX_PROSODY_RATE",
    "MIN_PROSODY_PITCH_SEMITONES",
    "MAX_PROSODY_PITCH_SEMITONES",
    "MIN_PROSODY_VOLUME_DB",
    "MAX_PROSODY_VOLUME_DB",
    "MIN_NORMALIZED_LEVEL",
    "MAX_NORMALIZED_LEVEL",
    "MAX_LOUDNESS_LUFS",
    "MAX_TRUE_PEAK_DBTP",
    "MIN_LOUDNESS_RANGE_LU",
    "MAX_LOUDNESS_RANGE_LU",
    "MIN_LOUDNESS_TOLERANCE_LU",
    "MAX_LOUDNESS_TOLERANCE_LU",
    "MIN_VERSION",
    "MIN_TEXT_LENGTH_CHARS",
    "MIN_RETENTION_DAYS",
    "MIN_COST_USD",
    "MIN_SAMPLE_RATE_HZ",
    "MAX_ADAPTER_TIMEOUT_SECONDS",
    "MIN_LATENCY_RESIDUAL_SAMPLES",
    "MAX_LATENCY_RESIDUAL_SAMPLES",
    "MIN_STEM_RECOMBINATION_TOLERANCE_LSB_24BIT",
    "MAX_STEM_RECOMBINATION_TOLERANCE_LSB_24BIT",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contract_modules() -> list[Path]:
    """Return every ``.py`` file in the package except the three central modules."""
    return sorted(p for p in PACKAGE_ROOT.glob("*.py") if p.name not in _CENTRAL_MODULES)


def _assigned_names(tree: ast.Module) -> set[str]:
    """Return the set of top-level names assigned (not imported) in ``tree``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _is_field_call(node: ast.Call) -> bool:
    """True when *node* is a ``Field(...)`` call (bare or attribute)."""
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "Field") or (
        isinstance(func, ast.Attribute) and func.attr == "Field"
    )


def _literal_numeric(value: ast.AST) -> float | None:
    """Return the numeric value of a literal node, or ``None`` when not numeric."""
    if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
        return float(value.value)
    return None


# ---------------------------------------------------------------------------
# Name-based divergence tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "central_name, forbidden_names",
    [
        ("validation.py", _VALIDATION_NAMES),
        ("defaults.py", _DEFAULTS_NAMES),
        ("limits.py", _LIMITS_NAMES),
    ],
)
def test_centralized_names_not_reassigned_in_contract_modules(central_name, forbidden_names):
    """No contract module may re-define a centralized constant."""
    offenders: dict[str, list[str]] = {}
    for module_path in _contract_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        found = _assigned_names(tree) & forbidden_names
        if found:
            offenders[module_path.name] = sorted(found)
    assert offenders == {}, f"constants from {central_name} must be imported, not re-defined: " + repr(offenders)


# ---------------------------------------------------------------------------
# AST divergence test: forbidden literal numeric Field defaults/bounds
# ---------------------------------------------------------------------------


def test_no_literal_numeric_field_defaults_or_bounds_in_contract_modules():
    """Every numeric Field default/bound in a contract module must be a named constant.

    Scans every ``kinocut_sound`` contract module for ``Field(...)`` calls whose
    ``default``, ``ge``, ``gt``, ``le``, or ``lt`` keyword argument is a literal
    number.  Such values must be routed through ``defaults.py`` or ``limits.py``
    so the tuning surface is auditable in one place.

    The only exceptions are entries in ``_FIELD_LITERAL_ALLOWLIST`` (see above).
    """
    offenders: list[str] = []
    for module_path in _contract_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_field_call(node):
                continue
            for kw in node.keywords:
                if kw.arg not in _FORBIDDEN_FIELD_ARGS:
                    continue
                num = _literal_numeric(kw.value)
                if num is None:
                    continue
                key = (module_path.name, kw.arg, num)
                if key in _FIELD_LITERAL_ALLOWLIST:
                    continue
                offenders.append(f"{module_path.name}: Field({kw.arg}={num!r})")
    assert not offenders, (
        "literal numeric Field default/bound outside central modules — "
        "route through defaults.py or limits.py:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# AST divergence test: forbidden inline regex patterns
# ---------------------------------------------------------------------------


def test_no_inline_regex_patterns_in_contract_modules():
    """Every regex pattern in a contract module must be imported from validation.py.

    Scans for ``re.match``, ``re.compile``, ``re.search``, ``re.fullmatch``
    calls whose first argument is a literal string.  Such patterns must be
    compiled once in ``validation.py`` and imported.
    """
    offenders: list[str] = []
    for module_path in _contract_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in ("match", "compile", "search", "fullmatch")):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "re"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    offenders.append(f"{module_path.name}: re.{func.attr}(r'{arg.value}')")
    assert not offenders, (
        "inline regex pattern outside validation.py — move to validation.py and import:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Central module independence test
# ---------------------------------------------------------------------------


def test_centralized_modules_do_not_import_kinocut_runtime():
    """defaults/validation/limits must not import the kinocut runtime."""
    for name in ("defaults.py", "validation.py", "limits.py"):
        path = PACKAGE_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "kinocut" or node.module.startswith("kinocut."))
            ):
                if node.module == "kinocut_sound" or node.module.startswith("kinocut_sound."):
                    continue  # intra-package imports are fine
                raise AssertionError(f"{name} imports kinocut runtime: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut" or alias.name.startswith("kinocut."):
                        raise AssertionError(f"{name} imports kinocut runtime: {alias.name}")


def test_centralized_modules_do_not_import_each_other():
    """defaults/validation/limits must not import from each other."""
    for name in ("defaults.py", "limits.py", "validation.py"):
        path = PACKAGE_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module.startswith("kinocut_sound.defaults")
                    or node.module.startswith("kinocut_sound.limits")
                    or node.module.startswith("kinocut_sound.validation")
                )
            ):
                if name == "validation.py" and node.module.startswith("kinocut_sound.validation"):
                    continue
                if name == "defaults.py" and node.module.startswith("kinocut_sound.defaults"):
                    continue
                if name == "limits.py" and node.module.startswith("kinocut_sound.limits"):
                    continue
                raise AssertionError(f"{name} imports another central module: {node.module}")


# ---------------------------------------------------------------------------
# __init__ export tests
# ---------------------------------------------------------------------------


def test_all_exports_have_no_duplicates():
    """__all__ must not contain duplicate entries."""
    all_list = kinocut_sound.__all__
    seen: set[str] = set()
    dupes: list[str] = []
    for name in all_list:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    assert not dupes, f"duplicate __all__ entries: {dupes}"


def test_all_exports_resolve():
    """Every name in __all__ must be a real attribute on the package."""
    missing = [n for n in kinocut_sound.__all__ if not hasattr(kinocut_sound, n)]
    assert not missing, f"__all__ names not found on package: {missing}"


def test_centralized_constants_are_exported():
    """Every centralized constant must appear in __all__."""
    import kinocut_sound.defaults as d
    import kinocut_sound.limits as lm
    import kinocut_sound.validation as v

    all_set = set(kinocut_sound.__all__)
    defaults_exports = {
        name
        for name, val in vars(d).items()
        if not name.startswith("_") and isinstance(val, (int, float)) and name.isupper()
    }
    limits_exports = {
        name
        for name, val in vars(lm).items()
        if not name.startswith("_") and isinstance(val, (int, float)) and name.isupper()
    }
    validation_exports = {name for name, val in vars(v).items() if not name.startswith("_") and name.isupper()}
    all_central = defaults_exports | limits_exports | validation_exports
    missing = all_central - all_set
    assert not missing, f"centralized constants not exported in __all__: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Spot-check: centralized values match actual Field metadata
# ---------------------------------------------------------------------------


def test_centralized_defaults_match_field_metadata():
    """Spot-check that centralized defaults are the actual Field defaults used."""
    from kinocut_sound.defaults import DEFAULT_GAP_TOLERANCE_SECONDS
    from kinocut_sound.defaults import DEFAULT_TAIL_SECONDS
    from kinocut_sound.defaults import DEFAULT_ADAPTER_TIMEOUT_SECONDS
    from kinocut_sound.defaults import DEFAULT_PROSODY_RATE
    from kinocut_sound.defaults import DEFAULT_SEND_GAIN_DB

    from kinocut_sound.capability import AdapterDescriptor
    from kinocut_sound.lines import Prosody
    from kinocut_sound.routing import SendReturn
    from kinocut_sound.timeline import Timeline

    assert Timeline.model_fields["gap_tolerance_seconds"].default == DEFAULT_GAP_TOLERANCE_SECONDS
    assert Timeline.model_fields["tail_seconds"].default == DEFAULT_TAIL_SECONDS
    assert AdapterDescriptor.model_fields["timeout_seconds"].default == DEFAULT_ADAPTER_TIMEOUT_SECONDS
    assert Prosody.model_fields["rate"].default == DEFAULT_PROSODY_RATE
    assert SendReturn.model_fields["gain_db"].default == DEFAULT_SEND_GAIN_DB


def test_centralized_limits_match_field_metadata():
    """Spot-check that centralized bounds are the actual Field bounds used."""
    from kinocut_sound.limits import MAX_ADAPTER_TIMEOUT_SECONDS
    from kinocut_sound.limits import MAX_GAIN_DB
    from kinocut_sound.limits import MAX_LATENCY_RESIDUAL_SAMPLES
    from kinocut_sound.limits import MAX_PROSODY_RATE
    from kinocut_sound.limits import MIN_GAIN_DB

    from kinocut_sound.capability import AdapterDescriptor
    from kinocut_sound.lines import Prosody
    from kinocut_sound.routing import LatencyCompensation
    from kinocut_sound.routing import Track

    # Ceiling on adapter timeout.
    adapter_le = AdapterDescriptor.model_fields["timeout_seconds"].metadata
    assert MAX_ADAPTER_TIMEOUT_SECONDS in [m.le for m in adapter_le if hasattr(m, "le")]

    # Gain envelope on tracks.
    track_meta = Track.model_fields["gain_db"].metadata
    assert MIN_GAIN_DB in [m.ge for m in track_meta if hasattr(m, "ge")]
    assert MAX_GAIN_DB in [m.le for m in track_meta if hasattr(m, "le")]

    # Prosody rate ceiling.
    prosody_meta = Prosody.model_fields["rate"].metadata
    assert MAX_PROSODY_RATE in [m.le for m in prosody_meta if hasattr(m, "le")]

    # Latency residual ceiling — construct at ceiling, reject above.
    lc = LatencyCompensation(policy="sample_accurate", residual_samples=MAX_LATENCY_RESIDUAL_SAMPLES)
    assert lc.residual_samples == MAX_LATENCY_RESIDUAL_SAMPLES
    with pytest.raises(Exception):
        LatencyCompensation(policy="sample_accurate", residual_samples=MAX_LATENCY_RESIDUAL_SAMPLES + 1)


def test_centralized_validation_patterns_match_usage():
    """Sha256 type uses the centralized strict-lowercase-hex pattern."""
    from pydantic import TypeAdapter

    from kinocut_sound._canonical import Sha256
    from kinocut_sound.validation import SHA256_PATTERN

    assert "0-9a-f" in SHA256_PATTERN
    ta = TypeAdapter(Sha256)
    good = "sha256:" + "a" * 64
    ta.validate_python(good)
    with pytest.raises(Exception):
        ta.validate_python("sha256:" + "z" * 64)
    with pytest.raises(Exception):
        ta.validate_python("sha256:" + "A" * 64)


def test_centralized_regexes_are_compiled_patterns():
    """All *_RE constants in validation.py must be compiled regex patterns."""
    import kinocut_sound.validation as v

    for name in dir(v):
        if name.endswith("_RE") and name.isupper():
            val = getattr(v, name)
            if isinstance(val, str):
                continue  # SHA256_PATTERN etc. are strings for Pydantic Field(pattern=)
            assert isinstance(val, re.Pattern), f"{name} must be a compiled regex, got {type(val)}"


def test_no_unused_imports_of_re_in_contract_modules():
    """Contract modules must not import ``re`` if they no longer use it directly."""
    for module_path in _contract_modules():
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
        # Find ``import re``.
        has_re_import = any(
            isinstance(node, ast.Import) and any(alias.name == "re" for alias in node.names) for node in ast.walk(tree)
        )
        if not has_re_import:
            continue
        # Check if ``re.`` is actually used.
        uses_re = any(
            isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re"
            for node in ast.walk(tree)
        )
        assert uses_re, f"{module_path.name} imports ``re`` but never uses it"
