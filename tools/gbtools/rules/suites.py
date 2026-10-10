# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de las carpetas y los ficheros de pruebas (RF-001-06; convergencia de la spec
001). Una prueba que no se carga no se ejecuta, y la comprobación completa daría verde
sin avisar.

- TST-01 (T34): desde Python 3.11, ``unittest discover`` no entra en una carpeta sin
  ``__init__.py`` (ni en nada de lo que cuelga de ella). Toda carpeta de ``tests/`` que
  contiene ficheros ``.py``, directamente o en alguna subcarpeta, debe tenerlo; también
  ``tests/``.
- TST-02 (T43): en una carpeta de pruebas, todo ``.py`` salvo ``__init__.py`` casa con
  el patrón con que la carga su paso (``SUITE_PATTERNS``: ``test*.py`` en
  ``tests/unit``, ``tests/arnes`` (``--completo``; spec 001 0.6), ``tests/referencia`` y
  ``tests/banco``; ``test_*.py`` en
  ``tests/blender`` y ``tests/rendimiento``; ``perf_*.py`` en
  ``tests/rendimiento/blender``) y es un nombre de módulo válido; y no hay ``.py`` en
  ``tests/`` fuera de esas carpetas, de ``tests/support/`` (las ayudas) y de
  ``tests/data/`` (los datos sintéticos), porque ningún paso los carga.
- TST-03 (T44): en una subclase de ``unittest.TestCase`` (directa, de otra clase del
  mismo fichero que lo es o de una base cuyo nombre termina en «TestCase»), un método
  cuyo docstring cita un ``RF-NNN-nn`` o un ``RNF-NNN-nn`` (es una prueba: las pruebas
  citan su requisito, ``geoblender/AGENTS.md``) y cuyo nombre no empieza por «test»
  (``unittest`` no lo ejecuta nunca). Las preparaciones (``setUp``, ``setUpClass``…) se
  ejecutan y no cuentan. Un fichero que no se puede analizar lo señala AST-01.
- TST-04 (T46): una omisión incondicional: ``@unittest.skip`` (con o sin motivo, sobre
  una prueba o una clase), ``skipIf``/``skipUnless`` con una condición constante que
  omite, y ``self.skipTest(…)`` o ``raise unittest.SkipTest(…)`` directamente en el
  cuerpo de una función o del módulo (no dentro de un ``if``, un ``try``…). La prueba no
  se ejecuta nunca, y con un motivo «[ENTORNO]» inventado ``tools/check.py`` la contaría
  como una omisión por un recurso (código 0). Lo que depende de un recurso, con
  ``tests.support.resources.requires``. Una condición «constante» es la que no tiene
  nombres, atributos ni llamadas (``1 == 1``, ``not False``), salvo nombres del módulo
  asignados una sola vez a una constante (``SIEMPRE = True``): se evalúa, y si no se
  puede (``2 ** 10 ** 10``, ``1 / 0``) cuenta como que omite. Y una omisión dentro de un
  ``if`` o un ``while`` constante que se cumple (o del ``else`` de un ``if`` que no), de
  un ``with`` o del cuerpo o el ``finally`` de un ``try`` se ejecuta siempre, igual que
  una suelta (hallazgo F1 de la ronda 3, T48). Límite declarado: un nombre que se
  asigna más de una vez, o uno importado, depende de algo y no se evalúa; lo que se
  omite por un recurso que no está en la lista cerrada lo para ``tools/check.py``
  (T47). Límite declarado (hallazgo F5 de la ronda 4; T63): una omisión por un recurso
  válido de la lista con una condición que no comprueba ese recurso
  (``skipUnless(os.environ.get("X"), skip_reason("symlink", …))``) depende de algo y no
  es incondicional: no la ve esta regla ni ``tools/check.py``; la revisa la persona en la
  revisión del código (la condición debe ser la comprobación del recurso:
  ``tests.support.resources.requires``).
- TST-05 (T53): en una clase de pruebas, dos métodos con el mismo nombre (salvo el
  ``setter`` de una propiedad y las sobrecargas de ``typing.overload``), y en el módulo,
  dos clases con el mismo nombre de las que una es de pruebas: el segundo sustituye al
  primero en silencio y ``unittest`` no lo ejecuta nunca (un ``test_falla`` rojo tapado
  por otro ``test_falla`` daba verde).
