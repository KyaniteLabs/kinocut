# AI-video Inspection

> **Lifecycle status (2026-07-12):** implemented on the incomplete draft branch and under
> review. Findings support human decisions; they do not assert creative approval or authorize
> release.

Kinocut's Wave-2 inspection flow binds every report and visual artifact to immutable source
bytes in a private project store.

## Flow

1. `video_ingest(project_dir, source_path, lineage?, usage_rights_status?,
   usage_rights_evidence_ref?)` validates generation/rights metadata, copies the original
   into the content-addressed store, and returns its authoritative `asset_id`.
2. `video_preflight(project_dir, asset_id)` records streams, codecs, dimensions, frame rate,
   rotation, loudness, color measurements, and a full-decode integrity result.
3. `video_inspect_temporal(project_dir, asset_id, declared_regions?)` samples the decoded
   0/25/50/75/95/last frame policy, creates audible and muted previews, a motion strip,
   normalized text/logo region crops, and frame-difference evidence, records deterministic
   findings, reports provider availability, and persists one canonical `InspectionPackage`.

Temporal bounds come from decoded video packets, not the container or audio duration, so a
longer audio track cannot extend findings or optional-provider analysis past playable video.

The MCP, Python, and CLI surfaces call the same adapter and return the same JSON-compatible
success envelope. `video_preflight` and `video_inspect_temporal` resolve only the unique active
stored record. They reject missing projects, unknown or ambiguous assets, symlinked store
components, missing originals, and invalid artifacts with stable errors that omit host paths.

## Examples

```bash
kino --format json video-ingest campaign-project incoming/clip.mov
kino --format json video-preflight campaign-project sha256:...
kino --format json video-inspect-temporal campaign-project sha256:...
```

```python
from kinocut import Client

client = Client()
asset = client.ingest("campaign-project", "incoming/clip.mov")
inspection = client.inspect_temporal("campaign-project", asset["asset_id"])
```

Optional visual analyzers are fail-soft and code-registered. The default public operation
performs no provider call, network access, dynamic import, or model download; it returns
typed `provider_not_configured` capability results while keeping the deterministic package
complete.
