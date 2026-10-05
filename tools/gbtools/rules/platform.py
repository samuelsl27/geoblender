# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de la plataforma de extensiones y de rutas (plan 001 §5.4.1; RF-001-16).

En ``geoblender/`` (rutas de las excepciones, relativas a la extensión):

- PLT-01: asignación de nivel de módulo a ``bl_info`` (ADR-0003: la identidad vive en el
  manifiesto).
- PLT-02: más de una clase cuya base termina en ``AddonPreferences``, una fuera de
  ``bl/props/preferences.py`` o con ``bl_idname`` distinto de ``ADDON_PACKAGE``.
- ARQ-03: en el ``__init__.py`` raíz, cualquier import que se ejecute al importarlo
  (también dentro de ``if``/``try`` o de clases) salvo ``from __future__ import
  annotations``; y deben existir ``register`` y ``unregister``.
- ARQ-09: import absoluto de ``Geoblender``, ``geoblender``, ``bl_ext`` o de un paquete
  propio (también dinámico de nombre literal), o relativo que se sale del paquete;
  salvo en ``ARQ09_ALLOWED``.
- ARQ-15: literal de cadena (salvo docstrings) que empieza por una unidad (``X:`` y una
  barra), dos barras invertidas, ``file://`` o una carpeta absoluta de Linux o macOS.
- ARQ-16: ``pickle`` y similares, o ``allow_pickle=True`` en cualquier llamada.
- ARQ-18: ``sys.path`` modificado (también con ``sys`` importado con otro nombre, o
  ``path`` importado con ``from sys import path``), ``site.addsitedir`` (también con
  ``site`` renombrado), ``import pip`` o ``ensurepip``, o el literal ``"pip"`` en una
  lista, una tupla o un argumento; salvo en ``PIP_SYS_PATH_ALLOWED``. Los alias y
  ``from sys import path`` llegan con la convergencia de la spec 001 (T39).
- ARQ-19: en ``bl/``, ``threading``, ``_thread``, ``concurrent.futures`` o
  ``multiprocessing``.

En ``geoblender/``, ``tools/`` y ``tests/``:

- PLT-03: un módulo ``x.py`` y un paquete ``x/`` (con ``__init__.py``) en la misma
  carpeta: Python importa el paquete y oculta el módulo sin avisar.
- EXP-01: texto con una ruta a los expedientes de clientes (unidad, dos puntos, barra,
  ``an`` y barra) o al NAS por IP (dos barras, invertidas, normales o mezcladas, una
  IPv4 y una barra; las normales, desde la convergencia de la spec 001, T39).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from ..findings import Finding
from ..repo import is_text_file, iter_repo_files, relpath
from . import pyast
from .imports import EXTENSION, is_internal

RULE_BL_INFO = "PLT-01"
RULE_PREFERENCES = "PLT-02"
RULE_SHADOWING = "PLT-03"
RULE_ROOT = "ARQ-03"
RULE_INTERNAL = "ARQ-09"
RULE_PATHS = "ARQ-15"
RULE_PICKLE = "ARQ-16"
RULE_SYS_PATH = "ARQ-18"
RULE_THREADS = "ARQ-19"
RULE_DOSSIERS = "EXP-01"

# Excepciones, con rutas relativas a geoblender/.
ARQ09_ALLOWED: tuple[str, ...] = ("workers/_bootstrap.py",)
PIP_SYS_PATH_ALLOWED: tuple[str, ...] = ("workers/_bootstrap.py", "jobs/runtime.py")
PREFERENCES_MODULE = "bl/props/preferences.py"
# Nombre de la constante de bl/__init__.py con el paquete raíz (plan 001 §5.3).
ADDON_PACKAGE_NAME = "ADDON_PACKAGE"

PICKLE_MODULES: frozenset[str] = frozenset(
    {"pickle", "_pickle", "cPickle", "shelve", "dill", "cloudpickle"}
)
THREAD_MODULES: frozenset[str] = frozenset({"threading", "_thread", "multiprocessing"})
SYS_PATH_METHODS: frozenset[str] = frozenset(
    {"append", "insert", "extend", "remove", "pop", "clear"}
)
PIP_MODULES: frozenset[str] = frozenset({"pip", "ensurepip"})
ROOT_ALLOWED_IMPORTS: frozenset[str] = frozenset({"__future__.annotations"})