- TST-06 (T54): una prueba que devuelve algo en lugar de ejecutar su cuerpo: ``async def
  test…`` en una clase sin ``IsolatedAsyncioTestCase`` en su cadena de bases (del mismo
  módulo), y ``def test…`` con ``yield`` (no en una función de dentro). Python 3.13 solo
  da un ``DeprecationWarning``; ``tools/check.py`` y el lanzador lo convierten además en
  error. Límite declarado: una base asíncrona propia definida en otro módulo no se ve.
- TST-07 (T59): ``expectedFailure`` de ``unittest`` en ``tests/``: como decorador (de una
  prueba o de una clase), llamado, importado (con o sin ``as``) o por su nombre, y la
  marca que pone (``__unittest_expecting_failure__``, también con ``getattr`` o
  ``setattr``). Una prueba roja así marcada da «OK (expected failures=n)» y código 0;
  ``tools/check.py``, el lanzador y el banco tampoco la aceptan como verde. Un error
  esperado se prueba con ``assertRaises``.
- TST-08 (T60): en un fichero de una carpeta de pruebas (``SUITE_PATTERNS``), una prueba
  fuera de un ``TestCase``: una función del módulo ``def test…`` (estilo pytest, también
  ``async`` o dentro de un ``if``/``try`` del módulo) y un método ``test…`` de una clase
  del módulo que no es de pruebas: sin bases, de ``object`` o de otra clase de
  ``builtins`` (``Exception``…), o de otra clase del módulo así. ``unittest`` solo
  ejecuta los métodos «test…» de las clases que heredan de ``TestCase``; las demás no
  se ejecutan nunca. No cuentan una clase de la que hereda una de pruebas del módulo (una
  mezcla) ni lo local de una función. Límite declarado: una clase cuya base llega de
  otro módulo y no se llama «…TestCase» no se juzga (puede ser un ``TestCase``).
