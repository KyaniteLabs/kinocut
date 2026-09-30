# Iteration 3: trim/speed transactional publication

Changes saved and scope frozen. No commits or remote changes performed by this agent; root coordinates requested banking and PR.

## Final behavior

`trim` and `speed` validate the caller's final path before staging, use the existing `_atomic_output` same-directory temporary path retaining the requested container suffix, declare the stage as an operation write, render there, and call existing `_build_edit_result` on staged media before publication. Failed FFmpeg encoding, subprocess timeout, completion exceptions and rejected postflight never replace an existing valid destination or leave a new destination/stage behind. On success, only the result's output_path is rewritten to the caller's path; signatures, existing fields, codec/container selection, speed audio/no-audio branches and accurate input-seek trim behavior stay intact.

Existing final-path source alias protection runs before creating the stage, tested for same path, hardlink and symlink. Existing scoped operation write/read bookkeeping remains consistent because staging is declared before postflight probing.

Neither trim nor speed exposes a progress callback. Tests inject a completion failure immediately after actual encoding of a valid staged output, covering the same exception-after-render hazard without adding a callback signature. Prior convert callback-specific regression remains in tests/test_conversion_transaction.py.

Trim time parsing retains numeric seconds, MM:SS and HH:MM:SS grammar and duration/end precedence. It now fails with structured `MCPVideoError(code="invalid_parameter")` for booleans, unsupported types, malformed strings, NaN/Inf (including colon-delimited values), integers whose float conversion overflows and strings longer than `MAX_TRIM_TIME_TEXT_LENGTH=128`. Numeric finiteness is checked by shared `_sanitize_ffmpeg_number`; the new text bound lives in validation.py. No new maximum valid duration is imposed. Optional duration/end None stays valid.

## Evidence and validation

`tests/test_basic_writer_transactions.py` executes real FFmpeg for trim and speed, against absent and existing valid destinations. It checks:
- actual invalid-encoder failures, real subprocess timeout under realtime input, rejection after successful staged metadata validation, and exceptions immediately after a successfully encoded valid stage;
- byte-for-byte preservation of existing destinations (and successful probe), absence of newly published destinations and stage cleanup;
- alias rejection before encoding;
- successful MOV/MP4 output with and without audio, result path/metadata and replacement;
- combined decoded video/audio SHA-256 hashes equal the prior direct command for eight operation/container/audio combinations;
- malformed/nonfinite/bool/oversized/type-invalid time values rejected before FFmpeg or staging.

Final focused run: **88 passed, 2 skipped in 18.36 s** across new writer tests, existing TestTrim/TestSpeed, advanced speed/trim, trim-end tests and contributor accurate-seek frame hashes. Two skips cover valid optional duration/end None values excluded from invalid-input parametrization. Ruff checks on changed runtime/tests passed; git diff --check passed; canonical `kinocut.Client is mcp_video.Client` import check passed.

Files owned this iteration: kinocut/engine_edit.py, kinocut/engine_speed.py, the three-line MAX_TRIM_TIME_TEXT_LENGTH addition in kinocut/validation.py, tests/test_engine_trim_end.py (existing command mock returns actual EditResult), and new tests/test_basic_writer_transactions.py. Earlier accurate seek and all unrelated shared dirty edits preserved.

Suggested changelog: “Trim and playback-speed edits publish atomically after staged output validation, preserving existing media when rendering or postflight fails. Invalid nonfinite, boolean and oversized trim times now return structured parameter errors before FFmpeg runs.”

Limits: publication is file-level atomic replacement, not a crash-durable fsync transaction or atomic database/media bundle; the existing shared helper defines the same guarantees as convert. Other direct-output effect writers remain outside this frozen scope. No blanket architecture migration was performed.
