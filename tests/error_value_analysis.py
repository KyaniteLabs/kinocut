"""Locate caller-controlled strings that reach a public error message.

The leak spans functions: a handler receives a caller's string, passes it to
an engine, and the engine interpolates it into a refusal. This module
follows that path so a guard can fail on it and so a repair can find every
site at once.

What counts as caller data:

* a public tool handler's parameter whose declared type can hold a string
  (an unannotated one can, because JSON carries anything);
* the alias of a caught exception, whose text routinely embeds the path
  that failed;
* everything derived from those: a local assigned from one, a parameter
  passed down into another function, an attribute read off one.

What does not: a number, a value with a numeric type, an internal label
that every call site fills with a literal, and a value a package function
builds from its own shipped data.

The analysis is a fixed point over the call graph: a handler's parameter
is tainted, the taint reaches the parameters it is passed into, and the
process repeats until nothing new is tainted.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kinocut"

#: The shipped packages whose public errors reach the caller. Both are
#: scanned: a refusal raised in either one travels back out in the JSON
#: payload and the CLI panel.
PACKAGES = (PACKAGE, ROOT / "kinocut_sound")

#: The constructors whose message the caller reads.
ERROR_CALLS = frozenset(
    {
        "MCPVideoError",
        "ValidationError",
        "_validation_error",
        "_MCPVideoError",
        "_flow_error",
        "_fail",
        "ProcessingError",
        "CodecError",
        "InputFileError",
        "HyperframesProjectError",
        # The sound package's own contract errors, and the helpers that
        # build them. Their message reaches the caller through the
        # re-wrap in ``kinocut/server_tools_sound.py``.
        "SoundContractError",
        "VoiceError",
        "MixError",
        "_cutfile_error",
        "ir_error",
        "contract_error",
        "voice_error",
        "bounded_voice_error",
        "mix_error",
        # Every public subclass of MCPVideoError. A subclass that builds
        # its own message is inspected through its ``__init__``.
        "FFmpegNotFoundError",
        "FFprobeNotFoundError",
        "C2PAToolNotFoundError",
        "C2PASigningError",
        "C2PAVerificationError",
        "HyperframesNotFoundError",
        "HyperframesRenderError",
        "BackendUnavailableError",
        "ResourceError",
        "RevideoNotFoundError",
        "RevideoProjectError",
        "RevideoRenderError",
    }
)

#: The base classes. Their message is the finished text by definition, so
#: their own ``__init__`` is not a construction site.
ERROR_BASES = frozenset({"MCPVideoError", "Exception", "ValueError", "BackendUnavailableError"})

#: Exceptions whose message is written by the shipped package rather than
#: copied from a caller. Their text is guidance — "sample rate must be
#: positive" — so a re-wrap may carry it. The proof is not assumed: the
#: constructors above are scanned like every other error site, so a
#: caller value interpolated into one of these messages is reported.
CONTRACT_EXCEPTIONS = frozenset({"SoundContractError", "VoiceError", "MixError"})

#: For each constructor, the argument positions that reach the message text.
#:
#: A position that is not listed never becomes text: it is a label, a
#: machine-readable identifier, or a value the constructor strips. The
#: stripping matters — ``InputFileError(path, reason)`` removes the path
#: from the reason before it reaches the message, so a path passed there
#: is not an echo.
MESSAGE_POSITIONS: dict[str, frozenset[int]] = {
    "MCPVideoError": frozenset({0}),
    "ValidationError": frozenset({0, 1}),
    "InputFileError": frozenset({1}),
    # These classes build their own message from their own arguments, so
    # the call site publishes no message text at all. The class's
    # ``__init__`` is the construction site, and it is checked there.
    "ProcessingError": frozenset(),
    "HyperframesRenderError": frozenset(),
    "RevideoRenderError": frozenset(),
    "CodecError": frozenset({1}),
    "HyperframesProjectError": frozenset({1}),
    "RevideoProjectError": frozenset({1}),
    "_validation_error": frozenset({0}),
    "_MCPVideoError": frozenset({0}),
    "_flow_error": frozenset({0}),
    "_fail": frozenset({0}),
    "SoundContractError": frozenset({0}),
    "VoiceError": frozenset({0}),
    "MixError": frozenset({0}),
    "contract_error": frozenset({0}),
    "voice_error": frozenset({0}),
    "bounded_voice_error": frozenset({0}),
    "mix_error": frozenset({0}),
}

#: Keywords whose value never becomes message text.
NON_MESSAGE_KEYWORDS = frozenset({"error_type", "code", "docs_url"})

#: The helpers that build an error from a message the caller of a
#: validator already wrote. They are not entry points: their ``message``
#: parameter is the finished text, not the caller's input.
ERROR_BUILDERS = frozenset(
    {
        "contract_error",
        "voice_error",
        "bounded_voice_error",
        "mix_error",
        "bounded_mix_error",
        "dag_error",
        "workflow_error",
        "rescue_error",
        "_validation_error",
        "_MCPVideoError",
        "_flow_error",
        "_fail",
        "_creation_error",
        "_clamp_error",
        "_route_error",
    }
)

#: The helpers that make a value safe to name. A call to one of them is the
#: trust boundary: they name a value by its type and never copy it.
SANITIZERS = frozenset(
    {
        "rejected_value",
        "exception_kind",
        "invalid_parameter",
        # The shipped type-category helpers: identity, not names. A class's
        # ``__name__`` is mutable caller data; these read the type object
        # itself, so what they return is a shipped vocabulary.
        "builtin_type_name",
        "type_label",
        "number_text",
        # The text with the caller's submitted value removed.
        "_without_value",
        # The reason of one of our own errors. A foreign exception's text
        # is never republished; its kind is.
        "reason",
        # The rendered cause of a plan/review/package refusal: it
        # republishes exactly the causes own_reason marked and names
        # everything else by type, so it is safe on any input. The mark
        # itself (own_reason) is conditional — see below.
        "likely_cause",
        # The event kind, validated against the shipped set of kinds.
        "_validate_event_kind",
        # The operation kind, validated against the shipped kind sets.
        "_validate_operation_kind",
        # The house rule for naming a rejected value: by type only.
        "_describe",
        # Why a stored location is unsafe. The reason never contains the
        # location, so it is ours to publish.
        "location_violation",
        # A bounded, privacy-safe summary of our own validation error.
        "_summary",
    }
)

#: Sanitizers that are safe only when their argument is. The provenance
#: mark claims its argument was written by this package — a claim about
#: the argument, checked against it, not assumed: wrapping caller data in
#: ``own_reason`` stays a finding. ``likely_cause`` is NOT here: it is the
#: renderer for a cause of *unknown* provenance and collapses everything
#: unmarked by type, so it is safe on any input.
CONDITIONAL_SANITIZERS = frozenset(
    {
        "own_reason",
    }
)

#: A declared type that can hold a string.
STRING_TYPES = frozenset({"str", "Path", "Any", "object", "bytes"})
#: A declared type that cannot hold a string. Everything else is treated
#: as string-capable, so a type this analyzer cannot resolve fails closed.
NUMERIC_TYPES = frozenset({"int", "float", "bool", "None", "NoneType", "complex"})
#: A word that marks a string as a type expression rather than a value.
TYPE_WORDS = re.compile(
    r"\b(str|int|float|bool|bytes|complex|Path|Any|None|Optional|Union|Annotated"
    r"|Sequence|Mapping|Iterable|list|dict|tuple|set|Literal)\b"
)
#: A child process's own output. It is never guidance we wrote, and it
#: repeats the path the caller submitted.
DIAGNOSTIC_ATTRIBUTES = frozenset({"stderr", "stdout"})
#: A numeric format spec proves the value is a number: formatting a string
#: with ``:.0f`` raises.
NUMERIC_SPECS = frozenset("fFeEgGdiuXobn%")
#: Constructors whose result is a number whatever they were given.
#: ``sorted``, ``min`` and ``max`` are deliberately absent: they return
#: their argument's elements, and the caller's elements can be strings.
#: Treating them as numeric laundered a caller's string into a message —
#: the guard failed open on a live class rather than on a theoretical one.
NUMERIC_CALLS = frozenset({"float", "int", "bool", "round", "abs", "len", "sum"})
#: Calls whose result carries a tainted argument into the result.
CARRYING_CALLS = frozenset({"str", "repr", "format", "join", "Path", "PurePath"})

#: Attributes that hold a number however the object was obtained. A number
#: is safe to repeat, so these never taint.
NUMERIC_ATTRIBUTES = frozenset(
    {
        "width",
        "height",
        "display_width",
        "display_height",
        "timeline_duration_seconds",
        "error_count",
        "size",
        "count",
        "fps",
        "duration",
        "duration_sec",
        "index",
        "length",
        "len",
        "rate",
        "frames",
        "frame_count",
        "nframes",
        "bitrate",
        "channels",
        "sample_rate",
        "sar",
        "dar",
        "total",
        "limit",
        "max",
        "min",
        "value",
        "number",
        "pixels",
        "megapixels",
        "bytes",
        "r",
        "g",
        "b",
        "a",
    }
)


@dataclass(frozen=True)
class Finding:
    """One interpolation that carries a caller-controlled string."""

    path: Path
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    expression: str
    kind: str
    source: str


def callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def calls_in(node: ast.AST) -> list[ast.Call]:
    """Every call in ``node``, without descending into nested functions.

    A nested function has its own scope, so its calls belong to it and
    must not be attributed to the enclosing one.
    """
    found: list[ast.Call] = []

    def visit(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
                continue
            if isinstance(child, ast.Call):
                found.append(child)
            visit(child)

    visit(node)
    return found


def base_annotation(node: ast.AST | None) -> str:
    """The annotation with ``Annotated[...]`` unwrapped to its first arm."""
    if node is None:
        return "?"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Annotated":
        slice_node = node.slice
        if isinstance(slice_node, ast.Tuple) and slice_node.elts:
            return base_annotation(slice_node.elts[0])
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return "?"


def type_aliases() -> dict[str, list[str]]:
    """Module-level type aliases, and the type each one really is.

    A parameter annotated ``ExistingVideoPath`` is a string. The alias
    hides the ``str`` from a reader — and from an analyzer that only
    looks at the annotation's text — so an alias is resolved before the
    type is judged.
    """
    aliases: dict[str, list[str]] = {}
    for package in PACKAGES:
        for path in sorted(package.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover - defensive
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                base = base_annotation(node.value)
                if base == "?" or base == "None":
                    continue
                if not TYPE_WORDS.search(base) and not base.isidentifier():
                    continue
                bases = aliases.setdefault(target.id, [])
                if base not in bases:
                    bases.append(base)
    return aliases


def holds_string(text: str, aliases: dict[str, list[str]] | None = None, depth: int = 0) -> bool:
    """True when the declared type can carry a caller-controlled string.

    ``int | None`` cannot. ``int | str`` can — the string arm is the leak.
    An unannotated parameter can, so it is treated as string-capable.

    A type alias is resolved first: ``ExistingVideoPath`` is ``str``, and
    a reader — or an analyzer — that only sees the alias's name would
    wrongly conclude the parameter is safe. A type that cannot be
    resolved at all is treated as string-capable, so the guard fails
    closed rather than open.

    A container counts: a ``dict[str, str]`` carries caller-chosen keys
    and values, and a message that repeats one repeats the caller's
    input.
    """
    if text == "?":
        return True
    for part in (piece.strip() for piece in text.split("|")):
        if part in NUMERIC_TYPES:
            continue
        if aliases and part in aliases and depth < 5:
            if any(holds_string(base, aliases, depth + 1) for base in aliases[part]):
                return True
            continue
        # Not a number, and not a type this analyzer can read. It may
        # still hold a string, so it is treated as string-capable.
        return True
    return False


def holds_container(text: str) -> bool:
    """True when the declared type is a mapping or sequence of values.

    The elements of a container are the caller's too, so a loop that
    binds a name from one has bound caller data.
    """
    if text == "?":
        return False
    lowered = text.lower()
    return any(
        token in lowered for token in ("dict", "mapping", "list", "tuple", "sequence", "iterable", "set[", "frozenset")
    )


def spec_is_numeric(spec: ast.AST | None) -> bool:
    """True when the format spec proves the value is a number."""
    if spec is None:
        return False
    if isinstance(spec, ast.JoinedStr):
        text = "".join(
            part.value for part in spec.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    else:
        try:
            text = ast.unparse(spec)
        except Exception:  # pragma: no cover - defensive
            return False
    return bool(text) and text[-1] in NUMERIC_SPECS


def is_mcp_tool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for a function an MCP client calls by name."""
    for decorator in node.decorator_list:
        try:
            text = ast.unparse(decorator)
        except Exception:  # pragma: no cover - defensive
            text = ""
        if "mcp.tool" in text or "app.tool" in text:
            return True
    return False


