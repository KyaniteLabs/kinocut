# Kinocut Integration Roadmap

**Created:** 2026-03-27
**Context:** Integration wishlist from Cerafica feedback — to be addressed after v0.6.0 improvements ship.

---

## 1. Blender MCP Integration — DEFERRED, NOT APPROVED

### Status: Ready to use (existing project)

**Project:** [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)
- Socket-based bridge: Claude AI <-> Blender
- Supports Blender 3.0+ (including 4.x)
- Create, modify, delete 3D objects via natural language
- Scene creation, lighting, camera control, rendering
- Sketchfab integration for asset import
- Free addon, active development

### Setup Steps
1. Install Blender (latest stable)
2. Install the Blender MCP addon from GitHub releases
3. Configure socket connection in Claude Code MCP settings
4. Test with a simple object creation prompt

### Cerafica Pipeline
```
Blender MCP (3D vessel modeling + rotation animation)
  → Render to MP4 (Blender's render engine)
    → Kinocut (add text overlays, logo, export for Instagram/Web)
```

### Use Cases for Cerafica
- Photorealistic 3D vessel rotation instead of filmed footage
- Consistent lighting and backgrounds across all products
- Batch render 11 products with same camera angle/lighting
- Combine with Kinocut for branded output

### Skills Needed
- Create a Cerafica workflow skill that chains: Blender MCP → Kinocut
- No custom MCP development required

### Effort: 1-2 days (setup + workflow skill)

---

## 2. Image Analysis MCP — COMPLETED

### Status: Shipped in v0.7.0

Three image analysis tools built directly into Kinocut using scikit-learn K-means (already a dependency) and optional Claude Vision API for AI descriptions.

**Tools shipped:**
1. `image_extract_colors(image_path, n_colors=5)` — dominant colors with hex codes + percentages
2. `image_analyze_product(image_path, use_ai=False)` — color extraction + optional AI product description
3. `image_generate_palette(image_path, harmony="complementary")` — color harmony palette generation

**Architecture:**
```
Built into the Kinocut server (no separate MCP server needed)
  ├── Color extraction (scikit-learn K-means) — FREE, LOCAL
  └── AI descriptions (Claude Vision API) — OPTIONAL, $0.15/image
```

**Pipeline Integration:**
```
Kinocut (`video_export_frames`)
  → Image Analysis tools (extract colors, descriptions)
    → Kinocut (use metadata in text overlays)
```

---

## 3. Hyperframes Integration — COMPLETED

### Status: Shipped in v1.2.5

Full Hyperframes integration with 8 MCP tools, Python client methods, and CLI commands.

**Tools shipped:**
1. `hyperframes_init` — scaffold new projects
2. `hyperframes_render` — render compositions to video
3. `hyperframes_still` — render single frames
4. `hyperframes_compositions` — list compositions
5. `hyperframes_preview` — launch preview studio
6. `hyperframes_validate` — validate project structure
7. `hyperframes_add_block` — install blocks from catalog
8. `hyperframes_to_mcpvideo` — render + post-process pipeline

**Architecture:** HTML-native video creation via `npx hyperframes` CLI. No pip dependencies — requires Node.js 22+ and npx.

---

## 4. Remotion Integration — REMOVED

### Status: Completely removed in v1.3.1 (PR #163).

Remotion's custom freemium license (company-size gate, no derivative resale) created liability for wrappers like Kinocut. All Remotion MCP tools, CLI commands, client methods, engine modules, and tests have been deleted. Hyperframes (HTML-native, Apache 2.0) is now the sole code-based video creation engine.

**Migration path:** Use `hyperframes_init`, `hyperframes_render`, `hyperframes_preview`, and `hyperframes_to_mcpvideo` instead of the removed Remotion equivalents.

---

## Summary

| Integration | Priority | Effort | Status | Approved | ROI |
|-------------|----------|--------|--------|---------|-----|
| Blender MCP | LOW | 1-2 days | Defer | No | Medium |
| Image Analysis | MEDIUM | 2-3 days | **Completed (v0.7.0)** | Yes | Medium |
| Hyperframes | HIGH | Shipped | **Completed (v1.2.5)** | Yes | High |
| Remotion | MEDIUM | 5-10 days | **Removed (v1.3.1)** | N/A | N/A |
