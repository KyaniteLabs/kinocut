"""Extract bounded intents; preserve everything the rules do not understand."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MAX_TEXT = 4000
MAX_LENGTH = 14400.0
_NUMBER = r"\d+(?:\.\d+)?"
_TIME = rf"(?:\d+:\d{{2}}|{_NUMBER}[ -]*(?:minutes?|mins?|m)(?:\s*{_NUMBER}[ -]*(?:seconds?|secs?|s))?|{_NUMBER}[ -]*(?:seconds?|secs?|s))"
_ONES = dict(
    zip(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ],
        range(20),
        strict=True,
    )
)
_TENS = dict(
    zip(["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], range(20, 100, 10), strict=True)
)
_WORDS = {**_ONES, **_TENS, "hundred": 100}


@dataclass
class Direction:
    text: str
    platform: str | None = None
    target_length: float | None = None
    trim_start: float = 0.0
    trim_end: float = 0.0
    remove_silence: bool = False
    captions: bool = False
    loudness: bool = False
    speed: float | None = None
    thumbnail: bool = False
    reframe: bool = False
    mute: bool = False
    assumptions: list[str] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)
    question: str | None = None
    explicit_negation: bool = False
    input_path: str = "input.mp4"
    output_path: str = "input_direct.mp4"


def _numbers(match: re.Match) -> str:
    total = 0
    for word in re.findall(r"[a-z]+", match[0]):
        if word == "hundred":
            total = max(total, 1) * 100
        else:
            total += _WORDS[word]
    return str(total)


def _seconds(value: str) -> float:
    if ":" in value:
        m, s = value.split(":")
        return float(m) * 60 + float(s)
    parts = re.findall(rf"({_NUMBER})[ -]*(minutes?|mins?|m|seconds?|secs?|s)\b", value)
    return sum(float(n) * (60 if unit.startswith("m") else 1) for n, unit in parts)


def _normalize(text: str) -> tuple[str, list]:
    assumptions = []
    if len(text) > MAX_TEXT:
        assumptions.append("Only the first 4000 characters were read; the rest was truncated.")
    text = text[:MAX_TEXT]
    cleaned = "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)
    if cleaned != text:
        assumptions.append("Control characters were stripped.")
    text = cleaned.lower().replace("\u2019", "'")
    text = re.sub(r"\bhalf (?:a |one )?minute\b", "30 seconds", text)
    words = "|".join(_WORDS)
    text = re.sub(rf"\b(?:{words})(?:[ -]+(?:{words}))*\b", _numbers, text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
        if not any("4000" in a for a in assumptions):
            assumptions.append("Normalized text was truncated to 4000 characters.")
    return text, assumptions


def _bounded(d: Direction, value, label):
    if not 0 < value <= MAX_LENGTH:
        d.assumptions.append(f"{label} was limited to 0.01-14400 seconds.")
    return min(MAX_LENGTH, max(0.01, value))


_INTENT_WORDS = {
    "format": r"vertical|portrait|square|landscape|youtube|instagram|tiktok|reels?|shorts|feed|9:16|1:1|16:9",
    "captions": r"captions?|subtitles?",
    "silence": r"silences?|pauses|dead air|tighten",
    "loudness": r"quiet|louder|normalize|balance",
    "thumbnail": r"thumbnail",
    "reframe": r"reframe|face|crop",
    "mute": r"mute|audio|sound",
    "pacing": r"speed|faster|punchier|slow",
    "length": r"skip|cut|lose|remove|drop|trim|seconds?|minutes?",
}


def _clause(text: str, position: int, limit: int | None = None) -> str:
    start = max((m.end() for m in re.finditer(r"[,;.!?]|\b(?:but|then|and)\b", text[:position])), default=0)
    end = re.search(r"[,;.!?]|\b(?:but|then|and)\b", text[position:])
    stop = position + end.start() if end else len(text)
    return text[start : min(stop, limit) if limit is not None else stop]


def _is_negated(match: re.Match, text: str, intent: str) -> bool:
    start = max((m.end() for m in re.finditer(r"[,;.!?]|\b(?:but|then|and)\b", text[: match.start()])), default=0)
    leading_separator = re.match(r"[,;.!?]|\b(?:but|then|and)\b", text[match.start() :])
    if leading_separator:
        start = match.start() + leading_separator.end()
    end = re.search(r"[,;.!?]|\b(?:but|then|and)\b", text[start:])
    stop = start + end.start() if end else len(text)
    clause = text[start:stop]
    local_start = max(0, match.start() - start)
    local_end = min(stop, match.end()) - start
    before = clause[:local_start]
    after = clause[local_end:]
    terms = _INTENT_WORDS[intent]
    negators = re.finditer(
        r"\b(?:no|not|without|don't|do not|never|drop|lose|hide|skip|get rid of|leave|avoid|nothing)\b", before
    )
    denied = any(len(re.findall(r"\w+", before[negator.end() :])) <= 2 for negator in negators) or re.search(
        r"\b(?:is|are|was|were)\s+not\s+(?:needed|wanted|necessary)\b|\bfine as is\b", after
    )
    preserved = intent != "reframe" and re.search(
        rf"\b(?:keep|preserve|retain)\b(?:\s+\w+){{0,3}}\s+(?:{terms})\b", clause
    )
    turned_off = re.search(rf"\b(?:turn|switch) off\b(?:\s+the)?\s+(?:{terms})\b", clause) or re.search(
        rf"\b(?:{terms})\s+off\b", clause
    )
    return bool(denied or preserved or turned_off)


def _take_intent(d: Direction, take, pattern: str, intent: str):
    matches = take(pattern)
    active = [match for match in matches if not _is_negated(match, d.text, intent)]
    denied = len(active) != len(matches)
    d.explicit_negation |= denied
    if denied:
        d.question = d.question or "Should I apply that change, or keep this part as requested?"
        return []
    return active


def _parse_formats(d: Direction, take) -> None:
    formats = _take_intent(
        d,
        take,
        r"\b(?:youtube shorts?|instagram reels?|tiktok|tik tok|reels?|shorts|vertical|portrait|9:16|square|1:1|instagram(?: (?:square|feed))?|feed|youtube|landscape|16:9)\b",
        "format",
    )
    choices = []
    for m in formats:
        value = m[0]
        choices.append(
            "square"
            if value in {"square", "1:1", "feed"} or (value.startswith("instagram") and "reel" not in value)
            else "landscape"
            if value in {"youtube", "landscape", "16:9"}
            else "vertical"
        )
    if choices:
        d.platform = choices[-1]
        if len(set(choices)) > 1:
            d.question = "Which format should I use: vertical, square, or landscape?"
            d.assumptions.append(f"Conflicting formats: the later format ({d.platform}) wins for review.")


def _parse_captions(d: Direction, take) -> None:
    negative_matches = take(
        r"\b(?:no|not|without|don't|do not|never|keep|preserve|retain|remove|drop|lose|hide|skip|avoid|leave)"
        r"(?: add| include| use| want)?(?: the)? (?:captions?|subtitles?)\b"
        r"|\bget rid of(?: the)? (?:captions?|subtitles?)\b"
        r"|\b(?:turn|switch) off (?:the )?(?:captions?|subtitles?)\b"
        r"|\b(?:turn|switch) (?:the )?(?:captions?|subtitles?) off\b"
        r"|\b(?:captions?|subtitles?) off\b"
        r"|\b(?:remove|drop|lose|hide|skip|avoid|leave|get rid of)(?:\s+(?!(?:but|while|then|with)\b|and\s+(?:add|burn|include|put)\b)\w+){0,5}\s+(?:captions?|subtitles?)\b"
        r"|\b(?:captions?|subtitles?)\s+(?:(?:are|is)\s+)?(?:not|aren't|isn't)\s+(?:needed|wanted|necessary)\b"
        r"|\b(?:captions?|subtitles?)\s+(?:(?:are|is)\s+)?(?:unnecessary|optional)\b"
        r"|\b(?:captions?|subtitles?)\b(?:\s+(?!(?:but|while|then|with)\b|and\s+(?:add|burn|include|put)\b)\w+){0,4}\s+(?:removed|deleted|dropped|hidden|skipped|avoided)\b"
        r"|\boptional\s+(?:captions?|subtitles?)\b"
        r"|\b(?:captions?|subtitles?)\s+(?:are\s+)?fine as is\b"
    )
    positives = [
        m
        for m in take(r"\b(?:captions?|subtitles?)\b")
        if not any(n.start() <= m.start() < n.end() for n in negative_matches)
    ]
    negatives = [m for m in negative_matches if re.search(r"captions?|subtitles?", m[0])]
    d.captions = bool(positives) and not negatives
    d.explicit_negation |= bool(negatives)
    if negatives:
        d.question = d.question or "Should captions stay off?"
    if negatives and positives:
        d.assumptions.append("Conflicting caption requests: no captions wins, even if requested earlier.")


def _parse_pacing(d: Direction, take, consumed: list) -> None:
    pacing = _take_intent(
        d,
        take,
        rf"\b(?:speed(?: (?:it|this))? up(?: (?:(?:by|to) )?{_NUMBER}x)?(?: a (?:little|lot))?|speed(?: (?:it|this))? {_NUMBER}x|{_NUMBER}x speed|{_NUMBER}x faster|(?:a lot )?(?:punchier|faster)(?: a lot)?|slow(?: it)? down(?: (?:(?:by|to) )?{_NUMBER}x| to half speed)?)\b",
        "pacing",
    )
    if pacing:
        value = pacing[-1][0]
        numeric = re.search(rf"({_NUMBER})x", value)
        raw = (
            float(numeric[1])
            if numeric
            else 0.5
            if "half speed" in value
            else 0.9
            if "slow" in value
            else 1.25
            if "a lot" in value
            else 1.1
        )
        if numeric and raw <= 1 and ("faster" in value or re.search(r"\bspeed(?: (?:it|this))? up\b", value)):
            d.question = d.question or "What playback speed should I use?"
            return
        if numeric and raw >= 1 and "slow" in value:
            d.question = d.question or "What playback speed should I use?"
            return
        d.speed = min(2.0, max(0.5, raw))
        if raw != d.speed:
            d.assumptions.append("Playback speed was capped to the safe range 0.5-2.0x.")
    for value in re.finditer(rf"\b{_NUMBER}x\b", d.text):
        if any(consumed[value.start() : value.end()]):
            continue
        clause = _clause(d.text, value.start())
        if re.search(r"\b(?:speed(?: (?:it|this))? up|slow(?: it)? down|faster)\b", clause):
            d.speed = None
            d.question = d.question or "What playback speed should I use?"
            return


def _parse_lengths(d: Direction, text: str, consumed: list) -> None:
    lengths = []
    for m in re.finditer(rf"\b{_TIME}\b", text):
        if not any(consumed[m.start() : m.end()]):
            consumed[m.start() : m.end()] = [True] * len(m[0])
            before = text[max(0, m.start() - 48) : m.start()]
            after = text[m.end() : min(len(text), m.end() + 64)]
            edit_offset = next(
                (i for i, used in enumerate(consumed[m.end() : m.end() + len(after)]) if used), len(after)
            )
            position_clause = after[:edit_offset]
            format_word = rf"(?:{_INTENT_WORDS['format']}|clip|short|video|cut|version)"
            after_clause = re.sub(r"^[,;:]\s*", "", after).lstrip()
            next_word = re.match(r"([a-z0-9:]+)", after_clause)
            format_after = re.match(rf"{format_word}\b", after_clause)
            trailing_max = re.match(r"max\b", after_clause)
            after_max = re.sub(r"^max\b\s*", "", after_clause)
            after_max = re.sub(r"^[,;:]\s*", "", after_max)
            after_max = re.sub(r"[,;:.!?]+$", "", after_max).strip()
            format_after_max = re.match(rf"{format_word}\b", after_max)
            simple_suffix = re.fullmatch(r"(?:long|total)(?:\s+please)?|please|or less|at most", after_max)
            edit_after = any(consumed[m.end() : m.end() + len(after)])
            edit_connector = re.match(r"(?:and|then|but|with|for)\b", after_max)
            suffix = re.match(r"(?:or less|at most|long|total|please)\b", after_max)
            suffix_tail = after_max[suffix.end() :].lstrip(" ,;:") if suffix else ""
            suffix_then_edit = bool(suffix and re.match(r"(?:and|then|with|for)\b", suffix_tail) and edit_after)
            max_separator = bool(trailing_max and re.match(r"\s*[,;:]", after_clause[trailing_max.end() :]))
            separated_edit = bool(edit_after and (re.match(r"\s*[,;:]", after) or max_separator or edit_connector))
            format_before = re.search(rf"\b{_INTENT_WORDS['format']}\s*(?:,|\band\b)?\s*$", before)
            allowed_after = bool(
                format_after
                or format_after_max
                or (trailing_max and not after_max)
                or simple_suffix
                or suffix_then_edit
                or separated_edit
            )
            unresolved_after = bool(next_word and not allowed_after and next_word[1] not in {"but", "then"})
            explicit_length = (
                re.search(
                    r"\b(?:make (?:it|this|that)(?: (?:about|around|exactly|approximately|approx(?:imately)?|roughly))?|make (?:a|me a|the video)|keep it(?: to| under)?|cut(?: it)?(?: down)? to|trim(?: it)?(?: down)? to|shorten(?: it)? to|limit it to|set it to|under|at most|max(?:imum)?(?: of)?)\s*$",
                    before,
                )
                or format_before
                or format_after
                or format_after_max
                or (trailing_max and not after_max)
                or simple_suffix
                or suffix_then_edit
            )
            modifier = r"\b(?:shorter|by|before|after|start|end|first|last|at least|hold|appear|middle|bit|add)\b"
            position_after = re.search(
                r"\b(?:from|starting|start|end|first|last|middle|best|between|per|before|after|at least|by|shorter)\b"
                r"|\bof\s+(?:the\s+)?(?!(?:clip|video|format)\b)\w+|\bfor\s+each\b",
                position_clause,
            )
            ambiguous = bool(position_after) or any(
                len(re.findall(r"\w+", before[cue.end() :])) <= 2 for cue in re.finditer(modifier, before)
            )
            less_modifier = re.search(r"\bless\b", after_clause) and not re.match(r"or less\b", after_clause)
            ambiguous |= bool(less_modifier)
            removal_verb = re.search(r"\b(?:cut|remove|drop|lose|chop|shave)\b(?:\s+\w+){0,4}\s*$", before)
            target_connection = re.search(r"\b(?:to|down to)\s*$", before)
            if ambiguous or unresolved_after or (removal_verb and not target_connection) or not explicit_length:
                d.question = d.question or "Should I keep that as the total length, or remove that part?"
            else:
                lengths.append(m)
    if lengths:
        d.target_length = _bounded(d, _seconds(lengths[-1][0]), "Target length")
        if len({_seconds(m[0]) for m in lengths}) > 1:
            d.question = d.question or "Which target length should I use?"
            d.assumptions.append("Conflicting lengths: the later target length wins for review.")


def _unrecognized(text: str, consumed: list) -> list:
    # Remove only grammatical glue. Substantive unknown words remain visible.
    rest = "".join(" " if consumed[i] else c for i, c in enumerate(text))
    rest = re.sub(
        r"\b(?:um|uh|please|and|then|but|with|for|to|a|an|the|this|it|me|my|i|want|can|you|make|give|add|cut|remove|keep|under|max|maximum|at|most|version|it's|is)\b",
        " ",
        rest,
    )
    parts = [part.strip(" ,.!?;:-") for part in re.split(r"[,.;!?]+", rest) if part.strip(" ,.!?;:-")]
    return [re.sub(r"\s+", " ", p) for p in parts]


def parse_direction(text: str) -> Direction:
    """Translate words into intents, never into code, paths, or filter expressions."""
    text, assumptions = _normalize(text)
    d = Direction(text=text, assumptions=assumptions)
    consumed = [False] * len(text)

    def take(pattern):
        matches = list(re.finditer(pattern, text))
        for match in matches:
            consumed[match.start() : match.end()] = [True] * len(match[0])
        return matches

    trim_matches = _take_intent(
        d,
        take,
        rf"\b(?:skip|cut|lose|remove|drop|trim)(?: off)?(?: the)? (?P<side>first|last) (?P<time>{_TIME})\b",
        "length",
    )
    for match in trim_matches:
        label = "start" if match["side"] == "first" else "end"
        setattr(d, f"trim_{label}", _bounded(d, _seconds(match["time"]), f"Trim {label}"))
    if trim_matches:
        for match in _take_intent(
            d, take, rf"\b(?:and|,)\s+(?:the )?(?P<side>first|last) (?P<time>{_TIME})\b", "length"
        ):
            label = "start" if match["side"] == "first" else "end"
            setattr(d, f"trim_{label}", _bounded(d, _seconds(match["time"]), f"Trim {label}"))

    # A time next to a boundary word can mean either removing that section or
    # keeping a target-length excerpt. Without an explicit matching trim form,
    # preserve the intent for review rather than silently treating it as length.
    for _match in take(
        rf"\b(?:{_TIME}\s+(?:off|from)\s+(?:the\s+)?(?:start|beginning|end)|(?:start|beginning|end)\s+(?:by\s+)?{_TIME})\b"
    ):
        d.question = d.question or "Should I remove that amount from the start or end, or keep it as the target length?"
    for match in re.finditer(rf"\b(?:first|last) {_TIME}\b", text):
        span = slice(match.start(), match.end())
        if any(consumed[span]):
            continue
        consumed[span] = [True] * len(match[0])
        d.question = d.question or "Should I remove that amount from the start or end, or keep it as the target length?"

    _parse_formats(d, take)
    _parse_captions(d, take)
    d.remove_silence = bool(
        _take_intent(d, take, r"\b(?:dead air|silences?|pauses|tighten(?: (?:this|it))?(?: up)?)\b", "silence")
    )
    d.loudness = bool(
        _take_intent(d, take, r"\b(?:too quiet|louder|normalize(?: the audio)?|balance (?:the )?audio)\b", "loudness")
    )
    d.thumbnail = bool(_take_intent(d, take, r"\bthumbnail\b", "thumbnail"))
    d.reframe = bool(
        _take_intent(d, take, r"\b(?:reframe|keep (?:the |my )?face in (?:the )?frame|smart crop)\b", "reframe")
    )
    d.mute = bool(
        _take_intent(
            d,
            take,
            r"\b(?:mute(?! (?:the )?(?:\w+ )?music\b)|remove (?:all |the )?audio|no sound)\b",
            "mute",
        )
    )
    _parse_pacing(d, take, consumed)
    _parse_lengths(d, text, consumed)
    d.unrecognized = _unrecognized(text, consumed)
    if re.search(r"\b(?:(?:remove|mute) (?:the )?(?:\w+ )?music|no music)\b", text):
        d.assumptions.append(
            "Separate music removal is not available without model inference; the mixed audio stays unchanged."
        )
    if any(
        re.search(r"\b(?:no|not|without|don't|do not|never|keep|preserve|retain|off|remove)\b", part)
        for part in d.unrecognized
    ):
        d.question = d.question or "Could you clarify what you want to change?"
    return d
