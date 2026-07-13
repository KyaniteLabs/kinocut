"""``kinocut_sound.post`` — restoration and spatial post-processing chain.

The S7 leaf of the Sonic World audio-play program. This sidecar package
implements the fixed-order post chain:

    denoise → de-ess → EQ → dynamics → convolution space
           → distance → humanization → loudness/true-peak

It is fully usable without importing any ``kinocut`` runtime module: it
re-uses the canonical contracts from :mod:`kinocut_sound` (SoundPlan, Line,
DeliveryPolicy, RenderFingerprint, etc.) and implements typed
:class:`ProcessorAdapter` and :class:`SpatializerAdapter` conforming to the
:class:`kinocut_sound.registry.Adapter` protocol.

Public surface:

* :class:`PostChain`, :class:`PostContext`, :class:`PostStageResult`,
  :class:`PostChainResult`.
* :class:`ProcessorAdapter`, :class:`SpatializerAdapter` protocols.
* :class:`FFTDenoiseAdapter`, :class:`NeuralDenoiseAdapter`.
* :class:`DeEssAdapter`.
* :class:`EqAdapter`, :class:`EqBandGains`, named presets.
* :class:`DynamicsAdapter`.
* :class:`ConvolutionReverbAdapter`, :class:`DistanceAdapter`,
  :class:`HumanizationAdapter`.
* :class:`LoudnessAdapter`.
* :class:`BatchPlanner`, :class:`BatchClip`, :class:`BatchResult`.
* :class:`PostError` and stable post error codes.
"""

from __future__ import annotations

from kinocut_sound.post._errors import (
    POST_CLIP_MISSING,
    POST_DEPENDENCY_MISSING,
    POST_INVALID_PARAM,
    POST_OVER_LIMIT,
    POST_OVERRUN,
    POST_PRESET_UNKNOWN,
    POST_PROCESSING_FAILED,
    POST_TIMEOUT,
    PostError,
    post_error,
)
from kinocut_sound.post._subprocess import (
    DEFAULT_POST_TIMEOUT_SECONDS,
    MAX_POST_TIMEOUT_SECONDS,
)
from kinocut_sound.post.batch import (
    BatchClip,
    BatchPlanner,
    BatchResult,
    MAX_BATCH_CLIPS,
)
from kinocut_sound.post.chain import (
    CANONICAL_STAGE_ORDER,
    PostChain,
    PostChainResult,
    PostContext,
    PostStageResult,
    ProcessorAdapter,
    SpatializerAdapter,
)
from kinocut_sound.post.deess import DeEssAdapter
from kinocut_sound.post.denoise import FFTDenoiseAdapter, NeuralDenoiseAdapter
from kinocut_sound.post.dynamics import DynamicsAdapter
from kinocut_sound.post.eq import (
    BAND_FREQUENCIES,
    EQ_PRESETS,
    EqAdapter,
    EqBandGains,
    PRESET_NAMES as EQ_PRESET_NAMES,
)
from kinocut_sound.post.loudness import (
    LOUDNESS_PRESET_NAMES,
    LoudnessAdapter,
)
from kinocut_sound.post.spatial import (
    ConvolutionReverbAdapter,
    DistanceAdapter,
    HumanizationAdapter,
    REVERB_PRESETS,
)

__version__ = "0.1.0"

__all__ = [
    "BAND_FREQUENCIES",
    "CANONICAL_STAGE_ORDER",
    "DEFAULT_POST_TIMEOUT_SECONDS",
    "EQ_PRESETS",
    "EQ_PRESET_NAMES",
    "LOUDNESS_PRESET_NAMES",
    "MAX_BATCH_CLIPS",
    "MAX_POST_TIMEOUT_SECONDS",
    "POST_CLIP_MISSING",
    "POST_DEPENDENCY_MISSING",
    "POST_INVALID_PARAM",
    "POST_OVERRUN",
    "POST_OVER_LIMIT",
    "POST_PRESET_UNKNOWN",
    "POST_PROCESSING_FAILED",
    "POST_TIMEOUT",
    "REVERB_PRESETS",
    "BatchClip",
    "BatchPlanner",
    "BatchResult",
    "ConvolutionReverbAdapter",
    "DeEssAdapter",
    "DistanceAdapter",
    "DynamicsAdapter",
    "EqAdapter",
    "EqBandGains",
    "FFTDenoiseAdapter",
    "HumanizationAdapter",
    "LoudnessAdapter",
    "NeuralDenoiseAdapter",
    "PostChain",
    "PostChainResult",
    "PostContext",
    "PostError",
    "PostStageResult",
    "ProcessorAdapter",
    "SpatializerAdapter",
    "post_error",
]