def is_client_method(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for a public method of the Python client.

    The client is a public entry surface beside the MCP server: its
    methods take the caller's values directly, so a refusal built inside
    one reaches the caller the same way an MCP payload does. Leaving it
    unrooted is how ``Client._validate_choice`` came to echo the rejected
    value back as ``got {value}``.
    """
    if path.parent != PACKAGE / "client":
        return False
    if node.name.startswith("_"):
        return False
    args = node.args.posonlyargs + node.args.args
    return bool(args) and args[0].arg in {"self", "cls"}


def is_cli_handler(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for a function the CLI dispatches to.

    A CLI handler reads its arguments off the parsed namespace, so the
    values it forwards are caller data on the same footing as an MCP
    tool's parameters.
    """
    if path.parent != PACKAGE / "cli":
        return False
    if node.name.startswith("_"):
        return False
    args = node.args.posonlyargs + node.args.args
    if not args:
        return False
    return args[0].arg in {"a", "args", "namespace", "opts"}


def exported_names() -> set[tuple[str, str]]:
    """The functions a package's ``__all__`` publishes.

    A subpackage that publishes a validator publishes it as a public
    entry point: a caller can import it and hand it a value, and its
    refusal travels back to that caller. Rooting only the MCP, client,
    and CLI surfaces left the library surface unchecked.
    """
    exported: set[tuple[str, str]] = set()
    for package in PACKAGES:
        for init in sorted(package.rglob("__init__.py")):
            try:
                tree = ast.parse(init.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover - defensive
                continue
            names: list[str] = []
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Name)
                            and target.id == "__all__"
                            and isinstance(node.value, ast.List | ast.Tuple | ast.Set)
                        ):
                            names.extend(
                                element.value
                                for element in node.value.elts
                                if isinstance(element, ast.Constant) and isinstance(element.value, str)
                            )
            if not names:
                continue
            module = str(init.parent.relative_to(package))
            for name in names:
                exported.add((module, name))
    return exported


