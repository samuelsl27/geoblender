# SPDX-License-Identifier: GPL-3.0-or-later
"""El arnés con el Blender real: las pruebas que lanzan ``blender.exe`` (plan 001 §7.1).

Es el paso «arnés» de ``tools/check.py --completo`` (spec 001 0.6, RF-001-06; D-9 de la
spec 002, T48): prueban ``tools/`` y ``tests/support/``, no la extensión, y la
comprobación de cada tarea no las ejecuta; ``tools/publish.py`` las pide siempre. Las que
solo simulan o lanzan el Python de Blender siguen en
``tests/unit/tools/test_harness_blender.py``. Estas pruebas lanzan Blender de verdad, en
segundo plano, con ``tools/run_blender_tests.py`` y un perfil temporal
(``gbtools.blender``):

- RF-001-06: una prueba de Blender que falla o que lanza una excepción no capturada
  (en la prueba, al importarla o en el propio guion) da un código distinto de 0; una que
  pasa, 0 (control positivo); y el lanzador no da por buena una salida a mitad
  (``os._exit(0)``), una prueba que devuelve algo ni un fallo esperado.
- RF-001-07: una carpeta sin pruebas no es un verde: código 1 y el motivo.
- RNF-007-01, RF-001-06 (spec 003, T40): con ``--parte i/n``, el lanzador ejecuta solo
  su parte y lo dice; entre todas las partes, cada prueba una vez.
- RF-001-09: una ejecución real del lanzador (una prueba que habilita la extensión y
  guarda un ``.blend``) no crea ni cambia ningún fichero del repositorio (ignorados
  incluidos, salvo ``.git/``; ningún ``__pycache__``) ni del perfil de Blender del
  usuario, y no deja la copia temporal de la extensión. La suite real (``tests/blender``)
  la ejecuta el paso «blender» de ``tools/check.py`` con su foto del repositorio: aquí no
  se repite (RNF-001-01; convergencia de la spec 002, T39). Cada proceso que
  lanzan estas pruebas (Blender o una orden de ``check.py``) tiene su propia carpeta
  temporal (``TMPDIR``, ``TEMP`` y ``TMP``), que se borra entera al terminar: lo que deje
  no se busca ni se borra en el ``%TEMP%`` compartido, donde otra comprobación que se
  ejecute a la vez tiene lo suyo (convergencia, T61).
- RF-001-05: la huella de la sesión de pruebas de Blender ve las fugas de una copia de la
  extensión (control positivo de CE-001-04).
- RF-001-02: el paso «manifiesto» de ``tools/check.py``, con el Blender real, falla sobre
  una copia de la extensión cuyo manifiesto empieza por BOM y pasa sobre la copia sin él.
- RF-001-26: ``tools/build.py`` empaqueta una copia temporal sin ``AGENTS.md``,
  ``CLAUDE.md``, ``__pycache__`` ni copias ``.blendN``, y no deja zip si la validación
  de Blender falla.
- RF-001-27: ese zip se instala en un perfil temporal limpio, una sesión nueva lo ve
  habilitado (con control positivo) y, tras desinstalarlo, no queda ni su carpeta ni su
  entrada en la lista de complementos.
- RF-001-28: ``tools/dev_install.py`` con un perfil temporal la deja habilitada para las
  sesiones siguientes y ``--desinstalar`` la quita, sin tocar el perfil del usuario.

Si no hay un Blender 5.2 localizable, se omiten con el motivo (``tools/check.py`` ya lo
exige antes de ejecutarlas). Si el Blender del usuario está abierto y guarda algo en su
perfil justo durante la ejecución, ``test_repo_and_user_profile_untouched`` lo señala:
repítala con ese Blender cerrado.
"""

import contextlib
import io
import shutil
import tempfile
import unittest
import zipfile
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

from tests.support.harness import (
    ASYNC_FAILING,
    EXITING,
    EXPECTED_FAILURE,
    FAILING,
    GENERATOR_FAILING,
    LAUNCHER,
    PASSING,
    RAISING,
    RAISING_ON_IMPORT,
    RETURN_WARNING,
    SPDX,
    blender_runner,
    check_step,
    listing,
    listing_changes,
    locate,
    run_in_blender,
    run_output,
    user_profile,
)
from tests.support.repo import (
    EMPTY_WHEELS_TOML,
    EXT,
    ROOT,
    manifest_without_wheels,
    tools_on_path,
)
from tests.support.trees import child_temp, temp_tree

tools_on_path()

import build  # noqa: E402
import check  # noqa: E402
import dev_install  # noqa: E402
from gbtools import discovery, manifest, parts  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402

