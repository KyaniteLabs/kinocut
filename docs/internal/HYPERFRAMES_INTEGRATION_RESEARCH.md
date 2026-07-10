# Hyperframes Integration Research

> **Historical note.** This research led to the Hyperframes integration that shipped in v1.2.5. Remotion was later removed in v1.3.0/v1.3.1 due to licensing concerns.
>
> **Issue:** [#153](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/153)
> **Date:** 2026-04-27
> **Author:** Kimi Code CLI  

---

## 1. Executive Summary

[Hyperframes](https://github.com/heygen-com/hyperframes) is an open-source, HTML-native video rendering framework from HeyGen. It targets the same "video-as-code" niche as Remotion (already integrated in mcp-video) and Revideo, but with a fundamentally different approach: **pure HTML compositions instead of React/TypeScript components**.

This document provides a full technical comparison and proposes how Hyperframes could integrate into mcp-video's existing MCP tool surface.

---

## 2. What Is Hyperframes?

### Core Philosophy
> "Write HTML. Render video. Built for agents."

Hyperframes treats every HTML element as a "clip" on a timeline. Compositions are standard HTML files annotated with `data-*` attributes. There is **no React requirement**, no proprietary DSL, and no custom component system.

### Minimal Example

```html
<div id="root" data-composition-id="demo"
     data-start="0" data-width="1920" data-height="1080">

  <video id="clip-1" data-start="0" data-duration="5"
         data-track-index="0" src="intro.mp4" muted playsinline></video>

  <h1 id="title" class="clip"
      data-start="1" data-duration="4" data-track-index="1"
      style="font-size: 72px; color: white;">
    Welcome to Hyperframes
  </h1>

  <audio id="bg-music" data-start="0" data-duration="5"
         data-track-index="2" data-volume="0.5" src="music.wav"></audio>
</div>
```

```bash
npx hyperframes render --output demo.mp4
```

### Rendering Pipeline

1. **Compose** — Write HTML with data attributes. Animations via GSAP, Lottie, CSS, or any seekable runtime.
2. **Preview** — `npx hyperframes preview` launches a browser studio with HMR.
3. **Render** — Headless Chrome seeks to each frame (`frame = floor(time * fps)`), captures via `beginFrame`, encodes with FFmpeg.

### Key Packages

| Package | Purpose |
|---------|---------|
| `hyperframes` | CLI — init, lint, preview, render, transcribe, TTS, doctor |
| `@hyperframes/core` | Types, parsers, generators, linter, runtime, frame adapters |
| `@hyperframes/engine` | Seekable page-to-video capture (Puppeteer + FFmpeg) |
| `@hyperframes/producer` | Full rendering pipeline (capture + encode + audio mix) |
| `@hyperframes/studio` | Browser-based composition editor UI |
| `@hyperframes/player` | Embeddable `<hyperframes-player>` web component |
| `@hyperframes/shader-transitions` | WebGL shader transitions |

### Catalog

50+ ready-to-use blocks (social overlays, shader transitions, data viz, cinematic effects):

```bash
npx hyperframes add flash-through-white
npx hyperframes add instagram-follow
npx hyperframes add data-chart
```

---

## 3. Architecture Comparison

### Hyperframes vs Remotion vs Revideo

| Dimension | **Hyperframes** | **Remotion** | **Revideo** |
|-----------|----------------|--------------|-------------|
| **Language** | HTML + CSS + JS | React + TypeScript | TypeScript (Canvas API) |
| **DSL** | None (plain HTML) | React components + hooks | Custom scene graph |
| **React required** | No | Yes | No (but player is React) |
| **Agent affinity** | Very high (LLMs write HTML natively) | Medium (LLMs know React but JSX has quirks) | Medium |
| **Determinism** | Frame-exact via `beginFrame` | Frame-exact via `seek()` | Frame-exact |
| **Animation runtimes** | GSAP, Lottie, CSS, Three.js (Frame Adapter) | GSAP, CSS, custom Remotion hooks | Custom generators/yield |
| **Preview** | Browser studio with HMR | Remotion Studio | React Player component |
| **CLI design** | Non-interactive, fail-fast, plain text | Interactive by default | API-first + CLI |
| **Node version** | >= 22 | >= 18 | >= 18 |
| **Maturity** | New (launched ~April 2026) | Mature (4+ years) | Early (forked 2024) |
| **Catalog/templates** | 50+ blocks via `npx hyperframes add` | Templates + community packages | Examples repo |
| **Hosted rendering** | Self-hosted / Docker | Remotion Lambda (paid) | Self-hosted / Cloud Run |
| **License** | Apache 2.0 | MIT + company backing | AGPL / commercial |

### Strengths of Each

**Hyperframes**
- Zero learning curve for web developers (no React/TSX)
- Best agent experience — HTML is the format LLMs generate most confidently
- No framework lock-in; any CSS/JS animation library works
- Deterministic by design with no wall-clock dependencies
- First-class skills/plugins for Claude Code, Cursor, Codex

**Remotion**
- Mature ecosystem with 4+ years of production use
- Rich React integration (useCurrentFrame, spring, interpolate, etc.)
- Remotion Lambda for scalable cloud rendering
- Large community, extensive docs, proven at scale
- Already integrated into mcp-video with 8 MCP tools

**Revideo**
- Purpose-built for programmatic editing (API endpoint pattern)
- Forked from Motion Canvas — good for animation-heavy content
- Headless rendering out of the box
- React player component for embedding previews

### Weaknesses of Each

**Hyperframes**
- Very new; limited production battle-testing
- Smaller community than Remotion
- No managed cloud rendering option (self-host only)
- Frame Adapter pattern requires runtime authors to implement seeking

**Remotion**
- React-only limits audience (non-React devs need to learn TSX)
- JSX can be error-prone for LLM agents (braces, fragments, hooks)
- Lambda rendering is paid; self-hosted requires infrastructure

**Revideo**
- Smallest ecosystem of the three
- AGPL license may be restrictive for some users
- Canvas-based rendering limits DOM/CSS capabilities

---

## 4. Fit Analysis for mcp-video

### Does Hyperframes Fit mcp-video's Architecture?

**Yes — strongly.**

mcp-video already integrates Remotion as an external Node.js rendering engine. Hyperframes follows the exact same pattern:

1. **External dependency** — Requires Node.js + npx (same as Remotion)
2. **CLI-driven** — Non-interactive CLI perfect for agent workflows
3. **Subprocess execution** — mcp-video's `remotion_engine.py` pattern maps directly
4. **Deterministic output** — Frame-exact rendering aligns with mcp-video's quality standards

### Unique Value Add

Hyperframes would differentiate mcp-video in ways Remotion cannot:

| Capability | Remotion | Hyperframes |
|------------|----------|-------------|
| Agent generates composition without React knowledge | ❌ | ✅ |
| Plain HTML output (easy to preview in any browser) | ❌ | ✅ |
| Works with existing web design systems | ❌ | ✅ |
| No build step for simple compositions | ❌ | ✅ |
| Skills/plugins for Claude/Cursor/Codex | ❌ | ✅ |

### Checklist from Issue #153

- [x] **Can be implemented with local processing** — Yes. Hyperframes renders locally via Node.js + FFmpeg.
- [x] **Helps AI agents complete video workflows with less guessing** — Yes. HTML is the format LLMs are best at. The CLI is explicitly designed for agent-driven workflows.
- [ ] **Existing equivalent in README/roadmap** — No existing Hyperframes integration.

---

## 5. Proposed Integration Surface

Following the exact pattern established by `remotion_engine.py` and `server_tools_remotion.py`, we propose these MCP tools:

### Core Tools

```python
hyperframes_render(project_path, output_path, fps, width, height, ...)
hyperframes_preview(project_path, port)
hyperframes_validate(project_path)
hyperframes_init(name, output_dir, template)
hyperframes_compositions(project_path)
hyperframes_still(project_path, output_path, frame)
```

### Catalog & Scaffolding Tools

```python
hyperframes_add_block(project_path, block_name)
hyperframes_list_blocks()
hyperframes_scaffold_template(project_path, spec, slug)
```

### Pipeline Tool (mirroring `remotion_to_mcpvideo`)

```python
hyperframes_to_mcpvideo(project_path, post_process, output_path)
```

### Proposed API Signatures

#### `hyperframes_render`
```python
def hyperframes_render(
    project_path: str,
    output_path: str | None = None,
    fps: float = 30.0,
    width: int = 1920,
    height: int = 1080,
    composition_id: str | None = None,
    crf: int | None = None,
) -> dict[str, Any]:
    """Render a Hyperframes composition to MP4.
    
    Args:
        project_path: Absolute path to the Hyperframes project directory.
        output_path: Where to save the video. Auto-generated if omitted.
        fps: Frames per second. Default 30.
        width: Output width in pixels. Default 1920.
        height: Output height in pixels. Default 1080.
        composition_id: Optional composition ID (for multi-composition projects).
        crf: CRF quality value (lower = better quality).
    """
```

#### `hyperframes_preview`
```python
def hyperframes_preview(
    project_path: str,
    port: int = 3000,
) -> dict[str, Any]:
    """Launch Hyperframes Studio for live preview."""
```

#### `hyperframes_init`
```python
def hyperframes_init(
    name: str,
    output_dir: str | None = None,
    template: str = "blank",
) -> dict[str, Any]:
    """Scaffold a new Hyperframes project.
    
    Templates: blank, swiss-grid, nyt-graph, play-mode, vignelli
    """
```

#### `hyperframes_add_block`
```python
def hyperframes_add_block(
    project_path: str,
    block_name: str,
) -> dict[str, Any]:
    """Install a block from the Hyperframes catalog.
    
    Examples: flash-through-white, instagram-follow, data-chart
    """
```

---

## 6. Implementation Plan

### Phase 1: Engine Module (1-2 days)

Create `mcp_video/hyperframes_engine.py` mirroring `remotion_engine.py`:

- `_require_hyperframes_deps()` — check Node.js >= 22, npx, hyperframes CLI
- `_validate_project()` — check for `index.html` or `composition.html`
- `_run_hyperframes()` — subprocess wrapper for `npx hyperframes ...`
- `render()` — call `hyperframes render`
- `preview()` — call `hyperframes preview` (non-blocking)
- `validate()` — call `hyperframes lint` + structural checks
- `init()` — call `hyperframes init` or scaffold manually
- `compositions()` — parse HTML for `data-composition-id` attributes
- `still()` — render single frame

### Phase 2: MCP Tool Registration (1 day)

Create `mcp_video/server_tools_hyperframes.py` mirroring `server_tools_remotion.py`:

- Register 6-8 tools via `@mcp.tool()`
- Validation using existing `mcp_video/validation.py` constants
- Error handling via `mcp_video/errors.py` custom types
- Lazy imports inside handlers for fast startup

### Phase 3: Models (2 hours)

Create `mcp_video/hyperframes_models.py` mirroring `remotion_models.py`:

- `HyperframesRenderResult`
- `HyperframesPreviewResult`
- `HyperframesValidationResult`
- `HyperframesProjectResult`
- `HyperframesBlockResult`
- `HyperframesPipelineResult`

### Phase 4: CLI Handlers (2 hours)

Create `mcp_video/cli/handlers_hyperframes.py` and `mcp_video/cli/parser/hyperframes.py`:

- Add subcommands to the existing CLI hierarchy
- Reuse existing argument validation

### Phase 5: Client Support (2 hours)

Add to `mcp_video/client/`:

- `mcp_video/client/hyperframes.py` — typed client methods
- Update `mcp_video/client/contracts.py` with Hyperframes contracts

### Phase 6: Tests (1 day)

- Unit tests for engine functions
- Integration tests (skip if Hyperframes not installed, same pattern as Remotion)
- Mock subprocess tests for CLI parsing

### Total Estimated Effort

**3-4 days** for a complete, production-ready integration following mcp-video's existing patterns.

---

## 7. File Changes Required

```
New files:
  mcp_video/hyperframes_engine.py
  mcp_video/server_tools_hyperframes.py
  mcp_video/hyperframes_models.py
  mcp_video/cli/handlers_hyperframes.py
  mcp_video/cli/parser/hyperframes.py
  mcp_video/client/hyperframes.py
  tests/test_hyperframes_engine.py
  tests/test_hyperframes_tools.py

Modified files:
  mcp_video/server.py          # register new tools
  mcp_video/__init__.py        # expose new models
  mcp_video/__main__.py        # add CLI subcommands
  mcp_video/client/__init__.py # expose client methods
  mcp_video/validation.py      # add Hyperframes templates/blocks
  mcp_video/errors.py          # add Hyperframes-specific errors
```

---

## 8. Risks & Considerations

| Risk | Mitigation |
|------|------------|
| Hyperframes is very new (launched April 2026) | Treat as experimental; mark tools as beta in docs |
| Node.js >= 22 requirement | Document clearly; add doctor check |
| Smaller community than Remotion | Monitor upstream for breaking changes; pin versions |
| No managed cloud rendering | Acceptable — mcp-video targets local processing |
| Potential overlap with Remotion integration | Position Hyperframes as "HTML-native alternative" in docs |
| Maintenance burden of two Node.js engines | Code reuse via shared subprocess helpers in `ffmpeg_helpers.py` |

---

## 9. Recommendation

**Proceed with integration.**

Hyperframes fills a genuine gap in mcp-video's offering:

1. **Lower barrier to entry** — Users who don't know React can still generate videos from HTML.
2. **Better agent experience** — LLMs write HTML more confidently than JSX/TypeScript.
3. **Competitive differentiation** — mcp-video would be the first MCP server to offer Hyperframes integration.
4. **Low implementation risk** — The architecture mirrors Remotion exactly; most patterns are copy-paste-adapt.

### Suggested Next Steps

1. **Create a feature branch** `feat/hyperframes-integration`
2. **Implement Phase 1** (engine module) as an MVP
3. **Add 3 core MCP tools**: `hyperframes_render`, `hyperframes_init`, `hyperframes_preview`
4. **Write integration tests** following the Remotion test pattern
5. **Open a PR** and link to this research document
6. **Iterate** based on review feedback

---

## 10. References

- [Hyperframes GitHub](https://github.com/heygen-com/hyperframes)
- [Hyperframes Documentation](https://hyperframes.heygen.com/introduction)
- [Remotion GitHub](https://github.com/remotion-dev/remotion)
- [Revideo GitHub](https://github.com/redotvideo/revideo)
- [HeyGen Blog: Video as Code](https://blog.nidhin.dev/video-as-code-a-deep-dive-into-heygen-s-hyperframes)
- mcp-video Remotion integration: `mcp_video/remotion_engine.py`, `mcp_video/server_tools_remotion.py`
