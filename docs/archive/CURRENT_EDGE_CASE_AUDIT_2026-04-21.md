# Current Edge Case & Failure Mode Audit

> **Historical document.** Remotion was removed in v1.3.0/v1.3.1. This audit is preserved for reference only.
>
> Scope: current `master` at `b1cc7126ae11a5f6382f6ea50bccfb643140f51b` after PRs #131-#138.
>
> Purpose: supersede the earlier `EDGE_CASE_AUDIT_BACKLOG.md` snapshot by separating fixed items from issues still visible in the current codebase.
>
> Method: repository inspection only. Evidence below cites current file paths and line ranges.

---

## Executive summary

The prior P0 security pass was largely completed: output path validation now exists and is broadly called, input path validation return values are carried through many engine paths, FFmpeg numeric interpolation is much more consistently sanitized, direct/yt-dlp downloads have timeout and size limits, progress reporting no longer hides callback errors, and the social preview image was replaced.

The remaining risks are now concentrated in a smaller set of areas:

1. **Residual SSRF DNS rebinding gap** — URL safety check and fetch still use separate resolutions.
2. **AI/resource bounds** — Whisper/Demucs now have direct model/duration/timeout guards, while upscale still needs deeper disk-space/temp-frame guard coverage.
3. **Client API contract consistency** — client-side empty-input validation has improved, but return-type consistency remains.
4. **Subprocess architecture cleanup** — many subprocess calls now have timeouts, but duplicated direct handling remains.

---

## Current priority findings

### P0 / release-blocking candidates

| ID | Status | Finding | Evidence | Recommended fix |
|---|---|---|---|---|
| C-P0-1 | Closed in follow-up branch | `engine_batch.video_batch()` previously created caller-provided `output_dir` without `_validate_output_path()` or canonical policy check. | Follow-up remediation validates `output_dir` before `os.makedirs()` and adds a null-byte regression test. | Keep regression coverage around batch output directories. |
| C-P0-2 | Removed | Remotion project scaffolding previously wrote project files under caller-provided `output_dir` + `name` without output-path validation. | Remotion integration completely removed in PR #163. `remotion_engine.py` and all related server/client/tests deleted. | N/A |
| C-P0-3 | Closed in follow-up branch | Direct URL download previously checked DNS before `urlopen()` but did not verify the connected peer address. | Follow-up remediation re-checks the peer IP from the opened response before reading bytes and rejects private/reserved peers. | Keep peer-IP regression coverage; future hardening can move to IP-pinned connects if needed. |

### P1 / next reliability sprint

| ID | Status | Finding | Evidence | Recommended fix |
|---|---|---|---|---|
| C-P1-1 | Closed in follow-up branch | Client `audio_compose()` previously forwarded empty `tracks` and non-positive `duration` to the engine. | Follow-up remediation adds `tracks` and `duration > 0` validation with client tests. | Keep client-side validation aligned with engine semantics. |
| C-P1-2 | Closed in follow-up branch | Client `add_text()` previously relied on deeper engine validation for empty text. | Follow-up remediation adds client-side empty/whitespace text validation before path/FFmpeg work. | Keep client validation fast and explicit. |
| C-P1-3 | Closed in follow-up branch | Client `text_animated()` previously forwarded empty text to FFmpeg-backed implementation. | Follow-up remediation adds client-side empty/whitespace text validation with tests. | Keep client validation fast and explicit. |
| C-P1-4 | Closed in follow-up branch | Demucs separation previously called `demucs.separate.main()` without an explicit timeout. | Follow-up remediation validates Demucs model names, enforces audio-duration bounds, and runs Demucs through a timeout-capable subprocess. | Keep timeout and model validation regression coverage. |
| C-P1-5 | Partial | Whisper model/duration guard is now present, but RAM-specific guard remains a future enhancement. | Follow-up remediation validates Whisper model names and enforces transcription duration bounds before extraction/model load. | Add memory/RAM-aware guard if Whisper resource telemetry becomes available. |
| C-P1-6 | Closed in follow-up branch | AI scene detection previously lacked AI-mode threshold validation and could extract unbounded frames for long videos. | Follow-up remediation validates threshold before mode branching, enforces the global video-duration limit, and caps AI frame extraction with `MAX_AI_SCENE_FRAMES`. | Keep threshold and frame-cap regression tests. |
| C-P1-7 | Closed in follow-up branch | Spatial audio simple path previously had unclear no-audio behavior and a private empty-position crash path. | Follow-up remediation validates audio streams before pan filters and rejects empty positions inside `_apply_simple_spatial()`. | Keep no-audio and empty-position regression tests. |

### P2 / robustness and cleanup

