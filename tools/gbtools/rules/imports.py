# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de imports (plan 001 §5.4.1; ADR-0004).

- ARQ-01 (RF-001-12): un módulo de Blender (``BLENDER_MODULES`` o un nombre que empieza
  por ``_bpy`` o ``_bl_``) solo se importa en ``geoblender/bl/``. También se aplica a
  ``tests/`` y ``tools/``, salvo ``tests/blender/``, ``tests/rendimiento/blender/``,
  ``tests/support/blender_ext.py``, ``tools/run_blender_tests.py`` y
  ``tools/inblender/``. Cuenta el import dentro de funciones y de ``if TYPE_CHECKING``
  y el dinámico de nombre literal. ``tools/check.py`` amplía la lista con los módulos
  de la instalación localizada (``installation_modules``) y se la pasa a las pruebas en
  ``GEOBLENDER_BLENDER_MODULES`` (``blender_modules``); sin ella, la lista fija.
- ARQ-04 (RF-001-13): fuera de ``geoblender/adapters/``, un import absoluto solo puede
  ser de la biblioteca estándar (``sys.stdlib_module_names``), numpy o ``__future__``.
  Los módulos de Blender (ARQ-01) y los nombres propios de Geoblender (ARQ-09) tienen
  su regla.
- ARQ-05 (RF-001-13): en ``adapters/``, cada librería externa la importa solo el
  módulo o subpaquete dueño que fija ``ADAPTER_OWNERS`` (pyproj, de la spec 006:
  ``adapters.pyproj_crs``).
- HER-01 (RF-001-13): ``tools/`` (salvo ``run_blender_tests.py`` y ``tools/inblender/``)
  solo importa biblioteca estándar, ``gbtools``, los scripts hermanos de ``tools/`` y
  ``geoblender`` cargado por ruta con ``gbtools.package.load_geoblender`` (nunca
  ``geoblender.bl``).

Dirección de las dependencias dentro de ``geoblender/`` (RF-001-14; imports relativos):

- ARQ-02: nada importa ``bl`` salvo el ``__init__.py`` raíz dentro de ``register()`` y
  ``unregister()``.
- ARQ-06: ``core`` solo importa ``core``; ``jobs``, ``core`` y ``jobs`` (lo absoluto lo
  cubren ARQ-01, ARQ-04 y ARQ-09).
- ARQ-07: un paquete de dominio solo importa paquetes de nivel menor (``LEVELS``); de
  ``adapters``, solo ``adapters.registry`` y dentro de una función; nunca ``workers``.
  ``bl`` no importa ``adapters`` ni ``workers``.
- ARQ-08: sin ciclos en el grafo de los imports que se ejecutan al importar (cuerpo de
  módulo, sin funciones ni ``if TYPE_CHECKING``). En ``from x import y``, el destino
  es ``x.y`` si es un módulo y si no ``x``; importar de sí mismo no es una arista.
  Importar un submódulo importa antes sus paquetes: hay arista del importador a cada
  paquete antecesor del destino que no lo sea también del importador (ese ya está
  en ``sys.modules``). Así un ``__init__`` que importa sus submódulos no es un
  ciclo, y sí lo es un submódulo que importa un nombre del ``__init__`` de su
  paquete mientras este lo importa a él.
- ARQ-10: ``adapters`` solo importa ``core`` y módulos ``ports``;
  ``adapters/registry.py`` importa sus hermanos solo dentro de funciones; un
  ``ports.py`` solo importa ``core``.

Workers (spec 004, T16; RF-004-14; ``check_workers``):

- ARQ-11: un módulo de ``workers/`` no importa ``bl``, ``core.project`` ni el adaptador
  de escritura de DuckDB (``WORKERS_FORBIDDEN``), ni nada suyo: ni relativo, ni absoluto
  (``geoblender.…``, ``bl_ext.<repo>.geoblender.…`` o el paquete suelto), ni dinámico de
  nombre literal; también dentro de funciones y de ``if TYPE_CHECKING``. El proyecto
  solo lo escribe Blender (escritor único, principio 7; ADR-0010).
- ARQ-09, condición de su excepción: ``workers/_bootstrap.py`` (``ARQ09_ALLOWED`` de
  ``platform``) importa ``geoblender`` de forma absoluta solo tras cargarlo por ruta, así
  que lo que se ejecuta al importarlo (fuera de funciones y de ``if TYPE_CHECKING``) solo
  importa la biblioteca estándar: ni numpy ni ``geoblender``.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

