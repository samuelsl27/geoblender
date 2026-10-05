# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiempo de repetir la copia espejo sin cambios sobre 1 000 ficheros (RNF-001-04).

Se ejecuta con ``tools/check.py --rendimiento`` (Python de Blender). La instalación de
desarrollo copia la extensión al perfil aislado con ``gbtools.sync.mirror`` y las
exclusiones del manifiesto (plan 001 §5.4.5 y §5.4.14): aquí se mide esa copia, repetida
sin cambios sobre un árbol de 1 000 ficheros en ``%TEMP%`` (origen y destino locales).
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support.repo import real_manifest, tools_on_path

tools_on_path()

from gbtools import manifest, sync  # noqa: E402

FILES = 1000
BUDGET_S = 3.0  # RNF-001-04: ≤ 3 s y 0 ficheros copiados
FOLDERS = ("core", "gis", "drillholes", "blockmodel", "bl/ops", "bl/ui", "resources/icons")


def _seconds(value: float) -> str:
    """Segundos con dos decimales y coma decimal (salida en español)."""
    return f"{value:.2f}".replace(".", ",")


def build_source(src: Path) -> int:
    """1 000 ficheros (``.py`` de unos 6 KiB y algún PNG) repartidos en carpetas, más
    ficheros que el manifiesto excluye; devuelve cuántos se deben copiar."""
    body = ("# SPDX-License-Identifier: GPL-3.0-or-later\n" + "x = 1\n" * 1000).encode()
    for number in range(FILES):
        folder = src / FOLDERS[number % len(FOLDERS)]
        folder.mkdir(parents=True, exist_ok=True)
        if folder.name == "icons":
            (folder / f"icon_{number:04d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" * 64)
        else:
            (folder / f"module_{number:04d}.py").write_bytes(body)
    for excluded in ("AGENTS.md", "CLAUDE.md", "bl/AGENTS.md", "core/__pycache__/a.pyc"):
        path = src / excluded
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"excluido")
    return FILES


class SyncSpeedTest(unittest.TestCase):
    def test_resync_1000_files_under_3_s(self) -> None:
        """RNF-001-04: repetir la copia de la instalación de desarrollo sin cambios sobre
        1 000 ficheros tarda ≤ 3 s y copia 0 ficheros."""
        exclude = manifest.exclude_patterns(real_manifest())
        with tempfile.TemporaryDirectory(prefix="geoblender-rendimiento-") as tmp:
            src, dst = Path(tmp) / "origen", Path(tmp) / "perfil" / "extension"
            expected = build_source(src)
            start = time.perf_counter()
            first = sync.mirror(src, dst, exclude)
            first_s = time.perf_counter() - start
            start = time.perf_counter()
            second = sync.mirror(src, dst, exclude)
            seconds = time.perf_counter() - start
        print(
            f"RNF-001-04: repetir la copia sin cambios sobre {FILES} ficheros: "
            f"{_seconds(seconds)} s, {len(second.copied)} copiados "
            f"(presupuesto {_seconds(BUDGET_S)} s; primera copia {_seconds(first_s)} s, "
            f"{len(first.copied)} copiados)",
            file=sys.stderr,
            flush=True,
        )
        self.assertEqual(len(first.copied), expected)
        self.assertEqual(second.copied, [])
        self.assertEqual(second.deleted, [])
        self.assertEqual(second.unchanged, expected)
        self.assertLessEqual(seconds, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
