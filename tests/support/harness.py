# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas del arnés con el Blender real (plan 001 §7.1).

Las comparten ``tests/unit/tools/test_harness_blender.py`` (lo que solo simula, o lanza
el Python de Blender) y ``tests/arnes/test_harness_blender.py`` (lo que lanza
``blender.exe``: el paso «arnés» de ``tools/check.py --completo``; spec 001 0.6, D-9 de
la spec 002, T48): los textos de las pruebas que se escriben en carpetas temporales, el
localizador que omite con el recurso ``blender`` si no hay un Blender 5.2, el lanzamiento
de un guion en Blender con un perfil temporal y una carpeta temporal propia de cada hijo
(convergencia de la spec 001, T61), el listado de una carpeta con tamaños y fechas, y un
paso de ``tools/check.py`` con una sola orden real.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

from tests.support.repo import ROOT, real_manifest, tools_on_path
from tests.support.resources import skip_reason
from tests.support.trees import child_runner, child_temp

tools_on_path()

import check  # noqa: E402
from gbtools import blender, manifest  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402

LAUNCHER = ROOT / "tools" / "run_blender_tests.py"
TIMEOUT_S = 300.0
TEMP_COPY_PREFIX = "geoblender-pruebas-"
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"

PASSING = SPDX + (
    "import unittest\n\n\n"
    "class Pasa(unittest.TestCase):\n"
    "    def test_pasa(self):\n"
    "        import bpy\n\n"
    "        self.assertGreaterEqual(tuple(bpy.app.version), (5, 2, 0))\n"
)
FAILING = SPDX + (
    "import unittest\n\n\n"
    "class Falla(unittest.TestCase):\n"
    "    def test_falla(self):\n"
    "        self.fail('sabotaje')\n"
)
RAISING = SPDX + (
    "import unittest\n\n\n"
    "class Lanza(unittest.TestCase):\n"
    "    def test_lanza(self):\n"
    "        raise RuntimeError('sabotaje')\n"
)
RAISING_ON_IMPORT = SPDX + "raise RuntimeError('sabotaje al importar')\n"
PLAIN = SPDX + (
    "import unittest\n\n\n"
    "class Pasa(unittest.TestCase):\n"
    "    def test_pasa(self):\n"
    "        self.assertTrue(True)\n"
)
# Sale del proceso con 0 a mitad de la ejecución (hallazgo 3, sabotaje S5).
EXITING = SPDX + (
    "import os\n"
    "import unittest\n\n\n"
    "class Sale(unittest.TestCase):\n"
    "    def test_sale(self):\n"
    "        os._exit(0)\n"
)
# Omisiones: sin recurso (hallazgo N1) y por un recurso que falta (T42).
SKIPPED_NO_RESOURCE = SPDX + (
    "import unittest\n\n\n"
    "class Saltada(unittest.TestCase):\n"
    "    @unittest.skip('pendiente de arreglar')\n"
    "    def test_pendiente(self):\n"
    "        self.fail('roja')\n"
)
SKIPPED_RESOURCE = SPDX + (
    "import unittest\n\n\n"
    "class Saltada(unittest.TestCase):\n"
    "    def test_recurso(self):\n"
    "        self.skipTest('[ENTORNO] motor: tools/install_runtime.py')\n"
)
# Pruebas que no ejecutan su cuerpo: una corrutina que nadie espera y un generador que
# nadie recorre; unittest solo avisa con un DeprecationWarning (hallazgo F7; T54).
ASYNC_FAILING = SPDX + (
    "import unittest\n\n\n"
    "class Asincrona(unittest.TestCase):\n"
    "    async def test_falla(self):\n"
    "        self.fail('roja')\n"
)
GENERATOR_FAILING = SPDX + (
    "import unittest\n\n\n"
    "class Generadora(unittest.TestCase):\n"
    "    def test_falla(self):\n"
    "        self.fail('roja')\n"
    "        yield\n"
)
RETURN_WARNING = "It is deprecated to return a value"
# Una prueba roja marcada como fallo esperado: unittest da «OK (expected failures=1)» y
# código 0 (hallazgo F1 de la ronda 4; T59).
EXPECTED_FAILURE = SPDX + (
    "import unittest\n\n\n"
    "class Esperada(unittest.TestCase):\n"
    "    @unittest.expectedFailure\n"
    "    def test_roja(self):\n"
    "        self.fail('roja')\n"
)
# La lista cerrada de recursos de una raíz temporal, con el de la omisión anterior (T47).
RESOURCES_WITH_ENGINE = SPDX + 'RESOURCES: tuple[str, ...] = ("motor",)\n'


