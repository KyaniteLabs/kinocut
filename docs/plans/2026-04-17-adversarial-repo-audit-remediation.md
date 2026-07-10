# Adversarial Repo Audit Remediation Implementation Plan

> **Historical document.** Remotion was removed in v1.3.0/v1.3.1. This plan is preserved for reference only.

**Goal:** Turn `mcp-video` from a high-speed agent-built repo with strong raw capability into a trusted, discoverable, maintainable open source project that can compound GitHub adoption.

**Architecture:** Separate the plan into trust rails, adoption/discovery, maintainability, integration hardening, and growth loops. Preserve the public MCP/Python/CLI API while splitting oversized internals and deleting duplicated helper paths.

**Tech Stack:** Python 3.11+, MCP, FFmpeg, Remotion, GitHub Actions, PyPI, GitHub Pages, MCP Registry, static HTML, `llms.txt`, `robots.txt`, JSON-LD, Ruff, pytest.

---

## Executive Read

The repo has real product value: 83 MCP tools, 858 tests collected, working PyPI/package/release machinery, and a clear wedge: "video editing for AI agents." The risk is not that it is useless. The risk is that it looks and behaves like it grew too fast.

The leverage move is to turn the repo from "large pile of agent-created capability" into "boring trusted infrastructure for agent video workflows." That means:

1. Make public trust signals impossible to misread.
2. Make AI agents and humans discover the same canonical entry points.
3. Split giant files only after behavior is locked.
4. Kill duplicated FFmpeg/error handling paths.
5. Build distribution loops around MCP directories, demos, good first issues, and discussions.

## Evidence Snapshot

- GitHub queue: zero open issues and zero open PRs after stale issue/PR cleanup.
- GitHub adoption baseline: community profile reports 100 percent.
- Repo metrics: 4 stars, 3 forks at audit time.
- Package state: `pyproject.toml` is `1.2.1`, but latest GitHub release is still `v1.2.0`.
- Tool count: AST count found 83 `@mcp.tool()` handlers.
- Tests: `pytest --collect-only -q` collected 858 tests. Non-slow suite result: 733 passed, 9 skipped, 114 deselected, 2 xpassed.
- Oversized modules violating project rules:
  - `mcp_video/engine.py`: 3855 LOC
  - `mcp_video/server.py`: 3467 LOC
  - `mcp_video/__main__.py`: 2908 LOC
  - `mcp_video/ai_engine.py`: 2018 LOC
  - `mcp_video/client.py`: 1430 LOC
  - `mcp_video/design_quality.py`: 1237 LOC
  - `mcp_video/effects_engine.py`: 1048 LOC
  - `mcp_video/audio_engine.py`: 902 LOC
- Oversized functions:
  - `mcp_video/__main__.py:167 main`: 2737 lines
  - `mcp_video/ai_engine.py:1785 analyze_video`: 233 lines
  - `mcp_video/engine.py:1210 convert`: 201 lines
  - `mcp_video/ai_engine.py:1309 ai_upscale`: 201 lines
  - `mcp_video/engine.py:2122 _apply_composite_overlays`: 192 lines
- Duplicated helper paths:
  - `_run_ffmpeg`: `ffmpeg_helpers.py` and `engine.py`
  - `_get_video_duration`: `ffmpeg_helpers.py` and `ai_engine.py`
  - `_seconds_to_srt_time`: `ffmpeg_helpers.py` and `ai_engine.py`
- Error-contract drift:
  - Raw `ValueError`, `RuntimeError`, and `FileNotFoundError` still appear in engines/client paths.
  - Several failures still embed or parse `result.stderr` directly instead of routing through structured error classes.
- Local artifact pressure in the main checkout:
  - Repo directory: 3.1 GB
  - `explainer-video`: 1.9 GB
  - `.venv`: 1.0 GB
  - `out`: 67 MB
  - `.omx`: 9.5 MB
- CI blind spot:
  - CI checks `ruff format --check mcp_video/`, but local `ruff format --check mcp_video/ tests/` showed all test files would be reformatted before this audit branch.

## External Discovery Evidence

