# Workflows — Routing Table

## Which workflow should I use?

| Goal | Workflow | Stages | Typical Duration |
|---|---|---|---|
| Turn a long video into a TikTok / Short / Reel | `01-social-media-clip` | 5 | 2-5 min |
| Extract a podcast highlight with chapters and captions | `02-podcast-clip` | 6 | 5-10 min |
| Build a branded explainer video from scratch | `03-explainer-video` | 10 | 30-60 min |
| Create a video with Hyperframes, then post-process | `04-hyperframes-video` | 5 | 10-20 min |
| Prove Kinocut can create a checked output without private media | `05-confidence-baseline` | 8 | 1-3 min |
| Create a platform-ready repurposing package with review artifacts | `06-repurpose-package` | 5 | 2-5 min |
| Verify the confidence baseline produced its trust artifacts | `benchmarks/run_confidence_benchmark.py` | pass/fail checks | 1-3 min |

## How to run a workflow

1. `cd workflows/01-social-media-clip`
2. Read `CONTEXT.md` for the stage contract
3. Run `python workflow.py` (or follow the agent prompts in `references/`)
4. Review output at each stage before proceeding
5. Final artifact lands in `output/`

## Workflow structure

Each workflow follows ICM conventions:

- `CONTEXT.md` — Stage contract (Inputs, Process, Outputs)
- `references/` — Factory configuration (platform specs, style guides)
- `output/` — Working artifacts (generated at each stage)
- `workflow.py` — Runnable Python script using the Kinocut client

Benchmark scripts live in `workflows/benchmarks/` and write ignored JSON reports to `workflows/benchmarks/output/`.
