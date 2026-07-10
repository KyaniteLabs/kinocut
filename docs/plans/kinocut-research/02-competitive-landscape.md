# Competitive landscape (Claude agent) — key findings

BASELINE: mcp-video 71★/19 forks. NOTE: kinocut.dev site STALE ("81 tools, FFmpeg + Remotion" vs 119-tool/Hyperframes reality).

DIRECT FFMPEG MCPs: all superseded by mcp-video (video-creator/ffmpeg-mcp 137★ dormant-ish, egoist 120★ dormant, misbahsy 82★). ~40 video MCPs exist, 7+ FFmpeg ones; NONE has preflight/quality checkpoints — guardrail positioning unique in cluster.
NAME COLLISION: studiomeyer-io/mcp-video (npx mcp-video!) 4★ active — has browser recording (Playwright), LUT color grading, beat-sync compose, built-in TTS.

STANDOUT COMPETITORS:
- FireRed-OpenStoryline (Xiaohongshu) 3,069★ = highest-starred AI video editing agent: brief→finished-video autonomy, asset search/download, script gen w/ style transfer, BGM beat-sync, EDITING SKILL ARCHIVING (save workflow as reusable Skill), AI transitions, ships Claude Code skills.
- FableCut 238★ very active: whole timeline = one project.json over MCP+REST, UI hot-reloads 150ms, human-agent CO-EDITING live. The HITL answer.
- watch-skill (oxbshw) 134★: "agent watches its own work and fixes it" — frame+OCR+transcript index, THE LOOP (render→critique→fix→re-verify→before/after proof). Closest to mcp-video's QC thesis, vision-based vs VMAF.
- claude-video-vision 958★: Claude plugin for watching videos.
- davinci-resolve-mcp 1,507★ (DOUBLED in 3mo — NLE-MCP cluster fastest-growing); Premiere MCP 354★ (278 tools); fcpxml-mcp 65★ (QC on timelines).
- Jumper (commercial): local visual/face/transcript search → selects → timeline export to 4 NLEs; agent gets only metadata.
- Eddie AI: multicam sync 6 cams, A/B-roll classification, narrative rough cuts, NLE export.
- auto-editor 4,523★: motion-based dead-space detection, exports Premiere XML/FCPXML/Resolve.
- burningion/video-editing-mcp 279★: OTIO export into DaVinci Resolve, semantic video search (cloud).
- Descript: API early access, NO MCP server (surprising gap); generative jump-cut smoothing, Overdub.
- OpusClip: official opus-skills for Claude Code — vendor moving into coding-agent surface.
- Shotstack: JSON timeline → cloud render; "rendering is the hardest layer... infrastructure problems not prompting problems".
- Hyperframes itself 34,023★ (HeyGen) — tailwind for mcp-video.
- Velorn 283★: ComfyUI-orbit desktop AI video workstation.

FEATURES NOBODY NAILED (discourse): 1) end-to-end brief→final-cut on real footage (a16z: "what Cursor did for coding" — products don't exist; "spell-checkers for video, not ghostwriters"); 2) narrative coherence at length (20 decisions/min compounds); 3) taste/context judgment; 4) non-linear iterative creative loop + partial-failure handling; 5) self-verification: NO ONE combines metric QC (VMAF) + vision QC + narrative QC; 6) rendering-as-infrastructure; 7) ZERO official vendor MCPs in video editing (Descript/Runway/Kling/Avid all absent); 8) HITL review surface non-technical humans can watch (FableCut + Descript = only working answers; MCP-only servers incl mcp-video lack it); 9) C2PA provenance — EU AI Act Art.50 synthetic-content labeling ENFORCEABLE AUG 2026, no video MCP ships C2PA signing today.
