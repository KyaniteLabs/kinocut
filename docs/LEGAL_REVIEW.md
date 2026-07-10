# Licensing and Commercial-Use Notes

This is a practical project-specific licensing summary for Kinocut.

**Not legal advice.** If you are distributing this commercially or embedding it in a product, have counsel review the final obligations for your use case.

## Project license

The `kinocut` Python package is released under **Apache 2.0**. The `mcp-video` distribution is a compatibility shim and carries the same project license. See [LICENSE](../LICENSE).

## Important dependency and tooling caveats

### FFmpeg

Kinocut depends on FFmpeg being available at runtime for many features.

- FFmpeg licensing depends on how FFmpeg is built and distributed.
- If you only invoke a system-installed FFmpeg, your obligations may differ from bundling FFmpeg binaries yourself.
- If you distribute FFmpeg binaries, review FFmpeg's own legal guidance carefully.

Reference:
- https://ffmpeg.org/legal.html

## Optional AI/media dependencies

Optional dependencies may bring their own licenses and model/runtime constraints. In particular:

- `openai-whisper`
- `demucs`
- `realesrgan`
- `basicsr`
- `torch`
- `torchaudio`
- `opencv-contrib-python`

If you package or redistribute an environment containing those components, review their individual licenses.

## Repo-specific provenance notes

This repository previously contained local/demo artifacts and extracted/reference materials that were not appropriate for public deploy or packaging surfaces. Those surfaces have now been cleaned up, but the principle remains:

- generated outputs should not be tracked unless intentionally curated
- local tool state should remain untracked
- third-party-derived reference material should be reviewed before publication

## Practical guidance

Before a public release or commercial deployment:

2. Confirm whether you are **bundling** FFmpeg or only invoking a system install.
3. Review the licenses of all optional AI/media dependencies you intend to ship.
4. Keep release artifacts limited to the intended package surface.
