# Kinocut Context

A Python MCP server, client and CLI that expose FFmpeg-based video processing as typed tools for AI agents.

## Language

**Engine**:
A self-contained processing module that builds and executes FFmpeg commands or runs AI/ML models. Examples: `effects_engine`, `audio_engine`, `ai_engine`, `design_quality`.
_Avoid_: module, handler, worker, processor

**Tool**:
A function registered as an MCP tool via `@mcp.tool()` in a `server_tools_*.py` file. Tools are the public API surface.
_Avoid_: endpoint, API, command, route

**Hot path**:
The eight tools every surface lists by name: `video_info`, `video_trim`, `video_merge`, `video_add_text`, `video_add_audio`, `video_extract_frame`, `video_shorts`, `video_doctor` (`CORE_TOOLS` in `tool_registry.py`).
_Avoid_: core 20, default tools

**Operation family**:
A typed dispatch tool (`video_edit_ops`, `audio_ops`, ...) whose `operation` enum names member tools and whose `params` are validated against that tool's own contract. Defined in `tool_families.py`. `list_operations` and `describe_operation` discover family members.
_Avoid_: meta-tool, router

**Profile**:
A named tool selection served with `KINOCUT_TOOLS=profile:<name>`. `KINOCUT_TOOLS=all` serves every tool by name.
_Avoid_: mode, preset

**Pipeline**:
An FFmpeg filtergraph string assembled from user parameters. Engines construct pipelines; `_run_ffmpeg()` executes them.
_Avoid_: chain, graph, filter string

**Probe**:
Analysis of a video file's properties (duration, resolution, fps, codec, colors) using ffprobe.
_Avoid_: scan, inspect, metadata read

**Guardrail**:
A design-quality or technical-quality check that scores a video against objective criteria. May trigger auto-fixes.
_Avoid_: linter, validator, checker

**Facade**:
The thin re-export layer (`engine.py`, `server.py`) that presents a unified import surface without containing logic.
_Avoid_: barrel file, index, proxy

**Filter** (in FFmpeg context):
An FFmpeg video/audio filter (drawtext, scale, fade, etc.) applied via `-vf` or `-filter_complex`.
_Avoid_: Using "filter" to mean Python list/dict filtering in FFmpeg-related code.

**Command** (in CLI context):
A CLI subcommand handled by a `cli/handlers_*.py` module.
_Avoid_: Using "command" to mean FFmpeg command-line invocation in CLI-related code.

**Timeline**:
A JSON specification describing a multi-track video edit with clips, overlays, transitions, and export settings.
_Avoid_: composition, sequence. Use **project** only with one of the qualified meanings below.

**Creation project**:
The cinematic generation concept owned by `creation_engine.py`.
**Hyperframes project**:
The Hyperframes-specific project concept owned by `hyperframes_engine.py`.
**Edit project**:
The durable trusted-execution kernel identity and its append-only revision history. Public kernel API nouns use `edit_project_*`.
**Render runner**:
The detached process that executes a persistent render job.
_Avoid_: worker

## Relationships

- A **Tool** validates inputs and either delegates to exactly one **Engine** function or compiles typed operations into the editing kernel: **Tool → (Engine | kernel-compile)**.
- An **Engine** assembles **Pipeline** operations and executes them via `_run_ffmpeg()`.
- A **Probe** reads video metadata via ffprobe.
- A **Guardrail** evaluates video quality; may trigger auto-fixes via **Engine** functions.
- **Facade** files (`engine.py`, `server.py`) re-export from underlying modules.
- A **Command** usually calls the same function as a **Tool**; not every Tool has a Command.
- An **Operation family** dispatches to member **Tools**; the result is identical to calling the Tool by name.

## Example dialogue

> **Dev:** "When a user calls the `video_trim` **Tool**, which **Engine** handles it?"
> **Domain expert:** "`engine_edit.trim` builds the **Pipeline**, then `_run_ffmpeg()` executes it."
>
> **Dev:** "Does the **Guardrail** run a **Probe** first?"
> **Domain expert:** "Yes — `_probe_video` gathers frame data, then the **Guardrail** checks apply scoring rules."

## Flagged ambiguities

- "engine" was used to mean both the Python module (`effects_engine.py`) and FFmpeg's internal processing engine — resolved: "Engine" is the Python module only.
- "filter" means both FFmpeg filter expressions and Python list/dict filters — resolved: in FFmpeg context, always say "Filter"; in Python context, say "list comprehension" or "predicate".
- "command" means both CLI subcommand and FFmpeg command-line invocation — resolved: "Command" is the CLI subcommand; "FFmpeg invocation" is the subprocess call.
- "project" has three deliberate, qualified meanings — creation project, Hyperframes project, and edit project — so unqualified use remains ambiguous and should be avoided.
