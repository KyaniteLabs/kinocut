<!-- mcp-name: io.github.KyaniteLabs/mcp-video -->
# mcp-video is now Kinocut

This package preserves existing installs after the project rename. It installs the matching
Kinocut release and keeps the `mcp-video` command and `mcp_video` Python import working.

New installations should use:

```bash
pip install kinocut
kino doctor
```

When upgrading an older shim, reinstall its matching canonical release after
the upgrade. Older installer records can remove the shared executable even when
`pip check` reports no dependency conflict:

```bash
python -m pip install --upgrade 'mcp-video==1.6.15'
python -m pip install --force-reinstall --no-deps 'kinocut==1.16.0'
python -m pip check
kino --version
kinocut --version
mcp-video --version
```

Preserve configured extras during the first upgrade. The new shim owns no console
scripts; after this repair, removing it preserves all three canonical aliases.

Compatibility identifiers remain supported on the published Kinocut 1.15.x line
and the upcoming 1.16.x line. Project home:
[kinocut.dev](https://kinocut.dev/).
