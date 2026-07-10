# mcp-video release-hardening handoff — 2026-05-09

> **Historical snapshot.** This handoff predates the Kinocut rename. The
> `mcp-video` name, `mcp_video/` paths, commands, and findings describe the
> repository state on 2026-05-09 and are not current setup instructions.

## Current repo state

Canonical checkout used for this handoff:

```bash
cd <repo>
```

Current verified state at handoff creation:

```text
branch: master
tracking: origin/master
HEAD: d076440 Reject invalid audio compose shape (#290)
status: clean relative to tracked files before this handoff document was created
open PRs: none listed by `gh pr list --state open --limit 20`
open issues: none listed by `gh issue list --state open --limit 20`
```

This file itself is a handoff artifact and may be uncommitted unless a later agent commits documentation changes.

## User intent

The user asked for a bounded release-hardening sweep after two originally observed bugs:

1. Green cast over generated/processed video output made results unusable.
2. Related MCP video feature paths needed investigation before cutting a new release.

The user later asked to stop the loop, then asked for this handoff so another agent can continue if needed.

## What was already fixed and merged

Do **not** repeat these fixes. They are already on `master`.

### Original severe bugs

- PR #263 — <https://git.kyanitelabs.tech/KyaniteLabs/kinocut/pull/263>
  - Fixed green-cast video effects and 24-bit WAV handling.
  - Covered `effect_noise` / `video_overlay` visual output and 24-bit PCM WAV audio effects.

- PR #266 — <https://git.kyanitelabs.tech/KyaniteLabs/kinocut/pull/266>
  - Hardened adjacent media paths.
  - Fixed 24-bit WAV handling in `audio_compose`.
  - Checked Hyperframes version: `npm view hyperframes version dist-tags.latest --json` reported `0.5.5`; no newer package was available during the sweep.

### Hyperframes fixes

- PR #267 — reject unsupported Hyperframes render dimensions.
- PR #272 — report Hyperframes render artifacts correctly by output format, including `png-sequence` directories.
- PR #273 — fail Hyperframes render-and-post/pipeline paths when render artifacts are missing.

### Analysis/reporting correctness

- PR #268 — implemented real `analyze_video(include_colors=True)` color extraction instead of placeholder behavior.
- PR #269 — `video_info_detailed` now returns real dominant colors instead of `None`.

### Swallowed cleanup errors

- PR #270 — pipeline cleanup `OSError`s are surfaced as warnings instead of being swallowed.

### Video/effect validation parity

- PR #271 — reject unknown text animations.
- PR #274 — reject empty animated text at engine and MCP/tool layers.
- PR #275 — reject invalid layout/PIP choices at tool and engine boundaries.
- PR #276 — validate mograph duration/fps/style and reject unknown progress style.
- PR #277 — reject unknown animated text positions.
- PR #280 — reject unknown watermark/overlay positions.
- PR #282 — reject malformed timeline image overlay position dicts before input probing.

### Encoding/export/batch/subtitle validation

- PR #278 — validate convert format/quality before probe/FFmpeg.
- PR #279 — validate HLS qualities and segment duration before probe/FFmpeg.
- PR #281 — reject unsupported `compare_quality(metrics=[...])` metrics instead of reporting meaningless `unknown`.
- PR #283 — validate `video_batch` operation names before input path validation.
- PR #284 — validate malformed subtitle entries/ranges before input path validation.

### Direct/client/server audio validation parity

- PR #285 — `audio_compose()` rejects missing track files instead of silently skipping them and writing partial/empty output.
- PR #286 — `audio_sequence()` rejects unknown/missing event types and unsupported tone waveforms instead of skipping/defaulting/rendering as sine.
- PR #287 — `audio_effects()` rejects unknown/missing effect types instead of silently ignoring them.
- PR #288 — `audio_preset()` rejects invalid `pitch` and `intensity` instead of silently falling back/scaling unsafely.
- PR #289 — `audio_synthesize(effects={...})` rejects unknown effect keys instead of silently ignoring requested processing.
- PR #290 — `audio_compose()` rejects empty tracks, non-dict track entries, non-positive duration, and invalid volume at the direct engine boundary.

## How the bugs were found

The method was intentionally repetitive and evidence-driven:

1. Start from the user-reported symptom, not from assumptions.
2. Inspect local code and current GitHub state:
   ```bash
   git status --short --branch
   gh pr list --state open --limit 20
   gh issue list --state open --limit 20
   ```
3. Search for high-risk patterns:
   ```bash
   rg -n "except Exception|pass$|continue$|\.get\([^\n]*,|fallback|unknown|NotImplemented|return None" mcp_video tests -S
   ```
4. Prioritize public surfaces where bad input could return success or produce plausible wrong media:
   - MCP server tools
   - Python client methods
   - direct engine functions
   - Hyperframes render/pipeline wrappers
5. For every candidate, prove the defect with a failing regression first.
6. Patch the narrowest boundary that makes the behavior fail loudly before media IO/FFmpeg/rendering when possible.
7. Run focused tests, then broader tests, then open an atomic PR.
8. Watch GitHub checks, merge, sync `master`, clean the worktree, and move to the next candidate.

Typical per-fix workflow:

