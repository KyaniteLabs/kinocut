# Kinocut Workflows

ICM-style staged pipelines for common video productions.

## Available Workflows

| Workflow | Description | Stages |
|---|---|---|
| `01-social-media-clip` | Turn landscape video into TikTok / Short / Reel | 5 |
| `02-podcast-clip` | Extract highlight with chapters and captions | 6 |
| `03-explainer-video` | Build branded explainer from scratch | 10 |
| `04-hyperframes-video` | Create video with Hyperframes, then post-process | 5 |
| `05-confidence-baseline` | Generate or accept a tiny source clip, create a checked vertical proof, and write a Video Receipt | 8 |
| `06-repurpose-package` | Turn one source clip into a local platform package with manifest, variants, review artifacts, checkpoints, and a Video Receipt | 5 |
| `benchmarks` | Run local receipt/readiness and adversarial certification checks over workflow outputs | varies |

## How to use

### With Claude Code

1. `cd workflows/01-social-media-clip`
2. Read `CONTEXT.md` to understand the pipeline
3. Place your raw video in the workflow directory
4. Run `python workflow.py /path/to/video.mp4`
5. Review `output/` at each stage

### As a human

Each workflow has:
- `CONTEXT.md` — Stage contract with Inputs, Process, Outputs
- `references/` — Factory configuration (specs, styles, presets)
- `workflow.py` — Runnable Python script
- `output/` — Generated artifacts

## Adding a new workflow

1. Create `workflows/NN-your-workflow/`
2. Write `CONTEXT.md` with stage contract
3. Add `references/` for configuration
4. Write `workflow.py` using the Kinocut client
5. Update `workflows/CONTEXT.md` routing table

## Confidence baseline

Use `05-confidence-baseline` when you need a clean proof run without private media:

```bash
cd workflows/05-confidence-baseline
python workflow.py
```

The workflow writes `output/video_receipt.json` so the final video, quality report, thumbnail, storyboard, and human-review status are inspectable together.

## Confidence benchmark

Run the benchmark after the baseline when you need a machine-checkable pass/fail summary:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_confidence_benchmark.py
```

The benchmark verifies the final video, quality report, release checkpoint, thumbnail, storyboard frames, Video Receipt, and pending human-review status.

For adversarial readiness checks:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_adversarial_certification.py
```
