## Why

<!-- Explain the user problem, bug, or maintenance risk this PR addresses. -->

## What changed

<!-- Keep this concrete and reviewable. -->

## Verification

<!-- Paste commands and outcomes. Prefer focused tests plus the relevant broader suite. -->

- [ ] `python3 -m pytest tests/ -x -q --tb=short`
- [ ] `python3 -c "import kinocut, mcp_video"`
- [ ] `./scripts/git-professional-audit.sh`
- [ ] Other:

## Maintainer checklist

- [ ] Public MCP tool signatures are unchanged, or the compatibility impact is explained.
- [ ] New or changed FFmpeg filter strings escape user-controlled values with `_escape_ffmpeg_filter_value()`.
- [ ] Subprocess calls include a timeout and route FFmpeg failures through `ProcessingError`.
- [ ] New defaults live in `defaults.py`; validation constants live in `validation.py` or `limits.py`.
- [ ] No generated media, logs, caches, local research dumps, or build artifacts were committed.
- [ ] Documentation, README counts, or roadmap entries were updated when the public surface changed.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Empower Orchestrator checklist

- [ ] I checked whether this PR reveals a repeatable task or recurring agent failure.
- [ ] If it does, I either shipped the smallest durable improvement or documented why not.
- [ ] Any automation or durable system change included the scale/severity/reversibility/predictability blast-radius check.
- [ ] Workers/subagents stayed inside their assigned scope and verification evidence is included before completion claims.
<!-- EMPOWER_ORCHESTRATOR:END -->
