# Workflow Benchmarks

Local confidence checks for mcp-video workflows.

## Confidence Benchmark

Run the receipt-backed baseline and verify the expected trust artifacts:

```bash
uv run --no-project --with mcp-video python workflows/benchmarks/run_confidence_benchmark.py
```

The benchmark checks:

- final video exists
- quality report exists
- release checkpoint exists
- thumbnail exists
- storyboard frames exist
- Video Receipt exists
- quality passed
- human review remains required and pending

Generated benchmark output lands in `workflows/benchmarks/output/` and is ignored by git.
