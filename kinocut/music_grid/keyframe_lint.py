"""Lint literal authoring times without executing a composition's code."""

from html.parser import HTMLParser
import re

from .grid import validate_edit_points

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def snap_duration_to_grid(duration_s, grid):
    return grid.nearest(duration_s, duration=True)


def _seconds(text):
    match = re.fullmatch(rf"({_NUMBER})(ms|s)?", str(text).strip())
    if not match:
        raise ValueError("Expected literal seconds or milliseconds")
    return float(match[1]) / (1000 if match[2] == "ms" else 1)


def _event_points(event):
    name = event.get("name", "event")
    if "time" in event:
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
    for call in re.finditer(r"\bgsap\.to\s*\(([^;]*?)\)\s*;?", text):
        match = re.fullmatch(r"\s*([^,]+),\s*\{([^{}]*)\}\s*", call[1])
        if not match:
            raise ValueError("Unsupported GSAP tween; supply resolved timeline events")
        props = dict((key.strip(), val.strip()) for key, val in re.findall(r"(\w+)\s*:\s*([^,}]+)", match[2]))
        yield from _event_points(
            dict(name=match[1].strip(" \"'"), start=props.get("delay", 0), duration=props.get("duration", ""))
        )


def _css(text):
    keyframes = {}
    for block in re.finditer(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", text):
        selectors = re.findall(r"([^{}]+)\{[^{}]*\}", block[2])
        stops = re.findall(rf"({_NUMBER})\s*%", ",".join(selectors))
        keyframes[block[1]] = [float(stop) / 100 for stop in stops]
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        props = dict(
            (key.strip(), val.strip()) for key, val in re.findall(r"(animation-[\w-]+)\s*:\s*([^;}}]+)", rule[2])
        )
        if "animation-duration" not in props:
            continue
        start = _seconds(props.get("animation-delay", 0))
        duration = _seconds(props["animation-duration"])
        name = props.get("animation-name", rule[1].strip())
        yield from _event_points(dict(name=name, start=start, duration=duration))
        for stop in keyframes.get(name, []):
            yield f"{name}.{100 * stop:g}%", start + stop * duration


class _Composition(HTMLParser):
    def __init__(self):
        super().__init__()
        self.points = []
        self.block = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in ("script", "style"):
            self.block = tag
        if "data-start" in values or "data-duration" in values:
            event = {key[5:]: value for key, value in attrs if key.startswith("data-")}
            self.points.extend(_event_points(dict(event, name=values.get("id", tag))))
        if "style" in values:
            self.points.extend(_css("inline {" + values["style"] + "}"))

    def handle_endtag(self, tag):
        if tag == self.block:
            self.block = None

    def handle_data(self, data):
        if self.block == "style":
            self.points.extend(_css(data))
        elif self.block == "script":
            self.points.extend(_gsap(data))


def lint_composition_keyframes(source_html_or_events, grid, *, tolerance_ms=2.0):
    source = source_html_or_events
    if isinstance(source, str):
        parser = _Composition()
        if "<" in source:
            parser.feed(source)
            parser.close()
            points = parser.points
        else:
            points = [*_gsap(source), *_css(source)]
    else:
        points = [point for event in source for point in _event_points(event)]
    result = validate_edit_points((time for _, time in points), grid, tolerance_ms)
    rows = [dict(row, name=name) for (name, _), row in zip(points, result["points"], strict=True)]
    return dict(grid=result["grid"], keyframes=rows, passed=bool(rows) and result["passed"])