- OpenAI crawler docs separate `OAI-SearchBot` for ChatGPT search visibility from `GPTBot` for model training control: https://developers.openai.com/api/docs/bots
- Anthropic documents separate `ClaudeBot`, `Claude-User`, and `Claude-SearchBot`; blocking search/user bots can reduce visibility in Claude search/user retrieval: https://privacy.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler
- Google recommends structured data validation, crawlability, and sitemap submission for software-app search presentation: https://developers.google.com/search/docs/appearance/structured-data/software-app
- MCP Registry supports PyPI package metadata and verifies PyPI ownership through an `mcp-name` marker in the package README: https://modelcontextprotocol.io/registry/package-types

## Completed In This Branch

Files added:

- `.github/CODEOWNERS`
- `.github/DISCUSSION_TEMPLATE/ideas.yml`
- `.github/DISCUSSION_TEMPLATE/q-a.yml`
- `.github/DISCUSSION_TEMPLATE/show-and-tell.yml`
- `.github/dependabot.yml`
- `CHANGELOG.md`
- `GOVERNANCE.md`
- `MAINTAINERS.md`
- `docs/AI_AGENT_DISCOVERY.md`
- `llms.txt`
- `robots.txt`
- `server.json`
- `sitemap.xml`

Files updated:

- `README.md`
- `index.html`
- `pyproject.toml`
- `scripts/repo-readiness-audit.py`
- `docs/repository-audit-checklist.md`

GitHub settings updated:

- Discussions enabled.
- Wiki disabled so docs stay canonical.
- Delete branch on merge enabled.
- Update branch enabled.
- Secret scanning enabled.
- Secret scanning push protection enabled.
- Topics expanded to the GitHub maximum of 20.
- Repo description updated from 82 tools / 690+ tests to 83 tools / 858 tests collected.
- Routing labels added for areas, cleanup, performance, reproduction, blocked state, and low priority.

## ROI-Ordered Remediation

### P0. Trust And Distribution Rails

#### Task 1: Publish the missing `v1.2.1` release

**Why:** Public package metadata says 1.2.1, README says 1.2.1, but GitHub latest release is 1.2.0. That is a trust tax.

**Files:**
- Verify: `pyproject.toml`
- Verify: `CHANGELOG.md`
- Verify: `README.md`

**Steps:**

1. Run:

   ```bash
   git fetch --tags origin
   git tag --list --sort=-creatordate | head
   gh release list --repo KyaniteLabs/kinocut --limit 10
   ```

2. If no `v1.2.1` tag exists, create a signed or annotated tag from current `master` after CI is green:

   ```bash
   git checkout master
   git pull --ff-only
   python -m pytest tests/ -q -m "not slow" --tb=short
   python -m build
   python .github/scripts/check-built-artifacts.py dist
   git tag -a v1.2.1 -m "Release v1.2.1"
   git push origin v1.2.1
   gh release create v1.2.1 --title "v1.2.1" --notes-file CHANGELOG.md
   ```

3. Confirm PyPI trusted publishing runs from the release event.

**Expected outcome:** GitHub latest release, README, PyPI, `server.json`, and `pyproject.toml` all agree.

**ROI:** Very high. **Effort:** Low. **Risk:** Low.

#### Task 2: Land the adoption/discovery branch

**Why:** This branch adds the public trust and agent-discovery substrate that GitHub's community score does not fully capture.

**Files:**
- New and updated files listed in "Completed In This Branch."

**Steps:**

1. Run:

   ```bash
   python -m json.tool server.json >/dev/null
   ./scripts/repo-readiness-audit.py
   ruff check mcp_video/ tests/
   ruff format --check mcp_video/
   python -m pytest tests/ -q -m "not slow" --tb=short
   ```

2. Commit using Lore protocol.
3. Push branch.
4. Open PR.
5. Merge after CI passes.

**Expected outcome:** GitHub users and AI agents get canonical docs, registry metadata, discussions, labels, governance, and crawlable discovery files.

**ROI:** Very high. **Effort:** Low. **Risk:** Low.

#### Task 3: Add branch protection without bricking solo maintenance

**Why:** This is the line between "personal project" and "project people trust."

