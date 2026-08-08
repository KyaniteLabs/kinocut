"""Caption translation ES-first with honest coverage (P2.9)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable, Mapping

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path, _validate_output_path
from kinocut.intent.language_coverage import language_coverage_report

_CUE_SPLIT = re.compile(r"\n\s*\n")
_TS = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")

# Small deterministic EN→ES map for offline honesty tests (not a full MT system).
_EN_ES: Mapping[str, str] = {
    "hello": "hola",
    "world": "mundo",
    "thanks": "gracias",
    "thank you": "gracias",
    "yes": "sí",
    "no": "no",
    "music": "música",
    "video": "vídeo",
    "welcome": "bienvenidos",
    "subscribe": "suscríbete",
    "like": "me gusta",
    "today": "hoy",
    "tomorrow": "mañana",
}


@dataclass(frozen=True)
class TranslateResult:
    source_path: str
    output_path: str
    source_lang: str
    target_lang: str
    cue_count: int
    backend: str
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def translate_caption_file(
    input_path: str,
    output_path: str | None = None,
    *,
    source_lang: str = "en",
    target_lang: str = "es",
    backend: str = "offline_map",
    translator: Callable[[str, str, str], str] | None = None,
) -> TranslateResult:
    """Translate an SRT file. Never claims unsupported pairs as done."""
    src = Path(_validate_input_path(input_path))
    src_l = source_lang.lower().strip()
    tgt_l = target_lang.lower().strip()
    coverage = language_coverage_report()
    pair = f"{src_l}->{tgt_l}"
    supported = coverage["surfaces"]["translate"]["supported_languages_or_pairs"]
    if pair not in supported and src_l != tgt_l and translator is None:
        raise MCPVideoError(
            f"translate pair {pair!r} not in honest coverage {supported}",
            error_type="validation_error",
            code="unsupported_translate_pair",
        )
    text = src.read_text(encoding="utf-8")
    cues = _parse_srt(text)
    if not cues:
        raise MCPVideoError(
            "no SRT cues found",
            error_type="validation_error",
            code="empty_srt",
        )
    fn = translator or _default_translate
    out_cues: list[tuple[str, str, str]] = []
    for start, end, body in cues:
        if src_l == tgt_l:
            translated = body
            used = "identity"
        else:
            translated = fn(body, src_l, tgt_l)
            used = backend
        out_cues.append((start, end, translated))
    if output_path:
        out_str = _validate_output_path(output_path)
    else:
        out_str = _validate_output_path(str(src.with_name(f"{src.stem}.{tgt_l}.srt")))
    out = Path(out_str)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_srt(out_cues), encoding="utf-8")
    return TranslateResult(
        source_path=str(src),
        output_path=str(out.resolve()),
        source_lang=src_l,
        target_lang=tgt_l,
        cue_count=len(out_cues),
        backend=used if src_l != tgt_l else "identity",
        coverage=coverage,
    )


def _default_translate(text: str, source_lang: str, target_lang: str) -> str:
    if source_lang == target_lang:
        return text
    if source_lang != "en" or target_lang != "es":
        raise MCPVideoError(
            f"offline_map only supports en→es, got {source_lang}→{target_lang}",
            error_type="validation_error",
            code="offline_map_pair",
        )
    # Phrase then word replacements (deterministic, incomplete by design).
    lower = text
    for en, es in sorted(_EN_ES.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(re.escape(en), re.IGNORECASE)
        lower = pattern.sub(es, lower)
    return lower


def _parse_srt(text: str) -> list[tuple[str, str, str]]:
    blocks = [b.strip() for b in _CUE_SPLIT.split(text.strip()) if b.strip()]
    cues: list[tuple[str, str, str]] = []
    for block in blocks:
        lines = block.splitlines()
        # index line optional
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            continue
        m = _TS.search(lines[0])
        if not m:
            continue
        body = "\n".join(lines[1:]).strip()
        cues.append((m.group(1), m.group(2), body))
    return cues


def _render_srt(cues: list[tuple[str, str, str]]) -> str:
    parts: list[str] = []
    for i, (start, end, body) in enumerate(cues, start=1):
        parts.append(f"{i}\n{start} --> {end}\n{body}\n")
    return "\n".join(parts)
