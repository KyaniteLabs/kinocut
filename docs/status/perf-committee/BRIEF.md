# Performance committee — inspect only

**Purpose:** Find real Kinocut bottlenecks and the cheapest safe optimizations.  
**Why:** User asked a multi-model committee on performance only.  
**Mode:** Inspect-only. Do **not** edit `kinocut/`, `tests/`, README, or claims.  
**Write exactly one file:** the report path named in your dispatch task.  
**Stop-and-ask:** If you think a code change is required, describe it in the report. Do not implement.

## Scope

- 360 assembly: `kinocut/te/sphere_*.py`, `tests/test_sphere_assembly.py`
- Hot FFmpeg path: `kinocut/ffmpeg_helpers.py`, `kinocut/te/sphere_render.py`, `kinocut/te/sphere_storyboard.py`, `kinocut/te/sphere_filters.py`
- Import/startup: PEP 562 `kinocut/__init__.py`, doctor
- Evidence already on disk: `docs/status/golden-path-timings.md`, `scripts/golden_path_timings.py`

## Do not

- Add stitchers, cubemap decode, face tracking, vendor SDKs
- Propose rewriting FFmpeg in Python
- Touch `docs/public_claims.json`
- Claim “optimized” as a product fact
- Run long encodes; cheap probes only (`pytest tests/test_sphere_assembly.py`, `kino doctor --json`)

## Required report shape (markdown)

1. Bottom line (5 bullets max)
2. Measured or code-traced bottlenecks (file:line + why)
3. Ranked fixes: effort (S/M/L) × impact × risk
4. What you would **not** do (waste)
5. Evidence: commands you ran and key output

## Constraints

- Forgejo is source of truth; this is a local inspect.
- Custom errors / escape / 800-80 LOC still apply to any *proposal*.
- No secrets or home paths in the report.