#: The published names, resolved once.
_EXPORTED_NAMES = exported_names()


def is_library_export(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for a function a subpackage publishes in its ``__all__``.

    The export is matched on the name the package publishes, not on the
    module the function happens to live in: a package re-exports a
    validator from a submodule, and the caller reaches it by the
    published name.

    A published *error builder* is not an entry point. It takes the
    message a caller of the validator already wrote, so rooting it would
    taint its own parameters and report every builder as a leak.
    """
    if node.name in ERROR_BUILDERS:
        return False
    for package in PACKAGES:
        try:
            relative = path.relative_to(package)
        except ValueError:
            continue
        module = str(relative.parent)
        if (module, node.name) in _EXPORTED_NAMES:
            return True
    return False


def root_kind(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Which public entry surface this function is, if any.

    Every surface a caller can reach must be a root, or the analysis
    only proves the redaction for the surface that was checked.
    """
    if is_mcp_tool(node):
        return "mcp"
    if is_client_method(path, node):
        return "client"
    if is_cli_handler(path, node):
        return "cli"
    if is_library_export(path, node):
        return "library"
    return None


def _numeric_names(node: ast.AST) -> set[str]:
    """Names the code has already established are numbers.

    A number may be repeated in a message; only a string, a path or a
    caught exception's text is caller data. The code itself says which
    is which: a value it compares against a numeric literal, or checks
    with ``isinstance(value, (int, float))``, is a number at that point.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Compare):
            for other in child.comparators:
                for subject, candidate in ((child.left, other), (other, child.left)):
                    if isinstance(subject, ast.Name) and _is_number_literal(candidate):
                        names.add(subject.id)
        elif isinstance(child, ast.Call) and callee_name(child) == "isinstance":
            if len(child.args) != 2 or not _mentions_number_type(child.args[1]):
                continue
            target = child.args[0]
            if isinstance(target, ast.Name):
                names.add(target.id)
        elif (
            isinstance(child, ast.Call)
            and callee_name(child) in {"int", "float"}
            and child.args
            and isinstance(child.args[0], ast.Name)
        ):
            # A value the code hands to a numeric constructor is a number at
            # that point, whether or not it was annotated.
            names.add(child.args[0].id)
    return names


def _is_number_literal(node: ast.expr) -> bool:
    """True for a literal number, or a call that always yields one."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int | float | complex) and not isinstance(node.value, bool)
    if isinstance(node, ast.Call):
        return callee_name(node) in {"len", "int", "float", "abs", "round"}
    return False


def _mentions_number_type(node: ast.expr) -> bool:
    """True for a type expression that includes a numeric type."""
    if isinstance(node, ast.Name):
        return node.id in {"int", "float", "complex"}
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(_mentions_number_type(element) for element in node.elts)
    return False


class Function:
    """One function in the package, with what it knows about taint."""

    __slots__ = ("aliases", "annotations", "handler", "node", "numeric", "params", "path", "root_kind", "tainted")

    def __init__(self, path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.path = path
        self.node = node
        args = node.args
        self.params: list[str] = []
        self.annotations: dict[str, str] = {}
        for group in (args.posonlyargs, args.args, args.kwonlyargs):
            for arg in group:
                self.params.append(arg.arg)
                self.annotations[arg.arg] = base_annotation(arg.annotation)
        if args.vararg:
            self.params.append(args.vararg.arg)
            self.annotations[args.vararg.arg] = "?"
        if args.kwarg:
            self.params.append(args.kwarg.arg)
            self.annotations[args.kwarg.arg] = "?"
        self.root_kind = root_kind(path, node)
        self.handler = self.root_kind is not None
        self.tainted: set[str] = set()
        self.numeric: set[str] = _numeric_names(node)
        self.aliases: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.ExceptHandler) and child.name:
                self.aliases.add(child.name)

    @property
    def name(self) -> str:
        return self.node.name


def package_functions() -> tuple[dict[str, list[Function]], list[Function]]:
    """Every function in the shipped packages, indexed by its bare name."""
    by_name: dict[str, list[Function]] = {}
    all_functions: list[Function] = []
    for package in PACKAGES:
        for path in sorted(package.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover - defensive
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    function = Function(path, node)
                    by_name.setdefault(function.name, []).append(function)
                    all_functions.append(function)
    return by_name, all_functions


def _label_candidates(candidates: list[Function], caller: Function, call: ast.Call) -> list[Function]:
    """The helpers a call site can be talking to.

    Three modules each define a ``_require_digest`` with different
    parameters. A call in one of them is a call to *that* one, so the
    helper in the caller's own module wins; otherwise the signature has to
    fit.
    """
    local = [candidate for candidate in candidates if candidate.path.name == caller.path.name]
    if local:
        return local
    fitting = []
    for candidate in candidates:
        names = list(candidate.params)
        if len(call.args) > len(names):
            continue
        if any(keyword.arg is not None and keyword.arg not in names for keyword in call.keywords):
            continue
        fitting.append(candidate)
    return fitting or candidates


def label_parameters() -> set[tuple[str, str, str]]:
    """Parameters every call site fills with a literal, or with a label.

    Those are internal labels — ``name="width"``, ``label="destination"`` —
    chosen by the shipped code, not by the caller. A parameter with no call
    site in the package is not a label: the caller may still supply it.

    A label often arrives through another label: a helper's ``name`` comes
    from a caller that was handed a literal two frames up. The rule follows
    the name down, or every downstream frame would see a label as caller
    data.

    The key names the *file* as well as the function: three modules each
    define a ``_require_digest`` with different parameters, and they are
    different helpers.
    """
    by_name, all_functions = package_functions()
    # (callee file, callee name, parameter) -> every way a call site filled it.
    filled: dict[tuple[str, str, str], list[ast.expr]] = {}
    callers: dict[tuple[str, str, str], list[tuple[Function, ast.expr]]] = {}
    for function in all_functions:
        for call in calls_in(function.node):
            name = callee_name(call)
            if name is None or name not in by_name:
                continue
            for candidate in _label_candidates(by_name[name], function, call):
                names = list(candidate.params)
                for position, argument in enumerate(call.args):
                    if position >= len(names):
                        break
                    key = (candidate.path.name, name, names[position])
                    filled.setdefault(key, []).append(argument)
                    callers.setdefault(key, []).append((function, argument))
                for keyword in call.keywords:
                    if keyword.arg is None or keyword.arg not in names:
                        continue
                    key = (candidate.path.name, name, keyword.arg)
                    filled.setdefault(key, []).append(keyword.value)
                    callers.setdefault(key, []).append((function, keyword.value))
    labels: set[tuple[str, str, str]] = set()
    changed = True
    while changed:
        changed = False
        for key, _arguments in filled.items():
            if key in labels:
                continue
            for function, argument in callers[key]:
                if isinstance(argument, ast.Constant):
                    continue
                # A label passed on from the caller is still a label.
                if isinstance(argument, ast.Name) and (function.path.name, function.name, argument.id) in labels:
                    continue
                break
            else:
                labels.add(key)
                changed = True
    return labels


def _string_collection_literal(node: ast.AST) -> bool:
    """True when the expression is a literal collection of string constants.

    ``{"2x2", "3x1"}`` is a vocabulary the package owns: nobody chose its
    elements at a call site.
    """
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return False
    return all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in node.elts)


def _collect_vocabulary_name(statement: ast.stmt, names: set[str]) -> None:
    """Record a name the module or a class binds to a literal string set."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        if _string_collection_literal(statement.value):
            names.add(statement.targets[0].id)
    elif (
        isinstance(statement, ast.AnnAssign)
        and statement.value is not None
        and isinstance(statement.target, ast.Name)
        and _string_collection_literal(statement.value)
    ):
        names.add(statement.target.id)


_VOCABULARIES: dict[str, set[str]] | None = None


def _module_vocabularies() -> dict[str, set[str]]:
    """The shipped vocabularies, by the module that binds them.

    A name bound at module level or as a class attribute to a literal
    collection of string constants names a vocabulary the package owns.
    Function-local bindings are not vocabularies: a local can be rebound
    from caller data, and a module-level or class-level literal cannot.
    """
    global _VOCABULARIES
    if _VOCABULARIES is None:
        vocabularies: dict[str, set[str]] = {}
        for package in PACKAGES:
            for path in sorted(package.rglob("*.py")):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError):  # pragma: no cover - defensive
                    continue
                names = vocabularies.setdefault(path.name, set())
                for statement in tree.body:
                    _collect_vocabulary_name(statement, names)
                    if not isinstance(statement, ast.ClassDef):
                        continue
                    for member in statement.body:
                        _collect_vocabulary_name(member, names)
        _VOCABULARIES = vocabularies
    return _VOCABULARIES


def _is_vocabulary(argument: ast.AST, caller: Function, vocabularies: dict[str, set[str]]) -> bool:
    """True when the argument is one of the caller module's own vocabularies."""
    if _string_collection_literal(argument):
        return True
    if isinstance(argument, ast.Name):
        return argument.id in vocabularies.get(caller.path.name, set())
    if isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name):
        return argument.attr in vocabularies.get(caller.path.name, set())
    return False