**GitHub settings:**
- Protect `master`.
- Require status checks:
  - `Lint`
  - `Package surface`
  - `Test (Python 3.11)`
  - `Test (Python 3.12)`
  - `Test (Python 3.13)`
  - `Docker build`
- Require branches to be up to date before merge.
- Block force pushes.
- Block deletions.
- Allow admins to bypass initially, then revisit.

**Steps:**

1. Apply in GitHub UI first to avoid API misconfiguration.
2. Open a tiny test PR and verify maintainer workflow.
3. Document final settings in `docs/git-branch-governance.md`.

**Expected outcome:** Contributors cannot accidentally land broken `master`.

**ROI:** High. **Effort:** Low. **Risk:** Medium if configured too aggressively.

### P1. Kill Integration Hell

#### Task 4: Introduce `mcp-video doctor`

**Why:** Optional dependencies are the integration trap. Users need a single truth source for FFmpeg, drawtext, vidstab, Node, npm, Remotion, Whisper, Demucs, OpenCV DNN, and image extras.

**Files:**
- Modify: `mcp_video/__main__.py`
- Create: `mcp_video/doctor.py`
- Test: `tests/test_doctor.py`
- Docs: `README.md`, `docs/AI_AGENT_DISCOVERY.md`

**Behavior:**
- `mcp-video doctor --json`
- Reports installed/missing/optional/required.
- Never imports heavyweight optional packages unless probing that feature.
- Returns actionable install guidance.

**Steps:**

1. Write failing tests for JSON shape and missing-tool behavior.
2. Implement `doctor.py` with small probe helpers.
3. Wire CLI subcommand.
4. Add README troubleshooting snippet.
5. Run:

   ```bash
   pytest tests/test_doctor.py tests/test_cli.py -q
   ```

**ROI:** Very high. **Effort:** Medium. **Risk:** Low.

#### Task 5: Make dependency extras honest and cheap

**Why:** Current optional extras can scare users or fail on heavyweight AI packages. The default install should feel boring.

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `mcp_video/ai_engine.py`
- Test: `tests/test_ai_features.py`

**Plan:**
- Keep base install minimal.
- Split AI extras into narrower groups:
  - `transcribe`
  - `stems`
  - `upscale`
  - `image`
  - `all-ai`
- Ensure missing dependency errors name the exact extra.

**ROI:** High. **Effort:** Medium. **Risk:** Medium due packaging compatibility.

#### Task 6: Add integration smoke matrix

