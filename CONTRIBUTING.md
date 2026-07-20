# Contributing to Kinocut

Thanks for your interest in improving Kinocut. This is a focused project: every tool should work reliably, and every change should maintain that standard.
External issues and pull requests belong on **[GitHub](https://github.com/KyaniteLabs/kinocut)** — that is the tracked public surface for bugs, features, questions, and contributions.

## Quick Start

```bash
# Clone and install dev dependencies
git clone https://github.com/KyaniteLabs/kinocut.git
cd kinocut
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_engine.py -v
```

## Project Structure

```
kinocut/
├── __init__.py             # Canonical public API
├── __main__.py             # kino/kinocut/mcp-video CLI entry point
├── server.py               # MCP registration assembly (142 tools)
├── server_app.py           # Shared FastMCP app and result helpers
├── server_tools_*.py       # Thin public MCP registration modules
├── engine_*.py             # Focused FFmpeg/media operations
├── client/                 # Python Client mixins and contracts
├── cli/                    # Parsers, handlers, and formatting
├── workflow/               # Plan/validate/render/resume/inspect engine
├── rescue/                 # Dedicated review-first rescue pipeline
├── ai_engine/              # Optional AI analysis and media operations
├── audio_engine/           # Procedural audio and composition
├── effects_engine/         # Effects and motion graphics
├── design_quality/         # Design checks and auto-fix implementation
├── ffmpeg_helpers.py       # Canonical FFmpeg execution/path helpers
├── defaults.py             # Runtime defaults
├── validation.py           # Shared parameter validation
└── limits.py               # Resource and subprocess limits
mcp_video.py                # Compatibility import module
compat/mcp-video-shim/      # Compatibility distribution metadata
tests/
├── test_public_surface.py       # Exact CLI/MCP/discovery compatibility contract
├── test_server*.py              # MCP registration and wire behavior
├── test_cli*.py                 # CLI parsing and command behavior
├── test_workflow_*.py           # Workflow engine and receipt contracts
├── test_rescue_*.py             # Rescue pipeline contracts
└── test_real_*.py               # Real-media coverage (usually marked slow)
```

## Making Changes

### Adding a new tool

1. **Engine first** — Add behavior to the focused `engine_*.py` module or existing subpackage that owns the operation. Reuse `_validate_input_path()`, `_validate_output_path()`, `_run_ffmpeg()`, and audio/video-aware probes from `ffmpeg_helpers.py`.
2. **Model if needed** — Add any new Pydantic models to `models.py`
3. **Error if needed** — Add error types to `errors.py` if the failure mode is distinct
4. **Server** — Add the thin `@mcp.tool()` wrapper to the matching `server_tools_*.py` module with parameter validation; keep business logic out of the registration layer
5. **Tests** — Add tests in the appropriate file:
   - `test_engine_advanced.py` for new operations
   - `test_server.py` for the MCP tool wrapper
   - `test_e2e.py` if it's a workflow-type operation
   - `test_adversarial_audit.py` for any new validation/injection tests
6. **Update contracts** — Update `EXPECTED_CLI_COMMANDS`, the exact MCP count, README, `llms.txt`, `docs/AI_AGENT_DISCOVERY.md`, and tool/reference docs when the public surface changes

### Fixing a bug

1. Write a failing test that reproduces the bug
2. Fix the code
3. Verify the test passes and nothing else breaks
4. If it changes behavior, update README if needed

## Code Conventions

- **Error types matter** — Use `input_error` for validation failures, `processing_error` for FFmpeg failures, `dependency_error` for missing tools. Don't default to `unknown_error`.
- **Validate at the boundary** — Parameter validation belongs in the matching `server_tools_*.py` registration module before the engine call, with engine-level validation retained for non-MCP callers. Use `_validation_error()` or the established structured error helper.
- **Probe after processing** — Every operation that produces a video file should call `probe(output)` and return duration/resolution in the `EditResult`.
- **Escape FFmpeg special chars** — Use `_escape_ffmpeg_filter_value()` from `ffmpeg_helpers.py` for paths/values going into FFmpeg filter strings.
- **Validate paths** — Use `_validate_input_path()` and `_validate_output_path()` from `ffmpeg_helpers.py` to reject null bytes, confine paths, and verify inputs. Treat `validation.py` as the shared source of allowed-value constants, not a hidden catch-all helper layer.
- **Sanitize output paths** — `_auto_output` replaces colons with underscores to prevent FFmpeg filter breakage.
- **No shell=True** — All subprocess calls use list args, never shell strings.
- **Keep ownership clear** — Prefer focused engine functions and existing subpackages. Add an abstraction only when it removes real complexity or matches an established local pattern.

## Testing Rules

- Unit tests (models, errors, templates) must not need FFmpeg installed
- Integration tests need FFmpeg and produce real video files
- Every new tool needs at least: success case, error case (bad input), and one edge case
- Add adversarial tests in `test_adversarial_audit.py` for any new validation
- E2E tests chain multiple operations together
- Run the full suite before pushing: `pytest tests/ -v -m "not slow" --tb=short`
- Keep the default non-slow suite green, and run slower or environment-sensitive coverage when your change touches those surfaces

### Automated tests vs manual scripts

- Files under pytest discovery must be **hermetic automated tests** only.
- Manual experiments, local-media scripts, and research sweeps must **not** live in `test_*.py` names that pytest will auto-collect.
- If a script depends on author-local files, machine-specific paths, or exploratory output review, place it under a non-pytest path such as `manual/` or `research/`.
- Before adding a new test file, verify its name and location are appropriate for CI collection.

### Repository artifact policy

- Do **not** commit generated logs, browser captures, temporary research extracts, or render outputs unless they are explicitly curated release assets.
- Generated media belongs outside source control by default.
- Research/reference material derived from third-party sites must be provenance-reviewed before it is tracked or published.
- If an artifact should never reach the public site or release archives, it should not remain in the tracked product surface.

## Commit Messages

Keep them short and descriptive:
```
Add crop operation for rectangular region extraction
Fix colon escaping in drawtext filter strings
Bump version to 1.2.0
```

## Git Hygiene & Branch Management

To keep branch history clean and reviewable, follow the governance guide in `docs/git-branch-governance.md`.

Before opening a PR, run:

```bash
./scripts/git-professional-audit.sh
```

Address all `FAIL` results, and resolve `WARN` results when practical.

For broader repository health (docs + templates + metadata), run:

```bash
./scripts/repo-readiness-audit.py
```

For workspace cleanup (stale worktrees/branches), run:

```bash
./scripts/git-workspace-cleanup.sh
```

To monitor CI and review comments on pull requests, run:

```bash
./scripts/github-pr-monitor.py --owner KyaniteLabs --repo kinocut
# optional: target a specific PR
./scripts/github-pr-monitor.py --owner KyaniteLabs --repo kinocut --pr 17
```

## Pull Request Process

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Run `pytest tests/ -v -m "not slow"` — all must pass
5. Open a PR with a clear description of what changed and why

## Reporting Issues

When reporting a bug, include:
- The exact tool call or command you ran
- The input file (codec, resolution, duration)
- The full error output
- Your OS and FFmpeg version (`ffmpeg -version`)

## Questions?

Open a [GitHub Q&A discussion](https://github.com/KyaniteLabs/kinocut/discussions/new?category=q-a).

<!-- EMPOWER_ORCHESTRATOR:START -->
## Agent-law contribution rule

This repository follows the Empower Orchestrator law in `docs/agent-law/empower-orchestrator.md`.

If a change exposes a repeated task or repeated agent failure, contributors and agents should either ship the smallest durable prevention artifact or explain why this PR is intentionally one-off.

Automation and durable system changes require the scale/severity/reversibility/predictability blast-radius check before dispatch.
<!-- EMPOWER_ORCHESTRATOR:END -->