```bash
git worktree add .worktrees/fix-name -b fix-name origin/master
cd .worktrees/fix-name
# write failing tests first
python3 -m pytest <focused tests> -q
# implement minimal fix
python3 -m pytest <focused tests> -q
python3 -m pytest <changed broader tests> -q
python3 -m ruff check <changed files>
python3 -m ruff format --check <changed files>
python3 -m pytest tests/ -x -q --tb=short
python3 -c "import mcp_video"
git add <changed files>
git commit -m "...Lore protocol message..."
git push -u origin <branch>
gh pr create --title "..." --body "...verification..." --base master --head <branch>
gh pr checks <PR_NUMBER> --watch --interval 10
gh pr merge <PR_NUMBER> --squash --delete-branch --admin || true
gh pr view <PR_NUMBER> --json state,mergedAt,mergeCommit,url
cd <repo>
git fetch origin && git pull --ff-only
python3 -c "import mcp_video"
git worktree remove .worktrees/<branch>
git branch -D <branch> || true
```

Note: `gh pr merge --admin` often printed this harmless local worktree-related error even when the remote merge succeeded:

```text
failed to run git: fatal: 'master' is already used by worktree at '<repo>'
```

Always verify merge truth with:

```bash
gh pr view <PR_NUMBER> --json state,mergedAt,mergeCommit,url
```

## Verification evidence from the hardening pass

Every merged fix had fresh local verification and passing GitHub checks before merge. Representative full-suite gates near the end:

```text
1150 passed, 10 skipped
1154 passed, 10 skipped
1158 passed, 10 skipped
1161 passed, 10 skipped
1166 passed, 10 skipped
```

Common gates used:

```bash
python3 -m ruff check .
python3 -m ruff format --check <changed files>
python3 -m pytest tests/ -x -q --tb=short
python3 -c "import mcp_video"
gh pr checks <PR_NUMBER> --watch --interval 10
```

Important caveat: full-repo `ruff format --check .` had pre-existing unrelated drift in:

```text
examples/agent_cookbook.py
```

Changed files were format-checked per PR. If the next agent wants a tiny cleanup PR, formatting `examples/agent_cookbook.py` is safe but should be separated from behavior fixes.

## Remaining observed candidates / things to inspect next

No open PRs or issues were present at the handoff point. The loop stopped because the user said to stop, not because a mathematical proof of zero defects exists.

The next agent should treat the following as **candidates**, not confirmed bugs. Use failing tests before patching.

### 1. Pre-existing format drift

Candidate:

```text
examples/agent_cookbook.py
```

Evidence:

```bash
python3 -m ruff format --check .
# reported: Would reformat: examples/agent_cookbook.py
```

Suggested action:

- Optional docs/example cleanup PR only.
- Do not mix with behavior changes.

### 2. Remaining broad fallback/swallowing patterns

Run this on current `master`:

```bash
rg -n "except Exception|except OSError|pass$|continue$|\.get\([^\n]*,|fallback|unknown|TODO|NotImplemented|return None" mcp_video --glob '*.py' -S
```

High-signal areas from the last scan:

- `mcp_video/quality_guardrails.py`
  - Multiple `except Exception` blocks convert probe/analysis failures into diagnostics or fallback reports.
  - This may be intentional because guardrails should degrade gracefully, but verify whether user-facing “pass/fail” can become misleading success.

- `mcp_video/engine_runtime_utils.py`
  - `_generate_thumbnail_base64` returns `None` on failures and warns.
  - Likely optional preview behavior, but verify if any public tool treats missing thumbnails as complete success without warning.

- `mcp_video/hyperframes_engine.py`
  - Some `pass` / `return None` paths remain around optional composition discovery and file-add response parsing.
  - Many Hyperframes render blockers were already fixed in #267/#272/#273; avoid duplicating those.

- `mcp_video/templates.py`
  - Uses defaults like `quality_bitrate.get(quality, 8.0)` and timeline dict `.get(...)` defaults.
  - Could hide invalid template/timeline values if exposed to public callers. Investigate before editing.

- `mcp_video/image_engine.py`
  - Has a bare-ish `pass` around optional image path cleanup/import behavior. Confirm if this is optional or masks output failure.

- `mcp_video/server_app.py`
  - Startup/import fallback catches broad exceptions for MCP import compatibility.
  - Likely intentional, but be careful because swallowing import errors can make tools unavailable without clear diagnostics.

- `mcp_video/design_quality/guardrails/*`
  - Several broad exception-to-pass or exception-to-warning paths.
  - Likely intended for advisory guardrails, but verify that failures are visible in reports.

### 3. Possible next concrete validation families

After the audio parity fixes, the next most promising families are:

1. Template/timeline validation parity
   - Check whether direct `templates.py` or timeline conversion accepts unknown quality/format/positions and silently defaults.
   - Write tests that assert invalid public template/timeline values fail before FFmpeg/file probing.

2. Quality guardrail truthfulness
   - Check whether probe/color/loudness failures return an overall “pass” without a diagnostic warning.
   - Any fix should preserve graceful degradation but make uncertainty explicit.

3. Optional AI/download/transcribe paths
   - Search for `except Exception` and `continue` in `mcp_video/ai_engine/*`.
   - Be careful: many AI/download paths intentionally continue across candidates/mirrors. Only patch if user-visible success is false or diagnostics are hidden.

4. Hyperframes advisory paths
   - Re-run Hyperframes-specific tests and inspect remaining `pass`/`return None` locations.
   - Do not change render artifact detection again unless you find a new failing test; #272 and #273 already covered that.

## Release caution

Do **not** cut a release unless the user explicitly asks. The work completed so far makes `master` much more release-ready, but release work should include its own version/changelog/package/publish gates.

## Suggested final verification before any release

```bash
git status --short --branch
git fetch origin && git pull --ff-only
python3 -m ruff check .
python3 -m pytest tests/ -x -q --tb=short
python3 -c "import mcp_video"
npm view hyperframes version dist-tags.latest --json
# if release requested, run the repo's packaging/release checks from pyproject/docs
```

If full-repo format is part of the release gate, handle `examples/agent_cookbook.py` first in a separate cleanup commit/PR.
