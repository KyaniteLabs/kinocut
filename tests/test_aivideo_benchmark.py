"""Versioned AI-video acceptance benchmark (#61)."""

from __future__ import annotations

from kinocut.aivideo.benchmark import (
    AIVIDEO_CORPUS,
    BenchmarkReceipt,
    run_aivideo_benchmark,
)


def _diagnostics(ffmpeg_ok: bool, whisper_ok: bool = False, ffmpeg_version: str = "n8.1"):
    return {
        "success": True,
        "checks": [
            {"name": "ffmpeg", "category": "core", "required": True, "ok": ffmpeg_ok, "version": ffmpeg_version},
            {"name": "ffprobe", "category": "core", "required": True, "ok": ffmpeg_ok},
            {"name": "openai-whisper", "category": "optional", "required": False, "ok": whisper_ok},
        ],
    }


def test_corpus_is_versioned_and_nonempty():
    assert AIVIDEO_CORPUS.corpus_version == "ai-video-v1"
    assert len(AIVIDEO_CORPUS.items) >= 4
    ids = [item.item_id for item in AIVIDEO_CORPUS.items]
    assert len(set(ids)) == len(ids)


def test_benchmark_receipt_records_one_result_per_corpus_item():
    receipt = run_aivideo_benchmark(diagnostics=_diagnostics(ffmpeg_ok=True, whisper_ok=True))
    assert isinstance(receipt, BenchmarkReceipt)
    assert receipt.corpus_version == "ai-video-v1"
    assert len(receipt.results) == len(AIVIDEO_CORPUS.items)
    assert {r.item_id for r in receipt.results} == {item.item_id for item in AIVIDEO_CORPUS.items}


def test_benchmark_all_pass_when_deps_present():
    receipt = run_aivideo_benchmark(diagnostics=_diagnostics(ffmpeg_ok=True, whisper_ok=True))
    assert receipt.passed_count == len(AIVIDEO_CORPUS.items)
    assert receipt.failed_count == 0
    assert all(r.availability == "available" for r in receipt.results)


def test_benchmark_flags_failed_items_when_required_dep_missing():
    receipt = run_aivideo_benchmark(diagnostics=_diagnostics(ffmpeg_ok=False))
    assert receipt.failed_count >= 1
    assert receipt.passed_count < len(AIVIDEO_CORPUS.items)
    edit = next(r for r in receipt.results if r.item_id == "edit_mp4")
    assert edit.availability == "unavailable"


def test_benchmark_receipt_captures_toolchain_versions():
    receipt = run_aivideo_benchmark(diagnostics=_diagnostics(ffmpeg_ok=True, ffmpeg_version="n7.1.5"))
    assert receipt.ffmpeg_version == "n7.1.5"
    # kinocut_version is best-effort; it is either a string or None, never absent.
    assert receipt.kinocut_version is None or isinstance(receipt.kinocut_version, str)