"""

from __future__ import annotations

import ast
import builtins
import fnmatch
import re
from collections.abc import Iterator
from pathlib import Path

from ..discovery import UNITTEST_PATTERN
from ..findings import Finding
from ..repo import iter_py_files, relpath
from . import pyast

RULE = "TST-01"
RULE_NAMES = "TST-02"
RULE_METHODS = "TST-03"
RULE_SKIPS = "TST-04"
RULE_DUPLICATES = "TST-05"
RULE_NOT_RUN = "TST-06"
RULE_EXPECTED = "TST-07"
RULE_OUTSIDE = "TST-08"
TESTS_FOLDER = "tests"
INIT = "__init__.py"
MESSAGE = (
    "la carpeta tiene ficheros .py (o subcarpetas con ellos) y le falta «__init__.py»: "
    "unittest discover no entra en ella y sus pruebas no se ejecutarían sin avisar "
    "(falso verde); cree un «__init__.py» con la cabecera SPDX"
)

# Carpeta de pruebas → patrón de los ficheros que carga su paso (``tools/check.py``, el
# lanzador de Blender y ``tools/bench_silvestre.py``). La más concreta, primero.
SUITE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("tests/rendimiento/blender/", "perf_*.py"),
    ("tests/rendimiento/", "test_*.py"),
    ("tests/blender/", "test_*.py"),
    ("tests/unit/", UNITTEST_PATTERN),
    ("tests/arnes/", UNITTEST_PATTERN),
    ("tests/referencia/", UNITTEST_PATTERN),
    ("tests/banco/", UNITTEST_PATTERN),
)
# Carpetas de ``tests/`` con ``.py`` que no son pruebas.
NOT_SUITES: tuple[str, ...] = ("tests/support/", "tests/data/")
MOVE_HINT = "si es una ayuda de las pruebas, llévela a tests/support/"

TEST_PREFIX = "test"  # el ``testMethodPrefix`` de unittest
REQUIREMENT = re.compile(r"\bRN?F-\d{3}-\d{2}\b")
TESTCASE_SUFFIX = "TestCase"  # TestCase, IsolatedAsyncioTestCase y las bases propias
FIXTURES = frozenset(
    {"setUp", "tearDown", "setUpClass", "tearDownClass", "asyncSetUp", "asyncTearDown"}
)
SKIP_MESSAGE = (
    "omisión incondicional ({what}): la prueba no se ejecuta nunca y, con un motivo "
    "«[ENTORNO]», tools/check.py la contaría como una omisión por un recurso (falso "
    "verde); si depende de un recurso, use tests.support.resources.requires; si no, "
    "quite la omisión y arregle la prueba"
)


def _folders(paths: list[str]) -> list[Finding]:
    """TST-01: carpetas de ``tests/`` sin ``__init__.py`` por las que discover pasa."""
    needed: set[str] = set()
    present: set[str] = set()
    for rel in paths:
        folder, _sep, name = rel.rpartition("/")
        if name == INIT:
            present.add(folder)
        parts = folder.split("/")
        needed.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    return [Finding(f"{folder}/", 0, RULE, MESSAGE) for folder in sorted(needed - present)]


def _name_problem(rel: str) -> str | None:
    """TST-02: por qué ningún paso cargaría el fichero ``rel`` (``None`` si lo carga)."""
    name = rel.rpartition("/")[2]
    if name == INIT or rel.startswith(NOT_SUITES):
        return None
    for folder, pattern in SUITE_PATTERNS:
        if not rel.startswith(folder):
            continue
        if not fnmatch.fnmatchcase(name, pattern):
            return (
                f"«{name}» no casa con «{pattern}», el patrón con que se cargan las "
                f"pruebas de «{folder}»: unittest no lo carga y sus pruebas no se "
                f"ejecutarían nunca (falso verde); renómbrelo o, {MOVE_HINT}"
            )
        if not name.removesuffix(".py").isidentifier():
            return (
                f"«{name}» no es un nombre de módulo válido: unittest discover lo salta "
                "sin avisar (falso verde); use solo letras, números y «_»"
            )
        return None
    return (
        "está en tests/ fuera de las carpetas de pruebas ("
        + ", ".join(f"«{folder}»" for folder, _pattern in SUITE_PATTERNS)
        + f"): ningún paso lo carga (falso verde); muévalo a la suya o, {MOVE_HINT}"
    )


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _test_classes(tree: ast.Module) -> list[ast.ClassDef]:
    """Las subclases de ``TestCase`` del módulo: con una base cuyo nombre termina en
    «TestCase» o que es otra clase del módulo que lo es (en cualquier orden)."""
    pending = [
        node for node in pyast.iter_statements(tree) if isinstance(node, ast.ClassDef)
    ]
    known: set[str] = set()
    found: list[ast.ClassDef] = []
    changed = True
    while changed:
        changed = False
        for node in list(pending):
            bases = [name for name in map(_base_name, node.bases) if name is not None]
            if any(name.endswith(TESTCASE_SUFFIX) or name in known for name in bases):
                known.add(node.name)
                found.append(node)
                pending.remove(node)
                changed = True
    return found


def _hidden_tests(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-03: métodos de un ``TestCase`` que citan un requisito y que ``unittest`` no
    ejecuta porque su nombre no empieza por «test»."""
    findings: list[Finding] = []
    for node in _test_classes(tree):
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if item.name.startswith(TEST_PREFIX) or item.name in FIXTURES:
                continue
            cited = REQUIREMENT.search(ast.get_docstring(item) or "")
            if cited is None:
                continue
            findings.append(
                Finding(
                    rel,
                    item.lineno,
                    RULE_METHODS,
                    f"el método «{item.name}» de «{node.name}» cita {cited.group()} en "
                    f"su docstring, así que es una prueba, pero no empieza por "
                    f"«{TEST_PREFIX}»: unittest no lo ejecuta nunca (falso verde); "
                    f"renómbrelo «{TEST_PREFIX}_…» o, si es una ayuda, quite el "
                    "requisito de su docstring",
                )
            )
    return findings


class _Unknown(Exception):
    """La condición depende de algo (un nombre, un atributo, una llamada…)."""


