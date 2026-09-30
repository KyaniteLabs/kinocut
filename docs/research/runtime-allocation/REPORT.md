# Runtime allocation and optimization research

**Latest checkpoint:** [Iteration 2 implementation](iteration-2/IMPLEMENTATION.md)
records subsequent fixes, current ASR/Jev research and validation. The baseline
and first-iteration observations below are historical; use iteration 2 for
current working-tree allocation and remaining issues.

Baseline: `a820bd42205e43ca81eebc435e8529b2d0d42fcc` (master).

## Allocation

| Category | Counted source bytes | Share |
| --- | ---: | ---: |
| Deterministic code | 2,624,930 | 96.9014% |
| Operational prose for LLMs | 72,271 | 2.6679% |
| Traditional/non-LLM ML integration | 11,666 | 0.4307% |
| Total | 2,708,867 | 100.0000% |

This is an exhaustive **static inventory of the selected runtime sources**, not
a measurement of CPU time, token spending, model size, execution frequency, or
the percentage of useful work performed by each approach. All 1,431 tracked
files were inventoried; 616 first-party runtime source files were classified.
Automated source inspection covers every selected source; it does not mean a
line-by-line human review of every file. Model execution can dominate a job
despite its small authored-source share.

The denominator contains non-comment Python tokens excluding ordinary
docstrings, plus non-whitespace source from the small JS/TS/shell runtime.
Actual registered MCP tool/resource descriptions, parameter-schema descriptions,
server instructions and the optional Claude product-description prompt count
as operational LLM prose. MCP descriptions instruct an
external agent; they do not themselves invoke a model. Most prose here is that
interface metadata: only 119 bytes are the direct product-description prompt.
Deterministic SDK wiring is code. Function bodies that implement learned
inference or clustering are assigned to ML, including their local integration
logic; surrounding validation, schemas, orchestration and registration remain
code. This is a documented responsibility-based convention, not a claim that
every instruction inside a model wrapper is nondeterministic.

Whisper is a specialized speech model, not the general-purpose prompted LLM
category used here. Torch/ONNX neural models also belong to non-LLM ML. FFT,
RMS, loudness, hashes, thresholds, perceptual hashes, routing tables and DSP
are deterministic algorithms, even when housed in a module named `ai`.

Third-party library implementations, model weights, generated bundles,
lockfiles, tests, build scripts, documentation and example assets are outside
the operating-source denominator. The three public host SKILL.md files contain
another 23,193 raw bytes of prose, reported separately because a host interprets
them outside the runtime. Including those bytes as a separate sensitivity
view would produce approximately 96.0788% code, 3.4942% prose and 0.4270% ML;
raw Markdown bytes and source-token bytes have different normalization, so
that view is not the primary result. Creation style/storyboard templates are
inputs intended for external generative media providers; they are not evidence
of an executing in-process LLM or media-generation integration.

Reproduce from the repository root with:

```sh
.venv/bin/python scripts/audit-runtime-allocation.py --output /tmp/kinocut-allocation
```

While these changes are uncommitted, add `--baseline-head` to read changed
tracked source files from HEAD without replacing the checkout. The registered
MCP metadata must be unchanged for that mode; it is unchanged in this batch.

`allocation.json` records the classification manifest and limitations;
`runtime-allocation.csv` provides exclusive counts per source file;
`repository-inventory.csv` makes the included/excluded scope inspectable.

## Is the allocation appropriate?

There is no best-practice target percentage. Correct allocation is a decision
per capability, judged against accuracy, latency, memory, privacy, reproducibility
and cost. Kinocut's core separation is appropriate: execute media operations,
validate plans, enforce approval, bound resources, compute provenance and check
objective output properties with code. Do not replace those paths with agents.

