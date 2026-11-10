# KINOCUT QoL PASS — Engineering Spec (CEO-approved ALL 7, 2026-10-26)

Base: KyaniteLabs/kinocut @ master (post-#599, post-#637/#638). All work on feature branches → PRs to master. No release cuts (November door-walk owns 1.16.5 + yaml pin-bump PR).

## Guardrail floor (non-negotiable)
- teknium-approved security posture unchanged: telemetry/network/overwrite defaults stay as-is.
- No behavioral change to how guards DENY — only better messages after denial.
- T1–T6 checklist applies to every PR.

## Item 1 — Tool diet with profiles (M)
- Default MCP surface: curated ~20 core tools (registry dump: 211 defs in server_tools*.py; core confirmed: video_info/trim/merge/add_text/add_texts/add_audio/resize/convert/speed + search_tools + receipts + doctor-class).
- Everything else: hidden from default registration; discoverable via search_tools (already exists); exposed via env KINOCUT_TOOLS=all or KINOCUT_TOOLS=profile:editor etc.
- Registry mapping: one declarative table (tool name → profile tags) so the diet is config, not code edits.
- Acceptance: default server registers ≤25 tools; KINOCUT_TOOLS=all registers 203+; search_tools finds hidden tools with the flag to enable.

## Item 2 — Errors that teach (S)
- Audit every user-facing refusal/exception path (overwrite guard, protected paths, network-off, missing ffmpeg, bad timecodes).
- Each error message ends with the exact retry invocation that would succeed (CLI form + MCP param form), e.g. "...; retry with overwrite=true (MCP) / --overwrite (CLI)".
- Acceptance: test asserting every refusal message contains a retry token; no silent failures.

## Item 3 — One-call shorts flow (M)
- New MCP tool video_shorts(input_path, segments, style?) → trim → caption → vertical template → export, ONE receipt chain.
- Acceptance: agent calls 1 tool, gets artifact paths + receipts; underlying calls reuse existing engines (no new ffmpeg paths).

## Item 4 — Startup snap (S–M)
- Measured warm: doctor ≈3.5s, info ≈1.7s (2026-10-26, Mac.lan, uvx 1.16.4). Target: warm info < 1.0s.
- Lazy-import heavy modules (server tool registration defers; ffmpeg checks defer to first use); cache env resolution.
- Acceptance: before/after timing in PR body; no import-time side effects.

## Item 5 — Streaming progress (S)
- Verify _mcp_progress_reporter renders in Hermes desktop on a >30s render; wire progress into long ops missing it.
- Acceptance: live progress observed in desktop; screenshot/diff receipt.

## Item 6 — Skill = the manual (S) [growth seat]
- SKILL.md (≤250 chars, first-57 trigger) + llms.txt + docs/TOOLS.md audited as one coherent quick-start: recipes, guardrail FAQ, receipts, tool-diet explanation.
- Acceptance: new-agent cold test picks right tools without TOOLS.md spelunking.

## Item 7 — video_doctor() MCP preflight (S)
- Expose doctor as MCP tool (ffmpeg present/versions, perms, disk, env flags in effect).
- Acceptance: agent can call video_doctor() pre-job and get JSON verdict.

## Item 8 — Documentation pass (CEO-directed 2026-10-26) [growth seat]
- README: refresh badges (203 tools / 177 commands change when item 1 lands — badge reflects default surface), Producer Stack framing, eyes-free design law stated.
- docs/TOOLS.md + llms.txt: post-diet tool map, profiles documented, recipes.
- SKILL.md: ≤250 chars, first-57 trigger, intent-first quick start.
- Acceptance: no doc still describes the pre-diet surface as default.

## Item 9 — Contributor credits (CEO-directed 2026-10-26)
- Changelog entries credit externals by handle: Beritwu — exact probe (#599, Co-authored-by already in squash); Mimatovitch — macOS cleanup bug report (#594, Reported-by line added to the 1.16.1 section; post-hoc credit = text edit, not history rewrite).
- README acknowledgments section listing external contributors.
- Acceptance: every external contribution in the shipped history is credited by handle.

## QA gates per PR
T1 destructive-write guard · T2 skills never mutate host · T3 network honesty/defaults-off · T4 dependency contract · T5 tool-surface narrowing (item 1 IS T5) · T6 pinned verifiable launches.
