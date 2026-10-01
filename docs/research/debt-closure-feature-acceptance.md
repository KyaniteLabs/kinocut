# Motion, vision, and voice evidence closeout

This change completes source-bound motion review and an explicitly configured
semantic keyframe execution path. It also repairs voice evidence validation and
removes invented batch loudness certification. It does not certify unavailable
models, providers, hardware, or human viewing.

## Whole-film motion acceptance (#583)

The existing temporal decoder remains the only measurement stack. Its report
retains chronological luma-change windows, rate lurches, sustained high change,
calm-to-high intervals, isolated transition candidates, thresholds, source hash,
duration, and bounded decode coverage. New `review_items` identify every flagged
interval and potential cut with a stable digest.

The new Python client operation records a separate reviewer's attestation:

```python
from kinocut import Client
from kinocut.semantic.models import canonical_digest

# motion is the motion_coherence report returned by complete temporal inspection.
# final_film is the exact assembled media used for that inspection.
# The reviewer must actually watch the complete film before recording this.
receipt = Client().record_motion_acceptance(
    motion,
    input_path=final_film,
    reviewer_id="human:editor",
    source_sha256=motion["source_sha256"],
    report_sha256=canonical_digest(motion),
    watched_intervals=[{"start": 0.0, "end": motion["expected_media_end"]}],
    dispositions=reviewer_dispositions,
    verdict="accept",
)
```

`reviewer_dispositions` maps every `review_items[*].review_id` to an explicit
judgment. Rate findings accept `purposeful_motion` or `needs_fix`; transition
candidates accept `intended_cut` or `needs_fix`. An acceptance cannot contain
`needs_fix`. A `reject` receipt may preserve unresolved findings. Calm footage
without findings still requires complete viewing; calm is never automatically
rejected for its low image-change rate.

The operation rejects source replacement, a stale report/source digest,
unbound observations, incomplete/corrupt/truncated decode evidence, viewing
gaps, excess viewing intervals, missing/extra dispositions, and invalid numbers.
Complete-decode labels do not override contradictory measurements: media end,
decoded coverage, difference coverage through the last observed timestamp,
frame count, and absence of unmeasured/corrupt intervals must agree. The final
frame's duration is included in decoded coverage, while difference coverage
ends at that frame's timestamp. Strict producer schemas reject malformed,
nonfinite, out-of-film, and unordered finding/transition spans before hashing.
Receipts include an independently reproducible digest. They do not modify the
measurement report or grant audio, semantic-model, release, or overall film
acceptance. `attestation_verified_by_system` is false: software verifies coverage
and binding of the assertion, not that a human really watched the movie.

Acceptance controls cover calm film, steady change, repeated rate lurches,
sustained high change, freeze-to-high change, and intended cuts. Observation
fixtures exercise rate predicates and explicit purposeful-motion exceptions.
Actual four-second decoded media fixtures additionally exercise calm/cut
classification, source binding, duration, and review integration. The proxy
cannot establish camera speed, purposeful movement, or artistic intent; those
remain explicit human decisions rather than falsely automated judgments.

## Semantic vision provider integration

Explicitly set both
`KINOCUT_VISION_MODEL` to an Anthropic model available to the account and
`ANTHROPIC_API_KEY` using the host's secret mechanism. No model is selected by
default. Installing an SDK or setting an API key alone cannot trigger a paid
request. The bounded standard-library transport requires no optional SDK;
`vlm_package_installed` is informational. Existing `run_vision_qc`,
`video_qc_vision`, and CLI vision calls share
the executor; no new MCP tool is registered.

The operation performs at most one request with no retries, inside a worker
process with a hard 60-second elapsed deadline (plus bounded process cleanup),
and a 1,024-token output budget. Sample count is limited to 12;
timestamps must be unique, finite, numeric, and within the existing media-duration
limit. Extracted JPEG dimensions are bounded to 1,280 on either axis and frames
are rejected above 2 MiB. Request JSON is ceiling-bounded, held in a private
owned directory with a mode-0600 file, and removed after success, failure, or
timeout. Successful HTTP response bodies are capped at 64 KiB while reading,
before UTF-8 or JSON decoding. Error bodies are closed unread. Redirects and
compressed responses are rejected; credentials and media never move to a
redirect target. Its strict schema
rejects extra fields, inconsistent verdicts, unsampled timestamps, invalid
numbers, and excessive findings/text. Truncated responses, malformed output,
provider failures, and timeouts cannot produce a semantic pass.

