# SPDX-License-Identifier: GPL-3.0-or-later
"""Análisis de los ``.py`` con ``ast`` para las reglas (plan 001 §5.4.2).

- :func:`collect_imports` recorre todo el árbol (funciones, clases y bloques
  ``if TYPE_CHECKING:`` incluidos) y devuelve un :class:`ImportRef` por nombre
  importado, con su contexto. Los relativos se resuelven a un nombre absoluto dentro
  de su paquete (``core/a.py`` con ``from ..gis import x`` → ``gis.x``); uno que se
  sale del paquete queda marcado (``escapes``). ``importlib.import_module("<literal>")``
  y ``__import__("<literal>")`` cuentan como import absoluto (``dynamic``); con un
  nombre que no es literal no se pueden resolver y no se informan (límite declarado).
- :func:`parse_modules` analiza los ``.py`` de una carpeta del repositorio
  comprobado. Un fichero que no se puede analizar no pasa en silencio: da un
  incumplimiento AST-01.

Para que las reglas recorran miles de ficheros en pocos segundos (RNF-001-02), los
árboles y los imports se guardan en caché por ruta, fecha y tamaño, y las expresiones
solo se recorren en busca de imports dinámicos si el texto del fichero menciona
``import_module`` o ``__import__``. Y cada fichero se analiza una sola vez por proceso
(spec 006, T47; RNF-001-01): su texto es el de ``repo.read_bytes``, que comparten todas
las reglas, y su árbol se recorre una sola vez (:func:`walk`, todos los nodos en el orden
de ``ast.walk``, e :func:`iter_statements`, las sentencias), y ese recorrido lo
comparten todas las reglas y las pruebas que las llaman. Los árboles no se modifican.
Al salir del proceso, las cachés se vacían (:func:`clear_caches`) antes de que Python lo
cierre: liberar al cerrar los árboles de todo el repositorio le cuesta unos 2 s.
"""

from __future__ import annotations

import ast
import atexit
import functools
import itertools
import weakref
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..findings import Finding
from ..repo import FileKey, clear_text_cache, file_key, iter_py_files, read_bytes, relpath

RULE_UNPARSABLE = "AST-01"
_DYNAMIC_HINTS: tuple[bytes, ...] = (b"import_module", b"__import__")
_CACHE_SIZE = 2048


@dataclass(frozen=True)
class ImportRef:
    """Un nombre importado por un módulo.

    ``target`` es el nombre absoluto (para un relativo, resuelto dentro de su paquete;
    con ``from x import y``, ``x.y``). ``top_function`` es la función de nivel de módulo
    que contiene el import, si la hay (no cuentan los métodos). ``base`` es, en un
    ``from x import y``, el módulo ``x`` resuelto (``""`` si es el paquete raíz); en
    ``import x`` y en los dinámicos, ``None``.
    """

    target: str
    line: int
    relative_level: int = 0
    in_function: bool = False
    in_type_checking: bool = False
    dynamic: bool = False
    top_function: str | None = None
    escapes: bool = False
    base: str | None = None

    @property
    def top(self) -> str:
        """Primer componente del nombre importado."""
        return self.target.partition(".")[0]


@dataclass(frozen=True)
class PyModule:
    """Un ``.py`` analizado: ruta, nombre de módulo dentro de su base y árbol.

    ``key`` (ruta, fecha y tamaño) identifica el contenido en las cachés;
    ``dynamic_hint`` dice si el texto menciona ``import_module`` o ``__import__``.
    """

    path: Path
    rel: str
    name: str
    is_package: bool
    tree: ast.Module
    key: tuple[str, int, int] = ("", 0, 0)
    dynamic_hint: bool = True


def module_name(rel_to_base: str) -> tuple[str, bool]:
    """``("core.a", False)`` para ``core/a.py``; ``("core", True)`` para
    ``core/__init__.py``."""
    parts = rel_to_base.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


# En el orden de los campos de ast (Try: body, handlers, orelse, finalbody).
_STATEMENT_FIELDS = ("body", "handlers", "orelse", "finalbody", "cases")


