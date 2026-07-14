"""Deterministic receipt-bound text/logo/caption composition (Wave 5 Task 9)."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kinocut.aivideo.graphics_recipe import (
    GraphicsResult,
    compose_graphics_recipe,
    _mutation_intent,
)
from kinocut.aivideo.protection import (
    MutationOperation,
    mutation_fingerprint,
    protect,
    touched_dependencies,
)
from kinocut.contracts.protection import ProtectedElement
from kinocut.contracts.review import ReviewDecision
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, ingest_asset, open_project
from tests.contracts_fixtures import protection_kwargs, review_decision_kwargs


ROOT = Path(__file__).resolve().parents[1]
CHECKS_PATH = ROOT / "kinocut" / "aivideo" / "graphics_recipe_checks.py"
RECIPE_PATH = ROOT / "kinocut" / "aivideo" / "graphics_recipe.py"


def _module_assignments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _imports_from(path: Path, module_substr: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and module_substr in node.module
        for alias in node.names
    }


def _sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def font_path(tmp_path) -> str:
    source = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not source.is_file():
        pytest.skip("DejaVu font not installed")
    private_copy = tmp_path / "DejaVuSans.ttf"
    private_copy.write_bytes(source.read_bytes())
    return str(private_copy)


@pytest.fixture
def source(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    asset = ingest_asset(project, sample_video)
    return project, asset


@pytest.fixture
def logo_path(tmp_path) -> str:
    logo = tmp_path / "logo.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=64x48:duration=0.04",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(logo),
        ],
        check=True,
        capture_output=True,
    )
    return str(logo)


def _basic_layers(logo: str | None = None) -> list[dict]:
    layers: list[dict] = [
        {"kind": "text", "text": "HELLO", "color": "#FFFFFF", "size": 48, "position": {"x": 10, "y": 10}},
        {
            "kind": "caption",
            "text": "World",
            "color": "#FFFF00",
            "size": 36,
            "position": {"x": 10, "y": 420},
            "start": 0.0,
            "duration": 1.0,
        },
    ]
    if logo is not None:
        layers.append({"kind": "logo", "src": logo, "position": {"x": 560, "y": 10}, "width": 64, "height": 48})
    return layers


def _canvas() -> dict:
    return {"width": 320, "height": 240, "fps": 12, "duration": 1.0, "background": "#000000"}


def test_graphics_recipe_is_deterministic_and_idempotent(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    second = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )

    assert isinstance(first, GraphicsResult)
    assert second.recipe_hash == first.recipe_hash
    assert second.parameter_hash == first.parameter_hash
    assert second.font_hash == first.font_hash
    assert second.source_asset_hashes == first.source_asset_hashes
    assert second.output_hash == first.output_hash
    assert second.receipt_hash == first.receipt_hash
    assert second.asset.record_id == first.asset.record_id


def test_receipt_binds_source_font_output_and_receipt_hashes(source, font_path, logo_path):
    project, asset = source
    result = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=_basic_layers(logo_path),
        canvas=_canvas(),
    )
    assert asset.asset_id in result.source_asset_hashes
    assert result.font_hash == _sha(font_path)
    assert result.output_hash == result.asset.asset_id
    assert result.receipt_hash.startswith("sha256:")
    artifact = project.root / result.receipt_artifact_location
    assert artifact.is_file()
    assert _sha(artifact) == result.receipt_artifact_id
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["output_hash"] == result.output_hash
    assert payload["receipt_hash"] == result.receipt_hash
    assert payload["background_asset_id"] == asset.asset_id


@pytest.mark.parametrize("field", ["prompt", "model", "seed", "provider", "generator"])
def test_recipe_rejects_generative_fields(source, font_path, field):
    project, asset = source
    layers = [{"kind": "text", "text": "HI", field: "value", "position": {"x": 0, "y": 0}}]
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=layers,
            canvas=_canvas(),
        )
    assert exc.value.code == "invalid_graphics_layer"


def test_recipe_rejects_unknown_layer_kind(source, font_path):
    project, asset = source
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=[{"kind": "generated_overlay", "text": "x", "position": {"x": 0, "y": 0}}],
            canvas=_canvas(),
        )
    assert exc.value.code == "invalid_graphics_layer"


def test_recipe_rejects_logo_with_traversal(source, font_path):
    project, asset = source
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=[{"kind": "logo", "src": "../../etc/passwd", "position": {"x": 0, "y": 0}}],
            canvas=_canvas(),
        )
    assert exc.value.code == "invalid_graphics_layer"


def test_recipe_rejects_text_layer_with_empty_text(source, font_path):
    project, asset = source
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=[{"kind": "text", "text": "   ", "position": {"x": 0, "y": 0}}],
            canvas=_canvas(),
        )
    assert exc.value.code == "invalid_graphics_layer"


def test_recipe_fails_closed_on_source_substitution(source, font_path, logo_path, monkeypatch):
    import kinocut.aivideo.graphics_recipe as gr

    project, asset = source
    original = gr._verified_file_copy

    def mutate_then_copy(src, dst, expected_hash):
        Path(src).write_bytes(b"substituted after authorization")
        return original(src, dst, expected_hash)

    monkeypatch.setattr(gr, "_verified_file_copy", mutate_then_copy)
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=_basic_layers(logo_path),
            canvas=_canvas(),
        )
    assert exc.value.code == "graphics_source_changed"
    assert exc.value.error_type == "integrity_error"


def test_recipe_fails_closed_on_font_substitution(source, font_path, logo_path, monkeypatch):
    import kinocut.aivideo.graphics_recipe as gr

    project, asset = source
    original = gr._verified_file_copy
    call_count = [0]

    def mutate_font_on_second_call(src, dst, expected_hash):
        call_count[0] += 1
        if call_count[0] == 1:
            Path(src).write_bytes(b"not a font anymore")
        return original(src, dst, expected_hash)

    monkeypatch.setattr(gr, "_verified_file_copy", mutate_font_on_second_call)
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=_basic_layers(logo_path),
            canvas=_canvas(),
        )
    assert exc.value.code == "graphics_source_changed"


def test_user_text_with_ffmpeg_special_chars_renders_deterministically(source, font_path):
    project, asset = source
    tricky = "50%{off} semi:colon 'quote' back\\slash"
    layers = [{"kind": "text", "text": tricky, "position": {"x": 10, "y": 10}}]
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    second = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    assert first.output_hash == second.output_hash
    assert first.recipe_hash == second.recipe_hash


def test_graphics_recipe_uses_edit_graphic_operation_footprint():
    from kinocut.aivideo.graphics_recipe import _mutation_intent

    recipe_hash = "sha256:" + "0" * 64
    intent = _mutation_intent(recipe_hash)
    assert intent.operation is MutationOperation.EDIT_GRAPHIC
    touched = {("graphic", recipe_hash)}
    assert {("graphic", fingerprint) for _kind, fingerprint in touched_dependencies(intent)} == {
        ("graphic", value) for _kind, value in touched
    }


def test_graphics_recipe_carries_authorization_decision_ids():
    recipe_hash = "sha256:" + "0" * 64
    decision_id = "sha256:" + "1" * 64
    assert _mutation_intent(recipe_hash, (decision_id,)).authorization_decision_ids == (decision_id,)


def _protect_recipe_with_original(project, recipe_hash):
    original = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=recipe_hash,
                dependency_fingerprint=recipe_hash,
            )
        ),
    )
    lock = protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="graphic",
                dependency_fingerprint=recipe_hash,
                human_approval_ref=original.record_id,
            )
        ),
    )
    return lock, original


def _graphics_approval(project, recipe_hash, lock, original, **overrides):
    fingerprint = mutation_fingerprint(_mutation_intent(recipe_hash))
    values = review_decision_kwargs(
        project_id=project.project_id,
        target_ref=fingerprint,
        dependency_fingerprint=fingerprint,
        source_record_ids=(lock.record_id, original.record_id),
    )
    values.update(overrides)
    return append_record(project, ReviewDecision(**values))


def test_recipe_accepts_fresh_exact_authorization(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    lock, original = _protect_recipe_with_original(project, first.recipe_hash)
    approval = _graphics_approval(project, first.recipe_hash, lock, original)

    result = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
        authorization_decision_ids=(approval.record_id,),
    )
    assert result.recipe_hash == first.recipe_hash


def test_recipe_rejects_superseded_authorization(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    lock, original = _protect_recipe_with_original(project, first.recipe_hash)
    approval = _graphics_approval(project, first.recipe_hash, lock, original)
    _graphics_approval(
        project,
        first.recipe_hash,
        lock,
        original,
        decision="reject",
        supersedes=approval.record_id,
    )

    with pytest.raises(MCPVideoError):
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=layers,
            canvas=_canvas(),
            authorization_decision_ids=(approval.record_id,),
        )


def test_recipe_rejects_wrong_fingerprint_authorization(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    lock, original = _protect_recipe_with_original(project, first.recipe_hash)
    approval = _graphics_approval(
        project,
        first.recipe_hash,
        lock,
        original,
        target_ref="sha256:" + "9" * 64,
        dependency_fingerprint="sha256:" + "9" * 64,
    )
    with pytest.raises(MCPVideoError):
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=layers,
            canvas=_canvas(),
            authorization_decision_ids=(approval.record_id,),
        )


def test_recipe_collides_with_protected_recipe(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="graphic",
                dependency_fingerprint=first.recipe_hash,
            )
        ),
    )
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id=asset.asset_id,
            font_path=font_path,
            layers=layers,
            canvas=_canvas(),
        )
    assert exc.value.code == "protected_element_change"


def test_recipe_honors_exact_allowed_operation(source, font_path, logo_path):
    project, asset = source
    layers = _basic_layers(logo_path)
    first = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="graphic",
                dependency_fingerprint=first.recipe_hash,
                allowed_operations=("edit_graphic",),
            )
        ),
    )
    second = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=layers,
        canvas=_canvas(),
    )
    assert second.asset.record_id == first.asset.record_id


def test_receipt_does_not_leak_absolute_paths(source, font_path, logo_path, tmp_path):
    project, asset = source
    result = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=_basic_layers(logo_path),
        canvas=_canvas(),
    )
    artifact = (project.root / result.receipt_artifact_location).read_text(encoding="utf-8")
    assert str(project.root) not in artifact
    assert font_path not in artifact
    assert logo_path not in artifact


def test_recipe_rejects_missing_background_asset(source, font_path, logo_path):
    project, _asset = source
    with pytest.raises(MCPVideoError) as exc:
        compose_graphics_recipe(
            project,
            background_asset_id="sha256:" + "0" * 64,
            font_path=font_path,
            layers=_basic_layers(logo_path),
            canvas=_canvas(),
        )
    assert exc.value.code == "graphics_integrity_failed"


def test_receipt_records_layer_kind_set(source, font_path, logo_path):
    import json

    project, asset = source
    result = compose_graphics_recipe(
        project,
        background_asset_id=asset.asset_id,
        font_path=font_path,
        layers=_basic_layers(logo_path),
        canvas=_canvas(),
    )
    artifact = (project.root / result.receipt_artifact_location).read_text(encoding="utf-8")
    payload = json.loads(artifact)
    kinds = {layer["kind"] for layer in payload["layers"]}
    assert kinds == {"text", "logo", "caption"}
    assert payload["operation"] == "graphics_recipe"
    assert payload["schema_version"] == 1
    assert "render_determinism_scope" in payload


# ---------------------------------------------------------------------------
# Repo-policy divergence tests: graphics modules must consume shared sources.
# ---------------------------------------------------------------------------


def test_graphics_checks_consumes_max_layers_from_limits() -> None:
    """Graphics layer ceiling is imported from ``kinocut.limits`` (no local copy)."""

    assert "MAX_GRAPHICS_LAYERS" in _imports_from(CHECKS_PATH, "limits")
    assigned = _module_assignments(CHECKS_PATH)
    assert "_MAX_LAYERS" not in assigned
    assert "MAX_GRAPHICS_LAYERS" not in assigned


def test_graphics_checks_consumes_max_canvas_duration_from_limits() -> None:
    """Graphics canvas-duration ceiling is imported from ``kinocut.limits``."""

    assert "MAX_GRAPHICS_CANVAS_DURATION" in _imports_from(CHECKS_PATH, "limits")
    assigned = _module_assignments(CHECKS_PATH)
    assert "_MAX_CANVAS_DURATION" not in assigned
    assert "MAX_GRAPHICS_CANVAS_DURATION" not in assigned


def test_graphics_checks_consumes_hex_color_regex_from_validation() -> None:
    """Graphics hex-color regex is shared from ``kinocut.validation``."""

    assert "GRAPHICS_HEX_COLOR_RE" in _imports_from(CHECKS_PATH, "validation")
    assigned = _module_assignments(CHECKS_PATH)
    assert "_HEX_COLOR_RE" not in assigned


def test_graphics_checks_consumes_closed_sets_from_validation() -> None:
    """Generative-field and base-field closed sets come from ``kinocut.validation``."""

    imported = _imports_from(CHECKS_PATH, "validation")
    assert "GRAPHICS_GENERATIVE_FIELD_HINTS" in imported
    assert "GRAPHICS_LAYER_BASE_FIELDS" in imported
    assigned = _module_assignments(CHECKS_PATH)
    assert "_GENERATIVE_FIELD_HINTS" not in assigned
    assert "_LAYER_BASE_FIELDS" not in assigned


def test_graphics_checks_consumes_hash_chunk_bytes_from_defaults() -> None:
    """Graphics hashing chunk size is the shared ``defaults`` constant."""

    assert "DEFAULT_HASH_CHUNK_BYTES" in _imports_from(CHECKS_PATH, "defaults")
    assigned = _module_assignments(CHECKS_PATH)
    assert "_CHUNK_BYTES" not in assigned


def test_graphics_checks_consumes_canvas_defaults_from_defaults_module() -> None:
    """Graphics canvas fps/duration/background defaults come from ``kinocut.defaults``."""

    imported = _imports_from(CHECKS_PATH, "defaults")
    assert "DEFAULT_GRAPHICS_CANVAS_FPS" in imported
    assert "DEFAULT_GRAPHICS_CANVAS_DURATION" in imported
    assert "DEFAULT_GRAPHICS_CANVAS_BACKGROUND" in imported


def test_graphics_recipe_does_not_redefine_parameter_error_code() -> None:
    """The error-code constant has exactly one definition across both modules."""

    recipe_assigned = _module_assignments(RECIPE_PATH)
    checks_assigned = _module_assignments(CHECKS_PATH)
    # Exactly one definition across the two modules (lives in checks).
    assert "_PARAMETER_ERROR_CODE" not in recipe_assigned
    assert "_PARAMETER_ERROR_CODE" in checks_assigned
    # graphics_recipe imports it from checks rather than redefining.
    assert "_PARAMETER_ERROR_CODE" in _imports_from(RECIPE_PATH, "graphics_recipe_checks")


def test_graphics_enforcement_follows_shared_max_layers(monkeypatch) -> None:
    """Lowering ``limits.MAX_GRAPHICS_LAYERS`` tightens graphics enforcement."""

    import kinocut.aivideo.graphics_recipe_checks as checks
    import kinocut.limits as limits

    layers = [{"kind": "text", "text": "X", "position": {"x": 0, "y": 0}} for _ in range(3)]
    checks._validated_layers(layers)  # 3 layers under default 32 — passes
    monkeypatch.setattr(limits, "MAX_GRAPHICS_LAYERS", 2)
    monkeypatch.setattr(checks, "MAX_GRAPHICS_LAYERS", 2)
    with pytest.raises(MCPVideoError) as exc:
        checks._validated_layers(layers)
    assert exc.value.code == "invalid_graphics_layer"


def test_graphics_enforcement_follows_shared_max_canvas_duration(monkeypatch) -> None:
    """Lowering ``limits.MAX_GRAPHICS_CANVAS_DURATION`` tightens canvas validation."""

    import kinocut.aivideo.graphics_recipe_checks as checks
    import kinocut.limits as limits

    raw = {"width": 320, "height": 240, "fps": 12, "duration": 5.0, "background": "#000000"}
    checks._normalized_canvas(raw, "ignored")  # 5.0s under default 60.0s — passes
    monkeypatch.setattr(limits, "MAX_GRAPHICS_CANVAS_DURATION", 2.0)
    monkeypatch.setattr(checks, "MAX_GRAPHICS_CANVAS_DURATION", 2.0)
    with pytest.raises(MCPVideoError) as exc:
        checks._normalized_canvas(raw, "ignored")
    assert exc.value.code == "invalid_graphics_layer"


def test_graphics_enforcement_follows_shared_generative_field_hints(monkeypatch) -> None:
    """A field added to the shared validation set is rejected by graphics."""

    import kinocut.aivideo.graphics_recipe_checks as checks
    import kinocut.validation as validation

    widened = validation.GRAPHICS_GENERATIVE_FIELD_HINTS | {"malevolent_signal"}
    monkeypatch.setattr(validation, "GRAPHICS_GENERATIVE_FIELD_HINTS", widened)
    monkeypatch.setattr(checks, "GRAPHICS_GENERATIVE_FIELD_HINTS", widened)
    raw = [{"kind": "text", "text": "X", "malevolent_signal": "x", "position": {"x": 0, "y": 0}}]
    with pytest.raises(MCPVideoError) as exc:
        checks._validated_layers(raw)
    assert exc.value.code == "invalid_graphics_layer"


def test_graphics_enforcement_follows_shared_layer_base_fields(monkeypatch) -> None:
    """Shrinking the shared base-field set rejects previously-accepted fields."""

    import kinocut.aivideo.graphics_recipe_checks as checks
    import kinocut.validation as validation

    shrunk = validation.GRAPHICS_LAYER_BASE_FIELDS - {"opacity"}
    monkeypatch.setattr(validation, "GRAPHICS_LAYER_BASE_FIELDS", shrunk)
    monkeypatch.setattr(checks, "GRAPHICS_LAYER_BASE_FIELDS", shrunk)
    raw = [{"kind": "text", "text": "X", "opacity": 0.5, "position": {"x": 0, "y": 0}}]
    with pytest.raises(MCPVideoError) as exc:
        checks._validated_layers(raw)
    assert exc.value.code == "invalid_graphics_layer"


def test_graphics_enforcement_follows_shared_hex_color_regex(monkeypatch) -> None:
    """Mutating the shared regex changes what colors graphics accepts."""

    import kinocut.aivideo.graphics_recipe_checks as checks
    import kinocut.validation as validation
    import re

    strict = re.compile(r"^#[0-9A-Fa-f]{6}$")  # disallow optional alpha / bare hex
    monkeypatch.setattr(validation, "GRAPHICS_HEX_COLOR_RE", strict)
    monkeypatch.setattr(checks, "GRAPHICS_HEX_COLOR_RE", strict)
    # Six-digit bare hex (no #) was previously accepted; the strict pattern rejects it.
    with pytest.raises(MCPVideoError):
        checks._validate_color("FFFFFF", offset=1)


# ---------------------------------------------------------------------------
# AST divergence: reject forbidden literal defaults and local tunable constants.
# ---------------------------------------------------------------------------

# Stable schema/operation/provider/error/receipt identifiers that may remain as
# module-level literals. Each pins the receipt protocol and never varies at
# runtime; they are NOT tunable defaults.
_ALLOWED_MODULE_LITERALS: frozenset[str] = frozenset(
    {
        # graphics_recipe.py — receipt/provider identifiers
        "_GENERATOR_MODEL",
        "_PROVIDER_ID",
        "_RECEIPT_NAME",
        # graphics_recipe_checks.py — schema/operation/error identifiers
        "_SCHEMA_VERSION",
        "_OPERATION_NAME",
        "_PARAMETER_ERROR_CODE",
    }
)


def _is_tunable_literal(node: ast.AST) -> bool:
    """Whether *node* is a scalar literal that must not be inlined as a default.

    Returns ``True`` only for numeric/string ``Constant`` nodes. ``None`` /
    ``True`` / ``False`` are sentinels, and collection literals inside function
    bodies are implementation details (not defaults), so those return ``False``.
    """

    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, str))
    return False


def test_graphics_modules_reject_forbidden_literal_defaults() -> None:
    """AST divergence test: no inlined tunable literals in either graphics module.

    Walks both modules and rejects:
    - ``Field(default=LITERAL)`` or ``Field(default_factory=lambda: ...)``
    - Model-field annotated assignments with tunable literal values
    - Function-default arguments with tunable literal values
    - Module-level tunable constants outside the narrow stable-identifier allowlist
    """

    violations: list[str] = []
    for path, label in ((RECIPE_PATH, "graphics_recipe"), (CHECKS_PATH, "graphics_recipe_checks")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # 1. Field() calls: default must not be a literal; default_factory must not be a lambda.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if fname != "Field":
                continue
            for kw in node.keywords:
                if kw.arg == "default" and _is_tunable_literal(kw.value):
                    violations.append(f"{label}:L{node.lineno} Field(default=<literal>)")
                if kw.arg == "default_factory" and isinstance(kw.value, ast.Lambda):
                    violations.append(f"{label}:L{node.lineno} Field(default_factory=lambda:...) — use a named factory")

        # 2. Class-body AnnAssign (model field defaults): color/opacity/etc. must
        #    reference a named constant. Only direct children of ClassDef are
        #    checked so local variables inside methods/functions are excluded.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if (
                    isinstance(child, ast.AnnAssign)
                    and isinstance(child.target, ast.Name)
                    and child.value is not None
                    and _is_tunable_literal(child.value)
                ):
                    violations.append(
                        f"{label}:L{child.lineno} {child.target.id}: ... = <literal> — import from defaults.py"
                    )

        # 3. Function defaults: no tunable literal values in default arguments.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for default in defaults:
                if _is_tunable_literal(default):
                    violations.append(f"{label}:L{node.lineno} {node.name}() has tunable literal default arg")

        # 4. Module-level constants: only stable identifiers may be literals.
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and _is_tunable_literal(node.value)
                    and target.id not in _ALLOWED_MODULE_LITERALS
                ):
                    violations.append(
                        f"{label}:L{node.lineno} module constant '{target.id}' = <literal> "
                        "— move to defaults/limits/validation"
                    )

    assert not violations, "Forbidden literal defaults found:\n" + "\n".join(violations)


def test_graphics_checks_consumes_layer_defaults_from_defaults_module() -> None:
    """Graphics layer color/opacity/position defaults come from kinocut.defaults."""

    imported = _imports_from(CHECKS_PATH, "defaults")
    assert "DEFAULT_GRAPHICS_LAYER_COLOR" in imported
    assert "DEFAULT_GRAPHICS_LAYER_OPACITY" in imported
    assert "DEFAULT_GRAPHICS_LAYER_POSITION_X" in imported
    assert "DEFAULT_GRAPHICS_LAYER_POSITION_Y" in imported


def test_default_position_factory_produces_independent_dicts() -> None:
    """_default_position() returns a fresh dict every call (no mutable shared state)."""

    from kinocut.aivideo.graphics_recipe_checks import _default_position

    d1 = _default_position()
    d2 = _default_position()
    assert d1 == d2 == {"x": 0.0, "y": 0.0}
    assert d1 is not d2

    # Mutating one dict must not affect the other.
    d1["x"] = 5.0
    assert d2 == {"x": 0.0, "y": 0.0}


def test_graphics_layer_default_position_not_shared_across_instances() -> None:
    """Two GraphicsLayer instances with default position must not alias the same dict.

    Frozen models don't deep-freeze mutable containers, so mutating one
    instance's position dict must never leak to another instance.
    """

    import kinocut.aivideo.graphics_recipe_checks as checks

    layer1 = checks._validate_graphics_layer({"kind": "text", "text": "A"}, 1)
    layer2 = checks._validate_graphics_layer({"kind": "text", "text": "B"}, 2)

    assert layer1.position == {"x": 0.0, "y": 0.0}
    assert layer2.position == {"x": 0.0, "y": 0.0}
    assert layer1.position is not layer2.position

    # Mutate one instance's position dict in place.
    layer1.position["x"] = 999.0
    assert layer2.position == {"x": 0.0, "y": 0.0}