# La ejecución real de RealRunTest (RF-001-09): habilita la extensión real, como hacen las
# pruebas de tests/blender, guarda un .blend en una carpeta temporal (Blender anota sus
# ficheros recientes en el perfil) y la deshabilita. La suite real la ejecuta el paso
# «blender» de check.py, con la foto del repositorio (RNF-001-01; convergencia de la spec
# 002, T39).
REAL_RUN = SPDX + (
    "import tempfile\n"
    "import unittest\n"
    "from pathlib import Path\n\n"
    "import bpy\n\n"
    "from tests.support import blender_ext\n\n\n"
    "class Real(unittest.TestCase):\n"
    "    def test_habilita_y_guarda(self):\n"
    "        blender_ext.enable()\n"
    "        try:\n"
    "            with tempfile.TemporaryDirectory() as tmp:\n"
    "                path = Path(tmp) / 'vista.blend'\n"
    "                bpy.ops.wm.save_as_mainfile(filepath=str(path))\n"
    "                self.assertTrue(path.is_file())\n"
    "        finally:\n"
    "            blender_ext.unload()\n"
)
REAL_RUN_FILES = {"pruebas/test_real.py": REAL_RUN}
# Una prueba que solo habilita y deshabilita la extensión, sin mirar la huella.
ENABLE_DISABLE = SPDX + (
    "import unittest\n\n"
    "from tests.support import blender_ext\n\n\n"
    "class Ciclo(unittest.TestCase):\n"
    "    def test_ciclo(self):\n"
    "        blender_ext.enable()\n"
    "        blender_ext.disable()\n"
    "        blender_ext.unload()\n"
)
# Raíz de una extensión con todas las fugas que la huella debe ver, que se repiten igual
# en cada habilitación (una copia y tres lanzamientos de Blender para todas: presupuesto
# de RNF-001-01; convergencia, T62): Scene.gb_x (hallazgo 2 de la verificación
# independiente, sabotaje S3; T36); draw_left envuelta con functools.wraps, que copia el
# módulo y el nombre de la original de Blender, tomada antes de que la spec 003 ponga su
# envoltorio al registrar (hallazgo N4; T40; ajustada en la 003/T37); una función
# en el menú Archivo › Importar, como el importador de las specs 005 y 006, y una
# propiedad en Curve (hallazgo F2 de la ronda 3, sabotajes X3 y X4; T49); un temporizador
# persistente y sus traducciones (hallazgo F3 de la ronda 3, sabotaje X7; T50: en la
# segunda habilitación ya están registradas); y un manejador de dibujo del 3D View, una
# colección de previews, una suscripción de msgbus, una preferencia cambiada, un
# complemento y una entrada de driver_namespace (hallazgo F3 de la ronda 4; T62).
LEAKY_ROOT = SPDX + (
    '"""Copia con fugas, para el control positivo de la huella de la sesión."""\n\n'
    "_ICONOS = []\n"
    "_PROPIETARIO = object()\n\n\n"
    "def _sabotaje_menu(self, context):\n"
    "    pass\n\n\n"
    "def _sabotaje_timer():\n"
    "    return 60.0\n\n\n"
    "def _sabotaje_dibujo():\n"
    "    pass\n\n\n"
    "def register():\n"
    "    import functools\n\n"
    "    import bpy\n"
    "    import bpy.utils.previews\n\n"
    "    from . import bl\n\n"
    "    topbar = bpy.types.TOPBAR_HT_upper_bar\n"
    "    original = topbar.draw_left  # el de Blender: la 003 lo envuelve al registrar\n"
    "    bl.register()\n"
    "    bpy.types.Scene.gb_x = bpy.props.IntProperty()\n\n"
    "    @functools.wraps(original)\n"
    "    def draw_left(self, context):\n"
    "        original(self, context)\n\n"
    "    topbar.draw_left = draw_left\n"
    "    bpy.types.TOPBAR_MT_file_import.append(_sabotaje_menu)\n"
    "    bpy.types.Curve.gb_sabotaje = bpy.props.IntProperty()\n"
    "    bpy.app.timers.register(_sabotaje_timer, first_interval=60.0, persistent=True)\n"
    "    try:\n"
    "        bpy.app.translations.register(__package__, {'es_ES': {('*', 'Hello'): 'Hola'}})\n"
    "    except ValueError:\n"
    "        pass\n"
    "    bpy.types.SpaceView3D.draw_handler_add(_sabotaje_dibujo, (), 'WINDOW', 'POST_VIEW')\n"
    "    _ICONOS.append(bpy.utils.previews.new())\n"
    "    bpy.msgbus.subscribe_rna(\n"
    "        key=(bpy.types.Object, 'location'),\n"
    "        owner=_PROPIETARIO,\n"
    "        args=(),\n"
    "        notify=_sabotaje_dibujo,\n"
    "    )\n"
    "    bpy.context.preferences.view.show_tooltips = False\n"
    "    if 'gb_sabotaje_complemento' not in bpy.context.preferences.addons:\n"
    "        bpy.context.preferences.addons.new().module = 'gb_sabotaje_complemento'\n"
    "    bpy.app.driver_namespace['gb_sabotaje'] = _sabotaje_dibujo\n\n\n"
    "def unregister():\n"
    "    from . import bl\n\n"
    "    bl.unregister()\n"
)


