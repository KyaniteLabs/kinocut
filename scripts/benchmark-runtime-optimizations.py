"""Compare deterministic optimization kernels with output-equivalent references."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import tempfile
import time
import tracemalloc
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def timed(function, repeats: int = 5) -> dict:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter() - start)
    return {"median_seconds": statistics.median(samples), "samples": samples}


def roster(size: int) -> tuple:
    signals = []
    for index in range(size):
        values = (int(10000 * math.sin(2 * math.pi * (100 + index * 23) * j / 16000)) for j in range(2048))
        pcm = struct.pack("<2048h", *values)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(pcm)
        signals.append((str(index), buffer.getvalue()))
    return tuple(signals)


def collision_experiment() -> list:
    from kinocut_sound.voice_consistency.distinctiveness import detect_collisions, spectral_distance

    results = []
    for size in (4, 8, 16):
        pairs = roster(size)

        def reference(pairs=pairs):
            return tuple(spectral_distance(a[1], b[1]) for i, a in enumerate(pairs) for b in pairs[i + 1 :])

        expected = reference()
        actual = detect_collisions(pairs)
        if actual.distances != expected:
            raise AssertionError("Collision distances changed")
        results.append(
            {
                "roster": size,
                "reference": timed(reference),
                "optimized": timed(lambda pairs=pairs: detect_collisions(pairs)),
                "report_sha256": hashlib.sha256(repr(actual).encode()).hexdigest(),
            }
        )
    return results


def color_experiment() -> dict:
    import numpy as np

    labels = np.random.default_rng(42).integers(0, 20, size=40000)

    def reference():
        counts = {}
        for label in labels:
            counts[int(label)] = counts.get(int(label), 0) + 1
        return counts

    def optimized():
        histogram = np.bincount(labels)
        return {label: int(histogram[label]) for label in dict.fromkeys(labels.tolist())}

    if list(reference().items()) != list(optimized().items()):
        raise AssertionError("Color counts or first-seen order changed")
    return {"labels": len(labels), "reference": timed(reference, 31), "optimized": timed(optimized, 31)}


def hash_experiment() -> dict:
    from kinocut.ai_engine.upscale import _verify_model_hash

    with tempfile.TemporaryDirectory(prefix="kinocut_hash_bench_") as directory:
        path = Path(directory) / "model.bin"
        digest = hashlib.sha256()
        chunk = bytes(1 << 20)
        with path.open("wb") as writer:
            for _ in range(64):
                writer.write(chunk)
                digest.update(chunk)
        expected = digest.hexdigest()

        def reference():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AssertionError("Reference checksum changed")

        result = {"file_bytes": path.stat().st_size, "expected_sha256": expected}
        for name, function in (("reference", reference), ("optimized", lambda: _verify_model_hash(path, expected))):
            tracemalloc.start()
            try:
                measurement = timed(function, 3)
                measurement["peak_python_bytes"] = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            result[name] = measurement
        return result


def wav_experiment() -> dict:
    from kinocut_sound.voice_consistency.distinctiveness import _parse_wav

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48000)
        writer.writeframes(bytes(2 * (1 << 20)))
    payload = buffer.getvalue()
    expected, rate = _parse_wav(payload)
    offset = payload.find(b"data") + 8

    def reference():
        return tuple(struct.unpack_from("<h", payload, offset + i * 2)[0] for i in range(len(expected)))

    if reference() != expected:
        raise AssertionError("WAV samples changed")
    return {
        "samples": len(expected),
        "sample_rate": rate,
        "reference": timed(reference),
        "optimized": timed(lambda: _parse_wav(payload)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "method": "Local synthetic CPU microbenchmarks; references check exact outputs; not end-to-end model speedups.",
        "collision": collision_experiment(),
        "color_count": color_experiment(),
        "hash": hash_experiment(),
        "wav_parse": wav_experiment(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Measurements written to {args.output}")


if __name__ == "__main__":
    main()