from ..findings import Finding
from ..layout import EXTENSION_DIR
from . import pyast

RULE_BLENDER = "ARQ-01"
RULE_BL_IMPORT = "ARQ-02"
RULE_EXTERNAL = "ARQ-04"
RULE_ADAPTER_OWNER = "ARQ-05"
RULE_CORE = "ARQ-06"
RULE_LEVELS = "ARQ-07"
RULE_CYCLES = "ARQ-08"
RULE_ADAPTERS = "ARQ-10"
RULE_WORKERS = "ARQ-11"
RULE_BOOTSTRAP = "ARQ-09"
RULE_TOOLS = "HER-01"

# Niveles de los paquetes de dominio (vision-general.md §2.1; ratificados en el plan
# 001, D-2): un paquete solo importa paquetes de nivel menor.
LEVELS: Mapping[str, int] = {
    "core": 0,
    "jobs": 1,
    "gis": 2,
    "drillholes": 3,
    "geomodel": 4,
    "implicit": 5,
    "blockmodel": 6,
    "pitopt": 7,
    "design": 8,
    "reserves": 9,
    "interop": 10,
    "plans": 11,
}
REGISTRY = "adapters.registry"
BL_ENTRY_POINTS: frozenset[str] = frozenset({"register", "unregister"})

# Lista fija del plan 001 §5.4.1; check.py la amplía con los módulos de la instalación.
BLENDER_MODULES: frozenset[str] = frozenset(
    {
        "bpy",
        "bmesh",
        "gpu",
        "gpu_extras",
        "mathutils",
        "bpy_extras",
        "blf",
        "bl_ui",
        "bl_operators",
        "bl_app_override",
        "bl_app_template_utils",
        "bl_keymap_utils",
        "addon_utils",
        "nodeitems_utils",
        "rna_keymap_ui",
        "rna_prop_ui",
        "blend_render_info",
        "idprop",
        "imbuf",
        "aud",
        "freestyle",
        "bl_math",
    }
)
BLENDER_PREFIXES: tuple[str, ...] = ("_bpy", "_bl_")
# Variable con la que tools/check.py pasa a las pruebas los módulos de la instalación
# localizada (nombres separados por comas): amplía BLENDER_MODULES (plan 001 §5.4.1).
ENV_BLENDER_MODULES = "GEOBLENDER_BLENDER_MODULES"
# Carpetas de <Blender>/<versión>/scripts con los módulos de Blender importables.
INSTALLATION_FOLDERS: tuple[str, ...] = ("modules", "startup")

EXTENSION = EXTENSION_DIR
# Paquetes de la extensión (ADR-0004): un import absoluto de uno de ellos, o de
# INTERNAL_ROOTS, es ARQ-09 (los imports internos son relativos).
EXTENSION_PACKAGES: frozenset[str] = frozenset(
    {
        "core",
        "jobs",
        "gis",
        "drillholes",
        "geomodel",
        "implicit",
        "blockmodel",
        "pitopt",
        "design",
        "reserves",
        "interop",
        "plans",
        "adapters",
        "workers",
        "bl",
    }
)
INTERNAL_ROOTS: frozenset[str] = frozenset({"Geoblender", "geoblender", "bl_ext"})
ALLOWED_THIRD_PARTY: frozenset[str] = frozenset({"numpy", "__future__"})

# Ficheros y carpetas que sí pueden importar módulos de Blender (ARQ-01).
ARQ01_ALLOWED: tuple[str, ...] = (
    f"{EXTENSION_DIR}/bl/",
    "tests/blender/",
    "tests/rendimiento/blender/",
    "tests/support/blender_ext.py",
    "tools/run_blender_tests.py",
    "tools/inblender/",
)
# Guiones de tools/ que se ejecutan dentro de Blender: fuera de HER-01.
HER01_EXEMPT: tuple[str, ...] = ("tools/run_blender_tests.py", "tools/inblender/")

# Librería (primer nivel del import) → módulo o subpaquete dueño dentro de la
# extensión; cada spec que añade un adaptador registra aquí su librería, con el ADR que la
# admite (pyproj: spec 006, ADR-0005; certifi no se importa: es dependencia de pyproj).
ADAPTER_OWNERS: Mapping[str, str] = {"pyproj": "adapters.pyproj_crs"}

