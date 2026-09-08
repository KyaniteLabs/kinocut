# Sound input validation

Sound numeric guards inspect booleans before Pydantic can convert them to numbers.
Use numeric values for durations, gains, pan positions, loudness measurements and
targets, voice modifiers, cost estimates, adapter timeouts and profile versions.
`true` and `false` remain valid for actual boolean flags such as mute, solo and
human-review requirements.

The checked guard inventory and compatibility controls are retained in
`tests/fixtures/sound_numeric_guard_inventory.json` and
`tests/fixtures/sound_numeric_baseline.json`. They cover the existing numeric
guards plus receipt output duration and routing latency residuals.

## Existing input conventions

This does not enable global strict mode. Existing field-specific numeric-string
conversion, nullable values, defaults, enum strings and JSON arrays representing
tuples remain as defined by each model. Some fields already require actual
numeric primitives; their numeric-string rejection remains unchanged. In
particular, `OrderedInput` time fields and `Transformation` durations retain
their existing strict checks.

Profile-version pairs keep their normal container conversion and positive-integer
validation. Boolean version elements are rejected before integer conversion.
Malformed containers and rows still fail normal model validation.

Valid inputs retain their schema versions, normalized values and canonical hashes.
The change rejects ambiguous boolean numerics rather than changing audio processing.

## Public plan validation

`sound_plan_validate` accepts a valid serialized plan or a supported typed plan.
Typed plans are revalidated from their current serialized state, including nested
fields; an invalid `model_copy` cannot bypass validation merely by retaining its
class. This cannot recover input history already discarded by an earlier model
constructor. Valid typed and dictionary plans produce the same plan hash.

Omitting the plan or passing `None` retains the existing example-plan check.
An explicit empty dictionary, false value, empty string or other invalid plan
fails instead of selecting that example. The lower-level `plan_json` alias uses
the same selection rules: conflicting non-None aliases and unknown plan-validation
arguments fail. Legacy voice-plan mode also revalidates typed state and does not
silently ignore an alias when the primary plan is None.

Python, CLI and MCP share these checks. CLI validation errors retain the existing
nonzero exit and stderr message behavior; they do not emit a successful plan result.

