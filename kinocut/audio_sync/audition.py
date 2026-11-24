"""One-picture A/B audition, as a multi-audio container or an offline review."""

from __future__ import annotations

import base64
import html
import json
import math
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json
from ..publication import anchored_tree, atomic_output, record_operation_input
from .onsets import _nonnegative

_LOUDNESS = re.compile(r'"input_i"\s*:\s*"(-?(?:\d+(?:\.\d+)?|inf))"')
_RMS = re.compile(r"RMS level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))")
_PEAK = re.compile(r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))")
_STATS = "aformat=sample_fmts=dbl,astats=measure_perchannel=none:measure_overall=Peak_level+RMS_level"
_SAMPLE_PEAK_CEILING = -1.0
_PEAK_MARGIN = 0.002
_MATCH_TOLERANCE = 0.075


@dataclass(frozen=True)
class _AudioLevels:
    lufs: float | None
    rms_dbfs: float | None
    peak_dbfs: float

    def level(self, method: str) -> float | None:
        return self.lufs if method == "lufs" else self.rms_dbfs


def _measure_audio(source: str, stream: int = 0) -> _AudioLevels:
    measure = ["-nostdin", "-hide_banner", "-nostats", "-v", "info", "-i", source, "-map", f"0:a:{stream}", "-vn"]
    try:
        log = _run_ffmpeg([*measure, "-af", f"{_STATS},loudnorm=print_format=json", "-f", "null", "-"]).stderr
    except ProcessingError:
        log = _run_ffmpeg([*measure, "-af", _STATS, "-f", "null", "-"]).stderr
    peak = _PEAK.search(log)
    if peak is None:
        raise MCPVideoError("Could not measure audition audio sample peak", code="audio_measurement_failed")
    return _AudioLevels(_finite_level(_LOUDNESS, log), _finite_level(_RMS, log), float(peak[1]))


def _finite_level(pattern: re.Pattern[str], log: str) -> float | None:
    match = pattern.search(log)
    return value if match and math.isfinite(value := float(match[1])) else None


def _blind_label(index: int) -> str:
    letters = ""
    number = index + 1
    while number:
        number, digit = divmod(number - 1, 26)
        letters = chr(ord("A") + digit) + letters
    return f"Mix {letters}"


def _mix_receipts(mixes, *, blind: bool) -> tuple[list[dict], list[_AudioLevels]]:
    entries = []
    measurements = []
    for index, mix in enumerate(mixes):
        label = mix["label"]
        if not isinstance(label, str) or not label.strip() or "\x00" in label:
            raise MCPVideoError("Mix labels must be nonempty text", code="invalid_parameter")
        source = str(Path(mix["audio_path"]).absolute())
        record_operation_input(source)
        levels = _measure_audio(source)
        measurements.append(levels)
        entries.append(
            {
                "label": label,
                "display_label": _blind_label(index) if blind else label,
                "source": source,
                "measured_lufs": levels.lufs,
                "measured_rms_dbfs": levels.rms_dbfs if levels.lufs is None else None,
                "measurement": "lufs"
                if levels.lufs is not None
                else ("rms_dbfs" if levels.rms_dbfs is not None else "unmeasurable"),
                "measured_sample_peak_dbfs": levels.peak_dbfs if math.isfinite(levels.peak_dbfs) else None,
                "applied_gain_db": 0.0,
            }
        )
    if not entries:
        raise MCPVideoError("Provide at least one audition mix", code="invalid_parameter")
    return entries, measurements


def _headroom_target(requested: float, ceiling: float, *, explicit: bool) -> float:
    if requested > ceiling and explicit:
        raise ValueError("Requested loudness target is unreachable without exceeding the sample-peak ceiling")
    return min(requested, ceiling)


