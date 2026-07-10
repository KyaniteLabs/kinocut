# Kinocut - The Speculative Roadmap (2026-2028)

**Nine-lane research synthesis, 2026-07-09.** Lanes: 4 Claude web-research agents (competitive landscape, frontier, demand, virality mechanics) + Codex (in-repo architecture audit), Kimi (futurist), GLM-5.2 (red-team bear case), Antigravity (wedge features). MiniMax lane failed (provider stream errors, twice); its angle was absorbed by the frontier and strategy lanes.

---

## The verdict in one paragraph

At the pre-rename planning snapshot, Kinocut (then named `mcp-video`) was, in Codex's words, **"a guardrailed media RPC toolbox, not yet an agentic editor."** Every lane, independently, converged on the same diagnosis: the tool was positioned as a utility, and - per GLM's red team - **"utilities get used; they don't get talked about."** The most-talked-about crown in this field is unclaimed (the competitive lane confirmed ~40 video MCP servers, no winner, zero official vendor entries), and it will go to whoever ships the **trusted execution layer for agentic video**: durable editing state, renders that watch themselves, and one killer product motion on top. Kinocut's existing moat - guardrails - is the only defensible differentiator it has (GLM's ranking), and it happens to be the exact seed of that trust layer. The gap between the snapshot's "119-tool wrapper" and "the runtime every video agent calls" is three architectural bets and one distribution playbook.

---

## Tier 1 — The three bets that flip the game

### 1. The Editing Kernel ("git for video")

The single deepest finding. In the pre-rename snapshot, Codex found **118 of 119 tools were synchronous**, 74 took `input_path`/75 returned `output_path` (filesystem paths as identity), the `Timeline` model was a one-shot render DTO with no stable node IDs (`kinocut/models.py:310`), the executor flattened all video tracks into one list and deleted state after every call (`kinocut/engine_timeline.py`), and the only cache was an in-memory ffprobe cache that died on restart. Agents could not inspect, branch, undo, or resume an edit.

