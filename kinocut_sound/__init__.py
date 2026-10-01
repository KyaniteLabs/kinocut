"""``kinocut_sound`` — standalone audio-play production contracts.

The foundation leaf (S1) of the Sonic World audio-play production design.
This package ships **inside** the Kinocut repository but is fully usable
without importing any ``kinocut`` runtime module: it re-implements the
canonical-record pattern (frozen Pydantic models, fail-closed typed ids,
sorted-key JSON digests) so the sidecar boundary stays clean.

Public surface (this leaf):

* :class:`SoundPlan` and supporting provenance refs.
* :class:`Timeline`, :class:`Cue`, :class:`CueKind`.
* :class:`AudioFormat` and closed enums for layout/sample/time-base/dither.
* :class:`Routing`, :class:`Track`, :class:`Bus`, sends, sidechains, automation.
* :class:`Line`, :class:`ProfileRef`, :class:`Prosody`, :class:`Emotion`.
* :class:`DeliveryPolicy`, :class:`DeliveryPreset`, loudness and stem policy.
* :class:`ConsentGrant`, :class:`ConsentScope`, :class:`CloudEgressGrant`.
* :class:`AdapterDescriptor`, :class:`CapabilityResult`, :class:`CostDisclosure`.
* :class:`SoundReceipt`, :class:`SoundReceiptSection`, :class:`OrderedInput`.
* :class:`RenderFingerprint`, :class:`DeterminismClass`.
* :class:`SoundContractError` and the stable contract error codes.

Numerical defaults (loudness tolerance, true-peak ceilings, latency residual,
gap tolerance) live in :mod:`kinocut_sound.defaults`; resource ceilings
(stem-recombination tolerance, max loudness tolerance, latency residual) live
in :mod:`kinocut_sound.limits`; and closed validation regexes/sets live in
:mod:`kinocut_sound.validation`. Adapter authors import these directly rather
than reaching into owning modules.
"""

# New leaves added in this integration (S5 voice, S7 post, S8 world) keep
# their public exports in their own subpackages. The top-level surface below
# re-exports the key contracts so adapter authors and plans can import from
# ``kinocut_sound`` directly while the sidecar boundary stays clean.

from __future__ import annotations

from kinocut_sound._canonical import (
    BoundedCode as BoundedCode,
    FrozenModel as FrozenModel,
    RecordBase as RecordBase,
    Sha256 as Sha256,
    canonical_digest as canonical_digest,
    canonical_record_id as canonical_record_id,
    location_violation as location_violation,
)
from kinocut_sound._policy_exports import *  # noqa: F403 - public constant facade
from kinocut_sound._policy_exports import __all__ as _POLICY_NAMES

from kinocut_sound._errors import (
    INVALID_RECORD as INVALID_RECORD,
    UNSAFE_LOCATION as UNSAFE_LOCATION,
    UNKNOWN_RECORD_FIELD as UNKNOWN_RECORD_FIELD,
    SoundContractError as SoundContractError,
    contract_error as contract_error,
)
from kinocut_sound.capability import (
    AdapterDescriptor as AdapterDescriptor,
    AdapterLocality as AdapterLocality,
    CapabilityResult as CapabilityResult,
    CostDisclosure as CostDisclosure,
)
from kinocut_sound.consent import (
    AuditEvent as AuditEvent,
    BlendAuthorization as BlendAuthorization,
    CloudEgressGrant as CloudEgressGrant,
    ConsentGrant as ConsentGrant,
    ConsentScope as ConsentScope,
    ConsentState as ConsentState,
    RetentionPolicy as RetentionPolicy,
)
from kinocut_sound.delivery import (
    DEFAULT_PRESET as DEFAULT_PRESET,
    DeliveryPolicy as DeliveryPolicy,
    DeliveryPreset as DeliveryPreset,
    LoudnessTarget as LoudnessTarget,
    StemLayout as StemLayout,
    StemRecombinationPolicy as StemRecombinationPolicy,
)
from kinocut_sound.format import (
    CHANNEL_COUNT as CHANNEL_COUNT,
    AudioFormat as AudioFormat,
    ChannelLayout as ChannelLayout,
    ConversionPolicy as ConversionPolicy,
    DitherPolicy as DitherPolicy,
    SampleFormat as SampleFormat,
    TimeBase as TimeBase,
)
from kinocut_sound.lines import (
    Emotion as Emotion,
    Line as Line,
    ProfileRef as ProfileRef,
    PronunciationOverride as PronunciationOverride,
    Prosody as Prosody,
)
from kinocut_sound.receipt import (
    LoudnessVerification as LoudnessVerification,
    OrderedInput as OrderedInput,
    PreservationProof as PreservationProof,
    PreservationVerdict as PreservationVerdict,
    SoundReceipt as SoundReceipt,
    SoundReceiptSection as SoundReceiptSection,
    Transformation as Transformation,
)
from kinocut_sound.render_fingerprint import (
    DeterminismClass as DeterminismClass,
    FingerprintComponent as FingerprintComponent,
    RenderFingerprint as RenderFingerprint,
    ToolchainVersion as ToolchainVersion,
)
from kinocut_sound.routing import (
    AutomationEnvelope as AutomationEnvelope,
    AutomationPoint as AutomationPoint,
    Bus as Bus,
    DuckingSidechain as DuckingSidechain,
    LatencyCompensation as LatencyCompensation,
    PanLaw as PanLaw,
    Routing as Routing,
    SendReturn as SendReturn,
    Track as Track,
)
from kinocut_sound.sound_plan import (
    AssetLicenseRef as AssetLicenseRef,
    ModelRef as ModelRef,
    PlanProvenance as PlanProvenance,
    ProcessingPresetRef as ProcessingPresetRef,
    SoundPlan as SoundPlan,
)
from kinocut_sound.voice import (
    BatchPlanner as VoiceBatchPlanner,
    BatchResult as VoiceBatchResult,
    CloudTtsAdapterStub as CloudTtsAdapterStub,
    LocalSynthesisAdapter as LocalSynthesisAdapter,
    PronunciationDictionary as PronunciationDictionary,
    TtsAdapter as TtsAdapter,
    VoiceError as VoiceError,
    VoiceRoster as VoiceRoster,
    VoiceSlot as VoiceSlot,
    default_roster as default_voice_roster,
)
from kinocut_sound.post import (
    BatchClip as PostBatchClip,
    BatchPlanner as PostBatchPlanner,
    BatchResult as PostBatchResult,
    DeEssAdapter as DeEssAdapter,
    DynamicsAdapter as DynamicsAdapter,
    EqAdapter as EqAdapter,
    FFTDenoiseAdapter as FFTDenoiseAdapter,
    LoudnessAdapter as LoudnessAdapter,
    PostChain as PostChain,
    PostChainResult as PostChainResult,
    PostContext as PostContext,
    PostError as PostError,
    PostStageResult as PostStageResult,
)
from kinocut_sound.world import (
    AmbientLayer as AmbientLayer,
    AuditionContract as AuditionContract,
    CatalogAsset as CatalogAsset,
    FoleyResolver as FoleyResolver,
    LayerStack as LayerStack,
    LocationPreset as LocationPreset,
    PresetRegistry as PresetRegistry,
    SeamlessLoop as SeamlessLoop,
    WorldAssetCatalog as WorldAssetCatalog,
    WorldError as WorldError,
)
from kinocut_sound.timeline import (
    Cue as Cue,
    CueKind as CueKind,
    Timeline as Timeline,
)

