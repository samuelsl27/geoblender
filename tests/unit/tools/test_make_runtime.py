# SPDX-License-Identifier: GPL-3.0-or-later
"""El motor de cálculo de pruebas, ``tools/make_runtime.py`` (spec 004, T30; RF-004-28,
RNF-004-06; plan 004 §5.1 y §7.1).

- Crea el motor en ``<.deps>/runtime/<lock_id>/`` con el mismo código que el producto: carga
  ``jobs/runtime.py`` con ``gbtools.package.load_geoblender`` y lanza la cadena de
  ``RuntimeSetup.install`` (``runtime_install`` → ``runtime_check`` → adopción) con un
  ``JobRunner`` cuya raíz de trabajos es temporal, desde un almacén de ruedas
  (``--wheelhouse``, o ``GEOBLENDER_WHEELHOUSE``) o desde las URL del lock (``--pypi``).
  Cronometra la instalación y da la línea ``RNF-004-06`` (s, MB en disco y de descarga).
- Un motor ya listo no se vuelve a instalar; una rueda que falta en el almacén o una
  descarga que falla terminan con 1 sin dejar ni motor ni carpeta parcial; las opciones que
  no valen, con 2 sin hacer nada.

Ruedas sintéticas (un «numpy» de pruebas con su BLAS y ``gbtestpkg``) en un almacén temporal
y un lock temporal; la «PyPI» son URL ``file://``: ninguna prueba usa la red.
"""

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import make_runtime  # noqa: E402

runtime = import_geoblender("jobs.runtime")

NUMPY_VERSION = "9.8.7"
FAKE_NUMPY = '''"""numpy sintético de las pruebas: lo justo para verificar un motor."""

__version__ = "{version}"
float64 = float


class _Matrix:
    def __init__(self, n):
        self.shape = (n, n)

    def __matmul__(self, other):
        return _Matrix(self.shape[0])


def ones(shape, dtype=None):
    return _Matrix(shape[0])


def show_config(mode="stdout"):
    return {{"Build Dependencies": {{"blas": {{"name": "scipy-openblas"}}}}}}
'''
LOCK_HEADER = (
    'schema = "geoblender.runtime_lock/1"\npython = "3.13"\nplatform = "win_amd64"\n'
)
STORE_VARIABLE = "GEOBLENDER_WHEELHOUSE"


def _wheels(store: Path) -> list:
    """El «numpy» sintético y ``gbtestpkg`` en ``store``."""
    source = FAKE_NUMPY.format(version=NUMPY_VERSION)
    return [
        _support.make_wheel(store, name="numpy", version=NUMPY_VERSION,
                            extra_files={"numpy/__init__.py": source}),
        _support.make_wheel(store),
    ]


def _write_lock(path: Path, wheels: Sequence, url_of: Callable[[object], str]) -> Path:
    """Un lock en TOML con ``wheels`` (sus URL, ``url_of(rueda)``)."""
    tables = []
    for wheel in wheels:
        tables.append(
            "\n[[package]]\n"
            f"name = {json.dumps(wheel.name)}\n"
            f"version = {json.dumps(wheel.version)}\n"
            f"filename = {json.dumps(wheel.filename)}\n"
            f"url = {json.dumps(url_of(wheel))}\n"
            f'sha256 = "{wheel.sha256}"\n'
            f"size = {wheel.size}\n"
            "installed_size = 1000000\n"
            'license = "MIT"\n'
            "bundled_licenses = []\n"
            'required_by = ["004"]\n'
        )
    path.write_text(LOCK_HEADER + "".join(tables), encoding="utf-8", newline="\n")
    return path


def _run(
    argv: Sequence[str],
    *,
    deps: Path,
    lock: Path,
    environ: Mapping[str, str] | None = None,
) -> tuple[int, str, list[Path]]:
    """``make_runtime.main`` con ``deps`` y el lock ``lock``: su código, toda su salida y
    las carpetas temporales que creó (la raíz de trabajos)."""
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(*args: object, **kwargs: object) -> str:
        folder = real_mkdtemp(*args, **kwargs)
        created.append(Path(folder))
        return folder

    out = io.StringIO()
    with (
        mock.patch.object(make_runtime.tempfile, "mkdtemp", side_effect=mkdtemp),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(out),
    ):
        code = make_runtime.main(
            list(argv), root=ROOT, deps_dir=deps, lock_path=lock,
            environ={} if environ is None else environ,
        )
    return code, out.getvalue(), created


