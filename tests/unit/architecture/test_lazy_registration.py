# SPDX-License-Identifier: GPL-3.0-or-later
"""Habilitar Geoblender no carga el cálculo de la 012 (spec 012, T38; RNF-001-03 de la spec 001;
plan 012 §7.4; principio 8).

Habilitar la extensión en Blender 5.2.1 en segundo plano tarda ≤ 0,5 s (RNF-001-03). Las
máscaras de las restricciones, su búsqueda, el motor de la verificación y la cadena de la
procedencia y las versiones que arrastran (``core.versions.reproduce`` y ``freeze``, con
``core.provenance.lineage`` y ``recompute``) costaban unos 55 ms en frío y no se necesitan hasta la
primera orden: ``bl`` declara en el registro lo que hace falta (familias, operaciones, cifras,
comprobación de congelar) con módulos ligeros y los importa **al usarlos**, dentro de la función.

Esta prueba lo fija sin Blender, con el árbol sintáctico (AST): los imports que se ejecutan al
importar los subpaquetes que registra ``bl`` (``props``, ``scene``, ``draw``, ``gn``, ``ops`` y
``ui``, con los de nivel de módulo de todo lo que importan, y los paquetes que contienen cada
módulo) no llegan a ninguno de :data:`HEAVY`; un import dentro de una función o de
``if TYPE_CHECKING`` no cuenta (es el que la hace perezosa). Lo mide de verdad
``tests/rendimiento/blender/perf_registration.py`` y lo comprueba en Blender
``tests/blender/test_constraints_registration.py`` (``LazyRegistrationTest``).
"""

from __future__ import annotations

import ast
import unittest
from collections import deque
from collections.abc import Collection, Mapping

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import imports, pyast  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"

HEAVY: frozenset[str] = frozenset({
    # Las máscaras: componer, guardar, compilar, buscar y exportar (``gis.masks.provenance`` es la
    # declaración ligera de lo que se registra).
    "gis.masks.access", "gis.masks.combine", "gis.masks.compile", "gis.masks.export",
    "gis.masks.overlay", "gis.masks.sectors", "gis.masks.sources", "gis.masks.store",
    "gis.masks.zones",
    # La búsqueda de intocables.
    "gis.search",
    # El motor de la verificación por recinto y su almacén.
    "reserves.compliance", "reserves.compliance_store",
    # La cadena de las versiones y la procedencia que arrastran el almacén y las máscaras.
    "core.versions.freeze", "core.versions.reproduce", "core.versions.copy",
    "core.versions.check", "core.provenance.lineage", "core.provenance.recompute",
    # El cálculo de las envolventes y el escalonado de la 013 (spec 013, T21): ``design.params``,
    # ``design.provenance``, ``design.profiles``, ``design.messages`` y ``design.model`` son las
    # declaraciones ligeras que registra ``bl/ops/des.py``; el resto se importa al usarlo.
    "design.benching", "design.berms", "design.compose", "design.envelopes", "design.export",
    "design.pipeline", "design.preview", "design.reduction", "design.report",
    "design.reproduce", "design.sectors", "design.seeds", "design.steps", "design.store",
    "design.surfaces", "design.zones",
    # Las entidades de diseño de la 015 (spec 015, T02, T06 y T11): ``design.entities``,
    # ``design.platform`` y ``design.entity_store``.
    "design.entities", "design.platform", "design.entity_store",
    # La detección de acopios de la 016 (spec 016, T11 y T12): preparar, calcular por pasos y el resumen.
    "design.stockpiles", "design.stockpile_store",
})
"""Los módulos de la 012, la 013 y la 015 (y la cadena que arrastran) que se importan al primer uso."""


def registered_roots(modules: Collection[pyast.PyModule]) -> list[str]:
    """Los paquetes que importa ``bl.register()`` (``bl.SUBPACKAGES``, leído de ``bl/__init__.py``
    sin importarlo) y ``bl`` mismo."""
    names = {module.name for module in modules}
    package = next(module for module in modules if module.name == "bl")
    for node in package.tree.body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == "SUBPACKAGES" and node.value is not None):
            subpackages = ast.literal_eval(node.value)
            break
    else:
        raise AssertionError("bl/__init__.py no declara SUBPACKAGES")
    return ["bl", *(f"bl.{name}" for name in subpackages if f"bl.{name}" in names)]


