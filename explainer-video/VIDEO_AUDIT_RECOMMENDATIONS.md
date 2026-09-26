Address everything critical, high, medium, low, all of the priorities.# mcp-video Explainer Video - Red Team Audit & Implementation Guide

**Video Analyzed:** `~/workspaces/mcp-video/explainer-video/out/video-social.mp4`  
**Duration:** ~48 seconds  
**Audit Date:** 2026-03-28  
**Auditor:** AI Red Team Analysis

---

## Executive Summary

The current explainer video has polished visuals but fails at storytelling and clarity. It tells what mcp-video *has* but not why anyone should *care*. The lack of a concrete demo showing AI actually using the tool is the biggest missed opportunity.

**Current Grade: C+**

### Primary Issues
1. No narration/voiceover - relies entirely on text
2. Confusing negative opening hook
3. No actual demonstration of the product working
4. Weak call-to-action
5. Missing accessibility features (captions)

---

## Implementation Priorities

### P0 - CRITICAL (Must Fix)
| # | Issue | Current State | Required Fix |
|---|-------|---------------|--------------|
| 1 | Opening Hook | "CLI video editing is broken" | Reframe to positive: "CLI video editing just got an upgrade" or "AI agents can now edit video programmatically" |
| 2 | Demo Gap | No demonstration of AI using the tool | Add 5-8 second screen recording showing an AI agent (Claude/Cursor) calling mcp-video and processing a video |
| 3 | Feature Cards Scene | Decorative gradient bar with no purpose | Replace with actual before/after video comparisons showing transformations |
| 4 | Accessibility | No captions/subtitles | Add burned-in animated captions throughout |

### P1 - HIGH PRIORITY (Should Fix)
| # | Issue | Current State | Required Fix |
|---|-------|---------------|--------------|
| 5 | Audio | Completely silent | Add background music (tech/electronic beat, 120-130 BPM) OR professional voiceover |
| 6 | Counter Animation | Tool names orbit too fast, unreadable | Slow orbit to 50% speed OR use radial explosion reveal with staggered timing |
| 7 | Pro Features | List without context or demos | Add micro-demos: show shaky clip → stabilized, green screen → replaced background |
| 8 | Color Palette Scene | Unclear value proposition | Add context text: "Match your video's color grade to your brand palette automatically" |
| 9 | CTA | Weak ending with just stats | Add compelling CTA with animation: "pip install mcp-video" with typing animation and copy indicator |

### P2 - MEDIUM PRIORITY (Nice to Have)
| # | Issue | Current State | Required Fix |
|---|-------|---------------|--------------|
| 10 | Architecture Slide | Dense text stack (5 boxes) | Animate data flow with glowing packet traveling AI → MCP → FFmpeg → Output |
| 11 | Remotion Integration | Abstract file tree view | Show actual Remotion project rendering with mcp-video post-processing it |
| 12 | MCP Explanation | Assumes audience knows MCP | Add 1-second primer: "MCP = USB-C for AI tools" with visual analogy |
| 13 | Competitive Context | No differentiation | Add 3-second comparison: 10 lines of MoviePy vs 1 line of mcp-video |
| 14 | Trust Signals | No social proof | Add 2-second montage of real videos created with the tool |

---

## Detailed Scene-by-Scene Breakdown

### Scene 1: Opening Hook (00:00 - 00:02)

**Current:**
- Black screen with cyan cursor blinking
- Text types: "CLI video editing is broken"
- Glitch transition to "mcp-video"

**Problems:**
- Negative framing alienates CLI users
- No audio cue for attention

**Required Changes:**
```
Option A (Recommended):
- Text: "What if AI could edit videos for you?"
- Or: "AI agents can now edit video programmatically"
- Keep the glitch transition (it's good)
- Add subtle "typewriter" sound effect

Option B:
- Text: "CLI video editing, reimagined for AI"
- More neutral, doesn't insult current users
```

