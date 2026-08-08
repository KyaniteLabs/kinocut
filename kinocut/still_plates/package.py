"""still-package: establish → edit beats → match → grade → gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from .edit import image_edit
from .gate import still_gate
from .grade import still_grade
from .io import ensure_output_dir, validate_still_path, write_receipt
from .match import still_match


def _edit_beats(
    establish_path: Path,
    beat_paths: list[Path],
    intent_list: list[str],
    edit_dir: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    edited_paths: list[Path] = []
    edit_receipts: list[dict[str, Any]] = []
    for beat, intent in zip(beat_paths, intent_list, strict=True):
        er = image_edit(
            source=beat,
            reference=establish_path,
            intent=intent,
            output_dir=edit_dir / beat.stem,
            prefer="edit",
            allow_paid_gen=False,
            dry_run=False,
        )
        edit_receipts.append(er)
        edited_paths.append(Path(er["outputs"][0]["output"]))
    return edited_paths, edit_receipts


def still_package(
    *,
    establish: str | Path,
    beats: list[str | Path],
    output_dir: str | Path,
    intents: list[str] | None = None,
    apply_grade: bool = True,
    lut_path: str | Path | None = None,
    signal_mode: bool = False,
    dry_run: bool = False,
    receipt_name: str = "still_package_receipt.json",
) -> dict[str, Any]:
    """Edit beats → match → grade → gate for a multi-still package."""
    if not beats:
        raise MCPVideoError(
            "still-package requires at least one beat still",
            error_type="validation_error",
            code="empty_inputs",
        )
    establish_path = validate_still_path(establish)
    beat_paths = [validate_still_path(b) for b in beats]
    out_dir = ensure_output_dir(output_dir)
    intent_list = intents or ["match establish world and light"] * len(beat_paths)
    if len(intent_list) != len(beat_paths):
        raise MCPVideoError(
            "intents length must match beats length",
            error_type="validation_error",
            code="intent_length_mismatch",
        )
    graph = [
        {"step": "edit_beats", "count": len(beat_paths)},
        {"step": "still_match", "hero": str(establish_path)},
        {"step": "still_grade", "enabled": apply_grade},
        {"step": "still_gate"},
    ]
    if dry_run:
        receipt = {
            "tool": "still_package",
            "status": "planned",
            "dry_run": True,
            "graph": graph,
            "establish": str(establish_path),
            "beats": [str(p) for p in beat_paths],
        }
        path = write_receipt(out_dir / receipt_name, receipt)
        receipt["receipt_path"] = str(path)
        receipt["output_dir"] = str(out_dir)
        return receipt

    edited_paths, edit_receipts = _edit_beats(establish_path, beat_paths, intent_list, out_dir / "edits")
    match_receipt = still_match(hero=establish_path, inputs=edited_paths, output_dir=out_dir / "matched")
    matched_paths = [Path(o["output"]) for o in match_receipt["outputs"]]
    grade_receipt = None
    gate_inputs = matched_paths
    if apply_grade:
        grade_receipt = still_grade(
            inputs=matched_paths,
            output_dir=out_dir / "graded",
            hero=establish_path,
            lut_path=lut_path,
            signal_mode=signal_mode,
        )
        gate_inputs = [Path(o["output"]) for o in grade_receipt["outputs"]]
    gate_receipt = still_gate(inputs=gate_inputs, output_dir=out_dir / "gate")
    passed = bool(gate_receipt.get("passed"))
    package = {
        "tool": "still_package",
        "status": "ok" if passed else "gate_failed",
        "dry_run": False,
        "graph": graph,
        "establish": str(establish_path),
        "edit_receipts": edit_receipts,
        "match_receipt": match_receipt,
        "grade_receipt": grade_receipt,
        "gate_receipt": gate_receipt,
        "passed": passed,
        "exit_code": 0 if passed else 1,
        "output_dir": str(out_dir),
    }
    package["receipt_path"] = str(write_receipt(out_dir / receipt_name, package))
    return package