| ID | Status | Finding | Evidence | Recommended fix |
|---|---|---|---|---|
| C-P2-1 | Partial | Direct `subprocess.run()` handling remains duplicated in multiple modules. Most have timeouts now, but behavior/error shaping remains inconsistent. | Examples include `mcp_video/engine_audio_waveform.py:45`, `mcp_video/engine_compare_quality.py:80`, `mcp_video/engine_detect_scenes.py:48`, `mcp_video/engine_stabilize.py:92`, plus AI and design-quality modules. | Gradually route FFmpeg/ffprobe subprocesses through canonical helpers or focused wrappers; keep tests around error typing. |
| C-P2-2 | Partial | Temporary files with `delete=False` now mostly clean up, but this pattern remains and should stay under regression coverage. | Current cleanup evidence: `mcp_video/ai_engine/transcribe.py:117-119`, `mcp_video/ai_engine/stem.py:130-132`, `mcp_video/engine_runtime_utils.py:444-477`, `mcp_video/audio_engine/__init__.py:78-122`, `mcp_video/audio_engine/sequencing.py:100-115`. | Add regression tests or convert safe cases to `TemporaryDirectory`/managed temp paths. |
| C-P2-3 | Removed | `remotion_engine.py` previously used `subprocess.Popen()` directly without timeout/lifecycle review. | Remotion integration completely removed in PR #163. `remotion_engine.py` deleted. | N/A |
| C-P2-4 | Partial | Client mixin return types remain inconsistent: media methods return structured results, while audio/effects methods return raw `str` or `dict`. | `mcp_video/client/audio.py:90-134`, `mcp_video/client/effects.py:154-170`. Remotion client mixin deleted in PR #163. | Decide public contract, then standardize or document the exception explicitly. |
| C-P2-5 | Open | Optional dependency errors may still be inconsistent across lazy import surfaces. | Server/client tool layers perform many lazy imports; direct evidence requires a dependency-by-dependency test sweep. | Add tests for missing optional dependencies (`whisper`, `demucs`, `realesrgan`) and assert `dependency_error` where expected. |

---

## Prior backlog status map

Legend:

- **Closed**: current code directly shows the issue is addressed.
- **Partial**: current code shows meaningful remediation, but a narrower residual risk remains.
- **Open**: current code still shows the issue.
- **Superseded**: the original wording no longer matches current code, but a related item appears above.

