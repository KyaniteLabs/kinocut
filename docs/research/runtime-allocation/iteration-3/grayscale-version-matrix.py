# ruff: noqa: S101
"""Executable research assertions; run from the repo root with PYTHONPATH=."""

import argparse
import shutil
import tempfile
import json
import os
from pathlib import Path
from tests.test_quality_signalstats_bitdepth import _fixture_video
from kinocut.quality_guardrails import VisualQualityGuardrails

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ffprobe6", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg or not args.ffprobe6.is_file():
    parser.error("An installed FFmpeg and prepared FFprobe 6.1 binary are required")
original_path = os.environ["PATH"]
rows = []
with tempfile.TemporaryDirectory(prefix="gray-runtime-") as folder:
    root = Path(folder)
    binaries = root / "bin"
    binaries.mkdir()
    (binaries / "ffprobe").symlink_to(args.ffprobe6.resolve())
    (binaries / "ffmpeg").symlink_to(ffmpeg)
    fixtures = {
        (base, depth, rng, True): _fixture_video(root, base, depth, rng)
        for base in ("gray", "yuv420p", "yuv422p", "yuv444p")
        for depth in (8, 10, 12, 16)
        for rng in ("tv", "pc")
    }
    fixtures.update(
        {
            ("gray", depth, rng, False): _fixture_video(root, "gray", depth, rng, moving=False)
            for depth in (8, 10, 12, 16)
            for rng in ("tv", "pc")
        }
    )
    fixtures.update(
        {
            ("yuv444p", depth, "tv", False): _fixture_video(root, "yuv444p", depth, "tv", moving=False)
            for depth in (8, 10, 12, 16)
        }
    )
    # 48 actual encoded sources:32 moving plus12 static and4 extra422static.
    fixtures.update(
        {
            ("yuv422p", depth, "tv", False): _fixture_video(root, "yuv422p", depth, "tv", moving=False)
            for depth in (8, 10, 12, 16)
        }
    )
    for key, source in fixtures.items():
        measurements = []
        for version, prefix in ((6, str(binaries) + os.pathsep), (7, "")):
            os.environ["PATH"] = prefix + original_path
            g = VisualQualityGuardrails()
            stats = g._get_all_signalstats(source)
            assert stats, key
            individual = g._run_ffprobe(source, "lavfi.signalstats.YAVG")
            fallback = g._run_ffmpeg_signalstats(source)
            motion = g._measure_temporal_motion(source)
            assert abs(individual["mean"] - stats["lavfi.signalstats.YAVG"]) < 0.001, (key, version, individual, stats)
            assert abs(fallback["yavg"] - stats["lavfi.signalstats.YAVG"]) < 0.6, (key, version, fallback, stats)
            if key[0] == "gray" and key[3]:
                assert abs(stats["lavfi.signalstats.YMIN"] - (16 + 43 * 219 / 255)) < 0.2, (key, version, stats)
                assert abs(motion["mean"] - 2 * 219 / 255) < 0.2, (key, version, motion)
            if not key[3]:
                assert abs(motion["mean"]) < 0.01 and motion["static_fraction"] == 1, (key, version, motion)
            measurements.append(
                {"version": version, "stats": stats, "individual": individual, "fallback": fallback, "motion": motion}
            )
        diffs = {
            tag: abs(measurements[0]["stats"][tag] - measurements[1]["stats"][tag]) for tag in measurements[0]["stats"]
        }
        assert max(diffs.values()) < (1.0 if key[0] == "gray" else 0.001), (key, diffs)
        rows.append({"fixture": key, "measurements": measurements, "cross_version_max_diff": max(diffs.values())})
        print("PASS", key, flush=True)
os.environ["PATH"] = original_path
args.output.write_text(json.dumps(rows, indent=2) + "\n")
print("PASS", len(rows), "fixtures,96measurementsets")
