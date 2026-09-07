# Verified sound mastering

`sound_master_render` uses installed FFmpeg to normalize a supplied mono PCM16
WAV in two passes. It measures the final decoded audio and publishes a new ZIP
only when loudness, true peak, output format and frame count satisfy the request.
It requires real input; there is no implicit demo or model download.

```json
{
  "schema_version": 1,
  "source": {"path": "mix.wav", "sha256": "sha256:<actual lowercase digest>"},
  "output_path": "mastered.zip",
  "output_sample_rate_hz": 44100
}
```

```python
from kinocut import Client
result = Client().sound_master_render(request, project_root="/your/project")
```

```bash
kino --format json sound-master-render --request-json request.json --project-root .
kino --format json sound master-render --request-json request.json --project-root .
```

The MCP tool takes the same `request` object and explicit `project_root`.
Input and output paths are project-relative. Existing output is never replaced;
choose a new filename for a new run. Parent directories must already exist.

The optional `delivery` is a `DeliveryPolicy`. Its numeric loudness target and
tolerance are authoritative, along with the stricter of its two true-peak
ceilings. The preset label is informational identity; it is not certification.
Nonempty stems, nondefault recombination, metadata codes and master-only limiting
intent are rejected. This operation masters one supplied mix and does not produce
or verify stems or distribution metadata.

FFmpeg may use linear or dynamic normalization. Dynamic processing is permitted
by this operation and disclosed as `normalization_type` in the receipt. The
renderer reserves 0.2 dB below the requested peak ceiling where FFmpeg's range
allows, but final acceptance uses the original policy with no extra allowance.
This margin is not a guarantee; unmet final targets return `master_target_unmet`
without publishing a ZIP. No additional compressor or repeated correction loop
is applied. Integrated targets must be −70 to −5 LUFS and effective peak ceilings
−9 to 0 dBTP; material must yield a finite gated measurement.

The ZIP contains `master.wav` and `receipt.json`. The receipt binds request,
source, policy and final-media hashes; backend version; actual normalization mode;
internal and requested peak limits; measured loudness, true peak and range; and
input/output sample counts and rates. The completed archive is verified before
exclusive publication. `timing_proof=frame_count_only` does not claim universal
alignment or human listening acceptance. Listen to the retained master before
release, especially when dynamic normalization was applied.

Input supports 8–96 kHz mono PCM16, at least three seconds and at most one hour.
The output rate defaults to the input rate. Input/output bytes and an eight-times
combined-size memory estimate are bounded by the existing mix limits. The output
must have exactly `round(input_frames * output_rate / input_rate)` frames; even a
successful FFmpeg exit is rejected if a size cap truncated its output.

One 180-second job budget covers analysis, rendering, final metering and archive
verification. Diagnostic capture is bounded at 64 KiB. Deadlines are checked
around synchronous file work and passed as remaining time to subprocesses.
Timeout and repeated cancellation retain ownership of the direct child until
reaped, then remove private files and staging. The filesystem protections require
descriptor-relative no-follow operations and fail when unavailable; they do not
claim a disk quota or defense against a malicious replacement FFmpeg binary.