TOOLS_LIBRARY = "gbtools"
PACKAGE_LOADER = "load_geoblender"

# ARQ-11 (spec 004): lo que un worker no importa, con nombres dentro de la extensión. Un
# módulo que añada otro adaptador que escriba en el proyecto lo añade aquí.
WORKERS_PACKAGE = "workers"
WORKERS_FORBIDDEN: tuple[str, ...] = ("bl", "core.project", "adapters.duckdb_store")
# El arranque de los workers: la excepción de ARQ-09 (platform.ARQ09_ALLOWED).
BOOTSTRAP_MODULE = "workers._bootstrap"
# Cuántos componentes ocupa cada raíz de INTERNAL_ROOTS en un nombre absoluto: uno, salvo
# ``bl_ext.<repo>.<extensión>`` (tres).
_ROOT_PARTS: Mapping[str, int] = {
    root: 3 if root == "bl_ext" else 1 for root in INTERNAL_ROOTS
}


def is_blender_module(
    name: str, blender_modules: Collection[str] = BLENDER_MODULES
) -> bool:
    """Verdadero si el primer componente de ``name`` es un módulo de Blender."""
    top = name.partition(".")[0]
    return top in blender_modules or top.startswith(BLENDER_PREFIXES)


def installation_modules(scripts_dir: Path) -> frozenset[str]:
    """Módulos de Blender de una instalación: nombres de primer nivel de
    ``<scripts>/modules`` y ``<scripts>/startup`` (ficheros ``.py`` y carpetas cuyo
    nombre es un identificador de Python, sin ``__pycache__``)."""
    names: set[str] = set()
    for folder in INSTALLATION_FOLDERS:
        try:
            entries = list(os.scandir(Path(scripts_dir) / folder))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                name = entry.name
            elif entry.name.endswith(".py"):
                name = entry.name[: -len(".py")]
            else:
                continue
            if name.isidentifier() and name != "__pycache__":
                names.add(name)
    return frozenset(names)


