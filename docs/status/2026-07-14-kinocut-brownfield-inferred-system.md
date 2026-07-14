# INFERRED-SYSTEM — kinocut.dev (brownfield)

**Pack:** canonical TasteCheck monorepo `~/workspaces/tastecheck`  
**Skills:** `improve-existing-website` + `design-system-interview` + `tastecheck-pass`  
**Contracts:** `contracts/v1/interviews/brownfield.json` + `greenfield.json`  
**Artifact:** https://kinocut.dev/ (live, 2026-07-14)  
**Product:** Kinocut only (not KyaniteLabs org marketing)

> **Historical snapshot:** This inference record captures the site observed on
> 2026-07-14 before the 1.8.0 release reconciliation. It is not current product
> release guidance; use the root README and `docs/public_claims.json` for that.

---

## Evidence summary (EVIDENCE)

| Observation | Where |
| --- | --- |
| Dark basalt/void field, cyan accents | home CSS + hero |
| Video Receipt figure as hero object | home |
| Playhead scroll chrome | `js/site.js` |
| Bilingual EN/ES toggle on home | home header |
| Multi-page marketing hub (install, prompts, …) | `/install.html` etc. |
| Doc pages use separate `pages.css` utility chrome | live compare home vs install |
| Product claims at capture: 1.7.0 / local-first / formerly mcp-video | home, llms, FAQ |
| No forms, no analytics cookies | live |

## Inferred brand signals (INFERRED)

| Inference | Basis |
| --- | --- |
| Trust triad (preflight / receipt / quality) is the product story | home ledger copy + JTBD |
| Operator density preferred over lifestyle marketing | dense mono install blocks, tool depth |
| Signature must be receipt, not logo wordmark alone | receipt panel visual weight on home |
| Doc hub shipped for GEO faster than design-system shell | pages.css drift vs DESIGN-SYSTEM.md |

## Preserved signals (must not erase without approval)

1. **Video Receipt** as conceptual and visual signature  
2. **Dark-only** product marketing field  
3. **Cyan / amber / magenta** semantic jobs (system / trust / human-pending)  
4. **Space Grotesk + Plus Jakarta + JetBrains Mono** stack  
5. **Tableau hero** (single photographic asset)  
6. **Local-first / no analytics** stance  
7. **Bilingual EN/ES** on primary surface  
8. **Playhead** as ambient timeline metaphor  

## Readiness scores (0–10, pass ≥6)

| Dimension | Score | Note |
| --- | ---: | --- |
| brand_coherence | 7 | Home coheres; doc pages lag |
| visual_consistency | 5 | Multi-page chrome drift |
| content_clarity | 8 | JTBD, install, compare strong |
| accessibility_baseline | 6 | Skip + details; nav density weak |
| performance_signals | 8 | Static Pages, self-hosted fonts |
| navigation_clarity | 5 | Long doc-nav; hub helps |

**Overall readiness:** **medium** — proceed with **targeted improvement**, not full rebrand. Material redesign of doc shell requires explicit approval (already framed as HOLD blockers).

## Proposed improvement scope (ordered)

1. **Normalize** doc-page chrome to design-system tokens (preserve receipt/home language).  
2. **Normalize** nav for 320px + keyboard (preserve path set).  
3. **Approve needed** if expanding ES beyond `es-content.html` (scope change, not identity change).  
4. **Preserve** home signature; do not restyle receipt into paper/novelty forms.

## Material redesign gate

Changing the home receipt signature, dark-only mode, or cyan/amber/magenta roles = **material redesign** → needs Simon explicit approval.  
Fixing `pages.css` drift = **normalize** under existing DESIGN-SYSTEM.md.

---

## Link to greenfield interview answers

Full dimension answers (Kinocut-specific):  
`docs/DESIGN-SYSTEM-INTERVIEW-KINOCUT.md`

TasteCheck release brief:  
`docs/status/2026-07-14-tastecheck-ledger.md` → **HOLD**
