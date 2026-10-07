# SPDX-License-Identifier: GPL-3.0-or-later
"""Lock del motor de cálculo (spec 004, T24; RF-004-21; plan 004 §5.2.5; ADR-0009 y
ADR-0017).

- ``jobs.runtime.compute_lock_id``: 12 hexadecimales del sha256 de la forma canónica
  (``schema``, ``python``, ``platform`` y ``{name, version, sha256}`` de cada paquete,
  ordenados por nombre): no cambia al reordenar los paquetes ni con lo que no los
  identifica (url, tamaños, licencias); cambia con una huella o una versión.
- ``jobs.runtime.read_lock``: lee ``jobs/runtime_lock.toml`` (por defecto, el del paquete)
  y rechaza con ``LockError`` el que no cumple su esquema.
- ``tools/check_licenses.py`` (``gbtools.runtime_lock``, LIC-01) valida el lock con la
  evaluación de ADR-0017 §3: rechaza un paquete sin sha256, con una licencia fuera de la
  lista o con etiquetas que no son ``cp313-win_amd64`` / ``py3-none-any``; numpy sí entra
  (ADR-0017 §6), y el lock real de numpy 2.5.3 pasa.
- ``tools/lock_runtime.py``: rellena ``filename``, ``url``, ``sha256``, ``size``,
  ``installed_size`` y ``license`` con la API JSON de PyPI y la rueda (del almacén o
  descargada), conservando lo que escribe la persona; una rueda con DLL en
  ``<paquete>.libs/`` y ``bundled_licenses`` vacío, o con otra huella, termina con error y
  no escribe nada (ADR-0017 §4).

Ruedas sintéticas (``gbtestpkg``) y un PyPI simulado: ninguna prueba usa la red ni lanza
``pip`` (el tamaño instalado lo da un instalador simulado).
"""

import contextlib
import io
import json
import unittest
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

import lock_runtime  # noqa: E402
from gbtools import runtime_lock, wheels  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402

runtime = import_geoblender("jobs.runtime")

LOCK_RELPATH = runtime_lock.LOCK_RELPATH
SHA_A = "a" * 64
NUMPY_SHA = "71cad2b2a7451ab79d8f5e71b453485b6775963d5cf794179144a7463fe6e8ec"
NUMPY_LICENSE = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
NUMPY_BUNDLED = [
    "BSD-3-Clause-Open-MPI",
    "GPL-3.0-or-later WITH GCC-exception-3.1",
    "LicenseRef-MSVC-Runtime",
]
FILES_URL = "https://files.pythonhosted.org/packages/aa/bb/"
HEADER = {"schema": "geoblender.runtime_lock/1", "python": "3.13", "platform": "win_amd64"}
PACKAGE: Mapping[str, object] = {
    "name": "gbtestpkg",
    "version": "1.0.0",
    "filename": "gbtestpkg-1.0.0-py3-none-any.whl",
    "url": FILES_URL + "gbtestpkg-1.0.0-py3-none-any.whl",
    "sha256": SHA_A,
    "size": 1234,
    "installed_size": 5678,
    "license": "MIT",
    "bundled_licenses": [],
    "required_by": ["004"],
}
OTHER: Mapping[str, object] = dict(
    PACKAGE,
    name="otropkg",
    version="2.0.0",
    filename="otropkg-2.0.0-cp313-cp313-win_amd64.whl",
    url=FILES_URL + "otropkg-2.0.0-cp313-cp313-win_amd64.whl",
    sha256="b" * 64,
)


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, Sequence):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return str(value)


def _lock_text(
    *packages: Mapping[str, object], header: Mapping[str, object] = HEADER
) -> str:
    """Texto de un lock con ``header`` y una tabla ``[[package]]`` por paquete."""
    parts = [f"{key} = {_value(value)}\n" for key, value in header.items()]
    for package in packages:
        parts.append("\n[[package]]\n")
        parts.extend(f"{key} = {_value(value)}\n" for key, value in package.items())
    return "".join(parts)


def _package(base: Mapping[str, object] = PACKAGE, **changes: object) -> dict[str, object]:
    """``base`` con cambios; un valor ``None`` quita la clave."""
    package = dict(base)
    for key, value in changes.items():
        if value is None:
            package.pop(key, None)
        else:
            package[key] = value
    return package


def _parsed(*packages: Mapping[str, object]) -> object:
    with temp_tree({LOCK_RELPATH: _lock_text(*packages)}) as root:
        return runtime.read_lock(root / LOCK_RELPATH)


