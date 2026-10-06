# SPDX-License-Identifier: GPL-3.0-or-later
"""El arnés sin lanzar ``blender.exe``: lo que solo simula o lanza el Python de Blender
(plan 001 §7.1).

Las pruebas del arnés que lanzan Blender entero están en
``tests/arnes/test_harness_blender.py``, el paso «arnés» de ``tools/check.py
--completo`` (spec 001 0.6; D-9 de la spec 002, T48); aquí quedan las que caben en la
comprobación de cada tarea (RNF-001-01, ≤ 40 s):

- RF-001-06: un paso de ``tools/check.py`` con ``unittest`` real (el Python de Blender)
  no da por buena una salida a mitad (``os._exit(0)``), una omisión sin recurso, una
  prueba que devuelve algo ni un fallo esperado.
- RF-001-09: cada proceso que lanzan las pruebas del arnés (Blender o una orden de
  ``check.py``) tiene su propia carpeta temporal (``TMPDIR``, ``TEMP`` y ``TMP``), que se
  borra entera al terminar (convergencia, T61); el listado con el que se comparan el
  repositorio y el perfil del usuario ve los cambios (control positivo).
- RNF-001-01, RF-001-05, RF-001-09: las pruebas del arnés que lanzan Blender no recorren
  ``tests/blender`` entero (convergencia de la spec 002, T39).

Si no hay un Blender 5.2 localizable, las que necesitan su Python se omiten con el motivo
(``tools/check.py`` ya lo exige antes de ejecutarlas).
"""

import os
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

from tests.arnes import test_harness_blender as arnes
from tests.support.harness import (
    ASYNC_FAILING,
    EXITING,
    EXPECTED_FAILURE,
    GENERATOR_FAILING,
    LAUNCHER,
    PLAIN,
    RESOURCES_WITH_ENGINE,
    RETURN_WARNING,
    SKIPPED_NO_RESOURCE,
    SKIPPED_RESOURCE,
    SPDX,
    TEMP_COPY_PREFIX,
    check_step,
    listing,
    listing_changes,
    locate,
    run_in_blender,
)
from tests.support.repo import tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools import blender  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402


