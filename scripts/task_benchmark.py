#!/usr/bin/env python3
"""Task-level benchmark: do agents finish real edits with fewer tokens, calls and retries?

Listing size (bytes, tokens) is a proxy for how good an MCP surface is. This
script measures the thing itself. It runs a fixed set of everyday edits
(``TASKS``) against one or more Kinocut MCP servers with one or more models,
then checks each output file with ffprobe and reports, per server and model:

- success: how many edits produced the requested output;
- tokens: model input plus output tokens per task;
- calls: tool calls per task;
- retries: tool calls that came back as errors.

Each server is a ``label=command`` pair, so two releases compare side by side::

    python scripts/task_benchmark.py \\
        --server "1.16.5=uvx --from kinocut==1.16.5 kinocut --mcp" \\
        --server "2.0=uvx --from kinocut==2.0.1 kinocut --mcp" \\
        --model anthropic:claude-sonnet-5-5 --model openai:gpt-5.5 \\
        --out bench.json

Real runs call paid model APIs with the keys in ``ANTHROPIC_API_KEY`` and
``OPENAI_API_KEY`` (``OPENAI_BASE_URL`` points the OpenAI-style client at
another official endpoint). ``--dry-run`` swaps in a scripted model that costs
nothing and checks the plumbing end to end against the local checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from collections.abc import Callable
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 12
RESULT_CHARS = 20_000
SYSTEM_PROMPT = (
    "You are a video editing agent. Use the Kinocut tools to complete the edit. "
    "Write the result to exactly the output path given. Reply with one short line when done."
)

Probe = dict[str, Any]


# ── Edits ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    output: str
    check: Callable[[Probe, Probe], bool]


def _duration(probe: Probe) -> float:
    return float(probe.get("format", {}).get("duration") or 0.0)


def _video(probe: Probe) -> dict[str, Any]:
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})


def _has_audio(probe: Probe) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe.get("streams", []))


def _near(value: float, target: float, tolerance: float = 0.6) -> bool:
    return abs(value - target) <= tolerance


def _fps(probe: Probe) -> float:
    num, _, den = str(_video(probe).get("avg_frame_rate", "0/1")).partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


TASKS: tuple[Task, ...] = (
    Task("trim", "Cut {src} down to the part from 2s to 5s.", "trim.mp4", lambda o, s: _near(_duration(o), 3.0)),
    Task("resize", "Resize {src} to 640x360.", "resize.mp4", lambda o, s: _video(o).get("width") == 640),
    Task(
        "webm", "Convert {src} to WebM.", "convert.webm", lambda o, s: o["format"]["format_name"].startswith("matroska")
    ),
    Task("audio", "Extract the audio of {src} as an MP3.", "audio.mp3", lambda o, s: _has_audio(o) and not _video(o)),
    Task("mute", "Remove the audio track from {src}.", "mute.mp4", lambda o, s: not _has_audio(o) and bool(_video(o))),
    Task("speed", "Make {src} play twice as fast.", "speed.mp4", lambda o, s: _near(_duration(o), _duration(s) / 2)),
    Task(
        "square",
        "Crop {src} to a centred square.",
        "square.mp4",
        lambda o, s: _video(o).get("width") == _video(o).get("height"),
    ),
    Task("reverse", "Play {src} backwards.", "reverse.mp4", lambda o, s: _near(_duration(o), _duration(s))),
    Task(
        "rotate",
        "Rotate {src} 90 degrees clockwise.",
        "rotate.mp4",
        lambda o, s: _video(o).get("width") == _video(s).get("height"),
    ),
    Task(
        "thumbnail",
        "Save a still frame of {src} at 3 seconds as a PNG.",
        "thumb.png",
        lambda o, s: _video(o).get("codec_name") == "png",
    ),
    Task("text", "Put the title 'Hello' over {src}.", "text.mp4", lambda o, s: _near(_duration(o), _duration(s))),
    Task(
        "fade", "Fade {src} in from black and out to black.", "fade.mp4", lambda o, s: _near(_duration(o), _duration(s))
    ),
    Task(
        "merge",
        "Join {src} with itself, end to end.",
        "merge.mp4",
        lambda o, s: _near(_duration(o), 2 * _duration(s), 1.0),
    ),
    Task(
        "gif",
        "Make a GIF of the first 2 seconds of {src}.",
        "clip.gif",
        lambda o, s: _video(o).get("codec_name") == "gif",
    ),
    Task("fps", "Change {src} to 15 frames per second.", "fps.mp4", lambda o, s: _near(_fps(o), 15.0, 0.5)),
    Task(
        "compress",
        "Compress {src} so the file is smaller.",
        "small.mp4",
        lambda o, s: int(o["format"]["size"]) < int(s["format"]["size"]),
    ),
    Task(
        "vertical",
        "Make a 9:16 vertical version of {src} for Shorts.",
        "vertical.mp4",
        lambda o, s: _video(o).get("height", 0) > _video(o).get("width", 0),
    ),
    Task(
        "volume",
        "Halve the volume of {src}.",
        "quiet.mp4",
        lambda o, s: _has_audio(o) and _near(_duration(o), _duration(s)),
    ),
    Task("loop", "Loop {src} so it plays twice.", "loop.mp4", lambda o, s: _near(_duration(o), 2 * _duration(s), 1.0)),
    Task("grayscale", "Make {src} black and white.", "gray.mp4", lambda o, s: _near(_duration(o), _duration(s))),
)


def ffprobe(path: Path) -> Probe | None:
    if not path.is_file():
        return None
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return json.loads(proc.stdout) if proc.returncode == 0 else None


def make_source(workdir: Path) -> Path:
    """A 10 s 1280x720 30 fps clip with a tone, so every edit has video and audio to work on."""
    src = workdir / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        check=True,
        timeout=120,
    )
    return src


def task_passed(task: Task, output: Path, source: Probe) -> bool:
    probe = ffprobe(output)
    if probe is None:
        return False
    try:
        return bool(task.check(probe, source))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


# ── Models ───────────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Turn:
    calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0


class Model(Protocol):
    label: str

    def start(self, prompt: str, tools: list[dict[str, Any]]) -> None: ...
    async def step(self) -> Turn: ...
    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None: ...


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=300)
    response.raise_for_status()
    return response.json()


class AnthropicModel:
    """Anthropic Messages API, official endpoint only."""

    def __init__(self, model: str) -> None:
        self.label, self.model = f"anthropic:{model}", model
        self.headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}

    def start(self, prompt: str, tools: list[dict[str, Any]]) -> None:
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in tools]
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    async def step(self) -> Turn:
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "tools": self.tools,
            "messages": self.messages,
        }
        data = await asyncio.to_thread(_post, "https://api.anthropic.com/v1/messages", self.headers, body)
        self.messages.append({"role": "assistant", "content": data["content"]})
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data["content"] if b["type"] == "tool_use"]
        usage = data.get("usage", {})
        # Cached prompt tokens are reported apart from input_tokens; all three are input.
        prompt = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        return Turn(calls, prompt, usage.get("output_tokens", 0))

    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        blocks = [
            {"type": "tool_result", "tool_use_id": c.id, "content": text, "is_error": err} for c, text, err in results
        ]
        self.messages.append({"role": "user", "content": blocks})


class OpenAIModel:
    """OpenAI-style chat completions; ``OPENAI_BASE_URL`` must be the model owner's official endpoint."""

    def __init__(self, model: str) -> None:
        self.label, self.model = f"openai:{model}", model
        self.url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}

    def start(self, prompt: str, tools: list[dict[str, Any]]) -> None:
        self.tools = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]},
            }
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    async def step(self) -> Turn:
        body = {"model": self.model, "messages": self.messages, "tools": self.tools}
        data = await asyncio.to_thread(_post, self.url, self.headers, body)
        message = data["choices"][0]["message"]
        self.messages.append(message)
        calls = [
            ToolCall(c["id"], c["function"]["name"], json.loads(c["function"].get("arguments") or "{}"))
            for c in message.get("tool_calls") or []
        ]
        usage = data.get("usage", {})
        return Turn(calls, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        self.messages += [{"role": "tool", "tool_call_id": c.id, "content": text} for c, text, _ in results]


class ScriptedModel:
    """Free stand-in for ``--dry-run`` and tests: plays back fixed tool calls, then stops.

    ``script`` maps a tool name to its arguments, one call per turn. Tokens are the
    character count of what the model would have read and written, divided by four.
    """

    def __init__(self, script: list[tuple[str, dict[str, Any]]], label: str = "scripted") -> None:
        self.label, self.script = label, script

    def start(self, prompt: str, tools: list[dict[str, Any]]) -> None:
        self.pending = list(self.script)
        self.context = len(prompt) + len(json.dumps(tools))

    async def step(self) -> Turn:
        if not self.pending:
            return Turn([], self.context // 4, 2)
        name, args = self.pending.pop(0)
        return Turn([ToolCall(f"call-{len(self.pending)}", name, args)], self.context // 4, len(json.dumps(args)) // 4)

    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        self.context += sum(len(text) for _, text, _ in results)


def build_model(spec: str) -> Model:
    provider, _, name = spec.partition(":")
    if provider == "anthropic" and name:
        return AnthropicModel(name)
    if provider == "openai" and name:
        return OpenAIModel(name)
    raise SystemExit(f"--model must be anthropic:<id> or openai:<id>, got {spec!r}")


# ── Agent loop ───────────────────────────────────────────────────────────────


class ToolSession(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


@dataclass
class TaskResult:
    server: str
    model: str
    task: str
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    retries: int = 0
    turns: int = 0
    error: str | None = None


def result_text(result: Any) -> tuple[str, bool]:
    """Flatten an MCP tool result and decide whether the agent would read it as a failure."""
    text = "\n".join(getattr(part, "text", "") for part in getattr(result, "content", []) or [])[:RESULT_CHARS]
    failed = bool(getattr(result, "isError", False))
    if not failed:
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        failed = isinstance(payload, dict) and (payload.get("success") is False or "error" in payload)
    return text, failed


async def run_task(
    session: ToolSession, model: Model, tools: list[dict[str, Any]], prompt: str, row: TaskResult
) -> None:
    model.start(prompt, tools)
    for _ in range(MAX_TURNS):
        turn = await model.step()
        row.turns += 1
        row.input_tokens += turn.input_tokens
        row.output_tokens += turn.output_tokens
        if not turn.calls:
            return
        results = []
        for call in turn.calls:
            try:
                text, failed = result_text(await session.call_tool(call.name, call.arguments))
            except Exception as exc:  # a crashed call is a retry the agent has to recover from
                text, failed = f"tool call failed: {exc}", True
            row.calls += 1
            row.retries += int(failed)
            results.append((call, text, failed))
        model.add_results(results)
    row.error = f"gave up after {MAX_TURNS} turns"


def tool_specs(listing: Any) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description or "", "schema": t.inputSchema} for t in listing.tools]


async def run_server(
    label: str, command: list[str], models: list[Model], tasks: tuple[Task, ...], workdir: Path
) -> list[TaskResult]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    source = make_source(workdir)
    source_probe = ffprobe(source) or {}
    params = StdioServerParameters(
        command=command[0], args=command[1:], env=dict(os.environ), cwd=str(workdir.resolve())
    )
    rows: list[TaskResult] = []
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timedelta(minutes=10)) as session,
    ):
        await session.initialize()
        tools = tool_specs(await session.list_tools())
        for model in models:
            for task in tasks:
                output = workdir / label / model.label.replace(":", "_") / task.output
                output.parent.mkdir(parents=True, exist_ok=True)
                row = TaskResult(label, model.label, task.id, False)
                prompt = task.prompt.format(src=source) + f" Save the result to {output}."
                try:
                    await run_task(session, model, tools, prompt, row)
                except Exception as exc:  # one broken task must not sink the run
                    row.error = f"{type(exc).__name__}: {exc}"
                row.success = task_passed(task, output, source_probe)
                rows.append(row)
                print(f"{label:>8} {model.label:<32} {task.id:<10} {'ok' if row.success else 'FAIL'}", file=sys.stderr)
    return rows


