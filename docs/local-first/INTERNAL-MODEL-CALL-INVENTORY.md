# Internal model/ASR/vision call inventory (workstream C seed pass)

Scope: every kinocut-internal model / ASR / vision call at commit `e593881`
(+ security-gates branch), with what it calls, local-endpoint support today,
cloud-default exposure, and graceful-degradation behavior. File:line citations
are load-bearing; this is the map the hardening pass works from, not an audit
verdict. Verification pass per item follows in the full workstream.

Legend — **Local-endpoint support**: does the call site accept a LOCAL
OpenAI-compatible endpoint (org-engines Air `:8817` / mini `:8788`, LM Studio,
llama-server, Ollama) instead of a fixed cloud API? `yes` / `no` / `partial`.

## 1. ASR — Whisper transcription (library inference, local)

| What | Where |
|---|---|
| Call | `import whisper` → `whisper.load_model(model)` → `.transcribe()` |
| Sites | `kinocut/ai_engine/transcribe.py:173,205-215` (MCP `video_ai_transcribe`, `kinocut/server_tools_ai.py:47-60`); longform chunk path `kinocut/ai_engine/_longform_runtime.py:45-59`; longform entry `kinocut/ai_engine/transcribe_longform.py`; repurpose `video_repurpose_*` uses `whisper_model` param (`kinocut/server_tools_ai.py:67-117`) |
| Transport | In-process library (openai-whisper, torch). No HTTP. Model weights download once from the public whisper CDN into `~/.cache/whisper/` on first use; `kinocut/rescue/capabilities.py:26-28` probes that cache path |
| Local-endpoint | **yes (n/a-by-design)** — runs fully local; no endpoint involved. Not wired to the org-engines HTTP endpoints (no need today) |
| Cloud-default | none |
| Degradation | fail-closed with honest receipt: `dependency_error` / `code="missing_whisper"` + `suggested_action` install hint (`transcribe.py:175-186`, `_longform_runtime.py:47-58`); rescue lane gates the `openai-whisper` executor on a capability probe (`kinocut/rescue/policy.py:43-45`, `capabilities.py:76-91`) |
| Gap for hardening | offline-first: no pre-cache/seeding story for weights; small-model profiles (tiny/base) not receipt-compared for accuracy vs `large` |

## 2. Vision-language — image description (Claude Vision) — THE cloud path

| What | Where |
|---|---|
| Call | `anthropic.Anthropic(api_key=...)` → messages with image, `model="claude-sonnet-4-20250514"` |
| Sites | `kinocut/image_engine.py:318-347`; registered `kinocut/server_tools_image.py:69` (`use_ai` flag) and CLI `kinocut/cli/parser/image.py:34` (`--use-ai`) |
| Transport | Anthropic cloud HTTPS API |
| Local-endpoint | **no** — no `base_url` exposure; the SDK supports one but kinocut never passes it |
| Cloud-default | cloud WITHIN the feature, but the feature is opt-in (`use_ai=False` default; without it the local structural/EXIF description path runs). NOT cloud-default at the tool level |
| Degradation | fail-closed `missing_api_key` (`image_engine.py:333-338`) and package-missing install hint (`:318-322`) |
| Gap for hardening | the only true cloud-API call in the package: needs a `base_url`/OpenAI-compatible vision option and/or a local VLM path to reach 100% local-endpoint-first |

## 3. Vision QC (VLM-adjacent, structural default)

| What | Where |
|---|---|
| Call | none by default — ffmpeg keyframe sampling only; VLM never auto-called |
| Sites | `kinocut/watching/vision_qc.py:29` (availability probe = `anthropic` spec), `:95-135` (three-state receipt) |
| Local-endpoint | **partial by design** — receipts expose keyframe paths + `next_action: "call_provider_with_keyframe_paths"` for out-of-band VLM use |
| Cloud-default | none (no auto-call at all) |
| Degradation | exemplary honesty: `warn "VLM not installed; vision QC skipped (graceful)"` / `info "structural keyframe sample only"` / `info "rubric deferred to explicit provider call; keyframes ready"` with `auto_scored: False` (`vision_qc.py:97-131`) |

## 4. 360 sphere director (OpenAI-compatible director) — the local-first exemplar

| What | Where |
|---|---|
| Call | injected `DirectorFn` or detected director endpoint; heuristic plan always computed first |
| Sites | `kinocut/te/sphere_director.py:20-24` (env `KINOCUT_360_DIRECTOR`, `_MODEL`, `_BASE_URL`, `_ALLOW_CLOUD`), `:55-93` (`apply_director`), `:126` (`local` vs `cloud` host classification); `kinocut/te/sphere_assembly.py:67,88` (base_url pass-through); cloud ids `kinocut/validation.py:47` |
| Local-endpoint | **yes** — `base_url` param + env; local hostnames classified `local` |
| Cloud-default | **no — cloud blocked by default**: `allow_cloud: bool = False` + `_assert_cloud_allowed` (`sphere_director.py:57,61`); "Never used at render time" |
| Degradation | heuristic fallback with honest writer receipt (`kind: heuristic|model`, `unavailable: True, reason: capability_unavailable` on failure, `:63-92`) |
| Note | this is the pattern workstream C should replicate across every model-facing feature |

