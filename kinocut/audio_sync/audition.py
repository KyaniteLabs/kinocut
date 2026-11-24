"""One-picture A/B audition, as a multi-audio container or an offline review."""

from __future__ import annotations

import base64
import html
import json
import math
import re
import shutil
from pathlib import Path

from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _run_ffmpeg
from ..publication import anchored_tree, atomic_output, record_operation_input
from .onsets import _nonnegative

_LOUDNESS = re.compile(r'"input_i"\s*:\s*"(-?(?:\d+(?:\.\d+)?|inf))"')
_RMS = re.compile(r"RMS level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))")


def _measure_loudness(source: str) -> tuple[float | None, str]:
    measure = ["-nostdin", "-hide_banner", "-nostats", "-v", "info", "-i", source, "-map", "0:a:0", "-vn"]
    try:
        log = _run_ffmpeg([*measure, "-af", "loudnorm=print_format=json", "-f", "null", "-"]).stderr
    except ProcessingError:
        log = ""
    lufs = _LOUDNESS.search(log)
    if lufs and math.isfinite(integrated := float(lufs[1])):
        return integrated, "lufs"
    log = _run_ffmpeg(
        [*measure, "-af", "astats=measure_perchannel=none:measure_overall=RMS_level", "-f", "null", "-"]
    ).stderr
    rms = _RMS.search(log)
    if rms and math.isfinite(level := float(rms[1])):
        return level, "rms_dbfs"
    return None, "unmeasurable"


def _blind_label(index: int) -> str:
    letters = ""
    number = index + 1
    while number:
        number, digit = divmod(number - 1, 26)
        letters = chr(ord("A") + digit) + letters
    return f"Mix {letters}"


def _mix_receipts(mixes, *, blind: bool, loudness_match: bool, target: float) -> list[dict]:
    entries = []
    for index, mix in enumerate(mixes):
        label = mix["label"]
        if not isinstance(label, str) or not label.strip() or "\x00" in label:
            raise MCPVideoError("Mix labels must be nonempty text", code="invalid_parameter")
        source = str(Path(mix["audio_path"]).absolute())
        record_operation_input(source)
        level, method = _measure_loudness(source)
        entries.append(
            {
                "label": label,
                "display_label": _blind_label(index) if blind else label,
                "source": source,
                "measured_lufs": level if method == "lufs" else None,
                "measured_rms_dbfs": level if method == "rms_dbfs" else None,
                "measurement": method,
                "applied_gain_db": target - level if loudness_match and level is not None else 0.0,
            }
        )
    if not entries:
        raise MCPVideoError("Provide at least one audition mix", code="invalid_parameter")
    return entries


def _volume(entry: dict) -> str:
    return f"volume={entry['applied_gain_db']:.12g}dB"


def _mux(video: Path, entries: list[dict], output: Path) -> None:
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
    with atomic_output(str(output)) as stage:
        _run_ffmpeg([*args, stage])


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


def _review(video: Path, entries: list[dict], output: Path, receipt: dict, loop: list) -> None:
    with anchored_tree(output) as stage:
        picture = f"picture{video.suffix.lower()}"
        shutil.copyfile(video, stage / picture)
        tracks = []
        for index, entry in enumerate(entries, 1):
            audio = stage / f"mix-{index:03}.wav"
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
            tracks.append(audio)
        _write_page(stage / "index.html", picture, entries, tracks, loop)
        (stage / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_ab_audition(
    video_path,
    mixes,
    output_path,
    *,
    mode="multi_audio",
    loudness_match=True,
    target_lufs=-16.0,
    blind=False,
    loop_start_s=None,
    loop_end_s=None,
):
    """Package premixed, picture-aligned audio alternatives and return an audition receipt."""
    video, output = Path(video_path).absolute(), Path(output_path).absolute()
    if mode not in ("multi_audio", "review_page") or not math.isfinite(target_lufs) or not -70 <= target_lufs <= 0:
        raise MCPVideoError("Invalid audition mode or loudness target", code="invalid_parameter")
    if mode == "multi_audio" and output.suffix.lower() not in (".mp4", ".mkv"):
        raise MCPVideoError("Multi-audio audition output must be MP4 or MKV", code="invalid_parameter")
    loop = [loop_start_s, loop_end_s]
    if loop != [None, None] and (
        None in loop or _nonnegative(loop_start_s, "loop_start_s") >= _nonnegative(loop_end_s, "loop_end_s")
    ):
        raise MCPVideoError("Supply an increasing loop start and end in seconds", code="invalid_parameter")
    record_operation_input(str(video))
    entries = _mix_receipts(mixes, blind=blind, loudness_match=loudness_match, target=target_lufs)
    receipt = {
        "mode": mode,
        "output_path": str(output),
        "video_source": str(video),
        "mixes": entries,
        "loudness_match": loudness_match,
        "target_lufs": target_lufs,
        "blind_key": {entry["display_label"]: entry["label"] for entry in entries} if blind else {},
        "loop_start_s": loop_start_s,
        "loop_end_s": loop_end_s,
    }
    if mode == "multi_audio":
        _mux(video, entries, output)
    else:
        _review(video, entries, output, receipt, loop)
    return receipt
