# Design-system interview — **Kinocut only**

**Product:** Kinocut (formerly mcp-video) — guardrailed local video MCP / CLI / Python client  
**Site:** https://kinocut.dev/  
**Interview authority:** `design-system-interview` (latest in `~/.grok/skills/design-system-interview/`, 2026-07-13)  
**Date:** 2026-07-14  
**State:** `approval-ready` — answers are **Kinocut-specific commitments** ready for Simon confirmation before implementation redesign. Not KyaniteLabs generic marketing.

**What I see:** Kinocut sells **trust after an agent edit** (preflight → render → receipt → human gate), not “AI magic video.”  
**My recommendation:** Instrument-bench / edit-suite dark UI where the **Video Receipt** is the hero object and density beats lifestyle whitespace.  
**Why it fits:** Operators run agents on real client media; they need scan speed, proof, and fail-closed language — not SaaS gradients.

---

## Every required dimension (answered for Kinocut)

### 1. `reference` — Visual reference / personality anchor

**Question the skill forces:** What real artifact should this interface feel like, and what does that earn?

**Kinocut answer (committed recommendation):**

| | |
| --- | --- |
| **Reference** | A **colorist / finishing bay** desk + **NLE inspector panel** (DaVinci/Resolve-class instrument chrome), not a consumer iMovie splash and not a generic “AI startup” landing. Secondary: **terminal job log** (the CLI/MCP operator already lives here). |
| **What it earns** | Immediate “this product *is* an execution instrument,” room for mono receipts, and permission for high information density. |
| **Explicit rejection** | KyaniteLabs org homepage as the *product* reference; SaaS feature-grid templates; paper/till-receipt novelty for the Video Receipt. |
| **Evidence** | Product is FFmpeg/MCP/CLI; primary JTBD is local interview → verticals **with a receipt**; existing hero already uses receipt + playhead timeline metaphor. |

---

### 2. `personality` — Brand personality spectrum

**Question:** Which pole, not the middle?

**Kinocut answer:**

| Pole | Choice | Why Kinocut (not org-generic) |
| --- | --- | --- |
| Warm ↔ Cool | **Cool field** | Edit rooms, scopes, scopes-as-UI; warmth only at **trust moments** (pass stamps). |
| Playful ↔ Serious | **Serious** | Client media + publish risk; playful undermines “don’t silently ship bad renders.” |
| Airy ↔ Dense | **Dense** | 135+ tools and agent logs; airy marketing wastes the operator’s scan time. |
| Raw ↔ Refined | **Technical-refined** | Precision without enterprise beige; refined means hairlines and hierarchy, not luxury fashion. |

**One line:** cool · serious · dense · technical-refined — **for an edit-suite product**, not a labs portfolio.

---

### 3. `aesthetic` — Aesthetic territory

**Question:** One concrete phrase that predicts hierarchy and material.

**Kinocut answer:**

> **“Agent edit bay on basalt — cyan schematics, amber verified, magenta still needs a human.”**

Predicts:

- Hierarchy: commands and receipts outrank adjectives  
- Material: dark stone surfaces, hairline rules, flat panels (no glassmorphism)  
- Meaning: cyan = active/system; amber = verified/pass; magenta = pending human  

---

### 4. `type` — Typography stance

**Question:** Binding evidence, display/body stance, language/measure risk.

**Kinocut answer:**

