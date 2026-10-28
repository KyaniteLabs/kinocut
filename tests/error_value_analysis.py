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
        "contract_error",
        "voice_error",
        "bounded_voice_error",
        "mix_error",
    }
)

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
    "CodecError": frozenset({1}),
    "HyperframesProjectError": frozenset({1}),
    "ProcessingError": frozenset({1, 2}),
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
    }
)

#: The helpers that make a value safe to name. A call to one of them is the
#: trust boundary: they name a value by its type and never copy it.
SANITIZERS = frozenset({"rejected_value", "exception_kind", "invalid_parameter"})

#: A declared type that cannot hold a string.
NUMERIC_TYPES = frozenset({"int", "float", "bool", "None"})
#: A declared type that can hold a string.
STRING_TYPES = frozenset({"str", "Path", "Any", "object", "bytes"})
#: A numeric format spec proves the value is a number: formatting a string
#: with ``:.0f`` raises.
NUMERIC_SPECS = frozenset("fFeEgGdiuXobn%")
#: Constructors whose result is a number whatever they were given.
NUMERIC_CALLS = frozenset({"float", "int", "bool", "round", "abs", "len", "sum", "min", "max", "sorted"})
#: Calls whose result carries a tainted argument into the result.
CARRYING_CALLS = frozenset({"str", "repr", "format", "join", "Path", "PurePath"})

#: Attributes that hold a number however the object was obtained. A number
#: is safe to repeat, so these never taint.
NUMERIC_ATTRIBUTES = frozenset(
    {
        "width",
        "height",
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


def holds_string(text: str) -> bool:
    """True when the declared type can carry a caller-controlled string.

    ``int | None`` cannot. ``int | str`` can — the string arm is the leak.
    An unannotated parameter can, so it is treated as string-capable.

    A container counts: a ``dict[str, str]`` carries caller-chosen keys
    and values, and a message that repeats one repeats the caller's
    input.
    """
    if text == "?":
        return True
    parts = [part.strip() for part in text.split("|")]
    if all(part in NUMERIC_TYPES for part in parts):
        return False
    return any(part in STRING_TYPES or part == "?" for part in parts)


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


def label_parameters() -> set[tuple[str, str]]:
    """Parameters every call site fills with a literal.

    Those are internal labels — ``name="width"``, ``label="destination"`` —
    chosen by the shipped code, not by the caller. A parameter with no call
    site in the package is not a label: the caller may still supply it.
    """
    by_name, _ = package_functions()
    labels: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for package in PACKAGES:
        for path in sorted(package.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover - defensive
                continue
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                name = callee_name(call)
                if name is None:
                    continue
                for candidate in by_name.get(name, ()):
                    names = list(candidate.params)
                    for position, argument in enumerate(call.args):
                        if position >= len(names):
                            break
                        key = (name, names[position])
                        seen.add(key)
                        if not isinstance(argument, ast.Constant):
                            labels.discard(key)
                    for keyword in call.keywords:
                        if keyword.arg is None or keyword.arg not in names:
                            continue
                        key = (name, keyword.arg)
                        seen.add(key)
                        if not isinstance(keyword.value, ast.Constant):
                            labels.discard(key)
    return labels


def _is_tainted_expr(node: ast.AST, function: Function) -> bool:
    """True when the expression carries a caller-controlled string.

    The walk is recursive rather than flat so that a numeric attribute
    stops the descent: ``img.width`` is a number even when ``img`` came
    from a caller-controlled path, and ``type(x).__name__`` is the name of
    a class rather than a value.

    A call to one of the sanitizers is the trust boundary: those helpers
    name a value by its type and never copy it, so what they return is
    safe by construction.
    """
    tainted = function.tainted
    if isinstance(node, ast.Call):
        name = callee_name(node)
        if name in SANITIZERS:
            return False
        if name in NUMERIC_CALLS:
            return False
        if name in CARRYING_CALLS:
            return any(_is_tainted_expr(argument, function) for argument in node.args)
        # A value pulled out of a caller-supplied container is caller data:
        # ``op.get("op")`` returns the string the caller submitted.
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop"}:
            return _is_tainted_expr(node.func.value, function)
        return False
    if isinstance(node, ast.Name):
        if node.id in function.numeric:
            # The code has established this is a number, and a number may
            # be repeated in a message.
            return False
        return node.id in tainted
    if isinstance(node, ast.Attribute):
        if node.attr == "__name__":
            return False
        if node.attr in NUMERIC_ATTRIBUTES:
            return False
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
    if isinstance(node, ast.Dict):
        return any(_is_tainted_expr(key, function) for key in node.keys if key is not None) or any(
            _is_tainted_expr(value, function) for value in node.values
        )
    return False


def _local_taint(function: Function) -> bool:
    """Taint the locals of one function from what it already knows."""
    changed = False
    for child in ast.walk(function.node):
        if not isinstance(child, ast.Assign):
            continue
        if not _is_tainted_expr(child.value, function):
            continue
        targets: list[ast.expr] = []
        for target in child.targets:
            if isinstance(target, ast.Name):
                targets.append(target)
            elif isinstance(target, ast.Tuple | ast.List):
                targets.extend(element for element in target.elts if isinstance(element, ast.Name))
        for target in targets:
            assert isinstance(target, ast.Name)
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


def _propagate(function: Function, by_name: dict[str, list[Function]]) -> bool:
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
                declared = candidate.annotations.get(parameter, "?")
                if not holds_string(declared) and not holds_container(declared):
                    continue
                candidate.tainted.add(parameter)
                changed = True
            for keyword in call.keywords:
                if keyword.arg is None or keyword.arg not in candidate.params:
                    continue
                if not _is_tainted_expr(keyword.value, function):
                    continue
                if keyword.arg in candidate.tainted:
                    continue
                declared = candidate.annotations.get(keyword.arg, "?")
                if not holds_string(declared) and not holds_container(declared):
                    continue
                candidate.tainted.add(keyword.arg)
                changed = True
    return changed


def tainted_functions(labels: set[tuple[str, str]]) -> list[Function]:
    """Every function that holds caller-controlled data."""
    by_name, all_functions = package_functions()
    for function in all_functions:
        function.tainted.update(function.aliases)
        if not function.handler:
            continue
        for parameter, declared in function.annotations.items():
            if not holds_string(declared) and not holds_container(declared):
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
            if _propagate(function, by_name):
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


def find_leaks() -> list[Finding]:
    """Every interpolation of a caller-controlled string into an error."""
    labels = label_parameters()
    findings: list[Finding] = []
    for function in tainted_functions(labels):
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
