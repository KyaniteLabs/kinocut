"""Determinism, sidecar boundary, and integration tests for the S8 world leaf.

Covers required row:
* deterministic same inputs yield same output hashes.

Plus architecture constraints:
* ``kinocut_sound/world/`` never imports any ``kinocut.*`` runtime module.
* World types reuse the stable S1-S4 contracts (AssetLicenseRef, etc.).
* No world module exceeds the 800-line ceiling; no function exceeds 80 lines.
"""

from __future__ import annotations

import ast
from pathlib import Path


import kinocut_sound.world as world

_WORLD_ROOT = Path(world.__file__).resolve().parent
_SHA = "sha256:" + "a" * 64


def test_deterministic_same_inputs_yield_same_output_hashes():
    from kinocut_sound.world import (
        AuditionContext,
        AuditionContract,
        AuditionRequest,
        SeamlessLoop,
        generate_loop,
    )

    # Loop digest: identical plans yield identical digests.
    plan_a = SeamlessLoop(
        loop_label="deterministic",
        source_duration_seconds=120.0,
        target_duration_seconds=900.0,
        crossfade_seconds=0.5,
    )
    plan_b = SeamlessLoop(
        loop_label="deterministic",
        source_duration_seconds=120.0,
        target_duration_seconds=900.0,
        crossfade_seconds=0.5,
    )
    assert generate_loop(plan_a).digest() == generate_loop(plan_b).digest()

    # Audition digest: identical requests yield identical digests.
    contract = AuditionContract()
    request = AuditionRequest(
        bed_id="bed_common_room",
        context=AuditionContext(
            reviewer_id="rev_1",
            project_id="proj",
            episode_id="ep",
        ),
        reel_label="reel",
    )
    assert contract.audition(request).digest() == contract.audition(request).digest()


def test_world_subpackage_does_not_import_kinocut_runtime():
    """Recursive AST scan: no world module imports ``kinocut.*`` (video runtime).

    The S1 sidecar boundary test scans only the flat ``kinocut_sound/*.py`` set;
    the world subpackage needs its own recursive scan so the S8 leaf does not
    smuggle a ``kinocut`` runtime import into a subdirectory.
    """

    offenders: dict[str, list[str]] = {}
    for module_path in sorted(_WORLD_ROOT.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        bad: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "kinocut" or node.module.startswith("kinocut."))
            ):
                bad.append(f"from {node.module} import ...")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut" or alias.name.startswith("kinocut."):
                        bad.append(f"import {alias.name}")
        if bad:
            offenders[module_path.name] = bad
    assert offenders == {}, "kinocut_sound.world must not import the kinocut runtime: " + repr(offenders)


def test_world_package_reuses_stable_contracts():
    """The world package reuses S1-S4 contracts rather than re-declaring them."""

    from kinocut_sound import AssetLicenseRef
    from kinocut_sound.world.catalog import CatalogAsset

    # CatalogAsset carries an AssetLicenseRef imported from the S1 contracts.
    fields = CatalogAsset.model_fields
    assert "license_ref" in fields
    # An actual AssetLicenseRef instance round-trips through CatalogAsset.
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    asset = CatalogAsset(
        asset_id="bed_reuse_check",
        kind=world.WorldAssetKind.BED,
        duration_seconds=10.0,
        license_ref=ref,
        provenance=world.AssetProvenance(content_hash=_SHA, source_ref="beds/check.wav"),
    )
    assert asset.license_ref == ref


def test_world_modules_stay_below_size_ceiling():
    """No world module exceeds the 800-line project ceiling."""

    oversized = {}
    for path in sorted(_WORLD_ROOT.glob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > 800:
            oversized[path.name] = line_count
    assert oversized == {}, f"world modules exceed 800 lines: {oversized}"


def test_world_functions_stay_below_function_ceiling():
    """No world function exceeds the 80-line function ceiling."""

    oversized = {}
    for path in sorted(_WORLD_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.end_lineno is not None
                and node.end_lineno - node.lineno + 1 > 80
            ):
                oversized[f"{path.name}:{node.name}"] = node.end_lineno - node.lineno + 1
    assert oversized == {}, f"world functions exceed 80 lines: {oversized}"


def test_world_public_exports_resolve_and_have_no_duplicates():
    seen: set[str] = set()
    dupes: list[str] = []
    for name in world.__all__:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    assert not dupes, f"duplicate __all__ entries: {dupes}"
    missing = [n for n in world.__all__ if not hasattr(world, n)]
    assert not missing, f"__all__ names not found on package: {missing}"


def test_world_does_not_redefine_centralized_constants():
    """World modules must not re-assign names owned by the central modules."""

    from tests.test_kinocut_sound_centralization import (
        _DEFAULTS_NAMES,
        _LIMITS_NAMES,
        _VALIDATION_NAMES,
    )

    forbidden = _VALIDATION_NAMES | _DEFAULTS_NAMES | _LIMITS_NAMES
    offenders: dict[str, list[str]] = {}
    for path in sorted(_WORLD_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assigned: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
        found = assigned & forbidden
        if found:
            offenders[path.name] = sorted(found)
    assert offenders == {}, "world modules re-define centralized constants: " + repr(offenders)


def test_world_error_payload_shape_is_stable():
    from kinocut_sound.world._errors import world_error_dict

    payload = world_error_dict("unknown_foley_cue", "fixture cue missing")
    assert payload == {
        "type": "validation_error",
        "code": "unknown_foley_cue",
        "message": "fixture cue missing",
        "suggested_action": {"auto_fix": False},
    }