__version__ = "0.1.0"

__all__ = [
    *_POLICY_NAMES,
    "CHANNEL_COUNT",
    "DEFAULT_PRESET",
    "INVALID_RECORD",
    "UNKNOWN_RECORD_FIELD",
    "UNSAFE_LOCATION",
    "AdapterDescriptor",
    "AdapterLocality",
    "AmbientLayer",
    "AssetLicenseRef",
    "AudioFormat",
    "AuditEvent",
    "AuditionContract",
    "AutomationEnvelope",
    "AutomationPoint",
    "BlendAuthorization",
    "BoundedCode",
    "Bus",
    "CapabilityResult",
    "CatalogAsset",
    "ChannelLayout",
    "CloudEgressGrant",
    "CloudTtsAdapterStub",
    "ConsentGrant",
    "ConsentScope",
    "ConsentState",
    "ConversionPolicy",
    "CostDisclosure",
    "Cue",
    "CueKind",
    "DeEssAdapter",
    "DeliveryPolicy",
    "DeliveryPreset",
    "DeterminismClass",
    "DitherPolicy",
    "DuckingSidechain",
    "DynamicsAdapter",
    "Emotion",
    "EqAdapter",
    "FFTDenoiseAdapter",
    "FingerprintComponent",
    "FoleyResolver",
    "FrozenModel",
    "LatencyCompensation",
    "LayerStack",
    "Line",
    "LocalSynthesisAdapter",
    "LocationPreset",
    "LoudnessAdapter",
    "LoudnessTarget",
    "LoudnessVerification",
    "ModelRef",
    "OrderedInput",
    "PanLaw",
    "PlanProvenance",
    "PostBatchClip",
    "PostBatchPlanner",
    "PostBatchResult",
    "PostChain",
    "PostChainResult",
    "PostContext",
    "PostError",
    "PostStageResult",
    "PreservationProof",
    "PreservationVerdict",
    "PresetRegistry",
    "ProcessingPresetRef",
    "ProfileRef",
    "PronunciationDictionary",
    "PronunciationOverride",
    "Prosody",
    "RecordBase",
    "RenderFingerprint",
    "RetentionPolicy",
    "Routing",
    "SampleFormat",
    "SeamlessLoop",
    "SendReturn",
    "Sha256",
    "SoundContractError",
    "SoundPlan",
    "SoundReceipt",
    "SoundReceiptSection",
    "StemLayout",
    "StemRecombinationPolicy",
    "TimeBase",
    "Timeline",
    "ToolchainVersion",
    "Track",
    "Transformation",
    "TtsAdapter",
    "VoiceBatchPlanner",
    "VoiceBatchResult",
    "VoiceError",
    "VoiceRoster",
    "VoiceSlot",
    "WorldAssetCatalog",
    "WorldError",
    "canonical_digest",
    "canonical_record_id",
    "contract_error",
    "default_voice_roster",
    "location_violation",
]
