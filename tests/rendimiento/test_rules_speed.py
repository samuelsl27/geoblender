# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiempo de las reglas sobre 1 000 ficheros ``.py`` (RNF-001-02; plan 001 §7.1).

Se ejecuta con ``tools/check.py --rendimiento`` (Python de Blender). Genera en ``%TEMP%``
un árbol con la forma de la extensión —raíz, paquetes de dominio, ``adapters``,
``workers`` y ``bl`` con operadores y grupos de propiedades, más el manifiesto y los
``AGENTS.md`` y ``CLAUDE.md`` raíz reales— con 1 000 ficheros ``.py`` de 200 líneas,
limpio para todas las reglas, y mide ``rules.run_all`` en frío (ficheros nuevos: sin la
caché de una pasada anterior).
"""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path

tools_on_path()

from gbtools import manifest, rules  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402

FILES = 1000
LINES = 200
BUDGET_S = 10.0  # RNF-001-02: ≤ 10 s con el Python de Blender
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later"
BPY = "b" + "py"  # el texto del repositorio no contiene imports de Blender fuera de bl/

DOMAIN = (
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
)
BL_SUBPACKAGES = ("props", "scene", "draw", "gn", "ops", "ui")
FOLDERS = (*DOMAIN, *(f"bl/{sub}" for sub in BL_SUBPACKAGES))


def _seconds(value: float) -> str:
    """Segundos con dos decimales y coma decimal (salida en español)."""
    return f"{value:.2f}".replace(".", ",")


def _module(head: list[str]) -> str:
    """Módulo de exactamente ``LINES`` líneas: cabecera, funciones de relleno con un
    bucle (Python puro, usan ``scale``) y comentarios hasta completar."""
    lines = [SPDX, *head]
    index = 0
    while True:
        block = [
            "",
            "",
            f"def step_{index:04d}(value: float, count: int = 8) -> float:",
            f'    """Paso sintético {index}."""',
            "    total = 0.0",
            "    for item in range(count):",
            "        total += (abs(value) + item) ** 0.5 * scale(item)",
            "    return total",
        ]
        if len(lines) + len(block) > LINES:
            break
        lines.extend(block)
        index += 1
    while len(lines) < LINES:
        lines.append(f"# relleno {len(lines) + 1}")
    return "\n".join(lines) + "\n"


def _scale_import(folder: str) -> str:
    """Import relativo de ``core.base.scale`` desde un paquete de ``geoblender/``."""
    if folder == "core":
        return "from .base import scale"
    return "from " + "." * (folder.count("/") + 2) + "core.base import scale"


def _domain_module(folder: str, name: str) -> str:
    return _module(
        [
            f'"""Módulo sintético «{name}» de ``{folder}`` (RNF-001-02)."""',
            "",
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass",
            "",
            _scale_import(folder),
            "",
            "",
            "@dataclass",
            "class Sample:",
            '    """Dato sintético."""',
            "",
            "    name: str",
            "    value: float",
        ]
    )


def _bl_module(folder: str, number: int) -> str:
    operator = f"GEOBLENDER_OT_core_synthetic_{number:04d}"
    group = f"GEOBLENDER_PG_core_synthetic_{number:04d}"
    return _module(
        [
            f'"""Módulo sintético {number} de ``{folder}`` (RNF-001-02)."""',
            "",
            "from __future__ import annotations",
            "",
            f"import {BPY}",
            "",
            _scale_import(folder),
            "",
            "",
            f"class {operator}({BPY}.types.Operator):",
            '    """Operador sintético."""',
            "",
            f'    bl_idname = "geoblender.core_synthetic_{number:04d}"',
            f'    bl_label = "Synthetic {number}"',
            "",
            "    def execute(self, context):",
            '        return {"FINISHED"}',
            "",
            "",
            f"class {group}({BPY}.types.PropertyGroup):",
            '    """Grupo de propiedades sintético con el GeoOrigin en enteros."""',
            "",
            f"    origin_x: {BPY}.props.IntProperty(name='X0')",
            f"    origin_y: {BPY}.props.IntProperty(name='Y0')",
            f"    section_step: {BPY}.props.FloatProperty(name='Paso')",
            "",
            "",
            f"classes = ({operator}, {group})",
        ]
    )


def build_tree(root: Path) -> int:
    """Escribe el árbol sintético bajo ``root`` (UTF-8 y LF); devuelve cuántos ``.py``."""
    files: dict[str, str] = {
        f"{EXT}/__init__.py": _module(
            [
                '"""Raíz sintética: sin imports a nivel de módulo (ARQ-03)."""',
                "",
                "",
                "def register() -> None:",
                "    from . import bl",
                "",
                "    bl.register()",
                "",
                "",
                "def unregister() -> None:",
                "    from . import bl",
                "",
                "    bl.unregister()",
                "",
                "",
                "def scale(value: float) -> float:",
                "    return 2.0 * value",
            ]
        ),
        f"{EXT}/core/base.py": _module(
            [
                '"""Base sintética del núcleo."""',
                "",
                "",
                "def scale(value: float) -> float:",
                '    """Escala sintética."""',
                "    return 2.0 * value",
            ]
        ),
        f"{EXT}/bl/__init__.py": _module(
            [
                '"""Presentación sintética: importa los subpaquetes dentro de funciones."""',
                "",
                "import importlib",
                "",
                "from ..core.base import scale",
                "",
                f"SUBPACKAGES = {BL_SUBPACKAGES!r}",
                "",
                "",
                "def register() -> None:",
                "    for name in SUBPACKAGES:",
                '        importlib.import_module(f".{name}", __package__)',
                "",
                "",
                "def unregister() -> None:",
                "    pass",
            ]
        ),
    }
    for folder in FOLDERS:
        files[f"{EXT}/{folder}/__init__.py"] = _module(
            [f'"""Paquete sintético ``{folder}``."""', "", _scale_import(folder)]
        )
    for number in range(FILES - len(files)):
        folder = FOLDERS[number % len(FOLDERS)]
        name = f"synthetic_{number:04d}"
        if folder.startswith("bl/"):
            text = _bl_module(folder, number)
        else:
            text = _domain_module(folder, name)
        files[f"{EXT}/{folder}/{name}.py"] = text
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    shutil.copy2(ROOT / manifest.MANIFEST_RELPATH, root / manifest.MANIFEST_RELPATH)
    # El AGENTS.md mínimo del código y su puntero (AGT-01 y AGT-03; spec 007, T16).
    for name in ("AGENTS.md", "CLAUDE.md"):
        shutil.copy2(ROOT / name, root / name)
    return len(files)


class RulesSpeedTest(unittest.TestCase):
    def test_1000_files_under_10_s(self) -> None:
        """RNF-001-02: las reglas de §4.3 y §4.4 recorren 1 000 ``.py`` sintéticos de 200
        líneas en ≤ 10 s con el Python de Blender."""
        with tempfile.TemporaryDirectory(prefix="geoblender-rendimiento-") as tmp:
            root = Path(tmp)
            self.assertEqual(build_tree(root), FILES)
            py_files = sorted(root.rglob("*.py"))
            self.assertEqual(len(py_files), FILES)
            for path in py_files:
                self.assertEqual(path.read_bytes().count(b"\n"), LINES, path)
            start = time.perf_counter()
            findings = rules.run_all(root)
            seconds = time.perf_counter() - start
        print(
            f"RNF-001-02: reglas (run_all) sobre {FILES} ficheros .py de {LINES} líneas: "
            f"{_seconds(seconds)} s (presupuesto {_seconds(BUDGET_S)} s)",
            file=sys.stderr,
            flush=True,
        )
        self.assertEqual(findings, [], "\n" + format_findings(findings))
        self.assertLessEqual(seconds, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