# ── Report ───────────────────────────────────────────────────────────────────


@dataclass
class Summary:
    server: str
    model: str
    tasks: int
    passed: int
    mean_tokens: float
    mean_calls: float
    retries: int
    rows: list[TaskResult] = field(default_factory=list, repr=False)


def summarize(rows: list[TaskResult]) -> list[Summary]:
    groups: dict[tuple[str, str], list[TaskResult]] = {}
    for row in rows:
        groups.setdefault((row.server, row.model), []).append(row)
    return [
        Summary(
            server,
            model,
            len(group),
            sum(r.success for r in group),
            statistics.fmean(r.input_tokens + r.output_tokens for r in group),
            statistics.fmean(r.calls for r in group),
            sum(r.retries for r in group),
            group,
        )
        for (server, model), group in groups.items()
    ]


def markdown_table(summaries: list[Summary]) -> str:
    lines = [
        "| Server | Model | Success | Tokens / task | Calls / task | Retries |",
        "|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.server} | {s.model} | {s.passed}/{s.tasks} | {s.mean_tokens:,.0f} | {s.mean_calls:.1f} | {s.retries} |"
        )
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_server(spec: str) -> tuple[str, list[str]]:
    label, sep, command = spec.partition("=")
    if not sep or not label or not command.strip():
        raise SystemExit(f"--server must be label=command, got {spec!r}")
    return label, shlex.split(command)


