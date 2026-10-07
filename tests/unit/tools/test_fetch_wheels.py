# SPDX-License-Identifier: GPL-3.0-or-later
"""Descarga de las ruedas fijadas, ``tools/fetch_wheels.py`` (plan 001 §5.4.12).

- RF-001-25: deja en ``geoblender/wheels/`` exactamente las ruedas de destino
  «extension», en ``.deps/site/`` las de los dos destinos extraídas y en el manifiesto
  su lista, sin cambiar el resto del fichero; una rueda cuyo sha256 no coincide con el
  fijado no se acepta: no cambia nada y la nombra con los dos hashes. Si
  ``tools/wheels.toml`` no cumple LIC-01, sale sin tocar nada.

Las ruedas son sintéticas (zips mínimos creados con ``zipfile``) y llegan de una carpeta
local (``--desde`` o ``GEOBLENDER_WHEELHOUSE``) o de un PyPI simulado: ninguna prueba
usa la red.
"""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.support.repo import (
    EMPTY_WHEELS_TOML,
    EXT,
    manifest_without_wheels,
    tools_on_path,
)
from tests.support.trees import temp_tree

tools_on_path()

import fetch_wheels  # noqa: E402
from gbtools import manifest, wheels  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402

MANIFEST = manifest.MANIFEST_RELPATH
TOML = wheels.WHEELS_TOML_RELPATH
ENV = "GEOBLENDER_WHEELHOUSE"
STORE = "almacen"
SITE = ".deps/site"
WHEELS_DIR = f"{EXT}/wheels"


def _wheel(
    name: str, version: str, salt: str = "", extra: Sequence[str] = ()
) -> bytes:
    """Una rueda mínima: el paquete y su ``.dist-info`` (y los ficheros ``extra``)."""
    info = f"{name}-{version}.dist-info"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}/__init__.py", f"# rueda sintética {salt}\n")
        for member in extra:
            archive.writestr(member, b"MZ sintetica")
        archive.writestr(
            f"{info}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        )
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
        archive.writestr(f"{info}/RECORD", "")
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Wheel:
    """Una rueda fijada y los bytes que tiene el almacén."""

    name: str
    version: str
    filename: str
    target: str
    data: bytes
    pinned: str  # sha256 fijado en tools/wheels.toml

    def entry(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "filename": self.filename,
            "sha256": self.pinned,
            "license": "MIT",
            "bundled_licenses": [],
            "target": self.target,
            "spec": "006",
            "adr": "ADR-0010",
        }


def _make(name: str, version: str, target: str, filename: str | None = None) -> Wheel:
    data = _wheel(name, version)
    filename = filename or f"{name}-{version}-cp313-cp313-win_amd64.whl"
    return Wheel(name, version, filename, target, data, _sha(data))


PYPROJ = _make("pyproj", "3.8.0", "extension")
DUCKDB = _make("duckdb", "1.5.7", "dev")
TOMLI = _make("tomli_w", "1.2.0", "extension", "tomli_w-1.2.0-py3-none-any.whl")


def _value(value: object) -> str:
    if isinstance(value, str):
        return '"' + value + '"'
    if isinstance(value, Sequence):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return str(value)


def _toml(*entries: Mapping[str, object]) -> str:
    parts = ["schema_version = 1\n"]
    for entry in entries:
        parts.append("\n[[wheel]]\n")
        parts.extend(f"{key} = {_value(value)}\n" for key, value in entry.items())
    return "".join(parts)


@contextlib.contextmanager
def _project(
    pinned: Sequence[Wheel] = (),
    *,
    store: Sequence[Wheel] = (),
    extra: Mapping[str, str | bytes] | None = None,
    toml_text: str | None = None,
) -> Iterator[Path]:
    """Árbol con ``tools/wheels.toml``, el manifiesto real sin ruedas (no depende de las
    que fije cada spec: T45) y un almacén local con las ruedas de ``store`` (con sus
    bytes)."""
    files: dict[str, str | bytes] = {
        TOML: toml_text if toml_text is not None else _toml(*(w.entry() for w in pinned)),
        MANIFEST: manifest_without_wheels(),
        f"{STORE}/": "",
    }
    for wheel in store:
        files[f"{STORE}/{wheel.filename}"] = wheel.data
    files.update(extra or {})
    with temp_tree(files) as root:
        yield root


@dataclass
class Outcome:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


def _no_network(*args: object, **kwargs: object) -> object:
    raise AssertionError("la prueba no debe usar la red")


def _run(
    root: Path,
    *args: str,
    environ: Mapping[str, str] | None = None,
    opener: object = _no_network,
) -> Outcome:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fetch_wheels.main(
            list(args), root=root, environ=dict(environ or {}), opener=opener
        )
    return Outcome(code, out.getvalue(), err.getvalue())


def _from_store(root: Path, *args: str) -> Outcome:
    return _run(root, "--desde", str(root / STORE), *args)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int] | None]:
    """Contenido y ``mtime_ns`` de cada fichero bajo ``root`` (las carpetas, ``None``)."""
    entries: dict[str, tuple[bytes, int] | None] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            entries[rel + "/"] = None
        else:
            entries[rel] = (path.read_bytes(), path.stat().st_mtime_ns)
    return entries