| Old # | Prior issue | Current status | Notes / evidence |
|---:|---|---|---|
| 1 | Arbitrary file overwrite via unvalidated `output_path` | Mostly closed | `_validate_output_path()` exists and is widely called (`mcp_video/ffmpeg_helpers.py:36-54`; many engine call sites). Follow-up remediation closes the known batch/remotion write-surface gaps. |
| 2 | Arbitrary file writes in AI engine | Mostly closed | AI/transcribe/stem/audio output paths now call `_validate_output_path()` in observed write paths (`mcp_video/ai_engine/transcribe.py:105-108`, `mcp_video/ai_engine/stem.py:69-72`, `mcp_video/audio_engine/core.py:299-300`). Remotion project writes remain separate C-P0-2. |
| 3 | Unescaped numeric values in FFmpeg filter strings | Mostly closed | Current code uses `_sanitize_ffmpeg_number()` and/or `_escape_ffmpeg_filter_value()` in affected engine paths, e.g. `mcp_video/effects_engine/core.py:37-40`, `mcp_video/engine_fade.py:29-35`, `mcp_video/engine_timeline.py:189-228`. Keep future regression tests. |
| 4 | `_validate_input_path` resolved path discarded | Mostly closed | Many core engine paths now assign returned values, e.g. merge `mcp_video/engine_merge.py:45-66`, audio ops `mcp_video/engine_audio_ops.py:29-30`. Some server helpers still validate list members without assignment; lower risk if engines revalidate. |
| 5 | `_run_ffmpeg_with_progress` stderr deadlock | Closed | Reader thread and timeout wait are present in `mcp_video/engine_runtime_utils.py:371-418`; progress callback failures are propagated at `mcp_video/engine_runtime_utils.py:378-423`. |
| 6 | yt-dlp download has no timeout/size limit | Closed | Direct URL uses `urlopen(..., timeout=120)` and 2GiB cap (`mcp_video/ai_engine/download.py:130-148`); yt-dlp options include `socket_timeout` and `max_filesize` (`mcp_video/ai_engine/download.py:165-174`). |
| 7 | AI model download no timeout/size limit/atomic write | Mostly closed | `urlretrieve` no longer appears in `mcp_video`; model download path needs deeper resource-path testing but original primitive is gone. |
| 8 | AI upscaling OOM risk/no tiling | Partial | Upscale path has additional guards, but disk-space/temp-frame/resource limits remain worth targeted re-audit. |
| 9 | Temp file leaks | Mostly closed | Transcribe/stem temp WAVs are unlinked in finally blocks (`mcp_video/ai_engine/transcribe.py:117-119`, `mcp_video/ai_engine/stem.py:130-132`). Keep as regression watch item C-P2-2. |
| 10 | Raw exceptions from ffprobe parsing | Closed | Probe duration parsing was hardened in PR #132; current `engine_probe.py` includes parse fallbacks and tests in current suite. |
| 11 | Insecure design_quality auto-fix output construction | Closed | Auto-fix paths were changed away from raw `.replace()` pattern and input validation was added in PR #131; no raw `video_path.replace(".mp4"` pattern remains. |
| 12 | Missing design_quality input validation | Partial | Public check path validates `video_path`; internals still contain direct subprocess calls, so keep under subprocess wrapper cleanup. |
| 13 | Negative afade start time | Closed | `engine_audio_ops.py` now clamps/handles fade-out timing and validates input paths; covered by merged robustness work. |
| 14 | Subtitle generator ignores filename | Closed | `_write_srt()` supports file-style and directory-style `output_path` (`mcp_video/engine_subtitle_generate.py:97-113`). |
| 15 | SSRF check TOCTOU race | Closed in follow-up branch | See C-P0-3. |
| 16 | Silence detection accepts invalid params | Partial | Numeric sanitization exists (`mcp_video/ai_engine/silence.py:35-36`, `mcp_video/ai_engine/silence.py:101`), but semantic bounds should be tested explicitly. |
| 17 | ai_color_grade missing reference/FFmpeg errors | Closed | Reference path is validated (`mcp_video/ai_engine/color.py:65-69`) and reference analysis catches `ProcessingError` for neutral fallback (`mcp_video/ai_engine/color.py:203-205`). |
| 18 | Inconsistent client mixin return types | Open | See C-P2-4. |
| 19 | Missing client-side bounds/enum validation | Partial | Some media validations were added; remaining client gaps are C-P1-1 through C-P1-3. |
| 20 | Empty list/string client edge cases | Mostly closed | `merge([])`, `audio_sequence([])`, `add_text("")`, `text_animated("")`, and invalid `audio_compose()` inputs are covered after follow-up remediation. |
| 21 | Demucs runs without timeout | Closed in follow-up branch | See C-P1-4. |
| 22 | Whisper model/RAM guard | Partial | Model and duration guards are closed; RAM-specific guard remains. See C-P1-5. |
| 23 | AI scene threshold validation | Closed in follow-up branch | See C-P1-6. |
| 24 | `_generate_thumbnail_base64` missing input validation | Closed | Thumbnail helper validates and uses named timeout (`mcp_video/engine_runtime_utils.py:439-463`). |
| 25 | Hardcoded thumbnail timeout | Closed | `DOCTOR_COMMAND_TIMEOUT` is used for thumbnail probe generation (`mcp_video/engine_runtime_utils.py:26`, `mcp_video/engine_runtime_utils.py:463`). |
| 26 | Dead `_validate_input` | Closed | No `def _validate_input` remains in `mcp_video/engine_runtime_utils.py`. |
| 27 | Hardcoded timeout messages | Mostly closed | `"600 seconds"` no longer appears in `mcp_video`; remaining hardcoded timeout literals in non-FFmpeg contexts should be separately reviewed. |
| 28 | Concat demuxer path escaping | Partial | Merge path uses escaping; AI spatial/silence concat behavior needs targeted tests. |
| 29 | Unvalidated batch `output_dir` | Closed in follow-up branch | See C-P0-1. |
| 30 | Lazy imports return generic optional-dep errors | Open | See C-P2-5. |
| 31 | Missing remotion return type annotations | Removed | Remotion client mixin deleted in PR #163. |
| 32 | Lazy imports in client effects/audio | Open | Still present in `mcp_video/client/audio.py` and `mcp_video/client/effects.py`; classify as low-risk style debt. |
| 33 | `design_quality_check` vague return type | Open | Not re-audited in depth; should be checked with client quality contract cleanup. |
| 34 | Trailing comment in quality.py | Unknown | Not rechecked in this pass. |
| 35 | Font validation raw `os.path.isfile` | Closed | Text engine uses `_validate_input_path()` for explicit fonts in current code. |
| 36 | SRT text format safety | Partial | Newlines are normalized and `-->` is allowed as valid caption text; additional control-character policy may be optional. |
| 37 | `_sanitize_params` over-sanitizes future string params | Open | Current `engine_filters.py` still sanitizes every key except `preset`; future string params would fail. |
| 38 | Duplicated subprocess handling | Open | See C-P2-1. |
| 39 | Subprocess.Popen policy violation | Partial | `engine_runtime_utils.py` uses `Popen` with `wait(timeout=...)`; `remotion_engine.py` previously used `Popen` but was removed in PR #163. See C-P2-3. |
| 40 | AI scene temp bloat | Closed in follow-up branch | See C-P1-6. |
| 41 | AI upscale disk-space guard | Open | Needs targeted check for temp-frame path. |
| 42 | Spatial no-audio check | Closed in follow-up branch | See C-P1-7. |
| 43 | Spatial empty positions crash | Closed in follow-up branch | See C-P1-7. |

---

## Recommended next implementation bundle

Next high-value bundle after this follow-up branch:

1. Add deeper AI upscale disk-space/temp-frame guards.
2. Add RAM-aware Whisper guard if feasible from local metadata.
3. Add targeted tests around optional dependency and resource-bound behavior.

Subsequent cleanup bundle:

1. Standardize client return contracts or document intentional exceptions.
2. Gradually route direct FFmpeg/ffprobe subprocess handling through canonical helpers.
3. Re-audit AI upscaling disk/temp-frame resource guards.

