"""Brand kits / style profiles (TE.3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import _validate_artifact_path, _validate_input_path


@dataclass
class BrandKit:
    name: str
    primary_color: str = "#FFFFFF"
    accent_color: str = "#000000"
    font: str = "sans"
    logo_path: str | None = None
    subtitle_style: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def save_brand_kit(path: str, kit: BrandKit) -> dict[str, Any]:
    p = Path(_validate_artifact_path(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"artifact_kind": "brand_kit", **kit.to_dict()}
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_brand_kit(path: str) -> BrandKit:
    p = Path(_validate_input_path(path))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            f"invalid brand kit JSON: {exc}",
            error_type="validation_error",
            code="invalid_brand_kit",
        ) from exc
    return BrandKit(
        name=str(data.get("name") or "unnamed"),
        primary_color=str(data.get("primary_color") or "#FFFFFF"),
        accent_color=str(data.get("accent_color") or "#000000"),
        font=str(data.get("font") or "sans"),
        logo_path=data.get("logo_path"),
        subtitle_style=dict(data.get("subtitle_style") or {}),
        notes=str(data.get("notes") or ""),
    )
