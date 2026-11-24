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
        for entry in match[2].split(","):
            prop = re.fullmatch(rf"\s*(duration|delay|x|y|opacity|scale|rotation)\s*:\s*({_NUMBER})\s*", entry)
            if not prop or prop[1] in props:
                raise ValueError("Expected literal supported GSAP properties")
            props[prop[1]] = prop[2]
        yield from _event_points(
            dict(name=match[1].strip(" \"'"), start=props.get("delay", 0), duration=props.get("duration", ""))
        )


def _css(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if re.search(r"(?:animation(?!-(?:duration|name|delay)\s*:)|transition)[\w-]*\s*:|@import|\\", text, re.I):
        raise ValueError("Unsupported CSS timing; supply resolved timeline events")
    keyframes = {}
    for block in re.finditer(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", text):
        selectors = re.findall(r"([^{}]+)\{[^{}]*\}", block[2])
        if any(
            not re.fullmatch(rf"\s*(?:from|to|{_NUMBER}\s*%)\s*", selector)
            for selector in ",".join(selectors).split(",")
        ):
            raise ValueError("Unsupported keyframe selector")
        stops = re.findall(rf"({_NUMBER})\s*%", ",".join(selectors))
        keyframes[block[1]] = [Fraction(stop) / 100 for stop in stops]
    text = re.sub(r"@keyframes\s+[\w-]+\s*\{((?:[^{}]|\{[^{}]*\})*)\}", "", text)
    rule_pattern = r"([^{}@;()]+)\{([^{}]*)\}"
    if re.sub(rule_pattern, "", text).strip():
        raise ValueError("Unsupported stylesheet structure")
    for rule in re.finditer(rule_pattern, text):
        props = dict(
            (key.lower(), val.strip()) for key, val in re.findall(r"(animation-[\w-]+)\s*:\s*([^;}}]+)", rule[2], re.I)
        )
        if "animation-duration" not in props:
            if props:
                raise ValueError("Unresolved CSS duration")
            continue
        start = _seconds(props.get("animation-delay", 0))
        duration = _seconds(props["animation-duration"])
        name = props.get("animation-name", rule[1].strip())
        if "animation-name" in props and not re.fullmatch(r"[\w-]+", name):
            raise ValueError("Unresolved CSS animation name")
        yield from _event_points(dict(name=name, start=start, duration=duration))
        for stop in keyframes.get(name, []):
            yield f"{name}.{float(100 * stop):g}%", start + stop * duration


class _Composition(HTMLParser):
    def __init__(self):
        super().__init__()
        self.points = []
        self.block = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if (
            (tag == "script" and "src" in values)
            or (tag == "link" and "stylesheet" in (values.get("rel") or "").lower())
            or tag in ("animate", "animatetransform", "set", "iframe")
            or any(key.startswith("on") for key in values)
        ):
            raise ValueError("Unresolved embedded timing")
        if tag in ("script", "style"):
            self.block = tag
        if "data-start" in values or "data-duration" in values:
            event = {key[5:]: value for key, value in attrs if key.startswith("data-")}
            self.points.extend(_event_points(dict(event, name=values.get("id", tag))))
        if "style" in values:
            self.points.extend(_css("inline {" + (values["style"] or "") + "}"))

    def handle_endtag(self, tag):
        if tag == self.block:
            self.block = None

    def handle_data(self, data):
        if self.block == "style":
            self.points.extend(_css(data))
        elif self.block == "script":
            self.points.extend(_gsap(data))


def _points(source):
    if isinstance(source, str):
        parser = _Composition()
        if source.lstrip().startswith("<"):
            parser.feed(source)
            parser.close()
            if parser.block is not None:
                raise ValueError("Unclosed composition block")
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
