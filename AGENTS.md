# Kinocut - Project Rules

## Public Agent Skill
- `skills/kinocut/SKILL.md` is the canonical public skill for this repo.
- Invoke `$kinocut` in compatible agent hosts for guarded video inspection, editing, Hyperframes, repurposing, release checkpoints, and human-review workflows.
- `skills/mcp-video/SKILL.md` is a compatibility entry point only. Keep it thin and direct new work to `$kinocut`.
- Keep the skill aligned with `docs/CLI_REFERENCE.md`, `docs/TOOLS.md`, the Python client, and public MCP tool names when those surfaces change.

## Before Writing Any Code

1. **Check if it already exists.** Search `ffmpeg_helpers.py`, `validation.py`, `limits.py`, and `defaults.py` before writing any utility function. Import, don't duplicate.
2. **Check the public API.** Functions registered as MCP tools in `server.py` are the public surface. Internal functions are prefixed with `_`. Don't break tool signatures.

## FFmpeg Security

3. **ALL user-controlled values in FFmpeg filter strings MUST be escaped** with `_escape_ffmpeg_filter_value()` from `ffmpeg_helpers.py`. This includes: colors, fonts, text, paths, and any string that goes into a `-vf` or `-filter_complex` argument.
4. **Gold standard pattern** (from `effects_engine.py:text_animated`):
   ```python
   safe_text = _escape_ffmpeg_filter_value(text)
   safe_font = _escape_ffmpeg_filter_value(font) if font is not None else font
   safe_color = _escape_ffmpeg_filter_value(color) if color is not None else color
   ```
5. **Never use f-string interpolation of user values directly into filter strings** without escaping.

## Error Handling

6. **Always raise custom types from `errors.py`**, never raw `ValueError`, `RuntimeError`, or `FileNotFoundError`.
   - Input file issues → `InputFileError`
   - FFmpeg processing failures → `ProcessingError` (auto-truncates stderr to 500 chars)
   - Bad parameters → `MCPVideoError` with `error_type="validation_error"`
7. **Never embed `result.stderr` directly in error messages.** Route through `ProcessingError` which truncates to 500 chars.
8. **Never use bare `except Exception:` without logging.** Always `except Exception as e: logger.warning(...)`.

## Subprocess Calls

9. **ALL `subprocess.run()` and `subprocess.Popen()` calls MUST have a `timeout` parameter.** Use `DEFAULT_FFMPEG_TIMEOUT` from `defaults.py`.
10. **Catch `subprocess.TimeoutExpired`** and raise `ProcessingError` with a clear timeout message.
11. **Validate input paths** with `_validate_input_path()` from `ffmpeg_helpers.py` before passing to subprocess.

## Configuration

12. **All default values MUST be defined in `defaults.py`.** Reference by name, never hardcode magic numbers like `crf=23`, `timeout=600`, `fps=30`.
13. **Validation constants** go in `validation.py`. Resource limits go in `limits.py`. Runtime defaults go in `defaults.py`.

## Size Limits

14. **No module may exceed 800 LOC.** If it does, split into a subpackage.
15. **No function may exceed 80 lines.** If it does, extract helpers.
16. **No dead code.** If a function/method/constant has zero callers outside its definition, remove it.

## Architecture

17. **`ffmpeg_helpers.py` is the single source of truth** for: `_run_ffmpeg()`, `_validate_input_path()`, `_escape_ffmpeg_filter_value()`, `_get_video_duration()`, `_run_ffprobe()`, `_seconds_to_srt_time()`. Never duplicate these.
18. **`server.py` is the tool registration layer.** Business logic goes in engine modules, not in server tool handlers.
19. **Lazy imports in `server.py`** keep startup fast. Follow the existing pattern: import inside the tool handler function.

## Git Workspace Hygiene
Preserve user-owned repository state and inspect it before any Git cleanup.

- Do not delete branches, remove worktrees, prune remotes, rebase, merge, reset,
  or discard changes unless the task explicitly authorizes the exact operation
  and target.
- Clean up only artifacts created by the current task when that cleanup is safe
  and authorized; otherwise report them for owner direction.
- A clean working tree is a goal only when the task requires it. Never convert
  an existing dirty state into a cleanup task or overwrite user work.

## Contributor CI ownership

When checking external contributions, own the CI investigation instead of handing
the user an unexplained approval gate.

- An empty PR check list is not evidence that CI is absent. Inspect workflow runs
  for the exact PR head; distinguish `action_required`, queued, running, failed,
  skipped and successful runs. Confirm the reason for `action_required`.
- Explain first-time-contributor approval as permission to execute CI. It does
  not approve the code, merge the PR, or grant the contributor repository access.
- Before enabling a run, inspect the complete diff, workflow definitions and
  invoked scripts, token permissions, secrets exposure and runner isolation.
  Do not execute untrusted code on a persistent or privileged runner merely to
  clear the gate. Recheck that the reviewed head still matches the pending run.
- When existing user authority covers normal CI execution and review establishes
  that the run is safe, approve the specific pending runs and verify their actual
  states. Do not ask the user to repeat authorization or perform a routine click.
- If authority, access or safety is unresolved, state the exact blocker, the
  investigation already completed, and the smallest decision or action needed.
  Never substitute a bare "maintainer approval required" status for that work.
- Keep run approval separate from code review and merge gates. Do not disable
  protections, expand token permissions, change repository settings, approve
  future contributions indiscriminately, or post contributor messages without
  the applicable authorization.

## Testing

20. **Every code fix must pass the full suite before merge:** `python3 -m pytest tests/ -x -q --tb=short`. Draft commits and PRs may be created to obtain hosted validation; they are candidates, not verified releases. The hosted PR job runs the full suite, including slow tests, against the candidate head. Reconcile its recorded source SHA with the reviewed head before merging.
21. **Verify the canonical import and compatibility shim in that validation job:** `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"`.

- Use existing hosted runners for heavy tests, renders and builds. Keep a constrained
  coordination machine to light editing, review and CI coordination. A capacity
  hold overrides local test recipes and serialization locks; do not start heavy
  local work, add workers or choose another fleet host without placement authority.
- Run targeted reproductions where needed, then comprehensive validation on the
  frozen candidate. Do not duplicate full local and hosted suites by default or
  repeat unchanged successful checks without a specific unresolved concern.
- Retain source SHA, runtime versions, command, exit status and test/skip evidence.
  Failed, cancelled, missing or skipped required scenarios are not passes. Changes
  to cached-model ASR require real recognition evidence on an assigned host with
  the existing runtime and cache before merge; contract tests alone do not suffice.
  Do not download models or use the coordination host to erase this gap.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Empower Orchestrator law

The canonical law and blast-radius check live in
`docs/agent-law/empower-orchestrator.md`. Read that source when orchestrating
automation or durable system changes.
<!-- EMPOWER_ORCHESTRATOR:END -->