def _lock_findings(*packages: Mapping[str, object], **kwargs: object) -> list:
    with temp_tree({LOCK_RELPATH: _lock_text(*packages, **kwargs)}) as root:
        return runtime_lock.check(root)


# Tres pruebas con varias comprobaciones cada una: tools/check.py reparte las unitarias
# en 4 procesos por número de pruebas (gbtools.parts) y más pruebas aquí movían módulos
# lentos a la misma parte (RNF-001-01, docs/trampas.md §4).
class LockIdTest(unittest.TestCase):
    def test_lock_id(self) -> None:
        """RF-004-21: el ``lock_id`` tiene 12 hexadecimales y es el mismo con los paquetes
        en otro orden o con el nombre escrito de otra forma (PEP 503); cambia si cambia
        la huella o la versión de un paquete, o la cabecera. La url, los tamaños, las
        licencias y ``required_by`` no lo cambian: dos locks con los mismos paquetes dan
        la misma carpeta del motor."""
        self.identity_only()
        base = _parsed(PACKAGE, OTHER)
        lock_id = runtime.compute_lock_id(base)
        self.assertRegex(lock_id, r"\A[0-9a-f]{12}\Z")
        self.assertEqual(base.lock_id, lock_id)
        self.assertEqual(runtime.compute_lock_id(_parsed(OTHER, PACKAGE)), lock_id)
        self.assertEqual(
            runtime.compute_lock_id(_parsed(_package(name="GbTestPkg"), OTHER)), lock_id
        )
        changed = {
            "huella": _parsed(_package(sha256="c" * 64), OTHER),
            "versión": _parsed(
                _package(
                    version="1.0.1",
                    filename="gbtestpkg-1.0.1-py3-none-any.whl",
                ),
                OTHER,
            ),
            "un paquete menos": _parsed(PACKAGE),
        }
        for case, lock in changed.items():
            with self.subTest(caso=case):
                self.assertNotEqual(runtime.compute_lock_id(lock), lock_id)
        with temp_tree(
            {LOCK_RELPATH: _lock_text(PACKAGE, OTHER, header=dict(HEADER, python="3.14"))}
        ) as root:
            other_python = runtime.read_lock(root / LOCK_RELPATH)
        self.assertNotEqual(runtime.compute_lock_id(other_python), lock_id)

    def identity_only(self) -> None:
        """Solo ``{name, version, sha256}`` y la cabecera cuentan (forma canónica)."""
        lock_id = runtime.compute_lock_id(_parsed(PACKAGE))
        other = _package(
            url="https://files.pythonhosted.org/packages/cc/dd/"
            "gbtestpkg-1.0.0-py3-none-any.whl",
            size=1,
            installed_size=2,
            license="Apache-2.0",
            bundled_licenses=["Zlib"],
            required_by=["004", "006"],
        )
        self.assertEqual(runtime.compute_lock_id(_parsed(other)), lock_id)
        self.assertEqual(
            runtime.canonical_lock(_parsed(PACKAGE)),
            json.dumps(
                {
                    "package": [
                        {"name": "gbtestpkg", "sha256": SHA_A, "version": "1.0.0"}
                    ],
                    "platform": "win_amd64",
                    "python": "3.13",
                    "schema": "geoblender.runtime_lock/1",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


class LockFileTest(unittest.TestCase):
    def test_read_and_check_the_lock(self) -> None:
        """RF-004-21: ``read_lock`` lee un lock y rechaza con ``LockError`` el que no cumple
        su esquema; ``check_licenses`` rechaza un paquete sin sha256, con una licencia
        fuera de la lista o con etiquetas que no son ``cp313-win_amd64`` /
        ``py3-none-any``, admite numpy en el lock y no en ``tools/wheels.toml``, y acepta
        el lock real de numpy 2.5.3 según ADR-0017."""
        self.reads_a_lock()
        self.rejects_a_broken_lock()
        self.real_lock_is_numpy_and_passes_the_licenses()
        self.rejects_hash_license_and_tag()
        self.numpy_only_in_the_lock()

    def reads_a_lock(self) -> None:
        """``read_lock`` devuelve la cabecera y cada paquete con sus campos (listas como
        tuplas, huella en minúsculas)."""
        lock = _parsed(_package(sha256="A" * 64), OTHER)
        self.assertEqual((lock.schema, lock.python, lock.platform), tuple(HEADER.values()))
        self.assertEqual([p.name for p in lock.packages], ["gbtestpkg", "otropkg"])
        first = lock.packages[0]
        self.assertEqual(first.sha256, SHA_A)
        self.assertEqual((first.size, first.installed_size), (1234, 5678))
        self.assertEqual(first.bundled_licenses, ())
        self.assertEqual(first.required_by, ("004",))
        self.assertEqual(lock.package("GBTESTPKG"), first)
        self.assertIsNone(lock.package("numpy"))

    def rejects_a_broken_lock(self) -> None:
        """Un lock que no cumple su esquema da ``LockError`` (un ``ValueError``) que dice
        qué falla: otro esquema, sin paquetes, un paquete sin huella o con una mal
        formada, un tamaño que no es un entero, una clave desconocida, un paquete
        repetido, TOML roto o un fichero que no existe."""
        cases = {
            "otro esquema": _lock_text(PACKAGE, header=dict(HEADER, schema="otro/1")),
            "sin paquetes": _lock_text(),
            "sin huella": _lock_text(_package(sha256=None)),
            "huella mal formada": _lock_text(_package(sha256="g" * 64)),
            "tamaño no entero": _lock_text(_package(size="1234")),
            "tamaño booleano": _lock_text(_package(installed_size=True)),
            "clave desconocida": _lock_text(_package(licence="MIT")),
            "repetido": _lock_text(PACKAGE, _package(name="GbTestPkg")),
            "TOML roto": "schema = \n",
        }
        for case, text in cases.items():
            with self.subTest(caso=case), temp_tree({LOCK_RELPATH: text}) as root:
                with self.assertRaises(runtime.LockError) as caught:
                    runtime.read_lock(root / LOCK_RELPATH)
                self.assertIsInstance(caught.exception, ValueError)
                self.assertTrue(str(caught.exception))
        with temp_tree({}) as root, self.assertRaises(runtime.LockError):
            runtime.read_lock(root / LOCK_RELPATH)


    def real_lock_is_numpy_and_passes_the_licenses(self) -> None:
        """El lock del paquete fija numpy 2.5.3 de PyPI (huella de la auditoría de
        ADR-0017, 12 560 965 bytes, tamaño instalado medido) con su licencia y sus
        componentes incluidos, lo pide la 004, y ``tools/check_licenses.py`` lo
        acepta."""
        self.assertEqual(runtime.LOCK_PATH, ROOT / LOCK_RELPATH)
        lock = runtime.read_lock()
        self.assertEqual(
            (lock.schema, lock.python, lock.platform),
            ("geoblender.runtime_lock/1", "3.13", "win_amd64"),
        )
        self.assertEqual([p.name for p in lock.packages], ["numpy"])
        numpy = lock.packages[0]
        self.assertEqual(numpy.version, "2.5.3")
        self.assertEqual(numpy.filename, "numpy-2.5.3-cp313-cp313-win_amd64.whl")
        self.assertTrue(numpy.url.startswith("https://files.pythonhosted.org/"))
        self.assertTrue(numpy.url.endswith("/" + numpy.filename))
        self.assertEqual(numpy.sha256, NUMPY_SHA)
        self.assertEqual(numpy.size, 12_560_965)
        self.assertGreater(numpy.installed_size, numpy.size)
        self.assertEqual(numpy.license, NUMPY_LICENSE)
        self.assertLessEqual(set(NUMPY_BUNDLED), set(numpy.bundled_licenses))
        self.assertEqual(numpy.required_by, ("004",))
        self.assertRegex(lock.lock_id, r"\A[0-9a-f]{12}\Z")
        findings = runtime_lock.check(ROOT)
        self.assertEqual(findings, [], format_findings(findings))

    def rejects_hash_license_and_tag(self) -> None:
        """LIC-01: ``check_licenses`` rechaza un paquete del lock sin sha256, con una
        licencia fuera de la lista (también en ``bundled_licenses``) o con etiquetas que
        no son ``cp313-win_amd64`` / ``py3-none-any``; acepta uno bien."""
        self.assertEqual(_lock_findings(PACKAGE, OTHER), [])
        cases = {
            "sin sha256": _package(sha256=None),
            "sha256 corto": _package(sha256="a" * 63),
            "licencia fuera": _package(license="GPL-3.0-only"),
            "LicenseRef sin ADR": _package(license="LicenseRef-propia"),
            "incluida fuera": _package(bundled_licenses=["GPL-3.0-or-later"]),
            "cp312": _package(filename="gbtestpkg-1.0.0-cp312-cp312-win_amd64.whl"),
            "manylinux": _package(
                filename="gbtestpkg-1.0.0-cp313-cp313-manylinux_2_28_x86_64.whl"
            ),
            "url fuera de PyPI": _package(url="https://example.org/gbtestpkg.whl"),
            "tamaño por medir": _package(installed_size=0),
            "sin required_by": _package(required_by=[]),
        }
        for case, package in cases.items():
            with self.subTest(caso=case):
                findings = _lock_findings(package)
                self.assertTrue(findings, case)
                self.assertEqual({f.rule for f in findings}, {"LIC-01"}, case)
                self.assertEqual({f.path for f in findings}, {LOCK_RELPATH}, case)
                self.assertIn("gbtestpkg", format_findings(findings), case)
        wrong_header = _lock_findings(PACKAGE, header=dict(HEADER, platform="win32"))
        self.assertEqual({f.rule for f in wrong_header}, {"LIC-01"})
        with temp_tree({}) as root:
            self.assertEqual({f.rule for f in runtime_lock.check(root)}, {"LIC-01"})

    def numpy_only_in_the_lock(self) -> None:
        """ADR-0017 §6: la expresión real de numpy con sus tres componentes incluidos pasa
        en el lock, y la misma rueda en ``tools/wheels.toml`` falla solo porque numpy
        está prohibido allí (ADR-0009)."""
        numpy = _package(
            name="numpy",
            version="2.5.3",
            filename="numpy-2.5.3-cp313-cp313-win_amd64.whl",
            url=FILES_URL + "numpy-2.5.3-cp313-cp313-win_amd64.whl",
            sha256=NUMPY_SHA,
            license=NUMPY_LICENSE,
            bundled_licenses=NUMPY_BUNDLED,
        )
        self.assertEqual(_lock_findings(numpy), [])
        entry = {
            "name": "numpy",
            "version": "2.5.3",
            "filename": "numpy-2.5.3-cp313-cp313-win_amd64.whl",
            "sha256": NUMPY_SHA,
            "license": NUMPY_LICENSE,
            "bundled_licenses": NUMPY_BUNDLED,
            "target": "dev",
            "spec": "004",
            "adr": "ADR-0009",
        }
        problems = wheels.entry_problems(entry)
        self.assertEqual([key for key, _ in problems], ["name"])
        self.assertIn("prohibida", problems[0][1])


@contextlib.contextmanager
def _tool_tree(
    package: Mapping[str, object], wheel: _support.SyntheticWheel | None = None
) -> Iterator[Path]:
    """Árbol con el lock de ``package`` (con un comentario de la auditoría que la
    herramienta debe conservar) y un almacén con ``wheel``."""
    text = _lock_text(package).replace(
        "bundled_licenses =", "# auditoría de la persona\nbundled_licenses ="
    )
    files: dict[str, str | bytes] = {LOCK_RELPATH: text, "almacen/": ""}
    if wheel is not None:
        files[f"almacen/{wheel.filename}"] = wheel.path.read_bytes()
    with temp_tree(files) as root:
        yield root


def _pypi(wheel: _support.SyntheticWheel, *, sha256: str | None = None):
    """Un PyPI simulado: solo responde al JSON de ``wheel``; la descarga, prohibida."""
    requested: list[str] = []

    def opener(url: object, timeout: float | None = None) -> io.BytesIO:
        text = str(getattr(url, "full_url", url))
        requested.append(text)
        expected = lock_runtime.PYPI_JSON.format(name=wheel.name, version=wheel.version)
        if text != expected:
            raise AssertionError(f"URL inesperada: {text}")
        body = {
            "urls": [
                {
                    "filename": f"{wheel.name}-{wheel.version}.tar.gz",
                    "packagetype": "sdist",
                    "url": FILES_URL + f"{wheel.name}-{wheel.version}.tar.gz",
                    "digests": {"sha256": "0" * 64},
                    "size": 10,
                },
                {
                    "filename": wheel.filename,
                    "packagetype": "bdist_wheel",
                    "url": FILES_URL + wheel.filename,
                    "digests": {"sha256": sha256 or wheel.sha256},
                    "size": wheel.size,
                },
            ]
        }
        return io.BytesIO(json.dumps(body).encode("utf-8"))

    return opener, requested


def _run_tool(root: Path, opener: object, installed: list[Path]) -> tuple[int, str]:
    def installer(wheel: Path, work: Path) -> int:
        installed.append(wheel)
        return 4321

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = lock_runtime.main(
            ["--desde", str(root / "almacen")],
            root=root,
            environ={},
            opener=opener,
            installer=installer,
        )
    return code, out.getvalue()


class LockRuntimeToolTest(unittest.TestCase):
    def test_lock_runtime_tool(self) -> None:
        """RF-004-21: ``tools/lock_runtime.py`` rellena el lock desde PyPI y la rueda;
        una rueda con DLL sin auditar (``bundled_licenses = []``) o con otra huella
        termina con error y no escribe nada (ADR-0017 §4); el tamaño instalado se mide
        con ``pip`` aislado en una carpeta de destino."""
        self.fills_the_lock_from_pypi_and_the_store()
        self.native_libraries_need_bundled_licenses()
        self.pip_command_installs_only_the_wheel()

    def fills_the_lock_from_pypi_and_the_store(self) -> None:
        """La herramienta toma de PyPI el fichero, la url y la huella, comprueba que la
        rueda del almacén es esa, copia su ``License-Expression``, mide el tamaño
        instalado y reescribe solo esos campos (el comentario de la auditoría se
        conserva); el lock resultante lo leen el producto y ``check_licenses``, y da el
        ``lock_id`` que imprime."""
        with _support.jobs_tmp() as tmp:
            wheel = _support.make_wheel(tmp, license_expression="MIT OR Apache-2.0")
            stale = _package(
                filename=None, url=None, sha256=None, size=None, installed_size=None
            )
            with _tool_tree(stale, wheel) as root:
                opener, requested = _pypi(wheel)
                installed: list[Path] = []
                code, out = _run_tool(root, opener, installed)
                self.assertEqual(code, 0, out)
                text = (root / LOCK_RELPATH).read_text(encoding="utf-8")
                lock = runtime.read_lock(root / LOCK_RELPATH)
                findings = runtime_lock.check(root)
        self.assertEqual(findings, [], format_findings(findings))
        self.assertEqual(len(requested), 1)
        self.assertEqual([path.name for path in installed], [wheel.filename])
        package = lock.packages[0]
        self.assertEqual(package.filename, wheel.filename)
        self.assertEqual(package.url, FILES_URL + wheel.filename)
        self.assertEqual(package.sha256, wheel.sha256)
        self.assertEqual(package.size, wheel.size)
        self.assertEqual(package.installed_size, 4321)
        self.assertEqual(package.license, "MIT OR Apache-2.0")
        self.assertIn("# auditoría de la persona\nbundled_licenses = []\n", text)
        self.assertNotIn("\r", text)
        self.assertIn(lock.lock_id, out)

    def native_libraries_need_bundled_licenses(self) -> None:
        """ADR-0017 §4: una rueda con ``<paquete>.libs/a.dll`` y ``bundled_licenses =
        []`` termina con error y no escribe nada (ni instala); con una huella de PyPI
        que no es la del almacén, igual."""
        with _support.jobs_tmp() as tmp:
            native = _support.make_wheel(
                tmp / "nativa",
                license_expression="MIT",
                extra_files={"gbtestpkg.libs/a.dll": "no es una DLL de verdad\n"},
            )
            plain = _support.make_wheel(tmp / "pura", license_expression="MIT")
            cases = {
                "DLL sin auditar": (native, _pypi(native)[0], "a.dll"),
                "otra huella": (plain, _pypi(plain, sha256="f" * 64)[0], "f" * 64),
            }
            for case, (wheel, opener, mention) in cases.items():
                with self.subTest(caso=case), _tool_tree(PACKAGE, wheel) as root:
                    before = (root / LOCK_RELPATH).read_bytes()
                    installed: list[Path] = []
                    code, out = _run_tool(root, opener, installed)
                    self.assertEqual(code, 1, out)
                    self.assertIn(mention, out)
                    self.assertEqual((root / LOCK_RELPATH).read_bytes(), before)
                    self.assertEqual(installed, [])
                    leftovers = sorted(p.name for p in (root / LOCK_RELPATH).parent.iterdir())
                    self.assertEqual(leftovers, [Path(LOCK_RELPATH).name])

    def pip_command_installs_only_the_wheel(self) -> None:
        """El tamaño instalado se mide con el ``pip`` del intérprete en modo aislado, sin
        índice ni dependencias, solo ruedas y sin caché, en una carpeta de destino (nunca
        en el ``site-packages`` de Blender)."""
        python, wheel, target = Path("py.exe"), Path("w.whl"), Path("destino")
        command = lock_runtime.pip_command(python, wheel, target)
        self.assertEqual(command[:5], [str(python), "-B", "-I", "-m", "pip"])
        for flag in (
            "--isolated", "--no-index", "--no-deps", "--only-binary=:all:",
            "--no-cache-dir", "--disable-pip-version-check",
        ):
            with self.subTest(opcion=flag):
                self.assertIn(flag, command)
        self.assertEqual(command[command.index("--target") + 1], str(target))
        self.assertEqual(command[-1], str(wheel))


if __name__ == "__main__":
    unittest.main()
