# Performance committee receipts (inspect only)

**Date:** 2026-08-13 (filed 2026-08-19)  
**Mode:** inspect leftovers. **Do not implement from these reports.**

Five models recommended a 3-encode split/PiP rewrite. That work **already shipped**
in 1.14.0 as `kinocut.te.sphere_graph.render_window_single_pass` (used from
`sphere_render.py`). Re-implementing it from these reports would be a regression.

These files are dated inspection receipts, not a current performance claim and
not a 1.15.0 product change.

| File | Role |
| --- | --- |
| `BRIEF.md` | Inspect-only dispatch brief |
| `REPORT-sol.md` | Sol |
| `REPORT-grok.md` | Grok |
| `REPORT-glm.md` | GLM |
| `REPORT-kimi-k3.md` | Kimi |
| `REPORT-deepseek-v4-pro.md` | DeepSeek |

Reopen a 360-perf change only with a **failing timing probe** against the
current single-pass renderer, not from this folder.