def reachable(edges: Mapping[str, Collection[str]], roots: Collection[str]
              ) -> dict[str, list[str]]:
    """Lo que se importa al importar ``roots`` (los imports de nivel de módulo, transitivos): cada
    módulo con el camino más corto que lo trae desde uno de ellos."""
    paths: dict[str, list[str]] = {root: [root] for root in roots if root in edges}
    queue = deque(paths)
    while queue:
        node = queue.popleft()
        for child in sorted(edges.get(node, ())):
            if child not in paths:
                paths[child] = [*paths[node], child]
                queue.append(child)
    return paths


def loaded_by_registering(modules: list[pyast.PyModule]) -> dict[str, list[str]]:
    edges, _lines = imports._import_graph(modules)
    return reachable(edges, registered_roots(modules))


def heavy_reached(modules: list[pyast.PyModule], heavy: Collection[str] = HEAVY) -> list[str]:
    """Una línea por módulo pesado que registra ``bl``, con el camino que lo trae."""
    paths = loaded_by_registering(modules)
    return [" → ".join(paths[name]) for name in sorted(heavy) if name in paths]


class LazyRegistrationTest(unittest.TestCase):
    def test_registering_does_not_reach_the_heavy_modules(self) -> None:
        """RNF-001-03 (spec 001), plan 012 §7.4: ninguna importación de nivel de módulo de lo que
        registra ``bl`` llega a las máscaras, a la búsqueda, al motor de la verificación ni a la
        cadena de versiones y procedencia que arrastran; se importan al usarlas."""
        modules, findings = pyast.parse_modules(ROOT, EXT, EXT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))
        reached = heavy_reached(modules)
        self.assertEqual(reached, [], "\nImportados al habilitar (de uno de los subpaquetes de "
                         "bl al módulo pesado):\n  " + "\n  ".join(reached))

    def test_the_heavy_modules_exist(self) -> None:
        """RNF-001-03: cada nombre de :data:`HEAVY` es un módulo del código (no un error de
        escritura que dejaría la prueba sin vigilar nada)."""
        modules, _findings = pyast.parse_modules(ROOT, EXT, EXT)
        names = {module.name for module in modules}
        self.assertEqual(sorted(HEAVY - names), [])

    def test_bl_registers_the_six_subpackages(self) -> None:
        """RNF-001-03: las raíces de la prueba son ``bl`` y sus seis subpaquetes de registro."""
        modules, _findings = pyast.parse_modules(ROOT, EXT, EXT)
        self.assertEqual(registered_roots(modules),
                         ["bl", "bl.props", "bl.scene", "bl.draw", "bl.gn", "bl.ops", "bl.ui"])

    def test_the_closure_follows_module_level_imports_only(self) -> None:
        """RNF-001-03: un import de nivel de módulo (también de un paquete que contiene al
        módulo) llega al pesado; uno dentro de una función o de ``if TYPE_CHECKING`` no."""
        tree = {
            f"{EXT}/bl/__init__.py": SPDX + "SUBPACKAGES: tuple[str, ...] = ('ops',)\n",
            f"{EXT}/bl/ops/__init__.py": SPDX + "from . import eager, lazy, typed\n",
            f"{EXT}/bl/ops/eager.py": SPDX + "from ...gis.masks import store\n",
            f"{EXT}/bl/ops/lazy.py": SPDX + "def use():\n    from ...gis.masks import access\n",
            f"{EXT}/bl/ops/typed.py": SPDX + (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from ...reserves import compliance\n"),
            f"{EXT}/gis/__init__.py": SPDX,
            f"{EXT}/gis/masks/__init__.py": SPDX + "from . import zones\n",
            f"{EXT}/gis/masks/store.py": SPDX,
            f"{EXT}/gis/masks/access.py": SPDX,
            f"{EXT}/gis/masks/zones.py": SPDX,
            f"{EXT}/reserves/__init__.py": SPDX,
            f"{EXT}/reserves/compliance.py": SPDX,
            f"{EXT}/__init__.py": SPDX,
        }
        heavy = {"gis.masks.store", "gis.masks.access", "gis.masks.zones", "reserves.compliance"}
        with temp_tree(tree) as root:
            modules, findings = pyast.parse_modules(root, EXT, EXT)
        self.assertEqual(findings, [])
        self.assertEqual(
            heavy_reached(modules, heavy),
            ["bl.ops → bl.ops.eager → gis.masks.store",
             "bl.ops → bl.ops.eager → gis.masks → gis.masks.zones"],
        )


if __name__ == "__main__":
    unittest.main()