def vocabulary_parameters() -> set[tuple[str, str, str]]:
    """Parameters every call site fills with a shipped vocabulary.

    ``_validate_choice(name, value, valid_values)`` is handed a set of the
    package's own accepted values at every call site — a module constant or
    a ``ClassVar`` literal set — so publishing it publishes shipped
    guidance, not the caller's input. This is the vocabulary twin of
    ``label_parameters``: a parameter with no call site in the package is
    not a vocabulary, because the caller may still supply it.

    The key names the *file* as well as the function, for the same reason
    the label rule does.
    """
    by_name, all_functions = package_functions()
    vocabularies = _module_vocabularies()
    filled: dict[tuple[str, str, str], list[tuple[Function, ast.expr]]] = {}
    for function in all_functions:
        for call in calls_in(function.node):
            name = callee_name(call)
            if name is None or name not in by_name:
                continue
            for candidate in _label_candidates(by_name[name], function, call):
                names = list(candidate.params)
                for position, argument in enumerate(call.args):
                    if position >= len(names):
                        break
                    filled.setdefault((candidate.path.name, name, names[position]), []).append((function, argument))
                for keyword in call.keywords:
                    if keyword.arg is None or keyword.arg not in names:
                        continue
                    filled.setdefault((candidate.path.name, name, keyword.arg), []).append((function, keyword.value))
    return {
        key
        for key, fills in filled.items()
        if all(_is_vocabulary(argument, function, vocabularies) for function, argument in fills)
    }


_NUMERIC_RETURNS: set[str] | None = None


_TUPLE_ELEMENTS: dict[str, list[str]] | None = None


