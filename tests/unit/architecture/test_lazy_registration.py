# SPDX-License-Identifier: GPL-3.0-or-later
"""Habilitar Geoblender no carga el cálculo de la 012 (spec 012, T38; RNF-001-03 de la spec 001;
plan 012 §7.4; principio 8).

Habilitar la extensión en Blender 5.2.1 en segundo plano tarda ≤ 0,57 s (RNF-001-03). Las
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
    # La retirada de un acopio de la 016 (spec 016, T17 y T18): la transición y lo que se apoyaba (lee el almacén y las superficies).
    "design.removal",
    # El almacén de la retirada (spec 016, T20; el patrón de T25 y T27): preparar, calcular, crear, recalcular y reproducir.
    "design.supported_store",
    # El cálculo del contrafuerte y del cuerpo apoyado de la 016 (spec 016, T23 a T27 y T51): el espesor, el contrafuerte, el borde
    # de lo apoyado y la morfología. Ya eran perezosos; lo fija la prueba para que no vuelvan a cargarse al habilitar (RNF-001-03:
    # la 016 subió el habilitado de 0,487 s a 0,512 s con sus declaraciones y sus familias, y no con estos).
    "design.thickness", "design.buttress", "design.supported_edge", "design.morphology",
    # Las seis peticiones de la 016 (spec 016, T51): 4,2 ms de dataclasses que habilitar no necesita;
    # ``design.model`` las ofrece con su nombre de siempre al pedirlas (``__getattr__``).
    "design.supported_requests",
    # El perfil de pista de la 017 (spec 017, T04): la tabla, la edición de los perfiles y sus derivados; ``provenance`` declara
    # la operación (``des.edit_road_profiles``) y este módulo se importa al usarlo (RNF-001-03, RNF-017-10).
    "design.road_profiles",
    # Los datos de la pista y de la accesibilidad de la 017 (spec 017, T05): las peticiones, los trabajos y los resultados
    # (``@dataclass``, ≈ 0,5–1 ms cada uno al importar) los pide quien calcula; no los carga ``design.model`` ni el arranque.
    "design.road_model",
    # La malla, los 16 rumbos y la red 2D de la ruta de la 017 (spec 017, T06; Dijkstra con ``heapq``, plan §9): los pide quien traza
    # una pista; ``design.model`` y el arranque no los importan.
    "design.road_net",
    # La ruta 3D de mínimo coste de la 017 (spec 017, T07; A* con ``heapq``, plan §9): la pide quien traza una pista; ``design.model`` y el
    # arranque no la importan.
    "design.road_route",
    # El eje con curvas circulares de la 017 (spec 017, T10; Douglas–Peucker y arcos con numpy): lo pide quien forma el eje de una pista;
    # ``design.model`` y el arranque no lo importan.
    "design.road_axis",
    # La rasante acotada de la 017 (spec 017, T11; ``minimum.accumulate`` con numpy): la pide quien da la rasante a un eje; ``design.model`` y el
    # arranque no la importan.
    "design.road_gradient",
    # La sección tipo de la 017 (spec 017, T12; huella, lados y cotas con numpy): la pide quien calcula una pista; ``design.model`` y el arranque no la importan.
    "design.road_section",
    # El grabado de la sección y su borde con dos ángulos de la 017 (spec 017, T13; envolventes y alcance de la 013, copia de ``platform._edge_units``): lo pide quien
    # calcula una pista; ``design.model`` y el arranque no lo importan.
    "design.road_engrave",
    # Lo alcanzable y las cotas de la accesibilidad de la 017 (spec 017, T15; pendiente local, apertura y componentes con numpy): lo pide quien calcula la accesibilidad;
    # ``design.model`` y el arranque no lo importan.
    "design.road_access",
    # La operación de accesibilidad de la 017 (spec 017, T17): preparar, calcular por pasos y el resumen (lee el almacén, las superficies y las máscaras); la piden las
    # órdenes al usarla, no habilitar.
    "design.access_store",
    # Preparar la pista de la 017 (spec 017, T19; lee el almacén, las superficies, las máscaras y las capas): la piden las órdenes al usarla, no habilitar.
    "design.road_store",
    # La capa de ejes de pistas de la 017 (spec 017, T26): el formato de ``des_rax_<vNN>``, lo que lee el almacén y la operación; ``provenance`` declara la operación
    # (``des.road_layer``) y ``design.store`` la importa al escribirla; ``design.entity_store`` solo si la versión tiene pistas.
    "design.road_layer",
    # Lo que la barra N lee de una pista y de una accesibilidad (spec 017, T31b; importa ``road_store`` y ``access_store``): la barra N lo importa al usarla, no habilitar.
    "design.road_card",
    # Los datos de la corta de la 018 (spec 018, T05): las peticiones, el trabajo y el resultado; los pide quien calcula, no habilitar.
    "design.pit_model",
    # La distancia por arista de la corta y su desfase (spec 018, T08): lo pide quien calcula, no habilitar.
    "design.pit_offset",
    # Los bancos de la corta ascendente (spec 018, T10): lo pide quien calcula, no habilitar.
    "design.pit_bench",
    # La rampa en espiral de la corta (spec 018, T15): lo pide quien calcula, no habilitar.
    "design.pit_ramp",
    # La superficie de la corta en la rejilla (spec 018, T18): lo pide quien calcula, no habilitar.
    "design.pit_surface",
    "design.pit_sky",
    "design.pit_store",
    # Los hallazgos, las cifras y el contraste con la 013 de la corta (spec 018, T20).
    "design.pit_report",
    "design.pit_check013",
    # Lo que la barra N lee de una corta (spec 018, T34): la barra N lo importa al usarla, no habilitar.
    "design.pit_card",
    # El aspecto de los elementos de la 019 (spec 019, T02): el catálogo, los predefinidos y la validación; los pide el panel
    # del elemento al usarlo, no habilitar (RNF-001-03, RNF-019-04).
    "core.appearance.catalog", "core.appearance.merge", "core.appearance.model",
    # La cola de avisos con caducidad (spec 019, T05): la usa la barra de estado al avisar, no habilitar.
    "core.notices",
})
"""Los módulos de la 012, la 013, la 015, la 016 y la 017 (y la cadena que arrastran) que se importan al primer uso."""


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
