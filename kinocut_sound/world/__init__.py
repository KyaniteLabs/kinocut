"""``kinocut_sound.world`` — ambient assets, layers, loops, presets & Foley (S8).

The S8 leaf of the Sonic World audio-play production design. This sidecar
subpackage ships **inside** the ``kinocut_sound`` package but never imports any
``kinocut`` runtime module. It consumes the stable S1-S4 contracts
(:class:`AssetLicenseRef`, :class:`PlanProvenance`, :class:`CapabilityResult`,
:class:`AdapterDescriptor`, ...) and owns the M4 ambience/Foley/world-building
surface:

* :mod:`catalog`  — licensed ambient asset catalog with stable ids.
* :mod:`license`  — fail-closed license verification helpers.
* :mod:`layers`   — ambient layer stack with gain, mute/solo, ducking contract.
* :mod:`loop`     — seamless loop generator with loop-seam crossfade.
* :mod:`presets`  — per-location and per-deck sonic texture presets.
* :mod:`foley`    — Foley cue resolver against S4 cue ids.
* :mod:`audition` — audition contract and perceptual-QA receipt.
* :mod:`d41_port` — fake D41 bed/audition ports + descriptor-only cloud asset.

The real D41 binding (``audio-bed`` / ``bed-audition``) and the real cloud
asset generators wait for S13. This leaf defines the neutral typed interfaces
and local fake adapters only.
"""

from __future__ import annotations

from kinocut_sound.world._errors import (
    AUDITION_INVALID as AUDITION_INVALID,
    CATALOG_INVALID as CATALOG_INVALID,
    LAYER_STACK_INVALID as LAYER_STACK_INVALID,
    LOOP_INVALID as LOOP_INVALID,
    PORT_UNAVAILABLE as PORT_UNAVAILABLE,
    PRESET_INVALID as PRESET_INVALID,
    UNLICENSED_ASSET as UNLICENSED_ASSET,
    UNKNOWN_ASSET as UNKNOWN_ASSET,
    UNKNOWN_FOLEY_CUE as UNKNOWN_FOLEY_CUE,
    WorldError as WorldError,
    world_error as world_error,
)
from kinocut_sound.world.license import (
    LicenseVerifier as LicenseVerifier,
    LicenseVerdict as LicenseVerdict,
    verify_provenance_license as verify_provenance_license,
)
from kinocut_sound.world.catalog import (
    AssetProvenance as AssetProvenance,
    CatalogAsset as CatalogAsset,
    WorldAssetCatalog as WorldAssetCatalog,
    WorldAssetKind as WorldAssetKind,
)
from kinocut_sound.world.layers import (
    AmbientLayer as AmbientLayer,
    DEFAULT_LAYER_DUCKING_ATTACK_MS as DEFAULT_LAYER_DUCKING_ATTACK_MS,
    DEFAULT_LAYER_DUCKING_ATTENUATION_DB as DEFAULT_LAYER_DUCKING_ATTENUATION_DB,
    DEFAULT_LAYER_DUCKING_RECOVERY_MS as DEFAULT_LAYER_DUCKING_RECOVERY_MS,
    DEFAULT_LAYER_DUCKING_RELEASE_MS as DEFAULT_LAYER_DUCKING_RELEASE_MS,
    DuckingContract as DuckingContract,
    LayerMixResult as LayerMixResult,
    LayerStack as LayerStack,
)
from kinocut_sound.world.loop import (
    LoopResult as LoopResult,
    SceneCrossfade as SceneCrossfade,
    SeamReport as SeamReport,
    SeamlessLoop as SeamlessLoop,
    generate_loop as generate_loop,
    scene_crossfade as scene_crossfade,
)
from kinocut_sound.world.presets import (
    DeckId as DeckId,
    DeckTexturePreset as DeckTexturePreset,
    LocationId as LocationId,
    LocationPreset as LocationPreset,
    PresetRegistry as PresetRegistry,
    default_preset_registry as default_preset_registry,
)
from kinocut_sound.world.foley import (
    FoleyBinding as FoleyBinding,
    FoleyBindingSpec as FoleyBindingSpec,
    FoleyResolver as FoleyResolver,
    bindings_from_parsed_script as bindings_from_parsed_script,
)
from kinocut_sound.world.audition import (
    AuditionContext as AuditionContext,
    AuditionContract as AuditionContract,
    AuditionReceipt as AuditionReceipt,
    AuditionRequest as AuditionRequest,
)
from kinocut_sound.world.d41_port import (
    BedDescriptor as BedDescriptor,
    BedKind as BedKind,
    BedPort as BedPort,
    BedSpec as BedSpec,
    CLOUD_ASSET_ADAPTER_ID as CLOUD_ASSET_ADAPTER_ID,
    CloudAssetAdapter as CloudAssetAdapter,
    D41_AUDITION_FAKE_ADAPTER_ID as D41_AUDITION_FAKE_ADAPTER_ID,
    D41_BED_FAKE_ADAPTER_ID as D41_BED_FAKE_ADAPTER_ID,
    FakeD41Port as FakeD41Port,
    LOCAL_ASSET_ADAPTER_ID as LOCAL_ASSET_ADAPTER_ID,
    LocalFakeAssetAdapter as LocalFakeAssetAdapter,
    LocalFakeAuditionAdapter as LocalFakeAuditionAdapter,
    LocalFakeBedAdapter as LocalFakeBedAdapter,
    AuditionPort as AuditionPort,
    AuditionReelResult as AuditionReelResult,
    default_fake_d41_port as default_fake_d41_port,
)

