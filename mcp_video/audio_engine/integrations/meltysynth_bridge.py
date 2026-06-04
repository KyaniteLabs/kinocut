"""MeltySynth integration — pure Python SoundFont MIDI synthesizer.

License: MIT (https://github.com/sinshu/py-meltysynth)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...errors import MCPVideoError


def _require_meltysynth() -> Any:
    """Lazy import meltysynth with helpful error."""
    try:
        import meltysynth as ms

        return ms
    except ImportError as exc:
        raise MCPVideoError(
            "meltysynth is not installed. MeltySynth is not currently published on PyPI; "
            "install a compatible meltysynth module manually before using MIDI SoundFont synthesis.",
            error_type="dependency_error",
            code="meltysynth_not_found",
        ) from exc


def synthesize_midi(
    midi_path: str,
    soundfont_path: str,
    output: str,
    sample_rate: int = 44100,
) -> str:
    """Synthesize a MIDI file to WAV using a SoundFont.

    Args:
        midi_path: Path to MIDI file (.mid)
        soundfont_path: Path to SoundFont file (.sf2)
        output: Output WAV file path
        sample_rate: Output sample rate

    Returns:
        Path to output WAV file
    """
    ms = _require_meltysynth()

    midi_path_obj = Path(midi_path)
    sf_path_obj = Path(soundfont_path)

    if not midi_path_obj.exists():
        raise MCPVideoError(f"MIDI file not found: {midi_path}", error_type="input_error", code="invalid_input")
    if not sf_path_obj.exists():
        raise MCPVideoError(f"SoundFont not found: {soundfont_path}", error_type="input_error", code="invalid_input")

    sound_font = ms.SoundFont.from_file(str(sf_path_obj))
    settings = ms.SynthesizerSettings(sample_rate)
    synthesizer = ms.Synthesizer(sound_font, settings)

    midi_file = ms.MidiFile(str(midi_path_obj))
    synthesizer.render_midi(midi_file)

    # Write to WAV
    import wave

    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(synthesizer.get_samples().tobytes())

    return output


def render_notes(
    notes: list[dict[str, Any]],
    soundfont_path: str,
    output: str,
    sample_rate: int = 44100,
    duration: float | None = None,
) -> str:
    """Render a list of note events to WAV using a SoundFont.

    Args:
        notes: List of note dicts with keys:
            - channel: MIDI channel (0-15)
            - key: MIDI note number (0-127)
            - velocity: Note velocity (0-127)
            - start: Start time in seconds
            - duration: Note duration in seconds
        soundfont_path: Path to SoundFont file (.sf2)
        output: Output WAV file path
        sample_rate: Output sample rate
        duration: Total output duration (auto-calculated if None)

    Returns:
        Path to output WAV file
    """
    ms = _require_meltysynth()

    sf_path_obj = Path(soundfont_path)
    if not sf_path_obj.exists():
        raise MCPVideoError(f"SoundFont not found: {soundfont_path}", error_type="input_error", code="invalid_input")

    if duration is None:
        duration = max(n.get("start", 0) + n.get("duration", 0) for n in notes) + 1.0

    total_samples = int(duration * sample_rate)

    sound_font = ms.SoundFont.from_file(str(sf_path_obj))
    settings = ms.SynthesizerSettings(sample_rate)
    synthesizer = ms.Synthesizer(sound_font, settings)

    # Render silence up to each note, then play
    current_sample = 0
    for note in sorted(notes, key=lambda x: x.get("start", 0)):
        start_sample = int(note.get("start", 0) * sample_rate)
        note_duration = note.get("duration", 0.5)

        # Render silence until note start
        if start_sample > current_sample:
            silence_frames = start_sample - current_sample
            synthesizer.render(silence_frames)
            current_sample = start_sample

        # Note on
        synthesizer.note_on(
            note.get("channel", 0),
            note.get("key", 60),
            note.get("velocity", 100),
        )

        # Render note duration
        note_samples = int(note_duration * sample_rate)
        synthesizer.render(note_samples)
        current_sample += note_samples

        # Note off
        synthesizer.note_off(
            note.get("channel", 0),
            note.get("key", 60),
        )

    # Render remaining silence
    if current_sample < total_samples:
        synthesizer.render(total_samples - current_sample)

    # Write to WAV
    import wave

    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(synthesizer.get_samples().tobytes())

    return output
