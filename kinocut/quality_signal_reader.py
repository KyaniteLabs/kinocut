"""Bounded frame metadata streaming with owned child cleanup."""

from array import array
import logging
import os
import subprocess
import threading
import time

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .engine_runtime_utils import _ffprobe, _ffmpeg
from .errors import MCPVideoError, ProcessingError
from .limits import (
    QUALITY_GUARDRAILS_TIMEOUT,
    MAX_QUALITY_SIGNALSTATS_FRAMES,
    MAX_QUALITY_SIGNALSTATS_LINE_BYTES,
    MAX_QUALITY_SIGNALSTATS_OUTPUT_BYTES,
    MAX_QUALITY_SIGNALSTATS_DIAGNOSTIC_BYTES,
    FFMPEG_STDERR_DIAGNOSTIC_BYTES,
)
from .quality_signal_domain import _normalized_signalstat
from . import quality_signal_windows

logger = logging.getLogger(__name__)


_SIGNAL_TAGS = frozenset(
    [
        "YMIN",
        "YLOW",
        "YAVG",
        "YHIGH",
        "YMAX",
        "UMIN",
        "ULOW",
        "UAVG",
        "UHIGH",
        "UMAX",
        "VMIN",
        "VLOW",
        "VAVG",
        "VHIGH",
        "VMAX",
        "SATMIN",
        "SATLOW",
        "SATAVG",
        "SATHIGH",
        "SATMAX",
        "HUEMED",
        "HUEAVG",
        "YDIF",
        "UDIF",
        "VDIF",
        "YBITDEPTH",
        "UBITDEPTH",
        "VBITDEPTH",
    ]
)


class SignalReduction:
    """Compensated means and optionally bounded values for legacy/median callers."""

    def __init__(self, retain_values=False, difference=False):
        self.frames = 0
        self.sums = {}
        self.corrections = {}
        self.counts = {}
        self.values = {} if retain_values else None
        self.difference = difference
        self.hdr = False

    def consume(self, line):
        if not line.strip():
            return
        self.frames += 1
        if self.frames > MAX_QUALITY_SIGNALSTATS_FRAMES:
            raise MCPVideoError("Signalstats frame budget exceeded", code="analysis_over_limit")
        frame, tags = {}, {}
        for entry in line.decode("utf-8", errors="strict").strip().split("|"):
            if not entry:
                continue
            key, value = entry.split("=", 1)
            if key.startswith("tag:lavfi.signalstats.") and key.rsplit(".", 1)[-1] in _SIGNAL_TAGS:
                tags[key[4:]] = value
            elif key in {"pix_fmt", "color_range", "color_transfer"}:
                frame[key] = value
            else:
                raise MCPVideoError("Invalid signalstats field", code="analysis_invalid_output")
        self.hdr |= frame.get("color_transfer") in {"smpte2084", "arib-std-b67"}
        for tag, value in tags.items():
            try:
                number = _normalized_signalstat(frame, tag, value, difference=self.difference)
            except (ValueError, TypeError, MCPVideoError):
                continue
            total = self.sums.get(tag, 0.0)
            combined = total + number
            correction = (total - combined) + number if abs(total) >= abs(number) else (number - combined) + total
            self.corrections[tag] = self.corrections.get(tag, 0.0) + correction
            self.sums[tag] = combined
            self.counts[tag] = self.counts.get(tag, 0) + 1
            if self.values is not None:
                self.values.setdefault(tag, array("d")).append(number)

    def finish(self):
        pass

    def means(self):
        return {tag: (total + self.corrections[tag]) / self.counts[tag] for tag, total in self.sums.items()}


def _consume_stdout(process, reduction, failures, stop):
    try:
        total = 0
        lines = (
            quality_signal_windows.lines(process.stdout, stop)
            if os.name == "nt"
            else iter(lambda: process.stdout.readline(MAX_QUALITY_SIGNALSTATS_LINE_BYTES + 1), b"")
        )
        for line in lines:
            total += len(line)
            if total > MAX_QUALITY_SIGNALSTATS_OUTPUT_BYTES:
                raise MCPVideoError("Signalstats output budget exceeded", code="analysis_over_limit")
            if len(line) > MAX_QUALITY_SIGNALSTATS_LINE_BYTES:
                raise MCPVideoError("Signalstats line budget exceeded", code="analysis_over_limit")
            reduction.consume(line)
    except Exception as exc:
        logger.warning("Signalstats reader stopped (%s)", type(exc).__name__)
        failures.append(
            exc
            if isinstance(exc, MCPVideoError)
            else MCPVideoError("Invalid signalstats output", code="analysis_invalid_output")
        )
        _kill(process, failures)