__all__ = [
    "AUDITION_INVALID",
    "CATALOG_INVALID",
    "CLOUD_ASSET_ADAPTER_ID",
    "D41_AUDITION_FAKE_ADAPTER_ID",
    "D41_BED_FAKE_ADAPTER_ID",
    "DEFAULT_LAYER_DUCKING_ATTACK_MS",
    "DEFAULT_LAYER_DUCKING_ATTENUATION_DB",
    "DEFAULT_LAYER_DUCKING_RECOVERY_MS",
    "DEFAULT_LAYER_DUCKING_RELEASE_MS",
    "LAYER_STACK_INVALID",
    "LOCAL_ASSET_ADAPTER_ID",
    "LOOP_INVALID",
    "PORT_UNAVAILABLE",
    "PRESET_INVALID",
    "UNKNOWN_ASSET",
    "UNKNOWN_FOLEY_CUE",
    "UNLICENSED_ASSET",
    "AmbientLayer",
    "AssetProvenance",
    "AuditionContext",
    "AuditionContract",
    "AuditionPort",
    "AuditionReceipt",
    "AuditionReelResult",
    "AuditionRequest",
    "BedDescriptor",
    "BedKind",
    "BedPort",
    "BedSpec",
    "CatalogAsset",
    "CloudAssetAdapter",
    "DeckId",
    "DeckTexturePreset",
    "FakeD41Port",
    "FoleyBinding",
    "FoleyBindingSpec",
    "FoleyResolver",
    "LayerMixResult",
    "LayerStack",
    "LicenseVerdict",
    "LicenseVerifier",
    "LocalFakeAssetAdapter",
    "LocalFakeAuditionAdapter",
    "LocalFakeBedAdapter",
    "LocationId",
    "LocationPreset",
    "LoopResult",
    "PresetRegistry",
    "SceneCrossfade",
    "SeamReport",
    "SeamlessLoop",
    "WorldAssetCatalog",
    "WorldAssetKind",
    "WorldError",
    "bindings_from_parsed_script",
    "default_fake_d41_port",
    "default_preset_registry",
    "generate_loop",
    "scene_crossfade",
    "verify_provenance_license",
    "world_error",
]
