# Third-party notices

Kinocut is Apache-2.0 (see [LICENSE](LICENSE)). It bundles one third-party asset and
calls or depends on the software below. Licences were read from each package's installed
metadata on 2026-11-11; the package's own licence file is authoritative.

## Bundled

| Item | Licence | Where |
| --- | --- | --- |
| Chakra Petch font (The Chakra Petch Project Authors) | SIL Open Font License 1.1 | [assets/CHAKRA-PETCH-OFL.txt](assets/CHAKRA-PETCH-OFL.txt) |

## FFmpeg (not bundled)

Kinocut runs the FFmpeg on your `PATH`; it does not ship FFmpeg. FFmpeg is LGPL 2.1+ by
default and GPL 2+ when built with GPL components such as libx264, which Kinocut's core
render paths select. Which licence applies depends on the build you install, and a GPL
build changes redistribution obligations if you repackage it. See
[docs/MCPB_SUPPLY_CHAIN.md](docs/MCPB_SUPPLY_CHAIN.md).

## Python dependencies

Core (installed with `kinocut`):

| Package | Licence |
| --- | --- |
| mcp | MIT |
| anyio | MIT |
| click | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| PyJWT | MIT |
| pydantic | MIT |
| pydantic-settings | MIT |
| python-multipart | Apache-2.0 |
| starlette | BSD-3-Clause |
| rich | MIT |

Optional extras (only when you install them):

| Package | Extra | Licence |
| --- | --- | --- |
| pillow | image, client | MIT-CMU |
| numpy | image, audio | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| scikit-learn | image | BSD-3-Clause |
| webcolors | image | BSD |
| scipy | audio-enhanced | BSD |
| soundfile | audio-enhanced | see the package; not checked here |
| anthropic | image-ai | see the package; not checked here |

Transitive dependencies carry their own licences. Regenerate this list from
`pyproject.toml` with `pip-licenses` or `uv pip list` plus each package's metadata
when dependencies change.
