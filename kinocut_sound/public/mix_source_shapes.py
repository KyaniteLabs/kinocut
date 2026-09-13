"""Shared independent shape proof over bounded, hash-checked source bindings."""

from kinocut_sound.limits import MAX_MIX_INPUT_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.mix_files import read_asset
from kinocut_sound.public.mix_request import check_mix_resources


def verified_source_shapes(sources, request, root_fd):
    """Yield frame counts, retaining only small metadata between source reads."""
    cache = {}
    consumed = 0
    for source in sources:
        identity = (source.path, source.sha256)
        if identity not in cache:
            data = read_asset(root_fd, *identity, MAX_MIX_INPUT_BYTES - consumed)
            samples, rate, channels = decode_pcm_wav(data)
            if rate != request.plan.format.sample_rate_hz or channels != request.plan.format.channel_count:
                raise mix_error("verified source format mismatch", MIX_INPUT_INVALID)
            cache[identity] = (len(data), len(samples) // channels)
            del data, samples
        size, frames = cache[identity]
        consumed += size
        check_mix_resources(request, consumed)
        yield frames