class LauncherExitCodeTest(unittest.TestCase):
    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def run_folder(self, files: dict[str, str], *args: str) -> CompletedProcess[str]:
        with temp_tree(files) as tmp:
            folder = tmp / "pruebas"
            folder.mkdir(exist_ok=True)
            return run_in_blender(self.install, LAUNCHER, "--carpeta", str(folder), *args)

    def test_passing_test_exit_zero(self) -> None:
        """RF-001-06: control positivo: una carpeta con una prueba que pasa da 0, y el
        lanzador termina con su línea final (T37)."""
        result = self.run_folder({"pruebas/test_pasa.py": PASSING})
        self.assertEqual(result.returncode, 0, run_output(result))
        self.assertIn("Ran 1 test", result.stderr)
        self.assertEqual(
            result.stderr.strip().splitlines()[-1], "FIN DEL LANZADOR: 1 prueba, código 0"
        )

    def test_failing_test_exit_nonzero(self) -> None:
        """RF-001-06: una prueba de Blender que falla da código distinto de 0 y se
        nombra en la salida."""
        result = self.run_folder(
            {"pruebas/test_pasa.py": PASSING, "pruebas/test_falla.py": FAILING}
        )
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertIn("FAIL: test_falla", result.stderr)
        self.assertIn("sabotaje", result.stderr)

    def test_uncaught_exception_exit_nonzero(self) -> None:
        """RF-001-06: una excepción no capturada en una prueba, al importar su módulo o
        en el guion que ejecuta Blender da código distinto de 0, nunca verde."""
        result = self.run_folder({"pruebas/test_lanza.py": RAISING})
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertIn("RuntimeError: sabotaje", result.stderr)

        result = self.run_folder({"pruebas/test_importa.py": RAISING_ON_IMPORT})
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertIn("sabotaje al importar", result.stderr)

        with temp_tree({"guion.py": RAISING_ON_IMPORT}) as tmp:
            result = run_in_blender(self.install, tmp / "guion.py")
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertIn("sabotaje al importar", run_output(result))

    def test_empty_blender_suite_fails(self) -> None:
        """RF-001-07: una carpeta sin pruebas (o sin ficheros que casen con el patrón)
        da 1 y lo dice: un arnés sin pruebas no demuestra nada."""
        result = self.run_folder({"pruebas/": ""})
        self.assertEqual(result.returncode, 1, run_output(result))
        self.assertIn("NO HAY PRUEBAS", result.stderr)

        result = self.run_folder({"pruebas/otra_cosa.py": PASSING})
        self.assertEqual(result.returncode, 1, run_output(result))
        self.assertIn("NO HAY PRUEBAS", result.stderr)

    def test_unloaded_test_file_exit_nonzero(self) -> None:
        """RF-001-06: una prueba en una subcarpeta sin ``__init__.py``, que ``unittest
        discover`` no carga, da código distinto de 0 y el lanzador nombra el fichero,
        también si es la única (sin «NO HAY PRUEBAS», que el paso de rendimiento acepta);
        con ``__init__.py`` (control positivo), se carga y se ejecuta (convergencia,
        T35)."""
        result = self.run_folder(
            {"pruebas/test_pasa.py": PASSING, "pruebas/sub/test_falla.py": FAILING}
        )
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertIn("PRUEBAS SIN CARGAR", result.stderr)
        self.assertIn("sub/test_falla.py", result.stderr)

        result = self.run_folder({"pruebas/sub/test_falla.py": FAILING})
        self.assertEqual(result.returncode, 1, run_output(result))
        self.assertIn("sub/test_falla.py", result.stderr)
        self.assertNotIn("NO HAY PRUEBAS", result.stderr)

        result = self.run_folder(
            {
                "pruebas/test_pasa.py": PASSING,
                "pruebas/sub/__init__.py": SPDX,
                "pruebas/sub/test_otra.py": PASSING,
            }
        )
        self.assertEqual(result.returncode, 0, run_output(result))
        self.assertIn("Ran 2 tests", result.stderr)

    def test_parts_cover_every_test_once(self) -> None:
        """RNF-007-01, RF-001-06 (spec 003, T40): con ``--parte i/2``, cada Blender
        escribe «PARTE i de 2: r de 3 pruebas» y su línea final con r, ejecuta solo los
        módulos de su parte y, entre los dos, cada prueba una vez (las líneas cuadran);
        un fichero sin cargar lo dice cada parte; y una parte que no es «i/n» da 2."""
        files = {f"pruebas/test_{name}.py": PASSING for name in ("a", "b", "c")}
        found: list[tuple[int, int, int, int] | None] = []
        modules: list[str] = []
        for part in (1, 2):
            result = self.run_folder(files, parts.OPTION, f"{part}/2")
            text = run_output(result)
            self.assertEqual(result.returncode, 0, text)
            line = parts.last_line(text)
            found.append(line)
            self.assertIsNotNone(line, text)
            assert line is not None
            self.assertEqual((line[0], line[1], line[3]), (part, 2, 3))
            self.assertIn(discovery.launcher_end_line(line[2], 0), text)
            loaded = sorted({name.split(".")[0] for name in discovery.loaded_in_output(text)})
            self.assertEqual(len(loaded), line[2])
            modules.extend(loaded)
        self.assertEqual(sorted(modules), ["test_a", "test_b", "test_c"])
        self.assertIsNone(parts.consistency(found, 2))

        unloaded = {**files, "pruebas/sub/test_d.py": PASSING}
        result = self.run_folder(unloaded, parts.OPTION, "2/2")
        self.assertEqual(result.returncode, 1, run_output(result))
        self.assertIn("PRUEBAS SIN CARGAR", result.stderr)

        result = self.run_folder(files, parts.OPTION, "3/2")
        self.assertEqual(result.returncode, 2, run_output(result))
        self.assertIn(parts.OPTION, result.stderr)
        self.assertNotIn("Ran ", run_output(result))

    def test_usage_errors_exit_2(self) -> None:
        """RF-001-07: una opción desconocida o una carpeta que no existe dan 2 sin
        ejecutar nada."""
        result = run_in_blender(self.install, LAUNCHER, "--opcion-que-no-existe")
        self.assertEqual(result.returncode, 2, run_output(result))
        self.assertIn("opción desconocida", result.stderr)
        with temp_tree({"vacia/": ""}) as tmp:
            missing = tmp / "no-existe"
            result = run_in_blender(self.install, LAUNCHER, "--carpeta", str(missing))
        self.assertEqual(result.returncode, 2, run_output(result))
        self.assertIn("no existe la carpeta de pruebas", result.stderr)


