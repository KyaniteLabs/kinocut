"""Basic Pitch integration — Google's polyphonic pitch detection.

License: Apache 2.0 (https://github.com/spotify/basic-pitch)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...errors import MCPVideoError


def _require_basic_pitch_predict() -> Any:
    """Lazy import BasicPitch's predictor with helpful error."""
    try:
        from basic_pitch.inference import predict

        return predict
    except ImportError as exc:
        raise MCPVideoError(
            "basic-pitch not installed. It is a manual optional integration; install it separately on Python 3.11 or 3.12.",
            error_type="dependency_error",
            code="basic_pitch_not_found",
        ) from exc


def detect_pitch(
    input_path: str,
    output_directory: str | None = None,
    save_midi: bool = True,
    sonify_midi: bool = False,
    save_model_outputs: bool = False,
    save_notes: bool = False,
) -> dict[str, Any]:
    """Detect pitch from an audio file using Basic Pitch.

    Args:
        input_path: Path to audio file (.wav, .mp3, etc.)
        output_directory: Directory for output files (default: same as input)
        save_midi: Save MIDI output
        sonify_midi: Save sonified MIDI as audio
        save_model_outputs: Save model output numpy array
        save_notes: Save note events as CSV

    Returns:
        Dict with output paths and detected note data
    """
    predict = _require_basic_pitch_predict()

    input_path_obj = Path(input_path)
    if not input_path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {input_path}", error_type="input_error", code="invalid_input")

    if output_directory is None:
        output_directory = str(input_path_obj.parent)

    Path(output_directory).mkdir(parents=True, exist_ok=True)

    _model_output, midi_data, note_events = predict(input_path)

    result: dict[str, Any] = {
        "input": input_path,
        "output_directory": output_directory,
        "note_events": note_events,
    }

    base_name = input_path_obj.stem

    if save_midi and midi_data is not None:
        midi_path = str(Path(output_directory) / f"{base_name}_basic_pitch.mid")
        midi_data.write(midi_path)
        result["midi_path"] = midi_path

    return result


def audio_to_midi(
    input_path: str,
    output_midi: str,
) -> str:
    """Convert an audio file to MIDI using Basic Pitch.

    Args:
        input_path: Path to audio file
        output_midi: Output MIDI file path

    Returns:
        Path to output MIDI file
    """
    predict = _require_basic_pitch_predict()

    input_path_obj = Path(input_path)
    if not input_path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {input_path}", error_type="input_error", code="invalid_input")

    _, midi_data, _ = predict(input_path)

    if midi_data is None:
        raise MCPVideoError("No MIDI data generated", error_type="processing_error", code="basic_pitch_empty")

    midi_data.write(output_midi)
    return output_midi