The bet — five primitives (Codex's API sketches are in the appendix):
- **Durable projects + revisions**: unit of work becomes `project_id + revision_id`, not paths. Every mutation targets a base revision, applies typed operations atomically, returns a semantic diff. Undo = checkout. Alternate cuts = branches. Concurrent agents = compare-and-swap.
- **Timeline IR**: a typed, immutable graph (rational timebases, stable node IDs, effect stacks, nested sequences) that compiles to a render DAG.
- **Async render jobs**: submit → job_id → progress/cancel/resume/partial-range → progressive artifacts. The MCP spec just blessed this shape: the **Tasks primitive (SEP-1686)** is on the official 2026 roadmap. Build against it early and Kinocut is idiomatic the day every client supports it.
- **Content-addressed media store**: assets, proxies, transcripts, scene maps, renders — all digest-keyed, provenance-carrying, reachability-GC'd. Identical work never repeats.
- **Event control plane**: `render.segment.ready`, `quality.gate.failed`, `review.patch.proposed` — the substrate bet #2 runs on.

Kimi arrived at the same place from the future backwards: the winner is not the best editor but the **"Nix/Docker for video"** - a text-first, diffable video DAG where the .mp4 is a build artifact, enabling per-viewer compiled variants and video-as-CI. The tool surface does not die; it becomes compatibility adapters that compile into the kernel (Codex: "the next architectural move is not another tool").

### 2. The Watching Guardrail (renders that review themselves)

The frontier lane's sharpest gap: **"nobody couples a deterministic FFmpeg-level editor with a VLM critic loop as an open protocol."** Diffusion Studio's agent proved the render→watch→refine loop (VLM sampling frames at 1fps) but is browser-engine-bound and dormant; `watch-skill` (134★ at snapshot) markets "the agent watches its own work and fixes it" but is vision-only. The competitive lane's finding #5: **no one combines metric QC (VMAF/loudness) + vision QC (VLM frame grading) + narrative QC (pacing, hook, retention)**. Kinocut already owns the metric third.

The bet: evolve guardrails from *static preflight* to a **closed review loop** — exactly Codex's primitive #5 and Antigravity's "Director loop":
1. Render (or partial render of a proxy).
2. Sample keyframes + audio features around edit points.
3. Grade: objective metrics (VMAF, LUFS, black frames, A/V sync) + VLM rubric ("is the caption legible? overlapping a face?") + retention heuristics (first-15-seconds check — the demand lane found practitioners hand-check exactly this).
4. Return **findings anchored to time ranges and timeline node IDs, with proposed typed mutations** — never silent auto-mutation.
5. Bounded iteration (`max_iterations`, required gates) until pass.

This is the tagline the whole synthesis points at: **"Guardrails today are static; tomorrow they watch the output."** It converts the one defensible moat into the category-defining feature, and it grades *the edit*, not just the finished file — which the frontier lane identified as the open research gap (retention prediction today works at "rank my clips" fidelity, not "this cut at 00:12 loses viewers").

### 3. Repurposing as THE product (GLM's bear→bull flip)

GLM's red team was asked for the one ship that flips the bear case, and its answer is backed point-for-point by the demand lane: **an opinionated, one-command long-form→short-form pipeline as the product, everything else demoted to internals.**

Why it's the flip: it converts "no generation" from fatal gap to stated scope; it is the only hot, monetizable, search-intent-heavy use case in deterministic video ("turn my podcast into TikToks" has buyers; "call FFmpeg over MCP" does not); it makes the broad tool surface cohere as depth-of-pipeline instead of sprawl; and the pipeline's *output is the viral artifact*, fixing the demo problem for free.

Demand-lane evidence this wins: the #1 unmet ask across every incumbent is **steerable moment selection** ("wish I could train Opus on MY content" - r/NewTubers); r/selfhosted is asking verbatim for "a local Opus Clip"; a cottage industry of OSS clones (reelforge, Podcli) already markets *"plugs into Claude Code" as the interface*; incumbents charge credit-math users resent (1 credit/source-minute, no rollover, watermark ransom) while racing to bolt MCP onto cloud SaaS. Kinocut is the guardrailed, local, no-meter native in the exact spot the market is running toward.

The spec, from demand-lane JTBD ranking: steerable/trainable highlight detection (#1), speaker-aware 9:16 reframe — the acknowledged moat feature of OpusClip (#2), reliable word-timed styled captions (#3, reliability itself is the differentiator; Captions.ai's desync bug is notorious), and QC guardrails as a feature (#10: transcript-confidence gating, first-15s check, idempotent publishing) — with humans kept only at hook/thumbnail/final-review, the checkpoints practitioners refuse to automate anyway.

---

## Tier 2 — Force multipliers

**4. Intent-verb surface.** GLM's most actionable strike: the broad exposed schema set is a *tax on the agent* (the only real user) - selection accuracy degrades, tokens burn. Collapse the default exposed surface to ~8-12 semantic verbs (`remove_silence`, `reformat_vertical(subject_tracking=auto)`, `cut_to_beats`, `inject_broll`) plus a `video_intent` router; retain the full surface as internals/compatibility. The exact count becomes a depth claim instead of a liability. Codex independently said the same: freeze existing tools as compatibility adapters.

**5. The generative last-mile.** Don't generate — *finish*. The frontier lane's proof that abstraction wins: Sora 2's entire Videos API is deprecated 14 months after launch, while Gemini Omni Flash made conversational video editing a first-party primitive. Ship a provider-agnostic `generate` adapter (cloud APIs + local open-weights Wan 2.2 / LTX-2 / HunyuanVideo on a 24GB GPU), then own what every generated clip needs anyway: fps/color normalization, upscale, audio replacement, loudness, stitching with deterministic transitions and captions — plus the guardrails that only matter once generation enters the loop: **spend caps before the API call, prompt logging for reproducibility, and C2PA provenance signing** (EU AI Act Art. 50 synthetic-content labeling becomes enforceable **August 2026**; the competitive lane confirmed *no video MCP ships C2PA today* — being first is both a compliance story and a press story).

**6. OTIO in/out.** OpenTimelineIO is the agent-legible EDL — diffable, human-reviewable, and the interchange into DaVinci/Premiere/FCP. The NLE-MCP cluster is the fastest-growing corner of the ecosystem (davinci-resolve-mcp doubled to 1,507★ in ~3 months); auto-editor (4.5k★) exports NLE projects; nobody owns OTIO in MCP. Frontier lane: "cheap to claim, unclaimed."

**7. A review surface humans can watch.** The competitive lane's HITL lesson: FableCut's live co-edited `project.json` timeline and Descript's transcript UX are two working answers; MCP-only servers - Kinocut included - give a non-technical human nothing to watch. With the kernel in place, a hot-reloading timeline/preview page (Hyperframes can render it) is cheap and makes "agent proposes, human approves" real.

---

## Tier 3 — Distribution (features don't get talked about; moments do)

The virality lane's finding: this category blows up on X demos and default lists, not HN. The playbook, ranked by replicability:

1. **The Remotion move** (Jan 2026: one tweet, "make videos just with Claude Code," one-line skill install → 8.89M views in a day, 126k installs): Kinocut has a canonical `skills/kinocut/` entry. Package the repurposing pipeline as an agent skill with a one-line install and post one genuinely good output with "made just by prompting."
2. **The self-edited launch video** - *"this launch video was cut by the agent using Kinocut; manifest attached."* The virality lane checked: no one had claimed this format at the snapshot. It is simultaneously the demo of bets #1-3.
3. **Own the benchmark** (the Aider mechanic): publish a **Video-Editing Agent Bench** - which models complete real edit tasks through Kinocut. Every model release becomes free press.
4. **Grind the lists**: the pre-rename project was absent from the roundups deciding the niche (vidocu's "11 best video MCP servers," ffpipe). Re-check and submit under Kinocut after launch. The stale GitHub Pages copy was corrected during Phase 0. Then pursue Docker MCP Catalog, Claude Connectors verified tier, awesome-mcp lists, an n8n template, and one faceless-automation tutorial.
5. **Guardrails-as-story**, backed by third-party data: Bloomberry's analysis of 1,412 MCP servers found the average server has 1–4 tools and 38.7% ship no auth. "The guardrailed platform in a sea of thin wrappers" is press-ready contrast.
6. **Housekeeping with teeth**: the npm `mcp-video` name is a *different product* (studiomeyer-io's, active). Claim/defend the namespace story before the confusion compounds.
7. **Rename before the moment** (step 0 of the identity pivot): the `mcp-video` name was protocol-bound, generic among 7+ lookalike wrappers, and collided on npm. This decision was executed as **Kinocut** on 2026-07-10; the compatibility package/CLI remain for migration while all new discovery uses Kinocut.
   **Brainstorm executed 2026-07-09** (kimi=cinema history, glm=failure-mode screen, agy=brand systems/ES cognates, codex=dev ergonomics; 54 candidates swept across PyPI+npm+GitHub+RDAP). Finalists, all free on PyPI, npm, and GitHub-clean with .dev available: **kinocut** (`kino` CLI; Kino-Pravda "cinema truth" lineage; 0 GitHub hits), **proofcut** (the thesis as a name: every cut ships with proof; codex's #1), **verocut** (truth-rooted, most bilingual-safe, .dev AND .com free). Honorable: cutrail (guardrail pun). Killed by data: toma/kino/prisma/splice (package collisions), pauta/cobalto (701/109 GitHub name hits), moviola (living trademark), croma (Whisper writes "chroma"). **DECIDED (Simon, 2026-07-09): Kinocut** — CLI `kino`, home kinocut.dev, kinocli.* as redirects. Execution issue: git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/53 (after the in-flight release ships).

## Traps (Kimi + GLM, agreeing)

Full autonomy theater ("single click, no human" is the failure smell — HN consensus and a16z both say end-to-end doesn't exist yet; ship bounded loops with human gates). Competing with generators head-on (solo maintainer vs. funded giants; be the last mile). Emotion-adaptive editing, NFT provenance, avatar farms, spatial-video-first (Kimi's trap list). And the meta-trap: adding tool #120 instead of building the kernel.

## The one-line answer to "what's stopping it"

It's not a missing feature — it's a missing *identity*. The features that exist answer "what can an agent do to a video file"; the unclaimed crown answers **"why would an agent-built video be trusted, resumed, reviewed, and shipped."** Kernel + watching guardrail + repurposing product + one 30-second "made just by prompting" moment = the most talked-about tool in the field.

---

## Appendix — lane outputs (full texts on disk)

| Lane | Backend | File |
|---|---|---|
| Competitive landscape | Claude agent (web) | `out-competitive-agent.md` (summary; full in transcript) |
| Frontier agentic video | Claude agent (web) | `out-frontier-agent.md` (summary; full in transcript) |
| Demand / JTBD | Claude agent (web) | `out-demand-agent.md` (summary; full in transcript) |
| Virality mechanics | Claude agent (web) | `out-virality-agent.md` (summary; full in transcript) |
| Architecture audit | Codex (gpt-5.6-sol, in-repo) | `out-codex.md` |
| Futurist 2027–28 | Kimi | `out-kimi.md` |
| Red-team bear case | GLM-5.2 | `out-glm.md` |
| Wedge features / positioning | Antigravity | `out-agy.md` |
| Generative bridge | MiniMax via pi | FAILED ×2 (stream errors) — angle covered by frontier/GLM/agy lanes |

Credit where the ideas came from: the render→watch→fix loop pattern is proven by **Diffusion Studio's agent** and **oxbshw/watch-skill**; the skill-install viral mechanic is **Remotion's**; the benchmark-as-marketing mechanic is **Aider's (Paul Gauthier)**; the live co-edited JSON timeline is **FableCut's**; editing-skill archiving is **FireRed-OpenStoryline's (Xiaohongshu)**; the "intent-oriented tools, not API wrappers" framing echoes the 2026 MCP design discourse (Ankit Rana, mcpbundles, Auth0); "rendering is infrastructure, not prompting" is **Shotstack's**.
