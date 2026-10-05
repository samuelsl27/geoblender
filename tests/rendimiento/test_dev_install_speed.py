# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiempo de repetir la instalación de desarrollo sin cambios sobre 1 000 ficheros
(RNF-001-04; convergencia de la spec 001, T38).

Se ejecuta con ``tools/check.py --rendimiento`` (Python de Blender). Mide la orden real,
``tools/dev_install.py`` (``main``), con el Blender real y un perfil en ``%TEMP%``, sobre
una raíz temporal cuya extensión es la del repositorio más ficheros de relleno hasta
1 000 copiados: la primera ejecución copia y habilita; la segunda, la que se mide, no
debe copiar nada. Complementa a ``test_sync_speed.py``, que mide solo la copia espejo.
"""

import contextlib
import io
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, real_manifest, tools_on_path
from tests.support.resources import skip_reason
from tests.support.trees import child_runner

tools_on_path()

import dev_install  # noqa: E402
from gbtools import blender, manifest, sync  # noqa: E402

FILES = 1000
BUDGET_S = 3.0  # RNF-001-04: ≤ 3 s y 0 ficheros copiados
FILLER_FOLDERS = ("core", "gis", "drillholes", "blockmodel", "design", "plans")
_COPY_LINE = re.compile(r"copia: (\d+) copiados, (\d+) borrados, (\d+) sin cambios")


def _seconds(value: float) -> str:
    """Segundos con dos decimales y coma decimal (salida en español)."""
    return f"{value:.2f}".replace(".", ",")


def build_root(root: Path) -> int:
    """Raíz con el manifiesto y la extensión del repositorio más módulos de relleno (que
    nadie importa) hasta que la copia tenga exactamente :data:`FILES` ficheros; devuelve
    cuántos se deben copiar."""
    extension = root / EXT
    shutil.copytree(
        ROOT / EXT,
        extension,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]"),
    )
    exclude = manifest.exclude_patterns(manifest.load(root / manifest.MANIFEST_RELPATH))
    with tempfile.TemporaryDirectory(prefix="geoblender-rendimiento-") as probe:
        real = len(sync.mirror(extension, Path(probe) / "copia", exclude).copied)
    body = ("# SPDX-License-Identifier: GPL-3.0-or-later\n" + "x = 1\n" * 1000).encode()
    for number in range(FILES - real):
        folder = extension / FILLER_FOLDERS[number % len(FILLER_FOLDERS)]
        (folder / f"relleno_{number:04d}.py").write_bytes(body)
    return FILES


def _install(root: Path, profile: Path, temp: Path) -> tuple[int, str]:
    """``tools/dev_install.py --perfil <perfil>`` sobre ``root``, con su salida; localiza
    Blender como la orden real (``GEOBLENDER_BLENDER`` o la ruta por defecto), y cada
    Blender tiene su carpeta temporal en ``temp`` (convergencia, T61)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = dev_install.main(
            ["--perfil", str(profile)], root=root, runner=child_runner(temp, blender.run)
        )
    return code, out.getvalue()


def _copied(output: str) -> int:
    match = _COPY_LINE.search(output)
    if match is None:
        raise AssertionError(f"la salida no dice cuántos ficheros copió:\n{output}")
    return int(match.group(1))


class DevInstallSpeedTest(unittest.TestCase):
    def test_reinstall_1000_files_under_3_s(self) -> None:
        """RNF-001-04: repetir la instalación de desarrollo (``tools/dev_install.py``,
        con el Blender real y un perfil en ``%TEMP%``) sin cambios sobre 1 000 ficheros
        tarda ≤ 3 s y copia 0 ficheros."""
        minimum = manifest.blender_min(real_manifest())
        try:
            blender.locate_blender(minimum)
        except blender.EnvironmentProblem as exc:
            raise unittest.SkipTest(skip_reason("blender", str(exc))) from None
        with tempfile.TemporaryDirectory(prefix="geoblender-rendimiento-") as tmp:
            root, profile = Path(tmp) / "repo", Path(tmp) / "perfil"
            temp = Path(tmp) / "temporal-de-blender"
            temp.mkdir()
            expected = build_root(root)
            start = time.perf_counter()
            code, first = _install(root, profile, temp)
            first_s = time.perf_counter() - start
            self.assertEqual(code, 0, first)
            start = time.perf_counter()
            code, second = _install(root, profile, temp)
            seconds = time.perf_counter() - start
            self.assertEqual(code, 0, second)
        print(
            f"RNF-001-04: repetir la instalación de desarrollo sin cambios sobre {FILES} "
            f"ficheros: {_seconds(seconds)} s, {_copied(second)} copiados (presupuesto "
            f"{_seconds(BUDGET_S)} s; primera {_seconds(first_s)} s, {_copied(first)} "
            "copiados)",
            file=sys.stderr,
            flush=True,
        )
        self.assertEqual(_copied(first), expected)
        self.assertEqual(_copied(second), 0, second)
        self.assertLessEqual(seconds, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
