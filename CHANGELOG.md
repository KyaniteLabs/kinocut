# Changelog

All notable user-facing changes should be recorded here.

This project follows a simple release-note style:

- `Added` for new capabilities.
- `Changed` for behavior changes.
- `Fixed` for bug fixes.
- `Security` for vulnerability fixes.

## Unreleased

## 1.15.1 - 2026-08-31

Maintenance release: registry ownership plus the object-matte streaming port.

### Changed
- **mcp-video shim 1.6.12:** the compatibility shim carries the registry ownership marker, and the legacy `io.github.KyaniteLabs/mcp-video` registry entry was republished so directory listings (Glama, PulseMCP) point at living metadata (#469).
- **Object-matte streaming decode:** the object-matte engine now streams decode with scratch-directory caps — bounded memory on large inputs — with matching human-gate and product docs (#414, port of #412).

### Docs
- Colima warm-land recipe for CI landings, and the pinned tip SHA recorded after the #414 port (#415, #416).

## 1.15.0 - 2026-08-19

### Added
- **doctor `mcp-server-import` check:** `kino doctor` now imports the MCP server tool tree as a required core check, so it can no longer report OK while `kino --mcp` cannot start (#449, surfaced by #445).

### Changed
- **Honest MCP startup failures:** `kino --mcp` keeps the "requires the 'mcp' package" hint only when the `mcp` distribution is genuinely absent; any other server-tree import failure now prints its real cause — filesystem paths redacted, markup-safe — with a non-zero exit (#448, the second half of #445).
- **Windows test portability:** shebang-executable test stubs (fake ffmpeg/ffprobe, c2patool) skip explicitly on Windows instead of erroring at collection (#456, #450 complete).
- **Doctor import paths are platform-stable:** `kino doctor` reports the kinocut import origin with forward slashes on every OS so diagnostics compare and grep identically across Windows and POSIX.
- **UTF-8 console output:** the CLI reconfigures stdout/stderr to UTF-8 with replacement, fixing a hard `EncodeError` crash of `kino --help` on legacy cp1252 Windows consoles (caught by the new Windows CI job on its first run).

### Added
- **First-class Windows support:** portable projectstore file locking (`fcntl`/`msvcrt`) by [@gerardoscaglia-creator](https://github.com/gerardoscaglia-creator) (#446, landed with credit) — `kino --mcp` is importable on Windows; the lock backends enforce a contention-only error contract (permanent errors raise promptly; only genuine contention waits or maps to `BlockingIOError`) verified by cross-platform contract tests (#451).
- **Windows CI smoke job:** `windows-latest` runs lint, server-tree import checks, `kino doctor`, and the focused public-surface suite on every code change — Windows breakage can no longer land silently (#452).

### Fixed
- **Windows filter-option paths:** both FFmpeg unescaping passes escape filter-option paths correctly on Windows ([#458](https://github.com/KyaniteLabs/kinocut/pull/458) by [@pedropaav-art](https://github.com/pedropaav-art), merged with credit — item and credit backfilled 2026-08-31; the fix shipped in this release).

### Compatibility
- `mcp-video==1.6.11` installs `kinocut==1.15.0`.
- Published surface stays **196 MCP tools / 167 CLI commands**.

### Acknowledgements
- [@gerardoscaglia-creator](https://github.com/gerardoscaglia-creator) filed the Windows MCP-mode investigation ([#445](https://github.com/KyaniteLabs/kinocut/issues/445)) — the root-cause traceback in it exposed both diagnostics gaps fixed above — and contributed the portable file-locking fix ([#446](https://github.com/KyaniteLabs/kinocut/pull/446), landed on master with credit). Every fix in this release traces to that report. Bug reports with reproduction steps are contributions; thank you.
- [@pedropaav-art](https://github.com/pedropaav-art) contributed the Windows filter-option path escaping fix ([#458](https://github.com/KyaniteLabs/kinocut/pull/458)), which shipped in this release (credit backfilled 2026-08-31). Thank you.
- Kinocut's external community predates this release: betsmayank's merged Hyperframes no-TTY fix ([#361](https://github.com/KyaniteLabs/kinocut/pull/361)), austinwmson's `remotion_still` props report ([#306](https://github.com/KyaniteLabs/kinocut/issues/306)), ismailkattakath's self-host reference stack ([#432](https://github.com/KyaniteLabs/kinocut/issues/432)), and early PRs from Dodothereal and OyaAIProd. All of them shaped the product.

## 1.14.1 - 2026-08-13

### Fixed
- **GitHub Lint / pyright:** `_handle_cancellation` is `NoReturn` so `render_rescue` type-checks on the cancel path. No runtime behavior change.

### Compatibility
- `mcp-video==1.6.10` installs `kinocut==1.14.1`.
- Published surface stays **196 MCP tools / 167 CLI commands**.

## 1.14.0 - 2026-08-13

### Added
- **360 dual-cam assembly:** Any stitched equirect MP4 (Insta360, Ricoh Theta, GoPro MAX, DJI Osmo 360, …), not X4-only. `front_back` preset plus desk/table. Raw `.insv` / `.360` rejected by suffix. One ffprobe; no stitch. Operator guide: `docs/360_ASSEMBLY.md`.
- **360/perf committee top 10:** single-pass split/pip/switch `filter_complex`; sampled quality gate (`max_analyze_seconds`); lazy `mcp_video` (no star-import); SHA-256 path/mtime cache; merge `infos=` skip-reprobe; intermediate encode flags; doctor skips `npx --yes` unless Hyperframes is on PATH and runs command checks concurrently; batched 360 storyboard stills; lazy CLI handlers + doctor/info fast-path; lazy `mcp.types` on `Client.search_tools`.

### Changed
- **Lazy public import:** `import kinocut` no longer eagerly loads Client/engines (PEP 562). `from kinocut import Client` and `kinocut.Client is mcp_video.Client` still hold.
- **Ship-seam docs:** CLI/Client `repurpose` default `--min-score` 80 and `shorts-package --allow-fail` documented. MCP durable `video_repurpose` states that `min_score` is unused.
- **ROADMAP:** pre-1.13 archaeology moved to `docs/archive/roadmap-pre-1.13.md`.
- **360 docs pass:** operator guide plus NOW / SKILL / TOOLS / PYTHON_CLIENT / CLI / README / llms honesty (no 197th-tool claim).

### Compatibility
- `mcp-video==1.6.9` installs `kinocut==1.14.0`.
- Published surface stays **196 MCP tools / 167 CLI commands**. 360 assembly reuses `video_intent` / `video_review_decide` — it is not a 197th MCP tool.

## 1.13.4 - 2026-08-12

### Added
- **`video_cutfile_render` / `cutfile-render`:** public MCP + CLI surface for thin cutfile→workflow render (Track E).
- **`video_metric_qc` / `metric-qc`:** dedicated offline metric floor tool (Phase 3).
- **Edit session close + receipt:** `session_close` writes durable conversational receipts (Track E).
- **Phase 3/4/Track E formal GO suites** with real-media metric floor, mutation fail-closed apply, OTIO IR roundtrip, G004 synthetic phone-frame fixtures, MCPB production checklist.
- **Kinocut Video CI action** now emits metric-qc + optional cutfile-render receipts and a composite `video-ci.receipt.json`.

### Changed
- Published surface **196 MCP tools / 167 CLI commands**.
- Phase 3 Watching and Phase 4 Multipliers product gates marked **GO** with linked evidence (see `docs/status/PHASE_CHECKPOINTS.md`).
- Sound S14 live re-run on apple_silicon with honest `external_host_unavailable` for second class.

### Compatibility
- `mcp-video==1.6.8` installs `kinocut==1.13.4`.
- Mutations remain human-apply only (`human_apply_required` on silent apply).

## 1.13.3 - 2026-08-12

### Added

- **Cutfile thin library render:** `kinocut.te.render_cutfile` / `compile_cutfile_to_workflow` lower schema-valid cutfiles to the existing workflow engine (no new MCP/CLI surface; optional `DEF-cutfile-mcp`).
- **Golden-path timing harness:** `scripts/golden_path_timings.py` records cheap and full-path p50/p95 baselines (`docs/status/golden-path-timings.md`).

### Changed

- **Hyperframes ops size split:** Extracted helpers into `hyperframes_ops_helpers.py` so `hyperframes_ops` stays under the 800 LOC policy; architecture guardrail locks both modules.
- **Residual portfolio honesty:** ROADMAP / PHASE / HUMAN_GATES / DEFERRED ledger for agent vs human residuals; claim-ledger freeze rules documented.

### Fixed

- Cutfile v1 rejects `composite_layers` with a clear shape error; workflow specs use unique temp files to avoid concurrent overwrites.
- Ruff F541 in golden-path timings script (CI lint).

### Compatibility

- `pip install -U kinocut` to **1.13.3**. The `mcp-video` compatibility shim **1.6.7** installs `kinocut==1.13.3`.
- Published MCP/CLI counts remain **194 / 165** (no public surface expansion).
- Cutfile render is library-only until an explicit MCP/CLI claim.

## 1.13.2 - 2026-08-09

### Security

- **C2PA tool_path injection (CRITICAL):** Removed request-controlled `c2pa_tool_path` from the public MCP tool surface. The `c2patool` executable is now resolved exclusively from operator-controlled environment variables (`KINOCUT_C2PATOOL` / `MCP_VIDEO_C2PATOOL`).
- **C2PA signer_path injection (HIGH):** Removed request-controlled `c2pa_signer_path` from the public MCP tool surface. MCP signer configuration is server-side only.
- **DNS rebinding SSRF (HIGH):** HTTP downloads in `ai_engine/download.py` now connect only to addresses resolved and validated at connect time, closing a check-then-connect TOCTOU window that DNS rebinding could exploit to reach internal services; every redirect target is re-validated before following.
- **FFmpeg filter injection (HIGH):** Validated `style["size"]` interpolation in `engine_timeline.py` before passing to FFmpeg filter strings.
- **HLS path traversal (HIGH):** Added output-path containment check in `engine_hls.py` to prevent `playlist_name` escaping `output_dir`.
- **Symlink-swap race (HIGH):** `ffmpeg_helpers.py` now uses temp-file + atomic rename to close TOCTOU window on output paths.
- **Decompression bomb (HIGH):** `image_engine.py` enforces `MAX_IMAGE_PIXELS` ceiling (50 MP) before decoding.
- **Audio synthesis OOM (HIGH):** `audio_engine/synthesis.py` caps `MAX_SYNTHESIS_SAMPLES` (10 min @ 44.1 kHz stereo).
- **Predictable temp files (HIGH):** `server_tools_audio.py` uses exclusive per-request temp files instead of predictable `/tmp` names.
- **Batch output collision (HIGH):** `engine_batch.py` generates collision-resistant output names for same-named inputs from different directories.

### Fixed

- **Published MCP tool registration (regression):** Restored the full published MCP tool surface that regressed after the 1.13.1 module split, so every advertised tool registers and stays discoverable.
- **Hyperframes preview lifecycle:** Preview servers are now tracked in a registry, replace any preview already bound to the same port, register only after a successful startup, and are terminated (SIGTERM, escalating to SIGKILL) on exit or via explicit stop controls — preventing orphaned servers and leaked ports.
- **CLI JSON stderr warnings:** Structured JSON output stays clean so consumers parsing it are not broken by stray diagnostic noise on stderr (`server_app.py`).
- **Glitch shader typed errors:** Replaced raw `RuntimeError` in `engine_glitch_shader.py` with typed `MCPVideoError` codes (`missing_node`, `shader_render_failed`, `no_frames_extracted`, `too_many_frames`, `shader_no_output`).
- **signalstats failure-log leaks:** Redacted signalstats failure output in `quality_guardrails.py` so internal FFmpeg diagnostics are neither surfaced nor logged.

### Changed

- **Performance:** signalstats queries are batched into a single `ffprobe` pass; storyboard frames extract in a single FFmpeg pass; batch operations run on a bounded thread pool; audio-only inputs skip a redundant second `ffprobe`; and audio track mixing is vectorized with NumPy.
- **CI workflow:** Replaced `actions/checkout@v4` with authenticated manual `git clone` (Colima VM cannot reach `gitea.com`). FFmpeg matrix assets switched to `linuxarm64`. Lint routed to `light` label. Base image upgraded to `ubuntu:24.04` (Python 3.12).

### Compatibility

- **Breaking (security-driven):** The request-controlled `c2pa_tool_path` and `c2pa_signer_path` parameters are removed from the public MCP tool surface. The `c2patool` executable resolves from operator environment variables and signer configuration is server-side only; MCP callers that passed these parameters must move them to operator/server configuration.
- `pip install -U kinocut` to 1.13.2. The `mcp-video` compatibility shim **1.6.6** installs `kinocut==1.13.2`. The published surface remains **194 MCP tools / 165 CLI commands**.

## 1.13.1 - 2026-08-07

### Fixed

- **`add-audio --mix` amix normalization (issue #289):** `amix=inputs=2` applied FFmpeg's default `normalize=1`, scaling each input by 1/n (−6 dB for two tracks). Added `normalize=0` so both tracks sum at unity. Verified: base −21.1 dB → mixed −18.1 dB (3 dB louder, not 6 dB quieter).
- **GitHub Actions SHA bumps:** Ported Dependabot updates for `actions/checkout` (v7.0.1), `actions/setup-python` (v7.0.0), `actions/setup-node` (SHA bump), and `pypa/gh-action-pypi-publish` (SHA bump).

### Changed

- **Module split (WP-C):** Split `hyperframes_engine.py` (1302 → 629 LOC) and `workflow/executor.py` (1000 → 665 LOC) under the 800-LOC architecture ceiling. New modules: `hyperframes_ops.py` (794), `workflow/receipt.py` (391). PEP 562 `__getattr__` re-export preserves all existing import paths.
- **README:** Added dedicated Still / Image Editing section documenting the 8 image/still CLI commands, MCP tools, and Python client methods.

## 1.13.0 - 2026-08-07

### Added

- **Intent-verb surface (P2.5):** `video_intent` / `intent` routes ~10 semantic verbs to plans without silent media mutation.
- **B-roll proposals (P2.8):** `video_propose_broll` / `propose-broll` — human-reviewable only; never silent insert.
- **Caption translation ES-first (P2.9):** `video_translate_captions` / `translate-captions` + `video_language_coverage` honesty matrix (dub not claimed as available).
- **Watching guardrail floor (P3):** `video_review_run` / `review-run`, `video_review_decide` / `review-decide`, metric QC (blackdetect/LUFS), vision QC (graceful without VLM), narrative first-15s QC, `video_propose_mutations`.
- **Timeline IR validate/compile** via existing `kinocut.timeline_ir` + OTIO JSON bridge (`video_otio_export` / `video_otio_import`).
- **Phase-4 multipliers (plan-first):** generative spend-capped plan, review HTML surface, TTS dub plan (ES-first, non-executable until backend configured).
- **TE QoL / pillars:** `init`, `estimate`, `brand-kit`, `cutfile-validate`, publish-validate, hook-candidates, audiogram plan, punch-zoom plan, seek-frame, edit-session; `.github/actions/kinocut-video-ci`.
- Devcontainer, `Dockerfile.ci`, CI topology + MCPB gate docs, directory/launch/user program ops packs; community Funnel/OAuth deploy pointer.

### Changed

- Published surface grows to **194 MCP tools / 165 CLI commands** (from 169 / 145 in 1.12.0).
- Path validation hardened for caption translate, brand kit, and OTIO artifact writes.

### Security

- Subprocess metric probes use list argv + timeouts; spend caps fail closed for paid generative plans; b-roll/mutations remain human-apply only.

### Compatibility

- `pip install -U kinocut` to 1.13.0. The `mcp-video` compatibility shim **1.6.4** installs `kinocut==1.13.0`.
- **Not claimed:** live directory listings, first-10 real-user program completion, native signed MCPB public publish, or unbounded paid generation/TTS synthesis.

## 1.12.0 - 2026-08-07

### Added

- **Still/plate editor surface** across MCP, CLI, and Python client: `still_match` / `still-match`, `still_grade` / `still-grade`, `still_gate` / `still-gate`, `image_edit` / `image-edit`, and `still_package` / `still-package`.
- Package sequence match with one shared mean-RGB gain triple (no per-frame auto-WB; sources not overwritten).
- Ordered still grade (neutralize → match → optional 3D LUT last) with signal-mode near-extrema logging.
- Fail-closed cohesion gate (luma spread + shadow green/cyan) with contact sheet and named frame failures.
- `kino doctor` `still_plates` capability check; optional `kinocut[image]` stack documents Pillow + NumPy.
- Operator docs: [`docs/STILL_PLATES.md`](docs/STILL_PLATES.md).

### Changed

- Published surface grows to **169 MCP tools / 145 CLI commands** (from 161 / 140 in 1.11.x).
- `image-edit` intent is **audit metadata only** (`intent_policy=metadata_only`); v1 pixel path is establish mean-RGB match, not NL-driven generative edit.
- Pre-release honesty pass: no double exposure scale on match; signal-mode empty bands report null rather than 0.0.
- Runtime dependency pin: `mcp>=1.27.0,<2` so clean installs do not pull MCP Python SDK 2.x (which dropped `mcp.server.fastmcp`).

### Compatibility

- `pip install -U kinocut` to 1.12.0. The `mcp-video` compatibility shim **1.6.3** installs `kinocut==1.12.0` and forwards optional extras.
- **Not claimed:** NL intent as a pixel director, full color-science grade suite, native MCPB public publish, or post-release Phase 3–4/TE pillars.

## 1.11.1 - 2026-07-24

### Fixed

- Post-theme harden on the 1.11.0 sound public surface: every discovered operation has a real fail-closed invoke path; public results reject absolute host-path leakage; package/claims/distribution pins stay lockstep at 1.11.1.
- ProjectStore compatibility tests poll for `render.completed` after a resumed job succeeds (CI free-rider).

### Changed

- Published surface remains **161 MCP tools / 140 CLI commands** (no new tool family beyond 1.11.0).

### Compatibility

- `pip install -U kinocut` to 1.11.1. The `mcp-video` compatibility shim continues to install the matching Kinocut version.
- **Not claimed:** full-episode sound completion, protected-timeline kernel, native MCPB public publish, or G004 listening closure. G004 remains a human-only production claim gate for stream-shorts.

## 1.11.0 - 2026-07-24

### Added

- Thin `kinocut_sound` S12 public join across MCP, CLI, and Python client: `sound_capabilities` / `sound-capabilities`, `sound_plan_validate` / `sound-plan-validate`, `sound_voice_batch` / `sound-voice-batch`, `sound_mix_render` / `sound-mix-render`, `sound_qa_loudness` / `sound-qa-loudness`, and `sound_qa_asr` / `sound-qa-asr` (plus matching `kino sound <action>` namespaced aliases). Operators can discover and invoke a bounded local-first sound set without private imports.
- Public discovery stays aligned with invoke: no advertised sound operation raises unknown for a valid call.

### Changed

- Published surface grows to **161 MCP tools / 140 CLI commands** (from 155 / 134 in 1.10.x). Count tests, `CLIENT_METHOD_CONTRACTS`, and the thin `server.py` facade remain in lockstep.

### Compatibility

- `pip install -U kinocut` to 1.11.0. Does **not** claim full-episode sonic-world completion, kernel integration, or production stream-shorts listening (G004 remains human-open).

## 1.10.1 - 2026-07-24

### Fixed

- Stream-shorts package fails closed when draft video bytes diverge from the render-time content hash (`source_checksum_mismatch`), so operators cannot ship a swapped file under a trusted package path.
- Program ledger honesty free-rider: ROADMAP and post-1.10 status docs mark 1.9 policy engines and 1.10 shorts as publicized; open-loops manifest banner restates historical counts; G004 remains explicitly open.

### Changed

- Published surface remains **155 MCP tools / 134 CLI commands** (patch; no new public theme).

### Compatibility

- `pip install -U kinocut` to 1.10.1. Production stream-shorts acceptance still requires human listening / phone-frame review (G004).

## 1.10.0 - 2026-07-23

### Added

- Saved-plan stream-to-shorts stages across MCP, CLI, and Python client: `shorts_plan_show` / `shorts-plan-show`, `shorts_review` / `shorts-review`, `shorts_render` / `shorts-render`, and `shorts_package` / `shorts-package`. Operators can load a persisted plan, append fail-closed human review decisions, render platform drafts (YouTube Shorts / Instagram Reels) only after a current approve, and package local manifests without any network posting.
- Operator guide [`docs/STREAM_SHORTS.md`](docs/STREAM_SHORTS.md) and an honest acceptance-status proof under `docs/proofs/` (human listening remains an explicit gate for production claims).

### Changed

- Published surface grows to **155 MCP tools / 134 CLI commands** (from 150 / 129 in 1.9.0). Public claims, count tests, and the thin `server.py` facade remain in lockstep.
- Render and package stages require output roots under the plan `output_dir` (path containment).

### Compatibility

- `pip install -U kinocut` to 1.10.0. The `mcp-video` compatibility shim continues to install the matching Kinocut version; legacy `mcp_video` imports and env vars remain supported on the 1.10.x line.
- Stream-to-shorts is operator-available. Full production acceptance still requires human listening at edit boundaries and phone-frame visual review (see `docs/proofs/2026-07-24-stream-shorts-acceptance-status.md`).

## 1.9.0 - 2026-07-15

### Added

- Public MCP, CLI, and Python-client surfaces for eight release-artifact policy engines: `video_review_package`, `video_publish_gate`, `video_review_decision`, `video_learning_report`, `video_cost_ledger`, `video_recipe_capture`, `video_capabilities`, and `video_benchmark_run`. These expose the contract-first AI-video review, publish-gate, learning, cost, recipe, capability, and benchmark engines (previously internal records) to agents and operators across all three surfaces.

### Changed

- Published surface grew to **150 MCP tools / 129 CLI commands** (from 142 / 121 in 1.8.0). All parity invariants — count tests, public doc claims, the `CLIENT_METHOD_CONTRACTS` client registry, and the `server.py` thin-facade cap — were re-synced for the cutover.

## 1.8.0 - 2026-07-14

### Added

- Added the contract-first AI-video foundation: strict canonical records, append-only private project storage, immutable content-addressed ingest, unified media preflight, temporal evidence packages, deterministic defect findings, and fail-soft optional visual providers.
- Added governed AI-video review and salvage surfaces across MCP, Python, and CLI: exact-asset verdicts and acceptance evaluation, protected-element checks, audio-preserving body swap, and lineage-bound salvage derivatives that always require fresh review.
- Added loss-proof add-audio duration policies and authored ASS plus dimension-aware SRT/VTT subtitle rendering.
- Added public operating, status, provenance, verification, and parallel-execution documentation for the unfinished AI-video and `kinocut_sound` program.
- Added a path-based `skills/kinocut-repurpose` v1 skill, install notes, and a deterministic current-tools demo script for producing local short-clip repurpose packages without inventing commands or publishing externally.
- Optional C2PA provenance signing for final MP4 exports on the existing path-based `export` / `video_export` / `Client.export()` flow. Signing remains off by default and only reports `signed` after `c2patool` signs and a follow-up verification read succeeds.
- Added a staged Kinocut MCPB package (`mcpb/`) with a valid v0.4 manifest, Node stdio launcher, local build/validation script, user-facing install docs, and explicit release gates for bundled runtimes and runtime confinement.
- Added the fail-closed native MCPB builder foundation: strict digest-pinned runtime locks, bounded portable archive extraction, target-specific manifests, and a bundle-contained launcher. Native packages remain blocked from publication pending the documented FFmpeg provenance, licensing, and clean-machine gates.

### Changed

- Approved AI-video dispositions now require active exact human decisions with requirement-level evidence; analyzer output alone cannot create approval.
- Body-swap and salvage resolve verified stored source identities and reject stale, ambiguous, aliased, or protected inputs rather than trusting ambient paths.

### Fixed

- `hyperframes_init` no longer hangs when Kinocut runs as an MCP server. Project scaffolding now always invokes the Hyperframes CLI non-interactively and with `HYPERFRAMES_SKIP_SKILLS=1` (the CLI ignores the `--skip-skills` flag and otherwise runs a blocking network AI-skills check on `init`), and every Hyperframes subprocess is run with a closed stdin so a missing TTY can never block on an interactive prompt.

### Release preparation

### Fixed

- Public S14 benchmark receipts now use an explicit allowlist and exclude machine, processor, platform, notes, status, and unknown capability data.
- The staged MCPB identity and the `mcp-video` compatibility shim now align with Kinocut 1.8.0. Native MCPB bundles remain staged/local-only and are not published.
- Thanks to @betsmayank for the Hyperframes MCP no-TTY initialization fix (#361).

### Compatibility

- `mcp-video==1.6.2` is a metadata-only upgrade shim that installs `kinocut==1.8.0` and forwards every optional extra.

## 1.7.0 - 2026-07-10

### Added

- Kinocut is now the canonical Python distribution and import package, with `kino` and `kinocut` CLI commands alongside the preserved `mcp-video` command.
- The `kinocut` npm package provides a thin `uvx` launcher for the `kino` CLI, and the MCP Registry entry now publishes under the immutable `io.github.KyaniteLabs/kinocut` identity.
- The canonical `skills/kinocut` agent skill teaches both MCP and CLI workflows; `skills/mcp-video` remains as a compatibility pointer.

### Changed

- The project, repository links, documentation, package metadata, and public discovery surfaces now use the Kinocut name and `kinocut.dev` home.
- The implementation package moved from `mcp_video` to `kinocut`. New Python integrations should import from `kinocut`.
- Current documentation, examples, workflows, active plans, and research guidance now use canonical Kinocut names, paths, install commands, and the verified 135-tool/114-command surface. Dated evidence retains its historical identity with explicit snapshot notices.
- The documentation map separates current operating guidance from historical audits, proofs, and handoffs; local Markdown links and canonical naming are enforced by public-surface tests.

### Compatibility

- `mcp-video==1.6.1` is a metadata-only upgrade shim that installs `kinocut==1.7.0` and forwards every optional extra. Existing `mcp_video` imports, `mcp-video` commands, `MCP_VIDEO_*` environment variables, `~/.mcp-video` data, `mcp-video://` resource URIs, and receipt keys remain supported through at least Kinocut 1.8.x.
- Clean installs and in-place upgrades from `mcp-video==1.6.0` are exercised as release gates, including Python imports, all three CLI entry points, package metadata, and uninstall behavior.

### Fixed

- MCP Registry metadata now uses the registry-supported GitHub mirror URL, while Forgejo remains canonical everywhere else. The publish workflow also supports a registry-only recovery dispatch, so a downstream registry rejection can be repaired without attempting to re-upload an immutable PyPI release.
- The MCP stdio handshake now reports `kinocut` as the server name instead of the retired project name.
- Contribution, testing, licensing, design-standard, integration, workflow, and agent setup docs now match the current package layout and release behavior; the Remotion removal version is corrected to v1.3.1.

## 1.6.0 - 2026-07-10

### Fixed

- Audio-only normalization now uses an audio-aware output probe, so valid WAV results no longer fail with a misleading `No video stream found` error. Audio muxing continues to validate audio inputs without video-only warnings.
- Hyperframes commands normalize a project path once at command entry, preventing relative paths such as `hyperframes` from resolving as `hyperframes/hyperframes`.
- `audio-compose` now decodes supported non-legacy WAV containers, including `WAVE_FORMAT_EXTENSIBLE`, to canonical mono signed 16-bit PCM at the requested sample rate before mixing.
- Technical and design quality checks now report shared saturation and contrast metrics with explicit units and availability. `video-quality-check --fail-on-warning` exits nonzero whenever the returned result has `all_passed: false`.
- Rescue acceptance fixtures now encode rotation with stream metadata supported by the Bookworm CI image, so the push-only slow suite runs against its installed FFmpeg instead of failing during fixture creation.

### Added

- **Post-rescue planning capabilities** - eight matching MCP, CLI, and Python client
  surfaces now expose source-backed semantic timelines and local query, reviewable timeline
  edit plans, subject-aware visual transforms, evidence-gated restoration, source-backed
  composition, capability-gated creative autopilot, and explicit remote egress contracts.
  These calls plan or verify only: they do not render, download models, submit remote jobs,
  or silently broaden an approval. See `docs/POST_RESCUE_FEATURES.md`.

- **Rescue R1 extension contracts** - immutable, versioned policy profiles; separately
  hashed feature-intent envelopes; additive verifier and capability registries; and
  deterministic preview/approval bindings now let new editing features reuse the rescue
  safety kernel without changing rescue v1 plans, receipts, hashes, or behavior.
- **Dedicated video rescue pipeline** - three additive MCP tools
  (`video_rescue_plan`, `video_rescue_render`, `video_rescue_inspect`), CLI commands
  (`rescue-plan`, `rescue-render`, `rescue-inspect`), and Python client methods now diagnose
  one local video, classify repair candidates, render approved safe IDs, and inspect a
  verified rescue package. Every successful video rescue includes a master, universal
  sharing copy, hashed receipt, and optional caption/transcript sidecars or explicit
  unavailable reasons. See `docs/RESCUE.md`.
- **Rescue FFmpeg portability gate** - the pinned FFmpeg 6/7/8 CI matrix now exercises the
  public rescue plan/render/inspect path, MOV/WebM sharing copies, and reproducible render
  contracts in addition to compositor and workflow filtergraphs.
- **`composite_layers` workflow op** — the workflow engine's allowlist grows to **7 ops**;
  a step may now compose an ordered layer stack (`op: "composite_layers"`) without leaving
  the workflow's safety envelope. Layer sources are expressed as workflow `@refs`
  (`inputs.layers[].src` / `.mask` → `@sources.<id>` / `@work/<name>`), never as nested or
  raw paths (those fail closed with `unsafe_workflow_source`). Every layer source is
  resolved, workspace-confined, and hashed into the step's `input_hashes` (one sha256 per
  layer source), and the workflow layer synthesizes a workspace-confined nested spec that
  the vetted `composite_layers` engine consumes — so composite provenance matches every
  other op. The only tunable param is `canvas`; output uses the normal
  `@work`/`@outputs` binding + `output_hash`. This rides the existing `video_workflow_*`
  tools / `workflow-*` CLI (no new tool or command). See `docs/WORKFLOWS.md`.

### Safety

- Rescue is local-only, source-immutable, and timeline-locked. Plan/source/policy/dependency
  staleness and invalid approvals fail closed; cancellation never promotes output;
  verification failures are quarantined; resumable intermediates require matching hashes;
  and all promoted artifacts have receipt hashes and explicit verification metrics/units.
  Captions remain sidecars and rescue never downloads Whisper or invokes cloud processing.

### Compatibility

- Existing MCP, CLI, and Python APIs are unchanged. Whisper remains optional, the universal
  sharing copy is additive to the high-quality master, and intentional 24 fps delivery
  behavior elsewhere in MCP Video is unchanged.

### Security

- **Workflow artifact writes are confined to the spec's workspace root (R1)** — `--save-plan`,
  `--save-receipt`, and `--save-receipt-dir` now additionally require the resolved target to
  live UNDER the spec's workspace directory (the same realpath + `relative_to` confinement
  every declared source and output already obeys), on top of the existing
  traversal/symlink/system-dir/dotfile guard. A `.json` write that passed the media guard but
  pointed outside the workspace now fails closed with `unsafe_workflow_source`.
- **Out-of-workspace absolute paths redacted in workflow errors (R2)** — a wrapped engine
  fault whose message embeds an absolute home path (`/Users/<name>/…`, `/home/<name>/…`)
  outside the workspace is now redacted to `<redacted-path>` in both the raised
  `MCPVideoError` and the receipt's recorded step error, closing a residual path leak beyond
  the workspace-prefix strip.

### Added

- **Agent workflow engine** — a new `video_workflow_*` MCP tool family (`video_workflow_validate`, `video_workflow_plan`, `video_workflow_render`, `video_workflow_inspect`) plus flat CLI commands (`workflow-validate`, `workflow-plan`, `workflow-render`, `workflow-inspect`) and Python client parity (`Client.workflow_validate/plan/render/inspect`). An agent can define a multi-step local video job as a JSON spec (`schema_version: 1`), validate it cheaply, produce a no-render dry-run plan, render it with a provenance receipt, and inspect that receipt afterward. Steps are an ordered, backward-reference-only list over a fixed 6-op allowlist (`probe`, `trim`, `resize`, `convert`, `merge`, `add_text`), each backed by an existing vetted engine; unknown ops, forward/unknown `@refs`, and workspace-escaping paths fail closed with `MCPVideoError` codes.
- **Workflow resume, variants, and cleanup** — `video_workflow_render --resume <receipt>` continues a partially-completed job (spec-hash gated; a step is reused only when it is completed AND its output and input hashes still match); `variants[].overrides` emit N outputs from one source/step declaration; intermediates in the job's isolated `@work/` directory are cleaned on success, kept on failure, and `--keep-intermediates` overrides cleanup for inspection.
- **Compositor full-canvas blend modes** — `composite-layers` / `video_composite_layers` layers accept `blend` values `multiply`, `screen`, `overlay`, `darken`, `lighten`, applied full-canvas via the FFmpeg `blend` filter. Positioned/scaled/masked/timed blend is deferred and fails closed with the new `unsupported_blend_geometry` code; unknown modes fail closed with `unsupported_blend_mode`.
- **Compositor rotation and pivot** — layers accept `rotation` (degrees, transparent-fill) and a new `pivot` field (`center` default, plus the four corners) setting the rotation/placement reference point. The existing `anchor` position alias is unchanged. Unknown pivots and non-numeric rotation fail closed.
- `composite-layers` / `video_composite_layers` P2 supports transform sizing, timing windows, mask/matte alpha sources, dry-run layer plans, source/output hashes, and richer render receipts for agent review before publishing.
- `video_duck_audio`: mix background music under a video's voice with automatic sidechain ducking — the music dips during speech and recovers in pauses. Engine function `duck_audio` with validated `music_volume`, `threshold`, `ratio`, `attack`, and `release` parameters.
- `video_ai_color_grade` accepts `lut_path` for professional `.cube`/`.3dl` LUT files via FFmpeg `lut3d`, overriding style presets and reference matching.
- `video_convert` streams MCP progress notifications during long renders, so clients can show a live percentage instead of an apparently hung call.
- Spanish-language README section (`En español`) and bilingual EN/ES text for the most common errors (FFmpeg missing, file not found).
- New docs for the release surface: `docs/WORKFLOWS.md` (workflow engine), workflow + layer_plan receipt schemas in `docs/VIDEO_RECEIPT.md`, and a receipt-privacy scan test that fails on any home path, username-in-path, or secret-shaped token in committed docs/examples or freshly produced dry-run/render artifacts.

### Changed

- **`layer_plan` receipt bumped to `schema_version: 2`** (backward-readable, additive). It gains a `receipt_kind` discriminator (`"layer_plan"`), `transform.rotation`/`transform.pivot` fields, blend/rotation `features` flags, and an explicit `audio_policy: "dropped_video_only"` flag (composite output stays video-only this release; audio compositing is deferred, documented, and receipt-flagged rather than silent). `video_workflow_inspect` reads both new workflow receipts and legacy `receipt_kind`-less v1 layer_plan receipts by inferring the kind.
- Glitch tools (`glitch_rgb_shift`, `glitch_scanline_jitter`, `glitch_screen_tearing`, `glitch_vhs_tracking`, `glitch_macroblocking`, `glitch_datamoshing`, `glitch_cmyk_split`, `glitch_turbulent_displacement`) now return rich edit metadata in their MCP responses — `duration`, `resolution`, `size_mb`, and `elapsed_ms` — matching the envelope shape of all other edit tools. Previously these tools returned only `success` and `output_path`.

### Fixed

- The `composite-layers` layer-plan receipt now records `output_path` (and `resolved_src`/`mask`) relative to the spec directory whenever the file lives inside it, instead of emitting the resolved absolute path — a shared or committed receipt no longer leaks the user's home directory. Internal rendering still uses the resolved absolute location; only the receipt is relativized.
- Removed BasicPitch from declared optional extras and documented it as a manual integration so Dependabot can patch vulnerable TensorFlow/Keras/protobuf transitive dependencies instead of resolving an unsafe pinned stack.

### Security

- **Workflow param VALUE validation** — a step's `params` values are now type-checked against the backing engine's parameter types (not just names), so a string for an integer parameter (e.g. `width="20000"`, `size="24,drawtext=textfile=/etc/hosts"`) fails closed with `invalid_workflow_params` before any FFmpeg invocation. Engine sinks are independently hardened: `resize` rejects non-integer/oversize dimensions and `add_text` coerces `fontsize` through a numeric guard before filtergraph interpolation.
- **Workflow artifact write-path validation** — `--save-plan`, `--save-receipt`, and `--save-receipt-dir` now route through the same traversal/symlink/system-directory/sensitive-dotfile guard as media outputs and additionally refuse to overwrite any file that is not a `.json` artifact, closing an arbitrary out-of-workspace overwrite that previously only rejected null bytes.
- **Workflow resource caps** — a spec may declare at most 64 steps and 32 variants, and `resize` dimensions are bounded to 7680px; exceeding a cap fails closed.
- **`add_text` `font` excluded from workflow specs** — the path-typed `font` parameter (a filesystem existence oracle) is no longer tunable through a workflow op and fails closed as an unaccepted param; set fonts by calling `add_text` directly.
- Workflow steps now fail closed on ANY engine exception (not only `MCPVideoError`): an unexpected runtime fault is wrapped as `workflow_step_failed`, recorded on the receipt with a workspace-sanitized message, and left resumable; the Python client rejects a dict spec for render; batch variants that resolve to a colliding output path fail closed; and raw-relative input refs are re-confined to the workspace at execution time (closing a validate→execute symlink TOCTOU).

### Removed

- The opt-in anonymous analytics ping (`MCP_VIDEO_ANALYTICS=1`). The endpoint it posted to was never deployed or owned by the project, making the domain claimable by a third party — removed entirely rather than left as a silent no-op.
- `video_generate_music` and the MiniMax music API integration. A hosted, per-key music API does not belong in a local-first tool; background-music generation moves to a local open-source pipeline (planned: ACE-Step) with mcp-video handling the mixing via `video_duck_audio`.

## 1.5.2 - 2026-07-06

### Added

- Added `composite-layers` / `video_composite_layers` P1 for ordered image/video/solid layer stacks with normal alpha compositing, per-layer opacity, fixed x/y placement, and deterministic layer-plan receipts.
- Added Python client parity for `Client.composite_layers(...)`.

### Changed

- Routed Forgejo CI required jobs to the known-live `light` runner label so PR and post-merge checks do not wait on optional heavyweight runners.
- Aligned package metadata with the Forgejo repository as the canonical source while preserving MCP Registry identity.

### Fixed

- Guarded glitch shader ffprobe subprocess calls with timeout-aware error handling.
- Removed tracked local `.pi-lens` cache artifacts and scrubbed public local-infrastructure references from agent guidance files.
- Added release-hardening checks to prevent local path/cache leakage from returning.

## 1.5.1 - 2026-06-04

### Fixed

- Removed the unpublished `meltysynth` dependency from optional audio extras so Glama, uv, and package metadata validators can resolve the project.
- Updated the repository readiness audit after the intentionally removed `/explainer-video` npm Dependabot entry.

## 1.5.0 - 2026-06-04

### Added

- Added Video Receipt documentation for agent-created media review trails.
- Added receipt-backed confidence baseline workflow with quality report, release checkpoint, storyboard, thumbnail, and pending human-review status.
- Added local repurpose-package workflow for platform variants with manifest, review artifacts, checkpoints, and receipt output.
- Added confidence benchmark and adversarial certification scripts for local readiness proof.
- Added dated proof notes for fresh install confidence, public issue triage, agentic media readiness, and external feedback asks.

### Changed

- Hardened the explainer workflow into a 10-stage receipt-producing lane with transition audit records, audio normalization, quality report, and a real `min_score=50` release checkpoint.
- Updated workflow routing docs and golden workflow map around the confidence proof lanes.

### Fixed

- Removed the stale Dependabot `/explainer-video` npm configuration entry so dependency automation can run against real package paths.
- Made corrupted media probing fail as `InputFileError`, giving adversarial checks a clear invalid-input signal.
- Fixed the confidence benchmark so stale receipts cannot hide a failed workflow run.

## 1.4.1 - 2026-05-25

### Added

- Added preflight guardrails for high-risk video/audio edit paths:
  - `video_filter` warns and clamps out-of-range filter parameters.
  - `video_merge` warns on resolution/FPS/audio mismatches and rejects transitions longer than the shortest clip.
  - `video_add_audio` validates volume and warns on mix/timing risks.
  - `video_overlay`, `video_watermark`, and `video_chroma_key` validate opacity/similarity/blend/timing parameters.
  - `video_text_animated` validates color, start/duration, and warns on timing/overflow risks.
  - `video_layout_grid` and `video_split_screen` warn on clip-count, duration, FPS, and audio mismatches.
- Added tracked implementation plan at `docs/plans/2026-05-24-video-guardrails.md`.

### Changed

- Refreshed README, tool reference, landing page, roadmap, contribution guide, package metadata, and GitHub repository description for the current 119-tool guardrailed surface.

## 1.4.0 - 2026-05-09

### Added

- Expanded Hyperframes orchestration for the 0.5 surface: snapshots, inspection, metadata, catalog, website capture, local TTS, transcription, background removal, diagnostics, benchmarks, and richer render controls.
- Added local video repurposing helpers for dry-run manifests and platform-ready variants with thumbnails, storyboards, and optional release checkpoints.
- Real `analyze_video(include_colors=True)` color extraction — returns actual dominant colors instead of placeholder values.
- `video_info_detailed` now returns real dominant colors instead of `None`.

### Changed

- Refreshed README, MCP tool docs, Python client docs, AI discovery, and `llms.txt` so PUSHING CREATION, Hyperframes, and repurposing are described as the current operator paths without centering test-count messaging.
- Pipeline cleanup `OSError`s are now surfaced as warnings instead of being silently swallowed.

### Fixed

- Fixed green-cast video effects and 24-bit WAV handling in `effect_noise`, `video_overlay`, and audio effects.
- Fixed 24-bit WAV handling in `audio_compose`.
- Design quality probe now returns `None` on analysis failure instead of sentinel values (128 luma, 50 contrast) that produced perfect scores.
- Typography check adds an advisory issue when brightness analysis is unavailable.
- Reject unsupported Hyperframes render dimensions instead of silently accepting them.
- Report Hyperframes render artifacts correctly by output format, including `png-sequence` directories.
- Fail Hyperframes render-and-post/pipeline paths when render artifacts are missing.
- Reject unknown text animations instead of silently ignoring them.
- Reject empty animated text at engine and MCP/tool layers.
- Reject invalid layout/PIP choices at tool and engine boundaries.
- Validate mograph duration/fps/style and reject unknown progress style.
- Reject unknown animated text positions.
- Reject unknown watermark/overlay positions.
- Reject malformed timeline image overlay position dicts before input probing.
- Validate convert format/quality before probe/FFmpeg.
- Validate HLS qualities and segment duration before probe/FFmpeg.
- Reject unsupported `compare_quality` metrics instead of reporting meaningless `unknown`.
- Validate `video_batch` operation names before input path validation.
- Validate malformed subtitle entries/ranges before input path validation.
- `audio_compose()` rejects missing track files, empty tracks, non-dict entries, non-positive duration, and invalid volume.
- `audio_sequence()` rejects unknown/missing event types and unsupported tone waveforms.
- `audio_effects()` rejects unknown/missing effect types.
- `audio_preset()` rejects invalid pitch and intensity.
- `audio_synthesize(effects={...})` rejects unknown effect keys.

## 1.3.10 - 2026-05-07

### Fixed

- Improved `mcp-video doctor` guidance on Python 3.13+ so missing Real-ESRGAN/BasicSR reports explain the BasicSR build guard and point users to the OpenCV fallback or Python 3.11/3.12 for the Real-ESRGAN backend.

## 1.3.9 - 2026-05-06

### Fixed

- Fixed `mcp-video[all-ai]` and `mcp-video[upscale]` installs on Python 3.13 by guarding Real-ESRGAN/BasicSR dependencies behind the Python versions where BasicSR still builds, while keeping the OpenCV upscaling fallback installable.

## 1.3.8 - 2026-05-06

### Fixed

- Fixed AI scene-detection JSON output so perceptual-hash differences are serialized as standard JSON numbers.
- Added `torchcodec` to stem-separation extras and diagnostics so Demucs output works with current TorchAudio save behavior.

## 1.3.7 - 2026-05-06

### Fixed

- Fixed `search_tools()` / `Client.search_tools()` so discovery includes the full 91-tool MCP surface, including PUSHING CREATION, Hyperframes, audio, and AI tools.

## 1.3.6 - 2026-05-06

### Added

- Added PUSHING CREATION-compatible cinematic pre-production tools:
  - `video_project_create`
  - `style_pack_read`
  - `storyboard_read`
  - `shot_prompt_render`

### Changed

- Updated package, MCP registry metadata, README, `llms.txt`, and tool docs for the 91-tool cinematic creation surface.
- Toned down public launch copy so test coverage is supporting evidence rather than the main product message.

### Fixed

- Restored README readiness anchors required by the repository audit.

## 1.3.1 - 2026-05-03

### Security

- Fixed command injection risk in `engine_stabilize.py` — vectors file path now validated as absolute.
- Enabled SSL certificate verification for AI model downloads in `ai_engine/upscale.py`.
- Redacted full filesystem paths from stabilization error messages.

### Fixed

- Added proper AI operation timeout (3600s) for demucs/whisper — prevents premature kills on long videos.
- Increased FFmpeg stderr buffer from 1MB to 10MB — fixes truncated progress for long-running operations.
- Fixed temp file leak in typewriter text effect — cleanup now happens even on write failure.
- Added `OSError` handling in hyperframes for file size race conditions.
- Added pitch shift semitones range validation (-48 to +48) — prevents FFmpeg filter chain overflow.
- Capped pixel count in color extraction (50K max) — prevents memory exhaustion on large images.
- Added try-finally cleanup for Whisper temp WAV files.
- Added bitrate/size range validation in probe before integer conversion.
- Added 1MB JSON size limit in CLI argument parser.
- Added `threading.Lock` for thread-safe probe cache.
- Centralized all timeout constants in `limits.py`.

### Changed

- Standardized tool count to **87 MCP tools** across all documentation and metadata files.
- Removed duplicate Hyperframes Integration section from README.
- Removed duplicate architecture entry from README.
- Documented `video_cleanup` tool in TOOLS.md.
- Updated test count in TESTING.md.
- Marked shipped v1.3.0 features as completed in ROADMAP.md.
- Updated server.json version to 1.3.1.

### Removed

- **Remotion integration completely removed.** All Remotion MCP tools, CLI commands, client methods, engine modules, and tests have been deleted. The project now uses Hyperframes (HTML-native, Apache 2.0) as its sole code-based video creation engine.
  - Deleted: `mcp_video/remotion_engine.py`, `mcp_video/remotion_models.py`, `mcp_video/server_tools_remotion.py`, `mcp_video/client/remotion.py`, `mcp_video/cli/handlers_remotion.py`, `mcp_video/cli/parser/remotion.py`, `tests/test_remotion_engine.py`, `tests/test_remotion_deprecation.py`
  - Removed `RemotionNotFoundError`, `RemotionProjectError`, `RemotionRenderError` from `errors.py`
  - Removed `VALID_REMOTION_TEMPLATES` from `validation.py`
  - Removed Remotion category from `doctor.py` checks
  - Updated `test_public_surface.py`: 87 MCP tools (was 93), 88 CLI commands (was 94)
  - Removed `remotion` optional dependency, pytest marker, and keyword from `pyproject.toml`
  - Removed Remotion CI smoke test job
  - Updated all documentation to remove Remotion references

### Design

- Redesigned landing page: Space Grotesk + DM Sans typography, orange/teal video-editing palette.
- Fixed broken mobile menu with proper responsive CSS.
- Added inline SVG favicon, ARIA labels, skip-to-content link.
- Improved hero headline: "87 Video Tools. Zero Cloud Costs."
- Added Organization schema markup for better SEO.
- Optimized font loading with preconnect hints.

## 1.3.0 - 2026-04-28

### Added

- **Crop by percentage** — `crop()` now accepts `crop_percent` (e.g. `crop_percent=50` for a center 50% crop). Alternative to explicit `width` + `height`.
- **Orientation-aware metadata** — `VideoInfo` now exposes `rotation`, `display_width`, `display_height`, and `display_resolution`. ffprobe `side_data_list` is parsed for rotation metadata.
- **Audio waveform text representation** — `WaveformResult.text` returns an ASCII art waveform for agent-friendly display.
- **Frame-accurate seeking** — `trim()` gains `accurate=True` for output-seeking (slower, frame-perfect) vs the default fast input-seeking.
- **Pipeline output cleanup** — `Client.pipeline()` gains `cleanup=True` to auto-remove intermediate files after chaining.
- **Structured logging** — New `--verbose` / `-v` CLI flag enables DEBUG logging to stderr.
- **Template preview** — `preview_template()` returns operations list + estimated output before rendering a timeline template.
- **Custom font upload** — `font_manager.py` downloads and caches Google Fonts by name for use in text overlays.
- **Usage analytics** — `analytics.py` sends an optional anonymous ping on server startup. Disable with `MCP_VIDEO_ANALYTICS=0`.
- **HLS/DASH streaming** — `hls_segment()` segments video into HTTP Live Streaming format with multi-quality variants.
- **Advanced codecs** — `convert()` now supports `hevc` (H.265), `av1`, and `prores` output formats.
- **Advanced masking** — New `luma_key()` (brightness-based masking) and `shape_mask()` (circle, rounded_rect, oval) tools.
- **Smarter GIF output** — Quality-based fps scaling (10/12/15/20), Bayer dithering, and 128-color palette generation.

### Changed

- **Merge auto-normalize** now handles fps mismatches, audio sample rate mismatches, and rotation-aware display dimensions during normalization.
- **Remotion deprecation upgraded** from `DeprecationWarning` to `FutureWarning` for v1.3.0 timeline.
- Public tool count updated from 90 to **87** unique MCP tools.

### Fixed

- `convert()` vs `export_video()` docstrings clarified to distinguish format changes from quality-tuned delivery.

## 1.2.6 - 2026-04-27

### Changed

- Bumped version to 1.2.6 (1.2.5 tag already existed).

## 1.2.5 - 2026-04-27

### Added

- **Hyperframes integration** — 8 new MCP tools, Python client methods, and CLI commands for HTML-native video creation:
  - `hyperframes_init` — scaffold new projects (blank, warm-grain, swiss-grid templates)
  - `hyperframes_render` — render compositions to MP4/WebM/MOV
  - `hyperframes_still` — render single frames via snapshot
  - `hyperframes_compositions` — list compositions in a project
  - `hyperframes_preview` — launch live preview studio
  - `hyperframes_validate` — validate project structure and run lint
  - `hyperframes_add_block` — install blocks from the Hyperframes catalog
  - `hyperframes_to_mcpvideo` — render then post-process with mcp-video in one step
- Full test suite for Hyperframes engine: 54 unit + integration tests in `tests/test_hyperframes_engine.py`.
- `sample_hyperframes_project` pytest fixture.

### Changed

- **Remotion is deprecated.** All Remotion MCP tools, client methods, and CLI commands now emit `DeprecationWarning`. Remotion will be removed in a future major version. Migrate to Hyperframes (Apache 2.0) or Revideo (MIT).
- Public tool count updated from 82 to 90 unique MCP tools.
- `mcp_video/client/remotion.py` — all methods now warn on usage.

### Fixed

- `hyperframes_engine.validate()` no longer raises `HyperframesProjectError` when no HTML entry point is found; it correctly reports the issue in the validation result.

## 1.2.4 - 2026-04-22

### Added
- `Client.subtitles_styled()` alias for `text_subtitles()` to match MCP tool rename.
- Runnable `workflow.py` for `02-podcast-clip` (6 stages).
- Runnable `workflow.py` for `03-explainer-video` (7 stages, client-only, no raw FFmpeg).

### Changed
- Documentation updated for `search_tools`, `workflows/`, and ICM alignment.
- `workflows/01-social-media-clip/workflow.py` fixed client arg names.

## 1.2.3 - 2026-04-22

### Changed

- Consolidated duplicate tools: removed `video_blur`, `video_color_grade`, and `video_extract_frame` as standalone tools. Functionality preserved through `video_filter` and `video_thumbnail`.
- Renamed `video_text_subtitles` to `video_subtitles_styled` for clearer naming.
- Added `search_tools` meta-tool for fast tool discovery by keyword.
- Updated public tool count from 83 to 81 unique tools.
- Reorganized docs/TOOLS.md into 12 functional categories.

### Fixed

- Image analysis tools (`image_extract_colors`, `image_generate_palette`, `image_analyze_product`) now accept video input by auto-extracting a representative frame.

### Added

- Added ICM-style `workflows/` directory with 3 production-ready pipelines: social-media-clip, podcast-clip, and explainer-video.
- Added `CLAUDE.md` and `workflows/CONTEXT.md` for agent context routing.

## 1.2.2 - 2026-04-21

### Added

- Added GitHub Discussions templates, CODEOWNERS, maintainer/governance docs, and Dependabot configuration.
- Added `llms.txt`, `robots.txt`, `sitemap.xml`, and `server.json` for search, AI-agent discovery, and MCP Registry readiness.
- Added `docs/AI_AGENT_DISCOVERY.md` and an adversarial remediation plan.
- Added `_validate_output_path()` and rolled it out across all engines for safer output directory handling.
- Added client-side validation and return type annotations for improved API contract consistency.
- Added current edge-case audit document (`docs/CURRENT_EDGE_CASE_AUDIT_2026-04-21.md`).

### Changed

- Updated public tool count messaging from 82 to the current 83 MCP tools.
- Updated the landing page with crawl metadata and structured software/source metadata.
- Normalized root metadata links to the canonical repository URL.
- Replaced the grey social preview image with generated media artwork.

### Security

- Fixed TOCTOU race conditions and sanitized numeric values in FFmpeg filters.
- Hardened AI engine resource guards for scene detection, spatial audio, stem separation, transcription, and upscaling.
- Hardened direct download paths with timeout and size limits.
- Closed top-priority audit validation gaps across engine boundaries.
- Fixed design quality security and SRT format safety issues.

### Fixed

- Added startup validation to `remotion_engine.studio()` to catch immediate process crashes.

## 1.2.1 - 2026-04-13

### Changed

- Prepared the 1.2.1 package metadata and public badge.
- Improved runtime error contracts and diagnostics.
- Repaired repository trust rails for deploys, packages, tests, and AI extras.

### Fixed

- Aligned `mcp_video.__version__` with the package version in `pyproject.toml`.
- Moved optional dependency metadata out of Ruff configuration.
- Centralized chroma-key color validation for safer FFmpeg filter construction.

## 1.2.0 - 2026-03-31

### Added

- Published the 1.2.0 package release.
- Documented the broad MCP, CLI, Python client, FFmpeg, Remotion, image, audio, AI, and quality-guardrail surface.
