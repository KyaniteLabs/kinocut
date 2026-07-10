"""Evidence contracts and promotion gates for local restorative quality."""

from .contracts import (
    CapabilityStatus,
    ModelProvenance,
    ModelRequirement,
    RestorativeCapability,
    RestorativeFeature,
    RestorativePlan,
    VERIFICATION_CONTRACTS,
    VerificationContract,
)
from .api import evaluate_restoration, plan_restoration
from .evidence import (
    AdvancedColorHDREvidence,
    BackgroundRepairEvidence,
    FrameRepairEvidence,
    NoiseType,
    RestorativeEvidence,
    SpeechDenoiseEvidence,
    StyledCaptionEvidence,
)
from .evaluators import (
    GateResult,
    PromotionDecision,
    PromotionEvaluation,
    evaluate_advanced_color_hdr,
    evaluate_background_repair,
    evaluate_frame_repair,
    evaluate_promotion,
    evaluate_speech_denoise,
    evaluate_styled_captions,
)

__all__ = [
    "VERIFICATION_CONTRACTS",
    "AdvancedColorHDREvidence",
    "BackgroundRepairEvidence",
    "CapabilityStatus",
    "FrameRepairEvidence",
    "GateResult",
    "ModelProvenance",
    "ModelRequirement",
    "NoiseType",
    "PromotionDecision",
    "PromotionEvaluation",
    "RestorativeCapability",
    "RestorativeEvidence",
    "RestorativeFeature",
    "RestorativePlan",
    "SpeechDenoiseEvidence",
    "StyledCaptionEvidence",
    "VerificationContract",
    "evaluate_advanced_color_hdr",
    "evaluate_background_repair",
    "evaluate_frame_repair",
    "evaluate_promotion",
    "evaluate_restoration",
    "evaluate_speech_denoise",
    "evaluate_styled_captions",
    "plan_restoration",
]