def _tuple_elements() -> dict[str, list[str]]:
    """The element types of a function's declared tuple return.

    ``tuple[int, int, float, bool, str]`` says which unpacked name is a
    number and which is not.
    """
    global _TUPLE_ELEMENTS
    if _TUPLE_ELEMENTS is None:
        elements: dict[str, list[str]] = {}
        _by_name, all_functions = package_functions()
        for candidate in all_functions:
            if candidate.node.returns is None:
                continue
            returned = base_annotation(candidate.node.returns)
            if not (returned.startswith("tuple[") and returned.endswith("]")):
                continue
            inner = returned[len("tuple[") : -1]
            elements[candidate.name] = [part.strip() for part in inner.split(",")]
        _TUPLE_ELEMENTS = elements
    return _TUPLE_ELEMENTS


def _numeric_returns() -> set[str]:
    """Functions whose declared return type is a number.

    A call to one of them returns a number, whatever it was handed, and a
    number may be repeated in a message.
    """
    global _NUMERIC_RETURNS
    if _NUMERIC_RETURNS is None:
        names: set[str] = set()
        _by_name, all_functions = package_functions()
        for candidate in all_functions:
            if candidate.node.returns is None:
                continue
            returned = base_annotation(candidate.node.returns)
            if returned and all(part.strip() in NUMERIC_TYPES for part in returned.split("|")):
                names.add(candidate.name)
            elif returned.startswith("tuple[") and returned.endswith("]"):
                inner = returned[len("tuple[") : -1]
                parts = [part.strip() for part in inner.split(",")]
                if parts and all(part in NUMERIC_TYPES for part in parts):
                    names.add(candidate.name)
        _NUMERIC_RETURNS = names
    return _NUMERIC_RETURNS


def _provably_numeric(node: ast.AST, function: Function) -> bool:
    """True when the expression is a number by code, not by guesswork.

    A number may be repeated in a message, so a container of numbers is
    safe to publish. Deciding that from the code — a numeric literal, a
    numeric attribute, a numeric constructor, arithmetic over those —
    is what keeps the guard from laundering a caller's string through a
    call like ``sorted``.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int | float | complex) and not isinstance(node.value, bool)
    if isinstance(node, ast.Attribute):
        return node.attr in NUMERIC_ATTRIBUTES
    if isinstance(node, ast.Name):
        return node.id in function.numeric
    if isinstance(node, ast.Call):
        return callee_name(node) in NUMERIC_CALLS
    if isinstance(node, ast.BinOp):
        return _provably_numeric(node.left, function) and _provably_numeric(node.right, function)
    if isinstance(node, ast.UnaryOp):
        return _provably_numeric(node.operand, function)
    if isinstance(node, ast.Compare):
        return all(_provably_numeric(part, function) for part in [node.left, *node.comparators])
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return bool(node.elts) and all(_provably_numeric(element, function) for element in node.elts)
    if isinstance(node, ast.IfExp):
        return _provably_numeric(node.body, function) and _provably_numeric(node.orelse, function)
    return False


def _is_tainted_expr(node: ast.AST, function: Function) -> bool:
    """True when the expression carries a caller-controlled string.

    The walk is recursive rather than flat so that a numeric attribute
    stops the descent: ``img.width`` is a number even when ``img`` came
    from a caller-controlled path. ``x.__name__`` is NOT such a stop: a
    class's name is mutable, caller-controlled data, so a message that
    interpolates it is a publication of caller data — the shipped helpers
    in :mod:`kinocut.type_names` are the only way to name a type.

    A call to one of the sanitizers is the trust boundary: those helpers
    name a value by its type and never copy it, so what they return is
    safe by construction. The conditional sanitizers are safe only when
    what they were handed is safe: wrapping caller data in ``own_reason``
    must stay a finding.
    """
    tainted = function.tainted
    if isinstance(node, ast.Call):
        name = callee_name(node)
        if name in CONDITIONAL_SANITIZERS:
            # The provenance mark is a claim about its argument: the call
            # is safe exactly when the argument is, and never otherwise.
            arguments = [argument for argument in node.args]
            arguments.extend(keyword.value for keyword in node.keywords)
            return any(_is_tainted_expr(argument, function) for argument in arguments)
        if name in SANITIZERS:
            return False
        if name in NUMERIC_CALLS:
            return False
        if name in _numeric_returns():
            # The function declares that it returns a number, so the number
            # is what comes back, not the value it was handed.
            return False
        if name in CARRYING_CALLS:
            return any(_is_tainted_expr(argument, function) for argument in node.args)
        # A value pulled out of a caller-supplied container is caller data:
        # ``op.get("op")`` returns the string the caller submitted.
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop"}:
            return _is_tainted_expr(node.func.value, function)
        if isinstance(node.func, ast.Attribute):
            # A method on a caller-controlled value can carry it: ``x.strip()``,
            # ``x.lower()``, ``x.replace(...)``.
            return _is_tainted_expr(node.func.value, function)
        # A call that is handed caller data can return caller data: a helper
        # that takes a path and returns paths derived from it carries the
        # caller's path. The sanitizers and the numeric calls above are the
        # known exceptions; everything else is assumed to carry what it was
        # given, so the guard fails closed. A keyword argument carries it
        # too, and a **mapping carries all of it: a model built from a
        # caller's dictionary is made of that dictionary's values.
        if any(_is_tainted_expr(keyword.value, function) for keyword in node.keywords):
            return True
        return any(_is_tainted_expr(argument, function) for argument in node.args)
    if isinstance(node, ast.Name):
        if node.id in function.numeric:
            # The code has established this is a number, and a number may
            # be repeated in a message.
            return False
        return node.id in tainted
    if isinstance(node, ast.Attribute):
        if node.attr == "__name__":
            # A class's or module's ``__name__`` is mutable, caller-
            # controlled data, and there is no branch of a message where
            # publishing it is sound — the shipped helpers in
            # ``kinocut.type_names`` are the only way to name a type. This
            # is total on purpose: even a name the code elsewhere believes
            # is numeric may be named here precisely because it is NOT one
            # (``type(evt_at).__name__`` under a failed isinstance check).
            return True
        if node.attr in NUMERIC_ATTRIBUTES:
            return False
        if node.attr in DIAGNOSTIC_ATTRIBUTES and not (isinstance(node.value, ast.Name) and node.value.id == "sys"):
            # A child process's output is a diagnostic, not guidance we
            # wrote: it repeats the path the caller submitted.
            return True
        return _is_tainted_expr(node.value, function)
    if isinstance(node, ast.BinOp):
        return _is_tainted_expr(node.left, function) or _is_tainted_expr(node.right, function)
    if isinstance(node, ast.UnaryOp):
        return _is_tainted_expr(node.operand, function)
    if isinstance(node, ast.BoolOp):
        return any(_is_tainted_expr(value, function) for value in node.values)
    if isinstance(node, ast.IfExp):
        return _is_tainted_expr(node.body, function) or _is_tainted_expr(node.orelse, function)
    if isinstance(node, ast.Subscript):
        return _is_tainted_expr(node.value, function)
    if isinstance(node, ast.JoinedStr):
        return any(
            _is_tainted_expr(part.value, function) for part in node.values if isinstance(part, ast.FormattedValue)
        )
    if isinstance(node, ast.FormattedValue):
        return _is_tainted_expr(node.value, function)
    if isinstance(node, ast.Await | ast.Starred):
        return _is_tainted_expr(node.value, function)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return any(_is_tainted_expr(element, function) for element in node.elts)
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
        # A comprehension over caller data is a projection of caller data,
        # whatever its element expression is: a filter over the caller's
        # values keeps their names. The exception is a projection that is
        # a number by code — the operator may repeat a number.
        if _provably_numeric(node.elt, function):
            return False
        return _is_tainted_expr(node.elt, function) or any(
            _is_tainted_expr(generator.iter, function) or _is_tainted_expr(generator.target, function)
            for generator in node.generators
        )
    if isinstance(node, ast.DictComp):
        if _provably_numeric(node.key, function) and _provably_numeric(node.value, function):
            return False
        return (
            _is_tainted_expr(node.key, function)
            or _is_tainted_expr(node.value, function)
            or any(
                _is_tainted_expr(generator.iter, function) or _is_tainted_expr(generator.target, function)
                for generator in node.generators
            )
        )
    if isinstance(node, ast.Dict):
        return any(_is_tainted_expr(key, function) for key in node.keys if key is not None) or any(
            _is_tainted_expr(value, function) for value in node.values
        )
    return False


def _target_names(target: ast.expr) -> list[str]:
    """The names a binding target introduces."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [element.id for element in target.elts if isinstance(element, ast.Name)]
    return []


