"""Lint literal authoring times without executing a composition's code."""

from html.parser import HTMLParser
from fractions import Fraction
from typing import TypedDict
import re

from .grid import PointReceipt, validate_edit_points

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def snap_duration_to_grid(duration_s, grid):
    return grid.nearest(duration_s, duration=True)


def _seconds(text):
    if isinstance(text, Fraction):
        return text
    match = re.fullmatch(rf"({_NUMBER})(ms|s)?", str(text).strip())
    if not match:
        raise ValueError("Expected literal seconds or milliseconds")
    return Fraction(match[1]) / (1000 if match[2] == "ms" else 1)


def _event_points(event):
    name = event.get("name", "event")
    if "time" in event:
        if event.keys() - {"name", "time"}:
            raise ValueError("Expected standalone time or a timed interval")
        yield name, _seconds(event["time"])
        return
    start = _seconds(event.get("start", 0))
    if "start" in event or "duration" in event:
        yield f"{name}.start", start
    for key in ("ease", "end", "fade_end", "fade_in", "fade_out"):
        if key in event:
            yield f"{name}.{key}", _seconds(event[key])
    if "duration" in event:
        yield f"{name}.end", start + _seconds(event["duration"])
    elif not any(key in event for key in ("start", "ease", "end", "fade_end", "fade_in", "fade_out")):
        raise ValueError("No literal time for structured event")


def _gsap(text):
    for statement in filter(None, (part.strip() for part in text.split(";"))):
        match = re.fullmatch(r"""gsap\.to\s*\(\s*(\w+|"[^"()]*"|'[^'()]*')\s*,\s*\{([^{}]*)\}\s*\)""", statement)
        if not match:
            raise ValueError("Unsupported GSAP tween; supply resolved timeline events")
        props = {}
        raw_entries = [part.strip() for part in match[2].split(",")]
        if raw_entries and raw_entries[-1] == "":
            raw_entries.pop()
        if not raw_entries:
            raise ValueError("Expected literal supported GSAP properties")
        for entry in raw_entries:
            num_prop = re.fullmatch(rf"(duration|delay|x|y|opacity|scale|rotation)\s*:\s*({_NUMBER})", entry)
            ease_prop = re.fullmatch(r"""ease\s*:\s*(?:"[^"']*"|'[^"']*')""", entry)
            if num_prop:
                if num_prop[1] in props:
                    raise ValueError("Expected literal supported GSAP properties")
                props[num_prop[1]] = num_prop[2]
            elif ease_prop:
                if "ease" in props:
                    raise ValueError("Expected literal supported GSAP properties")
                props["ease"] = entry
            else:
                raise ValueError("Expected literal supported GSAP properties")
        if "duration" not in props:
            raise ValueError("Expected literal duration in GSAP tween")
        dur = _seconds(props["duration"])
        if dur < 0:
            raise ValueError("GSAP duration must be non-negative")
        yield from _event_points(dict(name=match[1].strip(" \"'"), start=props.get("delay", 0), duration=dur))


def _strip_css_comments(text: str) -> str:
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if "/*" in cleaned or "*/" in cleaned:
        raise ValueError("Unclosed CSS comment")
    return cleaned


