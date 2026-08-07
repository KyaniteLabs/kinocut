"""image-edit / still-edit: free establish-locked edit with plan + receipt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..defaults import STILL_MATCH_MAX_GAIN, STILL_MATCH_MIN_GAIN
from ..errors import MCPVideoError
from .io import (
    ensure_output_dir,
    file_sha256,
    load_rgb_array,
    require_still_deps,
    save_rgb_array,
    validate_still_path,
    write_receipt,
)
from .stats import apply_rgb_gains, mean_rgb, shared_gains_to_hero


def _validate_edit_policy(*, prefer: str, allow_paid_gen: bool, intent: str) -> str:
    if prefer not in {"edit", "gen"}:
        raise MCPVideoError(
            "prefer must be 'edit' or 'gen'",
            error_type="validation_error",
            code="invalid_prefer",
        )
    if prefer == "gen" and not allow_paid_gen:
        raise MCPVideoError(
            "prefer=gen requires allow_paid_gen=True (default prefers free edit)",
            error_type="validation_error",
            code="paid_gen_disabled",
        )
    if allow_paid_gen and prefer == "gen":
        raise MCPVideoError(
            "paid generative still edit is not configured; use prefer=edit",
            error_type="dependency_error",
            code="paid_edit_backend_unavailable",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Use prefer=edit with free establish-lock matching, "
                    "or install a configured gen backend when available."
                ),
            },
        )
    intent_text = (intent or "").strip()
    if not intent_text:
        raise MCPVideoError(
            "intent is required (describe the establish-locked edit)",
            error_type="validation_error",
            code="empty_intent",
        )
    return intent_text


def _require_edit_backend() -> None:
    try:
        require_still_deps()
    except MCPVideoError as exc:
        raise MCPVideoError(
            str(exc),
            error_type="dependency_error",
            code="edit_backend_unavailable",
            suggested_action={
                "auto_fix": False,
                "description": 'Install free still edit path: pip install "kinocut[image]"',
            },
        ) from exc


def image_edit(
    *,
    source: str | Path,
    reference: str | Path,
    intent: str,
    output_dir: str | Path,
    prefer: str = "edit",
    allow_paid_gen: bool = False,
    dry_run: bool = False,
    receipt_name: str = "image_edit_receipt.json",
) -> dict[str, Any]:
    """Plan-first establish-locked still match with plan/receipt.

    v1 pixel path is free establish mean-RGB match only. ``intent`` is required
    audit metadata (what the agent meant); it does **not** select pixel ops.
    Paid generative backends stay off unless explicitly enabled (then still
    unavailable until configured).
    """
    intent_text = _validate_edit_policy(prefer=prefer, allow_paid_gen=allow_paid_gen, intent=intent)
    _require_edit_backend()

    source_path = validate_still_path(source)
    ref_path = validate_still_path(reference)
    out_dir = ensure_output_dir(output_dir)

    src_arr = load_rgb_array(source_path)
    ref_arr = load_rgb_array(ref_path)
    gains = shared_gains_to_hero(
        mean_rgb(ref_arr),
        mean_rgb(src_arr),
        max_gain=STILL_MATCH_MAX_GAIN,
        min_gain=STILL_MATCH_MIN_GAIN,
    )
    plan = {
        "backend": "free_establish_match",
        "prefer": prefer,
        "allow_paid_gen": allow_paid_gen,
        # Intent is audit/receipt metadata for agents and humans. v1 pixel path
        # is establish mean-RGB match only — intent does not drive pixels.
        "intent": intent_text,
        "intent_policy": "metadata_only",
        "pixel_ops": ["establish_mean_rgb_match"],
        "source": str(source_path),
        "reference": str(ref_path),
        "shared_gains": list(gains),
        "mutates_pixels": not dry_run,
        "stages": ["plan", "establish_match", "export"],
    }
    if dry_run:
        receipt = {"tool": "image_edit", "status": "planned", "dry_run": True, "plan": plan, "outputs": []}
    else:
        dest = out_dir / f"{source_path.stem}_edited.png"
        save_rgb_array(apply_rgb_gains(src_arr, gains), dest)
        receipt = {
            "tool": "image_edit",
            "status": "ok",
            "dry_run": False,
            "plan": plan,
            "outputs": [
                {
                    "source": str(source_path),
                    "output": str(dest),
                    "source_sha256": file_sha256(source_path),
                    "output_sha256": file_sha256(dest),
                    "reference_sha256": file_sha256(ref_path),
                }
            ],
        }
    receipt_path = write_receipt(out_dir / receipt_name, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["output_dir"] = str(out_dir)
    return receipt