def _local_taint(function: Function) -> bool:
    """Taint the locals of one function from what it already knows."""
    changed = False
    for child in ast.walk(function.node):
        if isinstance(child, ast.comprehension):
            # The loop variable of a comprehension over caller data is the
            # caller's data: it is one of their values.
            if not _is_tainted_expr(child.iter, function):
                continue
            for name in _target_names(child.target):
                if name not in function.tainted:
                    function.tainted.add(name)
                    changed = True
            continue
        if not isinstance(child, ast.Assign | ast.AnnAssign):
            continue
        if not _is_tainted_expr(child.value, function):
            continue
        targets: list[ast.expr] = []
        for target in child.targets if isinstance(child, ast.Assign) else [child.target]:
            if isinstance(target, ast.Name):
                targets.append(target)
            elif isinstance(target, ast.Tuple | ast.List):
                targets.extend(element for element in target.elts if isinstance(element, ast.Name))
        element_types = None
        if isinstance(child.value, ast.Call):
            element_types = _tuple_elements().get(callee_name(child.value) or "")
        for position, target in enumerate(targets):
            assert isinstance(target, ast.Name)
            if element_types is not None and position < len(element_types) and element_types[position] in NUMERIC_TYPES:
                # The declared tuple says what each unpacked name is.
                continue
            if target.id not in function.tainted:
                function.tainted.add(target.id)
                changed = True
    return changed


def _loop_key_taint(function: Function) -> bool:
    """Taint the loop variables a caller's dictionary contributes.

    ``for key, value in metadata.items()`` binds ``key`` to a name the
    caller chose. The name is caller data even when the dictionary itself
    is a parameter the analyzer already knows, so a message that repeats
    the key repeats the caller's input.
    """
    changed = False
    for child in ast.walk(function.node):
        if not isinstance(child, ast.For):
            continue
        iterator = child.iter
        enumerate_index = False
        if isinstance(iterator, ast.Call):
            name = callee_name(iterator)
            if name in {"items", "keys"}:
                receiver = iterator.func
                if not isinstance(receiver, ast.Attribute):
                    continue
                if not _is_tainted_expr(receiver.value, function):
                    continue
            elif name in {"enumerate", "zip"}:
                # ``for i, op in enumerate(post_process)`` binds the element
                # the caller submitted, not a shipped name. The first name
                # of an ``enumerate`` is the index, which is a number.
                if not any(_is_tainted_expr(argument, function) for argument in iterator.args):
                    continue
                enumerate_index = name == "enumerate"
            else:
                continue
        elif not _is_tainted_expr(iterator, function):
            # ``for key in caller_dict`` binds the key the same way.
            continue
        targets = child.target
        if isinstance(targets, ast.Tuple | ast.List):
            names = [target.id for target in targets.elts if isinstance(target, ast.Name)]
        elif isinstance(targets, ast.Name):
            names = [targets.id]
        else:
            continue
        if enumerate_index and names:
            # The index of an ``enumerate`` is a number, and a number may
            # be repeated in a message.
            names = names[1:]
        for name in names:
            if name in function.tainted:
                continue
            function.tainted.add(name)
            changed = True
    return changed