def locate() -> BlenderInstall:
    """El Blender 5.2 del puesto (el mínimo del manifiesto) o, si no lo hay, la prueba
    se omite con el recurso ``blender`` (``tools/check.py`` ya lo exige antes)."""
    minimum = manifest.blender_min(real_manifest())
    try:
        return blender.locate_blender(minimum)
    except blender.EnvironmentProblem as exc:
        raise unittest.SkipTest(skip_reason("blender", str(exc))) from None


def blender_runner(temp: Path) -> blender.Runner:
    """``blender.run`` con la carpeta temporal del hijo en ``temp`` (``TMPDIR``, ``TEMP``
    y ``TMP``): lo que deje allí no se mezcla con lo de otra comprobación que se ejecute a
    la vez en el ``%TEMP%`` compartido (convergencia, T61)."""
    return child_runner(temp, blender.run)


def run_in_blender(
    install: BlenderInstall, script: Path, *args: str, leftovers: list[str] | None = None
) -> CompletedProcess[str]:
    """Ejecuta ``script`` en Blender en segundo plano con un perfil temporal propio y su
    propia carpeta temporal, que se borra al terminar con lo que Blender deje en ella;
    si se da ``leftovers``, se le añade lo que quedó (convergencia, T61)."""
    with (
        tempfile.TemporaryDirectory(prefix="geoblender-perfil-") as profile,
        child_temp() as temp,
    ):
        result = blender_runner(temp)(
            blender.background_cmd(install, script, *args),
            env=blender.isolated_env(Path(profile)),
            cwd=ROOT,
            timeout=TIMEOUT_S,
        )
        if leftovers is not None:
            leftovers.extend(sorted(os.listdir(temp)))
        return result


def run_output(result: CompletedProcess[str]) -> str:
    """La salida entera de un lanzamiento, para los mensajes de las aserciones."""
    return f"{result.stdout}\n{result.stderr}"


def listing(folder: Path) -> dict[str, tuple[int, int]]:
    """Ficheros y carpetas bajo ``folder`` (sin ``.git/``) con tamaño y ``mtime_ns``."""
    entries: dict[str, tuple[int, int]] = {}
    if not folder.is_dir():
        return entries
    for current, dirs, files in os.walk(folder):
        if ".git" in dirs:
            dirs.remove(".git")
        base = Path(current)
        for name in dirs:
            entries[(base / name).relative_to(folder).as_posix() + "/"] = (-1, 0)
        for name in files:
            path = base / name
            stat = path.stat(follow_symlinks=False)
            entries[path.relative_to(folder).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return entries


def listing_changes(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    """Lo que cambia entre dos listados (:func:`listing`): «nuevo», «borrado» y
    «cambiado», en ese orden."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    return (
        [f"nuevo: {key}" for key in added]
        + [f"borrado: {key}" for key in removed]
        + [f"cambiado: {key}" for key in changed]
    )


def user_profile() -> Path:
    """Perfil de Blender 5.2 del usuario (``%APPDATA%\\Blender Foundation\\Blender\\5.2``)."""
    return Path(os.environ.get("APPDATA", "")) / "Blender Foundation" / "Blender" / "5.2"


def check_step(
    install: BlenderInstall,
    root: Path,
    work: Path,
    run: Callable[[check.Context], check.Run],
) -> check.StepResult:
    """Un paso de ``check.py`` con una sola orden real, desde ``root``, con el perfil
    de Blender en ``work`` y su propia carpeta temporal (convergencia, T61)."""
    profile = work / "perfil"
    profile.mkdir(exist_ok=True)
    ctx = check.Context(root=root, install=install, profile=profile)
    step = check.Step("prueba", lambda context: [run(context)])
    with child_temp() as temp:
        return check.execute_step(step, ctx, blender_runner(temp))