PATH_LITERAL = re.compile(
    r"^(?:[A-Za-z]:[\\/]|\\\\|file://|/(?:home|mnt|media|Users|tmp|usr|var|opt)/)"
)
DOSSIER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b[a-z]:[\\/]+an[\\/]"),
    re.compile(r"[\\/]{2}\d{1,3}(\.\d{1,3}){3}[\\/]"),
)
SHADOW_SCOPES: tuple[str, ...] = (f"{EXTENSION}/", "tools/", "tests/")


def _ext_rel(module: pyast.PyModule) -> str:
    return module.rel.removeprefix(f"{EXTENSION}/")


def _finding(module: pyast.PyModule, line: int, rule: str, message: str) -> Finding:
    return Finding(module.rel, line, rule, message)


def _module_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Sentencias que se ejecutan al importar, sin entrar en funciones ni clases."""
    for statement in body:
        yield statement
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _module_level(getattr(statement, field, []) or [])
        for handler in getattr(statement, "handlers", []) or []:
            yield from _module_level(handler.body)
        for case in getattr(statement, "cases", []) or []:
            yield from _module_level(case.body)


def _bl_info(module: pyast.PyModule) -> list[Finding]:
    findings: list[Finding] = []
    for statement in _module_level(module.tree.body):
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            targets = [statement.target]
        if any(isinstance(t, ast.Name) and t.id == "bl_info" for t in targets):
            findings.append(
                _finding(
                    module,
                    statement.lineno,
                    RULE_BL_INFO,
                    "define bl_info: la identidad y la versión de la extensión viven "
                    "solo en blender_manifest.toml (ADR-0003)",
                )
            )
    return findings


def _root_module(module: pyast.PyModule) -> list[Finding]:
    findings: list[Finding] = []
    for ref in pyast.iter_imports(module):
        if ref.in_function or ref.target in ROOT_ALLOWED_IMPORTS:
            continue
        findings.append(
            _finding(
                module,
                ref.line,
                RULE_ROOT,
                f"importa «{ref.target}» a nivel de módulo: el __init__.py raíz no "
                "importa nada fuera de register() y unregister(), para que el núcleo "
                "se importe sin Blender (ADR-0004)",
            )
        )
    defined = {
        node.name
        for node in module.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in ("register", "unregister") if name not in defined]
    if missing:
        findings.append(
            _finding(
                module,
                0,
                RULE_ROOT,
                "faltan " + " y ".join(f"{name}()" for name in missing)
                + " a nivel de módulo: Blender las llama al habilitar y deshabilitar",
            )
        )
    return findings


def _import_rules(module: pyast.PyModule) -> list[Finding]:
    """ARQ-09, ARQ-16, ARQ-18 (imports de pip) y ARQ-19."""
    rel = _ext_rel(module)
    in_bl = rel.startswith("bl/")
    findings: list[Finding] = []
    for ref in pyast.iter_imports(module):
        if ref.escapes:
            findings.append(
                _finding(
                    module,
                    ref.line,
                    RULE_INTERNAL,
                    f"el import relativo «{ref.target}» se sale del paquete de la "
                    "extensión",
                )
            )
            continue
        if ref.relative_level:
            continue
        top = ref.top
        how = "de forma dinámica " if ref.dynamic else ""
        if is_internal(top) and rel not in ARQ09_ALLOWED:
            findings.append(
                _finding(
                    module,
                    ref.line,
                    RULE_INTERNAL,
                    f"importa {how}«{ref.target}» de forma absoluta: dentro de la "
                    "extensión los imports son relativos (from ..core import x); el "
                    "prefijo depende del repositorio de instalación (ADR-0004 R6)",
                )
            )
        if top in PICKLE_MODULES:
            findings.append(
                _finding(
                    module,
                    ref.line,
                    RULE_PICKLE,
                    f"importa {how}«{ref.target}»: pickle y sus variantes ejecutan "
                    "código al leer y no son reproducibles; use formatos abiertos "
                    "(npz sin pickle, Parquet, JSON)",
                )
            )
        if top in PIP_MODULES and rel not in PIP_SYS_PATH_ALLOWED:
            findings.append(
                _finding(
                    module,
                    ref.line,
                    RULE_SYS_PATH,
                    f"importa «{ref.target}»: nada se instala con pip dentro de "
                    "Blender (principio 8); solo workers/_bootstrap.py y "
                    "jobs/runtime.py",
                )
            )
        is_thread = top in THREAD_MODULES or (
            ref.target == "concurrent.futures"
            or ref.target.startswith("concurrent.futures.")
        )
        if in_bl and is_thread:
            findings.append(
                _finding(
                    module,
                    ref.line,
                    RULE_THREADS,
                    f"importa «{ref.target}» en bl/: los hilos que tocan bpy cuelgan "
                    "Blender; el trabajo en segundo plano vive en jobs/",
                )
            )
    return findings


def _module_names(tree: ast.Module) -> dict[str, set[str]]:
    """Nombres con los que el fichero importa ``sys`` y ``site`` (``import sys``,
    ``import sys as s``), en cualquier ámbito; siempre con el propio nombre."""
    names: dict[str, set[str]] = {"sys": {"sys"}, "site": {"site"}}
    for node in pyast.iter_statements(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in names:
                    names[alias.name].add(alias.asname or alias.name)
    return names


def _is_sys_path(node: ast.expr, sys_names: set[str]) -> bool:
    if isinstance(node, ast.Subscript):
        node = node.value
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and isinstance(node.value, ast.Name)
        and node.value.id in sys_names
    )


def _expression_rules(module: pyast.PyModule) -> list[Finding]:
    """ARQ-15 (literales con rutas), ARQ-16 (``allow_pickle=True``) y ARQ-18
    (``sys.path``, ``site.addsitedir`` y ``"pip"``), en un solo recorrido del árbol.

    ``ast.walk`` visita cada nodo antes que sus hijos: al pasar por un padre se marcan
    los literales que no cuentan (docstrings, el resto de una f-string) y los que son
    elemento de una lista o una tupla o argumento de una llamada.
    """
    allowed = _ext_rel(module) in PIP_SYS_PATH_ALLOWED
    aliases = _module_names(module.tree)
    sys_names, site_names = aliases["sys"], aliases["site"]
    findings: list[Finding] = []
    skip: set[int] = set()
    pip_slots: set[int] = set()

    def add(line: int, rule: str, message: str) -> None:
        findings.append(_finding(module, line, rule, message))

    def sys_path(line: int, what: str) -> None:
        add(
            line,
            RULE_SYS_PATH,
            f"{what}: la extensión no toca sys.path (principio 8); solo "
            "workers/_bootstrap.py y jobs/runtime.py",
        )

    for node in ast.walk(module.tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skip.add(id(body[0].value))  # docstring
        elif isinstance(node, ast.JoinedStr):
            # Solo cuenta el principio de una f-string (nada de un formato).
            first = 0 if id(node) in skip else 1
            skip.update(id(part) for part in node.values[first:])
        elif isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            skip.add(id(node.format_spec))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip and PATH_LITERAL.match(node.value):
                add(
                    node.lineno,
                    RULE_PATHS,
                    "literal con una ruta absoluta o de red: las rutas llegan por "
                    "configuración, por el proyecto o por variable de entorno, nunca "
                    "escritas en el código",
                )
            if node.value == "pip" and id(node) in pip_slots and not allowed:
                add(
                    node.lineno,
                    RULE_SYS_PATH,
                    "invoca pip: nada se instala con pip dentro de Blender "
                    "(principio 8); solo workers/_bootstrap.py y jobs/runtime.py",
                )
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg == "allow_pickle"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    add(
                        node.lineno,
                        RULE_PICKLE,
                        "allow_pickle=True ejecuta código al leer: guarde sin objetos "
                        "de Python",
                    )
                pip_slots.add(id(keyword.value))
            pip_slots.update(id(argument) for argument in node.args)
            func = node.func
            if allowed:
                continue
            if (
                isinstance(func, ast.Attribute)
                and func.attr in SYS_PATH_METHODS
                and _is_sys_path(func.value, sys_names)
            ):
                sys_path(node.lineno, f"modifica sys.path con {func.attr}()")
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "addsitedir"
                and isinstance(func.value, ast.Name)
                and func.value.id in site_names
            ) or (isinstance(func, ast.Name) and func.id == "addsitedir"):
                sys_path(node.lineno, "llama a site.addsitedir()")
        elif isinstance(node, (ast.List, ast.Tuple)):
            pip_slots.update(id(element) for element in node.elts)
        elif not allowed and isinstance(
            node, (ast.Assign, ast.AugAssign, ast.AnnAssign)
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_is_sys_path(target, sys_names) for target in targets):
                sys_path(node.lineno, "asigna sys.path")
        elif not allowed and isinstance(node, ast.Delete):
            if any(_is_sys_path(target, sys_names) for target in node.targets):
                sys_path(node.lineno, "borra de sys.path")
        elif (
            not allowed
            and isinstance(node, ast.ImportFrom)
            and node.module == "sys"
            and not node.level
            and any(alias.name == "path" for alias in node.names)
        ):
            sys_path(node.lineno, "importa path de sys (from sys import path)")
    return findings


def _preferences(modules: list[pyast.PyModule]) -> list[Finding]:
    classes: list[tuple[pyast.PyModule, ast.ClassDef]] = []
    for module in modules:
        for node in pyast.iter_statements(module.tree):
            if isinstance(node, ast.ClassDef) and any(
                ast.unparse(base).endswith("AddonPreferences") for base in node.bases
            ):
                classes.append((module, node))
    findings: list[Finding] = []
    for module, node in classes:
        problems: list[str] = []
        if len(classes) > 1:
            names = ", ".join(sorted(n.name for _, n in classes))
            problems.append(
                f"hay {len(classes)} clases de preferencias ({names}) y debe haber una "
                "sola: una segunda sustituye a la primera"
            )
        if _ext_rel(module) != PREFERENCES_MODULE:
            problems.append(f"debe estar en {EXTENSION}/{PREFERENCES_MODULE}")
        bl_idname = None
        for statement in node.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "bl_idname"
                for t in statement.targets
            ):
                bl_idname = statement.value
        if bl_idname is None:
            problems.append("le falta bl_idname = ADDON_PACKAGE")
        elif not (
            (isinstance(bl_idname, ast.Name) and bl_idname.id == ADDON_PACKAGE_NAME)
            or (
                isinstance(bl_idname, ast.Attribute)
                and bl_idname.attr == ADDON_PACKAGE_NAME
            )
        ):
            problems.append(
                f"su bl_idname es «{ast.unparse(bl_idname)}» y debe ser ADDON_PACKAGE "
                "(el paquete raíz; con el de un submódulo las preferencias no se "
                "enlazan)"
            )
        if problems:
            findings.append(
                _finding(
                    module,
                    node.lineno,
                    RULE_PREFERENCES,
                    f"«{node.name}» (AddonPreferences): " + "; ".join(problems),
                )
            )
    return findings


def _shadowing(root: Path, rels: list[str]) -> list[Finding]:
    present = set(rels)
    findings: list[Finding] = []
    for rel in rels:
        if not rel.endswith(".py") or not rel.startswith(SHADOW_SCOPES):
            continue
        package = rel.removesuffix(".py")
        if package + "/__init__.py" in present:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_SHADOWING,
                    f"hay un paquete «{package}/» con el mismo nombre: Python "
                    "importa el paquete y oculta este módulo sin avisar; renombre "
                    "uno de los dos",
                )
            )
    return findings


def _dossier_paths(root: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = relpath(root, path)
        if not rel.startswith(SHADOW_SCOPES) or path.is_symlink():
            continue
        if not is_text_file(path):
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.split("\n"), start=1):
            if any(pattern.search(line) for pattern in DOSSIER_PATTERNS):
                findings.append(
                    Finding(
                        rel,
                        number,
                        RULE_DOSSIERS,
                        "contiene una ruta a los expedientes de clientes o al NAS: "
                        "las rutas a datos reales llegan por variable de entorno "
                        "(GEOBLENDER_SILVESTRE_DIR…), nunca escritas (U4)",
                    )
                )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de PLT-01 a 03, ARQ-03, 09, 15, 16, 18, 19, EXP-01 y AST-01."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    for module in modules:
        findings.extend(_bl_info(module))
        if module.name == "":
            findings.extend(_root_module(module))
        findings.extend(_import_rules(module))
        findings.extend(_expression_rules(module))
    findings.extend(_preferences(modules))
    paths = list(iter_repo_files(root))
    findings.extend(_shadowing(root, [relpath(root, path) for path in paths]))
    findings.extend(_dossier_paths(root, paths))
    return sorted(findings)
