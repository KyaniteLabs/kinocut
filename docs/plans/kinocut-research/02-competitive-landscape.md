# Competitive landscape (Claude agent) — key findings

SNAPSHOT BASELINE (2026-07-09): the project, then named `mcp-video`, had 71 stars/19 forks and 119 tools. The stale kinocut.dev "81 tools, FFmpeg + Remotion" copy observed during research was corrected in the Phase 0 site cutover. Re-check live counts before external use.

DIRECT FFMPEG MCPS (snapshot): Kinocut exceeded the feature depth of video-creator/ffmpeg-mcp, egoist, and misbahsy. Roughly 40 video MCPs existed, including 7+ FFmpeg wrappers; none in the snapshot combined Kinocut's preflight and quality checkpoints.
NAME COLLISION: studiomeyer-io/mcp-video (npx mcp-video!) 4★ active — has browser recording (Playwright), LUT color grading, beat-sync compose, built-in TTS.

STANDOUT COMPETITORS:
- FireRed-OpenStoryline (Xiaohongshu) 3,069★ = highest-starred AI video editing agent: brief→finished-video autonomy, asset search/download, script gen w/ style transfer, BGM beat-sync, EDITING SKILL ARCHIVING (save workflow as reusable Skill), AI transitions, ships Claude Code skills.
- FableCut 238★ very active: whole timeline = one project.json over MCP+REST, UI hot-reloads 150ms, human-agent CO-EDITING live. The HITL answer.
- watch-skill (oxbshw) 134 stars at snapshot: "agent watches its own work and fixes it" - frame+OCR+transcript index, THE LOOP (render→critique→fix→re-verify→before/after proof). Closest to Kinocut's QC thesis, vision-based vs VMAF.
- claude-video-vision 958★: Claude plugin for watching videos.
- davinci-resolve-mcp 1,507★ (DOUBLED in 3mo — NLE-MCP cluster fastest-growing); Premiere MCP 354★ (278 tools); fcpxml-mcp 65★ (QC on timelines).
- Jumper (commercial): local visual/face/transcript search → selects → timeline export to 4 NLEs; agent gets only metadata.
- Eddie AI: multicam sync 6 cams, A/B-roll classification, narrative rough cuts, NLE export.
- auto-editor 4,523★: motion-based dead-space detection, exports Premiere XML/FCPXML/Resolve.
- burningion/video-editing-mcp 279★: OTIO export into DaVinci Resolve, semantic video search (cloud).
- Descript: API early access, NO MCP server (surprising gap); generative jump-cut smoothing, Overdub.
- OpusClip: official opus-skills for Claude Code — vendor moving into coding-agent surface.
- Shotstack: JSON timeline → cloud render; "rendering is the hardest layer... infrastructure problems not prompting problems".
- Hyperframes itself had 34,023 stars at snapshot (HeyGen) - a tailwind for Kinocut.
- Velorn 283★: ComfyUI-orbit desktop AI video workstation.

FEATURES NOBODY NAILED (snapshot discourse): 1) end-to-end brief→final-cut on real footage; 2) narrative coherence at length; 3) taste/context judgment; 4) non-linear iterative creative loop + partial-failure handling; 5) self-verification combining metric QC + vision QC + narrative QC; 6) rendering-as-infrastructure; 7) official vendor MCPs in video editing; 8) a HITL review surface non-technical humans can watch (Kinocut still lacks it); 9) C2PA provenance signing in a video MCP. Re-verify competitor and regulatory claims before publication.