def _render_matched(
    render: Callable[[], list[tuple[str, int]]],
    entries: list[dict],
    sources: list[_AudioLevels],
    receipt: dict,
    *,
    explicit: bool,
) -> None:
    if not receipt["loudness_match"]:
        render()
        return
    method = "rms_dbfs" if any(level.lufs is None and level.rms_dbfs is not None for level in sources) else "lufs"
    audible = [(index, level) for index, source in enumerate(sources) if (level := source.level(method)) is not None]
    if not audible:
        render()
        return
    ceiling = _SAMPLE_PEAK_CEILING - _PEAK_MARGIN
    gain_limits = {index: ceiling - sources[index].peak_dbfs for index, _ in audible}
    target = _headroom_target(
        receipt["target_lufs"], min(level + gain_limits[index] for index, level in audible), explicit=explicit
    )
    for index, level in audible:
        entries[index]["applied_gain_db"] = target - level

    for _ in range(6):
        tracks = render()
        corrections = {}
        next_target = target
        for index, _ in audible:
            source, stream = tracks[index]
            rendered = _measure_audio(source, stream)
            level = rendered.level(method)
            if level is None:
                raise ValueError("Rendered mix could not be measured at the common loudness target")
            error = target - level
            if abs(error) <= _MATCH_TOLERANCE and rendered.peak_dbfs <= _SAMPLE_PEAK_CEILING:
                continue
            gain = entries[index]["applied_gain_db"]
            corrections[index] = error
            next_target = min(next_target, level + min(ceiling - rendered.peak_dbfs, gain_limits[index] - gain))
        if not corrections:
            receipt["matching_measurement"] = method
            receipt["effective_target_lufs"] = target if method == "lufs" else None
            receipt["effective_target_rms_dbfs"] = target if method == "rms_dbfs" else None
            receipt["headroom_limited"] = target < receipt["target_lufs"]
            return
        next_target = _headroom_target(target, next_target, explicit=explicit)
        for index, _ in audible:
            entries[index]["applied_gain_db"] += corrections.get(index, 0.0) + next_target - target
        target = next_target
    raise ValueError("Could not match rendered mixes to a common loudness without exceeding the sample-peak ceiling")


def _volume(entry: dict) -> str:
    return f"volume={entry['applied_gain_db']:.12g}dB:precision=double"


def _mux(video: Path, entries: list[dict], stage: str) -> list[tuple[str, int]]:
    args = ["-nostdin", "-v", "error", "-i", str(video)]
    for entry in entries:
        args.extend(["-i", entry["source"]])
    args.extend(
        [
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-map_metadata",
            "-1",
            "-map_metadata:s",
            "-1",
            "-map_chapters",
            "-1",
        ]
    )
    for index, entry in enumerate(entries):
        label = entry["display_label"]
        args.extend(
            [
                "-map",
                f"{index + 1}:a:0",
                f"-filter:a:{index}",
                f"asetpts=PTS-STARTPTS,{_volume(entry)}",
                f"-metadata:s:a:{index}",
                f"title={label}",
                f"-metadata:s:a:{index}",
                f"handler_name={label}",
                f"-disposition:a:{index}",
                "default" if index == 0 else "0",
            ]
        )
    _run_ffmpeg([*args, stage])
    return [(stage, index) for index in range(len(entries))]