An evaluated result is scoped to sampled frames and never grants whole-film
acceptance. Required but unavailable/inconclusive/failed assessment is blocked.
The source hash and unchanged-file identity bind evidence to the inspected film;
source replacement during sampling/assessment invalidates a provider pass.
Image text is treated as untrusted evidence, and no model output executes edits
or tools. Error reports/logs expose error classes, not provider exception bodies
or credentials.

Prepared JPEGs remain caller-owned review artifacts, because deferred host
review needs readable paths. Remove the returned keyframe directory after that
review finishes; do not delete unrelated temporary directories. A failed
extraction with no valid keyframes cleans its owned directory automatically.
The frame byte ceiling is checked after encoding, while the dimension and sample
ceilings bound produced artifacts; it is not a hard filesystem quota.

Provider tests use a local worker transport fixture, bounded fake HTTP bodies,
actual safe local hanging/trickling child processes, and synthetic response JSON,
not the production paid API. They prove bounded invocation, connection closure,
schema/failure handling, predecode response limits, hard deadlines, request
cleanup, source binding, and integration. Real provider quality,
account permissions/model availability, and production service behavior remain
unverified without configured credentials and representative human labels.

## Voice evidence correctness

The standalone voice batch previously ignored all clips and emitted fixed
`-16 LUFS`, `-1 dBTP`, and `within_tolerance=True` as if they were measured. This
could incorrectly certify delivery compliance. It now emits `loudness=null`,
`loudness_assessment_status="not_evaluated"`, and `loudness_not_evaluated` in the
receipt warning list. A collection of separate TTS clips is not an assembled
program; final-master loudness QA remains the measurement authority.

`SoundReceiptSection` preserves old measured payloads with the default
`loudness_assessment_status="measured"`. Serialization omits that implicit
measured status to preserve the exact historic serialized shape and canonical
identity, including nested receipts. Explicit unmeasured payloads round-trip
with null evidence. Contradictory status/evidence combinations are rejected.
Consumers must inspect the status before reading numeric loudness fields.
Measured final-master/audio QA paths keep their actual finite measurements.

An additional safe local fixture reproduced a malformed D42 style backend
returning `similarity=NaN` and receiving `drift=False`. Both style and identity
facades now reject nonfinite, coerced, boolean, and out-of-range similarity.
Huge integers are range-checked before float conversion. Generated drift flags
cannot exceed the result flag ceiling or duplicate a backend-provided drift flag.
Style results also validate the profile, drift boolean, bounded tuple of flags,
and retain backend-detected drift even when scalar similarity exceeds threshold.
Existing calibrated ports remain injectable through `KinocutD42Port`; content
hash equality does not become speaker or style recognition.

No calibrated perceptual identity/style backend or labeled calibration corpus
is supplied by this environment. Default host ports still truthfully report
unavailable, and required perceptual checks fail closed. Hashes, synthetic TTS,
spectral heuristics, and fixture ports are not substitutes for calibration.

## Validation

Focused gate after independent review: 326 passed in 35.33 seconds across motion acceptance/coherence,
vision assessment/provider contracts, voice provider evidence, standalone voice
batch/receipt/consistency, host joins, temporal inspection, and the full Python
client suite. The final direct-provider timestamp guard receives a
separate focused rerun; the frozen-source full gate belongs to the overall
branch validation receipt. Ruff checks passed for all owned changes, and a physical AST
scan found no owned function above 80 lines or module above 800 lines.

The parent orchestration owns the frozen-source full test gate, independent
review, CI, commits, and merge evidence. No real semantic API quality benchmark,
real perceptual voice calibration, or human full-film review is claimed by these
automated fixture tests.