| Capability and source | Current approach | Assessment / next action |
| --- | --- | --- |
| FFmpeg engines, workflow, contracts, receipts, remote approvals | Deterministic orchestration and validation | Appropriate. Preserve fail-closed checks and output contracts while reducing redundant work. |
| `intent/router.py`, `te/sphere_plan.py` | Tables/heuristics and validated plans | Appropriate default. An external model may propose creative plans; keep plan validation and execution in code. |
| `te/sphere_director.py` | Injected proposal callback, opt-in cloud, heuristic fallback | No built-in provider call. Treat proposals as untrusted input, not evidence of autonomous LLM direction. |
| `image_engine.py:extract_colors` | Seeded MiniBatchKMeans | Appropriate lightweight ML for palettes; RGB/HSL conversion, pixel counting and color naming remain code. |
| Whisper transcription / longform / sound ASR | Specialized learned ASR plus deterministic timing and chunk handling | Appropriate. Reuse model initialization per job; evaluate word accuracy/timestamps before changing decoding precision or model size. |
| Demucs, Basic Pitch | Specialized separation/pitch models | Appropriate for perceptual tasks. Assess real audio quality and memory before replacing them with heuristics or generic LLMs. |
| `object_matte`, FSRCNN/Real-ESRGAN, NIMA | Specialized visual inference | Appropriate opt-in tools. Evaluate edge quality, artifacts and ranking bias; keep integrity checks and bounded processing. |
| `image_engine.py:analyze_product(use_ai=True)` | Claude image description; colors already computed by code | Open-ended visual description is a reasonable VLM use. Avoid asking it to redo measured colors/counts; supply deterministic evidence if descriptions must agree with palette measurements. No need to call it for color-only analysis. |
| `watching/vision_qc.py` | Keyframe extraction; VLM scoring deferred | A structural `pass` is not proof of semantic correctness. Keep technical checks deterministic; use separately labeled subjective review or specialized detectors with evaluated accuracy. |
| `intent/caption_translate.py` | Small EN→ES replacement map | Suitable only for a limited fallback, not full translation. Substring replacement can corrupt unrelated words. Evaluate specialized local translation first; use an LLM only for nuanced adaptation requiring context. Do not label dictionary replacement as ML. |
| Creation templates / storyboard prompt expansion | Deterministic text assembly for external media generation | Appropriate assembly mechanism. The provider's generative model is external, and is not necessarily an LLM. |

Do not push prose towards zero: clear tool descriptions help an external agent
select the right deterministic tool. Conversely, increasing ML's source share
does not itself improve perception quality. Prefer measurable capability
boundaries: numeric/structural checks in code, trained perception in specialized
models, and optional semantic/creative interpretation in an LLM with explicit
proposals and review.

## Optimization method

Use a finite experimental cycle: identify redundant work; record a baseline;
change one mechanism; compare output equivalence and relevant failure behavior;
measure again; retain only supported improvements. Preserve public signatures,
media quality, safety checks and dependency floors. Measurements below are
local microbenchmarks, not whole-application speedup claims.

The immediate candidates are repeated WAV feature extraction across every
roster pair, repeated Whisper model loads across chunks, Python label counting
after clustering, and NIMA candidate files being removed before scoring. Real
model inference requires optional dependencies and verified weights; simulated
tests can prove lifecycle/call-count behavior but cannot establish real ASR
accuracy, throughput or GPU memory use.

## Retained experiments

All changes are local, uncommitted, and reviewable in the working tree. No
dependency declarations, lockfiles, public tool signatures, approval gates,
model checksums or media-quality settings were changed.

| Experiment | Retained mechanism | Evidence and limits |
| --- | --- | --- |
| Collision analysis | Extract each signal's features once per roster call, then compare cached feature tuples | The original and final full report hashes match for rosters of 4, 8 and 16. A 16-signal baseline median of 1.4062 s became 0.0851 s (16.52×). Pair output remains quadratic; expensive signal feature work changes from O(n² × signal length) to O(n × signal length). Cache lifetime is one call and holds features, not waveform buffers. |
| WAV parsing | Unpack little-endian PCM in a single standard-library call | On 1,048,576 samples the actual parser median fell from 0.1297 s to 0.00573 s (22.63×). This preserves signed sample values and rate; existing input validation remains. |
| Pitch feature window | Slice only the decimated samples that the 1,024-point analysis consumes | Traced temporary allocations during the feature calculation on the large fixture fell from 1,057,472 to 8,736 bytes. Non-silent baseline feature values are checked at 8, 16 and 48 kHz; existing small-fixture collision hashes also match. This does not eliminate the full decoded PCM tuple. |
| Color counting | NumPy histogram plus first-seen key ordering | On 40,000 labels, counting fell from 4.84 ms to 0.589 ms (8.22×). Counts and tie ordering match; KMeans parameters and image quality are unchanged. This is counting-stage speed, not an end-to-end image-analysis speedup. |
| Model/artifact hashing | Stream SHA-256 with Python 3.11+ `hashlib.file_digest` in model validation, rescue inspection/verification and sound bindings | For a 64 MiB model, traced Python allocation peak fell from 67,113,627 to 267,548 bytes (about 64 MiB to 261 KiB); median time improved from 77.7 to 60.3 ms. Matching digests and deletion on checksum failure are tested. Peaks exclude OS page cache and are not whole-process RSS. |
| Longform ASR setup | One Whisper model cache per transcription job, reused across chunks and released when the job ends | A two-job/two-chunk test observes two model loads rather than four, identical decoding options, and no retained model references after return. No global model cache was added. Real Whisper latency/accuracy and accelerator behavior are unmeasured. |
| NIMA thumbnail lifecycle | Keep candidate frames within a context until scoring completes; remove them on normal and exceptional exit | Real FFmpeg JPEG extraction plus an injected scorer verifies the files exist during scoring and disappear afterwards. Previously extraction's `finally` removed candidates before the scorer could open them. Real NIMA weights and subjective ranking quality remain untested. This is a correctness repair, not a claimed speedup. |