def _files(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _temp_work_folders() -> set[str]:
    return {
        name
        for name in os.listdir(tempfile.gettempdir())
        if name.startswith(fetch_wheels.TEMP_PREFIX)
    }


STALE = {
    f"{WHEELS_DIR}/vieja-1.0-py3-none-any.whl": b"rueda vieja",
    f"{WHEELS_DIR}/LEEME.txt": "sobrante\n",
    f"{SITE}/viejo/__init__.py": "# extraído antes\n",
}


class FetchTest(unittest.TestCase):
    def test_empty_list(self) -> None:
        """RF-001-25: con la lista vacía (un ``tools/wheels.toml`` sin ruedas, con el
        esquema comentado; no el real, que fijará ruedas: T45), la orden no usa la red,
        deja el manifiesto byte a byte igual (y sin reescribirlo), quita lo que sobraba
        en ``geoblender/wheels/`` y deja ``.deps/site/`` vacía."""
        toml_text = EMPTY_WHEELS_TOML + '# name = "duckdb"\n# target = "extension"\n'
        with _project(toml_text=toml_text, extra=STALE) as root:
            path = root / MANIFEST
            past = time.time() - 3600
            os.utime(path, (past, past))
            before = path.read_bytes(), path.stat().st_mtime_ns
            result = _run(root)
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertFalse((root / WHEELS_DIR).exists())
            self.assertTrue((root / SITE).is_dir())
            self.assertEqual(list((root / SITE).iterdir()), [])
            findings = wheels.check(root)
            self.assertEqual(findings, [], format_findings(findings))
        self.assertIn("manifiesto sin cambios", result.out)

    def test_extension_wheel(self) -> None:
        """RF-001-25: una rueda «extension» queda en ``geoblender/wheels/`` (sola, con el
        sha256 fijado), extraída en ``.deps/site/`` y en la lista del manifiesto; LIC-02
        queda coherente. La carpeta sale de ``--desde`` o, sin ella, de
        ``GEOBLENDER_WHEELHOUSE``."""
        for how in ("--desde", ENV):
            with self.subTest(origen=how), _project(
                [PYPROJ], store=[PYPROJ], extra=STALE
            ) as root:
                if how == ENV:
                    result = _run(root, environ={ENV: str(root / STORE)})
                else:
                    result = _from_store(root)
                self.assertEqual(result.code, 0, result.text)
                self.assertEqual(_files(root / WHEELS_DIR), [PYPROJ.filename])
                stored = (root / WHEELS_DIR / PYPROJ.filename).read_bytes()
                self.assertEqual(_sha(stored), PYPROJ.pinned)
                self.assertEqual(
                    _files(root / SITE),
                    [
                        "pyproj-3.8.0.dist-info/METADATA",
                        "pyproj-3.8.0.dist-info/RECORD",
                        "pyproj-3.8.0.dist-info/WHEEL",
                        "pyproj/__init__.py",
                    ],
                )
                data = manifest.load(root / MANIFEST)
                self.assertEqual(manifest.wheel_files(data), [f"./wheels/{PYPROJ.filename}"])
                findings = wheels.check(root)
                self.assertEqual(findings, [], format_findings(findings))
                self.assertIn(PYPROJ.filename, result.out)

    def test_dev_wheel_only_in_deps(self) -> None:
        """RF-001-25: una rueda «dev» solo se extrae en ``.deps/site/``: ni va a
        ``geoblender/wheels/`` ni a la lista del manifiesto, que no cambia."""
        with _project([DUCKDB, PYPROJ], store=[DUCKDB, PYPROJ]) as root:
            result = _from_store(root)
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual(_files(root / WHEELS_DIR), [PYPROJ.filename])
            site = _files(root / SITE)
            self.assertIn("duckdb/__init__.py", site)
            self.assertIn("pyproj/__init__.py", site)
            data = manifest.load(root / MANIFEST)
            self.assertEqual(manifest.wheel_files(data), [f"./wheels/{PYPROJ.filename}"])

        with _project([DUCKDB], store=[DUCKDB]) as root:
            before = (root / MANIFEST).read_bytes()
            result = _from_store(root)
            self.assertEqual(result.code, 0, result.text)
            self.assertFalse((root / WHEELS_DIR).exists())
            self.assertIn("duckdb/__init__.py", _files(root / SITE))
            self.assertEqual((root / MANIFEST).read_bytes(), before)

    def test_hash_mismatch_changes_nothing(self) -> None:
        """RF-001-25: si una rueda no tiene el sha256 fijado, la orden termina con 1,
        nombra la rueda con los dos hashes y no cambia nada: ni ``geoblender/wheels/``,
        ni ``.deps/site/``, ni el manifiesto (todo o nada). Lo mismo si falta una rueda
        en el almacén, si una no es un zip válido o si trae DLL en ``<paquete>.libs/``
        con ``bundled_licenses`` vacío (ADR-0017 §4: sin auditar)."""
        tampered = Wheel(
            DUCKDB.name,
            DUCKDB.version,
            DUCKDB.filename,
            DUCKDB.target,
            _wheel(DUCKDB.name, DUCKDB.version, salt="alterada"),
            DUCKDB.pinned,
        )
        with _project([PYPROJ, DUCKDB], store=[PYPROJ, tampered], extra=STALE) as root:
            before = _snapshot(root)
            folders = _temp_work_folders()
            result = _from_store(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertIn(DUCKDB.filename, result.text)
            self.assertIn(DUCKDB.pinned, result.text)
            self.assertIn(_sha(tampered.data), result.text)
            self.assertEqual(_snapshot(root), before)
            self.assertEqual(_temp_work_folders(), folders)

        with _project([PYPROJ, DUCKDB], store=[PYPROJ], extra=STALE) as root:
            before = _snapshot(root)
            result = _from_store(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertIn(DUCKDB.filename, result.text)
            self.assertEqual(_snapshot(root), before)

        bad = b"no es un zip"
        broken = Wheel("roto", "1.0", "roto-1.0-py3-none-any.whl", "dev", bad, _sha(bad))
        with _project([PYPROJ, broken], store=[PYPROJ, broken], extra=STALE) as root:
            before = _snapshot(root)
            result = _from_store(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertIn(broken.filename, result.text)
            self.assertEqual(_snapshot(root), before)

        native = _wheel("nativa", "1.0", extra=["nativa.libs/a.dll"])
        unaudited = Wheel(
            "nativa", "1.0", "nativa-1.0-cp313-cp313-win_amd64.whl", "dev", native,
            _sha(native),
        )
        with _project([PYPROJ, unaudited], store=[PYPROJ, unaudited], extra=STALE) as root:
            before = _snapshot(root)
            result = _from_store(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertIn(unaudited.filename, result.text)
            self.assertIn("nativa.libs/a.dll", result.text)
            self.assertIn("bundled_licenses", result.text)
            self.assertEqual(_snapshot(root), before)

    def test_manifest_rewrite_preserves_rest(self) -> None:
        """RF-001-25: en el manifiesto solo cambia el bloque ``wheels = [...]``; el resto
        queda byte a byte igual, en UTF-8 sin BOM y con finales LF."""
        original = manifest_without_wheels()
        text = original.replace(
            "wheels = []\n", "# Ruedas: las escribe tools/fetch_wheels.py\nwheels = []\n"
        )
        self.assertNotEqual(text, original)
        with _project([TOMLI, PYPROJ], store=[TOMLI, PYPROJ]) as root:
            (root / MANIFEST).write_bytes(text.encode("utf-8"))
            result = _from_store(root)
            self.assertEqual(result.code, 0, result.text)
            written = (root / MANIFEST).read_bytes()
        block = (
            "wheels = [\n"
            f'  "./wheels/{TOMLI.filename}",\n'
            f'  "./wheels/{PYPROJ.filename}",\n'
            "]"
        )
        self.assertFalse(written.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", written)
        self.assertEqual(written.decode("utf-8"), text.replace("wheels = []", block))


class SourceAndUsageTest(unittest.TestCase):
    def test_lic01_failure_changes_nothing(self) -> None:
        """RF-001-25 / LIC-01: si ``tools/wheels.toml`` no cumple LIC-01 (numpy), la
        orden termina con 1, lo dice con la línea y no toca nada ni usa la red."""
        numpy = _make("numpy", "2.3.4", "dev")
        with _project([numpy, PYPROJ], store=[numpy, PYPROJ], extra=STALE) as root:
            before = _snapshot(root)
            result = _from_store(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertIn("[LIC-01]", result.text)
            self.assertIn("numpy", result.text)
            self.assertEqual(_snapshot(root), before)

    def test_missing_source_folder_exit_2(self) -> None:
        """RF-001-25: ``--desde`` (o ``GEOBLENDER_WHEELHOUSE``) a una carpeta que no
        existe es un error de uso: 2, sin tocar nada."""
        with _project([PYPROJ], extra=STALE) as root:
            before = _snapshot(root)
            missing = str(root / "no-existe")
            for result in (
                _run(root, "--desde", missing),
                _run(root, environ={ENV: missing}),
            ):
                self.assertEqual(result.code, 2, result.text)
                self.assertIn(missing, result.text)
            self.assertEqual(_snapshot(root), before)

    def test_usage(self) -> None:
        """RF-001-25: ``--ayuda`` muestra el uso; una opción desconocida o ``--desde`` sin
        valor dan 2 sin tocar nada; ``--desde=CARPETA`` también vale."""
        with _project([PYPROJ], store=[PYPROJ]) as root:
            before = _snapshot(root)
            result = _run(root, "--ayuda")
            self.assertEqual(result.code, 0)
            self.assertIn("--desde", result.out)
            for args in (("--otra",), ("--desde",), ("--desde", "")):
                with self.subTest(opciones=args):
                    result = _run(root, *args)
                    self.assertEqual(result.code, 2, result.text)
            self.assertEqual(_snapshot(root), before)
            result = _run(root, f"--desde={root / STORE}")
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual(_files(root / WHEELS_DIR), [PYPROJ.filename])

    def test_pypi_with_simulated_opener(self) -> None:
        """RF-001-25: sin carpeta, cada rueda se busca en el JSON de PyPI
        (``https://pypi.org/pypi/<nombre>/<versión>/json``, 60 s): el ``sha256`` que
        publica PyPI tiene que ser el fijado antes de descargar nada, y el fichero
        descargado se vuelve a comprobar. Con un PyPI simulado, sin red."""
        requested: list[tuple[str, float | None]] = []
        file_url = f"https://files.example/{PYPROJ.filename}"

        def opener(published: str, payload: bytes):
            def open_url(url: object, timeout: float | None = None) -> io.BytesIO:
                text = getattr(url, "full_url", url)
                requested.append((str(text), timeout))
                if text == "https://pypi.org/pypi/pyproj/3.8.0/json":
                    body = {
                        "urls": [
                            {
                                "filename": "pyproj-3.8.0.tar.gz",
                                "url": "https://files.example/pyproj-3.8.0.tar.gz",
                                "digests": {"sha256": "0" * 64},
                            },
                            {
                                "filename": PYPROJ.filename,
                                "url": file_url,
                                "digests": {"sha256": published},
                            },
                        ]
                    }
                    return io.BytesIO(json.dumps(body).encode("utf-8"))
                if text == file_url:
                    return io.BytesIO(payload)
                raise AssertionError(f"URL inesperada: {text}")

            return open_url

        with _project([PYPROJ]) as root:
            result = _run(root, opener=opener(PYPROJ.pinned, PYPROJ.data))
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual(_files(root / WHEELS_DIR), [PYPROJ.filename])
        self.assertEqual(
            requested,
            [
                ("https://pypi.org/pypi/pyproj/3.8.0/json", fetch_wheels.TIMEOUT_S),
                (file_url, fetch_wheels.TIMEOUT_S),
            ],
        )
        self.assertEqual(fetch_wheels.TIMEOUT_S, 60.0)

        requested.clear()
        with _project([PYPROJ], extra=STALE) as root:
            before = _snapshot(root)
            result = _run(root, opener=opener("f" * 64, PYPROJ.data))
            self.assertEqual(result.code, 1, result.text)
            self.assertIn("f" * 64, result.text)
            self.assertIn(PYPROJ.pinned, result.text)
            self.assertEqual(_snapshot(root), before)
        self.assertEqual([url for url, _ in requested], [requested[0][0]])

        with _project([PYPROJ], extra=STALE) as root:
            before = _snapshot(root)
            other = _wheel("pyproj", "3.8.0", salt="otra")
            result = _run(root, opener=opener(PYPROJ.pinned, other))
            self.assertEqual(result.code, 1, result.text)
            self.assertIn(_sha(other), result.text)
            self.assertEqual(_snapshot(root), before)

    def test_fetch_command(self) -> None:
        """RF-001-25: la orden que ``tools/check.py`` propone cuando faltan ruedas lleva
        ``--desde`` con el almacén si ``GEOBLENDER_WHEELHOUSE`` está definida."""
        python = Path(tempfile.gettempdir()) / "Blender" / "5.2" / "python" / "bin" / "python.exe"
        self.assertEqual(
            wheels.fetch_command(python, {}), f'& "{python}" tools/fetch_wheels.py'
        )
        store = str(Path(tempfile.gettempdir()) / "almacen de ruedas")
        self.assertEqual(
            wheels.fetch_command(python, {ENV: store}),
            f'& "{python}" tools/fetch_wheels.py --desde "{store}"',
        )
        self.assertEqual(wheels.ENV_WHEELHOUSE, ENV)


if __name__ == "__main__":
    unittest.main()
