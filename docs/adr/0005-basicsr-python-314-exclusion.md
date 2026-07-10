# BasicSR Python 3.13+ Exclusion

`basicsr>=1.4` cannot build from source on Python 3.13+ with current isolated-build tooling; its setup script raises `KeyError: '__version__'` before dependency resolution can complete. It is excluded via environment marker `python_version < '3.13'` in `pyproject.toml` so `kinocut[upscale]`, `kinocut[ai]`, and `kinocut[all-ai]` remain installable on current Python through the OpenCV upscaling fallback. This is a temporary constraint until `basicsr` publishes a compatible release.