class ExitMidwayTest(unittest.TestCase):
    """Un proceso de pruebas que sale con 0 a mitad (``os._exit(0)``) no es verde en
    ``tools/check.py`` (RF-001-06; convergencia de la spec 001, T37). El de ``unittest``,
    con el Python de Blender, está en ``tests/unit/tools/test_harness_blender.py``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def run_step(
        self, root: Path, work: Path, run: Callable[[check.Context], check.Run]
    ) -> check.StepResult:
        return check_step(self.install, root, work, run)

    def test_launcher_exit_zero_midway_fails(self) -> None:
        """RF-001-06: el lanzador con una prueba que llama a ``os._exit(0)`` deja a
        Blender salir con 0 sin resumen ni línea final, y el paso de ``check.py`` queda
        en fallo; sin esa prueba (control positivo), correcto. La copia que el lanzador
        no puede borrar (``os._exit``) queda en la carpeta temporal propia de Blender, que
        se borra con ella: no se busca en el ``%TEMP%`` compartido (convergencia, T61)."""
        files = {"pruebas/test_a.py": PASSING, "pruebas/test_b.py": EXITING}
        with temp_tree(files) as tmp:
            folder = str(tmp / "pruebas")
            result = self.run_step(ROOT, tmp, lambda ctx: ctx.blender_tests(folder))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertIn("(código 0)", result.output)
            self.assertIn("sin el resumen de unittest", result.detail)
            (tmp / "pruebas" / "test_b.py").unlink()
            result = self.run_step(ROOT, tmp, lambda ctx: ctx.blender_tests(folder))
        self.assertEqual(result.status, check.STATUS_OK, result.output)


class ReturnValueTest(unittest.TestCase):
    """Una prueba que devuelve algo en lugar de ejecutarse (``async def`` en un
    ``TestCase``, o con ``yield``) no es verde en el lanzador (RF-001-06; hallazgo F7 de
    la ronda 3, falso verde X9; convergencia, T54). La de ``tools/check.py``, en
    ``tests/unit/tools/test_harness_blender.py``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def test_launcher_fails(self) -> None:
        """RF-001-06: el lanzador, dentro de Blender, con una prueba ``async def`` y otra
        con ``yield`` (las dos con ``self.fail`` que no se ejecuta), termina con un
        código distinto de 0 y nombra el aviso convertido en error."""
        files = {
            "pruebas/test_asincrona.py": ASYNC_FAILING,
            "pruebas/test_generadora.py": GENERATOR_FAILING,
        }
        with temp_tree(files) as tmp:
            folder = str(tmp / "pruebas")
            result = run_in_blender(self.install, LAUNCHER, "--carpeta", folder)
        self.assertNotEqual(result.returncode, 0, run_output(result))
        self.assertEqual(result.stderr.count(f"DeprecationWarning: {RETURN_WARNING}"), 2)
        self.assertIn("FIN DEL LANZADOR: 2 pruebas, código 1", result.stderr)


