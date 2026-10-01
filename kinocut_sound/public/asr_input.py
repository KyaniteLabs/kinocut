"""Pre-allocation ASR bounds on the already opened, verified regular file."""

import struct

from kinocut_sound.limits import MAX_ASR_DURATION_SECONDS, MAX_ASR_SAMPLE_RATE_HZ, MAX_ASR_METADATA_BYTES
from kinocut_sound.public.asr_request import asr_error
from kinocut_sound.qa._errors import QA_INPUT_INVALID, qa_error


def validate_header(handle, file_size):
    """Scan small chunk headers; never read PCM or reopen a caller path."""
    header = handle.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
        raise qa_error("ASR input must be PCM16 WAV", QA_INPUT_INVALID)
    if struct.unpack_from("<I", header, 4)[0] + 8 != file_size:
        raise qa_error("ASR WAV length mismatch", QA_INPUT_INVALID)
    offset, overhead, chunks = 12, 12, {}
    while offset < file_size:
        handle.seek(offset)
        raw = handle.read(8)
        if len(raw) != 8:
            raise qa_error("ASR WAV chunk is truncated", QA_INPUT_INVALID)
        kind, size = struct.unpack("<4sI", raw)
        end = offset + 8 + size + size % 2
        if end > file_size:
            raise qa_error("ASR WAV chunk is truncated", QA_INPUT_INVALID)
        overhead += 8 + size % 2 + (size if kind != b"data" else 0)
        if overhead > MAX_ASR_METADATA_BYTES:
            raise asr_error("ASR WAV metadata exceeds bound", "asr_over_limit")
        if kind in {b"fmt ", b"data"}:
            if kind in chunks:
                raise qa_error("ASR WAV has duplicate chunks", QA_INPUT_INVALID)
            chunks[kind] = size
        if kind == b"fmt ":
            if size < 16:
                raise qa_error("ASR WAV format is truncated", QA_INPUT_INVALID)
            raw_format = handle.read(16)
            if len(raw_format) != 16:
                raise qa_error("ASR WAV format is truncated", QA_INPUT_INVALID)
            tag, channels, rate, byte_rate, alignment, bits = struct.unpack("<HHIIHH", raw_format)
            if channels != 1:
                raise qa_error("input WAV channel layout is unsupported for this operation", QA_INPUT_INVALID)
            if (tag, channels, alignment, bits) != (1, 1, 2, 16) or rate <= 0 or byte_rate != rate * 2:
                raise qa_error("ASR input must be mono PCM16 WAV", QA_INPUT_INVALID)
            if rate > MAX_ASR_SAMPLE_RATE_HZ:
                raise asr_error("ASR audio exceeds rate bound", "asr_over_limit")
        offset = end
    if b"fmt " not in chunks or b"data" not in chunks or chunks[b"data"] % 2:
        raise qa_error("ASR WAV requires aligned format and data chunks", QA_INPUT_INVALID)
    if chunks[b"data"] // 2 > MAX_ASR_DURATION_SECONDS * rate:
        raise asr_error("ASR audio exceeds duration bound", "asr_over_limit")
