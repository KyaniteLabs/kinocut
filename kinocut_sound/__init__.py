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
ducking envelope) live next to their owning modules and are exposed here for
adapter authors who need to reference them without reaching across modules.
"""

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
from kinocut_sound._errors import (
    INVALID_RECORD as INVALID_RECORD,
    UNSAFE_LOCATION as UNSAFE_LOCATION,
    UNKNOWN_RECORD_FIELD as UNKNOWN_RECORD_FIELD,
    SoundContractError as SoundContractError,
    contract_error as contract_error,
)
from kinocut_sound.capability import (
    ADAPTER_KINDS as ADAPTER_KINDS,
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
    DETERMINISM_CLASSES as DETERMINISM_CLASSES,
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
from kinocut_sound.timeline import (
    Cue as Cue,
    CueKind as CueKind,
    Timeline as Timeline,
)

__version__ = "0.1.0"

__all__ = [
    "ADAPTER_KINDS",
    "CHANNEL_COUNT",
    "DEFAULT_PRESET",
    "DETERMINISM_CLASSES",
    "INVALID_RECORD",
    "UNKNOWN_RECORD_FIELD",
    "UNSAFE_LOCATION",
    "AdapterDescriptor",
    "AdapterLocality",
    "AssetLicenseRef",
    "AudioFormat",
    "AuditEvent",
    "AutomationEnvelope",
    "AutomationPoint",
    "BlendAuthorization",
    "BoundedCode",
    "Bus",
    "CapabilityResult",
    "ChannelLayout",
    "CloudEgressGrant",
    "ConsentGrant",
    "ConsentScope",
    "ConsentState",
    "ConversionPolicy",
    "CostDisclosure",
    "Cue",
    "CueKind",
    "DeliveryPolicy",
    "DeliveryPreset",
    "DeterminismClass",
    "DitherPolicy",
    "DuckingSidechain",
    "Emotion",
    "FingerprintComponent",
    "FrozenModel",
    "LatencyCompensation",
    "Line",
    "LoudnessTarget",
    "LoudnessVerification",
    "ModelRef",
    "OrderedInput",
    "PanLaw",
    "PlanProvenance",
    "PreservationProof",
    "PreservationVerdict",
    "ProcessingPresetRef",
    "ProfileRef",
    "PronunciationOverride",
    "Prosody",
    "RecordBase",
    "RenderFingerprint",
    "RetentionPolicy",
    "Routing",
    "SampleFormat",
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
    "canonical_digest",
    "canonical_record_id",
    "contract_error",
    "location_violation",
]