_PLAYER = """
const picture = document.querySelector('video');
const picker = document.querySelector('select');
const enable = document.querySelector('#enable');
const loop = document.querySelector('#loop');
const status = document.querySelector('#status');
const [loopStart, loopEnd] = JSON.parse(document.querySelector('#loop-range').textContent);
const tracks = [...document.querySelectorAll('.track')];
let context, buffers, gains, voices = [], anchor, flowing = false;

function selectMix() {
  gains?.forEach((bus, index) => bus.gain.setValueAtTime(Number(index === picker.selectedIndex), context.currentTime));
}
function stopVoices() {
  voices.forEach(voice => { voice.stop(); voice.disconnect(); });
  voices = [];
  anchor = undefined;
}
function startVoices() {
  stopVoices();
  const rate = picture.playbackRate;
  if (!buffers || !flowing || picture.paused || picture.seeking || rate <= 0) return;
  const when = context.currentTime + 0.01;
  const mediaTime = picture.currentTime + 0.01 * rate;
  anchor = {when, mediaTime, rate};
  buffers.forEach((buffer, index) => {
    if (mediaTime >= buffer.duration) return;
    const voice = context.createBufferSource();
    voice.buffer = buffer;
    voice.playbackRate.value = rate;
    voice.connect(gains[index]);
    voice.start(when, mediaTime);
    voices.push(voice);
  });
}
function tick() {
  if (flowing && !picture.paused && !picture.seeking) {
    if (loop.checked && (picture.currentTime >= loopEnd || picture.currentTime < loopStart)) {
      picture.currentTime = loopStart;
    } else if (anchor) {
      const expected = anchor.mediaTime + (context.currentTime - anchor.when) * anchor.rate;
      if (Math.abs(expected - picture.currentTime) > 0.025) startVoices();
    }
  }
  requestAnimationFrame(tick);
}
enable.addEventListener('click', async () => {
  enable.disabled = true;
  status.textContent = 'Loading mixes…';
  try {
    context ??= new AudioContext();
    await context.resume();
    buffers ??= await Promise.all(tracks.map(track => {
      const bytes = Uint8Array.from(atob(track.textContent), character => character.charCodeAt(0));
      return context.decodeAudioData(bytes.buffer);
    }));
    gains ??= buffers.map(() => {
      const bus = context.createGain();
      bus.connect(context.destination);
      return bus;
    });
    selectMix();
    if (picture.paused) await picture.play();
    else startVoices();
    status.textContent = 'Ready';
    enable.hidden = true;
  } catch (error) {
    status.textContent = 'Could not start audition audio: ' + error.message;
    enable.disabled = false;
  }
});
picker.addEventListener('change', selectMix);
picture.addEventListener('playing', () => { flowing = true; startVoices(); });
for (const name of ['waiting', 'pause']) {
  picture.addEventListener(name, () => { flowing = false; stopVoices(); });
}
picture.addEventListener('ended', () => {
  flowing = false;
  stopVoices();
  if (loop.checked && loopStart < picture.duration) {
    picture.currentTime = loopStart;
    picture.play().catch(error => { status.textContent = error.message; });
  }
});
picture.addEventListener('seeking', stopVoices);
for (const name of ['seeked', 'ratechange']) picture.addEventListener(name, startVoices);
if (loopStart === null) {
  loop.disabled = true;
  loop.parentElement.hidden = true;
}
requestAnimationFrame(tick);
"""


