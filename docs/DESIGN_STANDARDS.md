# Kinocut Visual Design Standards

## Overview

Kinocut uses a consistent visual design system for all video output. These standards ensure professional, accessible, and visually appealing results.

## Color Palette

### Primary Colors
- **Electric Lime**: `#CCFF00` - Primary accent, CTAs, highlights
- **Midnight Violet**: `#5B2E91` - Deep backgrounds, contrast
- **Violet Mid**: `#7C3AED` - Secondary accent

### Background Colors
- **Deep**: `#1a1a1e` - Primary background (was pure black)
- **Elevated**: `#242428` - Cards, elevated surfaces
- **Surface**: `#2a2a2f` - Interactive elements

### Text Colors
- **Primary**: `#f0f1f5` - Main text
- **Secondary**: `#a1a1aa` - Supporting text
- **Muted**: `#71717a` - Disabled, hints

### Gradients
```css
Primary: linear-gradient(135deg, #5B2E91, #7C3AED, #CCFF00)
```

## Typography

### Font Stack
- **Display**: Inter, system-ui, -apple-system
- **Code**: JetBrains Mono, SF Mono, Fira Code

### Type Scale
| Level | Size | Weight | Use Case |
|-------|------|--------|----------|
| Display | 160px | 800 | Hero numbers |
| Headline | 64px | 600 | Scene titles |
| Title | 48px | 600 | Section headers |
| Subtitle | 24px | 500 | Supporting text |
| Body | 16px | 400 | Default text |
| Caption | 14px | 400 | Labels |
| Overline | 12px | 600 | Uppercase labels |

### Typography Rules
1. **Maximum line length**: 60 characters for readability
2. **Minimum font size for video**: 24px for 1080p
3. **Line height**: 1.5 for body, 1.1 for display
4. **Letter spacing**: -0.02em for headlines

## Layout & Spacing

### Safe Areas
- **Text safe margin**: 8% from edges (approx 154px on 1920px width)
- **Critical content**: Keep within 90% of frame center
- **Captions**: Position 60-100px from bottom

### Spacing Scale
| Token | Value | Use |
|-------|-------|-----|
| XS | 4px | Tight gaps |
| SM | 8px | Icon gaps |
| MD | 16px | Standard padding |
| LG | 32px | Section gaps |
| XL | 48px | Major sections |
| XXL | 80px | Scene separators |

### Glass Card Style
```css
background: rgba(27, 28, 30, 0.7);
backdrop-filter: blur(12px);
border: 1px solid rgba(255, 255, 255, 0.08);
border-radius: 12px;
```

## Motion & Animation

### Timing Standards
| Duration | Use Case |
|----------|----------|
| 200ms | Micro-interactions |
| 300ms | Button states |
| 500ms | Scene transitions |
| 1000ms | Major reveals |

### Easing Functions
- **Default**: `cubic-bezier(0.4, 0, 0.2, 1)` (ease-out)
- **Entrance**: `cubic-bezier(0, 0, 0.2, 1)` (decelerate)
- **Exit**: `cubic-bezier(0.4, 0, 1, 1)` (accelerate)
- **Bounce**: `cubic-bezier(0.34, 1.56, 0.64, 1)`

### Frame Rate Standards
- **Minimum**: 24 fps
- **Standard**: 30 fps
- **High-end**: 60 fps for motion-heavy content

## Composition Rules

### Visual Hierarchy
1. **Focal point**: One primary element per scene
2. **Rule of thirds**: Place key elements at intersections
3. **Balance**: Asymmetrical balance preferred
4. **White space**: 40% of frame should be "breathing room"

### Text Overlay Rules
1. **Contrast ratio**: Minimum 4.5:1 (WCAG AA)
2. **Background**: Add semi-transparent backdrop behind text
3. **Stroke/shadow**: Use for readability on busy backgrounds
4. **Duration**: Text should be readable for at least 2 seconds

## Quality Guardrails

### Technical Checks (Auto-enforced)
- Brightness target: FFmpeg `signalstats.YAVG` from 40-200 on the 8-bit luma scale (0-255).
- Contrast target: 20-100 percent of the 8-bit luma range, derived from `YHIGH-YLOW`.
- Saturation target: 10-120 percent of the practical 8-bit YUV saturation range, calculated as `SATAVG / 181 * 100`.
- Text contrast ratio: at least 4.5:1.
- Frame rate: at least 24 fps. A 24 fps delivery is valid and intentional, not a warning by itself.
- Audio loudness target: -16 LUFS; true peak must remain at or below -1 dBTP.
- Color-cast warnings are advisory when the look is intentional.

### Design Checks (Flagged for review)
- Text near edges (check safe areas).
- Font size below 24px at 1080p.
- Low saturation below 10 percent of the practical 8-bit YUV saturation range.
- High saturation above 90 percent is informational unless the brand theme makes it intentional.
- Excessive contrast above 100 percent of the 8-bit luma range.
- Animation frame drops.

### Composition Checks (Manual review suggested)
- 📝 Visual balance
- 📝 Focal point clarity
- 📝 Consistent spacing
- 📝 Color harmony

## Auto-Fix Capabilities

The design quality system can automatically fix:

1. **Brightness**: Adjust gamma for better visibility
2. **Contrast**: Apply mild contrast enhancement
3. **Saturation**: Boost slightly if too flat
4. **Audio levels**: Normalize to -16 LUFS

## Usage in Code

```python
from kinocut import design_quality_check, fix_design_issues

# Check design quality
report = design_quality_check("my_video.mp4")
print(f"Design score: {report.design_score}/100")

for issue in report.issues:
    print(f"{issue.severity}: {issue.message}")

# Auto-fix issues
fixed_video = fix_design_issues("my_video.mp4", output="fixed.mp4")
```

## Implementation

See `kinocut/design_quality/` for the implementation of these standards.
