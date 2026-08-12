# Wishlist + optional depth + ops closeout (2026-08-12)

## Scope (user-approved)

1. **All ROADMAP wishlist open checkboxes** (High/Medium/Low/Observability residual)
2. **All optional product depth** (TTS probe, VLM keyframes, foreign OTIO, generative paid rigor, perf baseline sample, sound dual-class honesty)
3. **Ops from residual matrix:** Renovate host token (#3) runbook + CI light runner topology

## Delivered

| Item | Result |
| --- | --- |
| Smarter GIF | Already shipped (low=320…ultra=800); ROADMAP unchecked row closed |
| `video_edit` sequence shortcut | `expand_sequence_shortcut` + docs; `clips`/`transitions`/`transition_duration` |
| Waveform text | Already shipped (`WaveformResult.text`); ROADMAP closed |
| Frame-accurate seek | Already shipped (`trim accurate=True` + TE seek); ROADMAP closed |
| Structured logging | `-v/--verbose` + **`--log-file PATH`** |
| TTS depth | Doctor-visible `detect_tts_backend`; plan `executable` tracks probe |
| VLM depth | Structural keyframe extract; VLM package = deferred explicit call (no fake scores) |
| Foreign OTIO | Local `file://`/path media → `foreign_otio_import` + sequence shortcut; remote rejected |
| Generative paid rigor | `executable`/`paid_path` + `assert_generative_executable` fail-closed |
| Perf | Cheap golden-path timings re-measured (doctor/info p50) |
| Sound dual-class | Evidence retained; second class remains host residual (`external_host_unavailable` when absent) |
| Renovate #3 | `docs/ops/RENOVATE_HOST_TOKEN.md` + HUMAN_GATES link; secrets still human |
| CI light topology | `docs/CI_RUNNER_TOPOLOGY.md` light contract table; lint stays on `light` |

## Tests

- `tests/test_wishlist_depth_closeout.py` (new)
- Related suites green: phase4 multipliers, finish_campaign, phase3 watching, engine/client/cli sample (319+)

## Human residual

- Install/set `RENOVATE_TOKEN` + `MIRROR_GITHUB_TOKEN` on Forgejo (see Renovate runbook)
- Live dual-class sound re-run when second host exists