def _write_page(path: Path, picture: str, entries: list[dict], tracks: list[Path], loop: list) -> None:
    with path.open("w", encoding="utf-8") as page:
        page.write("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mix audition</title><style>
body{margin:2rem auto;padding:0 1rem;max-width:60rem;font:1rem system-ui;color-scheme:light dark}
video{display:block;width:100%;margin:1rem 0;background:#000}
label,button{margin-inline-end:1rem} select,button{font:inherit}
</style><h1>Mix audition</h1>""")
        page.write(f'<video controls muted playsinline preload="metadata" src="{html.escape(picture)}"></video>\n')
        page.write('<button id="enable">Enable audio and play</button><label>Mix <select>')
        for entry in entries:
            page.write(f"<option>{html.escape(entry['display_label'])}</option>")
        page.write(
            '</select></label><label><input id="loop" type="checkbox"> Loop span</label>\n'
            '<p id="status" role="status"></p>\n'
        )
        page.write(f'<script id="loop-range" type="application/json">{json.dumps(loop)}</script>\n')
        for track in tracks:
            page.write('<script class="track" type="application/octet-stream">')
            with track.open("rb") as audio:
                while chunk := audio.read(3 * 16384):
                    page.write(base64.b64encode(chunk).decode("ascii"))
            page.write("</script>\n")
        page.write(f"<script>{_PLAYER}</script></html>\n")


_IMAGE_FORMATS = frozenset({"image2", "image2pipe", "ico", "mjpeg", "webp"})


def _is_still_image_format(probe: dict) -> bool:
    fmt = str(probe.get("format", {}).get("format_name") or "").lower()
    tokens = {tok.strip() for tok in fmt.split(",") if tok.strip()}
    return not tokens or any(tok in _IMAGE_FORMATS or tok.endswith("_pipe") for tok in tokens)


def _picture_stream(video: Path) -> int:
    try:
        if not stat.S_ISREG(video.lstat().st_mode):
            raise MCPVideoError("Picture must be a non-symlink regular file", code="invalid_picture")
    except OSError:
        raise MCPVideoError("Picture must be a non-symlink regular file", code="invalid_picture") from None
    try:
        probe = _run_ffprobe_json(str(video))
    except ProcessingError:
        probe = {}
    if _is_still_image_format(probe):
        raise MCPVideoError("Picture must contain a video stream, not a still image", code="invalid_picture")
    streams = probe.get("streams", [])
    for stream in streams:
        if (
            stream.get("codec_type") == "video"
            and not stream.get("disposition", {}).get("attached_pic")
            and stream.get("width", 0) > 0
            and stream.get("height", 0) > 0
        ):
            return stream["index"]
    raise MCPVideoError("Picture must contain a video stream", code="invalid_picture")


def _render_wavs(entries: list[dict], tracks: list[Path]) -> list[tuple[str, int]]:
    for entry, audio in zip(entries, tracks, strict=True):
        _run_ffmpeg(
            [
                "-nostdin",
                "-v",
                "error",
                "-i",
                entry["source"],
                "-map",
                "0:a:0",
                "-map_metadata",
                "-1",
                "-af",
                _volume(entry),
                "-c:a",
                "pcm_s16le",
                str(audio),
            ]
        )
    return [(str(track), 0) for track in tracks]


def _review(
    video: Path,
    picture_stream: int,
    entries: list[dict],
    sources: list[_AudioLevels],
    output: Path,
    receipt: dict,
    loop: list[float | None],
    *,
    explicit: bool,
) -> None:
    with anchored_tree(output) as stage:
        picture = f"picture{video.suffix.lower()}"
        _run_ffmpeg(
            [
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(video),
                "-map",
                f"0:{picture_stream}",
                "-c:v",
                "copy",
                "-an",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                str(stage / picture),
            ]
        )
        tracks = [stage / f"mix-{index:03}.wav" for index in range(1, len(entries) + 1)]
        _render_matched(lambda: _render_wavs(entries, tracks), entries, sources, receipt, explicit=explicit)
        _write_page(stage / "index.html", picture, entries, tracks, loop)
        (stage / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_ab_audition(
    video_path,
    mixes,
    output_path,
    *,
    mode="multi_audio",
    loudness_match=True,
    target_lufs: float | None = None,
    blind=False,
    loop_start_s: float | None = None,
    loop_end_s: float | None = None,
):
    """Package premixed, picture-aligned audio alternatives and return an audition receipt."""
    video, output = Path(video_path).absolute(), Path(output_path).absolute()
    target = -16.0 if target_lufs is None else target_lufs
    if mode not in ("multi_audio", "review_page") or not math.isfinite(target) or not -70 <= target <= 0:
        raise MCPVideoError("Invalid audition mode or loudness target", code="invalid_parameter")
    if mode == "multi_audio" and output.suffix.lower() not in (".mp4", ".mkv"):
        raise MCPVideoError("Multi-audio audition output must be MP4 or MKV", code="invalid_parameter")
    loop = [loop_start_s, loop_end_s]
    if (loop_start_s is not None or loop_end_s is not None) and (
        loop_start_s is None
        or loop_end_s is None
        or _nonnegative(loop_start_s, "loop_start_s") >= _nonnegative(loop_end_s, "loop_end_s")
    ):
        raise MCPVideoError("Supply an increasing loop start and end in seconds", code="invalid_parameter")
    picture_stream = _picture_stream(video) if mode == "review_page" else None
    record_operation_input(str(video))
    entries, sources = _mix_receipts(mixes, blind=blind)
    receipt = {
        "mode": mode,
        "output_path": str(output),
        "video_source": str(video),
        "mixes": entries,
        "loudness_match": loudness_match,
        "target_lufs": target,
        "effective_target_lufs": None,
        "effective_target_rms_dbfs": None,
        "matching_measurement": None,
        "headroom_limited": False,
        "sample_peak_ceiling_dbfs": _SAMPLE_PEAK_CEILING,
        "blind_key": {entry["display_label"]: entry["label"] for entry in entries} if blind else {},
        "loop_start_s": loop_start_s,
        "loop_end_s": loop_end_s,
    }
    explicit = target_lufs is not None
    if picture_stream is None:
        with atomic_output(str(output)) as stage:
            _render_matched(lambda: _mux(video, entries, stage), entries, sources, receipt, explicit=explicit)
    else:
        _review(video, picture_stream, entries, sources, output, receipt, loop, explicit=explicit)
    return receipt
