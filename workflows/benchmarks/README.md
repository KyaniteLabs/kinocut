# Workflow Benchmarks

Local confidence checks for Kinocut workflows.

## Confidence Benchmark

Run the receipt-backed baseline and verify the expected trust artifacts:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_confidence_benchmark.py
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

## Adversarial Certification

Run a small local certification suite over adversarial media fixtures:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_adversarial_certification.py
```

The certification covers quiet audio warnings, path handling with spaces, odd frame-rate resize, and corrupted-input failure behavior. It writes `workflows/benchmarks/output/adversarial-certification-latest.json`.