class ExpectedFailureTest(unittest.TestCase):
    """Una prueba roja marcada con ``expectedFailure`` («OK (expected failures=1)» y
    código 0 en ``unittest``) no es verde en el lanzador (RF-001-06; hallazgo F1 de la
    ronda 4; convergencia, T59). La de ``tools/check.py``, en
    ``tests/unit/tools/test_harness_blender.py``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def test_launcher_fails(self) -> None:
        """RF-001-06: el lanzador, dentro de Blender, con una prueba que pasa y la roja
        marcada con ``expectedFailure``, termina con 1 y nombra la prueba en «FALLOS
        ESPERADOS», aunque ``unittest`` diga «OK (expected failures=1)»."""
        files = {"pruebas/test_pasa.py": PASSING, "pruebas/test_esperada.py": EXPECTED_FAILURE}
        with temp_tree(files) as tmp:
            folder = str(tmp / "pruebas")
            result = run_in_blender(self.install, LAUNCHER, "--carpeta", folder)
        self.assertEqual(result.returncode, 1, run_output(result))
        self.assertIn("OK (expected failures=1)", result.stderr)
        self.assertIn("FALLOS ESPERADOS (1)", result.stderr)
        self.assertIn("test_esperada.Esperada.test_roja", result.stderr)
        self.assertIn("FIN DEL LANZADOR: 2 pruebas, código 1", result.stderr)


class RealRunTest(unittest.TestCase):
    """Una ejecución real del lanzador, con fotos antes y después: Blender con el perfil
    temporal y la copia de la extensión, sobre una carpeta con una sola prueba que la
    habilita, guarda un ``.blend`` y la deshabilita (:data:`REAL_RUN`). La suite real
    (``tests/blender``) no se repite aquí: la ejecuta el paso «blender» de
    ``tools/check.py``, cuya foto del repositorio cubre RF-001-09 para ella (RNF-001-01;
    convergencia de la spec 002, T39)."""

    result: CompletedProcess[str]
    repo_before: dict[str, tuple[int, int]]
    repo_after: dict[str, tuple[int, int]]
    profile_before: dict[str, tuple[int, int]]
    profile_after: dict[str, tuple[int, int]]
    leftovers: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        install = locate()
        cls.repo_before = listing(ROOT)
        cls.profile_before = listing(user_profile())
        # Lo que Blender deja en su carpeta temporal propia (convergencia, T61).
        cls.leftovers = []
        with temp_tree(REAL_RUN_FILES) as tmp:
            cls.result = run_in_blender(
                install, LAUNCHER, "--carpeta", str(tmp / "pruebas"), leftovers=cls.leftovers
            )
        cls.profile_after = listing(user_profile())
        cls.repo_after = listing(ROOT)

    def test_real_run_passes(self) -> None:
        """RF-001-06: la ejecución real termina con 0 y ejecuta su prueba."""
        self.assertEqual(self.result.returncode, 0, run_output(self.result))
        self.assertIn("Ran 1 test", self.result.stderr)
        self.assertIn("OK", self.result.stderr)

    def test_no_new_pycache_in_repo(self) -> None:
        """RF-001-09: no aparece ningún ``__pycache__`` en el repositorio."""
        before = {key for key in self.repo_before if "__pycache__" in key.split("/")}
        after = {key for key in self.repo_after if "__pycache__" in key.split("/")}
        self.assertEqual(sorted(after - before), [])

    def test_repo_and_user_profile_untouched(self) -> None:
        """RF-001-09: ni el repositorio (rutas, tamaños y ``mtime_ns``, ignorados
        incluidos salvo ``.git/``) ni el perfil real de Blender 5.2 del usuario cambian,
        y no queda la copia temporal de la extensión (ni nada) en la carpeta temporal
        propia de Blender, sin mirar el ``%TEMP%`` compartido (convergencia, T61)."""
        self.assertEqual(listing_changes(self.repo_before, self.repo_after), [])
        self.assertEqual(listing_changes(self.profile_before, self.profile_after), [])
        self.assertEqual(self.leftovers, [])


# Los ficheros de tests/blender que lleva la copia con fugas: la prueba de registro real
# y, antes que ella, una que habilita y deshabilita la extensión (RNF-001-01; T39).
LEAKY_SUITE = ("__init__.py", "test_registration.py")
LEAKY_CYCLE = "test_ciclo.py"


def _leaky_copy(folder: Path) -> Path:
    """Copia en ``folder`` del lanzador (con ``gbtools``), de ``tests/support`` y de la
    extensión, con la raíz de la extensión cambiada por :data:`LEAKY_ROOT` y el
    manifiesto real sin ruedas ni BOM (las fugas no dependen de él: T56); devuelve el
    lanzador de la copia. Su ``tests/blender`` lleva solo la prueba de registro real
    (:data:`LEAKY_SUITE`) y, antes que ella, :data:`ENABLE_DISABLE` como
    :data:`LEAKY_CYCLE`: así la extensión ya se ha habilitado y deshabilitado cuando llega
    la prueba de registro, como en la suite entera, sin repetir las demás pruebas
    (RNF-001-01; convergencia de la spec 002, T39)."""
    ignore = shutil.ignore_patterns("__pycache__", "*.py[cod]", "wheels")
    shutil.copytree(ROOT / "tools", folder / "tools", ignore=ignore)
    shutil.copytree(ROOT / EXT, folder / EXT, ignore=ignore)
    (folder / manifest.MANIFEST_RELPATH).write_bytes(
        manifest_without_wheels().encode("utf-8")
    )
    (folder / "tests").mkdir()
    shutil.copy2(ROOT / "tests" / "__init__.py", folder / "tests" / "__init__.py")
    shutil.copytree(ROOT / "tests" / "support", folder / "tests" / "support", ignore=ignore)
    suite = folder / "tests" / "blender"
    suite.mkdir()
    for name in LEAKY_SUITE:
        shutil.copy2(ROOT / "tests" / "blender" / name, suite / name)
    (suite / LEAKY_CYCLE).write_bytes(ENABLE_DISABLE.encode("utf-8"))
    (folder / EXT / "__init__.py").write_bytes(LEAKY_ROOT.encode("utf-8"))
    return folder / "tools" / "run_blender_tests.py"


class SessionFingerprintTest(unittest.TestCase):
    """La huella de la sesión de pruebas de Blender (RF-001-05, CE-001-04;
    convergencia de la spec 001, T36).

    Todas las fugas van en una sola copia de la extensión (:data:`LEAKY_ROOT`), y las
    pruebas de la clase leen tres lanzamientos de Blender, hechos una vez: la extensión
    real con una carpeta cuya única prueba habilita y deshabilita sin mirar la huella
    (control positivo), la copia con esa misma carpeta, y la copia con su
    ``tests/blender``, que lleva solo la prueba de registro real precedida de esa misma
    prueba (presupuesto de RNF-001-01; convergencia, T62, y de la spec 002, T39)."""

    clean: CompletedProcess[str]
    folder: CompletedProcess[str]
    suite: CompletedProcess[str]

    @classmethod
    def setUpClass(cls) -> None:
        install = locate()
        with temp_tree({"pruebas/test_ciclo.py": ENABLE_DISABLE}) as tmp:
            pruebas = str(tmp / "pruebas")
            cls.clean = run_in_blender(install, LAUNCHER, "--carpeta", pruebas)
            launcher = _leaky_copy(tmp / "copia")
            cls.folder = run_in_blender(install, launcher, "--carpeta", pruebas)
            cls.suite = run_in_blender(install, launcher)

    def test_launcher_detects_idempotent_leak(self) -> None:
        """RF-001-05: con una copia de la extensión que, al deshabilitarse, deja
        registrada ``Scene.gb_x`` (una fuga que se repite igual en cada habilitación),
        una carpeta cuya única prueba habilita y deshabilita sin mirar la huella da
        código distinto de 0, y el lanzador nombra la diferencia con la huella del
        principio de la sesión; con la extensión real (control positivo), la misma
        carpeta da 0."""
        self.assertEqual(self.clean.returncode, 0, run_output(self.clean))
        self.assertNotIn("HUELLA", self.clean.stderr)
        self.assertNotEqual(self.folder.returncode, 0, run_output(self.folder))
        self.assertIn("HUELLA: properties[Scene]: añadidos ['gb_x']", self.folder.stderr)
        self.assertIn("FIN DEL LANZADOR: 1 prueba, código 1", self.folder.stderr)

    def test_registration_test_uses_session_baseline(self) -> None:
        """RF-001-05: con esa copia, la prueba de registro real (``tests/blender`` de la
        copia, donde otra prueba la habilita y deshabilita antes) falla en
        ``test_disable_restores_fingerprint`` nombrando cada fuga: compara con la huella
        del principio de la sesión y no con una tomada después de que otra prueba
        habilitara la extensión (que ya tendría la fuga)."""
        self.assertNotEqual(self.suite.returncode, 0, run_output(self.suite))
        self.assertIn("FAIL: test_disable_restores_fingerprint", self.suite.stderr)
        for leak in (
            "properties[Scene]: añadidos ['gb_x']",
            "topbar_draw_left",
            "draw_funcs[TOPBAR_MT_file_import]",
            "properties[Curve]: añadidos ['gb_sabotaje']",
            "timers: añadidos [",
            "translations: añadidos [",
            "draw_handlers: añadidos [",
            "previews: añadidos [",
            "msgbus: añadidos [",
            "preferences[view.show_tooltips]",
            "addons: añadidos ['gb_sabotaje_complemento']",
            "driver_namespace: añadidos ['gb_sabotaje']",
        ):
            with self.subTest(fuga=leak):
                self.assertIn(leak, self.suite.stderr)

    def test_wrapped_draw_left_detected(self) -> None:
        """RF-001-05: con la copia, que envuelve ``draw_left`` con ``functools.wraps``
        (mismo módulo y nombre que la original) y no la restaura, el lanzador nombra
        ``topbar_draw_left`` («mismo nombre y otro objeto»): la huella compara el objeto,
        no solo el nombre (hallazgo N4; convergencia, T40)."""
        self.assertIn("HUELLA: topbar_draw_left", self.folder.stderr)
        self.assertIn("mismo nombre y otro objeto", self.folder.stderr)

    def test_menu_function_and_any_type_property_detected(self) -> None:
        """RF-001-05: con la copia, que deja una función en el menú Archivo › Importar y
        una propiedad en ``Curve`` (fuera de los menús de la barra superior y de los
        tipos principales), el lanzador nombra las dos fugas (hallazgo F2, sabotajes X3
        y X4; convergencia, T49)."""
        self.assertIn(
            "HUELLA: draw_funcs[TOPBAR_MT_file_import]: añadidos [", self.folder.stderr
        )
        self.assertIn("_sabotaje_menu", self.folder.stderr)
        self.assertIn("HUELLA: properties[Curve]: añadidos ['gb_sabotaje']", self.folder.stderr)

    def test_timer_and_translations_detected(self) -> None:
        """RF-001-05: con la copia, que deja registrados un temporizador persistente y
        sus traducciones (que no se pueden enumerar con la API pública), el lanzador
        nombra las dos fugas: anota los temporizadores que se registran durante la
        sesión y mira si siguen registrados, y prueba si los módulos de la copia tienen
        traducciones registradas (hallazgo F3, sabotaje X7; convergencia, T50)."""
        self.assertIn("HUELLA: timers: añadidos [", self.folder.stderr)
        self.assertIn("_sabotaje_timer", self.folder.stderr)
        self.assertIn(
            "HUELLA: translations: añadidos ['bl_ext.gb_tests.geoblender']", self.folder.stderr
        )

    def test_session_registrations_detected(self) -> None:
        """RF-001-05: con la copia, que deja un manejador de dibujo del 3D View, una
        colección de previews, una suscripción de msgbus, ``show_tooltips`` cambiada, un
        complemento en ``preferences.addons`` y una entrada en ``driver_namespace``, el
        lanzador nombra las seis fugas (las tres primeras no se pueden enumerar con la
        API pública: el lanzador envuelve sus funciones de registro) (hallazgo F3 de la
        ronda 4; convergencia, T62)."""
        module = "bl_ext.gb_tests.geoblender"
        for line in (
            "HUELLA: draw_handlers: añadidos ['SpaceView3D.draw_handler_add → "
            f"{module}._sabotaje_dibujo (objeto ",
            f"HUELLA: previews: añadidos ['bpy.utils.previews.new desde {module} (objeto ",
            f"HUELLA: msgbus: añadidos ['bpy.msgbus.subscribe_rna → {module}._sabotaje_dibujo",
            "HUELLA: preferences[view.show_tooltips]: True → False",
            "HUELLA: addons: añadidos ['gb_sabotaje_complemento'], quitados []",
            "HUELLA: driver_namespace: añadidos ['gb_sabotaje'], quitados []",
        ):
            with self.subTest(linea=line):
                self.assertIn(line, self.folder.stderr)


BOM = b"\xef\xbb\xbf"


class ManifestValidationTest(unittest.TestCase):
    """El paso «manifiesto» de ``tools/check.py`` con el Blender real."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def validate_copy(self, bom: bool) -> check.StepResult:
        """Ejecuta el paso «manifiesto» sobre una copia de ``geoblender/`` en ``%TEMP%``."""
        step = next(step for step in check.STEPS if step.name == "manifiesto")
        with tempfile.TemporaryDirectory(prefix="geoblender-manifiesto-") as tmp:
            root = Path(tmp)
            shutil.copytree(
                ROOT / EXT,
                root / EXT,
                ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]"),
            )
            path = root / manifest.MANIFEST_RELPATH
            # Sin el BOM que pudiera tener el real (T56), y con uno si se pide.
            path.write_bytes((BOM if bom else b"") + path.read_bytes().removeprefix(BOM))
            profile = root / "perfil"
            profile.mkdir()
            ctx = check.Context(root=root, install=self.install, profile=profile)
            with child_temp() as temp:
                return check.execute_step(step, ctx, blender_runner(temp))

    def test_validate_fails_with_bom(self) -> None:
        """RF-001-02: con BOM al principio del manifiesto, ``extension validate`` falla y
        el paso «manifiesto» queda en fallo con la salida de Blender; sin BOM (control
        positivo), el mismo paso es correcto."""
        result = self.validate_copy(bom=True)
        self.assertEqual(result.status, check.STATUS_FAIL, result.output)
        self.assertIn("line 1", result.output)

        result = self.validate_copy(bom=False)
        self.assertEqual(result.status, check.STATUS_OK, result.output)


