"""Caption translation ES-first with honest coverage (P2.9)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable, Mapping

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path, _validate_output_path
from kinocut.intent.language_coverage import language_coverage_report
from kinocut_sound.captions import _parse_srt as _parse_srt

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

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


@dataclass(frozen=True)
class TranslateResult:
    source_path: str
    output_path: str
    source_lang: str
    target_lang: str
    cue_count: int
    backend: str
    coverage: dict[str, Any]
    # Offline-map bookkeeping: how much of the source the word list actually
    # covered. ``translated_words`` stays None for external translators, whose
    # coverage this module cannot observe.
    translated_words: int | None = None
    total_words: int = 0
    untranslated_cues: int = 0
    warnings: list[str] = field(default_factory=list)

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
            f"translate pair is not in honest coverage {supported}",
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
    translated_words: int | None = None
    total_words = 0
    untranslated_cues = 0
    for start, end, body in cues:
        if src_l == tgt_l:
            translated = body
            used = "identity"
        else:
            words_in_cue = len(_WORD.findall(body))
            if translator is None:
                translated, matched = _offline_map_translate(body, src_l, tgt_l)
                translated_words = (translated_words or 0) + matched
                total_words += words_in_cue
                if words_in_cue and matched == 0:
                    untranslated_cues += 1
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
    warnings: list[str] = []
    if translated_words is not None and total_words and translated_words < total_words:
        percent = round(100 * translated_words / total_words)
        warnings.append(
            f"{backend} replaced {translated_words} of {total_words} words ({percent}%); "
            f"{untranslated_cues} of {len(out_cues)} cues have no translation at all. "
            "Treat this as a partial translation and review it before publishing."
        )
    return TranslateResult(
        source_path=str(src),
        output_path=str(out.resolve()),
        source_lang=src_l,
        target_lang=tgt_l,
        cue_count=len(out_cues),
        backend=used if src_l != tgt_l else "identity",
        coverage=coverage,
        translated_words=translated_words,
        total_words=total_words,
        untranslated_cues=untranslated_cues,
        warnings=warnings,
    )


def _offline_map_translate(text: str, source_lang: str, target_lang: str) -> tuple[str, int]:
    """Replace whole words only; return the text and the number of source words replaced."""
    if source_lang != "en" or target_lang != "es":
        raise MCPVideoError(
            f"offline_map only supports en→es, got {source_lang}→{target_lang}",
            error_type="validation_error",
            code="offline_map_pair",
        )
    replaced_words = 0
    # Longest keys first so phrases win over their component words.
    for en, es in sorted(_EN_ES.items(), key=lambda kv: -len(kv[0])):
        # Lookaround instead of \b: \b would also match inside "don't" style tokens.
        pattern = re.compile(r"(?<!\w)" + re.escape(en) + r"(?!\w)", re.IGNORECASE)

        def _swap(match: re.Match[str], replacement: str = es) -> str:
            nonlocal replaced_words
            replaced_words += len(_WORD.findall(match.group(0)))
            if match.group(0)[0].isupper():
                return replacement[0].upper() + replacement[1:]
            return replacement

        text = pattern.sub(_swap, text)
    return text, replaced_words


def _default_translate(text: str, source_lang: str, target_lang: str) -> str:
    if source_lang == target_lang:
        return text
    return _offline_map_translate(text, source_lang, target_lang)[0]


def _render_srt(cues: list[tuple[str, str, str]]) -> str:
    parts: list[str] = []
    for i, (start, end, body) in enumerate(cues, start=1):
        parts.append(f"{i}\n{start} --> {end}\n{body}\n")
    return "\n".join(parts)