The initial/final measurements are retained in `collisions-before.json`,
`collisions-final.json`, `color-counts.json`, `hash-before.json`,
`hash-after.json`, `wav-before.json` and `wav-after.json`. A second,
same-session comparison against output-equivalent reference kernels is in
`optimization-benchmarks.json`; its ratios vary with timing noise and workload
content. Reproduce that comparison with:

```sh
.venv/bin/python scripts/benchmark-runtime-optimizations.py \
  --output /tmp/kinocut-benchmarks.json
```

These are synthetic local CPU microbenchmarks. They are not guarantees for
production media, model inference, GPU throughput, server concurrency, or
end-to-end latency. The benchmarks assert the relevant output equivalence
before comparing performance.

After the retained changes the same allocation method gives 96.8952% code,
2.6670% operational LLM prose and 0.4378% ML integration, totaling 100% after
rounding-residual adjustment. `allocation-after.json` records those source
counts. The small increase in ML integration bytes is model-cache plumbing,
not an additional model or a new nondeterministic capability.

## Validation checkpoint

- The broad selected core run passed **6,899 tests**, with **176 skipped**.
  Command: `UV_CACHE_DIR=/workspace/.cache/uv npm_config_cache=/workspace/.cache/npm
  .venv/bin/pytest tests/ -q -m 'not slow and not hyperframes and not network'
  --deselect tests/test_ai_features.py::test_resolve_video_source_platform_url_requires_ytdlp
  --deselect tests/test_ai_features.py::test_resolve_video_source_direct_url_no_extension_no_ytdlp
  --tb=short -n 4 --dist loadfile`.
- The two deselected tests are known baseline failures, not successful or
  skipped validations. They patch a re-exported `_is_safe_url` instead of the
  defining download module. The exact required fail-fast command
  `.venv/bin/python -m pytest tests/ -x -q --tb=short` reproduced the first
  failure after 173 passed and 9 skipped. Neither assertion nor URL protection
  was disabled or modified. No commit was created while this gate is failing.
- After that broad run, the final WAV/kernel changes passed **45 focused
  tests**, including architecture limits, baseline feature equivalence,
  resource lifecycle, and voice consistency. The final sound hash bindings
  passed their six dedicated join tests; the integration/benchmark/lifecycle
  group also passed 18 tests. These counts overlap and must not be added to
  the broad count. The broad suite was not rerun after those last small edits.
- Ruff checks and `git diff --check` pass on changed code and research tools.
  Canonical/compatibility client identity and required `kino doctor` checks
  pass. The inventory scan additionally parsed all **1,080 tracked Python
  sources**, including tests and supporting automation; static statistics are
  in `python-inspection.csv`. Parsing and inventory are not behavior tests.
- Slow, Hyperframes, live-network, and real optional-model quality benchmarks
  are not claimed as executed or passing. Model dependencies and weights for
  Whisper, Demucs, ONNX, NIMA, Basic Pitch and upscaling are absent in this
  instance; the optional Anthropic SDK and API binding are also absent.

## Next research prerequisites and priorities

This completes the source-allocation audit and a measured optimization batch.
It does **not** establish that every dimension of Kinocut is maximally
optimized. A global claim cannot be made from source size or microbenchmarks,
and improving every performance dimension simultaneously can conflict with
quality, memory, concurrency and portability.

The next model-level cycle needs a representative workload/media corpus,
acceptable quality thresholds, and a compute/model-download budget. Those
criteria determine whether smaller models, quantization, larger batches,
accelerators or altered frame sampling are acceptable. Supply credentials
only through secure environment settings if a cloud-provider benchmark is
selected; no API credential value is needed in chat.

With those criteria, prioritize end-to-end profiling of longform ASR, bounded
ONNX preprocessing/inference, NIMA selection, and native DSP/render filters.
Track word error rate and word timing for ASR; temporal edge stability for
mattes; artifacts for upscaling; ranking consistency for thumbnail selection;
and objective audio properties alongside peak RSS and wall time. Evaluate
dictionary-translation limitations and structural-versus-semantic QC labels as
correctness work, rather than obscuring them with additional LLM calls.