def _copy_repo(folder: Path) -> Path:
    """Copia mínima del repositorio en ``folder``, para empaquetarla sin escribir en el
    repositorio: la extensión sin ``__pycache__`` ni ruedas, con el manifiesto sin
    ruedas, y un ``tools/wheels.toml`` sin ruedas (no dependen de las que fije cada
    spec: T45)."""
    shutil.copytree(
        ROOT / EXT,
        folder / EXT,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "wheels"),
    )
    (folder / manifest.MANIFEST_RELPATH).write_bytes(
        manifest_without_wheels().encode("utf-8")
    )
    (folder / "tools").mkdir()
    (folder / "tools" / "wheels.toml").write_bytes(EMPTY_WHEELS_TOML.encode("utf-8"))
    return folder


def _build(root: Path, install: BlenderInstall, *args: str) -> tuple[int, str]:
    """``tools/build.py`` sobre la copia ``root`` con el Blender real, cada Blender con su
    carpeta temporal propia (convergencia, T61)."""
    out = io.StringIO()
    with (
        child_temp() as temp,
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(out),
    ):
        code = build.main(
            list(args), root=root, runner=blender_runner(temp), locate=lambda minimum: install
        )
    return code, out.getvalue()


class BuildRealTest(unittest.TestCase):
    """``tools/build.py`` con el Blender real sobre copias temporales de la extensión."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def test_build_zip_has_no_agent_files(self) -> None:
        """RF-001-26: el zip de una copia de la extensión con ``AGENTS.md`` y
        ``CLAUDE.md`` anidados, ``__pycache__`` y una copia ``.blend1`` sale en
        ``dist/<id>-<versión>.zip`` (la versión, la del manifiesto) sin ninguno de ellos,
        con el manifiesto y el ``__init__.py`` en la raíz, y pasa la inspección."""
        with tempfile.TemporaryDirectory(prefix="geoblender-zip-") as tmp:
            root = _copy_repo(Path(tmp))
            extension = root / EXT
            (extension / "bl" / "ui" / "AGENTS.md").write_text("# reglas\n", encoding="utf-8")
            (extension / "bl" / "ui" / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (extension / "core" / "__pycache__").mkdir()
            (extension / "core" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"x")
            (extension / "copia.blend1").write_bytes(b"BLENDER")
            code, output = _build(root, self.install)
            self.assertEqual(code, 0, output)
            data = manifest.load(extension / "blender_manifest.toml")
            path = root / "dist" / f"{data['id']}-{data['version']}.zip"
            self.assertTrue(path.is_file(), output)
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
            self.assertEqual(build.inspect_zip(path, data), [])
        for name in names:
            with self.subTest(miembro=name):
                parts = name.split("/")
                self.assertNotIn(parts[-1], ("AGENTS.md", "CLAUDE.md"))
                self.assertNotIn("__pycache__", parts)
                self.assertFalse(name.endswith((".pyc", ".blend1")))
        for required in ("blender_manifest.toml", "__init__.py", "bl/ui/__init__.py"):
            self.assertIn(required, names)

    def test_no_zip_when_validate_fails(self) -> None:
        """RF-001-26: con un manifiesto que pasa MAN-01 pero no la validación de Blender
        (sin ``maintainer``), el empaquetado termina con 1, muestra el error de Blender y
        no deja zip en ``dist/`` (tampoco uno anterior)."""
        with tempfile.TemporaryDirectory(prefix="geoblender-zip-") as tmp:
            root = _copy_repo(Path(tmp))
            path = root / manifest.MANIFEST_RELPATH
            text = path.read_text(encoding="utf-8")
            self.assertIn('maintainer = "IMGA"\n', text)
            path.write_bytes(text.replace('maintainer = "IMGA"\n', "").encode("utf-8"))
            self.assertEqual(manifest.check(root), [])
            data = manifest.load(path)
            stale = root / "dist" / f"{data['id']}-{data['version']}.zip"
            stale.parent.mkdir()
            stale.write_bytes(b"zip anterior")
            code, output = _build(root, self.install)
            self.assertEqual(code, 1, output)
            self.assertIn("maintainer", output)
            self.assertEqual(list((root / "dist").iterdir()), [])

    def test_install_probe_leaves_no_trace(self) -> None:
        """RF-001-27: el zip de una copia temporal se instala en un perfil temporal
        limpio y una sesión nueva sin configuración de fábrica lo ve listado, importable
        y habilitado (control positivo: en un perfil donde no se instaló, la misma
        sesión no lo ve, así que la prueba no puede pasar sin instalar); tras
        desinstalarlo, otra sesión ya no lo ve y no queda su carpeta en el perfil. El
        perfil real del usuario no cambia."""
        profile_before = listing(user_profile())
        with tempfile.TemporaryDirectory(prefix="geoblender-zip-") as tmp:
            root = _copy_repo(Path(tmp) / "repo")
            code, output = _build(root, self.install)
            self.assertEqual(code, 0, output)
            data = manifest.load(root / manifest.MANIFEST_RELPATH)
            target = root / "dist" / build.zip_name(data)
            work = Path(tmp) / "trabajo"
            work.mkdir()
            temp = Path(tmp) / "temporal-de-blender"  # la carpeta temporal de cada Blender
            temp.mkdir()
            runner = blender_runner(temp)
            report = build.probe_install(self.install, target, data, work, runner)
            self.assertEqual(report.problems, [])
            self.assertEqual(report.installed, build.AddonState(True, True, True))
            self.assertEqual(report.removed, build.AddonState(False, False, False))
            self.assertFalse(report.folder_left)

            empty = Path(tmp) / "perfil-vacio"
            empty.mkdir()
            script = build.write_probe_script(work)
            state, output = build.probe_session(
                self.install, empty, script, build.installed_module(data), runner
            )
            self.assertEqual(state, build.AddonState(False, False, False), output)
        self.assertEqual(listing_changes(profile_before, listing(user_profile())), [])


def _dev_install(install: BlenderInstall, *args: str) -> tuple[int, str]:
    """``tools/dev_install.py`` sobre el repositorio real (solo lo lee) con el Blender
    real."""
    out = io.StringIO()
    with (
        child_temp() as temp,
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(out),
    ):
        code = dev_install.main(
            list(args), root=ROOT, runner=blender_runner(temp), locate=lambda minimum: install
        )
    return code, out.getvalue()


class DevInstallRealTest(unittest.TestCase):
    """``tools/dev_install.py`` con el Blender real y un perfil temporal (sin interfaz)."""

    def test_dev_install_enables_in_isolated_profile(self) -> None:
        """RF-001-28: la instalación de desarrollo en un perfil temporal deja la
        extensión habilitada para las sesiones siguientes de ese perfil (una sesión nueva
        sin configuración de fábrica la ve listada, importable y habilitada);
        ``--desinstalar`` la deja fuera de la lista de complementos y sin su carpeta. Ni
        el perfil real del usuario ni la extensión del repositorio cambian."""
        install = locate()
        data = manifest.load(ROOT / manifest.MANIFEST_RELPATH)
        module = build.installed_module(data)
        profile_before = listing(user_profile())
        extension_before = listing(ROOT / EXT)
        with tempfile.TemporaryDirectory(prefix="geoblender-dev-prueba-") as tmp:
            profile = Path(tmp) / "perfil"
            script = build.write_probe_script(Path(tmp))
            temp = Path(tmp) / "temporal-de-blender"  # la carpeta temporal de cada Blender
            temp.mkdir()
            runner = blender_runner(temp)
            code, output = _dev_install(install, "--perfil", str(profile))
            self.assertEqual(code, 0, output)
            state, probe = build.probe_session(install, profile, script, module, runner)
            self.assertEqual(state, build.AddonState(True, True, True), probe)

            code, output = _dev_install(install, "--perfil", str(profile), "--desinstalar")
            self.assertEqual(code, 0, output)
            folder = profile / "extensions" / build.INSTALL_REPO / str(data["id"])
            self.assertFalse(folder.exists())
            state, probe = build.probe_session(install, profile, script, module, runner)
            self.assertEqual(state, build.AddonState(False, False, False), probe)
        self.assertEqual(listing_changes(profile_before, listing(user_profile())), [])
        self.assertEqual(listing_changes(extension_before, listing(ROOT / EXT)), [])


if __name__ == "__main__":
    unittest.main()
