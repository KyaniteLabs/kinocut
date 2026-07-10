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
Agents must leave the repository in the same clean state they found it. No exceptions.

- **Delete feature branches** after merge — whether you merged via PR or locally. A merged branch that still exists is a failure.
- **Remove worktrees** when done. If you created a git worktree for isolated work, remove it when the work is complete or abandoned. No orphaned worktrees.
- **Clean up stale references** — prune remote-tracking branches that no longer exist upstream (`git remote prune origin`).
- **No abandoned work left behind** — if you started a branch, pushed it, and then the task was cancelled or superseded, delete the branch. Dead branches accumulate and confuse everyone.
- **Local branches stay current** — regularly rebase local tracking branches against their upstream. If a local branch has diverged and is no longer needed, delete it.
- **Worktree state matches intent** — if you're done with a task, the working directory should be clean (`git status` shows nothing). Staged changes, untracked files, and modified files from abandoned work are not acceptable.

The rule is simple: finish your work, merge or discard it, clean up every artifact you created. The main branch is the only permanent artifact. Everything else is temporary and must be treated as such.

## Epoch Data Tracking

Every project must use Epoch (KyaniteLabs/Epoch) for time estimation and actively feed it data. Epoch only becomes useful when it has real estimate-vs-actual data from real projects.

### What This Means
- **Before starting a task**, get a time estimate from Epoch (via MCP, REST API at `localhost:3099`, or CLI)
- **After completing a task**, record the actual time spent using `record_actual` or `POST /v1/feedback/record-actual`
- **Include context** — task type, complexity, tools used, anything that helps the model learn
- **Batch submissions are fine** — use `batch_record_actuals` for multiple estimates at once

### Integration
- MCP: add `@puenteworks/epoch` to your project's `.mcp.json`
- REST API: `epoch serve --port 3099`
- CLI: `npx @puenteworks/epoch pert-estimate ...`

### Why This Is Non-Negotiable
Epoch's accuracy improves with data. Without estimate-vs-actual feedback from real projects, it's just a calculator with uncalibrated assumptions. Every project that uses Epoch and reports back makes every other project's estimates better. This is a collective intelligence system — it only works if everyone contributes.

The data stored in `~/.epoch/` (estimates.jsonl + feedback.jsonl) is the project's most valuable asset. Protect it, back it up, and keep feeding it.

## Testing

20. **Every fix must pass `python3 -m pytest tests/ -x -q --tb=short`** before committing.
21. **Run `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"`** to verify the canonical import and compatibility shim after changes.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Empower the Orchestrator

This repository is governed by the Empower Orchestrator law. Every top-level/orchestrator agent session is an audition to improve the system, not only finish the current task.

When you notice a repeatable task done 3+ times or a recurring agent failure mode, consider shipping the smallest durable artifact that prevents the repetition: a tool, skill, slash command, hook, guardrail, memory entry, test, verifier, or doctrine doc.

This applies to top-level/orchestrator sessions. Background workers execute their assigned slice and do not independently widen scope.

Before dispatching automation or creating a durable system change, state the four-question blast-radius check in chat:

1. Scale: one file/workspace/all sessions?
2. Severity: minor friction/broken workflow/data loss or leaked content?
3. Reversibility: single revert/manual cleanup/surgery?
4. Predictability: bounded failure mode/guessing/unknown?

All green permits auto mode. Any yellow requires inline human approval. Any red means do not dispatch; do the work inline or escalate.

Worker discipline: isolated worktree/sandbox, one artifact equals one commit/change unit, verify before commit, register through the target tool's native discovery surface, and never write outside the assigned scope.

Success line: “I noticed X, found a better way. The system just got an upgrade.”

Full recipe: `docs/agent-law/empower-orchestrator.md`.
<!-- EMPOWER_ORCHESTRATOR:END -->