**Why:** The test suite is broad, but optional integrations need explicit smoke lanes so failures are attributable.

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/integration-smoke.yml`
- Modify: `docs/repository-audit-checklist.md`

**Lanes:**
- Base import and CLI help.
- FFmpeg smoke.
- Remotion validation smoke.
- Image extra import smoke.
- AI dependency import smoke where feasible.

**ROI:** High. **Effort:** Medium. **Risk:** Low.

### P1. Shrink The Slop Without Breaking The Product

#### Task 7: Split `__main__.py` first

**Why:** The CLI `main` function is the worst concentration of accidental complexity: 2737 lines. It is high ROI because it is mostly routing, not deep media logic.

**Files:**
- Create: `mcp_video/cli/__init__.py`
- Create: `mcp_video/cli/parser.py`
- Create: `mcp_video/cli/handlers.py`
- Create: `mcp_video/cli/output.py`
- Modify: `mcp_video/__main__.py`
- Test: `tests/test_cli.py`

**Steps:**

1. Add characterization tests around `--help`, JSON output, and representative commands.
2. Move parser construction without behavior changes.
3. Move output formatting helpers.
4. Move command handlers by family.
5. Leave `__main__.py` as a thin entrypoint.
6. Run:

   ```bash
   pytest tests/test_cli.py -q
   ruff check mcp_video/
   ```

**ROI:** High. **Effort:** Medium. **Risk:** Medium.

#### Task 8: Split `server.py` into tool groups

**Why:** MCP tool registration is public surface, but one 3467-line file makes every change risky.

**Files:**
- Create: `mcp_video/tools/core.py`
- Create: `mcp_video/tools/audio.py`
- Create: `mcp_video/tools/effects.py`
- Create: `mcp_video/tools/remotion.py`
- Create: `mcp_video/tools/ai.py`
- Create: `mcp_video/tools/resources.py`
- Modify: `mcp_video/server.py`
- Test: `tests/test_server.py`

**Rule:** Do not change tool names, parameter names, defaults, or return shapes.

**Validation:**

```bash
pytest tests/test_server.py -q
python - <<'PY'
from mcp_video.server import mcp
print(mcp.name)
PY
```

**ROI:** High. **Effort:** High. **Risk:** Medium-high.

#### Task 9: Split `engine.py` only after server/CLI routing is stable

**Why:** `engine.py` is huge, but it holds the highest behavioral risk. Cut it by capability after public wrappers are stable.

**Target layout:**
- `mcp_video/engines/probe.py`
- `mcp_video/engines/core.py`
- `mcp_video/engines/text.py`
- `mcp_video/engines/audio_video.py`
- `mcp_video/engines/timeline.py`
- `mcp_video/engines/metadata.py`
- `mcp_video/engines/batch.py`

**Compatibility:** Keep imports from `mcp_video.engine` working by re-exporting public functions during migration.

**ROI:** High. **Effort:** High. **Risk:** High.

### P1. Unify Error And FFmpeg Contracts

#### Task 10: Delete duplicate helpers

**Why:** Duplicated FFmpeg helpers are where safety policies fork silently.

**Files:**
- Modify: `mcp_video/engine.py`
- Modify: `mcp_video/ai_engine.py`
- Modify: `mcp_video/ffmpeg_helpers.py`
- Test: `tests/test_adversarial_audit.py`, `tests/test_ai_features.py`, `tests/test_engine.py`

**Targets:**
- Use `ffmpeg_helpers._run_ffmpeg`.
- Use `ffmpeg_helpers._get_video_duration`.
- Use `ffmpeg_helpers._seconds_to_srt_time`.
- Keep progress-specific execution separate only where needed.

**ROI:** High. **Effort:** Medium. **Risk:** Medium.

#### Task 11: Replace raw exceptions and raw stderr leaks

**Why:** The project rules say custom errors only. Current code still leaks raw `ValueError`, `RuntimeError`, `FileNotFoundError`, and `result.stderr`.

**Files:**
- Modify: `mcp_video/ai_engine.py`
- Modify: `mcp_video/remotion_engine.py`
- Modify: `mcp_video/effects_engine.py`
- Modify: `mcp_video/client.py`
- Test: `tests/test_errors.py`, `tests/test_adversarial_audit.py`, `tests/test_ai_features.py`, `tests/test_remotion_engine.py`

**Steps:**

1. Add regression tests for each raw exception class.
2. Route FFmpeg failures through `ProcessingError`.
3. Route bad parameters through `MCPVideoError(error_type="validation_error")`.
4. Route missing inputs through `InputFileError`.
5. Preserve public error JSON shape.

**ROI:** High. **Effort:** Medium. **Risk:** Medium.

### P2. CI, Tests, And Release Quality

#### Task 12: Make format checks cover tests or format tests intentionally

**Why:** Local `ruff format --check mcp_video/ tests/` showed all test files would be reformatted while CI only checks `mcp_video/`.

**Options:**
- Low risk: keep CI as-is and document that tests are not formatted.
- Better: run `ruff format tests/`, commit the mechanical change, then update CI to check tests too.

**Recommended:** Format tests in one isolated PR.

**ROI:** Medium. **Effort:** Low. **Risk:** Low-medium due diff size.

#### Task 13: Treat XPASS as debt

**Why:** Two XPASS results mean tests marked expected-fail now pass. That is stale test metadata.

**Files:**
- Search: `rg -n "xfail|XPASS" tests`
- Modify matching tests.

**ROI:** Medium. **Effort:** Low. **Risk:** Low.

#### Task 14: Add readiness audit to CI

**Why:** The repo now has `scripts/repo-readiness-audit.py`; it should guard every PR.

**Files:**
- Modify: `.github/workflows/ci.yml`

**Add step:**

```yaml
- name: Repository readiness audit
  run: ./scripts/repo-readiness-audit.py