def dry_run_model() -> Model:
    """Two scripted calls: one the server rejects (a retry), then a real read-only call."""
    return ScriptedModel([("no_such_tool", {}), ("video_info", {"input_path": "source.mp4"})], label="dry-run")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--server", action="append", default=[], help="label=command that starts a Kinocut MCP server on stdio"
    )
    parser.add_argument("--model", action="append", default=[], help="anthropic:<model id> or openai:<model id>")
    parser.add_argument("--task", action="append", default=[], help="run only these task ids (repeatable)")
    parser.add_argument("--out", type=Path, help="write every per-task row as JSON here")
    parser.add_argument(
        "--dry-run", action="store_true", help="scripted model, local checkout, first two tasks; costs nothing"
    )
    args = parser.parse_args(argv)

    servers = [parse_server(s) for s in args.server] or [("local", [sys.executable, "-m", "kinocut", "--mcp"])]
    tasks = tuple(t for t in TASKS if not args.task or t.id in args.task)
    if args.dry_run:
        models: list[Model] = [dry_run_model()]
        tasks = tasks[:2]
    elif not args.model:
        parser.error("pass at least one --model, or --dry-run")
    else:
        models = [build_model(spec) for spec in args.model]

    rows: list[TaskResult] = []
    for label, command in servers:
        with tempfile.TemporaryDirectory(prefix=f"kinocut-bench-{label}-") as tmp:
            rows += asyncio.run(run_server(label, command, models, tasks, Path(tmp)))
    print(markdown_table(summarize(rows)))
    if args.out:
        args.out.write_text(json.dumps([asdict(r) for r in rows], indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