# Lo que hace que una condición dependa de algo que no se ve en el fichero.
_DEPENDENT = (
    ast.Name,
    ast.Attribute,
    ast.Call,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.NamedExpr,
    ast.Lambda,
    ast.comprehension,
)
# Operaciones que, con constantes, pueden dar un valor enorme (2 ** 10 ** 10): no se
# evalúan; la condición sigue siendo constante, pero de valor desconocido.
_COSTLY = (ast.Pow, ast.LShift, ast.Mult, ast.MatMult)


# Los nodos que dan nombre a algo en el módulo (_module_constants).
_NAMING_NODES = (
    ast.Name,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """Nombres del módulo asignados una sola vez en todo el fichero, en su cuerpo, a
    una expresión constante (``SIEMPRE = True``): una condición que los usa no depende
    de nada. Un nombre que se asigna más veces (o se importa, o es una función) no
    cuenta."""
    stores: dict[str, int] = {}
    for node in pyast.nodes_of(tree, _NAMING_NODES):
        names: list[str] = []
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names = [node.id]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names = [node.name]
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names = [(alias.asname or alias.name).partition(".")[0] for alias in node.names]
        elif isinstance(node, ast.Global | ast.Nonlocal):
            names = list(node.names)
        for name in names:
            stores[name] = stores.get(name, 0) + 1
    constants: dict[str, object] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or stores.get(target.id) != 1:
            continue
        try:
            constants[target.id] = _evaluate(statement.value, constants)
        except _Unknown:
            continue
    return constants


def _evaluate(expr: ast.expr, constants: dict[str, object]) -> object:
    """Valor de ``expr`` si no depende de nada (solo constantes y ``constants``).

    Lanza :class:`_Unknown` si depende de algo, y devuelve ``Ellipsis`` (``...``) si es
    constante pero no se evalúa (una operación que puede dar un valor enorme o que
    falla, como ``1 / 0``)."""
    costly = False
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and node.id in constants:
            continue
        if isinstance(node, _DEPENDENT):
            raise _Unknown
        if isinstance(node, ast.BinOp) and isinstance(node.op, _COSTLY):
            costly = True
    if costly:
        return Ellipsis
    try:
        code = compile(ast.Expression(expr), "<condición>", "eval")
        return eval(code, {"__builtins__": {}}, dict(constants))  # noqa: S307
    except Exception:  # noqa: BLE001 - constante, pero no se puede evaluar
        return Ellipsis


def _always(expr: ast.expr, constants: dict[str, object], wanted: bool) -> bool:
    """Verdadero si la condición ``expr`` no depende de nada y su valor de verdad es
    ``wanted`` (o no se puede evaluar: una omisión con una condición que no depende de
    nada nunca es legítima)."""
    try:
        value = _evaluate(expr, constants)
    except _Unknown:
        return False
    return value is Ellipsis or bool(value) == wanted


def _skip_decorator(node: ast.expr, constants: dict[str, object]) -> str | None:
    """Cómo omite siempre el decorador ``node`` (``None`` si no omite siempre)."""
    func = node.func if isinstance(node, ast.Call) else node
    name = _base_name(func)
    if name == "skip":
        return "@skip"
    if isinstance(node, ast.Call) and name in ("skipIf", "skipUnless") and node.args:
        condition = node.args[0]
        if _always(condition, constants, name == "skipIf"):
            return f"@{name}({ast.unparse(condition)}, …)"
    return None


def _skip_statement(node: ast.stmt) -> str | None:
    """Si la sentencia ``node`` omite (``self.skipTest(…)``, ``raise SkipTest(…)``)."""
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _base_name(node.value.func) == "skipTest":
            return "skipTest(…)"
    if isinstance(node, ast.Raise) and node.exc is not None:
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if _base_name(exc) == "SkipTest":
            return "raise SkipTest(…)"
    return None


def _always_run(
    body: list[ast.stmt], constants: dict[str, object], where: tuple[str, ...] = ()
) -> list[tuple[ast.stmt, tuple[str, ...]]]:
    """Las sentencias de ``body`` que se ejecutan siempre que se ejecuta ``body``, con
    los bloques por los que se llega a ellas: las del propio cuerpo y, dentro, las de
    un ``if`` (o un ``while``) cuya condición constante se cumple (o del ``else`` de un
    ``if`` que no se cumple), de un ``with`` y del cuerpo y el ``finally`` de un
    ``try`` (no sus ``except``)."""
    found: list[tuple[ast.stmt, tuple[str, ...]]] = []
    for statement in body:
        found.append((statement, where))
        inner: list[tuple[list[ast.stmt], str]] = []
        if isinstance(statement, ast.If | ast.While):
            keyword = "if" if isinstance(statement, ast.If) else "while"
            head = f"{keyword} {ast.unparse(statement.test)}"
            if _always(statement.test, constants, True):
                inner.append((statement.body, head))
            elif isinstance(statement, ast.If) and _always(
                statement.test, constants, False
            ):
                inner.append((statement.orelse, f"else de «{head}»"))
        elif isinstance(statement, ast.With | ast.AsyncWith):
            inner.append((statement.body, "with"))
        elif isinstance(statement, ast.Try | ast.TryStar):
            inner += [(statement.body, "try"), (statement.finalbody, "finally")]
        for block, label in inner:
            found += _always_run(block, constants, (*where, label))
    return found


def _unconditional_skips(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-04: omisiones que no dependen de nada: decoradores que omiten siempre y
    omisiones que se ejecutan siempre en el cuerpo de una función o del módulo."""
    findings: list[Finding] = []
    constants = _module_constants(tree)

    def add(line: int, what: str) -> None:
        findings.append(Finding(rel, line, RULE_SKIPS, SKIP_MESSAGE.format(what=what)))

    bodies: list[list[ast.stmt]] = [tree.body]
    for node in pyast.iter_statements(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for decorator in node.decorator_list:
                what = _skip_decorator(decorator, constants)
                if what is not None:
                    add(decorator.lineno, what)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            bodies.append(node.body)
    for body in bodies:
        for statement, where in _always_run(body, constants):
            what = _skip_statement(statement)
            if what is not None:
                blocks = ", ".join(f"«{label}»" for label in where)
                add(statement.lineno, f"{what} dentro de {blocks}" if where else what)
    return findings


_ACCESSORS = frozenset({"setter", "getter", "deleter"})


def _redefines_on_purpose(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Una redefinición legítima: el ``setter`` de una propiedad o una sobrecarga."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Attribute) and decorator.attr in _ACCESSORS:
            return True
        if _base_name(decorator) == "overload":
            return True
    return False


def _duplicated_tests(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-05: en una clase de pruebas, dos métodos con el mismo nombre; y en el módulo,
    dos clases con el mismo nombre de las que una es de pruebas. El segundo sustituye al
    primero en silencio: ``unittest`` no lo ejecuta nunca."""
    findings: list[Finding] = []
    classes = _test_classes(tree)
    for node in classes:
        seen: dict[str, int] = {}
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            overloads = any(_base_name(d) == "overload" for d in item.decorator_list)
            if item.name in seen and not _redefines_on_purpose(item):
                findings.append(
                    Finding(
                        rel,
                        item.lineno,
                        RULE_DUPLICATES,
                        f"el método «{item.name}» de «{node.name}» ya está definido en la "
                        f"línea {seen[item.name]}: este lo sustituye en silencio y el "
                        "primero no se ejecuta nunca (falso verde); renombre uno de los dos",
                    )
                )
            if not overloads:
                seen[item.name] = item.lineno
    names = {node.name for node in classes}
    seen_classes: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in names:
            continue
        if node.name in seen_classes:
            findings.append(
                Finding(
                    rel,
                    node.lineno,
                    RULE_DUPLICATES,
                    f"la clase «{node.name}» ya está definida en la línea "
                    f"{seen_classes[node.name]}: esta la sustituye en silencio y las "
                    "pruebas de la primera no se ejecutan nunca (falso verde); renombre "
                    "una de las dos",
                )
            )
        else:
            seen_classes[node.name] = node.lineno
    return findings


ASYNC_CASE = "IsolatedAsyncioTestCase"


def _async_classes(tree: ast.Module, classes: list[ast.ClassDef]) -> set[str]:
    """Nombres de las clases de pruebas del módulo que esperan sus corrutinas: las que
    tienen ``IsolatedAsyncioTestCase`` en su cadena de bases (directa o a través de otra
    clase del módulo)."""
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in found:
                continue
            bases = {name for name in map(_base_name, node.bases) if name is not None}
            if ASYNC_CASE in bases or bases & found:
                found.add(node.name)
                changed = True
    return found


def _yields(function: ast.FunctionDef) -> bool:
    """Si el cuerpo de ``function`` tiene ``yield`` (no en una función, una lambda o una
    clase de dentro, que son otro ámbito)."""
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef
        ):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def _tests_not_run(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-06: pruebas que devuelven algo en lugar de ejecutar su cuerpo: ``async def
    test…`` en una clase que no espera corrutinas, y ``def test…`` con ``yield``."""
    findings: list[Finding] = []
    classes = _test_classes(tree)
    waiting = _async_classes(tree, classes)
    # Sin ningún «yield» en el fichero, ninguna prueba es generadora (spec 006, T47).
    generators = bool(pyast.nodes_of(tree, (ast.Yield, ast.YieldFrom)))
    for node in classes:
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not item.name.startswith(TEST_PREFIX):
                continue
            if isinstance(item, ast.AsyncFunctionDef) and node.name not in waiting:
                why = (
                    f"es «async def» y «{node.name}» no hereda de {ASYNC_CASE}: unittest "
                    "crea la corrutina y no la espera"
                )
            elif isinstance(item, ast.FunctionDef) and generators and _yields(item):
                why = "tiene «yield»: unittest crea el generador y no lo recorre"
            else:
                continue
            findings.append(
                Finding(
                    rel,
                    item.lineno,
                    RULE_NOT_RUN,
                    f"la prueba «{item.name}» de «{node.name}» {why}, así que su cuerpo no "
                    "se ejecuta y pasa siempre (Python 3.13 solo da un DeprecationWarning; "
                    f"falso verde); use {ASYNC_CASE} o quite el «yield»",
                )
            )
    return findings


# ``unittest.expectedFailure`` y el atributo que pone en la prueba o la clase.
EXPECTED_NAMES = frozenset({"expectedFailure", "__unittest_expecting_failure__"})
_ATTRIBUTE_CALLS = frozenset({"getattr", "setattr", "hasattr", "delattr"})
_EXPECTED_NODES = (ast.ImportFrom, ast.Attribute, ast.Name, ast.Call)


def _expected_failures(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-07: ``expectedFailure`` (decorador, llamada, importación o nombre) y la marca
    ``__unittest_expecting_failure__``; una sola vez por línea."""
    lines: dict[int, str] = {}
    for node in pyast.nodes_of(tree, _EXPECTED_NODES):
        what: str | None = None
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names if alias.name in EXPECTED_NAMES]
            what = f"importa «{names[0]}»" if names else None
        elif isinstance(node, ast.Attribute) and node.attr in EXPECTED_NAMES:
            what = f"«{ast.unparse(node)}»"
        elif isinstance(node, ast.Name) and node.id in EXPECTED_NAMES:
            what = f"«{node.id}»"
        elif (
            isinstance(node, ast.Call)
            and _base_name(node.func) in _ATTRIBUTE_CALLS
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in EXPECTED_NAMES
        ):
            what = f"«{_base_name(node.func)}(…, {node.args[1].value!r})»"
        if what is not None:
            lines.setdefault(node.lineno, what)
    return [
        Finding(
            rel,
            line,
            RULE_EXPECTED,
            f"{what}: una prueba roja marcada con expectedFailure da «OK (expected "
            "failures=n)» y código 0 en unittest (falso verde); quite expectedFailure y "
            "arregle la prueba, o pruebe el error esperado con assertRaises",
        )
        for line, what in sorted(lines.items())
    ]


_BUILTIN_NAMES = frozenset(dir(builtins))


def _module_scope(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Las sentencias que definen nombres del módulo: las de ``body`` y las de dentro de
    un ``if``, ``try``, ``with``, ``for`` o ``while`` del módulo (no las de una función
    o una clase, que son otro ámbito)."""
    for statement in body:
        yield statement
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _module_scope(getattr(statement, field, None) or [])
        for handler in getattr(statement, "handlers", None) or []:
            yield from _module_scope(handler.body)


def _plain_classes(classes: list[ast.ClassDef], tests: set[str]) -> dict[str, ast.ClassDef]:
    """Las clases del módulo que seguro no son de pruebas: todas sus bases son de
    ``builtins`` (o no tienen) o son otras clases del módulo así. Una base que llega de
    otro módulo (o por atributo) puede ser un ``TestCase``: esa clase no se juzga."""
    local = {node.name for node in classes}
    plain: dict[str, ast.ClassDef] = {}
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in plain or node.name in tests:
                continue
            if all(
                isinstance(base, ast.Name)
                and (base.id in plain or (base.id in _BUILTIN_NAMES and base.id not in local))
                for base in node.bases
            ):
                plain[node.name] = node
                changed = True
    return plain


def _mixins(test_classes: list[ast.ClassDef], plain: dict[str, ast.ClassDef]) -> set[str]:
    """Las clases de ``plain`` de las que hereda (directa o indirectamente) una clase de
    pruebas del módulo: sus métodos «test…» se ejecutan en ella."""
    found: set[str] = set()
    pending = [base for node in test_classes for base in node.bases]
    while pending:
        base = pending.pop()
        if isinstance(base, ast.Name) and base.id in plain and base.id not in found:
            found.add(base.id)
            pending.extend(plain[base.id].bases)
    return found


def _outside_testcase(rel: str, tree: ast.Module) -> list[Finding]:
    """TST-08: funciones del módulo ``def test…`` y métodos ``test…`` de clases del
    módulo que no son de pruebas (ni mezclas de una que lo es)."""
    findings: list[Finding] = []
    scope = list(_module_scope(tree.body))
    test_classes = _test_classes(tree)
    classes = [node for node in scope if isinstance(node, ast.ClassDef)]
    plain = _plain_classes(classes, {node.name for node in test_classes})
    mixins = _mixins(test_classes, plain)
    for node in scope:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith(TEST_PREFIX):
                findings.append(
                    Finding(
                        rel,
                        node.lineno,
                        RULE_OUTSIDE,
                        f"la función «{node.name}» es una prueba de estilo pytest: unittest "
                        "solo ejecuta los métodos «test…» de las clases que heredan de "
                        "unittest.TestCase y no la ejecuta nunca (falso verde); llévela a "
                        f"una clase de pruebas o, si es una ayuda, quítele el «{TEST_PREFIX}» "
                        "del principio",
                    )
                )
        elif isinstance(node, ast.ClassDef) and node.name in plain:
            if node.name in mixins:
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not item.name.startswith(TEST_PREFIX):
                    continue
                findings.append(
                    Finding(
                        rel,
                        item.lineno,
                        RULE_OUTSIDE,
                        f"el método «{item.name}» está en «{node.name}», que no hereda de "
                        "unittest.TestCase: unittest no lo ejecuta nunca (falso verde); "
                        f"haga que «{node.name}» herede de unittest.TestCase o, si es una "
                        f"ayuda, quítele el «{TEST_PREFIX}» del principio",
                    )
                )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de TST-01 a TST-08 en ``tests/``."""
    files = list(iter_py_files(root, TESTS_FOLDER))
    paths = [relpath(root, path) for path in files]
    findings = _folders(paths)
    for path, rel in zip(files, paths, strict=True):
        problem = _name_problem(rel)
        if problem is not None:
            findings.append(Finding(rel, 0, RULE_NAMES, problem))
        if path.is_symlink():
            continue  # lo señala TXT-03
        try:
            tree = pyast.parse_file(path)
        except (SyntaxError, ValueError):
            continue  # lo señala AST-01
        findings.extend(_hidden_tests(rel, tree))
        findings.extend(_unconditional_skips(rel, tree))
        findings.extend(_duplicated_tests(rel, tree))
        findings.extend(_tests_not_run(rel, tree))
        findings.extend(_expected_failures(rel, tree))
        if rel.startswith(tuple(folder for folder, _pattern in SUITE_PATTERNS)):
            findings.extend(_outside_testcase(rel, tree))
    return sorted(findings)