```

**ROI:** Medium. **Effort:** Low. **Risk:** Low.

### P2. Performance And Product Quality

#### Task 15: Add probe/result caching inside multi-step workflows

**Why:** Video operations repeatedly call `ffprobe` after each stage. Multi-step workflows can spend unnecessary time probing the same files.

**Files:**
- Modify: `mcp_video/engine.py`
- Modify later: split engine files.
- Test: focused unit tests around `probe` call count with monkeypatching.

**ROI:** Medium. **Effort:** Medium. **Risk:** Medium.

#### Task 16: Add operation timing to results

**Why:** You cannot optimize what you cannot see. Add `elapsed_ms` or `processing_time_ms` to internal metadata without breaking return contracts.

**Files:**
- Modify: `mcp_video/models.py`
- Modify: engine result construction sites.
- Test: `tests/test_models.py`, targeted engine tests.

**ROI:** Medium. **Effort:** Medium. **Risk:** Medium.

#### Task 17: Add golden workflow demos

**Why:** Adoption needs proof, not claims. Three short workflows beat a 3000-word README.

**Create:**
- `examples/agent_prompts/podcast_clip.md`
- `examples/agent_prompts/tiktok_captioned_clip.md`
- `examples/agent_prompts/product_demo_video.md`
- `examples/python/shorts_workflow.py`

**ROI:** High for growth. **Effort:** Low-medium. **Risk:** Low.

### P3. Reach, Virality, And Community Loops

#### Task 18: Publish to MCP directories

**Targets:**
- Official MCP Registry using `server.json`.
- Glama.
- Smithery.
- Awesome MCP server lists.
- Relevant GitHub topic lists.

**Proof checklist:**
- Directory URL added to README.
- Directory URL added to `docs/AI_AGENT_DISCOVERY.md`.
- Screenshot or badge only if it does not create artifact sprawl.

**ROI:** High. **Effort:** Medium. **Risk:** Low.

#### Task 19: Create 5 good-first issues after cleanup plan lands

**Issue seeds:**
- Add `mcp-video doctor`.
- Add one missing CLI smoke test.
- Add one agent prompt example.
- Add one docs snippet for Cursor.
- Add one docs snippet for Claude Desktop troubleshooting.

**Labels:**
- `good first issue`
- `help wanted`
- one `area:*`
- one `priority:*`

**ROI:** Medium-high. **Effort:** Low. **Risk:** Low.

#### Task 20: Make the landing page cite exact proof

**Why:** "690+ real media tests" was overbroad. Specific proof builds trust.

**Files:**
- `index.html`
- `README.md`

**Copy rule:** Prefer exact, verifiable proof over inflated marketing.

**ROI:** Medium. **Effort:** Low. **Risk:** Low.

## Unknown Unknowns To Investigate

1. PyPI download data: install `pypistats` or query BigQuery later to learn if anyone is actually installing.
2. Windows support: current FFmpeg/Remotion assumptions may be macOS/Linux-biased.
3. Optional AI dependency install reliability: Real-ESRGAN/Basicsr/OpenCV/Torch stacks can break by platform.
4. MCP client compatibility: verify Claude Code, Claude Desktop, Cursor, and any official MCP inspector path.
5. Pages indexing: add Search Console only if you control the GitHub Pages property.
6. Remotion licensing: keep `LEGAL_REVIEW.md` current as Remotion terms evolve.
7. Docker image strategy: decide whether Docker is a first-class distribution channel or just CI smoke.
8. Artifact sprawl: decide whether `explainer-video` source belongs in the repo long-term or should move to a marketing/media repo.

## Stop Doing

- Stop adding tools before the integration and docs surface can absorb them.
- Stop accepting generated PRs that patch symptoms while duplicating helper logic.
- Stop claiming exact counts unless generated or verified.
- Stop letting optional dependency failures masquerade as core package failures.
- Stop using the README as the only source of truth for agents.

## North Star

When someone searches "video editing MCP server" or asks an agent "what should I use to let Claude edit video?", `mcp-video` should be the obvious answer because it is:

- easy to install,
- clearly maintained,
- security-aware,
- visible to crawlers and agent discovery systems,
- listed in MCP directories,
- backed by tests,
- small enough internally that contributors can reason about it.
