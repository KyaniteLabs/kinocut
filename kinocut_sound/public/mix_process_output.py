"""Bound application output before retaining bytes or writing an owned sink."""

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error


class BoundedOutput:
    def __init__(self, limit, sink=None):
        if type(limit) is not int or limit < 0:
            raise mix_error("process output limit must be a nonnegative integer", MIX_INPUT_INVALID)
        self.limit = limit
        self.sink = sink
        self.count = 0
        self.buffer = bytearray()

    def append(self, chunk):
        if self.count + len(chunk) > self.limit:
            raise mix_error("mix worker pipe exceeded its byte limit", "mix_worker_failed")
        if self.sink is None:
            self.buffer.extend(chunk)
        elif self.sink.write(chunk) != len(chunk):
            raise mix_error("process output sink returned a short write", "mix_worker_failed")
        self.count += len(chunk)

    def value(self):
        return bytes(self.buffer)
