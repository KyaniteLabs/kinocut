# Smoke evidence generation log (release 1.6.0)

Seed token (novel per run): `1783589514`

All media generated fresh with FFmpeg; all receipts below are workspace-relative.

```
(a) E2E render status=completed steps=['completed', 'completed', 'completed', 'completed']
wrote smoke/workflow_render_receipt.json
(b) dry-run plan: media files before=3 after=3 (no media written)
wrote smoke/workflow_plan_dryrun.json
(c) variants batch kind=workflow_batch count=2 variants=['square', 'wide']
wrote smoke/workflow_variants_receipt.json
(d) first render status=completed (intermediates kept)
(d) sabotage: deleted output/final.mp4
(d) resume status=completed resume_used=True skipped=['probe-hero', 'trim-hero', 'resize-hero'] statuses={'probe-hero': 'completed', 'trim-hero': 'completed', 'resize-hero': 'completed', 'caption': 'completed'}
wrote smoke/workflow_resume_receipt.json
(e) composite dry-run schema=2 kind=layer_plan blend_modes=['multiply', 'normal'] rotation=True output_path=output/composite.mp4
wrote smoke/composite_layer_plan_v2.json
(f) SSIM between two independent renders = 1.0 (overall=high)
wrote smoke/ssim_stability.json
```