def _propagate(
    function: Function,
    by_name: dict[str, list[Function]],
    labels: set[tuple[str, str, str]],
    vocabularies: frozenset[tuple[str, str, str]] | set[tuple[str, str, str]] = frozenset(),
) -> bool:
    """Pass taint from this function's arguments into the ones it calls."""
    changed = False
    for call in calls_in(function.node):
        name = callee_name(call)
        if name is None or name in ERROR_CALLS or name in SANITIZERS:
            continue
        for candidate in by_name.get(name, ()):
            for position, argument in enumerate(call.args):
                if position >= len(candidate.params):
                    break
                if not _is_tainted_expr(argument, function):
                    continue
                parameter = candidate.params[position]
                if parameter in candidate.tainted:
                    continue
                if (candidate.path.name, candidate.name, parameter) in labels:
                    # A label every call site fills with shipped text.
                    continue
                if (candidate.path.name, candidate.name, parameter) in vocabularies:
                    # A vocabulary every call site fills from shipped constants.
                    continue
                declared = candidate.annotations.get(parameter, "?")
                if not holds_string(declared) and not holds_container(declared):
                    continue
                if parameter in candidate.numeric or parameter in NUMERIC_ATTRIBUTES:
                    # The callee only ever uses it as a number.
                    continue
                candidate.tainted.add(parameter)
                changed = True
            for keyword in call.keywords:
                if keyword.arg is None:
                    # A **mapping argument fills the callee's keyword
                    # parameter: helper(**mapping) hands the whole thing on,
                    # so the callee now holds caller data.
                    if not _is_tainted_expr(keyword.value, function):
                        continue
                    kwarg = candidate.node.args.kwarg
                    if kwarg is None or kwarg.arg in candidate.tainted:
                        continue
                    candidate.tainted.add(kwarg.arg)
                    changed = True
                    continue
                if keyword.arg not in candidate.params:
                    continue
                if not _is_tainted_expr(keyword.value, function):
                    continue
                if keyword.arg in candidate.tainted:
                    continue
                if (candidate.path.name, candidate.name, keyword.arg) in labels:
                    continue
                if (candidate.path.name, candidate.name, keyword.arg) in vocabularies:
                    continue
                declared = candidate.annotations.get(keyword.arg, "?")
                if not holds_string(declared) and not holds_container(declared):
                    continue
                if keyword.arg in candidate.numeric or keyword.arg in NUMERIC_ATTRIBUTES:
                    continue
                candidate.tainted.add(keyword.arg)
                changed = True
    return changed


def tainted_functions(
    labels: set[tuple[str, str, str]],
    vocabularies: frozenset[tuple[str, str, str]] | set[tuple[str, str, str]] = frozenset(),
) -> list[Function]:
    """Every function that holds caller-controlled data."""
    by_name, all_functions = package_functions()
    aliases = type_aliases()
    for function in all_functions:
        function.tainted.update(function.aliases)
        if not function.handler:
            continue
        for parameter, declared in function.annotations.items():
            if all(part.strip() in NUMERIC_TYPES for part in declared.split("|")):
                # A number may be repeated in a message.
                continue
            if not holds_string(declared, aliases) and not holds_container(declared):
                continue
            if (function.name, parameter) in labels:
                continue
            function.tainted.add(parameter)
    changed = True
    while changed:
        changed = False
        for function in all_functions:
            if _local_taint(function):
                changed = True
            if _loop_key_taint(function):
                changed = True
            if _propagate(function, by_name, labels, vocabularies):
                changed = True
    return all_functions


def _expression_kind(target: ast.AST, function: Function) -> str:
    """Whether the expression is a caught exception or any other value."""
    if isinstance(target, ast.Name) and target.id in function.aliases:
        return "exception"
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in function.aliases:
        return "exception"
    return "value"


def _caught_type(function: Function, alias: str) -> str | None:
    """The class named by ``except <Type> as alias``."""
    for child in ast.walk(function.node):
        if not isinstance(child, ast.ExceptHandler) or child.name != alias:
            continue
        if child.type is None:
            return None
        if isinstance(child.type, ast.Tuple):
            for element in child.type.elts:
                name = ast.unparse(element)
                if name in CONTRACT_EXCEPTIONS:
                    return name
            return None
        return ast.unparse(child.type)
    return None


def _is_contract_exception(target: ast.AST, function: Function) -> bool:
    """True when the expression reads a contract exception's own text.

    A contract exception's message is written by the shipped package, so
    it is guidance rather than a copy of the caller's input. The
    construction sites of those messages are scanned like every other
    error site, so a caller value interpolated into one is reported there.
    """
    alias: str | None = None
    if isinstance(target, ast.Name):
        alias = target.id
    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        alias = target.value.id
    elif isinstance(target, ast.Call) and callee_name(target) in {"str", "repr"}:
        first = target.args[0] if target.args else None
        if isinstance(first, ast.Name):
            alias = first.id
    if alias is None or alias not in function.aliases:
        return False
    return _caught_type(function, alias) in CONTRACT_EXCEPTIONS


#: Findings that are not caller data, each with the reason it is safe.
#:
#: The key is the file and the exact message, so a change to either line
#: brings the finding back: the exemption stops matching and the analyzer
#: reports it again. Nothing here is a threshold or a count.
#:
#: One entry remains. The rest of what the analyzer has raised turned out
#: to be a real leak or a precision gap in the analyzer, and both were
#: fixed at the source rather than exempted here.
EXEMPT: dict[tuple[str, str], str] = {
    (
        "kinocut/quality_guardrails.py",
        "fQuality gate failed: {; .join(failures)}. {recommendations}",
    ): (
        "The failures are the package's own sentences about the measured media and its "
        "recommendations are the messages of the package's own failed quality checks "
        "(quality_guardrails builds them as literals at the check). They travel through "
        "the report dictionary, so the analyzer cannot see that they are ours; it sees a "
        "tainted container. No value the caller submitted is in either."
    ),
}


def _collect_leaks() -> list[Finding]:
    """Every finding, including the ones an exemption covers."""
    labels = label_parameters()
    vocabularies = vocabulary_parameters()
    findings: list[Finding] = []
    functions = tainted_functions(labels, vocabularies)
    findings.extend(_constructor_leaks(functions))
    for function in functions:
        if function.name in ERROR_BUILDERS:
            # A builder's message parameter is the finished text. The call
            # site that built that text is where a leak would be, and it
            # is checked there.
            continue
        for call in calls_in(function.node):
            name = callee_name(call)
            if name not in ERROR_CALLS:
                continue
            positions = MESSAGE_POSITIONS.get(name, frozenset({0}))
            for position, argument in enumerate(call.args):
                if position not in positions:
                    continue
                findings.extend(_argument_leaks(argument, call, function))
            for keyword in call.keywords:
                if keyword.arg in NON_MESSAGE_KEYWORDS:
                    continue
                if keyword.arg == "suggested_action":
                    findings.extend(_action_leaks(keyword.value, function))
                    continue
                findings.extend(_argument_leaks(keyword.value, call, function))
    return findings


def raw_leaks() -> list[Finding]:
    """Every finding, including the ones an exemption covers."""
    return _collect_leaks()


def find_leaks() -> list[Finding]:
    """Every interpolation of a caller-controlled string into an error."""
    return [finding for finding in _collect_leaks() if _exemption_for(finding) is None]


def _message_key(source: str) -> str:
    """The message without its quoting.

    ``ast.unparse`` picks its quote style by interpreter version — 3.12 and
    3.14 disagree — so a key built from the raw source stops matching on
    the other one, and an exemption that silently stops applying is worse
    than no exemption at all. The quoting is not part of the message.
    """
    return source.replace('"', "").replace("'", "")


