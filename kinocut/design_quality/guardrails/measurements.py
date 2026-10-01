"""Canonical quality measurements shared across design checks and scoring."""

from __future__ import annotations

from copy import deepcopy

from ...defaults import QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES
from ...quality_guardrails import VisualQualityGuardrails


def _quality_engine(guardrail) -> VisualQualityGuardrails:
    """Retain source-identity-aware measurements across checks on one guardrail."""
    engine = getattr(guardrail, "_visual_quality_engine", None)
    if engine is None:
        engine = guardrail._visual_quality_engine = VisualQualityGuardrails()
    return engine


def _analyze_design_colors(guardrail, video_path: str) -> dict:
    """Return defensive copies; cache only complete, unchanged-source results."""
    engine = _quality_engine(guardrail)
    key = engine._signalstats_cache_key(video_path)
    cache = guardrail._color_analysis_cache
    if key is not None and key in cache:
        result = deepcopy(cache.pop(key))
        cache[key] = deepcopy(result)
    else:
        rgb = engine._get_rgb_means(video_path)
        rgb_values = [rgb[channel] for channel in ("r", "g", "b")] if rgb and "_error" not in rgb else None
        saturation_metric = engine.check_saturation(video_path).details["metric"]
        rgb_metric = {
            "name": "ffmpeg.signalstats.approximate_rgb",
            "available": rgb_values is not None,
            "value": rgb_values,
            "unit": "8bit_rgb_approximation",
            "approximate": True,
        }
        if rgb and "_error" in rgb:
            rgb_metric["diagnostic"] = rgb["_error"]
        result = {
            "rgb_means": rgb_values,
            "rgb_metric": rgb_metric,
            "saturation": saturation_metric["value"] if saturation_metric["available"] else None,
            "saturation_metric": saturation_metric,
        }
        if (
            key is not None
            and rgb_values is not None
            and saturation_metric["available"]
            and engine._signalstats_cache_key(video_path) == key
        ):
            cache[key] = deepcopy(result)
            while len(cache) > QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES:
                cache.pop(next(iter(cache)))
    guardrail.metrics["rgb"] = deepcopy(result["rgb_metric"])
    guardrail.metrics["saturation"] = deepcopy(result["saturation_metric"])
    return deepcopy(result)