| Role | Stance | Binding evidence |
| --- | --- | --- |
| Display | **Space Grotesk 700** (or brand-locked grotesque) | Product wordmark KINO/**CUT**; needs mechanical cut, not soft humanist marketing. |
| Body | **Plus Jakarta Sans 400/700** | Long EN/ES explanations (FAQ, install, compare); bilingual peer copy needs clean dual-script friendliness. |
| Mono | **JetBrains Mono** — **elevated role** | CLI, MCP JSON, receipts, digests, timecodes are first-class product UI, not footnotes. |
| Measure | **~60–70ch** for docs; tighter for hero lede | Docs pages already long; marketing hero stays scannable. |
| Language risk | **EN + ES as peers** | Product already ships bilingual surfaces; type must not privilege English-only flourish fonts. |

**Refusal:** Inter/Roboto/system-ui-as-brand; monospace only in code blocks as an afterthought.

---

### 5. `color_mode` — Color and mode

**Question:** Dominant hue, accent jobs, light/dark commitment.

**Kinocut answer:**

| Role | Token job | Kinocut meaning |
| --- | --- | --- |
| Field | Void / basalt darks | Edit suite default; matches local TUI/agent work. |
| Dominant accent | **Cyan** | Links, active rails, “system is live.” |
| Trust | **Amber only** | Checks passed, verified, receipt OK — *not* decorative gold. |
| Human gate | **Magenta only** | Pending human review, edit markers, “stop before publish.” |
| Structural | Cool blue (low chroma) | Borders/shapes only — never body copy. |
| Success | Mint/pass green | Quality pass marks in ledger/receipt. |
| Mode | **Dark-only product site** | Light theme is a later *docs-reader* option, not the brand surface for kinocut.dev. |

**Refusal:** Purple AI gradients; rainbow feature icons; amber everywhere.

---

### 6. `density_shape` — Density and shape language

**Question:** Density, radius range, elevation.

**Kinocut answer:**

| | |
| --- | --- |
| Density | **Dense-leaning** — more facts per viewport (tool counts, install, gates). |
| Radius | **4–8px** max; receipt panel may go slightly larger for grip, never pills. |
| Elevation | **Flat + hairline**; one lifted panel only: the receipt. |
| Cards | **Ledger rows**, not 3-up card grids. |

---

### 7. `structure_rhythm` — Layout structure and rhythm

**Question:** Composition, motif, sectional cadence.

**Kinocut answer:**

| | |
| --- | --- |
| Composition | **Asymmetric hero:** thesis/install left, **Video Receipt** right (or reverse on small screens stack receipt after thesis). |
| Motif | **Timeline / playhead** as ambient page chrome (page scroll = take); section labels can be timecodes or gate names (PREFLIGHT / RECEIPT / QUALITY). |
| Cadence | **Engineering-sheet bands** with left annotation rails — not metronomic equal marketing slabs. |
| Docs subpages | Single-column **48rem** reading measure; sticky top nav of product paths. |
| Hub | Home → job paths (install, prompts, tutorial, receipt, compare) as operator “bins,” not feature marketing tiles. |

---

### 8. `signature` — One memorable move

**Question:** What earns attention once?

**Kinocut answer:**

**The Video Receipt as an engraved instrument readout** (hashes, guardrails, human-review pending stamp) — the product thesis made visible.

Everything else (playhead, cyan rails) is **ambient**. If two things fight for boldness, **receipt wins**.

**Not the signature:** logo wordmark alone; purple hero blob; stock “team collaborating on video” photo.

---

### 9. `imagery_iconography` — Imagery and icon system

**Question:** Source/treatment or absence; one icon system.

**Kinocut answer:**

| Layer | Rule |
| --- | --- |
| Photography | **At most one** brand tableau (hero/OG) — stone/edit-suite, void-faded under text. No stock creators smiling at laptops. |
| Product imagery | Prefer **terminal transcripts**, receipt panels, quality scores — generated from real product chrome. |
| Icons | **One system** (Lucide 1.5px stroke) if needed; never emoji-as-UI; never mixed packs. |
| Diagrams | Cyan/amber on basalt only; one style for architecture/receipt field maps. |
| Rights | Only owned or generated brand art; no random AI stock. |

---

### 10. `motion` (optional but answered)

**Question:** Does motion change comprehension?

**Kinocut answer:**

| | |
| --- | --- |
| Level | **Restrained** |
| Allowed | Skip-link; hover; **scroll-linked playhead position**; FAQ open/close |
| Forbidden | Scroll-jacking; autoplay video; decorative parallax; staggered marketing reveals |
| Reduced motion | Collapse all nonessential motion immediately |

Motion should feel like a **transport control**, not a brand film.

---

## Decision map (confirmation table)

| ID | Evidence | Decision | Consequence | State |
| --- | --- | --- | --- | --- |
| reference | MCP/CLI/FFmpeg product; receipt JTBD | Edit bay + NLE inspector | Dense instrument UI | **committed recommendation** |
| personality | Publish risk; operator users | cool/serious/dense/refined | No playful SaaS tone | **committed recommendation** |
| aesthetic | Trust triad preflight/receipt/quality | “Agent edit bay on basalt…” | Cyan/amber/magenta roles | **committed recommendation** |
| type | CLI+receipt+EN/ES | Space Grotesk / Plus Jakarta / JetBrains | Mono elevated | **committed recommendation** |
| color_mode | Dark edit rooms; existing tokens | Dark-only; cyan/amber/magenta jobs | No light marketing default | **committed recommendation** |
| density_shape | 135 tools, docs depth | Dense, 4–8px, flat | Ledger not cards | **committed recommendation** |
| structure_rhythm | Timeline metaphor; multi-page hub | Asymmetric hero + sheet bands | Timecode/gate rails | **committed recommendation** |
| signature | Product differentiator | Video Receipt panel | One boldness budget | **committed recommendation** |
| imagery_iconography | Local-first; no stock | Tableau once; Lucide only | No AI-slop photos | **committed recommendation** |
| motion | Operator annoyance risk | Restrained + reduced-motion | Playhead ambient | **committed recommendation** |

**Readiness:** `approval-ready` — Simon can mark `approved` in one pass; implementation redesign should not start until that stamp (tastecheck below is against **current live artifact**, not a new build).

---

## Refusals (Kinocut-specific)

1. Do not brand the product site as generic **KyaniteLabs portfolio** chrome.  
2. Do not center **generative AI video** fantasy (Sora-class) — Kinocut is execution + trust.  
3. Do not use **tool count** as the only hero metric (stale-prone; prefer receipt/job).  
4. Do not ship **light-theme-first** marketing.  
5. Do not decorate with **purple gradients / glass / three-card features**.  

---

## One-line direction (for handoff)

> **Agent edit bay on basalt — dense cool instrument hierarchy, cyan system / amber verified / magenta human-pending, Space Grotesk + Plus Jakarta + elevated mono, flat hairline ledger structure, signature = Video Receipt panel, imagery = one tableau + product chrome only, motion = transport-level only.**

---

## Next move after approval

1. Re-token `kinocut-site` strictly to this map (it already mostly matches — close gaps from multi-page doc chrome).  
2. Re-run `tastecheck-pass` on **home + install + receipt** as the three critical surfaces.  
3. Only then visual redesign work.

---

**Canonical pack path (latest):** `~/workspaces/tastecheck` (skills + `contracts/v1/interviews/{greenfield,brownfield}.json`). Claude/Grok skill dirs symlink or copy from this tree (2026-07-13).
