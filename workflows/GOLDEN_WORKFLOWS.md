# Golden Workflow Map

These are the buyer-facing proof lanes for Kinocut.

## 1. Podcast or Interview to Vertical Short

Primary workflow:

- `workflows/01-social-media-clip`

Adjacent richer workflow:

- `workflows/02-podcast-clip`

Proof status:

- The social clip path is already used in the 2026-06-03 confidence baseline.
- It trims, resizes, adds hook text, normalizes audio, exports, and passes quality when run against the synthetic proof source.

Trust artifacts to require before publishing:

- final vertical MP4
- quality report
- release checkpoint
- Video Receipt

## 2. Product Demo / Explainer Video

Primary workflow:

- `workflows/03-explainer-video`

Proof status:

- Existing workflow demonstrates generated scenes, procedural audio, effects, transitions, assembly, audio mix, and export.
- It now writes a quality report, release checkpoint, and Video Receipt before it is treated as a release-grade demo lane.

Trust artifacts to require before publishing:

- generated scene list
- audio preset manifest
- final MP4
- quality report
- release checkpoint
- Video Receipt

## 3. Local Repurposing Package

Primary workflow:

- `workflows/06-repurpose-package`

Proof status:

- New golden workflow wraps `Client.repurpose` around a generated or user-provided source clip.
- It writes a package manifest, platform variants, thumbnails, storyboards, release checkpoints, and a Video Receipt.

Trust artifacts to require before publishing:

- `repurpose_manifest.json`
- platform variant MP4s
- per-platform thumbnails
- per-platform storyboards
- per-platform release checkpoints
- Video Receipt

## First Workflow To Try

Use `workflows/05-confidence-baseline` first. It is the smallest proof that install, edit, quality, checkpoint, receipt, and human-review behavior works without private media.