## 5. Aesthetic scoring — NIMA (local torch)

| What | Where |
|---|---|
| Call | lazy `import torch`/`torchvision`, VGG16 NIMA head, local `.pth` weights |
| Sites | `kinocut/aesthetic/__init__.py:38-53` (lazy import + install hint), `:52-62` (weights searched in local HF cache + repo dir), `:123-128` (missing weights → explicit download instruction, NO auto-download) |
| Local-endpoint | **yes (n/a)** — in-process local inference |
| Cloud-default | none (weights fetched manually, once, by the operator) |
| Degradation | `kinocut/aesthetic/smart_thumbnail.py:36-47` — NIMA unavailable/failing → deterministic `_default_timestamp` fallback with logged warning; honest at the call site |

## 6. Upscale — FSRCNN via OpenCV DNN super-resolution (local)

| What | Where |
|---|---|
| Call | OpenCV `dnn_superres` with FSRCNN `.pb` models |
| Sites | `kinocut/ai_engine/upscale.py:26-27` (pinned SHA256), `:86-88` (model URLs = github Saafke/FSRCNN_Tensorflow), `:96-135` (download, 500 MiB cap, hash verify, `~/.cache/mcp-video/models` cache) |
| Local-endpoint | **yes (n/a)** — local CPU inference; weights downloaded once, integrity-pinned |
| Cloud-default | none at runtime (one-time weight fetch) |
| Degradation | integrity/size failures delete the file and fail closed (`integrity_error`) |

## 7. Stem separation — Demucs (local torch)

| What | Where |
|---|---|
| Call | demucs via importlib/subprocess wrapper |
| Sites | `kinocut/ai_engine/stem.py:66-87`; MCP registration `kinocut/server_tools_ai.py:150-165` |
| Local-endpoint | **yes (n/a)** — in-process/subprocess local |
| Cloud-default | none |
| Degradation | duration caps (`MAX_AUDIO_DURATION`) + `ProcessingError`; doctor probes torch/torchaudio/torchcodec as optional extras (`kinocut/doctor.py:105-112`) |
| Boundary | classical stem separation is NOT feasible — this stays a model extra (documented honesty item for workstream A) |

## 8. Object matte weights (local inference, pinned download)

| What | Where |
|---|---|
| Call | weights download with byte-size cap + SHA256 + MD5 triple check |
| Sites | `kinocut/object_matte/weights.py:40-53` (verify), `:57-77` (`OBJECT_MATTE_WEIGHTS_URL` download, capped copy) |
| Local-endpoint | **yes (n/a)** — local model file |
| Cloud-default | none at runtime |

## 9. Network surfaces that are NOT model calls (completeness)

- Media download: `kinocut/ai_engine/download.py:11-15` — `http.client` with IP-validation SSRF guard.
- Font download: `kinocut/font_manager.py:84` — `urlretrieve` for font assets.
- Hyperframes preview: `kinocut/hyperframes_engine.py:579` — `http://localhost:{port}` local dev server.
- Doctor / capability probes (no network): `kinocut/doctor.py:97-112` (optional extras incl. anthropic/whisper/torch), `kinocut/capability_report.py:30,42` (tool→dependency map).

## 10. Modules confirmed model-free (grep-verified, no torch/whisper/openai/anthropic/HTTP-model imports)

`ai_engine/color.py`, `ai_engine/scene.py`, `ai_engine/silence.py`, `ai_engine/spatial.py` (all ffmpeg `_run_command`/`_run_ffprobe_json` classical paths); `aivideo/review.py`, `aivideo/verdict.py`, `aivideo/salvage*.py`, `aivideo/subtitle_qa*.py`, `aivideo/learning/*` (deterministic advice/cost/outcomes/recipes); `engine_thumbnail`/`engine_storyboard` (deterministic ffmpeg; `kinocut/server_tools_ai.py:273-295`); `rescue/policy.py` + `rescue/capabilities.py` are probes/policy only.

## Verdict against workstream C acceptance

- **Cloud-default paths: 0 tool-level defaults.** The single cloud API surface (Claude Vision, §2) is opt-in (`use_ai=False` default) and fail-closed without a key — but it has **no local-endpoint path today**, which blocks "100% of calls mapped local-endpoint-first" until §2 gains `base_url`/OpenAI-compatible support or a local VLM alternative.
- Everything else is in-process local inference (weights fetched once, integrity-pinned where downloaded) with honest fail-closed receipts and — in four places (vision QC, sphere director, smart thumbnail, doctor) — graceful degradation that already meets the receipt-honesty bar.
- **Test posture**: no test requires `ANTHROPIC_API_KEY` or any cloud key (whisper/anthropic are optional extras probed, not assumed) — cloud-key-free tests hold at seed-pass level; the hardening pass must pin this with explicit no-cloud-key CI assertions.

*Seed pass by KINOCUT-PM, 2026-09-18. Full per-item verification (runtime evidence, not grep) follows in the workstream C hardening pass.*