def _consume_stderr(process, diagnostic, failures, stop):
    try:
        total = 0
        chunks = (
            quality_signal_windows.chunks(process.stderr, stop, FFMPEG_STDERR_DIAGNOSTIC_BYTES)
            if os.name == "nt"
            else iter(lambda: process.stderr.read(FFMPEG_STDERR_DIAGNOSTIC_BYTES), b"")
        )
        for chunk in chunks:
            total += len(chunk)
            if total > MAX_QUALITY_SIGNALSTATS_DIAGNOSTIC_BYTES:
                raise MCPVideoError("Signalstats diagnostic budget exceeded", code="analysis_over_limit")
            room = FFMPEG_STDERR_DIAGNOSTIC_BYTES - len(diagnostic)
            if room > 0:
                diagnostic.extend(chunk[:room])
    except Exception as exc:
        logger.warning("Signalstats reader stopped (%s)", type(exc).__name__)
        failures.append(
            exc
            if isinstance(exc, MCPVideoError)
            else MCPVideoError("Invalid signalstats output", code="analysis_invalid_output")
        )
        _kill(process, failures)


def _kill(process, failures=None):
    try:
        process._kinocut_tree.kill()
    except MCPVideoError as exc:
        if failures is None:
            raise
        failures.append(exc)


def _run_reduction(cmd, reduction):
    """Read every frame, fail on overflow/error, and always reap the owned child."""
    failures, diagnostic = [], bytearray()
    try:
        from .process_tree import ProcessTree

        tree = ProcessTree(cmd)
        process = tree.process
        process._kinocut_tree = tree
    except OSError as exc:
        raise ProcessingError("signalstats backend", -1, "Backend unavailable") from exc
    readers, stop = [], threading.Event()
    deadline = time.monotonic() + QUALITY_GUARDRAILS_TIMEOUT
    try:
        for function, payload in ((_consume_stdout, (reduction, failures)), (_consume_stderr, (diagnostic, failures))):
            reader = threading.Thread(target=function, args=(process, *payload, stop))
            reader.start()
            readers.append(reader)
        try:
            returncode = tree.wait(timeout=QUALITY_GUARDRAILS_TIMEOUT)
        except MCPVideoError:
            if failures:
                raise failures[0] from None
            raise
        for reader in readers:
            reader.join(max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            raise subprocess.TimeoutExpired(cmd, QUALITY_GUARDRAILS_TIMEOUT)
        if failures:
            raise failures[0] from None
        if returncode:
            raise ProcessingError("ffprobe signalstats", returncode, diagnostic.decode(errors="replace"))
        reduction.finish()
        if reduction.hdr:
            logger.warning("HDR transfer observed: SDR signalstats heuristics do not evaluate HDR delivery acceptance")
        return reduction
    finally:
        stop.set()
        try:
            tree.close()
        finally:
            interrupted = False
            join_deadline = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT
            while True:
                try:
                    for reader in readers:
                        reader.join(max(0, join_deadline - time.monotonic()))
                    break
                except KeyboardInterrupt:
                    interrupted = True
            if any(reader.is_alive() for reader in readers):
                raise MCPVideoError("Signalstats readers could not stop", code="process_cleanup_failed")
            process.stdout.close()
            process.stderr.close()
            if interrupted:
                raise KeyboardInterrupt


class MetadataReduction(SignalReduction):
    """FFmpeg fallback emits frame headers and one metadata field per line."""

    def __init__(self):
        super().__init__()
        self.pending = {}
        self.has_header = False

    def consume(self, line):
        text = line.decode("utf-8", errors="strict").strip()
        if text.startswith("frame:"):
            self.finish()
            self.has_header = True
        elif text.startswith("lavfi.signalstats.") and self.has_header:
            key, value = text.split("=", 1)
            if key.rsplit(".", 1)[-1] not in _SIGNAL_TAGS:
                raise MCPVideoError("Signalstats tag budget exceeded", code="analysis_over_limit")
            self.pending[key] = value
        elif text:
            raise MCPVideoError("Invalid signalstats metadata", code="analysis_invalid_output")

    def finish(self):
        if self.pending:
            super().consume("|".join(f"tag:{key}={value}" for key, value in self.pending.items()).encode())
            self.pending.clear()


def read_signalstats(cmd, *, retain_values=False, difference=False):
    cmd = [_ffprobe(), *cmd[1:]]
    cmd[cmd.index("-of") + 1] = "compact=p=0:nk=0"
    return _run_reduction(cmd, SignalReduction(retain_values, difference))


def read_ffmpeg_signalstats(cmd):
    cmd = [_ffmpeg(), "-v", "error", "-nostdin", *cmd[1:]]
    index = cmd.index("-vf") + 1
    cmd[index] = cmd[index].replace("metadata=mode=print", "metadata=mode=print:file=-")
    cmd.insert(-1, "-an")
    return _run_reduction(cmd, MetadataReduction())