def _exemption_for(finding: Finding) -> str | None:
    """The reason a finding is not caller data, when it is exempt."""
    try:
        relative = str(finding.path.relative_to(ROOT))
    except ValueError:
        return None
    return EXEMPT.get((relative, _message_key(finding.source)))


def unused_exemptions(findings: list[Finding]) -> list[tuple[str, str]]:
    """Exemptions that no longer match anything.

    An exemption that matches nothing is a stale statement about code that
    has since changed, so the guard asks for this to be empty.
    """
    matched = {(str(finding.path.relative_to(ROOT)), _message_key(finding.source)) for finding in findings}
    return [key for key in EXEMPT if key not in matched]


def _error_classes() -> dict[str, tuple[Path, ast.ClassDef, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every shipped error class, with the ``__init__`` that builds its message."""
    classes: dict[str, tuple[Path, ast.ClassDef, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for package in PACKAGES:
        for path in sorted(package.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover - defensive
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name not in ERROR_CALLS:
                    continue
                initialiser = next(
                    (
                        member
                        for member in node.body
                        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name == "__init__"
                    ),
                    None,
                )
                if initialiser is None:
                    continue
                classes.setdefault(node.name, (path, node, initialiser))
    return classes


def _constructor_leaks(functions: list[Function]) -> list[Finding]:
    """Leaks in an error class that builds its own message.

    ``HyperframesRenderError(command, returncode, stderr)`` does not take
    a message: it makes one from its own arguments, and those arguments
    come from the caller and from a subprocess. A class that interpolates
    them into the message repeats the caller's data, so the class's
    ``__init__`` is a construction site.

    Only the parameters a caller actually passes caller data into count.
    A class whose every caller passes shipped text — ``ValidationError`` —
    is free to repeat it.
    """
    classes = _error_classes()
    findings: list[Finding] = []

    # Which parameters does each class receive caller data in?
    tainted_parameters: dict[str, set[str]] = {}
    for function in functions:
        if function.name in ERROR_BUILDERS:
            continue
        for call in calls_in(function.node):
            name = callee_name(call)
            if name not in classes:
                continue
            parameters = _parameter_names(classes[name][2])
            for position, argument in enumerate(call.args):
                if not _is_tainted_expr(argument, function):
                    continue
                if position < len(parameters):
                    tainted_parameters.setdefault(name, set()).add(parameters[position])
            for keyword in call.keywords:
                if keyword.arg is None or not _is_tainted_expr(keyword.value, function):
                    continue
                tainted_parameters.setdefault(name, set()).add(keyword.arg)

    for name, (path, _node, initialiser) in classes.items():
        if name in ERROR_BASES:
            continue
        received = tainted_parameters.get(name, set())
        if not received:
            continue
        function = Function(path, initialiser)
        # A parameter the class annotates as a number holds a number, and a
        # number may be repeated. The annotation decides, not the name.
        for parameter, declared in function.annotations.items():
            parts = {part.strip() for part in declared.split("|")}
            if parts and parts <= NUMERIC_TYPES:
                received.discard(parameter)
        function.tainted.update(received)
        # The class's message is often built by assignment rather than
        # written at the call to ``super().__init__``, so the locals it
        # derives from a tainted parameter are tainted too.
        for _round in range(3):
            if not _local_taint(function):
                break
        for call in calls_in(initialiser):
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "__init__":
                continue
            for position, argument in enumerate(call.args):
                if position != 0:
                    continue
                findings.extend(_argument_leaks(argument, call, function))
            for keyword in call.keywords:
                if keyword.arg in NON_MESSAGE_KEYWORDS:
                    continue
                if keyword.arg == "suggested_action":
                    findings.extend(_action_leaks(keyword.value, function))
                    continue
                findings.extend(_argument_leaks(keyword.value, call, function))
    return findings


def _parameter_names(initialiser: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The constructor's own parameter names, in order."""
    args = initialiser.args
    names: list[str] = []
    for group in (args.posonlyargs, args.args, args.kwonlyargs):
        for argument in group:
            if argument.arg != "self":
                names.append(argument.arg)
    return names


def _argument_leaks(argument: ast.expr, call: ast.Call, function: Function) -> list[Finding]:
    """The leaks in one argument of an error constructor."""
    if isinstance(argument, ast.JoinedStr):
        return _joined_leaks(argument, call, function)
    if _is_contract_exception(argument, function):
        return []
    if _is_tainted_expr(argument, function):
        return [_named_leak(argument, call, function)]
    return []


def _action_leaks(action: ast.expr, function: Function) -> list[Finding]:
    """The leaks inside a suggested action.

    The action's description and remedy are read by the operator, so a
    caller-controlled value in either reaches the payload.
    """
    findings: list[Finding] = []
    if not isinstance(action, ast.Dict):
        return findings
    placeholder = ast.Call(func=ast.Name(id="_action"), args=[], keywords=[])
    for key, value in zip(action.keys, action.values, strict=True):
        if not isinstance(key, ast.Constant) or key.value not in {"description", "remedy"}:
            continue
        if isinstance(value, ast.JoinedStr):
            findings.extend(_joined_leaks(value, placeholder, function))
        elif _is_tainted_expr(value, function):
            findings.append(_named_leak(value, placeholder, function))
    return findings


def _joined_leaks(argument: ast.JoinedStr, call: ast.Call, function: Function) -> list[Finding]:
    findings: list[Finding] = []
    for part in argument.values:
        if not isinstance(part, ast.FormattedValue):
            continue
        if not _is_tainted_expr(part.value, function):
            continue
        if spec_is_numeric(part.format_spec):
            continue
        if _is_contract_exception(part.value, function):
            continue
        findings.append(
            Finding(
                path=function.path,
                lineno=part.lineno,
                col_offset=part.col_offset,
                end_lineno=part.end_lineno,
                end_col_offset=part.end_col_offset,
                expression=ast.unparse(part.value),
                kind=_expression_kind(part.value, function),
                source=ast.unparse(argument),
            )
        )
    return findings


def _named_leak(argument: ast.expr, call: ast.Call, function: Function) -> Finding:
    return Finding(
        path=function.path,
        lineno=argument.lineno,
        col_offset=argument.col_offset,
        end_lineno=argument.end_lineno,
        end_col_offset=argument.end_col_offset,
        expression=ast.unparse(argument),
        kind=_expression_kind(argument, function),
        source=ast.unparse(argument),
    )
