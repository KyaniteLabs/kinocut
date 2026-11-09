"""Named content profiles for the SDR picture heuristics in ``video-quality-check`` (#679).

The default checks are tuned for camera footage. A UI screen capture that is
deliberately dark (or light), built from flat panels and a near-neutral palette,
fails them for being exactly what it was meant to be. A profile states that
intent explicitly and auditably instead of lowering ``min_score`` for everything.

A profile only changes the brightness, contrast and saturation bands. Audio,
color balance and temporal motion are profile-independent. Under any
non-default profile the relaxed bands become hard limits: a failed visual check
fails the release gate even when the overall score clears ``min_score``, so a
blank or black capture cannot slip through on the strength of its audio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .errors import MCPVideoError

DEFAULT_QUALITY_PROFILE = "default"


@dataclass(frozen=True)
class VisualBand:
    """Pass range plus scoring for one picture metric.

    ``plateau=False`` keeps the original camera-footage score: distance from
    ``optimum`` scaled by ``scale``. ``plateau=True`` scores 100 anywhere inside
    the pass range and decays by ``scale`` units per 100 points outside it.
    """

    target_min: float
    target_max: float
    optimum: float
    scale: float
    plateau: bool = False

    def score(self, value: float) -> float:
        if not self.plateau:
            return float(max(0.0, 100 - (abs(value - self.optimum) / self.scale) * 100))
        if self.target_min <= value <= self.target_max:
            return 100.0
        distance = self.target_min - value if value < self.target_min else value - self.target_max
        return float(max(0.0, 100 - (distance / self.scale) * 100))


@dataclass(frozen=True)
class QualityProfile:
    name: str
    description: str
    brightness: VisualBand
    contrast: VisualBand
    saturation: VisualBand
    visual_checks_gate: bool

    def receipt(self) -> dict:
        """Auditable record of the profile and every threshold it applied."""
        return {
            "name": self.name,
            "description": self.description,
            "visual_checks_gate": self.visual_checks_gate,
            "profile_independent_checks": ["audio_levels", "color_balance", "temporal_motion"],
            "bands": {
                "brightness": asdict(self.brightness),
                "contrast": asdict(self.contrast),
                "saturation": asdict(self.saturation),
            },
        }


# Contrast is the 10th-90th percentile luma spread (% of 8-bit range). UI text
# covers well under 10% of pixels, so flat panels legitimately read low; a
# single solid frame still reads ~0 and fails the 3% floor.
_UI_CONTRAST = VisualBand(target_min=3, target_max=100, optimum=50, scale=3, plateau=True)
# Near-neutral UI palettes are valid; oversaturation is still a defect.
_UI_SATURATION = VisualBand(target_min=0, target_max=120, optimum=50, scale=50, plateau=True)

QUALITY_PROFILES: dict[str, QualityProfile] = {
    DEFAULT_QUALITY_PROFILE: QualityProfile(
        name=DEFAULT_QUALITY_PROFILE,
        description="Camera footage: SDR code-value heuristics.",
        brightness=VisualBand(target_min=40, target_max=200, optimum=128, scale=128),
        contrast=VisualBand(target_min=20, target_max=100, optimum=50, scale=50),
        saturation=VisualBand(target_min=10, target_max=120, optimum=50, scale=50),
        visual_checks_gate=False,
    ),
    "ui-capture-dark": QualityProfile(
        name="ui-capture-dark",
        description="Dark-theme UI screen capture: dark ground, flat panels, neutral palette.",
        # Limited-range black is Y=16; a black or failed capture stays below 20.
        brightness=VisualBand(target_min=20, target_max=110, optimum=45, scale=10, plateau=True),
        contrast=_UI_CONTRAST,
        saturation=_UI_SATURATION,
        visual_checks_gate=True,
    ),
    "ui-capture-light": QualityProfile(
        name="ui-capture-light",
        description="Light-theme UI screen capture: light ground, flat panels, neutral palette.",
        # Limited-range white is Y=235; anything above it is clipped.
        brightness=VisualBand(target_min=120, target_max=235, optimum=200, scale=10, plateau=True),
        contrast=_UI_CONTRAST,
        saturation=_UI_SATURATION,
        visual_checks_gate=True,
    ),
}

VISUAL_PROFILE_CHECKS = ("brightness", "contrast", "saturation")


def resolve_quality_profile(name: str | None) -> QualityProfile:
    key = DEFAULT_QUALITY_PROFILE if name is None else name
    try:
        return QUALITY_PROFILES[key]
    except (KeyError, TypeError):
        raise MCPVideoError(
            f"Unknown quality profile {name!r}; choose one of: {', '.join(QUALITY_PROFILES)}",
            error_type="validation_error",
            code="invalid_parameter",
        ) from None