**Technical Specs:**
- Keep glitch effect duration (0.5s)
- Add sound effect: mechanical/digital transition sound
- Text color: Keep current orange (#FF6B35) or shift to gradient

---

### Scene 2: Counter Animation (00:02 - 00:06)

**Current:**
- Number counts: 5 → 12 → 20 → 32 → 43
- Tool names orbit around the number (watermark, fade, blur, trim, etc.)
- Text: "MCP Tools for AI Agents"

**Problems:**
- Orbiting text moves too fast to read
- No explanation of what "43" means until the end
- Empty black space feels unfinished

**Required Changes:**
```
1. Slow down the orbit animation by 50%
2. Add motion trails to orbiting labels
3. OR replace orbit with radial staggered reveal:
   - Each tool name fades in at its position
   - Lines connect to center number
   - Number pulses with each new tool revealed

4. Add subtitle: "43 powerful video editing tools"
5. Background: Add subtle particle field or grid to reduce empty space
```

**Technical Specs:**
- Orbit duration: Increase from current ~3s to 5-6s
- Text labels: Add glow/bloom effect for readability
- Number: Scale up 20% and add gradient fill

---

### Scene 3: Feature Cards (00:06 - 00:13)

**Current:**
- 6 feature cards in two rows:
  - Top: Trim & Cut, Merge, Color Grade
  - Bottom: Audio Sync, Resize, Convert
- Right side: Animated gradient bar with "BEFORE / AFTER" labels

**Problems:**
- Gradient bar is decorative but shows no actual transformation
- Cards are static and boring
- No demonstration of features working

**Required Changes:**
```
Replace entire scene with:

Layout:
┌─────────────────┬─────────────────┐
│  Feature Card   │   Before Clip   │
│  (Animated)     │   → After Clip  │
└─────────────────┴─────────────────┘

Feature demonstrations (cycle through 2-3):

1. Trim & Cut:
   - Before: Long video timeline
   - After: Trimmed section highlighted
   - Show scissors icon animation cutting the timeline

2. Color Grade:
   - Before: Flat, desaturated video clip
   - After: Same clip with cinematic color grading
   - Use actual video footage, not gradients

3. Merge:
   - Before: Two separate video clips
   - After: Seamlessly merged clip
   - Show transition effect

Animation:
- Cards slide in from left
- Before/After wipe transition (vertical or horizontal)
- Each feature shown for 2 seconds
```

**Technical Specs:**
- Card size: 280px × 120px each
- Video preview size: 400px × 225px (16:9)
- Transition wipe: 0.5s duration with motion blur
- Use actual video clips, not placeholder gradients

---

### Scene 4: Pro Features (00:13 - 00:20)

**Current:**
- "Pro Features" title
- Radial layout with center "PRO" circle
- 6 features around it: Chroma Key, Speed, Overlay, Stabilize, Subtitles, Watermark
- Bottom: Audio waveform visualization (purple bars)
- Bottom-left: "KEN BURNS" label on dark rectangle

**Problems:**
- No explanation of what makes these "Pro"
- Static radial layout is boring
- Ken Burns label is cryptic and unexplained
- Audio waveform is decoration without context

**Required Changes:**
```
Structure: Animated feature showcase

For each Pro Feature (1 second each):
1. Feature name highlights/pulses
2. Brief animation showing the effect:
   
   Chroma Key:
   - Show green screen footage
   - Green disappears, replaced with background
   
   Stabilize:
   - Show shaky handheld footage
   - Smooth stabilized version
   
   Speed:
   - Normal clip → Fast motion or slow motion
   
   Subtitles:
   - Clip with audio waveform
   - Text captions appear synced to waveform

Remove:
- "KEN BURNS" label (confusing, irrelevant)
- Static radial layout

Keep:
- Audio waveform but sync it to actual audio
- "Pro Features" title with gradient animation
```

**Technical Specs:**
- Feature highlight: Glow effect + scale 1.1x
- Demo clips: 1 second each, quick cuts
- Waveform: Animate bars to actual audio levels

---

### Scene 5: Color Palette (00:20 - 00:27)

**Current:**
- Left side: "ANALYZING" box, color palette circles, color wheel
- Right side: Code snippet showing Python usage
- Code: `from mcp_video import McpVideo` and `extract_colors()` example

**Problems:**
- Unclear what problem this solves
- Why would an AI agent need color extraction?
- Code is too small and static

**Required Changes:**
```
Add context header:
"AI-Powered Color Analysis"
"Extract brand colors from any image automatically"

Visual improvements:
1. Animate the color extraction process:
   - Show product image
   - Scan line moves across image
   - Dominant colors pop out and fill the palette circles
   
2. Code improvements:
   - Highlight key lines with background color
   - Animate typing of the code
   - Add comment explaining use case:
     # Extract brand colors for consistent video styling

3. Show output result:
   - Display extracted hex codes
   - Show them applied to a video color grade
```

**Technical Specs:**
- Scan animation: 2 seconds across image
- Code typing: 3 seconds, with cursor blink
- Add syntax highlighting colors (Python)
- Result overlay: Show hex codes floating from circles

---

### Scene 6: Remotion Integration (00:27 - 00:33)

**Current:**
- "Remotion Integration" title
- Terminal window showing file tree
- Workflow diagram: Spec → Components → Render → Export
- Bottom text: "remotion_render"

**Problems:**
- Assumes viewer knows Remotion
- File tree is abstract and boring
- Doesn't show the integration actually working

**Required Changes:**
```
Add context:
"Works seamlessly with Remotion"
"The React library for programmatic video"

Visual improvements:
1. Split screen:
   - Left: Remotion code being written
   - Right: Preview of video being rendered
   
2. Show the bridge:
   - Remotion output arrow → mcp-video icon → Final processed video
   - Animate the data flow

3. OR replace with:
   - Before: Complex FFmpeg command
   - After: Simple mcp-video one-liner
   - Show they're equivalent

4. Add Remotion logo (if licensing allows) or reference
```

**Technical Specs:**
- Split screen: 50/50 layout
- Data flow animation: Glowing dots traveling along path
- Code comparison: Use diff-style highlighting (red removed, green added)

---

### Scene 7: Architecture (00:33 - 00:40)

**Current:**
- "Architecture" title
- 5 stacked boxes:
  1. AI Agent (Claude / GPT / Copilot)
  2. MCP Protocol (JSON-RPC over stdio)
  3. mcp-video Server (Python / FFmpeg bridge)
  4. FFmpeg (Industry-grade encoding)
  5. Output (MP4 / WebM / GIF)
- Right side: Vertical dot line with labels

**Problems:**
- Information overload for social video
- Static boxes don't show flow
- Technical jargon without explanation

**Required Changes:**
```
Replace static boxes with animated data flow:

1. Horizontal flow diagram:
   [AI Agent] → [MCP] → [mcp-video] → [FFmpeg] → [Output]
   
2. Animated packet:
   - Glowing cyan dot travels the path
   - Each box lights up as packet passes through
   - Show transformation at each stage:
     - AI Agent: "Trim video, add captions"
     - MCP: JSON payload visible
     - mcp-video: Python code executing
     - FFmpeg: Progress bar
     - Output: Video file icon with checkmark

3. Add micro-interactions:
   - Packet enters box: Box glows
   - Packet exits: Trail effect
   - Each segment takes ~1 second

4. Simplify labels:
   - Remove "JSON-RPC over stdio" (too technical)
   - Keep "MCP Protocol" only
```

**Technical Specs:**
- Flow direction: Left to right
- Packet: 12px cyan circle with glow trail
- Box highlight: Border color change to cyan, subtle scale up
- Duration: 6-7 seconds total

---

### Scene 8: Call-to-Action (00:40 - 00:47)

**Current:**
- "mcp-video" logo
- Terminal: "$ pip install mcp-video" with cursor
- 3 stat cards: 43 Tools, 545+ Tests, Apache 2.0
- GitHub URL at bottom

**Problems:**
- Stats are boring and don't compel action
- No social proof
- GitHub URL is static text
- No urgency or compelling reason to install

**Required Changes:**
```
Revamped CTA sequence:

1. Problem statement (1 sec):
   "Tired of complex video editing APIs?"
   
2. Solution reveal (1 sec):
   "mcp-video makes it simple"
   
3. Install command with animation (3 sec):
   - Typewriter effect: "$ pip install mcp-video"
   - Cursor blinks after completion
   - Add "Copy" button that appears
   - Button press animation
   - "Copied!" confirmation
   
4. Social proof (2 sec):
   - "Trusted by developers worldwide"
   - OR: "Join 1,000+ developers"
   - Add GitHub stars count if available
   
5. Final CTA (1 sec):
   - "Get started today"
   - GitHub URL with QR code overlay
   - OR: "github.com/simonbraz/mcp-video" with underline animation

Remove:
- Static stat cards (boring)
- OR animate them: Numbers count up
```

**Technical Specs:**
- Command typing: 2 seconds
- Cursor blink: 0.5s on, 0.5s off
- Copy button: Fade in, scale up on hover
- QR code: 100px × 100px, corner position

---

## Audio Requirements

### Option A: Background Music Only
- Genre: Electronic / Tech / Lo-fi
- BPM: 120-130
- Energy: Medium, building throughout
- Duration: 48 seconds (loop if needed)
- Royalty-free sources: Epidemic Sound, Artlist, or YouTube Audio Library

### Option B: Full Voiceover
Script:
```
[00:00-00:02] "What if AI could edit videos for you?"
[00:02-00:06] "mcp-video gives AI agents 43 powerful video editing tools."
[00:06-00:13] "Trim, merge, color grade, convert—everything you need."
[00:13-00:20] "Pro features like chroma key, stabilization, and subtitles."
[00:20-00:27] "Extract colors, analyze content, automate your workflow."
[00:27-00:33] "Works seamlessly with Remotion and your favorite AI agents."
[00:33-00:40] "Built on MCP protocol and FFmpeg for industry-grade performance."
[00:40-00:47] "Install mcp-video today. pip install mcp-video."
```

Voice: Professional, neutral accent, medium pace

---

## Accessibility Requirements

### Captions/Subtitles
- Burn in captions (not optional overlay)
- Font: Sans-serif, bold, white with black outline
- Size: Large enough to read on mobile (40px+)
- Position: Bottom third, safe area
- Style: Appear word-by-word or line-by-line synced to content

### Color Contrast
- Ensure all text meets WCAG AA standards (4.5:1 ratio)
- Current orange text (#FF6B35) on black: ✓ Passes
- Cyan accents: Ensure visibility on dark backgrounds

---

## Technical Delivery Specs

### Video Format
- Resolution: 1920×1080 (1080p) minimum
- Aspect Ratio: 16:9 (primary), 9:16 vertical cut optional
- Frame Rate: 30fps
- Codec: H.264
- Container: MP4

### Platforms
- Primary: Twitter/X, LinkedIn, GitHub README
- Optional: YouTube (longer version with more detail)
- Mobile: Create 9:16 vertical cut (see below)

### Vertical Cut (9:16) Requirements
If creating mobile version:
- Recompose all scenes for vertical
- Stack layouts vertically instead of side-by-side
- Increase text size by 20%
- Ensure captions are in safe area (center 60% of screen)

---

## Assets Needed

### Video Clips (for before/after demonstrations)
Need 3-5 short clips (2-3 seconds each):
1. Shaky handheld footage (for stabilization demo)
2. Green screen footage (for chroma key demo)
3. Flat/desaturated footage (for color grade demo)
4. Multiple clips (for merge demo)
5. Talking head or audio content (for subtitle demo)

**Source**: Use stock footage from Pexels, Pixabay, or create synthetic clips

### Audio
- Background music track (royalty-free)
- Sound effects: Typewriter, glitch/transition, success/ding

### Graphics
- mcp-video logo (existing)
- MCP protocol logo/icon
- Remotion logo (check licensing)
- GitHub icon
- QR code for final scene

---

## Implementation Checklist

### Pre-Production
- [ ] Select/reject each recommendation
- [ ] Source video clips for demonstrations
- [ ] Select background music
- [ ] Write final voiceover script (if using)
- [ ] Create storyboard with all changes

### Production
- [ ] Record/generate voiceover
- [ ] Create new motion graphics
- [ ] Edit video clips for demonstrations
- [ ] Add sound effects
- [ ] Create animated captions

### Post-Production
- [ ] Color grade for consistency
- [ ] Audio mixing (music levels, voiceover clarity)
- [ ] Add burned-in captions
- [ ] Export multiple formats (16:9, 9:16)
- [ ] Test on mobile devices

### Quality Check
- [ ] Watch without sound (captions readable?)
- [ ] Watch on phone screen (text visible?)
- [ ] Check opening 3 seconds (hook compelling?)
- [ ] Verify CTA is clear and memorable
- [ ] Test accessibility (contrast, captions)

---

## Success Metrics

After implementing these changes, the video should:
1. **Hook viewers** in first 3 seconds (positive framing)
2. **Demonstrate value** with actual product usage (not just telling)
3. **Be accessible** with captions and clear visuals
4. **Drive action** with compelling CTA
5. **Work on mobile** with readable text and clear visuals

Target improvements:
- Engagement: Increase watch-through rate from ~40% to 70%+
- Clarity: Viewer can explain what mcp-video does after one watch
- Action: Measurable uptick in GitHub stars and pip installs

---

## Notes for Implementing Agent

1. **Source files**: The original video was created with Remotion. Check if source code is available in `explainer-video/` directory.

2. **Quick wins**: If time-constrained, prioritize P0 items and the P1 audio addition.

3. **Testing**: Get feedback from someone unfamiliar with mcp-video before finalizing.

4. **A/B test**: Consider creating two versions:
   - Version A: Music only, faster cuts
   - Version B: Voiceover, more explanation

5. **Platform variants**: The 16:9 version is primary, but a 9:16 vertical version will perform better on mobile/TikTok/Instagram Reels.

---

END OF DOCUMENT
