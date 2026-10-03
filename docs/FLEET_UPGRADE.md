# Fleet upgrade to Kinocut 1.16.0

1.16.0 is published (verified 2026-10-02 on PyPI/npm/GitHub release/canonical MCP Registry); the matching published compatibility installer is `mcp-video==1.6.15`. This verifies package publication, not fleet rollout. Use the owned consumer environment, configured extras and reviewed upgrade/restart plan below. A merge, successful build, or saved cloud setup draft does not update
an installed package or a running MCP process.

## Inventory and rollout

Record each consumer's host or service, owner, package manager, executable path,
Python environment, configured extras, package/source pin, running MCP process,
and deployment/restart mechanism. Count unreachable and unknown consumers
separately. GitHub code-search matches are leads, not a live fleet inventory.

Choose one representative consumer as a canary. Preserve its existing package
pin, configuration and environment so rollback can restore the same extras and
dependency lock. Check active render jobs and use the host's normal graceful
shutdown before restarting its MCP server. Do not kill active renders or replace
another service's Python environment to force an upgrade.

For a managed Python environment without the legacy distribution, use that
environment's interpreter and retain its explicitly configured extras. Consumers
with `mcp-video` must use the joint upgrade and ownership repair below:

```bash
/path/to/environment/bin/python -m pip install --upgrade 'kinocut==1.16.0'
/path/to/environment/bin/python -m pip check
/path/to/environment/bin/kino --version
/path/to/environment/bin/kino doctor
```

On Windows, use the consumer's existing environment under `Scripts` rather than
the Unix `bin` layout. For example, in PowerShell for a local `.venv`:

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade 'kinocut==1.16.0'
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\kino.exe --version
& .\.venv\Scripts\kino.exe --format json doctor
```

These commands preserve the same release and diagnostics workflow. Retain the
consumer's configured extras and verify its actual running interpreter on every
OS; platform-specific environment paths do not establish optional-model parity.

For a legacy consumer, replace both exact pins together and repair canonical
ownership afterward. Safe pip fixtures reproduced the old shim deleting
`mcp-video` after canonical installation, while `pip check` still passed.
The reinstall uses `--no-deps` to preserve the just-resolved dependency graph:

```bash
/path/to/environment/bin/python -m pip install --upgrade 'kinocut==1.16.0' 'mcp-video==1.6.15'
/path/to/environment/bin/python -m pip install --force-reinstall --no-deps 'kinocut==1.16.0'
/path/to/environment/bin/python -m pip check
/path/to/environment/bin/kino --version
/path/to/environment/bin/kinocut --version
/path/to/environment/bin/mcp-video --version
```

The equivalent PowerShell sequence uses that environment's `Scripts` executables:

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade 'kinocut==1.16.0' 'mcp-video==1.6.15'
& .\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps 'kinocut==1.16.0'
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\kino.exe --version
& .\.venv\Scripts\kinocut.exe --version
& .\.venv\Scripts\mcp-video.exe --version
```

Preserve existing extra names in the initial joint upgrade. The old shim requires
Kinocut 1.15.3, so upgrading canonical alone leaves a dependency conflict until
the shim is replaced. The new metadata-only shim owns no console scripts;
after repair, removing it preserves all three aliases. If removing an older
shim directly, perform the same canonical reinstall before relying on any alias.
Update and commit dependency locks through the consumer repository's normal
workflow. The release raises security floors for nine previously affected dependencies, including optional Pillow, and updates affected optional Torch/audio dependencies with their compatible GPU graph. BasicSR retains an unpatched advisory in an unused distributed path; legacy Real-ESRGAN import/inference and GPU driver compatibility need separate acceptance. Refresh the consumer lock instead of retaining affected transitive pins. Source-installed consumers must use the verified release tag/commit.

For a `uvx` MCP configuration, pin the package explicitly:

```json
{"command":"uvx","args":["--from","kinocut==1.16.0","kino","--mcp"]}
```

The npm launcher also pins a separate `uvx` Python environment. Updating a global
Python package alone does not update it. Upgrade its configured npm package to
`kinocut@1.16.0`, then verify the launched CLI version. A version-matched MCPB
requires its own matching artifact, readiness receipt and host installation;
do not reuse a 1.15.3 bundle or imply Desktop acceptance from CI checks.

After the controlled restart, verify the exact interpreter used by the service:

```bash
/path/to/environment/bin/python -c 'import importlib.metadata as m, kinocut, mcp_video; assert m.version("kinocut") == kinocut.__version__ == "1.16.0"; assert kinocut.Client is mcp_video.Client; print(kinocut.__version__, kinocut.__file__)'
```

Confirm that the MCP process was replaced, starts successfully, discovers the
expected installed tool schemas, and completes a small local synthetic-media
smoke test. Verify required FFmpeg/FFprobe capabilities and each consumer's
configured optional backends independently. Do not infer model quality or
backend availability from a successful core install.

Record old/new versions, exact release commit, artifact digest where available,
restart time, doctor/smoke result and rollback outcome. Roll out in bounded
batches only after the canary passes. Stop on failure and restore the prior
version/configuration using that consumer's normal deployment mechanism.

## Replacing an earlier build with the same version

A consumer already reporting `1.16.0` may still have an earlier candidate's
bytes. An actual pip fixture retained the old wheel after a successful
`pip install --upgrade` of the newer same-version wheel. Version output and
`pip check` alone therefore do not establish that it runs the final build.

Prefer a fresh environment built from the verified published release and the
consumer's reviewed dependency lock and configured extras. For an approved
in-place repair, explicitly replace canonical package bytes, then resolve the
approved pins and configured extras against the final metadata before restarting:

```bash
/path/to/environment/bin/python -m pip install --force-reinstall --no-deps 'kinocut==1.16.0'
/path/to/environment/bin/python -m pip install --upgrade 'kinocut==1.16.0'
/path/to/environment/bin/python -m pip check
```

Use the equivalent existing `Scripts` interpreter on Windows. Include the
consumer's configured extras and other approved pins in dependency resolution;
`--no-deps` only replaces package bytes and does not establish a valid dependency
graph. Legacy consumers still need the joint shim upgrade and final canonical
ownership repair above. Do not blindly reinstall a GPU dependency graph.

Verify the installed distribution against the final artifact or source commit,
not an earlier candidate receipt. Editable/source installations must switch to
the verified tag or commit through their normal deployment mechanism. Check
launcher-managed environments separately; a repaired global installation does
not replace a cached `uvx` environment. Record the actual running interpreter,
restart and smoke-test evidence before calling a consumer upgraded.

## Current verification boundary

The prior repair work is merged, with its tests and external requirements in
[DEBT_CLOSURE.md](research/DEBT_CLOSURE.md). Preparing this release does not close
the six external owner/evidence issues or the excluded Forgejo work. A complete
fleet claim requires an authoritative inventory and live per-consumer receipts;
neither is established by these instructions.


Drain queued and running repurpose jobs before upgrading. Legacy durable jobs without a frozen release policy fail closed on the new worker; recreate them from reviewed source inputs and explicit policy rather than bypassing the gate.
