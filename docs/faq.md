# Frequently Asked Questions

## What is Kinocut?

Kinocut is an open-source MCP server, Python library, and CLI that wraps FFmpeg, PUSHING CREATION-style planning, Hyperframes, and local repurposing workflows for AI-agent video editing and creation. It runs locally, requires no cloud services, and is free under the Apache-2.0 license.

## What is MCP?

MCP (Model Context Protocol) is a standard protocol that lets AI agents like Claude Code and Cursor call external tools through a structured interface. Think of it as "USB-C for AI tools" — a universal connector between agents and capabilities.

## Is Kinocut on the MCP Registry?

Kinocut targets the official MCP Registry identifier `io.github.KyaniteLabs/kinocut`. Registry metadata is published from the release workflow after package publication; treat the listing as pending until its public registry URL resolves.

## Which AI agents work with Kinocut?

Any MCP-compatible agent: Claude Code, Cursor, Windsurf, Cline, and any client that supports the MCP protocol. The server runs as a stdio transport, which is the standard MCP transport mode.

## Do I need FFmpeg installed?

Yes. FFmpeg must be installed and available on your `PATH`. On macOS: `brew install ffmpeg`. On Ubuntu: `sudo apt install ffmpeg`. The package does not bundle FFmpeg itself.

## Does it work on Windows?

Yes. Kinocut works on macOS, Linux, and Windows as long as FFmpeg is installed and accessible.

## What video formats are supported?

All formats that FFmpeg supports: MP4, WebM, MOV, AVI, MKV, GIF, and more. Input and output formats are auto-detected from file extensions.

## Can I use it without an AI agent?

Yes. Kinocut has three interfaces: MCP server (for agents), Python client (for scripts), and CLI (for terminal use). You can use any of them independently.

## How do I install it?

```bash
pip install kinocut
```

For AI features like transcription and upscaling, install the extras:

```bash
pip install "kinocut[ai]"
```

## What are the AI-powered features?

Kinocut includes 7 AI features: silence removal, Whisper transcription, scene detection, stem separation (isolate vocals/drums), AI upscaling (2x/4x super-resolution), auto color grading, and spatial audio positioning.

## What tool areas does it cover?

Kinocut covers Meta / Discovery, Cinematic Creation, Core Editing, AI-Powered media, Hyperframes, local repurposing, Audio Synthesis, Visual Effects, Transitions, Layout & Motion Graphics, Analysis, and Image Analysis. Use `search_tools` when an agent needs to find the right operation without loading the whole registry.

## What are the cinematic creation tools?

The cinematic creation tools add a PUSHING CREATION-compatible pre-production workflow: `video_project_create` scaffolds a project with `style.md`, `storyboard.md`, and `refs/`; `style_pack_read` parses STYLE_ and NEG_ blocks; `storyboard_read` parses shot rows; and `shot_prompt_render` expands a storyboard shot into generation-ready positive and negative prompts.

## What do the Hyperframes and repurposing tools add?

Hyperframes tools cover project scaffolds, renders, snapshots, layout inspection, catalog blocks, website capture, local TTS, transcription import, background removal, diagnostics, and benchmarking. Repurposing tools create dry-run manifests or local platform packages for Shorts, Reels, TikTok, and YouTube-style variants, including thumbnails, storyboards, and optional release checkpoints.

## Is it free?

Yes. Kinocut is open-source under the Apache-2.0 license. There are no API costs because everything runs locally using FFmpeg and optional local AI models.

## How fast is it?

Very fast. Since it wraps FFmpeg directly, operations like trimming, merging, and format conversion run at near-native FFmpeg speed. AI features depend on your hardware (GPU recommended for upscaling and transcription).

## Can I use it in production?

Yes. Kinocut has comprehensive error handling with structured error types, input validation, FFmpeg timeout protection, and CI coverage for package and repository readiness. It's used in CI/CD pipelines for automated video quality checks.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full guide. The short version: fork, branch, write tests, submit a PR. All PRs need passing CI.
