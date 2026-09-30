# Exact-head PR586 hosted safety investigation

This is the earlier investigation at the original PR head. The coordinated final
gate subsequently passed 7,412 tests; see [PR validation](../../PR_VALIDATION.md)
for the banked implementation and latest evidence. Its final exact CI formatting
scope is 1,067 files, including the new dependency-diagnostic test module.

Examined GitHub Actions run36743686143/job109984340546 for exact head0ff4fa51518b11aa2e36f74e0c5cc7287c5d5510. GitHub job metadata confirms Hosted PR checks completedfailure: checkout/classification/installFFmpeg/setupPython/installpackage successful; Lintfailed, Testskipped. No first-contributor approval block.

Both `gh run view --log-failed` and direct job/logs API attempts obtained signed backend redirects but fetch returnedHTTP403. No exact raw failure lines retrieved, and no claim made otherwise. Check annotations contain only exitcode1. Workflow reviewed: ubuntu-latest, pinned checkout/setupPython, Python3.14, editable package devinstall, Ruff0.15.11 lint+format, nonslowpytest. No workflow or permission changes.

Local HEAD exactlymatches observed failinghead. PinnedRuff0.15.11 installed in /tmp isolatedtarget. Exact `ruff check kinocut/ kinocut_sound/ mcp_video.py tests/` passed. Exact `ruff format --check` failed25files:10runtime+15tests. This reproduces a supported Lintfailure mechanism independently of unavailable rawlogs.

Repair: pinnedformatter only those25files; all pre/post PythonAST hashes identical. Ruff expansion increased temporal-motion helper to82lines; rootapproved docstring-only4line shortening, restoring function78 and module799 physical. No executableAST differences from exacthead in changedfiles after strippingdocstrings. Compositor799physical. No baselinerelaxation/gatedisabling/newpermissions.

Validation: exact pinnedRuff lint+format nowpass1066files, diffcheck/importshim pass, architecture+quality+cache+bitdepth+black+sharedstderrhelper103passed23.39s. Code frozen for parent fullAGENTS gate beforecommit. No commits, reruns, comments or remote modifications fromthisagent.