class _Collector(ast.NodeVisitor):
    """Recolector de imports. Con ``scan_calls`` falso solo baja por las sentencias
    (los imports estáticos siempre son sentencias), que es mucho más rápido."""

    def __init__(self, module: str, is_package: bool, scan_calls: bool) -> None:
        parts = module.split(".") if module else []
        self.package_parts = parts if is_package else parts[:-1]
        self.scan_calls = scan_calls
        self.refs: list[ImportRef] = []
        self.function_depth = 0
        self.class_depth = 0
        self.type_checking = 0
        self.top_function: str | None = None
        self.importlib_names = {"importlib"}
        self.import_module_names: set[str] = set()

    def generic_visit(self, node: ast.AST) -> None:
        if self.scan_calls:
            super().generic_visit(node)
            return
        for field in _STATEMENT_FIELDS:
            children = getattr(node, field, None)
            if isinstance(children, list):
                for child in children:
                    self.visit(child)

    def _add(self, target: str, line: int, **extra: object) -> None:
        self.refs.append(
            ImportRef(
                target=target,
                line=line,
                in_function=self.function_depth > 0,
                in_type_checking=self.type_checking > 0,
                top_function=self.top_function,
                **extra,  # type: ignore[arg-type]
            )
        )

    def _function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ) -> None:
        outer = self.top_function
        if self.function_depth == 0 and self.class_depth == 0:
            self.top_function = getattr(node, "name", None)
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1
        self.top_function = outer

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def visit_If(self, node: ast.If) -> None:
        if not _is_type_checking(node.test):
            self.generic_visit(node)
            return
        if self.scan_calls:
            self.visit(node.test)
        self.type_checking += 1
        for statement in node.body:
            self.visit(statement)
        self.type_checking -= 1
        for statement in node.orelse:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "importlib" and alias.asname:
                self.importlib_names.add(alias.asname)
            self._add(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        level = node.level or 0
        module = node.module or ""
        escapes = False
        if level == 0:
            base = module
            if module == "importlib":
                self.import_module_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
        elif level - 1 > len(self.package_parts):
            escapes = True
            base = "." * level + module
        else:
            kept = self.package_parts[: len(self.package_parts) - (level - 1)]
            base = ".".join([*kept, *([module] if module else [])])
        for alias in node.names:
            if alias.name == "*":
                target = base
            elif escapes:
                target = base + ("." if module else "") + alias.name
            else:
                target = f"{base}.{alias.name}" if base else alias.name
            self._add(
                target,
                node.lineno,
                relative_level=level,
                escapes=escapes,
                base=None if escapes else base,
            )

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        dynamic = (
            isinstance(func, ast.Name)
            and (func.id == "__import__" or func.id in self.import_module_names)
        ) or (
            isinstance(func, ast.Attribute)
            and func.attr == "import_module"
            and isinstance(func.value, ast.Name)
            and func.value.id in self.importlib_names
        )
        if dynamic and node.args:
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value
                and not first.value.startswith(".")
            ):
                self._add(first.value, node.lineno, dynamic=True)
        self.generic_visit(node)


def collect_imports(
    tree: ast.Module, module: str, is_package: bool, scan_calls: bool = True
) -> list[ImportRef]:
    """Los imports de un módulo (``module``: nombre con puntos dentro de su base).

    Con ``scan_calls`` falso no busca imports dinámicos (no recorre expresiones).
    """
    collector = _Collector(module, is_package, scan_calls)
    collector.visit(tree)
    return collector.refs


@dataclass(frozen=True)
class _Walked:
    """El recorrido de un árbol (spec 006, T47): sus nodos sin el propio árbol (así la
    caché no lo retiene y la entrada desaparece con él), en el orden de ``ast.walk``, el
    tipo de cada uno y los tipos que aparecen."""

    rest: tuple[ast.AST, ...]
    kinds: tuple[type, ...]
    present: frozenset[type]


_WALKS: weakref.WeakKeyDictionary[ast.AST, _Walked] = weakref.WeakKeyDictionary()
_STATEMENTS: weakref.WeakKeyDictionary[ast.AST, tuple[ast.stmt, ...]] = (
    weakref.WeakKeyDictionary()
)


def _traverse(tree: ast.AST) -> list[ast.AST]:
    """Los nodos de ``tree`` en el orden exacto de ``ast.walk`` (en anchura: cada nodo,
    y después sus hijos campo a campo), sin sus generadores: la mitad de tiempo."""
    found: list[ast.AST] = [tree]
    append = found.append
    for node in found:  # la lista crece mientras se recorre: es la cola
        for name in node._fields:
            value = getattr(node, name, None)
            if isinstance(value, ast.AST):
                append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        append(item)
    return found


def _walked(tree: ast.AST) -> _Walked:
    found = _WALKS.get(tree)
    if found is None:
        rest = tuple(_traverse(tree)[1:])
        kinds = tuple(map(type, rest))
        found = _WALKS[tree] = _Walked(rest, kinds, frozenset(kinds))
    return found


def walk(tree: ast.AST) -> Iterator[ast.AST]:
    """Todos los nodos de ``tree``, en el orden de ``ast.walk`` (cada nodo antes que sus
    hijos). El árbol se recorre una sola vez y lo comparten todas las llamadas (spec 006,
    T47); no lo modifique."""
    return itertools.chain((tree,), _walked(tree).rest)


def nodes_of(
    tree: ast.AST, types: type[ast.AST] | tuple[type[ast.AST], ...]
) -> list[ast.AST]:
    """Los nodos de :func:`walk` que son de ``types`` (como ``isinstance``), en su orden:
    lo que una regla recorre sin mirar los demás nodos (spec 006, T47)."""
    walked = _walked(tree)
    found: list[ast.AST] = [tree] if isinstance(tree, types) else []
    chosen = frozenset(kind for kind in walked.present if issubclass(kind, types))
    if chosen:
        found.extend(itertools.compress(walked.rest, map(chosen.__contains__, walked.kinds)))
    return found