def blender_modules(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """``BLENDER_MODULES`` más los que ``tools/check.py`` pasa en
    ``GEOBLENDER_BLENDER_MODULES`` (sin la variable, la lista fija)."""
    env = os.environ if environ is None else environ
    names = (name.strip() for name in env.get(ENV_BLENDER_MODULES, "").split(","))
    return BLENDER_MODULES | {name for name in names if name}


def is_internal(name: str) -> bool:
    """Verdadero si ``name`` nombra Geoblender de forma absoluta (asunto de ARQ-09)."""
    top = name.partition(".")[0]
    return top in INTERNAL_ROOTS or top in EXTENSION_PACKAGES


def is_external(name: str, blender_modules: Collection[str] = BLENDER_MODULES) -> bool:
    """Verdadero si ``name`` es una librería externa: ni biblioteca estándar, ni numpy,
    ni ``__future__``, ni Blender, ni Geoblender."""
    top = name.partition(".")[0]
    return not (
        top in sys.stdlib_module_names
        or top in ALLOWED_THIRD_PARTY
        or is_blender_module(top, blender_modules)
        or is_internal(top)
    )


def _all_modules(root: Path) -> tuple[list[pyast.PyModule], list[Finding]]:
    """Los ``.py`` de ``geoblender/`` (nombres relativos a la extensión), ``tests/``
    (``tests.…``) y ``tools/`` (relativos a ``tools/``)."""
    scopes = {EXTENSION: EXTENSION, "tests": "", "tools": "tools"}
    return pyast.parse_scopes(root, scopes)


def _in_extension(module: pyast.PyModule) -> bool:
    return module.rel.startswith(f"{EXTENSION}/")


def _absolute(module: pyast.PyModule) -> Iterable[pyast.ImportRef]:
    return (ref for ref in pyast.iter_imports(module) if not ref.relative_level)


def _how(ref: pyast.ImportRef) -> str:
    return "de forma dinámica " if ref.dynamic else ""


def _blender_findings(
    modules: Iterable[pyast.PyModule], blender_modules: Collection[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for module in modules:
        if module.rel.startswith(ARQ01_ALLOWED):
            continue
        if _in_extension(module):
            advice = f"muévalo a {EXTENSION_DIR}/bl/: el dominio no sabe de Blender"
        elif module.rel.startswith("tests/"):
            advice = (
                "las pruebas sin Blender no lo importan: si necesita bpy, póngala en "
                "tests/blender/"
            )
        else:
            advice = (
                "las herramientas se ejecutan fuera de Blender: si es un guion para "
                "dentro de Blender, póngalo en tools/inblender/"
            )
        for ref in _absolute(module):
            if is_blender_module(ref.target, blender_modules):
                findings.append(
                    Finding(
                        module.rel,
                        ref.line,
                        RULE_BLENDER,
                        f"importa {_how(ref)}«{ref.target}», un módulo de Blender: "
                        f"{advice} (ADR-0004)",
                    )
                )
    return findings


def _owns(owner: str, module_name: str) -> bool:
    return module_name == owner or module_name.startswith(owner + ".")


def _extension_external_findings(
    module: pyast.PyModule,
    blender_modules: Collection[str],
    adapter_owners: Mapping[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    in_adapters = module.name == "adapters" or module.name.startswith("adapters.")
    for ref in _absolute(module):
        if not is_external(ref.target, blender_modules):
            continue
        library = ref.top
        if not in_adapters:
            findings.append(
                Finding(
                    module.rel,
                    ref.line,
                    RULE_EXTERNAL,
                    f"importa {_how(ref)}«{ref.target}», una librería externa, fuera "
                    "de adapters/: defina un puerto en el dominio e impleméntelo en su "
                    "adaptador (principio 4; ADR-0004)",
                )
            )
            continue
        owner = adapter_owners.get(library)
        if owner is None:
            message = (
                f"importa «{library}», que no tiene adaptador dueño: regístrelo en "
                "ADAPTER_OWNERS (tools/gbtools/rules/imports.py) con el ADR y la spec "
                "que admiten la dependencia"
            )
        elif not _owns(owner, module.name):
            message = (
                f"importa «{library}», cuyo único dueño es «{owner}»: use ese "
                "adaptador (una librería, un adaptador)"
            )
        else:
            continue
        findings.append(Finding(module.rel, ref.line, RULE_ADAPTER_OWNER, message))
    return findings


def _uses_package_loader(tree: ast.Module) -> bool:
    for node in pyast.nodes_of(tree, (ast.Name, ast.Attribute, ast.ImportFrom)):
        if isinstance(node, ast.Name) and node.id == PACKAGE_LOADER:
            return True
        if isinstance(node, ast.Attribute) and node.attr == PACKAGE_LOADER:
            return True
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == PACKAGE_LOADER for alias in node.names
        ):
            return True
    return False


def _tools_findings(
    module: pyast.PyModule,
    siblings: frozenset[str],
    blender_modules: Collection[str],
) -> list[Finding]:
    if module.rel.startswith(HER01_EXEMPT):
        return []
    findings: list[Finding] = []
    loader = None  # se calcula solo si hace falta
    for ref in _absolute(module):
        top = ref.top
        if top in sys.stdlib_module_names or top == TOOLS_LIBRARY or top in siblings:
            continue
        if is_blender_module(top, blender_modules):
            continue  # lo señala ARQ-01
        if top == "geoblender":
            if ref.target == "geoblender.bl" or ref.target.startswith("geoblender.bl."):
                message = (
                    f"importa «{ref.target}»: la capa de presentación solo existe "
                    "dentro de Blender; las herramientas usan el núcleo y el dominio"
                )
            else:
                if loader is None:
                    loader = _uses_package_loader(module.tree)
                if loader:
                    continue
                message = (
                    f"importa «{ref.target}» sin cargarlo por ruta: llame antes a "
                    "gbtools.package.load_geoblender(raíz)"
                )
        else:
            message = (
                f"importa {_how(ref)}«{ref.target}»: las herramientas solo usan la "
                "biblioteca estándar, gbtools, sus scripts hermanos y geoblender "
                "cargado por ruta (ADR-0015)"
            )
        findings.append(Finding(module.rel, ref.line, RULE_TOOLS, message))
    return findings


def check_blender_modules(
    root: Path, blender_modules: Iterable[str] = BLENDER_MODULES
) -> list[Finding]:
    """Incumplimientos de ARQ-01 (y AST-01 de lo que no se puede analizar)."""
    modules, findings = _all_modules(root)
    findings.extend(_blender_findings(modules, frozenset(blender_modules)))
    return sorted(findings)


def check_external_libraries(
    root: Path,
    blender_modules: Iterable[str] = BLENDER_MODULES,
    adapter_owners: Mapping[str, str] = ADAPTER_OWNERS,
) -> list[Finding]:
    """Incumplimientos de ARQ-04, ARQ-05 y HER-01 (y AST-01)."""
    modules, findings = _all_modules(root)
    findings.extend(
        _external_findings(modules, frozenset(blender_modules), adapter_owners)
    )
    return sorted(findings)


def _external_findings(
    modules: list[pyast.PyModule],
    blender: frozenset[str],
    adapter_owners: Mapping[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    siblings = frozenset(
        module.name
        for module in modules
        if module.rel.startswith("tools/") and module.rel.count("/") == 1
    )
    for module in modules:
        if _in_extension(module):
            findings.extend(
                _extension_external_findings(module, blender, adapter_owners)
            )
        elif module.rel.startswith("tools/"):
            findings.extend(_tools_findings(module, siblings, blender))
    return findings


def _is_ports_module(name: str) -> bool:
    return name.rsplit(".", 1)[-1] == "ports"


def _names_ports(target: str) -> bool:
    """Verdadero si ``target`` es un módulo ``ports`` de un paquete o algo suyo."""
    return "ports" in target.split(".")[1:]


def _is_registry(target: str) -> bool:
    return target == REGISTRY or target.startswith(REGISTRY + ".")


def _direction_finding(module: pyast.PyModule, ref: pyast.ImportRef) -> Finding | None:
    """El incumplimiento de ARQ-02, 06, 07 o 10 de un import relativo, si lo hay."""
    source = module.name.partition(".")[0]
    target, top = ref.target, ref.top

    def finding(rule: str, message: str) -> Finding:
        return Finding(module.rel, ref.line, rule, message)

    if top == "bl" and source != "bl":
        if module.name == "" and ref.top_function in BL_ENTRY_POINTS:
            return None
        return finding(
            RULE_BL_IMPORT,
            f"importa «{target}»: nada importa bl (la presentación); solo el "
            "__init__.py raíz, dentro de register() y unregister() (ADR-0004)",
        )
    if source == "adapters":
        if top == "core" or _names_ports(target):
            return None
        if module.name == REGISTRY and top == "adapters":
            if ref.in_function:
                return None
            return finding(
                RULE_ADAPTERS,
                f"importa «{target}» a nivel de módulo: adapters/registry.py resuelve "
                "sus hermanos solo dentro de funciones (resolución diferida)",
            )
        return finding(
            RULE_ADAPTERS,
            f"importa «{target}»: un adaptador solo importa core y los módulos ports "
            "que implementa (ADR-0004 §4)",
        )
    if _is_ports_module(module.name):
        if top == "core":
            return None
        return finding(
            RULE_ADAPTERS,
            f"importa «{target}»: un ports.py solo importa la biblioteca estándar, "
            "numpy y core (vision-general.md §2.3)",
        )
    if source in ("core", "jobs"):
        allowed = ("core",) if source == "core" else ("core", "jobs")
        if top in allowed:
            return None
        return finding(
            RULE_CORE,
            f"importa «{target}»: {source} solo importa "
            + (" y ".join(allowed))
            + ", la biblioteca estándar y numpy (ADR-0004)",
        )
    if source in LEVELS:
        if top in LEVELS and top != source and LEVELS[top] >= LEVELS[source]:
            return finding(
                RULE_LEVELS,
                f"importa «{target}» (nivel {LEVELS[top]}) desde {source} (nivel "
                f"{LEVELS[source]}): un paquete de dominio solo importa paquetes de "
                "nivel menor (vision-general.md §2.2)",
            )
        if top == "adapters" and not (_is_registry(target) and ref.in_function):
            return finding(
                RULE_LEVELS,
                f"importa «{target}»: el dominio recibe los adaptadores por argumento "
                "o los resuelve adapters.registry dentro de una función",
            )
        if top == "workers":
            return finding(
                RULE_LEVELS,
                f"importa «{target}»: el dominio no importa workers (se lanzan como "
                "trabajos)",
            )
        return None
    if source == "bl" and top in ("adapters", "workers"):
        return finding(
            RULE_LEVELS,
            f"importa «{target}»: bl no importa adapters ni workers; llama al dominio",
        )
    return None


def _longest_module(name: str, names: Collection[str]) -> str | None:
    """El módulo existente más largo que es prefijo de ``name`` (``""`` = raíz)."""
    parts = name.split(".") if name else []
    for size in range(len(parts), -1, -1):
        candidate = ".".join(parts[:size])
        if candidate in names:
            return candidate
    return None


def _resolve_node(ref: pyast.ImportRef, names: Collection[str]) -> str | None:
    """Módulo que ejecuta un import: en ``from x import y``, ``x.y`` si es un módulo
    y si no ``x`` (``y`` es un nombre de ``x``); en ``import x.y``, ``x.y``."""
    if ref.base is not None and ref.target not in names:
        return _longest_module(ref.base, names)
    return _longest_module(ref.target, names)


def _prefixes(name: str) -> list[str]:
    """``""``, ``a``, ``a.b``… hasta ``name`` sin incluirlo."""
    parts = name.split(".") if name else []
    return [".".join(parts[:size]) for size in range(len(parts))]


def _import_graph(
    modules: Iterable[pyast.PyModule],
) -> tuple[dict[str, set[str]], dict[tuple[str, str], int]]:
    """Grafo de los imports que se ejecutan al importar cada módulo de la extensión."""
    by_name = {module.name: module for module in modules}
    edges: dict[str, set[str]] = {name: set() for name in by_name}
    lines: dict[tuple[str, str], int] = {}

    def add(source: str, target: str, line: int) -> None:
        edges[source].add(target)
        key = (source, target)
        lines[key] = min(line, lines.get(key, line))

    for name, module in by_name.items():
        own = {*_prefixes(name), name}
        for ref in pyast.iter_imports(module):
            if (
                not ref.relative_level
                or ref.escapes
                or ref.in_function
                or ref.in_type_checking
            ):
                continue
            node = _resolve_node(ref, by_name)
            if node is None or node == name:
                continue  # importar de sí mismo no ejecuta otro módulo
            add(name, node, ref.line)
            for ancestor in _prefixes(node):
                if ancestor in by_name and ancestor not in own:
                    add(name, ancestor, ref.line)
    return edges, lines


def _strongly_connected(edges: Mapping[str, Collection[str]]) -> list[list[str]]:
    """Componentes fuertemente conexas (Tarjan, iterativo)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []
    counter = 0
    for start in sorted(edges):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(edges[start])))]
        while work:
            node, children = work[-1]
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(edges[child]))))
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(sorted(component))
    return components


def _cycle_path(
    start: str, members: Collection[str], edges: Mapping[str, Collection[str]]
) -> list[str]:
    """Un ciclo que empieza y acaba en ``start`` dentro de su componente."""
    parents: dict[str, str] = {}
    queue = deque([start])
    seen = {start}
    while queue:
        node = queue.popleft()
        for child in sorted(edges[node]):
            if child == start:
                path = [node]
                while path[-1] != start:
                    path.append(parents[path[-1]])
                return [*reversed(path), start]
            if child in members and child not in seen:
                seen.add(child)
                parents[child] = node
                queue.append(child)
    return [start, start]


def _cycle_findings(modules: Iterable[pyast.PyModule]) -> list[Finding]:
    modules = list(modules)
    rel_of = {module.name: module.rel for module in modules}
    edges, lines = _import_graph(modules)
    findings: list[Finding] = []
    for component in _strongly_connected(edges):
        start = component[0]
        if len(component) == 1 and start not in edges[start]:
            continue
        path = _cycle_path(start, component, edges)
        shown = " → ".join(name or "(raíz)" for name in path)
        findings.append(
            Finding(
                rel_of[start],
                lines[(start, path[1])],
                RULE_CYCLES,
                f"ciclo de imports a nivel de módulo: {shown}; rómpalo moviendo lo "
                "común a un módulo de nivel menor o importando dentro de la función "
                "que lo usa",
            )
        )
    return findings


def check_dependency_direction(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-02, ARQ-06, ARQ-07, ARQ-08 y ARQ-10 (y AST-01)."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    findings.extend(_direction_findings(modules))
    return sorted(findings)


def _direction_findings(modules: list[pyast.PyModule]) -> list[Finding]:
    """ARQ-02, 06, 07 y 10 de cada import relativo y ARQ-08 del conjunto."""
    findings: list[Finding] = []
    for module in modules:
        for ref in pyast.iter_imports(module):
            if not ref.relative_level or ref.escapes:
                continue  # lo absoluto y lo que se sale del paquete: otras reglas
            problem = _direction_finding(module, ref)
            if problem is not None:
                findings.append(problem)
    findings.extend(_cycle_findings(modules))
    return findings


def _in_workers(module: pyast.PyModule) -> bool:
    return module.name == WORKERS_PACKAGE or module.name.startswith(WORKERS_PACKAGE + ".")


def _extension_name(ref: pyast.ImportRef) -> str | None:
    """El nombre dentro de la extensión (``core.project.session``) de lo que importa
    ``ref``: el relativo ya resuelto, el absoluto sin su raíz (``geoblender.``,
    ``bl_ext.<repo>.geoblender.``) o con un paquete propio (``core.…``, que además es
    ARQ-09); ``None`` si no es de la extensión o se sale del paquete."""
    if ref.escapes:
        return None
    if ref.relative_level:
        return ref.target
    parts = ref.target.split(".")
    size = _ROOT_PARTS.get(parts[0])
    if size is not None:
        return ".".join(parts[size:])
    if parts[0] in EXTENSION_PACKAGES:
        return ref.target
    return None


def _forbidden_for_workers(name: str) -> str | None:
    """El elemento de ``WORKERS_FORBIDDEN`` que es ``name`` o lo contiene, si lo hay."""
    for forbidden in WORKERS_FORBIDDEN:
        if name == forbidden or name.startswith(forbidden + "."):
            return forbidden
    return None


def _bootstrap_findings(module: pyast.PyModule) -> list[Finding]:
    """La condición de la excepción de ARQ-09: lo que se ejecuta al importar el arranque
    solo importa la biblioteca estándar."""
    findings: list[Finding] = []
    for ref in pyast.iter_imports(module):
        if ref.in_function or ref.in_type_checking:
            continue
        if not ref.relative_level and (
            ref.top in sys.stdlib_module_names or ref.top == "__future__"
        ):
            continue
        findings.append(
            Finding(
                module.rel,
                ref.line,
                RULE_BOOTSTRAP,
                f"importa {_how(ref)}«{ref.target}» al importarse: hasta cargar el paquete "
                f"por ruta, {EXTENSION_DIR}/workers/_bootstrap.py solo importa la "
                "biblioteca estándar (la excepción de ARQ-09 vale tras cargarlo; numpy, "
                "con el sys.path del intérprete ya fijado); impórtelo dentro de la función "
                "que lo usa",
            )
        )
    return findings


def _workers_findings(modules: Iterable[pyast.PyModule]) -> list[Finding]:
    """ARQ-11 de los módulos de ``workers/`` y la condición de ARQ-09 del arranque."""
    findings: list[Finding] = []
    for module in modules:
        if not _in_workers(module):
            continue
        if module.name == BOOTSTRAP_MODULE:
            findings.extend(_bootstrap_findings(module))
        for ref in pyast.iter_imports(module):
            name = _extension_name(ref)
            forbidden = None if name is None else _forbidden_for_workers(name)
            if forbidden is None:
                continue
            findings.append(
                Finding(
                    module.rel,
                    ref.line,
                    RULE_WORKERS,
                    f"importa {_how(ref)}«{ref.target}» ({forbidden}): un worker no "
                    "importa bl, core.project ni el adaptador de escritura de DuckDB; el "
                    "proyecto solo lo escribe Blender (escritor único, principio 7; "
                    "ADR-0010). Recibe sus entradas en in/ y deja sus resultados en out/",
                )
            )
    return findings


def check_workers(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-11 y de la condición de ARQ-09 de ``workers/_bootstrap.py``
    (y AST-01) en ``geoblender/``."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    findings.extend(_workers_findings(modules))
    return sorted(findings)


def check(
    root: Path, blender_modules: Iterable[str] = BLENDER_MODULES
) -> list[Finding]:
    """Incumplimientos de todas las reglas de imports (ARQ-01, 02, 04 a 08, 10, 11, la
    condición de ARQ-09 del arranque de los workers y HER-01, y AST-01) en el
    repositorio bajo ``root``, analizándolo una sola vez."""
    modules, findings = _all_modules(root)
    blender = frozenset(blender_modules)
    extension = [m for m in modules if _in_extension(m)]
    findings.extend(_blender_findings(modules, blender))
    findings.extend(_external_findings(modules, blender, ADAPTER_OWNERS))
    findings.extend(_direction_findings(extension))
    findings.extend(_workers_findings(extension))
    return sorted(set(findings))
