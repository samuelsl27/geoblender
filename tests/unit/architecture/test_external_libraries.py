# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-04, ARQ-05 y HER-01: librerías externas solo en adaptadores (RF-001-13).

- ARQ-04: fuera de ``geoblender/adapters/``, solo biblioteca estándar y numpy.
- ARQ-05: en ``adapters/``, cada librería la importa solo su módulo dueño
  (``ADAPTER_OWNERS``, vacía en esta spec).
- HER-01: ``tools/`` (salvo los guiones que se ejecutan dentro de Blender) solo importa
  biblioteca estándar, ``gbtools``, sus scripts hermanos y ``geoblender`` cargado por
  ruta con ``gbtools.package.load_geoblender`` (nunca ``geoblender.bl``).
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import imports  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
BPY = "b" + "py"


def _found(
    files: dict[str, str], owners: dict[str, str] | None = None
) -> list[tuple[str, int, str]]:
    tree = {rel: SPDX + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        if owners is None:
            findings = imports.check_external_libraries(root)
        else:
            findings = imports.check_external_libraries(root, adapter_owners=owners)
    return [(f.path, f.line, f.rule) for f in findings]


class ExternalLibrariesTest(unittest.TestCase):
    def test_external_outside_adapters(self) -> None:
        """RF-001-13 / ARQ-04: ``import duckdb`` u otra externa fuera de adapters/."""
        found = _found(
            {
                f"{EXT}/gis/grid.py": "import duckdb\n",
                f"{EXT}/design/pit.py": "from shapely.geometry import Point\n",
                f"{EXT}/bl/ops/gis.py": "def f():\n    import requests\n",
                f"{EXT}/core/crs.py": (
                    'import importlib\nimportlib.import_module("pyproj")\n'
                ),
                f"{EXT}/workers/run.py": "import scipy.optimize\n",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/bl/ops/gis.py", 3, "ARQ-04"),
                (f"{EXT}/core/crs.py", 3, "ARQ-04"),
                (f"{EXT}/design/pit.py", 2, "ARQ-04"),
                (f"{EXT}/gis/grid.py", 2, "ARQ-04"),
                (f"{EXT}/workers/run.py", 2, "ARQ-04"),
            ],
        )

    def test_unregistered_adapter_library(self) -> None:
        """RF-001-13 / ARQ-05: en ``adapters/``, una librería sin dueño registrado o
        importada desde un módulo que no es su dueño."""
        files = {
            f"{EXT}/adapters/duckdb_store.py": "import duckdb\n",
            f"{EXT}/adapters/other.py": "from duckdb import connect\n",
            f"{EXT}/adapters/gempy_2025/__init__.py": "",
            f"{EXT}/adapters/gempy_2025/engine.py": "import gempy\n",
        }
        self.assertEqual(imports.ADAPTER_OWNERS, {})
        self.assertEqual(
            _found(files),
            [
                (f"{EXT}/adapters/duckdb_store.py", 2, "ARQ-05"),
                (f"{EXT}/adapters/gempy_2025/engine.py", 2, "ARQ-05"),
                (f"{EXT}/adapters/other.py", 2, "ARQ-05"),
            ],
        )
        owners = {"duckdb": "adapters.duckdb_store", "gempy": "adapters.gempy_2025"}
        self.assertEqual(
            _found(files, owners), [(f"{EXT}/adapters/other.py", 2, "ARQ-05")]
        )

    def test_numpy_allowed(self) -> None:
        """RF-001-13 / ARQ-04: numpy y la biblioteca estándar valen fuera de
        ``adapters/``; las referencias a Geoblender o a Blender no son ARQ-04."""
        found = _found(
            {
                f"{EXT}/core/units.py": (
                    "from __future__ import annotations\n"
                    "import numpy as np\n"
                    "from numpy.typing import NDArray\n"
                    "import os, sqlite3, tomllib, concurrent.futures\n"
                    "from . import errors\n"
                ),
                f"{EXT}/gis/grid.py": "import numpy\nfrom ..core import units\n",
                f"{EXT}/bl/ops/core.py": f"import {BPY}\n",
                f"{EXT}/workers/_bootstrap.py": "import geoblender\n",
            }
        )
        self.assertEqual(found, [])

    def test_tools_stdlib_only(self) -> None:
        """RF-001-13 / HER-01: ``tools/`` solo importa biblioteca estándar, ``gbtools``
        y sus scripts hermanos; ``tools/inblender/`` y el lanzador, aparte."""
        found = _found(
            {
                "tools/check.py": (
                    "import os, subprocess\n"
                    "import gbtools.findings\n"
                    "from gbtools.rules import imports\n"
                    "import check_licenses\n"
                    "import duckdb\n"
                ),
                "tools/check_licenses.py": "import tomllib\n",
                "tools/gbtools/wheels.py": "import numpy\nfrom . import findings\n",
                "tools/build.py": "import fetch_wheels\nimport yaml\n",
                "tools/inblender/render.py": "import duckdb\n",
                "tools/run_blender_tests.py": "import tests.support.blender_ext\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("tools/build.py", 2, "HER-01"),
                ("tools/build.py", 3, "HER-01"),
                ("tools/check.py", 6, "HER-01"),
                ("tools/gbtools/wheels.py", 2, "HER-01"),
            ],
        )

    def test_tools_geoblender_by_path_ok(self) -> None:
        """RF-001-13 / HER-01: ``geoblender`` vale en ``tools/`` si se carga por ruta
        con ``load_geoblender``; ``geoblender.bl``, nunca."""
        loader = "from gbtools.package import load_geoblender\nload_geoblender(ROOT)\n"
        found = _found(
            {
                "tools/sdd.py": loader + "from geoblender.core import units\n",
                "tools/catalog.py": (
                    "import gbtools.package\n"
                    "def main():\n"
                    "    gbtools.package.load_geoblender(ROOT)\n"
                    "    import geoblender.interop\n"
                ),
                "tools/ui_dump.py": loader + "from geoblender.bl import ops\n",
                "tools/raw.py": "from geoblender import core\n",
            }
        )
        self.assertEqual(
            found, [("tools/raw.py", 2, "HER-01"), ("tools/ui_dump.py", 4, "HER-01")]
        )

    def test_real_tree(self) -> None:
        """RF-001-13 / ARQ-04, ARQ-05 y HER-01: el repositorio real cumple."""
        findings = imports.check_external_libraries(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()
