"""filter noise_reduction must clean a recorded voice without muffling it."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from kinocut.engine_filters import apply_filter

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

_HIGHS = "highpass=f=5000,highpass=f=5000,"


def _rms(path, chain: str = "") -> float:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"{chain}astats=measure_perchannel=none",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    report = completed.stderr
    return float(re.search(r"RMS level dB: (-?[\d.]+)", report).group(1))


def _brightness(path) -> float:
    return _rms(path, _HIGHS) - _rms(path)


def test_default_keeps_the_highs_of_a_bright_voice(tmp_path):
    # A bright, voice-like tone over a quiet room noise (-50 dB), as from a laptop microphone.
    clip = tmp_path / "voice.mp4"
    voice = r"aevalsrc='0.2*(2*mod(180*t\,1)-1)*(0.6+0.4*sin(2*PI*3*t))':s=48000:d=3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=160x90:r=25",
            "-f",
            "lavfi",
            "-i",
            voice,
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=white:amplitude=0.003:sample_rate=48000:seed=42",
            "-filter_complex",
            "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(tmp_path / "voice.mkv"),
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(tmp_path / "voice.mkv"),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            str(clip),
        ],
        check=True,
        timeout=120,
    )
    cleaned = apply_filter(str(clip), filter_type="noise_reduction", output_path=str(tmp_path / "clean.mp4"))
    kept, before = _brightness(cleaned.output_path), _brightness(clip)
    assert kept > before - 2, (kept, before)
    strong = apply_filter(
        str(clip), filter_type="noise_reduction", params={"noise_level": -25}, output_path=str(tmp_path / "strong.mp4")
    )
    assert kept > _brightness(strong.output_path) + 2
    explicit = apply_filter(
        str(clip),
        filter_type="noise_reduction",
        params={"noise_level": -50},
        output_path=str(tmp_path / "explicit.mp4"),
    )
    assert _brightness(explicit.output_path) == pytest.approx(kept, abs=0.01)
