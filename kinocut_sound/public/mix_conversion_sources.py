"""Worker resolver reads only parent-manifest-derived assets for V4."""

from kinocut_sound.mix._errors import mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.mix_files import read_asset


class PreparedSourceResolver:
    def __init__(self, root_fd, manifest):
        self.root_fd = root_fd
        self.entries = {(entry.kind, entry.binding_id): entry for entry in manifest.entries}

    def read(self, kind, binding_id, source, remaining):
        entry = self.entries.get((kind, binding_id))
        if entry is None or (entry.original.path, entry.original.sha256) != (source.path, source.sha256):
            raise mix_error("prepared conversion binding is missing or changed", "mix_worker_failed")
        derived = entry.derived
        data = read_asset(self.root_fd, derived.path, derived.sha256, remaining)
        pcm, rate, channels = decode_pcm_wav(data)
        if (len(data), rate, channels, len(pcm)) != (
            derived.byte_count,
            derived.sample_rate_hz,
            derived.channel_count,
            derived.frame_count * derived.channel_count,
        ):
            raise mix_error("derived conversion source shape mismatch", "mix_worker_failed")
        return data
