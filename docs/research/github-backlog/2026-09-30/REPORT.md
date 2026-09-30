# GitHub backlog review and local implementation — September 30, 2026

The complete public inventory contained **34 open issues and five draft PRs**.
Both issue pages were inspected. At the review checkpoint, repository master was
`a820bd42205e43ca81eebc435e8529b2d0d42fcc` and the adaptations were local,
uncommitted changes. At that checkpoint no merge, push, comment, submitted GitHub
review or issue/PR-state change had occurred. Subsequent user authorization
requests commits and a review PR; see [PR validation](../../PR_VALIDATION.md)
for the publication-stage gate and scope. [Inventory](inventory.json) preserves
the inspected issue identities and exact PR heads.

GitHub REST and GraphQL requests returned `Forbidden`. Public repository HTML,
embedded pagination payloads and native Git fetch remained available. All five
complete PR diffs were reviewed before executing their regression tests or
adapting their changes. Review found no contributed workflow/dependency changes
or external execution scripts. Contributor credit is preserved in the
[changelog](../../../../CHANGELOG.md) and review notes. Local validation does
not establish the status of a remote PR check.

## Draft PRs

| PR | Reviewed head | Local disposition |
| --- | --- | --- |
| [#567](https://github.com/KyaniteLabs/kinocut/pull/567) | `684f8a632239884235e8fb80d3218f9fefe33d90` | Adapt timestamp shifting for video layers and video masks; verify opening frames at the declared start. |
| [#573](https://github.com/KyaniteLabs/kinocut/pull/573) | `c64aa001b2bd9215390addf81fe2980b114a1600` | Adapt one-pass engine/Client mixing with bounded fades, source/output aliases rejected, staged validation and actual output metadata. |
| [#575](https://github.com/KyaniteLabs/kinocut/pull/575) | `ca896570f7da9b1a3b042081eceae64d9a9593fb` | Adapt quieter default noise floor; retain explicit filter overrides and real spectral regression. |
| [#577](https://github.com/KyaniteLabs/kinocut/pull/577) | `8986a05c74aca4b8192823f293527aeb551e5683` | Adapt accurate input seeking while preserving absolute end semantics and decoded frame hashes. |
| [#579](https://github.com/KyaniteLabs/kinocut/pull/579) | `f1891a9a1c9e6b34c64fb0e232a48f25b33edecd` | Adapt upright display-pixel cropping, tested with both quarter-turn directions. |

All five are contributions from
[@guillaume-hestia-projekt](https://github.com/guillaume-hestia-projekt).
These are reviewed local adaptations, not a claim that the draft PRs landed.

The [exact-head CI review](PR-CI-REVIEW.md) found 13 visible successful jobs for
each of #579, #577 and #567. The #575/#573 pages report completed workflows with
no jobs, so successful coverage remains unverified. No approval-request message
was visible, and none was inferred from an empty rollup. Full master CI is a
separate workflow; these PR checks do not establish integration correctness.

## Runtime and API issues

Nineteen reports have new local fixes; three already had their underlying fixes
in the checkout. References describe the current implementation, not a release
or a remote closure.

| Issue | Disposition and evidence |
| --- | --- |
| [#585](https://github.com/KyaniteLabs/kinocut/issues/585) | Honor caller-relative Hyperframes destinations and copy requested stills durably; missing outputs and unsuccessful renders fail truthfully. |
| [#584](https://github.com/KyaniteLabs/kinocut/issues/584) | Select supported codec/container pairs, produce PCM WAV, preserve stream properties, validate decoding and construct the result before publishing. |
| [#583](https://github.com/KyaniteLabs/kinocut/issues/583) | Add hash-bound chronological image-change windows and advisory temporal findings to the existing decoder. Coverage/budgets are explicit; semantic coherence and complete human viewing remain unassessed. |
| [#582](https://github.com/KyaniteLabs/kinocut/issues/582) | Use audio-capable probing for waveform and preflight; real stereo WAV/M4A/MP3/FLAC controls require no video stream. |
| [#581](https://github.com/KyaniteLabs/kinocut/issues/581) | Retain camera/lens direction and annotated style headings; reject malformed or duplicate declarations. |
| [#580](https://github.com/KyaniteLabs/kinocut/issues/580) | Extend existing measured EBU R128 and policy logic to hash-bound encoded audio/film across CLI/Client/MCP. Missing or unavailable measurements do not certify delivery. |
| [#578](https://github.com/KyaniteLabs/kinocut/issues/578) | Crop dimensions, percentages and center offsets use upright display pixels; PR #579 adapted. |
| [#576](https://github.com/KyaniteLabs/kinocut/issues/576) | Accurate trim uses input seeking with equivalent decoded frames and absolute-end conversion; PR #577 adapted. |
| [#574](https://github.com/KyaniteLabs/kinocut/issues/574) | Default `afftdn` noise floor becomes −50 dB; explicit −25 dB remains available; PR #575 adapted. |
| [#572](https://github.com/KyaniteLabs/kinocut/issues/572) | Add one-pass multi-track mixing to avoid repeated AAC generations; PR #573 adapted. |
| [#566](https://github.com/KyaniteLabs/kinocut/issues/566) | Delayed video and masks play from their opening frames at layer start; PR #567 adapted. |
| [#560](https://github.com/KyaniteLabs/kinocut/issues/560) | Apply glow color math in RGB rather than screening chroma planes; neutral-color control remains neutral. |
| [#557](https://github.com/KyaniteLabs/kinocut/issues/557) | Vignette darkens edges and preserves neutral hue; documented unused smoothness parameter remains a limitation. |
| [#556](https://github.com/KyaniteLabs/kinocut/issues/556) | Expose Client LUT path, document source confinement, and support opacity/timing in bounded non-normal blend geometries. Explicit RGB blending preserves source alpha. Sepia pixel-format fix was already present. |
| [#555](https://github.com/KyaniteLabs/kinocut/issues/555) | Allow bounded added-track looping during mixing, including late offsets and source-audio preservation. |
| [#554](https://github.com/KyaniteLabs/kinocut/issues/554) | Ken Burns retains tested constant-rate frame count and duration rather than multiplying each input frame; VFR equivalence remains unproven. |
| [#553](https://github.com/KyaniteLabs/kinocut/issues/553) | Already fixed: resolve font families to files before FFmpeg; prior Windows-specific crash fix remains in existing Unreleased notes. Linux validation is not a new Windows execution receipt. |
| [#552](https://github.com/KyaniteLabs/kinocut/issues/552) | Macroblocking restores original portrait/nonmultiple dimensions instead of producing mismatched frames. |
| [#551](https://github.com/KyaniteLabs/kinocut/issues/551) | Shape masks select compatible MOV/MP4 behavior; decoded pixel, feather, audio and timing controls cover output. |
| [#550](https://github.com/KyaniteLabs/kinocut/issues/550) | Already fixed: `layout_pip` supplies raw probe arguments to the shared runner. |
| [#549](https://github.com/KyaniteLabs/kinocut/issues/549) | Expose plain-file Client ducking and explicitly document the governed audio-bed snapshot requirement. |
| [#548](https://github.com/KyaniteLabs/kinocut/issues/548) | Already fixed: merge/video-filter outputs pin browser-compatible `yuv420p`. |

Detailed reviews: [audio](AUDIO-REVIEW.md), [independent audio review](AUDIO-INDEPENDENT-REVIEW.md),
[mixing](MIX-REVIEW.md), [trim/effects](LATENCY-REVIEW.md), and
[creation/Hyperframes/temporal](CREATION-REVIEW.md).

Independent review reproduced a source-alpha regression introduced by RGB
blending and three audio publication/cancellation defects. All were repaired
before the final integration run. Compositor tests cover fully transparent,
partially transparent and opaque images at two blend strengths, both full-canvas
and positioned, plus delayed video/masks and rotated crops.

## Ops and product issues

All twelve have concrete dispositions in the maintained
[ops board](../../../status/2026-09-30-ops-disposition.md):
#476, #477, #479, #481, #482, #483, #484, #485, #487, #488, #499 and #502.
The phase checkpoints and plan clarification preserve historical decisions
while correcting stale present-day blockers.

Public MCPB run [36167328576](https://github.com/KyaniteLabs/kinocut/actions/runs/36167328576)
succeeded for the exact base commit, including three runtime jobs and aggregate
evidence. It does not validate these local adaptations or prove a real desktop import. Production site and credential-disabled Forgejo checks hit proxy HTTP
403; their current deployed state remains unknown. Publication, private backend
provisioning, operator/company actions and representative full-episode listening
require their respective owners or infrastructure; local code does not close
those gates.

## Validation and remaining scope

The earlier complete integration checkpoint passed **7,320 tests, with 183 skipped and 8 warnings**,
in 899.29 seconds with that checkpoint frozen. Later trim/speed staging and
finite-time validation are tracked by the separate [PR validation gate](../../PR_VALIDATION.md);
this earlier run does not establish the final publication tree. [Validation](validation.json)
and the [full log](full-suite.log) preserve command, scope and outcome. Ruff,
whitespace checks, compatibility imports and `kino doctor` pass; all 1,113 Python
files parse. Earlier iteration checkpoints are historical and are not added to
that count.
Focused runs cover the actual media and failure behaviors described in each
review. Optional backend skips are not evidence that those backends work.

Remaining limits are explicit: some direct effect writers are not transactional.
Trim/speed now stage output and construct results before destination replacement;
this is scoped failure preservation, not universal engine publication coverage. Ken Burns VFR equivalence is
unproven; motion coherence is a bounded measured proxy, not artistic judgment;
model-quality comparisons still need representative labeled media and backend
access. New mixing and plain-file ducking APIs add no MCP/CLI registrations.

The full [Unreleased changelog](../../../../CHANGELOG.md) includes this batch
and the earlier optimization/reliability work. Living user, workflow, receipt,
quality, lifecycle and architecture documentation is updated; historical
release proofs remain historical.
