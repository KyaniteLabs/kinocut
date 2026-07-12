# Wishlist input provenance manifest

**Purpose:** public-safe provenance for the field-wishlist and AI-video design documents

**Source date:** 2026-07-10

**Publication policy:** normalized requirements only; no local source paths or private campaign data

## Inputs and derived artifacts

| Input class | Public derivative | Treatment |
| --- | --- | --- |
| Production postmortem findings | `docs/superpowers/specs/2026-07-10-kinocut-field-wishlist-design.md` | Twelve ranked defects/capabilities normalized into product requirements; private media and operator metadata omitted |
| Expanded AI-video feature backlog | `docs/superpowers/specs/2026-07-10-kinocut-ai-video-backlog-coverage.md` | Sixty-one capabilities classified against repository evidence |
| Repository architecture and shipped surfaces | `docs/superpowers/specs/2026-07-10-kinocut-ai-video-editor-design.md` | Contract-first program design with named code/document evidence |

The original operator notes and campaign artifacts are intentionally not tracked. Their local
paths, filenames, people, and private media are not required to review the normalized requirements.
No byte hash is claimed for an untracked private input. Git commits provide provenance for each
public derivative.

## Traceability rule

The field-wishlist design owns the detailed evidence-to-requirement mapping for the original
twelve findings. The backlog coverage document owns the 61-item classification. The editor design
owns shared contracts and program sequencing. If they conflict, the later contract-first design
controls architecture while preserving the field defect as acceptance evidence.