def _css_blocks(blocks):
    keyframes: dict[str, list[Fraction]] = {}
    rule_pattern = r"([^{}@;()]+)\{([^{}]*)\}"
    cleaned_blocks: list[str] = []
    for raw in blocks:
        text = _strip_css_comments(raw)
        if re.search(r"(?:animation(?!-(?:duration|name|delay)\s*:)|transition)[\w-]*\s*:|@import|\\", text, re.I):
            raise ValueError("Unsupported CSS timing; supply resolved timeline events")
        for block in re.finditer(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", text):
            selectors = re.findall(r"([^{}]+)\{[^{}]*\}", block[2])
            parsed_stops: list[Fraction] = []
            for raw_sel in ",".join(selectors).split(","):
                sel = raw_sel.strip()
                if sel == "from":
                    parsed_stops.append(Fraction(0))
                elif sel == "to":
                    parsed_stops.append(Fraction(1))
                else:
                    pct_match = re.fullmatch(rf"({_NUMBER})\s*%", sel)
                    if not pct_match:
                        raise ValueError("Unsupported keyframe selector")
                    pct = Fraction(pct_match[1])
                    if pct < 0 or pct > 100:
                        raise ValueError("Keyframe percentage must be between 0% and 100%")
                    parsed_stops.append(pct / 100)
            keyframes[block[1]] = parsed_stops
        body = re.sub(r"@keyframes\s+[\w-]+\s*\{((?:[^{}]|\{[^{}]*\})*)\}", "", text)
        if re.sub(rule_pattern, "", body).strip():
            raise ValueError("Unsupported stylesheet structure")
        cleaned_blocks.append(body)
    for body in cleaned_blocks:
        for rule in re.finditer(rule_pattern, body):
            props = dict(
                (key.lower(), val.strip())
                for key, val in re.findall(r"(animation-[\w-]+)\s*:\s*([^;}}]+)", rule[2], re.I)
            )
            if "animation-duration" not in props:
                if props:
                    raise ValueError("Unresolved CSS duration")
                continue
            start = _seconds(props.get("animation-delay", 0))
            duration = _seconds(props["animation-duration"])
            if duration < 0:
                raise ValueError("CSS animation-duration must be non-negative")
            name = props.get("animation-name", rule[1].strip())
            if "animation-name" in props:
                if not re.fullmatch(r"[\w-]+", name):
                    raise ValueError("Unresolved CSS animation name")
                if name == "none":
                    continue
                if name not in keyframes:
                    raise ValueError(f"Unresolved CSS @keyframes: {name}")
            yield from _event_points(dict(name=name, start=start, duration=duration))
            for stop in keyframes.get(name, []):
                yield f"{name}.{float(100 * stop):g}%", start + stop * duration


def _css(text):
    yield from _css_blocks([text])


class _Composition(HTMLParser):
    def __init__(self):
        super().__init__()
        self.points = []
        self.css_blocks: list[str] = []
        self.script_blocks: list[str] = []
        self.block = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if (
            (tag == "script" and "src" in values)
            or (tag == "link" and "stylesheet" in (values.get("rel") or "").lower())
            or tag.startswith("animate")
            or tag in ("discard", "set", "iframe", "object", "embed")
            or any(key.startswith("on") for key in values)
        ):
            raise ValueError("Unresolved embedded timing")
        if tag in ("script", "style"):
            self.block = tag
            self._buffer = []
        if "data-start" in values or "data-duration" in values:
            event = {key[5:]: value for key, value in attrs if key.startswith("data-")}
            event_name = values.get("id") or event.get("name") or tag
            self.points.extend(_event_points(dict(event, name=event_name)))
        if "style" in values:
            self.css_blocks.append("inline {" + (values["style"] or "") + "}")

    def handle_endtag(self, tag):
        if tag == self.block:
            content = "".join(self._buffer)
            if self.block == "style":
                self.css_blocks.append(content)
            elif self.block == "script":
                self.script_blocks.append(content)
            self.block = None
            self._buffer = []

    def handle_data(self, data):
        if self.block in ("style", "script"):
            self._buffer.append(data)


def _points(source):
    if isinstance(source, str):
        parser = _Composition()
        if source.lstrip().startswith("<"):
            parser.feed(source)
            parser.close()
            if parser.block is not None:
                raise ValueError("Unclosed composition block")
            if parser.css_blocks:
                parser.points.extend(_css_blocks(parser.css_blocks))
            for script in parser.script_blocks:
                parser.points.extend(_gsap(script))
            return parser.points
        return list(_css(source) if re.match(r"\s*(?:@|[^{};()]+\{)", source) else _gsap(source))
    return [point for event in source for point in _event_points(event)]


class Keyframe(PointReceipt):
    name: str


class LintReceipt(TypedDict):
    grid: dict
    keyframes: list[Keyframe]
    errors: list[str]
    passed: bool


def lint_composition_keyframes(source_html_or_events, grid, *, tolerance_ms=2.0) -> LintReceipt:
    try:
        points = _points(source_html_or_events)
    except ValueError as exc:
        return LintReceipt(grid=grid.receipt(), keyframes=[], errors=[str(exc)], passed=False)
    result = validate_edit_points((time for _, time in points), grid, tolerance_ms)
    rows = [Keyframe(**row, name=name) for (name, _), row in zip(points, result["points"], strict=True)]
    return LintReceipt(grid=result["grid"], keyframes=rows, passed=bool(rows) and result["passed"], errors=[])
