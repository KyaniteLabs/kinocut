import base64
import json
import math
import re
import shutil
import struct
import wave

import pytest

from kinocut.audio_sync import (
    Onset,
    align_hit_stack,
    build_ab_audition,
    detect_onsets,
    detect_sample_onset,
    nudge_off_transients,
    place_events_with_stem,
    pocket_lock,
)
from kinocut.bounded_process import run_bounded
from kinocut.errors import MCPVideoError

RATE = 48_000


def _wav(path, samples):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes(b"".join(struct.pack("<h", round(value * 32767)) for value in samples))
    return path


def _burst(samples, start, frequency):
    for index in range(576):
        envelope = min(index / 48, 1.0) * math.exp(-index / 180)
        samples[start + index] += 0.6 * envelope * math.cos(math.tau * frequency * index / RATE)


def test_pocket_lock_with_real_off_grid_hat_stem(tmp_path):
    samples = [0.0] * (RATE // 2)
    for time_s, frequency in [(0.06, 90), (0.111, 8000), (0.16, 700), (0.320, 8000)]:
        _burst(samples, round(time_s * RATE), frequency)
    stem = _wav(tmp_path / "drums.wav", samples)
    onsets = detect_onsets(stem)
    assert onsets == detect_onsets(stem)
    for time_s, band in [(0.06, "kick"), (0.16, "snare")]:
        assert any(onset.band == band and abs(onset.time_s - time_s) <= 0.004 for onset in onsets)
    events = [{"time_s": 0.1}, {"time_s": 0.3}, {"time_s": 0.4}]
    placed, receipt = pocket_lock(events, onsets, fine_grid_step_ms=2)
    assert placed[0]["time_s"] == pytest.approx(0.111, abs=0.002)
    assert placed[1]["time_s"] == pytest.approx(0.320, abs=0.002)
    assert placed[2] == events[2]
    assert receipt["unmatched_events"] == [2]
    assert all(abs(entry["final_time_s"] - entry["original_time_s"]) <= 0.025 for entry in receipt["events"])


def test_pocket_lock_confidence_ties_and_grid_window():
    events = [{"time_s": 0.1}]
    onsets = [Onset(0.125, "hat", 1, 0.8), Onset(0.075, "hat", 1, 0.8), Onset(0.101, "hat", 1, 0.2)]
    placed, receipt = pocket_lock(events, onsets, fine_grid_step_ms=70)
    assert placed == [{"time_s": 0.075}]
    assert receipt["events"][0]["matched_onset_s"] == 0.075
    assert pocket_lock(events, onsets, min_confidence=0.9)[0] == events


def test_masking_clearance_fixed_and_combined_precedence():
    events = [{"time_s": 0.100}, {"time_s": 0.2}, {"time_s": 0.100, "fixed": True}]
    onsets = [Onset(0.1, "kick", 1, 1), Onset(0.101, "hat", 1, 1)]
    placed, receipt = nudge_off_transients(events, onsets)
    assert placed[0]["time_s"] == pytest.approx(0.112)
    assert placed[1:] == events[1:]
    assert receipt["events"][0]["shift_ms"] == pytest.approx(12)
    assert receipt["unresolved_overlaps"][0]["event_index"] == 2
    varied = [dict(events[0], mode=mode) for mode in ("pocket_lock", "avoid_masking", "both")]
    placed, receipt = place_events_with_stem([*varied, events[2]], onsets)
    assert [event["time_s"] for event in placed] == pytest.approx([0.101, 0.112, 0.112, 0.1])
    assert receipt["events"][2]["masking"]["original_time_s"] == 0.101
    assert receipt["events"][3]["pocket_lock"]["moved"] is False


def test_masking_checks_other_transients_and_boundaries():
    onsets = [Onset(0.100, "kick", 1, 1), Onset(0.119, "snare", 1, 1)]
    events = [{"time_s": 0.100}, {"time_s": 0.0}]
    placed, _ = nudge_off_transients(events, onsets, prefer="late")
    assert placed[0]["time_s"] == pytest.approx(0.088)
    assert placed[1] == events[1]
    placed, receipt = nudge_off_transients(events, onsets, max_shift_ms=5)
    assert placed == events
    assert len(receipt["unresolved_overlaps"]) == 1


def test_zero_movement_budgets_do_not_move_even_with_sub_picosecond_offsets():
    events = [{"time_s": 0.125}]
    almost = math.nextafter(0.125, math.inf)
    locked, pocket = pocket_lock(events, [Onset(almost, "hat", 1, 1)], max_window_ms=0)
    nudged, masking = nudge_off_transients(
        events, [Onset(0.125, "kick", 1, 1)], clearance_ms=(almost - 0.125) * 1000, max_shift_ms=0
    )
    assert locked == nudged == events
    assert pocket["unmatched_events"] == [0]
    assert masking["events"][0]["shift_ms"] == 0.0
    assert masking["unresolved_overlaps"] == [{"event_index": 0, "onset_times_s": [0.125]}]


@pytest.mark.parametrize("confidence", [True, False, math.nan, math.inf, -math.inf, -0.01, 1.01])
def test_placement_rejects_invalid_confidence(confidence):
    events = [{"time_s": 0.1}]
    with pytest.raises(MCPVideoError, match="Confidence"):
        pocket_lock(events, [], min_confidence=confidence)
    with pytest.raises(MCPVideoError, match="Confidence"):
        pocket_lock(events, [Onset(0.1, "hat", 1, confidence)])
    with pytest.raises(MCPVideoError, match="Confidence"):
        nudge_off_transients(events, [Onset(0.1, "kick", 1, confidence)])


def test_stack_aligns_samples_flips_polarity_and_limits_peak(tmp_path):
    hit = [0.72 * math.cos(math.tau * 70 * index / RATE) for index in range(2400)]
    kick = _wav(tmp_path / "kick.wav", [0] * 37 + hit)
    sub = _wav(tmp_path / "sub.wav", [0] * 211 + [-value for value in hit])
    output = tmp_path / "stack.wav"
    receipt = align_hit_stack([kick, sub], output)
    assert [layer["onset_sample"] for layer in receipt["layers"]] == [37, 211]
    assert [layer["offset_samples"] for layer in receipt["layers"]] == [-37, -211]
    assert [layer["polarity_inverted"] for layer in receipt["layers"]] == [False, True]
    assert receipt["combined_peak_dbfs"] > 0 > receipt["applied_gain_db"]
    with wave.open(str(output), "rb") as stream:
        pcm = [value / 32768 for (value,) in struct.iter_unpack("<h", stream.readframes(stream.getnframes()))]
    onset = detect_sample_onset(pcm)
    assert onset is not None
    assert onset <= 1
    assert 20 * math.log10(max(map(abs, pcm))) == pytest.approx(-0.5, abs=0.002)
    second = tmp_path / "again.wav"
    align_hit_stack([kick, sub], second)
    assert output.read_bytes() == second.read_bytes()
    failed = tmp_path / "failed.wav"
    with pytest.raises(MCPVideoError, match="peak"):
        align_hit_stack([kick, sub], failed, on_clip="fail")
    assert not failed.exists()


def test_stack_compares_full_low_band_response_of_unequal_hits(tmp_path):
    long_hit = _wav(tmp_path / "long.wav", [-0.05] + [0.1] * 511)
    impulse = _wav(tmp_path / "impulse.wav", [0.5])
    output = tmp_path / "stack.wav"
    receipt = align_hit_stack([long_hit, impulse], output)
    assert [layer["polarity_inverted"] for layer in receipt["layers"]] == [False, False]
    with wave.open(str(output), "rb") as stream:
        assert stream.getnframes() == 512
        assert struct.unpack("<h", stream.readframes(1))[0] / 32768 == pytest.approx(0.45, abs=0.0001)


def _command(*args):
    result = run_bounded(list(map(str, args)), timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _video_hash(path):
    return _command("ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "hash", "-")


def _stream_types(path):
    streams = json.loads(_command("ffprobe", "-v", "error", "-show_streams", "-of", "json", path))["streams"]
    return [stream["codec_type"] for stream in streams]


def _rendered_levels(path, stream=0):
    result = run_bounded(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-map",
            f"0:a:{stream}",
            "-af",
            "aformat=sample_fmts=dbl,astats=measure_perchannel=none:measure_overall=Peak_level,"
            "loudnorm=print_format=json",
            "-f",
            "null",
            "-",
        ],
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    peak = re.search(r"Peak level dB: ([-\d.]+)", result.stderr)
    lufs = re.search(r'"input_i"\s*:\s*"([-\d.]+)"', result.stderr)
    assert peak is not None and lufs is not None, result.stderr
    return float(lufs[1]), float(peak[1])


@pytest.fixture
def audition_inputs(tmp_path):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("FFmpeg and FFprobe are required")
    video = tmp_path / "source.mp4"
    _command(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=96x64:r=30:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=300:duration=1",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        video,
    )
    mixes = []
    for index, (label, amplitude) in enumerate([("<Straight & loud>", 0.3), ("Swung", 0.075)]):
        audio = _wav(
            tmp_path / f"source-{index}.wav", [amplitude * math.sin(math.tau * 600 * i / RATE) for i in range(RATE)]
        )
        mixes.append({"label": label, "audio_path": str(audio)})
    return video, mixes


@pytest.mark.parametrize("suffix", ["mkv", "mp4"])
def test_audition_mux_keeps_encoded_picture_and_labels(tmp_path, audition_inputs, suffix):
    video, mixes = audition_inputs
    output = tmp_path / f"audition.{suffix}"
    receipt = build_ab_audition(video, mixes, output, blind=True)
    streams = json.loads(_command("ffprobe", "-v", "error", "-show_streams", "-of", "json", output))["streams"]
    assert [stream["codec_type"] for stream in streams] == ["video", "audio", "audio"]
    key = "title" if suffix == "mkv" else "handler_name"
    assert [stream["tags"][key] for stream in streams[1:]] == ["Mix A", "Mix B"]
    assert _video_hash(output) == _video_hash(video)
    assert receipt["blind_key"] == {"Mix A": mixes[0]["label"], "Mix B": mixes[1]["label"]}
    first, second = receipt["mixes"]
    assert first["measured_lufs"] - second["measured_lufs"] == pytest.approx(12.04, abs=0.15)
    assert second["applied_gain_db"] - first["applied_gain_db"] == pytest.approx(12.04, abs=0.15)


def test_audition_review_is_offline_and_blind(tmp_path, audition_inputs):
    video, mixes = audition_inputs
    folder = tmp_path / "review"
    receipt = build_ab_audition(video, mixes, folder, mode="review_page", blind=True, loop_start_s=0.1, loop_end_s=0.8)
    page = (folder / "index.html").read_text()
    assert "Mix A" in page and "Mix B" in page
    assert all(mix["label"] not in page for mix in mixes)
    assert "https://" not in page and "fetch(" not in page
    picture = folder / "picture.mp4"
    assert _stream_types(video) == ["video", "audio"]
    assert _stream_types(picture) == ["video"]
    assert _video_hash(picture) == _video_hash(video)
    assert _command("ffmpeg", "-v", "error", "-i", picture, "-f", "framemd5", "-") == _command(
        "ffmpeg", "-v", "error", "-i", video, "-an", "-f", "framemd5", "-"
    )
    payloads = re.findall(r'<script class="track" type="application/octet-stream">(.*?)</script>', page)
    files = [(folder / f"mix-{index:03}.wav").read_bytes() for index in (1, 2)]
    assert [base64.b64decode(payload) for payload in payloads] == files
    assert json.loads((folder / "receipt.json").read_text()) == receipt


@pytest.mark.parametrize("kind", ["audio", "text", "symlink", "directory"])
def test_audition_review_rejects_invalid_picture(tmp_path, audition_inputs, kind):
    video, mixes = audition_inputs
    invalid = tmp_path / "invalid.mp4"
    if kind == "audio":
        shutil.copyfile(mixes[0]["audio_path"], invalid)
    elif kind == "text":
        invalid.write_text("Not a video")
    elif kind == "symlink":
        invalid.symlink_to(video)
    else:
        invalid.mkdir()
    folder = tmp_path / "review"
    with pytest.raises(MCPVideoError, match="Picture"):
        build_ab_audition(invalid, mixes, folder, mode="review_page")
    assert not folder.exists()


@pytest.mark.parametrize("mode", ["review_page", "multi_audio"])
def test_audition_matches_rendered_high_crest_factor_mix_without_clipping(tmp_path, audition_inputs, mode):
    video, mixes = audition_inputs
    impulse = [0.0] * RATE
    impulse[RATE // 2] = 0.85
    audio = _wav(tmp_path / "impulse.wav", impulse)
    mixes = [mixes[0], {"label": "Transient", "audio_path": str(audio)}]
    output = tmp_path / ("review" if mode == "review_page" else "audition.mkv")
    with pytest.raises(ValueError, match=r"unreachable.*sample-peak ceiling"):
        build_ab_audition(video, mixes, output, mode=mode, target_lufs=-16.0)
    assert not output.exists()
    receipt = build_ab_audition(video, mixes, output, mode=mode)
    assert receipt["headroom_limited"] is True
    assert receipt["effective_target_lufs"] < -35
    transient = receipt["mixes"][1]
    assert transient["measured_lufs"] == pytest.approx(-42, abs=2)
    assert receipt["effective_target_lufs"] == pytest.approx(
        transient["measured_lufs"] - transient["measured_sample_peak_dbfs"] - 1.0, abs=1.0
    )
    tracks = (
        [(output / "mix-001.wav", 0), (output / "mix-002.wav", 0)]
        if mode == "review_page"
        else [(output, 0), (output, 1)]
    )
    levels = [_rendered_levels(path, stream) for path, stream in tracks]
    assert levels[0][0] == pytest.approx(levels[1][0], abs=0.15)
    for lufs, peak in levels:
        assert lufs == pytest.approx(receipt["effective_target_lufs"], abs=0.075)
        assert peak <= -1.0


def test_audition_short_mix_uses_rms_and_no_match_keeps_gain(tmp_path, audition_inputs):
    video, _ = audition_inputs
    audio = _wav(tmp_path / "short.wav", [0.1 * math.sin(math.tau * 600 * index / RATE) for index in range(4800)])
    receipt = build_ab_audition(
        video, [{"label": "Short", "audio_path": audio}], tmp_path / "short.mkv", loudness_match=False
    )
    (entry,) = receipt["mixes"]
    assert entry["measurement"] == "rms_dbfs"
    assert entry["measured_lufs"] is None
    assert entry["measured_rms_dbfs"] == pytest.approx(-23.01, abs=0.02)
    assert entry["applied_gain_db"] == 0


_PLAYER_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const page = fs.readFileSync(process.argv[2], 'utf8');
const audioCalls = [], stopped = [], nodes = {};
let frame;
function element(props) {
  return Object.assign({events: {}, addEventListener(name, listener) { this.events[name] = listener; }}, props);
}
nodes.video = element({currentTime: 0.3, playbackRate: 1, paused: true, seeking: false,
  async play() { this.paused = false; this.events.playing(); }});
nodes.select = element({selectedIndex: 0});
for (const name of ['#enable', '#loop', '#status']) nodes[name] = element();
nodes['#loop-range'] = {textContent: '[0.1, 0.8]'};
class AudioContext {
  currentTime = 1;
  async resume() {}
  async decodeAudioData(bytes) {
    assert.equal(Buffer.from(bytes).toString('ascii', 0, 4), 'RIFF');
    return {duration: 1};
  }
  createGain() {
    return {connect() {}, gain: {setValueAtTime(value) { this.value = value; }}};
  }
  createBufferSource() {
    return {playbackRate: {}, connect(bus) { this.bus = bus; },
      start(when, offset) { audioCalls.push({when, offset, bus: this.bus}); },
      stop() { stopped.push(true); }, disconnect() {}};
  }
}
const tracks = [...page.matchAll(/<script class="track"[^>]*>([^<]*)<\/script>/g)]
  .map(match => ({textContent: match[1]}));
vm.runInNewContext(page.match(/<script>([\s\S]*)<\/script>/)[1], {
  AudioContext, atob, document: {querySelector: name => nodes[name], querySelectorAll: () => tracks},
  requestAnimationFrame: callback => { frame = callback; }
});
(async () => {
  await nodes['#enable'].events.click();
  assert.equal(nodes['#status'].textContent, 'Ready');
  assert.deepEqual(audioCalls.map(({when, offset}) => [when, offset]), [[1.01, 0.31], [1.01, 0.31]]);
  assert.deepEqual(audioCalls.map(({bus}) => bus.gain.value), [1, 0]);
  nodes.select.selectedIndex = 1;
  nodes.select.events.change();
  assert.deepEqual(audioCalls.map(({bus}) => bus.gain.value), [0, 1]);
  assert.equal(stopped.length, 0);
  assert.equal(nodes.video.currentTime, 0.3);
  nodes['#loop'].checked = true;
  nodes.video.currentTime = 0.8;
  frame();
  assert.equal(nodes.video.currentTime, 0.1);
  nodes.video.events.seeking();
  nodes.video.events.seeked();
  assert.equal(stopped.length, 2);
  assert.equal(audioCalls.length, 4);
  assert.equal(audioCalls[2].offset, audioCalls[3].offset);
  console.log('switch and loop verified');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_review_player_switches_gains_without_seeking(tmp_path, audition_inputs):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to exercise the generated player script")
    video, mixes = audition_inputs
    folder = tmp_path / "review"
    build_ab_audition(video, mixes, folder, mode="review_page", loop_start_s=0.1, loop_end_s=0.8)
    harness = tmp_path / "player.cjs"
    harness.write_text(_PLAYER_HARNESS)
    assert _command(node, harness, folder / "index.html").strip() == "switch and loop verified"
