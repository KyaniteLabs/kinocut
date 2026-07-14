# TasteCheck Pass — kinocut.dev (live)

**Skill pack:** `tastecheck-pass` @ `~/.grok/skills/tastecheck-pass/` (latest present 2026-07-13)  
**Direction skill:** `design-system-interview` → Kinocut answers in `docs/DESIGN-SYSTEM-INTERVIEW-KINOCUT.md`  
**Artifact:** https://kinocut.dev/ (+ install, receipt, multi-page hub)  
**Spec:** `kinocut-site/DESIGN-SYSTEM.md` + interview record above  
**When:** 2026-07-14  

---

# HOLD — 4 blockers (content hub expanded faster than design system discipline)

**What passed:** Product story, SEO/GEO bones, bilingual intent, receipt as conceptual signature, dark basalt field, no purple-slop hero.  
**Ship blockers:** TC-STRUCT-01 doc-page chrome vs signature system; TC-A11Y-01 doc-nav density/keyboard; TC-DESLOP-01 multi-page template drift; TC-I18N-01 ES parity incomplete on new routes.  
**Fastest path:** Unify doc pages into design-system shell (receipt tokens, rails, density) → keyboard audit on `/install.html` nav → ES routes for install/faq or explicit EN-only labeling → remeasure.  
**Evidence:** live URLs 200; interview file; this ledger.

---

## Evidence table

| skill | check_id | status | reason | remediation | evidence | provenance |
| --- | --- | --- | --- | --- | --- | --- |
| design-system-interview | DIR-01 nine dimensions | **pass** | All 9 + motion answered for Kinocut specifically | Confirm with Simon → mark approved | `docs/DESIGN-SYSTEM-INTERVIEW-KINOCUT.md` | interview 2026-07-14 |
| design-system-interview | DIR-02 existing system | **pass** | Existing `DESIGN-SYSTEM.md` on site; interview refines Kinocut vs org-generic | Keep single SoT after approval | `kinocut-site/DESIGN-SYSTEM.md` | site repo |
| color-system | TC-COLOR-01 roles | **pass** | Live home uses void/basalt, cyan accents, amber trust, magenta pending on receipt | Keep role discipline on doc pages | https://kinocut.dev/ | live HTML/CSS |
| color-system | TC-COLOR-02 doc pages | **fail** | Doc pages use simplified `pages.css`; weaker amber/magenta semantics | Port token roles into `pages.css` | https://kinocut.dev/install.html | live |
| web-typography | TC-TYPE-01 faces | **pass** | Home self-hosts Space Grotesk / Plus Jakarta / JetBrains | — | `css/tokens.css` + home | live |
| web-typography | TC-TYPE-02 measure | **pass** | Doc main max-width ~48rem | Watch table overflow on mobile | `css/pages.css` | live |
| spacing-system | TC-SPACE-01 | **pass** | Token-based spacing on home | Align doc-top nav gap to same scale | home CSS | live |
| theming | TC-THEME-01 dark-only | **pass** | Dark product site intentional | Don’t add accidental light | home + docs | live |
| responsive-layout | TC-RESP-01 | **fail** | Doc-nav is a long wrap list; likely poor at 320px | Collapse to select/details nav or priority+more | `/install.html` nav | live structure |
| component-states | TC-STATE-01 | **n/a** | Few interactive controls beyond lang toggle + FAQ details | When buttons ship, full state matrix | home FAQ details | live |
| form-ux | TC-FORM-01 | **n/a** | No forms | — | — | — |
| empty-states | TC-EMPTY-01 | **n/a** | No empty app states | — | — | — |
| micro-motion | TC-MOTION-01 | **pass** | Restrained playhead; FAQ details | Ensure `prefers-reduced-motion` kills playhead animation | `js/site.js` | code |
| data-viz | TC-DV-01 | **n/a** | No charts on marketing site | Usage metrics stay internal | metrics docs | intentional |
| art-direction | TC-ART-01 | **pass** | Single tableau; receipt signature | Don’t add stock | home hero | live |
| a11y-pass | TC-A11Y-01 skip + lang | **pass** | Skip link; lang toggle; details/summary FAQ | — | home | live |
| a11y-pass | TC-A11Y-02 keyboard nav | **fail** | Doc-nav many tab stops; no landmark simplification | Fewer nav items or grouped nav | doc pages | live |
| cognitive-a11y | TC-COG-01 | **pass** | Clear JTBD emerging; failure examples help | Keep jargon defined (receipt) | `/failures.html` | live |
| i18n-ready | TC-I18N-01 | **fail** | Home bilingual; most new routes EN-only | ES for install/faq/receipt or label “EN” | `/es-content.html` vs `/install.html` | live |
| deslop-ui | TC-DESLOP-01 against spec | **fail** | Multi-page hub reads as utility docs template; drifts from edit-bay signature | Restyle doc chrome to rails + hairlines + receipt motifs | compare home vs install | live |
| humanize-copy | TC-COPY-01 | **pass** | Product-specific, anti-hype, rename honest | Keep “1.8 not released” discipline | compare/recommend | live |
| tastecheck-pass | TC-GATE-01 real artifact | **pass** | Live kinocut.dev used | — | curl 200s | 2026-07-14 |
| tastecheck-pass | TC-GATE-02 checks ran | **pass** | Manual live audit + interview complete | Full browser keyboard pass still recommended | this ledger | 2026-07-14 |
| tastecheck-pass | TC-GATE-03 blockers owned | **pass** | Each fail has remediation | Owner: site design pass | this ledger | 2026-07-14 |

---

## Blocker path (ordered)

1. **TC-DESLOP-01 / TC-COLOR-02** — Bring `pages.css` into DESIGN-SYSTEM tokens (cyan/amber/magenta jobs, hairlines, ledger feel).  
2. **TC-RESP-01 / TC-A11Y-02** — Compact doc navigation for small screens + keyboard.  
3. **TC-I18N-01** — ES for top paths (install, receipt, faq) or explicit language labeling.  
4. Re-run tastecheck on home + install + receipt only; promote to SHIP when those three are clean.

---

## Note on “latest pack”

Executed against the **installed** `tastecheck-pass` + sibling foundation skills under `~/.grok/skills/` dated **2026-07-13** (newest tastecheck-related tree present on this machine). Direction interview used the same day’s `design-system-interview` contract (9 dimensions + motion).

---

**Canonical pack path (latest):** `~/workspaces/tastecheck` (skills + `contracts/v1/interviews/{greenfield,brownfield}.json`). Claude/Grok skill dirs symlink or copy from this tree (2026-07-13).
