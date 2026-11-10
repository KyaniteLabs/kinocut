# Router evaluation harness

Scores operation routing for the kinocut family surface (204 operations across 8 family dispatchers). It ships two deterministic baselines and one optional model treatment. **No model is required** for the baselines or the tests.

## What is scored

| Arm | Definition |
| --- | --- |
| R1 | The shipped `kinocut.tool_discovery.discover_tools(query, discovery_catalog())` ordering; top-1 is the first result. |
| R2 | BM25 over `name + verb + family + description` from the registry, `k1=1.2`, `b=0.75`; tokens `[a-z0-9]+` lowercased; ties broken by ascending operation name. |
| Treatment | R2 top-5 become the choice criteria. One `POST /v1/systemone` asks d1-2B to pick one operation or `unsure`. |

The treatment body is `{"model": "d1-2b", "state": "User request: <request>\nContext: <context or none>", "questions": {"operation": {"type": "choice", "instructions": ..., "criteria": {...}}}}`.

A typed `choice` wins; if the reply carries probabilities but no valid choice, the argmax is used. `unsure`, a malformed reply, an HTTP error or a timeout falls back to the R2 top-1 and records `degraded: true`. The harness never calls a model in `--rules-only` mode.

## The set stays private

Real user requests are user content and are not committed here. The frozen JSONL set, its `MANIFEST.json` and the measured `baseline.json` live outside the repository. This directory ships only code and tests; the tests build their own tiny fixtures. The set schema is:

```json
{"id": "...", "request": "...", "context": null, "gold_operation": "...", "gold_family": "...",
 "mutates_media": true, "source": "...", "source_ref": "...", "labeler": "...", "notes": "..."}
```

`gold_operation` must exist in the registry at the pinned commit; `gold_family` must match the registry's family for that operation.

## Usage

Run from the repository root so `tools.router_eval` and `kinocut` are importable.

```bash
# Baselines only (CI-safe; no endpoint, no model)
python -m tools.router_eval.run_eval --set /path/to/dataset-v1.jsonl --rules-only --out /path/to/results.jsonl

# Treatment against a live /v1/systemone base URL
python -m tools.router_eval.run_eval --set /path/to/dataset-v1.jsonl \
  --endpoint http://127.0.0.1:46406 --limit 5 --out /path/to/results.jsonl

# Deterministic in-process fake endpoint (end-to-end plumbing check)
python -m tools.router_eval.run_eval --set /path/to/dataset-v1.jsonl --fake-endpoint --limit 3
```

`--out` writes one JSON object per item and `<out>.summary.json` beside it. Each record carries `r1_top1`, `r1_top5`, `r2_top1`, `r2_top5`, `candidates`, `picked`, `probabilities`, `wall_ms`, `degraded` and `mode`.

The manifest utility records the set hash, the prompt-template hash and the harness commit:

```bash
python -m tools.router_eval.manifest --set /path/to/dataset-v1.jsonl \
  --commit <harness-commit> --catalog-commit <kinocut-commit> --out /path/to/MANIFEST.json
```

## Prompt-template fingerprint

`tools.router_eval.prompt.template_fingerprint()` hashes the canonical prompt specification (version, state format, instructions, `unsure` text, choice type, candidate source). `tests/test_router_eval.py` pins the current value; changing a prompt literal without updating the test is a test failure, which is deliberate: the template is part of the protocol.

## Tests

```bash
python -m pytest tests/test_router_eval.py -q
```

The suite covers JSONL schema rejection, prompt fingerprint stability, the endpoint-down fallback, the fake-endpoint parser on three items, and the rules-only summary shape.

## Measured baselines for set v1 (100 items, kinocut 1171c213)

- R1: top-1 3/100, oracle@5 3/100, p50 4.4 ms.
- R2: top-1 63/100, oracle@5 78/100, p50 0.8 ms.

**Read the provenance before quoting these.** 90 of the 100 items are synthetic asks rewritten from the operation docs; on the 10 real asks in the set, R2 top-1 was 1/10 (1/9 Hermes-session, 0/1 Claude-transcript). The synthetic majority is lexically aligned with the docs, so the overall R2 number measures lexical overlap, not real-world routing. Use the set as a regression and plumbing instrument; do not present its top-1 as a product estimate. Any model-arm number must carry the same caveat.
