"""Comprehensive real-media regression tests for Kinocut 2.1.0 Audit Wave 2 fixes.

Covers every P0 (P0-13 through P0-17) and P1 finding remediated in Wave 2 using
real FFmpeg/FFprobe execution on synthesized temporary media.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import struct
import subprocess
import wave
from array import array
from pathlib import Path

import pytest
from PIL import Image

from kinocut.aivideo.subtitle_qa import subtitle_qa
from kinocut.audio_sync.audition import build_ab_audition
from kinocut.engine_advanced_mask import luma_key, shape_mask
from kinocut.engine_chroma_key import chroma_key
from kinocut.engine_edit import trim
from kinocut.engine_filters import _build_pitch_shift_filter, apply_filter
from kinocut.engine_mask import apply_mask
from kinocut.engine_merge import merge
from kinocut.engine_probe import probe, probe_exact
from kinocut.engine_resize import resize
from kinocut.engine_speed import speed
from kinocut.engine_split_screen import split_screen
from kinocut.errors import MCPVideoError
from kinocut.merge_guardrails import validate_merge_compatibility
from kinocut.models import VideoInfo
from kinocut.music_grid import (
    MusicalGrid,
    estimate_bpm_from_audio,
    lint_composition_keyframes,
    place_rhythm_cell,
    quantize_real_timestamps,
)
from kinocut.quality_guardrails import quality_check
from kinocut.shot_cache import ShotSpec, concat, render_shot_plan
from kinocut.te.punch_zoom import plan_punch_zooms
from kinocut import tv_preview
from kinocut.tv_preview import consume_tv_review_decision, prepare_tv_review_payload
from kinocut.visual_intelligence import (
    CameraMotion,
    CropBudget,
    CropTarget,
    FrameEvidence,
    NormalizedBox,
    SafeRegion,
    SourceVideo,
    SpeakerTurn,
    SubjectObservation,
    plan_subject_aware_reframe,
    plan_visual_analysis,
    render_reframe_plan,
)
from kinocut.watching.metrics import run_metric_qc
from kinocut_sound.delivery import StemLayout
from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.mix.bus_sends import BusSendGraph
from kinocut_sound.mix.ducking import duck_bed_under_speech
from kinocut_sound.mix.layers import MixLayer, apply_layers
from kinocut_sound.mix.renderer import MixClip, MixRenderer
from kinocut_sound.mix.stems import build_stem_bundle, recombine_stems
from kinocut_sound.post._subprocess import insert_protocol_whitelist, resolve_binary
from kinocut_sound.public import dub_spatial, master_job
from kinocut_sound.public.master_job import render_master_request
from kinocut_sound.routing import Bus, SendReturn
from kinocut_sound.timeline import Cue, Timeline
from kinocut_sound.world.layers import AmbientLayer


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"Command failed: {cmd}\n{proc.stderr}"
    return proc


def _ffprobe_streams(path: str | Path) -> list[dict]:
    out = _run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]).stdout
    return json.loads(out)["streams"]


def _extract_first_frame_rgba(path: str | Path, out_png: Path) -> Image.Image:
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-frames:v", "1", "-pix_fmt", "rgba", str(out_png)])
    return Image.open(out_png).convert("RGBA")


def _make_base_clip(path: Path, *, size: str = "320x180", fps: int = 24, duration: float = 2.0) -> Path:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={size}:r={fps}:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:r=48000:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def _make_odd_clip(path: Path) -> Path:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=321x181:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def _make_anamorphic_clip(path: Path) -> Path:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x360:r=24:d=1,setsar=2/1",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def _make_two_audio_clip(path: Path) -> Path:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=f=880:r=48000:d=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "2:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


# ---------------------------------------------------------------------------
# 1. P0-13 + P0-14 + C3-003: No intermediate PCM16 clamping in kinocut_sound
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channels", [1, 2])
def test_p0_13_recombine_stems_order_independent_no_intermediate_clamp(channels: int) -> None:
    vals = {"a": 30000, "b": 20000, "c": -20000}
    wavs = {
        k: pcm_to_wav(array("h", [v] * channels), sample_rate_hz=48000, channel_count=channels) for k, v in vals.items()
    }
    for order in itertools.permutations(("a", "b", "c")):
        layout = StemLayout(stem_ids=order)
        ordered_wavs = {k: wavs[k] for k in order}
        master = recombine_stems(build_stem_bundle(layout=layout, stem_wavs=ordered_wavs))
        samples, rate, ch = decode_pcm_wav(master)
        assert rate == 48000 and ch == channels
        assert list(samples) == [30000] * channels


def test_p0_13_recombine_stems_rejects_mono_length_mismatch() -> None:
    layout = StemLayout(stem_ids=("a", "b"))
    wavs = {
        "a": pcm_to_wav(array("h", [1000, 2000]), sample_rate_hz=48000),
        "b": pcm_to_wav(array("h", [1000]), sample_rate_hz=48000),
    }
    with pytest.raises(MixError):
        build_stem_bundle(layout=layout, stem_wavs=wavs)


def test_p0_14_bus_sends_and_renderer_and_layers_accumulate_unclipped() -> None:
    # BusSendGraph: bus fader attenuation applies BEFORE final PCM16 clamping
    buses = (
        Bus(bus_id="dialogue", kind="dialogue", gain_db=0.0),
        Bus(bus_id="ambience", kind="ambience", gain_db=-6.020599913279624),
        Bus(bus_id="sfx", kind="sfx", gain_db=0.0),
    )
    sends = (
        SendReturn(send_id="s1", source_bus_id="dialogue", destination_bus_id="ambience", gain_db=0.0, post_fader=True),
    )
    canvases = {"dialogue": array("h", [20000]), "ambience": array("h", [30000]), "sfx": array("h", [0])}
    BusSendGraph(buses, sends, 1, 1).process_buses(canvases)
    # Unclipped sum is 30000 + 20000 = 50000; attenuated by 0.5 => exact 25000 (not 16384!)
    assert canvases["ambience"][0] == 25000

    # MixRenderer: clip + bed + ambient layer on the same stem accumulate without intermediate clamping
    rate = 22050
    frame_dur = 4 / rate
    timeline = Timeline(
        cues=(Cue(cue_id="c1", kind="line", source_ref="c1.wav", start_seconds=0.0, duration_seconds=frame_dur),)
    )
    clips = (MixClip("c1", pcm_to_wav(array("h", [30000] * 4), sample_rate_hz=rate), "ambience"),)
    bed_wav = pcm_to_wav(array("h", [20000] * 4), sample_rate_hz=rate)
    neg_layer = (
        MixLayer(
            AmbientLayer(layer_id="neg", asset_ref="neg", gain_db=0.0),
            pcm_to_wav(array("h", [-20000] * 4), sample_rate_hz=rate),
            "pad",
            None,
        ),
    )
    result = MixRenderer(sample_rate_hz=rate).render(timeline=timeline, clips=clips, bed_wav=bed_wav, layers=neg_layer)
    assert list(decode_pcm_wav(result.master_wav)[0]) == [30000] * 4

    # apply_layers: multiple layers accumulate in float64 without order-dependent clipping
    amb_canvas = {"ambience": array("h", [30000] * 4)}
    layers = (
        MixLayer(
            AmbientLayer(layer_id="l1", asset_ref="a", gain_db=0.0),
            pcm_to_wav(array("h", [20000] * 4), sample_rate_hz=rate),
            "pad",
            None,
        ),
        MixLayer(
            AmbientLayer(layer_id="l2", asset_ref="b", gain_db=0.0),
            pcm_to_wav(array("h", [-20000] * 4), sample_rate_hz=rate),
            "pad",
            None,
        ),
    )
    apply_layers(amb_canvas, layers, rate, 1)
    assert list(amb_canvas["ambience"]) == [30000] * 4


def test_c3_003_ducking_uses_unbiased_rounding() -> None:
    speech = pcm_to_wav(array("h", [0] * 100), sample_rate_hz=8000)
    bed = pcm_to_wav(array("h", [-1001] * 100), sample_rate_hz=8000)
    out, _, _ = decode_pcm_wav(duck_bed_under_speech(speech, bed))
    assert out[0] == -1001


# ---------------------------------------------------------------------------
# 2. C3-023 + C2-012: kinocut_sound master rate conversion & protocol whitelist
# ---------------------------------------------------------------------------


def test_c3_023_c2_012_master_rate_conversion_and_protocol_whitelist(tmp_path: Path, monkeypatch) -> None:
    # Protocol whitelist helper inserts before every -i
    cmd = insert_protocol_whitelist(["-i", "in.wav", "-f", "null", "-"])
    assert cmd[:4] == ["-protocol_whitelist", "file,pipe", "-i", "in.wav"]
    assert "-protocol_whitelist" in dub_spatial._args("/usr/bin/ffmpeg")

    # KINOCUT_FFMPEG_EXECUTABLE override is honored
    real_ffmpeg = resolve_binary("ffmpeg")
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", real_ffmpeg)
    assert resolve_binary("ffmpeg") == real_ffmpeg
    assert dub_spatial._binary() == real_ffmpeg

    # Real master job with 44100 Hz -> 48000 Hz rate conversion succeeds without frame-count failure
    rate = 44100
    n = rate * 4  # 4 seconds (meter requires >= 3s non-silent material)
    tone = array("h", (round(32767 * 0.15 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))
    src_bytes = pcm_to_wav(tone, sample_rate_hz=rate)
    src_path = tmp_path / "src.wav"
    src_path.write_bytes(src_bytes)
    sha = "sha256:" + hashlib.sha256(src_bytes).hexdigest()
    payload = {
        "schema_version": 1,
        "source": {"path": "src.wav", "sha256": sha},
        "output_path": "mastered.zip",
        "output_sample_rate_hz": 48000,
    }
    res = render_master_request(payload, str(tmp_path))
    assert res["output_path"] == "mastered.zip"
    assert (tmp_path / "mastered.zip").is_file()
    assert (
        "-protocol_whitelist"
        in master_job._MasterJob(
            None, real_ffmpeg, src_path, tmp_path / "m.wav", 0, 0, "x", 0, "s", 0.0, 1, 1, 1, 1, 1, 1
        ).base
    )


# ---------------------------------------------------------------------------
# 3. P0-15 + C1-022: shot_cache FFmpeg 7.1.1 trim, warmup, odd dims, self-heal
# ---------------------------------------------------------------------------


def test_p0_15_c1_022_shot_cache_real_24fps_warmup_odd_and_stray_self_heal(tmp_path: Path, monkeypatch) -> None:
    base = _make_base_clip(tmp_path / "base.mp4", fps=24, duration=2.0)
    cache_dir = tmp_path / "cache"

    # Real 24fps H.264 clip trim succeeds end-to-end
    shot = ShotSpec("s1", source_path=base, start_frame=1, frame_count=10)
    receipt = render_shot_plan([shot], tmp_path / "out.mp4", cache_dir)
    assert receipt["rebuilt"] == ["s1"]
    assert receipt["total_frames"] == 10

    # Warmup frames honored cleanly with exact output frame count
    warmup_shot = ShotSpec("s2", source_path=base, start_frame=5, frame_count=8, warmup_frames=3)
    w_receipt = render_shot_plan([warmup_shot], tmp_path / "out_warmup.mp4", cache_dir)
    assert w_receipt["total_frames"] == 8

    # Odd-dim source clip renders cleanly with even dimensions
    odd = _make_odd_clip(tmp_path / "odd.mkv")
    odd_receipt = render_shot_plan(
        [ShotSpec("odd", source_path=odd, start_frame=0, frame_count=6)], tmp_path / "odd_out.mp4", cache_dir
    )
    assert odd_receipt["total_frames"] == 6
    odd_info = probe(str(tmp_path / "odd_out.mp4"))
    assert odd_info.width % 2 == 0 and odd_info.height % 2 == 0

    # C1-022: Corrupted cache entry with stray files self-heals cleanly
    entry_dir = cache_dir / receipt["digests"]["s1"]
    (entry_dir / "stray_garbage.tmp").write_bytes(b"stray")
    (entry_dir / "media" / "clip.mp4").write_bytes(b"corrupted")
    healed = render_shot_plan([shot], tmp_path / "healed.mp4", cache_dir)
    assert healed["rebuilt"] == ["s1"]
    assert healed["total_frames"] == 10
    assert not (entry_dir / "stray_garbage.tmp").exists()

    # concat._probe tolerates benign stderr warnings when rc == 0
    real_run_bounded = concat.run_bounded

    def noisy_probe(argv, **kwargs):
        proc = real_run_bounded(argv, **kwargs)
        return subprocess.CompletedProcess(proc.args, proc.returncode, proc.stdout, "benign ffprobe warning\n")

    monkeypatch.setattr(concat, "run_bounded", noisy_probe)
    assert concat.verify_concat_compatibility([tmp_path / "out.mp4"], [10]) == 10


# ---------------------------------------------------------------------------
# 4. C3-015: VideoInfo SAR, audio_channels, audio_stream_count, pix_fmt, VFR
# ---------------------------------------------------------------------------


def test_c3_015_video_info_probe_sar_and_extended_fields(tmp_path: Path) -> None:
    anamorphic = _make_anamorphic_clip(tmp_path / "anamorphic.mp4")
    info = probe(str(anamorphic))
    assert info.sample_aspect_ratio == "2:1"
    assert info.display_width == 640
    assert info.display_height == 360
    assert info.display_resolution == "640x360"
    assert info.aspect_ratio == "16:9"
    assert info.pix_fmt == "yuv420p"
    assert info.audio_channels is not None and info.audio_channels >= 1
    assert info.audio_stream_count == 1
    assert info.avg_frame_rate is not None

    # probe_exact does not collide on avg_frame_rate
    exact = probe_exact(str(anamorphic))
    assert exact.frame_count == 24
    assert exact.sample_aspect_ratio == "2:1"

    two_audio = _make_two_audio_clip(tmp_path / "two_audio.mp4")
    assert probe(str(two_audio)).audio_stream_count == 2


# ---------------------------------------------------------------------------
# 5. P0-16 + D2-004: Merge rotation, SAR, odd dims, xfade timebase, VP9 silent
# ---------------------------------------------------------------------------


def test_p0_16_d2_004_merge_rotation_odd_sar_xfade_and_vp9(tmp_path: Path) -> None:
    base = _make_base_clip(tmp_path / "base.mp4", size="320x180", fps=24, duration=1.5)
    rot90 = tmp_path / "rot90.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", str(base), "-c", "copy", str(rot90)])
    rot_neg90 = tmp_path / "rot_neg90.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "-90", "-i", str(base), "-c", "copy", str(rot_neg90)])

    # Merge +90 and -90 rotated portrait clips: output must be upright 180x320 (NOT double-rotated!)
    merged_rot = merge([str(rot90), str(rot_neg90)], output_path=str(tmp_path / "merged_rot.mp4"))
    rot_out_info = probe(merged_rot.output_path)
    assert rot_out_info.display_width == 180 and rot_out_info.display_height == 320
    assert rot_out_info.normalized_rotation == 0

    # Odd dimensions merge succeeds cleanly with even dimensions
    odd = _make_odd_clip(tmp_path / "odd.mkv")
    merged_odd = merge([str(odd), str(odd)], output_path=str(tmp_path / "merged_odd.mp4"))
    odd_out = probe(merged_odd.output_path)
    assert odd_out.width % 2 == 0 and odd_out.height % 2 == 0

    # D2-004: xfade between clips with mismatched timebases (1/15360 vs 1/90000) succeeds
    tb1 = tmp_path / "tb1.mp4"
    tb2 = tmp_path / "tb2.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=1.5",
            "-video_track_timescale",
            "15360",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(tb1),
        ]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=f=660:d=1.5",
            "-video_track_timescale",
            "90000",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(tb2),
        ]
    )
    xfade_out = merge(
        [str(tb1), str(tb2)], output_path=str(tmp_path / "xfade.mp4"), transition="fade", transition_duration=0.4
    )
    assert probe(xfade_out.output_path).duration == pytest.approx(2.6, abs=0.25)

    # _add_silent_audio does not -c:v copy VP9 into .mp4
    vp9_no_audio = tmp_path / "vp9.webm"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1",
            "-c:v",
            "libvpx-vp9",
            "-an",
            str(vp9_no_audio),
        ]
    )
    mixed_vp9 = merge([str(vp9_no_audio), str(base)], output_path=str(tmp_path / "mixed_vp9.mp4"))
    assert probe(mixed_vp9.output_path).duration > 2.0

    # merge_guardrails aligns with display geometry (rotated 320x180 vs upright 180x320 -> no mismatch)
    i1 = VideoInfo(path="a.mp4", duration=2.0, width=320, height=180, fps=24.0, codec="h264", rotation=90)
    i2 = VideoInfo(path="b.mp4", duration=2.0, width=180, height=320, fps=24.0, codec="h264", rotation=0)
    assert not any("different resolutions" in w for w in validate_merge_compatibility([i1, i2]))


# ---------------------------------------------------------------------------
# 6. P0-17 + C3-008: luma_key, apply_mask, chroma_key, shape_mask
# ---------------------------------------------------------------------------


def test_p0_17_c3_008_luma_key_apply_mask_chroma_key_and_shape_mask(tmp_path: Path) -> None:
    # Split frame: left half black, right half white
    bw = tmp_path / "bw.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x64:r=10:d=0.5",
            "-filter_complex",
            "[0:v][1:v]hstack=inputs=2[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(bw),
        ]
    )

    # luma_key rejects invalid thresholds
    for bad in (-0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(MCPVideoError):
            luma_key(str(bw), threshold=bad, output_path=str(tmp_path / "bad.mov"))

    # luma_key .mov produces real alpha transparency on dark half and opacity on white half
    lk_mov = luma_key(str(bw), threshold=0.5, output_path=str(tmp_path / "lk.mov"))
    lk_img = _extract_first_frame_rgba(lk_mov.output_path, tmp_path / "lk_frame.png")
    assert lk_img.getpixel((16, 32))[3] < 20  # black side keyed transparent
    assert lk_img.getpixel((96, 32))[3] > 235  # white side stays opaque
    assert _ffprobe_streams(lk_mov.output_path)[0]["pix_fmt"] == "yuva444p12le"

    # apply_mask: red video with half-black / half-white PNG mask
    red = tmp_path / "red.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=128x64:r=10:d=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(red),
        ]
    )
    mask_png = tmp_path / "half_mask.png"
    mask_img = Image.new("L", (128, 64), 0)
    mask_img.paste(255, (64, 0, 128, 64))
    mask_img.save(mask_png)

    # .mp4 output composites masked-out left half to black, keeps right half red
    masked_mp4 = apply_mask(str(red), str(mask_png), feather=0, output_path=str(tmp_path / "masked.mp4"))
    mp4_frame = _extract_first_frame_rgba(masked_mp4.output_path, tmp_path / "masked_mp4.png")
    assert mp4_frame.getpixel((16, 32))[0] < 30  # masked out -> black
    assert mp4_frame.getpixel((96, 32))[0] > 180  # unmasked -> red

    # .mov output preserves alpha channel
    masked_mov = apply_mask(str(red), str(mask_png), feather=0, output_path=str(tmp_path / "masked.mov"))
    mov_frame = _extract_first_frame_rgba(masked_mov.output_path, tmp_path / "masked_mov.png")
    assert mov_frame.getpixel((16, 32))[3] < 20
    assert mov_frame.getpixel((96, 32))[3] > 235

    # chroma_key: green left, blue right
    gb = tmp_path / "gb.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x00FF00:s=64x64:r=10:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0000FF:s=64x64:r=10:d=0.5",
            "-filter_complex",
            "[0:v][1:v]hstack=inputs=2[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(gb),
        ]
    )
    ck_mov = chroma_key(str(gb), color="0x00FF00", similarity=0.3, output_path=str(tmp_path / "ck.mov"))
    ck_mov_img = _extract_first_frame_rgba(ck_mov.output_path, tmp_path / "ck_mov.png")
    assert ck_mov_img.getpixel((16, 32))[3] < 20  # green keyed transparent
    assert ck_mov_img.getpixel((96, 32))[3] > 235  # blue opaque

    ck_mp4 = chroma_key(str(gb), color="0x00FF00", similarity=0.3, output_path=str(tmp_path / "ck.mp4"))
    ck_mp4_img = _extract_first_frame_rgba(ck_mp4.output_path, tmp_path / "ck_mp4.png")
    assert ck_mp4_img.getpixel((16, 32))[1] < 30  # green keyed and composited to black!
    assert ck_mp4_img.getpixel((96, 32))[2] > 180  # blue preserved

    # shape_mask on rotated 90° clip uses display dimensions
    rot_red = tmp_path / "rot_red.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", str(red), "-c", "copy", str(rot_red)])
    sm = shape_mask(str(rot_red), shape="circle", output_path=str(tmp_path / "shape.mp4"))
    sm_info = probe(sm.output_path)
    assert sm_info.display_width == 64 and sm_info.display_height == 128


# ---------------------------------------------------------------------------
# 7. C3-011 + D2-005 + D2-006 + C3-005 + C3-016 + C3-019
# ---------------------------------------------------------------------------


def test_c3_011_d2_005_d2_006_c3_005_c3_019_engines(tmp_path: Path) -> None:
    base = _make_base_clip(tmp_path / "base48k.mp4", fps=24, duration=2.0)

    # C3-011: pitch_shift(0) is no-op and does not stretch 48 kHz clip
    assert _build_pitch_shift_filter(0, sample_rate=48000) == "anull"
    assert "48000" in _build_pitch_shift_filter(2, sample_rate=48000)
    ps0 = apply_filter(str(base), "pitch_shift", {"semitones": 0}, output_path=str(tmp_path / "ps0.mp4"))
    assert ps0.duration == pytest.approx(2.0, abs=0.15)

    # C3-011: ken_burns on 2s video stays ~2s (not 250s!)
    kb = apply_filter(str(base), "ken_burns", {}, output_path=str(tmp_path / "kb.mp4"))
    assert kb.duration == pytest.approx(2.0, abs=0.3)

    # D2-005 / C3-016: resize fit_mode="pad" normalizes anamorphic SAR to 1:1
    anamorphic = _make_anamorphic_clip(tmp_path / "anam.mp4")
    r_pad = resize(str(anamorphic), width=640, height=360, fit_mode="pad", output_path=str(tmp_path / "pad.mp4"))
    pad_stream = _ffprobe_streams(r_pad.output_path)[0]
    assert (pad_stream["width"], pad_stream["height"]) == (640, 360)
    assert pad_stream.get("sample_aspect_ratio") == "1:1"

    # D2-006: split_screen handles odd-dim 321x181 inputs cleanly
    odd = _make_odd_clip(tmp_path / "odd.mkv")
    sp = split_screen(str(odd), str(odd), layout="side-by-side", output_path=str(tmp_path / "split_odd.mp4"))
    sp_info = probe(sp.output_path)
    assert sp_info.width % 2 == 0 and sp_info.height % 2 == 0

    # C3-005 & C3-019: trim and speed handle odd dims and preserve 2 audio tracks
    tr_odd = trim(str(odd), start=0, duration=0.5, output_path=str(tmp_path / "trim_odd.mp4"))
    assert probe(tr_odd.output_path).width % 2 == 0

    two_audio = _make_two_audio_clip(tmp_path / "two_audio.mp4")
    tr_two = trim(str(two_audio), start=0, duration=0.5, output_path=str(tmp_path / "trim_two.mp4"))
    assert probe(tr_two.output_path).audio_stream_count == 2

    spd_two = speed(str(two_audio), factor=2.0, output_path=str(tmp_path / "speed_two.mp4"))
    assert probe(spd_two.output_path).audio_stream_count == 2

    spd_odd = speed(str(odd), factor=2.0, output_path=str(tmp_path / "speed_odd.mp4"))
    assert probe(spd_odd.output_path).width % 2 == 0


# ---------------------------------------------------------------------------
# 8. D5-025 / C3-010: punch_zoom emits valid FFmpeg filter_hint
# ---------------------------------------------------------------------------


def test_d5_025_c3_010_punch_zoom_executes_in_ffmpeg_and_validates(tmp_path: Path) -> None:
    base = _make_base_clip(tmp_path / "base.mp4", size="320x180", fps=24, duration=1.0)
    plan = plan_punch_zooms([0.25], zoom=1.2, duration_seconds=0.35, fps=24, width=320, height=180)
    hint = plan["events"][0]["filter_hint"]
    assert "between(t," not in hint
    assert "s=320x180" in hint and "fps=24" in hint
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-vf", hint, "-f", "null", "-"])

    for bad_zoom in (float("nan"), float("inf"), 0.5, 2.5):
        with pytest.raises(MCPVideoError):
            plan_punch_zooms([0.5], zoom=bad_zoom)
    for bad_t in (-0.1, float("nan"), float("inf")):
        with pytest.raises(MCPVideoError):
            plan_punch_zooms([bad_t])


# ---------------------------------------------------------------------------
# 9. D6-001 + C3-013 + C3-017: dark-grade RGB, finite JSON, subtitle_qa profile
# ---------------------------------------------------------------------------


def test_d6_001_c3_013_c3_017_quality_metrics_and_subtitle_qa(tmp_path: Path) -> None:
    # D6-001: stylized dark-grade clip passes color_balance
    dark = tmp_path / "dark.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=#101c2c:s=320x180:r=24:d=1.5,noise=alls=10:allf=t",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=1.5,volume=-16dB",
            "-t",
            "1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(dark),
        ]
    )
    q_dark = quality_check(str(dark), profile="dark-grade")
    cb = next(c for c in q_dark["checks"] if c["name"] == "color_balance")
    assert cb["passed"] is True, cb

    # C3-013: silent audio produces strictly finite JSON in quality_check & run_metric_qc
    silent = tmp_path / "silent.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1.0",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=1.0",
            "-t",
            "1.0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(silent),
        ]
    )
    q_sil = quality_check(str(silent))
    json.dumps(q_sil, allow_nan=False)
    audio_chk = next(c for c in q_sil["checks"] if c["name"] == "audio_levels")
    assert audio_chk["details"]["lufs"] is None

    metric_findings = [f.to_dict() for f in run_metric_qc(str(silent))]
    json.dumps(metric_findings, allow_nan=False)

    # C3-017: subtitle_qa profile inference respects rotation and SAR
    base = _make_base_clip(tmp_path / "base.mp4", size="320x180", fps=24, duration=1.0)
    rot90 = tmp_path / "rot90.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", str(base), "-c", "copy", str(rot90)])
    anamorphic = _make_anamorphic_clip(tmp_path / "anamorphic.mp4")
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,900\nHello world\n", encoding="utf-8")
    assert subtitle_qa(str(rot90), str(srt), project_id="p1").profile_name == "vertical"
    assert subtitle_qa(str(anamorphic), str(srt), project_id="p1").profile_name == "horizontal"


# ---------------------------------------------------------------------------
# 10. D4-007 / C3-018: Reframe >100 crop samples & speaker safe_regions
# ---------------------------------------------------------------------------


def test_d4_007_c3_018_reframe_150_samples_and_speaker_safe_regions(tmp_path: Path) -> None:
    src = _make_base_clip(tmp_path / "src.mp4", size="320x180", fps=24, duration=2.0)
    sha = "sha256:" + hashlib.sha256(src.read_bytes()).hexdigest()
    # 150 distinct horizontal positions (previously crashed FFmpeg rc=234 at ~100!)
    n_samples = 150
    frames = tuple(
        FrameEvidence(
            timestamp_seconds=i * (2.0 / n_samples),
            subjects=(
                SubjectObservation(
                    subject_id="s1",
                    box=NormalizedBox(x=0.1 + 0.6 * (i / n_samples), y=0.25, width=0.15, height=0.5),
                    confidence=0.95,
                ),
            ),
            camera_motion=CameraMotion(dx=0, dy=0, rotation_degrees=0, confidence=1),
        )
        for i in range(n_samples)
    )
    analysis = plan_visual_analysis(
        source=SourceVideo(sha256=sha, width=320, height=180, duration_seconds=2.0),
        frames=frames,
        primary_subject_id="s1",
    )
    plan = plan_subject_aware_reframe(
        analysis=analysis,
        targets=(
            CropTarget(target_id="portrait", aspect_width=9, aspect_height=16, output_width=180, output_height=320),
        ),
        crop_budget=CropBudget(max_subject_loss=1.0, max_source_crop_fraction=0.95),
        max_center_step=1.0,
    )
    out = tmp_path / "reframed_150.mp4"
    receipt = render_reframe_plan(str(src), str(out), plan, "portrait")
    assert receipt.sample_count == n_samples
    out_stream = _ffprobe_streams(out)[0]
    assert (out_stream["width"], out_stream["height"]) == (180, 320)
    assert out_stream.get("sample_aspect_ratio") == "1:1"

    # C3-018: safe_regions looked up at primary timestamp across speaker switches
    frames_2 = (
        FrameEvidence(
            timestamp_seconds=0.0,
            subjects=(
                SubjectObservation(
                    subject_id="a", box=NormalizedBox(x=0.1, y=0.2, width=0.1, height=0.4), confidence=0.99
                ),
                SubjectObservation(
                    subject_id="b", box=NormalizedBox(x=0.8, y=0.2, width=0.1, height=0.4), confidence=0.90
                ),
            ),
            camera_motion=CameraMotion(dx=0, dy=0, rotation_degrees=0, confidence=1),
        ),
        FrameEvidence(
            timestamp_seconds=1.0,
            subjects=(
                SubjectObservation(
                    subject_id="a", box=NormalizedBox(x=0.1, y=0.2, width=0.1, height=0.4), confidence=0.99
                ),
            ),
            camera_motion=CameraMotion(dx=0, dy=0, rotation_degrees=0, confidence=1),
            safe_regions=(
                SafeRegion(
                    region_id="r1",
                    kind="text",
                    box=NormalizedBox(x=0.0, y=0.0, width=0.2, height=0.2),
                    confidence=0.95,
                ),
            ),
        ),
    )
    analysis_2 = plan_visual_analysis(
        source=SourceVideo(sha256=sha, width=320, height=180, duration_seconds=2.0),
        frames=frames_2,
        primary_subject_id="a",
    )
    plan_2 = plan_subject_aware_reframe(
        analysis=analysis_2,
        targets=(CropTarget(target_id="p", aspect_width=9, aspect_height=16, output_width=180, output_height=320),),
        crop_budget=CropBudget(max_subject_loss=1.0, max_source_crop_fraction=0.95),
        max_center_step=1.0,
        speaker_turns=(SpeakerTurn(subject_id="b", start_seconds=0.5, end_seconds=1.5, confidence=1.0),),
    )
    # At t=1.0 speaker b is active (nearest sample at t=0.0, x=0.8), so safe_region at x=0.0..0.2 is NOT covered!
    assert plan_2.variants[0].crop_track[1].safe_region_coverage == 0.0


# ---------------------------------------------------------------------------
# 11. D6-007 + D3-016 + C1-018: tv_preview codec/rotation transcode + disk TTL
# ---------------------------------------------------------------------------


def test_d6_007_d3_016_c1_018_tv_preview_transcode_and_persistence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KINOCUT_DATA_DIR", str(tmp_path / "state"))

    base = _make_base_clip(tmp_path / "base.mp4", size="320x180", fps=24, duration=1.0)
    # WebM VP9 must ALWAYS transcode to compliant H.264/AAC MP4 (never raw-copied WebM bytes!)
    webm = tmp_path / "clip.webm"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c:v", "libvpx-vp9", "-c:a", "libopus", str(webm)])
    tv_res = prepare_tv_review_payload(str(webm), proxy_output_path=str(tmp_path / "proxy.mp4"))
    proxy_bytes = Path(tv_res["proxy_path"]).read_bytes()
    assert proxy_bytes[4:8] == b"ftyp"  # Valid MP4 box, not WebM EBML 0x1a45dfa3!
    p_streams = _ffprobe_streams(tv_res["proxy_path"])
    assert p_streams[0]["codec_name"] == "h264"
    assert p_streams[0]["pix_fmt"] == "yuv420p"

    # Rotated 90° MP4 <=1080p must transcode and bake rotation
    rot90 = tmp_path / "rot90.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-display_rotation", "90", "-i", str(base), "-c", "copy", str(rot90)])
    tv_rot = prepare_tv_review_payload(str(rot90))
    assert tv_rot["proxy_path"] != str(rot90)
    assert probe(tv_rot["proxy_path"]).normalized_rotation == 0

    # C1-018: Simulated server restart clears RAM dict; persisted disk token still approves once!
    rid = tv_res["review_id"]
    with tv_preview._review_lock:
        tv_preview._pending_reviews.clear()
    approved = consume_tv_review_decision(rid, "APPROVE")
    assert approved == webm
    with pytest.raises(MCPVideoError) as replay_exc:
        consume_tv_review_decision(rid, "APPROVE")
    assert replay_exc.value.code == "unknown_tv_review"

    # D3-016: Expired review fails closed (never approves)
    monkeypatch.setattr(tv_preview, "_REVIEW_TTL_SECONDS", -1.0)
    expired_res = prepare_tv_review_payload(str(base))
    with pytest.raises(MCPVideoError) as exp_exc:
        consume_tv_review_decision(expired_res["review_id"], "APPROVE")
    assert exp_exc.value.code == "expired_tv_review"


# ---------------------------------------------------------------------------
# 12. C3-020 + C3-021 + C3-022: music_grid & audio_sync/audition
# ---------------------------------------------------------------------------


def test_c3_020_c3_021_c3_022_music_grid_and_audition(tmp_path: Path) -> None:
    # C3-020: 61s 120 BPM WAV does not exceed stdout_limit and estimates accurately
    wav_path = tmp_path / "click61.wav"
    with wave.open(str(wav_path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        beat = struct.pack("<h", 18000) * 80 + bytes(3920 * 2)  # 0.5s => 120 BPM
        audio.writeframes(beat * 122)  # 61 seconds
    assert estimate_bpm_from_audio(wav_path) == pytest.approx(120.0, abs=1.0)

    # C3-021: groove.py handles "1.5 s", lowercase ISO, and rejects span==0 with target_duration_s
    grid = MusicalGrid(120)
    g = quantize_real_timestamps(["1.5 s", "2.0 s"], grid)
    assert [e["source_time"] for e in g["events"]] == [1.5, 2.0]
    g_iso = quantize_real_timestamps(["1970-01-01t00:00:01z", "1970-01-01t00:00:02z"], grid)
    assert [e["source_time"] for e in g_iso["events"]] == [1.0, 2.0]
    with pytest.raises(ValueError, match="identical timestamps"):
        quantize_real_timestamps([1.0, 1.0], grid, target_duration_s=5.0)

    # C3-021: keyframe_lint handles from/to, rejects negative duration & out-of-range %,
    # allows GSAP ease, preserves data-name, skips animation-name: none
    css_from_to = (
        "@keyframes k { from { opacity: 0 } to { opacity: 1 } } .a { animation-name: k; animation-duration: 1s; }"
    )
    res_ft = lint_composition_keyframes(css_from_to, grid)
    assert res_ft["passed"] is True
    assert {"k.0%", "k.100%"} <= {row["name"] for row in res_ft["keyframes"]}

    assert not lint_composition_keyframes(".a { animation-duration: -1s; }", grid)["passed"]
    assert not lint_composition_keyframes(
        "@keyframes k { 150% { opacity: 1 } } .a { animation-name: k; animation-duration: 1s; }", grid
    )["passed"]
    assert not lint_composition_keyframes(".a { animation-name: none; animation-duration: 0.5s; }", grid)["passed"]

    gsap_res = lint_composition_keyframes('gsap.to("hero", {duration: 0.5, ease: "power2.out",})', grid)
    assert gsap_res["passed"] is True

    html_name = '<div data-name="banner" data-start="0.5" data-duration="0.5"></div>'
    html_res = lint_composition_keyframes(html_name, grid)
    assert html_res["passed"] is True
    assert any(row["name"] == "banner.start" for row in html_res["keyframes"])

    # C3-021: son_clave rejects phrase_bars=1
    with pytest.raises(ValueError, match="too short"):
        place_rhythm_cell("son_clave", grid, phrase_bars=1)

    # C3-022: audition multi_audio validates picture stream, transcodes incompatible codec for .mp4,
    # and raises typed MCPVideoError on 0-audio mix input
    base = _make_base_clip(tmp_path / "aud_base.mp4", size="96x64", fps=24, duration=1.0)
    mix_wav = tmp_path / "mix.wav"
    mix_wav.write_bytes(
        pcm_to_wav(
            array("h", [round(32767 * 0.2 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000)]),
            sample_rate_hz=48000,
        )
    )

    png = tmp_path / "still.png"
    Image.new("RGB", (64, 64), (255, 0, 0)).save(png)
    with pytest.raises(MCPVideoError) as pic_exc:
        build_ab_audition(png, [{"label": "A", "audio_path": str(mix_wav)}], tmp_path / "bad.mkv", mode="multi_audio")
    assert pic_exc.value.code == "invalid_picture"

    vp9 = tmp_path / "vp9_pic.webm"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c:v", "libvpx-vp9", "-an", str(vp9)])
    aud_mp4 = tmp_path / "vp9_aud.mp4"
    build_ab_audition(vp9, [{"label": "A", "audio_path": str(mix_wav)}], aud_mp4, mode="multi_audio")
    assert _ffprobe_streams(aud_mp4)[0]["codec_name"] == "h264"

    video_only = tmp_path / "no_audio.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-an", "-c:v", "copy", str(video_only)])
    with pytest.raises(MCPVideoError) as no_aud_exc:
        build_ab_audition(
            base, [{"label": "SilentMix", "audio_path": str(video_only)}], tmp_path / "bad_mix.mkv", mode="multi_audio"
        )
    assert no_aud_exc.value.code == "invalid_audition_audio"
