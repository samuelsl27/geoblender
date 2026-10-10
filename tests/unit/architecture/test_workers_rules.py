# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de imports de los trabajos en segundo plano (spec 004, T16; RF-004-14; plan 004
§5.1 y §6; ADR-0004 R5 y R6).

- ARQ-11: un módulo de ``workers/`` no importa ``bl``, ``core.project`` ni el adaptador de
  escritura de DuckDB (``adapters.duckdb_store``): ni de forma relativa, ni absoluta (como
  ``workers/_bootstrap.py``, que carga ``geoblender`` por ruta), ni dinámica con un nombre
  literal. Un worker no puede escribir el proyecto: solo lo escribe Blender (principio 7).
- ``jobs/`` no importa ningún paquete de dominio ni ``workers/`` (ARQ-06; de forma absoluta,
  ARQ-09): el ejecutor en hilo llama a ``WorkerInfo.run`` sin importar el dominio.
- ``workers/_bootstrap.py`` es la única excepción de ARQ-09, y solo tras cargar el paquete
  por ruta: a nivel de módulo importa solo la biblioteca estándar (lo de ``geoblender`` y
  numpy, dentro de funciones).

Cada regla se rompe a propósito en un árbol sintético, también sobre una copia de los
ficheros reales (falla), y se deshace (pasa); el árbol real cumple.
"""

import sys
import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import FAMILIES, imports, platform, pyast  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
BOOTSTRAP = "workers/_bootstrap.py"
# Un import que rompe ARQ-11 en un worker (también lo señala ARQ-02, que no se mira aquí).
FORBIDDEN_LINE = "from ..core import project\n"


def _tree(files: dict[str, str]) -> dict[str, str]:
    return {f"{EXT}/{rel}": SPDX + text for rel, text in files.items()}


def _workers(files: dict[str, str]) -> list[tuple[str, int, str]]:
    """Los incumplimientos de ``imports.check_workers`` (rutas relativas a la extensión)."""
    with temp_tree(_tree(files)) as root:
        findings = imports.check_workers(root)
    prefix = f"{EXT}/"
    return [(f.path.removeprefix(prefix), f.line, f.rule) for f in findings]


def _real(rel: str) -> str:
    """El texto de un fichero real de la extensión (``rel``, relativo a ella), sin la
    cabecera SPDX (``_tree`` la vuelve a poner)."""
    text = (ROOT / EXT / rel).read_text(encoding="utf-8")
    return text.removeprefix(SPDX)


def _real_workers() -> dict[str, str]:
    """Los ``.py`` reales de ``workers/``, sin la cabecera."""
    folder = ROOT / EXT / "workers"
    return {f"workers/{path.name}": _real(f"workers/{path.name}")
            for path in sorted(folder.glob("*.py"))}


class WorkersRuleTest(unittest.TestCase):
    def test_forbidden_relative_imports(self) -> None:
        """RF-004-14 / ARQ-11: un worker que importa ``bl``, ``core.project`` (o algo
        suyo) o el adaptador de escritura de DuckDB falla, también dentro de una función o
        de ``TYPE_CHECKING``; ``core`` y ``jobs``, ``adapters.registry``, un dominio o un
        nombre que solo empieza igual (``core.projection``), no."""
        found = _workers(
            {
                "workers/estimate.py": (
                    "from typing import TYPE_CHECKING\n"
                    "from ..bl import ui\n"
                    "from .. import bl\n"
                    "from ..core import project\n"
                    "from ..core.project.session import Project\n"
                    "from ..adapters import duckdb_store\n"
                    "def run(ctx):\n"
                    "    from ..adapters.duckdb_store import BlockStore\n"
                    "    return BlockStore\n"
                    "if TYPE_CHECKING:\n"
                    "    from ..core.project import open\n"
                    "from ..core import projection, units\n"
                    "from ..core.gpkg import wkb\n"
                    "from ..jobs import worker_api\n"
                    "from ..drillholes import model\n"
                    "from ..adapters import registry\n"
                ),
            }
        )
        rel = "workers/estimate.py"
        self.assertEqual(
            found, [(rel, line, "ARQ-11") for line in (3, 4, 5, 6, 7, 9, 12)]
        )

    def test_forbidden_absolute_and_dynamic_imports(self) -> None:
        """RF-004-14 / ARQ-11: también con el nombre absoluto (``geoblender.…``,
        ``bl_ext.<repo>.geoblender.…`` o el paquete suelto) y con ``import_module`` de un
        nombre literal; ``geoblender.jobs`` no."""
        found = _workers(
            {
                BOOTSTRAP: (
                    "import importlib\n"
                    "def run_job():\n"
                    "    from geoblender.jobs import protocol\n"
                    "    from geoblender import bl\n"
                    "    import geoblender.core.project\n"
                    "    from geoblender.adapters.duckdb_store import BlockStore\n"
                    '    importlib.import_module("geoblender.bl.ops")\n'
                    "    import bl_ext.user_default.geoblender.core.project.session\n"
                    "    return protocol, BlockStore\n"
                ),
                "workers/lp.py": "from core.project import session\n",
            }
        )
        self.assertEqual(
            found,
            [(BOOTSTRAP, line, "ARQ-11") for line in (5, 6, 7, 8, 9)]
            + [("workers/lp.py", 2, "ARQ-11")],
        )

    def test_only_workers(self) -> None:
        """RF-004-14 / ARQ-11: la regla es de ``workers/``: lo mismo en ``jobs/``, en un
        dominio o en ``bl/`` no es ARQ-11 (lo miran ARQ-02, ARQ-06 y ARQ-07)."""
        same = FORBIDDEN_LINE + "from ..adapters import duckdb_store\n"
        found = _workers(
            {
                "jobs/runner.py": same,
                "blockmodel/store.py": same,
                "bl/ops/jobs.py": "from ...core import project\n",
            }
        )
        self.assertEqual(found, [])

    def test_break_and_restore_real_workers(self) -> None:
        """RF-004-14 / ARQ-11: los workers reales cumplen; con un import de
        ``core.project`` añadido a ``workers/selftest.py`` falla en esa línea, y al
        quitarlo vuelve a cumplir."""
        files = _real_workers()
        self.assertIn("workers/selftest.py", files)
        self.assertIn(BOOTSTRAP, files)
        self.assertEqual(_workers(files), [])
        original = files["workers/selftest.py"]
        broken = dict(files)
        broken["workers/selftest.py"] = original + FORBIDDEN_LINE
        line = (SPDX + broken["workers/selftest.py"]).count("\n")
        self.assertEqual(_workers(broken), [("workers/selftest.py", line, "ARQ-11")])
        self.assertEqual(_workers(dict(files)), [])

    def test_forbidden_list(self) -> None:
        """RF-004-14 / ARQ-11: lo prohibido a los workers es exactamente ``bl``,
        ``core.project`` y ``adapters.duckdb_store`` (vision-general §9)."""
        self.assertEqual(
            imports.WORKERS_FORBIDDEN, ("bl", "core.project", "adapters.duckdb_store")
        )


class BootstrapTest(unittest.TestCase):
    def test_bootstrap_stdlib_before_loading(self) -> None:
        """RF-004-14 / ARQ-09: a nivel de módulo, ``workers/_bootstrap.py`` solo importa
        la biblioteca estándar (y ``__future__``); numpy o ``geoblender`` fallan, también
        dinámicos o en un ``try``; dentro de una función o de ``TYPE_CHECKING``, no."""
        found = _workers(
            {
                BOOTSTRAP: (
                    "from __future__ import annotations\n"
                    "import sys\n"
                    "import importlib.util\n"
                    "from typing import TYPE_CHECKING\n"
                    "import numpy\n"
                    "import geoblender\n"
                    "try:\n"
                    "    from geoblender.jobs import protocol\n"
                    "except ImportError:\n"
                    "    protocol = None\n"
                    'importlib.import_module("numpy.linalg")\n'
                    "if TYPE_CHECKING:\n"
                    "    from geoblender.jobs.paths import JobDir\n"
                    "def run_job():\n"
                    "    import numpy as np\n"
                    "    from geoblender.jobs import worker_api\n"
                    "    return np, worker_api\n"
                ),
                "workers/selftest.py": "import numpy\nfrom ..jobs.selftest import run\n",
            }
        )
        self.assertEqual(found, [(BOOTSTRAP, line, "ARQ-09") for line in (6, 7, 9, 12)])

    def test_break_and_restore_real_bootstrap(self) -> None:
        """RF-004-14 / ARQ-09: el arranque real cumple; con ``import numpy`` a nivel de
        módulo, antes de cargar el paquete, falla, y al quitarlo vuelve a cumplir."""
        original = _real(BOOTSTRAP)
        anchor = "\nimport argparse"
        self.assertIn(anchor, original)
        self.assertEqual(_workers({BOOTSTRAP: original}), [])
        broken = original.replace(anchor, "\nimport numpy" + anchor, 1)
        line = (SPDX + broken.split("\nimport numpy")[0]).count("\n") + 2
        self.assertEqual(_workers({BOOTSTRAP: broken}), [(BOOTSTRAP, line, "ARQ-09")])
        self.assertEqual(_workers({BOOTSTRAP: original}), [])

    def test_only_exception_of_arq09(self) -> None:
        """RF-004-14 / ARQ-09: ``workers/_bootstrap.py`` es la única excepción: el mismo
        import absoluto en otro worker o en ``jobs/`` falla, y en el árbol real es el
        único fichero de la extensión con imports absolutos de Geoblender."""
        self.assertEqual(platform.ARQ09_ALLOWED, (BOOTSTRAP,))
        self.assertEqual(imports.BOOTSTRAP_MODULE, "workers._bootstrap")
        code = "def main():\n    import geoblender.jobs\n"
        with temp_tree(
            _tree({BOOTSTRAP: code, "workers/selftest.py": code, "jobs/inprocess.py": code})
        ) as root:
            found = [(f.path.removeprefix(f"{EXT}/"), f.line, f.rule)
                     for f in platform.check(root, environ={}) if f.rule == "ARQ-09"]
        self.assertEqual(
            found, [("jobs/inprocess.py", 3, "ARQ-09"), ("workers/selftest.py", 3, "ARQ-09")]
        )
        modules, problems = pyast.parse_modules(ROOT, EXT, EXT)
        self.assertEqual(problems, [])
        absolute = sorted(
            module.rel.removeprefix(f"{EXT}/")
            for module in modules
            if any(not ref.relative_level and imports.is_internal(ref.top)
                   for ref in pyast.iter_imports(module))
        )
        self.assertEqual(absolute, [BOOTSTRAP])


class JobsImportsTest(unittest.TestCase):
    def test_jobs_imports_no_domain_nor_workers(self) -> None:
        """RF-004-14 / ARQ-06 y ARQ-09: ``jobs/`` no importa ``workers/`` ni un paquete
        de dominio, ni relativo (también dentro de una función) ni absoluto (también
        dinámico de nombre literal); ``core``, ``jobs`` y numpy, sí."""
        with temp_tree(
            _tree(
                {
                    "jobs/inprocess.py": (
                        "import importlib\n"
                        "import numpy\n"
                        "from ..core import units\n"
                        "from . import catalog\n"
                        "from ..workers import selftest\n"
                        "from .. import workers\n"
                        "from ..gis import grid\n"
                        "def run(name):\n"
                        "    from ..drillholes import model\n"
                        "    return model\n"
                        "import geoblender.workers.selftest\n"
                        'importlib.import_module("geoblender.workers.selftest")\n'
                    ),
                }
            )
        ) as root:
            findings = imports.check(root) + platform.check(root, environ={})
        found = sorted(
            (f.line, f.rule) for f in findings if f.path == f"{EXT}/jobs/inprocess.py"
        )
        self.assertEqual(
            found,
            [(6, "ARQ-06"), (7, "ARQ-06"), (8, "ARQ-06"), (10, "ARQ-06"),
             (12, "ARQ-09"), (13, "ARQ-09")],
        )

    def test_real_jobs_imports(self) -> None:
        """RF-004-14 / ARQ-06: en el árbol real, ``jobs/`` solo importa ``core``,
        ``jobs``, la biblioteca estándar y numpy."""
        modules, problems = pyast.parse_modules(ROOT, EXT, EXT)
        self.assertEqual(problems, [])
        jobs = [m for m in modules if m.name == "jobs" or m.name.startswith("jobs.")]
        self.assertGreater(len(jobs), 10)
        allowed_absolute = set(sys.stdlib_module_names) | {"numpy"}
        wrong = [
            f"{module.rel}:{ref.line} {ref.target}"
            for module in jobs
            for ref in pyast.iter_imports(module)
            if (ref.top not in ("core", "jobs") if ref.relative_level
                else ref.top not in allowed_absolute)
        ]
        self.assertEqual(wrong, [])


class FamilyTest(unittest.TestCase):
    def test_in_imports_family(self) -> None:
        """RF-004-14 / ARQ-11: la regla está en la familia ``imports`` de ``FAMILIES``
        (la ejecuta ``tools/check.py``): ``imports.check`` la informa."""
        self.assertIs(FAMILIES["imports"], imports.check)
        with temp_tree(_tree({"workers/estimate.py": FORBIDDEN_LINE})) as root:
            rules = {(f.path, f.line, f.rule) for f in imports.check(root)}
        self.assertIn((f"{EXT}/workers/estimate.py", 2, "ARQ-11"), rules)

    def test_real_tree(self) -> None:
        """RF-004-14 / ARQ-11 y ARQ-09: los workers y el arranque reales cumplen."""
        findings = imports.check_workers(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()
