# Contributing to mcp-video

Thanks for your interest in improving mcp-video. This is a focused project — every tool should work reliably, and every change should maintain that standard.

## Quick Start

```bash
# Clone and install dev dependencies
git clone https://git.kyanitelabs.tech/KyaniteLabs/kinocut.git
cd mcp-video
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
mcp_video/
├── __init__.py            # Exports Client + public API
├── __main__.py            # CLI entry point (argparse + Rich)
├── client.py              # Python Client API (wraps all engines)
├── server.py              # MCP server (119 tools + 4 resources)
├── engine.py              # Core FFmpeg engine (40 video operations)
├── models.py              # Pydantic models (VideoInfo, EditResult, Timeline DSL)
├── errors.py              # Error hierarchy + FFmpeg stderr parser
├── validation.py          # Shared validation constants / allowed values / normalized-parameter helpers
├── ffmpeg_helpers.py      # Shared FFmpeg utilities (escape, validate, run) (v1.2.0)
├── templates.py           # Social media templates (TikTok, YouTube, Instagram)
├── audio_engine.py        # Procedural audio synthesis (pure NumPy)
├── effects_engine.py      # Visual effects + motion graphics (FFmpeg filters)
├── transitions_engine.py  # Clip transitions (glitch, pixelate, morph)
├── ai_engine.py           # AI features (Whisper, Demucs, Real-ESRGAN, spatial audio)
├── hyperframes_engine.py  # Hyperframes CLI wrapper (render, preview, validate, init)
├── hyperframes_models.py  # Hyperframes data models
├── image_engine.py        # Image color analysis (K-means, palette generation)
├── image_models.py        # Image data models
├── quality_guardrails.py  # Automated quality checks (brightness, contrast, audio)
├── filter_guardrails.py   # Preflight bounds for video/audio filter parameters
├── merge_guardrails.py    # Pre-merge compatibility checks
├── audio_guardrails.py    # Audio mix validation helpers
├── design_quality.py      # Design quality + auto-fix (layout, typography, motion)
└── limits.py              # Resource validation constants (max 4h, 8K, 4GB)
tests/
├── conftest.py                  # Shared fixtures (sample video, audio, etc.)
├── test_models.py               # Model validation (no FFmpeg)
├── test_errors.py               # Error parsing (no FFmpeg)
├── test_templates.py            # Template functions (no FFmpeg)
├── test_client.py               # Client API wrapper
├── test_server.py               # MCP tool layer
├── test_engine.py               # Core FFmpeg operations
├── test_engine_advanced.py      # Edge cases, crop, rotate, fade, filters, validation
├── test_cli.py                  # CLI commands
├── test_e2e.py                  # Multi-step workflows
├── test_ai_features.py          # AI tools (mocked where needed)
├── test_audio_presets.py        # Audio preset validation
├── test_transitions.py          # Transition effects
├── test_quality_guardrails.py   # Quality scoring
├── test_image_engine.py         # Color extraction, palettes
├── test_adversarial_audit.py    # Security audit (injection, validation, bounds)
├── test_red_team.py             # Red team tests
├── test_hyperframes_engine.py   # Hyperframes CLI wrapper (mocked)
├── test_real_media.py           # Real-media integration tests (marked @slow)
├── test_real_all_features.py    # Real-media all-features sweep (marked @slow)
└── test_real_exhaustive.py      # Exhaustive real-media tests (marked @slow)
```

## Making Changes

### Adding a new tool

1. **Engine first** — Add the FFmpeg function in `engine.py`. Follow the existing pattern:
   - `_validate_input(input_path)` at the top
   - `_run_ffmpeg([...])` for the FFmpeg call
   - `probe(output)` after processing
   - Return an `EditResult` with `duration`, `resolution`, `size_mb`
2. **Model if needed** — Add any new Pydantic models to `models.py`
3. **Error if needed** — Add error types to `errors.py` if the failure mode is distinct
4. **Server** — Add the `@mcp.tool()` wrapper in `server.py` with parameter validation
5. **Tests** — Add tests in the appropriate file:
   - `test_engine_advanced.py` for new operations
   - `test_server.py` for the MCP tool wrapper
   - `test_e2e.py` if it's a workflow-type operation
   - `test_adversarial_audit.py` for any new validation/injection tests
6. **Update counts** — README test counts and tool count

### Fixing a bug

1. Write a failing test that reproduces the bug
2. Fix the code
3. Verify the test passes and nothing else breaks
4. If it changes behavior, update README if needed

## Code Conventions

- **Error types matter** — Use `input_error` for validation failures, `processing_error` for FFmpeg failures, `dependency_error` for missing tools. Don't default to `unknown_error`.
- **Validate in the server** — Parameter validation belongs in `server.py` (before calling the engine), not just in the engine. Use `_error_result(MCPVideoError(...))` for validation failures.
- **Probe after processing** — Every operation that produces a video file should call `probe(output)` and return duration/resolution in the `EditResult`.
- **Escape FFmpeg special chars** — Use `_escape_ffmpeg_filter_value()` from `ffmpeg_helpers.py` for paths/values going into FFmpeg filter strings.
- **Validate paths** — Use `_validate_input()` (engine) or `_validate_input_path()` (effects/transitions) to reject null bytes and verify file existence. Treat `validation.py` as the shared source of allowed-value constants, not a hidden catch-all helper layer.
- **Sanitize output paths** — `_auto_output` replaces colons with underscores to prevent FFmpeg filter breakage.
- **No shell=True** — All subprocess calls use list args, never shell strings.
- **Keep it simple** — One function per operation. No classes for engines. No abstractions for one-time use.

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

To monitor the GitHub mirror CI and review comments on mirrored PRs, run:

```bash
./scripts/github-pr-monitor.py --owner KyaniteLabs --repo mcp-video
# optional: target a specific PR
./scripts/github-pr-monitor.py --owner KyaniteLabs --repo mcp-video --pr 17
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

Open a Forgejo issue with the `question` label.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Agent-law contribution rule

This repository follows the Empower Orchestrator law in `docs/agent-law/empower-orchestrator.md`.

If a change exposes a repeated task or repeated agent failure, contributors and agents should either ship the smallest durable prevention artifact or explain why this PR is intentionally one-off.

Automation and durable system changes require the scale/severity/reversibility/predictability blast-radius check before dispatch.
<!-- EMPOWER_ORCHESTRATOR:END -->
