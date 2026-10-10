# SPDX-License-Identifier: GPL-3.0-or-later
"""Dirección de las dependencias dentro de la extensión (RF-001-14; ADR-0004).

- ARQ-02: nada importa ``bl`` salvo el ``__init__.py`` raíz dentro de ``register()`` y
  ``unregister()``.
- ARQ-06: ``core`` solo importa ``core``; ``jobs``, ``core`` y ``jobs``.
- ARQ-07: un paquete de dominio solo importa paquetes de nivel menor; de ``adapters``,
  solo ``adapters.registry`` dentro de una función; nunca ``workers``. ``bl`` no importa
  ``adapters`` ni ``workers``.
- ARQ-08: sin ciclos de imports a nivel de módulo.
- ARQ-10: ``adapters`` solo importa ``core`` y módulos ``ports``; un ``ports.py``, solo
  ``core``; ``adapters/registry.py`` importa sus hermanos solo dentro de funciones.
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import imports  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


def _findings(files: dict[str, str]):
    tree = {f"{EXT}/{rel}": SPDX + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        return imports.check_dependency_direction(root)


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    prefix = f"{EXT}/"
    return [(f.path.removeprefix(prefix), f.line, f.rule) for f in _findings(files)]


class LayerTest(unittest.TestCase):
    def test_domain_imports_bl(self) -> None:
        """RF-001-14 / ARQ-02: el dominio, ``workers`` o ``core`` importando ``bl``."""
        found = _found(
            {
                "gis/grid.py": "from ..bl import ui\n",
                "core/a.py": "def f():\n    from .. import bl\n",
                "workers/run.py": "from ..bl.ops import core\n",
                "bl/ops/core.py": "from .. import compat\nfrom ...core import units\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("core/a.py", 3, "ARQ-02"),
                ("gis/grid.py", 2, "ARQ-02"),
                ("workers/run.py", 2, "ARQ-02"),
            ],
        )

    def test_root_imports_bl_inside_register(self) -> None:
        """RF-001-14 / ARQ-02: el ``__init__.py`` raíz importa ``bl`` solo dentro de
        ``register()`` y ``unregister()``."""
        good = {
            "__init__.py": (
                "def register():\n    from . import bl\n    bl.register()\n"
                "def unregister():\n    from .bl import unregister as u\n    u()\n"
            ),
        }
        self.assertEqual(_found(good), [])
        bad = {
            "__init__.py": (
                "from . import bl\n"
                "def helper():\n    from . import bl\n"
                "class Addon:\n    def register(self):\n        from . import bl\n"
            ),
        }
        self.assertEqual(
            _found(bad),
            [("__init__.py", 2, "ARQ-02"), ("__init__.py", 4, "ARQ-02"),
             ("__init__.py", 7, "ARQ-02")],
        )

    def test_core_imports_gis(self) -> None:
        """RF-001-14 / ARQ-06: ``core`` solo importa ``core``; ``jobs``, también
        ``jobs``."""
        found = _found(
            {
                "core/a.py": "from ..gis import grid\nfrom . import b\n",
                "core/b.py": "def f():\n    from .. import jobs\n",
                "jobs/runner.py": "from ..core import units\nfrom . import protocol\n",
                "jobs/protocol.py": "from ..drillholes import model\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("core/a.py", 2, "ARQ-06"),
                ("core/b.py", 3, "ARQ-06"),
                ("jobs/protocol.py", 2, "ARQ-06"),
            ],
        )

    def test_levels(self) -> None:
        """RF-001-14 / ARQ-07: solo paquetes de nivel menor; nunca ``workers``; ``bl``
        sin ``adapters`` ni ``workers``."""
        self.assertEqual(
            imports.LEVELS,
            {
                "core": 0, "jobs": 1, "gis": 2, "drillholes": 3, "geomodel": 4,
                "implicit": 5, "blockmodel": 6, "pitopt": 7, "design": 8,
                "reserves": 9, "interop": 10, "plans": 11,
            },
        )
        found = _found(
            {
                "gis/grid.py": "from ..design import pit\nfrom ..jobs import runner\n",
                "design/pit.py": (
                    "from ..gis import contours\nfrom ..core import units\n"
                ),
                "drillholes/model.py": "from ..geomodel import units\n",
                "plans/sheet.py": (
                    "from ..interop import dxf\nfrom ..reserves import r\n"
                ),
                "reserves/r.py": "from . import balance\nfrom ..plans import legend\n",
                "geomodel/s.py": "from ..workers import run\n",
                "bl/ops/gis.py": "from ...adapters import registry\n",
                "bl/ui/menu.py": (
                    "from ...workers import run\nfrom ...gis import grid\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                ("bl/ops/gis.py", 2, "ARQ-07"),
                ("bl/ui/menu.py", 2, "ARQ-07"),
                ("drillholes/model.py", 2, "ARQ-07"),
                ("geomodel/s.py", 2, "ARQ-07"),
                ("gis/grid.py", 2, "ARQ-07"),
                ("reserves/r.py", 3, "ARQ-07"),
            ],
        )

    def test_registry_only_in_function(self) -> None:
        """RF-001-14 / ARQ-07: el dominio importa de ``adapters`` solo
        ``adapters.registry`` y solo dentro de una función."""
        found = _found(
            {
                "gis/crs.py": (
                    "from ..adapters import registry\n"
                    "def service():\n"
                    "    from ..adapters import registry\n"
                    "    from ..adapters.registry import resolve\n"
                    "    from ..adapters import pyproj_crs\n"
                    "    return registry\n"
                ),
            }
        )
        self.assertEqual(
            found, [("gis/crs.py", 2, "ARQ-07"), ("gis/crs.py", 6, "ARQ-07")]
        )


class AdaptersTest(unittest.TestCase):
    def test_adapters_only_core_and_ports(self) -> None:
        """RF-001-14 / ARQ-10: ``adapters`` solo importa ``core`` y módulos
        ``ports``; un ``ports.py`` solo importa ``core``."""
        found = _found(
            {
                "adapters/pyproj_crs.py": (
                    "from ..core import errors\n"
                    "from ..gis.ports import CrsService\n"
                    "from ..gis import ports\n"
                    "from ..gis import grid\n"
                    "from . import duckdb_store\n"
                ),
                "gis/ports.py": "from ..core import units\nfrom . import grid\n",
                "drillholes/ports.py": "from ..gis import ports\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("adapters/pyproj_crs.py", 5, "ARQ-10"),
                ("adapters/pyproj_crs.py", 6, "ARQ-10"),
                ("drillholes/ports.py", 2, "ARQ-10"),
                ("gis/ports.py", 3, "ARQ-10"),
            ],
        )

    def test_adapters_registry_siblings_in_function(self) -> None:
        """RF-001-14 / ARQ-10: ``adapters/registry.py`` importa sus hermanos solo
        dentro de funciones; ningún otro adaptador importa a sus hermanos."""
        found = _found(
            {
                "adapters/registry.py": (
                    "from ..core import errors\n"
                    "from . import duckdb_store\n"
                    "def resolve(name):\n"
                    "    from . import pyproj_crs\n"
                    "    return pyproj_crs\n"
                ),
                "adapters/duckdb_store.py": "def f():\n    from . import pyproj_crs\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("adapters/duckdb_store.py", 3, "ARQ-10"),
                ("adapters/registry.py", 3, "ARQ-10"),
            ],
        )


class CycleTest(unittest.TestCase):
    def test_cycle_detected(self) -> None:
        """RF-001-14 / ARQ-08: un ciclo ``a`` → ``b`` → ``a`` a nivel de módulo, y uno
        de tres, se informan una vez con el ciclo completo."""
        findings = _findings(
            {
                "core/a.py": "from . import b\n",
                "core/b.py": "import os\nfrom .a import thing\n",
                "gis/x.py": "from . import y\n",
                "gis/y.py": "from . import z\n",
                "gis/z.py": "from .x import f\n",
            }
        )
        self.assertEqual(
            [(f.path, f.line, f.rule) for f in findings],
            [
                (f"{EXT}/core/a.py", 2, "ARQ-08"),
                (f"{EXT}/gis/x.py", 2, "ARQ-08"),
            ],
        )
        self.assertIn("core.a → core.b → core.a", findings[0].message)
        self.assertIn("gis.x → gis.y → gis.z → gis.x", findings[1].message)

    def test_deferred_imports_are_not_cycles(self) -> None:
        """RF-001-14 / ARQ-08: lo importado dentro de funciones o de ``TYPE_CHECKING``
        no forma ciclos, ni un paquete que importa sus submódulos."""
        found = _found(
            {
                "core/c.py": "from . import d\n",
                "core/d.py": "def f():\n    from . import c\n",
                "core/e.py": (
                    "from typing import TYPE_CHECKING\n"
                    "from . import c\n"
                    "if TYPE_CHECKING:\n    from . import e2\n"
                ),
                "core/e2.py": "from . import e\n",
                "bl/__init__.py": "from . import props, ui\n",
                "bl/props/__init__.py": "from . import preferences\n",
                "bl/props/preferences.py": (
                    "from .. import compat\nfrom ... import core\n"
                ),
                "bl/ui/__init__.py": "from .. import props\n",
                "bl/compat.py": "",
            }
        )
        self.assertEqual(found, [])

    def test_package_cycle_through_init(self) -> None:
        """RF-001-14 / ARQ-08: un módulo que importa un nombre del ``__init__`` de su
        paquete mientras ese ``__init__`` lo importa a él es un ciclo."""
        findings = _findings(
            {
                "gis/__init__.py": "from .grid import Grid\nSTEP = 1.0\n",
                "gis/grid.py": "from . import STEP\nclass Grid: pass\n",
            }
        )
        self.assertEqual([(f.path, f.rule) for f in findings],
                         [(f"{EXT}/gis/__init__.py", "ARQ-08")])
        self.assertIn("gis → gis.grid → gis", findings[0].message)


class RealTreeTest(unittest.TestCase):
    def test_real_tree(self) -> None:
        """RF-001-14 / ARQ-02, 06, 07, 08 y 10: la extensión real cumple, incluido el
        ``register()`` raíz que importa ``bl``."""
        root_init = (ROOT / EXT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("from . import bl", root_init)
        findings = imports.check_dependency_direction(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()
