# QoL CI Fix Progress

## 1. Formatter

- Before: the CI Ruff formatter command reported 10 files needing formatting, including `kinocut/errors.py`.
- Change: ran the repository Ruff formatter over the same CI paths and kept the resulting formatting-only changes together.
- After: `ruff check kinocut/ kinocut_sound/ mcp_video.py tests/` passes; `ruff format --check ...` reports 1,192 files already formatted.
- Version note: the checkout could not fetch the CI-pinned Ruff 0.15.11 because network DNS is blocked. The cached Ruff 0.15.10 formatter and local `uv run` Ruff 0.15.12 both pass.

## 2. Default tool diet

- Before: importing the glitch tool modules after the server initialized leaked 12 glitch tools into the default MCP surface; the failing test observed 32 tools instead of at most 25.
- Change: tagged both glitch modules as `hidden`; enforced the active registry whenever the shared MCP server registers a tool; and reloaded previously imported modules when switching to `all` or discovery so hidden tools remain discoverable without leaking into the active surface.
- After: a default server reports exactly 20 tools and zero `glitch_*` tools, including after both glitch modules are imported; `KINOCUT_TOOLS=all` reports exactly 205 tools, including all 12 glitch tools. `search_tools("glitch")` returns 14 matches while the active default surface remains 20 tools.

## 3. Tests for hidden tools

- Before: MCP calls to `video_create_from_images` failed with `ToolError: Unknown tool`; full-catalog argument tests also ran against the default 20-tool surface.
- Change: added the shared `full_mcp_surface` fixture in `tests/conftest.py`, including subprocess MCP environment propagation, and applied it to tests that exercise hidden MCP tools. Default-surface tests remain unmarked and continue to assert the curated surface.
- After: the targeted `video_create_from_images` MCP tests pass (`6 passed`); the server/glitch test set passes (`74 passed, 4 skipped`); catalog, inspection, workflow, audio-bed, and public default-surface checks pass.

## Verification boundary

The broad local non-slow run was interrupted after 124 seconds at `896 passed, 140 skipped, 164 deselected, 107 failed`; the failures were dominated by this restricted client sandbox rejecting FFmpeg output paths such as `/dev/fd/13`, plus pre-existing architecture-guardrail failures from the QoL tree. No registry or hidden-tool failure remained in the isolated checks above.

## Commit boundary

The requested local commits could not be created because this managed checkout exposes `.git` read-only; Git fails before staging with `Unable to create .git/index.lock: Operation not permitted`. The working-tree changes remain on `fix/qol-ci` at the original `39b50ba` HEAD, with no push or PR attempted.
