# MCP Video 1.6.0 Rescue And Post-Rescue Release Receipt

**Generated:** 2026-07-10
**Feature implementation head:** `0c8adab`
**Closeout evidence:** the commit containing this receipt
**Pull request:** [#108](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/pulls/108)
**Base:** `1132219` (`master` after defect-fix PR #52)

## Release Identity

Live Forgejo and package evidence agree that this is the first 1.6 release candidate:

- Forgejo has no published releases and its newest tag is `v1.5.1`.
- PyPI's newest published package is `mcp-video 1.5.1`.
- `pyproject.toml` and `mcp_video.__version__` both declare `1.6.0`.
- `CHANGELOG.md` already contains the additive 1.6.0 workflow/compositor scope; this receipt
  supersedes the 2026-07-09 pre-rescue packet for final counts and scope.

No tag, package upload, or Forgejo release was created by this receipt. Those remain explicit
post-merge publication actions.

## Delivered Scope

### Production rescue pipeline

The public `plan -> approve -> render -> verify -> package -> inspect` flow is implemented
across MCP, CLI, and Python. Its policy is local-only, source-immutable, and timeline-locked.
The renderer accepts only policy-approved plan IDs, compiles them through a closed operation
registry, verifies independently, and atomically promotes a master, H.264/AAC sharing copy,
receipt, and optional caption/transcript sidecars.

### Post-rescue critical path

The approved post-rescue scope is implemented as strict planning, retrieval, verification,
approval, and explicit adapter contracts before any new unrestricted renderer is allowed:

| Gate or track | Delivered evidence |
| --- | --- |
| R1 extension seams | Versioned policy registry, intent envelope, additive verifier/capability registries, preview diff, and digest-bound approvals in `mcp_video/rescue/r1/` |
| S1 semantic timeline | Source-time words, speakers, shots, scenes, silence, audio events, keyframes, uncertainty, provenance, stable IDs, and hashes in `mcp_video/semantic/` |
| S2 local retrieval | Deterministic local lexical/embedding index returning source-backed span IDs and times |
| T1/T2 timeline edits | Hash-bound EDL, approval, visible timeline diff, verification, and generators for silence, filler, false starts, retakes, pacing, trim, and reorder |
| V1/V2/V3 visual work | Subject/camera evidence, ambiguity and tracking loss, crop tracks/previews/budgets, stabilization plans, abstention, and independent visual checks |
| Restorative quality | Evidence and promotion gates for denoise, color/HDR, frame repair, background work, and styled captions; unsupported or weak evidence abstains |
| C1/C2 composition | Hashed rights/provenance manifest, source-backed selection, storyboard/timeline preview, approval, compilation to vetted operations, and package verification |
| Creative autopilot | Capability-gated coordinator over proven planners; missing prerequisites and unapproved invention return abstentions |
| E1/E2/E3 remote boundary | Exact egress manifest, separate network approval, explicit remote selection, render/delivery/hosting adapter protocols and fake adapters, job/receipt contracts, local verification, and promotion gate |
| Public parity | Eight matching MCP tools, flat CLI commands, and Python client methods documented in `docs/POST_RESCUE_FEATURES.md` |

The post-rescue surfaces do not silently mutate media, install models, contact providers, or
submit jobs. Fake adapters prove the remote contract without claiming a production provider.
Rendering must still compile to an existing vetted MCP Video operation or a separately
approved executor.

## Defect Receipts

The four production defects are fixed on `master` by PR #52 and remain covered by this
candidate's full regression suite:

| Issue | Root-cause result | Forgejo receipt |
| --- | --- | --- |
| [#7](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/7) | Audio-only operations use an audio-aware probe; successful muxes no longer emit video-only warnings | comment `3960` |
| [#49](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/49) | Hyperframes project paths normalize once at command entry | comment `3962` |
| [#50](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/50) | Supported extensible WAV inputs decode to canonical PCM before composition | comment `3964` |
| [#51](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/51) | Quality metrics share explicit definitions/units and failed `--fail-on-warning` checks exit nonzero | comment `3966` |

The intentional 24 fps delivery behavior is unchanged.

## Implementation Commits

| Area | Commits |
| --- | --- |
| Design and execution plans | `c6de37c`, `fd7c7f6`, `2f3d07d`, `ddad6c6` |
| Rescue contracts through policy planning | `dceaea9`, `ee8ecd1`, `0c06265` |
| Closed execution, verification, render, and resume | `32e2b72`, `6a1ed95`, `f6483a2` |
| MCP/CLI/Python, sidecars, E2E, and docs | `72abc71`, `dbb4f90`, `06a7495`, `962d0f8`, `e68a783` |
| R1 extension seams and policy profiles | `b007cb8`, `dd5e902` |
| Visual, semantic/timeline, restorative, and composition tracks | `f2c3b5c`, `3b4c580`, `c556796`, `0f6c7ef`, `813828f` |
| Remote boundary and public parity | `6893acd`, `0c8adab` |

## Verification Gates

The closeout was verified from the release worktree after all production, test, CI, and
documentation changes were present:

| Gate | Result |
| --- | --- |
| Rescue and post-rescue focused tests | `199 passed in 87.03s` across every new test module |
| Full test suite | `2111 passed, 15 skipped, 8 warnings in 629.58s` |
| Ruff | `ruff check mcp_video tests`: clean |
| Pyright | Expanded rescue/post-rescue gate: `0 errors, 0 warnings` |
| Compile and diff hygiene | `compileall` and `git diff --check 1132219`: clean |
| Wheel and sdist build | Build and Twine checks passed for both 1.6.0 artifacts |
| Wheel contents and import smoke | All six new package families plus rescue CLI formatting present; tests absent; clean-wheel import reports `1.6.0` |
| Public leak audit | Added-line and tracked-identity scans clean; receipt privacy tests `4 passed` |
| Manual rescue CLI smoke | Source hash unchanged; `planned -> completed`; 12 gating checks passed; integrity matched; text and JSON inspect passed |
| FFmpeg 6/7/8 portability matrix | 6.1.3: `4 passed`; 7.1.5: `4 passed`; 8.1.2: `4 passed` |
| Public surface | 135 MCP tools and 114 CLI commands |
| Forgejo PR checks | Exact closeout-head result is an external post-push gate and is posted to PR #108 after CI completes |

Final locally built artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `mcp_video-1.6.0-py3-none-any.whl` | 526903 | `ec0de4ab27130251ec8e9badc68ffce86d132201ddbe2d258d2a9f2d8c93f6ab` |
| `mcp_video-1.6.0.tar.gz` | 415303 | `48542368195ad0915d3764d65cfad4a0d50c9b285b4edcd657c908048ddedd84` |

The Forgejo row is intentionally head-bound outside this commit: a commit cannot truthfully
attest to its own future CI result. The final PR comment records the immutable closeout SHA and
each check result after the push.

## Independent Review Closeout

The final independent review requested changes. The closeout resolves every finding:

- Rescue verification now uses the centrally resolved FFmpeg/ffprobe runtime, with an empty
  `PATH` regression test.
- Unexpected caption failures retain a sanitized exception class, are logged, and quarantine
  the package without persisting private messages or paths.
- Pyright now gates the new core and public rescue/post-rescue surfaces with zero diagnostics.
- Rescue CLI formatting moved into a feature module; the shared formatter is 784 lines, below
  the repository's 800-line limit.
- Branch-range whitespace checks are clean.

The measured rescue planning report is `.superpowers/sdd/rescue-performance.json`: a 60-second
1080p fixture recorded 35.04 seconds observed planning time on the measurement host. The
approximately 30-second goal is informative, not a heterogeneous-runner elapsed-time gate;
the bounded sample contract is enforced.

## Compatibility And Residual Risk

- Existing MCP tools, CLI commands, Python methods, workflows, and legacy receipts remain
  compatible; the release is additive except for the four root-cause defect corrections.
- Rescue is deliberately single-source, local-only, and timeline-preserving. Timeline edits,
  crop changes, synthesis, and network use require separate policy profiles and approvals.
- Optional Whisper absence is nonfatal and recorded as an unavailable sidecar reason.
- Media bytes are not claimed identical across FFmpeg builds. Plans, hashes, topology,
  durations, operation parameters, metric units, and package contracts are the reproducible
  boundary.
- Restorative and visual features abstain when evidence, capability, crop, continuity, or
  promotion thresholds are not satisfied.
- Remote provider adapters are protocols plus fake contract implementations. No production
  cloud provider, credentials, upload, billing, hosting, or deletion API is claimed.

## Publication Gate

PR #108 must be merged, the resulting `master` commit rerun through protected-branch CI, and
the exact built artifacts checked before creating `v1.6.0`, publishing to PyPI, or creating a
Forgejo release. This receipt does not bypass that external approval boundary.