def _statements(tree: ast.AST) -> Iterator[ast.stmt]:
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.stmt):
            yield node
        for field in _STATEMENT_FIELDS:
            children = getattr(node, field, None)
            if isinstance(children, list):
                stack.extend(reversed(children))


def iter_statements(tree: ast.AST) -> Iterator[ast.stmt]:
    """Todas las sentencias del árbol, también dentro de funciones y clases, sin
    recorrer las expresiones. El árbol se recorre una sola vez y lo comparten todas las
    llamadas (spec 006, T47); no lo modifique."""
    rest = _STATEMENTS.get(tree)
    if rest is None:
        found = _statements(tree)
        if isinstance(tree, ast.stmt):
            next(found)  # el propio árbol
        rest = _STATEMENTS[tree] = tuple(found)
    if isinstance(tree, ast.stmt):
        return itertools.chain((tree,), rest)
    return iter(rest)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _parse_cached(path: str, mtime_ns: int, size: int) -> tuple[ast.Module, bool]:
    data = read_bytes(Path(path), (path, mtime_ns, size))
    hint = any(token in data for token in _DYNAMIC_HINTS)
    return ast.parse(data, filename=path), hint


def _key(path: Path) -> FileKey:
    return file_key(path)


def parse_file(path: Path) -> ast.Module:
    """Árbol de un ``.py``, con caché por ruta, fecha y tamaño (no lo modifique)."""
    return _parse_cached(*_key(path))[0]


def unparsable(rel: str, error: SyntaxError | ValueError) -> Finding:
    """Incumplimiento AST-01 de un fichero que no se puede analizar."""
    line = getattr(error, "lineno", None) or 0
    detail = getattr(error, "msg", None) or str(error)
    return Finding(
        rel,
        line,
        RULE_UNPARSABLE,
        f"no se puede analizar ({type(error).__name__}: {detail}): corríjalo; mientras "
        "tanto no se pueden comprobar en él las reglas de arquitectura",
    )


def parse_scopes(
    root: Path, scopes: Mapping[str, str]
) -> tuple[list[PyModule], list[Finding]]:
    """Analiza los ``.py`` de varias carpetas recorriendo el repositorio una vez.

    ``scopes`` va de la carpeta (``"geoblender"``, ``"tests"``…) a la base respecto a
    la que se calcula el nombre de cada módulo: con base ``"geoblender"``,
    ``geoblender/core/a.py`` es ``core.a``; con base ``""``, ``tests/unit/x.py`` es
    ``tests.unit.x``.
    """
    prefixes = [(top.strip("/") + "/", base.strip("/")) for top, base in scopes.items()]
    modules: list[PyModule] = []
    findings: list[Finding] = []
    for path in iter_py_files(root, *scopes):
        if path.is_symlink():
            continue  # lo señala TXT-03
        rel = relpath(root, path)
        base = next(base for top, base in prefixes if rel.startswith(top))
        name, is_package = module_name(rel.removeprefix(base + "/" if base else ""))
        try:
            key = _key(path)
            tree, hint = _parse_cached(*key)
        except (SyntaxError, ValueError) as exc:
            findings.append(unparsable(rel, exc))
            continue
        modules.append(PyModule(path, rel, name, is_package, tree, key, hint))
    return modules, findings


def parse_modules(
    root: Path, top: str, base: str | None = None
) -> tuple[list[PyModule], list[Finding]]:
    """Analiza los ``.py`` de ``root/top`` (nombres respecto a ``base``, por defecto
    ``top``); ver :func:`parse_scopes`."""
    return parse_scopes(root, {top: top if base is None else base})


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _imports_cached(
    key: tuple[str, int, int], name: str, is_package: bool, hint: bool
) -> tuple[ImportRef, ...]:
    tree = _parse_cached(*key)[0]
    return tuple(collect_imports(tree, name, is_package, scan_calls=hint))


def iter_imports(module: PyModule) -> Iterator[ImportRef]:
    """Los imports de un módulo analizado (con caché)."""
    if module.key[0]:
        yield from _imports_cached(
            module.key, module.name, module.is_package, module.dynamic_hint
        )
    else:
        yield from collect_imports(module.tree, module.name, module.is_package)


def clear_caches() -> None:
    """Vacía las cachés de los árboles, sus recorridos y sus imports, y la del texto
    (``repo.read_bytes``): después, cada fichero se vuelve a leer y a analizar. Se llama
    sola al salir del proceso (spec 006, T47): al cerrarse, Python tarda unos 2 s en
    liberar los árboles de todo el repositorio, y vaciarlas antes cuesta unos 0,1 s."""
    _imports_cached.cache_clear()
    _parse_cached.cache_clear()
    _WALKS.clear()
    _STATEMENTS.clear()
    clear_text_cache()


atexit.register(clear_caches)
