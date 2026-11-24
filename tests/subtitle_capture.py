"""Test-owned evidence for distinguishing caption conversion from burn loss."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path


class SubtitleCapture:
    """Retain synthetic ASS bytes and successful diagnostics before cleanup."""

    def __init__(self, root: Path, monkeypatch):
        from kinocut import engine_subtitles, subtitles_common

        self.root = root / "subtitle-evidence"
        self.root.mkdir()
        self.evidence = {"stages": {}}
        conversion = subtitles_common._run_ffmpeg
        burn = engine_subtitles._run_ffmpeg
        staging = subtitles_common.staged_burn_source

        def convert(args, **kwargs):
            result = conversion(args, **kwargs)
            self.record("conversion", Path(args[-1]).read_bytes(), result)
            return result

        @contextmanager
        def stage(*args, **kwargs):
            with staging(*args, **kwargs) as source:
                self.record("staged", Path(source.path).read_bytes())
                yield source

        def render(args, **kwargs):
            result = burn(args, **kwargs)
            self.record("burn", result=result)
            return result

        monkeypatch.setattr(subtitles_common, "_run_ffmpeg", convert)
        monkeypatch.setattr(subtitles_common, "staged_burn_source", stage)
        monkeypatch.setattr(engine_subtitles, "staged_burn_source", stage)
        monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", render)

    def record(self, stage, content=None, result=None):
        entry = self.evidence["stages"].setdefault(stage, {})
        if content is not None:
            (self.root / f"{stage}.ass").write_bytes(content)
            lines = content.decode("utf-8", errors="replace").splitlines()
            entry.update(
                sha256=hashlib.sha256(content).hexdigest(),
                byte_count=len(content),
                dialogue_count=sum(line.startswith("Dialogue:") for line in lines),
                playres=[line for line in lines if line.startswith(("PlayResX:", "PlayResY:"))],
            )
        if result is not None:
            stderr = result.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            # Raw synthetic diagnostics stay in the test-owned evidence folder.
            (self.root / f"{stage}.stderr.txt").write_text(stderr[-16384:], encoding="utf-8")
            entry["returncode"] = result.returncode
        self._save()

    def pixels(self, source, output, dimensions, bottom, top):
        self.evidence.update(
            source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            output_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),
            dimensions=dimensions,
            caption_region_peak=bottom,
            header_region_peak=top,
        )
        self._save()

    def _save(self):
        (self.root / "capture.json").write_text(json.dumps(self.evidence, indent=2), encoding="utf-8")