class MakeRuntimeTest(unittest.TestCase):
    """RF-004-28, RNF-004-06: el motor de cálculo de pruebas con la cadena del producto."""

    def setUp(self) -> None:
        tmp = _support.jobs_tmp()
        self.tmp = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)
        self.store = self.tmp / "almacen"
        self.wheels = _wheels(self.store)
        self.lock_file = _write_lock(self.tmp / "lock.toml", self.wheels,
                                     lambda w: w.path.as_uri())
        self.lock = runtime.read_lock(self.lock_file)

    def test_creates_the_engine_with_the_product_chain(self) -> None:
        """RF-004-28, RNF-004-06: ``--wheelhouse`` crea el motor de pruebas en
        ``<.deps>/runtime/<lock_id>/`` con la cadena del producto (``ready``, con
        ``runtime.json``: almacén y carpeta, verificación correcta, sin carpeta parcial),
        cronometra la instalación (línea ``RNF-004-06`` con s y MB) y borra su raíz de
        trabajos temporal; ``find_test_runtime`` (el paso «motor» de ``tools/check.py``) no
        lo encuentra antes, con la orden que lo crea, y después da su carpeta ``site``; ya
        listo, no lo vuelve a instalar (también con el almacén de
        ``GEOBLENDER_WHEELHOUSE``)."""
        store, lock_file, lock = self.store, self.lock_file, self.lock
        deps = self.tmp / "deps"
        missing = make_runtime.find_test_runtime(ROOT, {}, deps_dir=deps, lock_path=lock_file)
        self.assertIsNone(missing.site)
        self.assertIn("tools/make_runtime.py", missing.reason)

        code, out, created = _run(["--wheelhouse", str(store)], deps=deps, lock=lock_file)
        self.assertEqual(code, 0, out)
        env = runtime.ComputeEnvironment(deps, lock)
        found = make_runtime.find_test_runtime(ROOT, {}, deps_dir=deps, lock_path=lock_file)
        self.assertEqual(found.site, env.site_dir())
        self.assertEqual(env.path, deps / "runtime" / lock.lock_id)
        self.assertEqual(env.status(), runtime.STATUS_READY, out)
        info = runtime.read_runtime_info(env.path)
        self.assertEqual(info["source"], {"kind": "wheelhouse", "folder": str(store)})
        self.assertIs(info["verification"]["ok"], True)
        self.assertEqual(info["verification"]["numpy"], NUMPY_VERSION)
        self.assertFalse(env.partial_path.exists())
        self.assertIn(lock.lock_id, out)
        self.assertRegex(out, r"RNF-004-06: .*\d+,\d+ s.*\d+,\d+ MB")
        self.assertTrue(created, "sin raíz de trabajos temporal")
        for folder in created:
            self.assertFalse(folder.exists(), f"queda {folder}")

        # Ya listo: no se instala otra vez (el almacén, de la variable).
        for argv, environ in (
            (["--wheelhouse", str(store)], {}),
            ([], {STORE_VARIABLE: str(store)}),
        ):
            with self.subTest(ya_listo=argv):
                code, out, created = _run(argv, deps=deps, lock=lock_file, environ=environ)
                self.assertEqual(code, 0, out)
                self.assertIn("ya está listo", out)
                self.assertEqual(created, [])

    def test_failures_leave_nothing(self) -> None:
        """RF-004-28: una rueda que falta en el almacén (antes de lanzar nada) o una
        descarga de ``--pypi`` que falla (en el trabajo de instalación) terminan con 1 y
        el mensaje del §8, sin motor ni carpeta parcial ni raíz de trabajos."""
        empty = self.tmp / "vacio"
        empty.mkdir()
        gone = _write_lock(self.tmp / "lock_pypi.toml", self.wheels,
                           lambda w: (self.tmp / "no_esta" / w.filename).as_uri())
        for name, argv, lock_path, expected in (
            ("sin rueda", ["--wheelhouse", str(empty)], self.lock_file, "No se encuentra"),
            ("descarga", ["--pypi"], gone, "No se pudo descargar"),
        ):
            with self.subTest(fallo=name):
                folder = self.tmp / name.replace(" ", "_")
                code, out, created = _run(argv, deps=folder, lock=lock_path)
                self.assertEqual(code, 1, out)
                self.assertIn(expected, out)
                failed = runtime.ComputeEnvironment(folder, runtime.read_lock(lock_path))
                self.assertEqual(failed.status(), runtime.STATUS_MISSING)
                self.assertFalse(failed.partial_path.exists())
                for made in created:
                    self.assertFalse(made.exists(), f"queda {made}")

    def test_invalid_options_do_nothing(self) -> None:
        """RF-004-28: sin origen de las ruedas, con un almacén que no existe, con
        ``--wheelhouse`` y ``--pypi`` a la vez, sin la carpeta o con una opción que no
        existe, código 2 sin crear nada."""
        for argv in (
            [],
            ["--wheelhouse", str(self.tmp / "no_existe")],
            ["--wheelhouse", str(self.store), "--pypi"],
            ["--wheelhouse"],
            ["--otra"],
        ):
            with self.subTest(opciones=argv):
                folder = self.tmp / "uso"
                code, out, created = _run(argv, deps=folder, lock=self.lock_file)
                self.assertEqual(code, 2, out)
                self.assertFalse(folder.exists())
                self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