class ExitMidwayTest(unittest.TestCase):
    """Un proceso de pruebas que sale con 0 a mitad (``os._exit(0)``) no es verde en
    ``tools/check.py`` (RF-001-06; convergencia de la spec 001, T37). El del lanzador,
    dentro de Blender, está en ``tests/arnes``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def run_step(
        self, root: Path, work: Path, run: Callable[[check.Context], check.Run]
    ) -> check.StepResult:
        return check_step(self.install, root, work, run)

    def test_unittest_exit_zero_midway_fails(self) -> None:
        """RF-001-06: ``unittest`` con el Python de Blender sobre una carpeta cuya
        segunda prueba llama a ``os._exit(0)`` termina con 0 y sin resumen, y el paso
        de ``check.py`` queda en fallo; sin esa prueba (control positivo), correcto."""
        files = {
            "pruebas/__init__.py": SPDX,
            "pruebas/test_a.py": PLAIN,
            "pruebas/test_b.py": EXITING,
        }
        with temp_tree(files) as tmp:
            result = self.run_step(tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertIn("(código 0)", result.output)
            self.assertIn("sin el resumen de unittest", result.detail)
            (tmp / "pruebas" / "test_b.py").unlink()
            result = self.run_step(tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
        self.assertEqual(result.status, check.STATUS_OK, result.output)


class SkipWithoutResourceTest(unittest.TestCase):
    """Una omisión sin «[ENTORNO] <recurso>: <orden>» no es verde en ``tools/check.py``
    (RF-001-06; hallazgo N1 de la reverificación; convergencia de la spec 001, T42)."""

    def test_real_skip_without_resource_fails(self) -> None:
        """RF-001-06: ``unittest`` real con el Python de Blender sobre una prueba con
        ``@unittest.skip('pendiente de arreglar')`` termina con 0 («OK (skipped=1)») y el
        paso de ``check.py`` queda en fallo, «1 omisión sin recurso»; una omisión por un
        recurso que no está en la lista cerrada de la raíz («[ENTORNO] motor: …» sin
        ``tests/support/resources.py``), también (T47); con ``motor`` en la lista
        (control positivo), correcto con ella."""
        install = locate()
        files = {
            "pruebas/__init__.py": SPDX,
            "pruebas/test_a.py": PLAIN,
            "pruebas/test_s.py": SKIPPED_NO_RESOURCE,
        }
        with temp_tree(files) as tmp:
            result = check_step(install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertIn("1 omisión sin recurso", result.detail)
            self.assertIn("(código 0)", result.output)
            self.assertIn("pruebas.test_s.Saltada.test_pendiente", result.output)
            (tmp / "pruebas" / "test_s.py").write_text(SKIPPED_RESOURCE, encoding="utf-8")
            result = check_step(install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertIn("1 omisión sin recurso", result.detail)
            support = tmp / "tests" / "support"
            support.mkdir(parents=True)
            (support / "resources.py").write_text(RESOURCES_WITH_ENGINE, encoding="utf-8")
            result = check_step(install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
        self.assertEqual(result.status, check.STATUS_OK, result.output)
        self.assertEqual(
            [(skip.resource, skip.hint) for skip in result.skipped],
            [("motor", "tools/install_runtime.py")],
        )


class ReturnValueTest(unittest.TestCase):
    """Una prueba que devuelve algo en lugar de ejecutarse (``async def`` en un
    ``TestCase``, o con ``yield``) no es verde en ``tools/check.py`` (RF-001-06; hallazgo
    F7 de la ronda 3, falso verde X9; convergencia, T54). La del lanzador, dentro de
    Blender, está en ``tests/arnes``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def test_unittest_step_fails(self) -> None:
        """RF-001-06: ``unittest`` real con el Python de Blender, desde ``check.py``, sobre
        una carpeta con una prueba ``async def`` y otra con ``yield`` (las dos con
        ``self.fail`` que no se ejecuta) deja el paso en fallo con el aviso convertido en
        error; sin ellas (control positivo), correcto."""
        files = {
            "pruebas/__init__.py": SPDX,
            "pruebas/test_a.py": PLAIN,
            "pruebas/test_asincrona.py": ASYNC_FAILING,
            "pruebas/test_generadora.py": GENERATOR_FAILING,
        }
        with temp_tree(files) as tmp:
            result = check_step(self.install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertEqual(result.output.count(f"DeprecationWarning: {RETURN_WARNING}"), 2)
            for name in ("test_asincrona.py", "test_generadora.py"):
                (tmp / "pruebas" / name).unlink()
            result = check_step(self.install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
        self.assertEqual(result.status, check.STATUS_OK, result.output)


class ExpectedFailureTest(unittest.TestCase):
    """Una prueba roja marcada con ``expectedFailure`` («OK (expected failures=1)» y
    código 0 en ``unittest``) no es verde en ``tools/check.py`` (RF-001-06; hallazgo F1
    de la ronda 4; convergencia, T59). La del lanzador, dentro de Blender, está en
    ``tests/arnes``."""

    install: BlenderInstall

    @classmethod
    def setUpClass(cls) -> None:
        cls.install = locate()

    def test_unittest_step_fails(self) -> None:
        """RF-001-06: ``unittest`` real con el Python de Blender, desde ``check.py``,
        sobre una carpeta con una prueba que pasa y otra roja marcada con
        ``expectedFailure`` termina con 0 y «OK (expected failures=1)», y el paso queda
        en fallo «con fallos esperados»; sin ella (control positivo), correcto."""
        files = {
            "pruebas/__init__.py": SPDX,
            "pruebas/test_a.py": PLAIN,
            "pruebas/test_esperada.py": EXPECTED_FAILURE,
        }
        with temp_tree(files) as tmp:
            result = check_step(self.install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
            self.assertEqual(result.status, check.STATUS_FAIL, result.output)
            self.assertIn("con fallos esperados", result.detail)
            self.assertIn("(código 0)", result.output)
            self.assertIn("OK (expected failures=1)", result.output)
            (tmp / "pruebas" / "test_esperada.py").unlink()
            result = check_step(self.install, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
        self.assertEqual(result.status, check.STATUS_OK, result.output)


FAKE_INSTALL = BlenderInstall(Path("blender.exe"), Path("python.exe"), (5, 2, 1))


class ChildTempTest(unittest.TestCase):
    """Cada proceso hijo que lanzan estas pruebas (Blender o una orden de ``check.py``)
    tiene su propia carpeta temporal (``TMPDIR``, ``TEMP`` y ``TMP``), que se borra entera
    al terminar, y nada más: otra comprobación que se ejecute a la vez tiene sus copias en
    el ``%TEMP%`` compartido (hallazgo F7 de la ronda 4; convergencia, T61). Sin lanzar
    nada: ``blender.run`` se sustituye por uno que anota el entorno."""

    def recorder(self, seen: list[dict[str, str]]) -> Callable[..., CompletedProcess[str]]:
        """Un ``blender.run`` que anota el entorno, comprueba que la carpeta temporal
        del hijo existe y deja en ella una copia, como un lanzador que sale a mitad."""

        def run(
            cmd: list[str],
            *,
            env: dict[str, str] | None = None,
            cwd: Path | None = None,
            timeout: float | None = None,
        ) -> CompletedProcess[str]:
            environment = dict(env or {})
            seen.append(environment)
            temp = Path(environment.get("TEMP", "no-existe"))
            self.assertTrue(temp.is_dir(), temp)
            # En el %TEMP% compartido no se deja nada (sería ajeno a la prueba).
            if temp.resolve() != Path(tempfile.gettempdir()).resolve():
                (temp / f"{TEMP_COPY_PREFIX}hijo").mkdir()
            return CompletedProcess(list(cmd), 0, "", "")

        return run

    def assertOwnTemp(self, env: dict[str, str]) -> None:
        temp = Path(env.get("TEMP", ""))
        self.assertEqual({env.get(name) for name in ("TMPDIR", "TEMP", "TMP")}, {str(temp)})
        self.assertNotEqual(temp.resolve(), Path(tempfile.gettempdir()).resolve())
        self.assertFalse(temp.exists(), "la carpeta del hijo se borra al terminar")

    def test_blender_child_has_own_temp(self) -> None:
        """RF-001-09: ``run_in_blender`` da al hijo una carpeta temporal propia, con el
        perfil aislado; lo que el hijo deja en ella se puede listar (``leftovers``) y se
        borra con ella, y una copia de otra comprobación en el ``%TEMP%`` compartido sigue
        ahí."""
        seen: list[dict[str, str]] = []
        leftovers: list[str] = []
        with tempfile.TemporaryDirectory(prefix=TEMP_COPY_PREFIX) as other:
            with mock.patch.object(blender, "run", self.recorder(seen)):
                run_in_blender(FAKE_INSTALL, LAUNCHER, leftovers=leftovers)
            self.assertTrue(Path(other).is_dir())
        (env,) = seen
        self.assertOwnTemp(env)
        self.assertIn(blender.ENV_USER_RESOURCES, env)
        self.assertEqual(leftovers, [f"{TEMP_COPY_PREFIX}hijo"])

    def test_check_step_child_has_own_temp(self) -> None:
        """RF-001-09: las órdenes de ``check.py`` que ejecutan estas pruebas
        (``check_step``) también tienen su carpeta temporal propia."""
        seen: list[dict[str, str]] = []
        with temp_tree({"pruebas/__init__.py": SPDX}) as tmp:
            with mock.patch.object(blender, "run", self.recorder(seen)):
                check_step(FAKE_INSTALL, tmp, tmp, lambda ctx: ctx.unittest("pruebas"))
                check_step(FAKE_INSTALL, tmp, tmp, lambda ctx: ctx.blender_tests("pruebas"))
        self.assertEqual(len(seen), 2)
        for env in seen:
            self.assertOwnTemp(env)
        self.assertNotEqual(seen[0]["TEMP"], seen[1]["TEMP"])


class HarnessBudgetTest(unittest.TestCase):
    """Las pruebas del arnés que lanzan Blender no recorren ``tests/blender`` entero: esa
    suite la ejecuta el paso «blender» de ``tools/check.py``, y repetirla dos veces más
    costaba unos 70 s de cada comprobación (RNF-001-01; convergencia de la spec 002,
    T39). Desde la spec 001 0.6 están en ``tests/arnes`` (el paso de ``--completo``;
    T48). Sin lanzar nada: ``locate``, ``run_in_blender`` y ``listing`` del módulo de la
    clase se sustituyen por unos que anotan lo que se lanzaría."""

    def recorded_runs(self, test_class: type[unittest.TestCase]) -> list[tuple[str, ...]]:
        """Llama a ``setUpClass`` de una subclase de ``test_class`` con los lanzamientos
        sustituidos y devuelve, por lanzamiento, los argumentos tras el guion y los
        ficheros de su carpeta de pruebas (``--carpeta``, o ``tests/blender`` junto al
        lanzador)."""
        runs: list[tuple[str, ...]] = []

        def fake_run(
            install: BlenderInstall, script: Path, *args: str, leftovers: list[str] | None = None
        ) -> CompletedProcess[str]:
            if "--carpeta" in args:
                folder = Path(args[args.index("--carpeta") + 1])
            else:
                folder = Path(script).resolve().parents[1] / "tests" / "blender"
            runs.append((*args, "|", *sorted(os.listdir(folder))))
            return CompletedProcess([], 0, "", "")

        probe = type("Sonda", (test_class,), {})
        module = sys.modules[test_class.__module__]
        with (
            mock.patch.object(module, "locate", return_value=FAKE_INSTALL),
            mock.patch.object(module, "run_in_blender", side_effect=fake_run),
            mock.patch.object(module, "listing", return_value={}),
        ):
            probe.setUpClass()  # type: ignore[attr-defined]
        return runs

    def test_real_run_uses_a_small_folder(self) -> None:
        """RNF-001-01, RF-001-09: la ejecución real de ``RealRunTest`` es una sola, con
        ``--carpeta`` y un único fichero de pruebas (habilita la extensión y guarda un
        ``.blend``), no ``tests/blender`` entero."""
        runs = self.recorded_runs(arnes.RealRunTest)
        self.assertEqual(len(runs), 1, runs)
        (run,) = runs
        self.assertEqual(run[0], "--carpeta", run)
        self.assertEqual(run[run.index("|") + 1 :], ("test_real.py",))

    def test_fingerprint_suite_runs_only_registration(self) -> None:
        """RNF-001-01, RF-001-05: la copia con fugas de ``SessionFingerprintTest`` lleva
        en su ``tests/blender`` solo la prueba de registro real y una que habilita y
        deshabilita antes que ella (así su huella de referencia sigue siendo la del
        principio de la sesión), no la suite entera."""
        runs = self.recorded_runs(arnes.SessionFingerprintTest)
        self.assertEqual(len(runs), 3, runs)
        suite = runs[2]
        self.assertNotIn("--carpeta", suite)
        self.assertEqual(
            suite[suite.index("|") + 1 :],
            ("__init__.py", "test_ciclo.py", "test_registration.py"),
        )


class ListingTest(unittest.TestCase):
    def test_listing_sees_changes(self) -> None:
        """RF-001-09: control positivo del listado: ve un fichero nuevo, uno borrado y
        uno cambiado."""
        with temp_tree({"a.txt": "a", "b.txt": "b", "sub/c.txt": "c"}) as tmp:
            before = listing(tmp)
            (tmp / "a.txt").write_text("aa", encoding="utf-8")
            (tmp / "b.txt").unlink()
            (tmp / "sub" / "__pycache__").mkdir()
            after = listing(tmp)
        self.assertEqual(
            listing_changes(before, after),
            ["nuevo: sub/__pycache__/", "borrado: b.txt", "cambiado: a.txt"],
        )


if __name__ == "__main__":
    unittest.main()
