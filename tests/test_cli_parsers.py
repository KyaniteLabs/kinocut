"""Tests for CLI parser modules."""

import argparse


def _get_subparser_names(parser_module):
    """Return set of subparser names added by a parser module."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    parser_module.add_parsers(subparsers)
    return set(subparsers.choices.keys())


class TestParserCore:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import core

        names = _get_subparser_names(core)
        expected = {
            "doctor",
            "info",
            "extract-frame",
            "trim",
            "merge",
            "edit",
            "blur",
            "color-grade",
            "template",
            "templates",
            "video-extract-frame",
        }
        assert expected <= names


class TestParserMedia:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import media

        names = _get_subparser_names(media)
        expected = {
            "convert",
            "crop",
            "extract-audio",
            "fade",
            "preview",
            "resize",
            "rotate",
            "speed",
            "storyboard",
            "subtitles",
            "thumbnail",
            "export",
        }
        assert expected <= names


class TestParserAdvanced:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import advanced

        names = _get_subparser_names(advanced)
        expected = {
            "apply-mask",
            "batch",
            "compare-quality",
            "create-from-images",
            "detect-scenes",
            "export-frames",
            "generate-subtitles",
            "read-metadata",
            "stabilize",
            "write-metadata",
            "audio-waveform",
        }
        assert expected <= names


class TestParserAI:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import ai

        names = _get_subparser_names(ai)
        expected = {
            "video-ai-transcribe",
            "video-analyze",
            "video-ai-upscale",
            "video-ai-stem-separation",
            "video-ai-scene-detect",
            "video-ai-color-grade",
            "video-ai-remove-silence",
        }
        assert expected <= names


class TestParserAudio:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import audio

        names = _get_subparser_names(audio)
        expected = {
            "audio-synthesize",
            "audio-compose",
            "audio-preset",
            "audio-sequence",
            "audio-effects",
            "video-add-generated-audio",
            "video-audio-spatial",
            "normalize-audio",
        }
        assert expected <= names


class TestParserEffects:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import effects

        names = _get_subparser_names(effects)
        expected = {
            "effect-vignette",
            "effect-glow",
            "effect-noise",
            "effect-scanlines",
            "effect-chromatic-aberration",
            "add-text",
            "add-audio",
            "chroma-key",
            "filter",
            "overlay-video",
            "reverse",
            "split-screen",
            "transition-glitch",
            "transition-morph",
            "transition-pixelate",
            "watermark",
        }
        assert expected <= names


class TestParserLayout:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import layout

        names = _get_subparser_names(layout)
        expected = {
            "video-layout-grid",
            "video-layout-pip",
            "video-mograph-count",
            "video-mograph-progress",
            "video-text-animated",
        }
        assert expected <= names


class TestParserImage:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import image

        names = _get_subparser_names(image)
        expected = {
            "image-extract-colors",
            "image-generate-palette",
            "image-analyze-product",
        }
        assert expected <= names


class TestParserHyperframes:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import hyperframes

        names = _get_subparser_names(hyperframes)
        expected = {
            "hyperframes-render",
            "hyperframes-compositions",
            "hyperframes-preview",
            "hyperframes-still",
            "hyperframes-init",
            "hyperframes-add-block",
            "hyperframes-validate",
            "hyperframes-pipeline",
        }
        assert expected <= names

    def test_render_output_format_does_not_override_global_json_format(self):
        from mcp_video.cli.parser import build_parser

        args = build_parser().parse_args(["--format", "json", "hyperframes-render", "project", "--format", "webm"])

        assert args.format == "json"
        assert args.output_format == "webm"

    def test_render_accepts_current_hyperframes_resolution_and_png_sequence(self):
        from mcp_video.cli.parser import build_parser

        args = build_parser().parse_args(
            [
                "hyperframes-render",
                "project",
                "--composition",
                "compositions/intro.html",
                "--resolution",
                "portrait",
                "--format",
                "png-sequence",
            ]
        )

        assert args.composition == "compositions/intro.html"
        assert args.resolution == "portrait"
        assert args.output_format == "png-sequence"

    def test_render_still_and_snapshot_accept_runtime_data_flags(self):
        from mcp_video.cli.parser import build_parser

        render_args = build_parser().parse_args(
            [
                "hyperframes-render",
                "project",
                "--variables",
                '{"title":"Launch"}',
                "--variables-file",
                "/tmp/render-vars.json",
            ]
        )
        still_args = build_parser().parse_args(
            [
                "hyperframes-still",
                "project",
                "--variables",
                '{"title":"Still"}',
                "--variables-file",
                "/tmp/still-vars.json",
            ]
        )
        snapshot_args = build_parser().parse_args(
            [
                "hyperframes-snapshot",
                "project",
                "--variables",
                '{"title":"Snapshot"}',
                "--variables-file",
                "/tmp/snapshot-vars.json",
            ]
        )

        assert render_args.variables == '{"title":"Launch"}'
        assert render_args.variables_file == "/tmp/render-vars.json"
        assert still_args.variables == '{"title":"Still"}'
        assert still_args.variables_file == "/tmp/still-vars.json"
        assert snapshot_args.variables == '{"title":"Snapshot"}'
        assert snapshot_args.variables_file == "/tmp/snapshot-vars.json"

    def test_init_add_and_benchmark_accept_current_hyperframes_flags(self):
        from mcp_video.cli.parser import build_parser

        init = build_parser().parse_args(
            [
                "hyperframes-init",
                "demo",
                "--video",
                "/tmp/source.mp4",
                "--audio",
                "/tmp/source.wav",
                "--skip-transcribe",
                "--model",
                "base.en",
                "--language",
                "en",
                "--tailwind",
                "--resolution",
                "landscape",
            ]
        )
        add = build_parser().parse_args(["hyperframes-add-block", "project", "shader-wipe", "--no-clipboard"])
        benchmark = build_parser().parse_args(["hyperframes-benchmark", "project", "--runs", "5"])

        assert init.video == "/tmp/source.mp4"
        assert init.audio == "/tmp/source.wav"
        assert init.skip_transcribe is True
        assert init.model == "base.en"
        assert init.language == "en"
        assert init.tailwind is True
        assert init.resolution == "landscape"
        assert add.no_clipboard is True
        assert benchmark.runs == 5


class TestParserQuality:
    def test_adds_expected_parsers(self):
        from mcp_video.cli.parser import quality

        names = _get_subparser_names(quality)
        expected = {
            "video-auto-chapters",
            "video-info-detailed",
            "video-quality-check",
            "video-design-quality-check",
            "video-fix-design-issues",
        }
        assert expected <= names

    def test_quality_commands_accept_output_format_after_subcommand(self):
        from mcp_video.cli.parser import build_parser

        parser = build_parser()
        cases = [
            ["video-auto-chapters", "input.mp4", "--format", "json"],
            ["video-info-detailed", "input.mp4", "--format", "json"],
            ["video-quality-check", "input.mp4", "--format", "json"],
            ["video-design-quality-check", "input.mp4", "--format", "json"],
            ["video-fix-design-issues", "input.mp4", "--format", "json"],
        ]

        for argv in cases:
            args = parser.parse_args(argv)
            assert args.format == "json"

    def test_quality_commands_keep_global_output_format(self):
        from mcp_video.cli.parser import build_parser

        args = build_parser().parse_args(["--format", "json", "video-quality-check", "input.mp4"])

        assert args.format == "json"


class TestParserInit:
    def test_build_parser_returns_parser(self):
        from mcp_video.cli.parser import build_parser

        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)
