# SPDX-License-Identifier: GPL-3.0-or-later
"""El almacén de ruedas del motor de cálculo, ``tools/fetch_runtime_wheels.py`` (spec 004,
T30; RF-004-24; plan 004 §5.1; D-4).

- Llena el almacén (``--wheelhouse``, o ``GEOBLENDER_WHEELHOUSE``) con las ruedas del lock
  descargándolas de sus URL con ``jobs.runtime.fetch_wheel``, el código del producto, que
  comprueba la huella mientras lee: solo deja una rueda si es la del lock.
- Una rueda que ya está con su huella no se vuelve a descargar; una que está con otra huella
  no se toca y la orden termina con 1, y una descarga con otra huella no deja nada.
- Sin almacén, o con uno que no existe, termina con 2 sin hacer nada.

Ruedas sintéticas; la «PyPI» son URL ``file://``: ninguna prueba usa la red.
"""

import contextlib
import io
import json
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from tests.support import jobs_fixtures as _support
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import fetch_runtime_wheels  # noqa: E402

LOCK_HEADER = (
    'schema = "geoblender.runtime_lock/1"\npython = "3.13"\nplatform = "win_amd64"\n'
)


def _write_lock(path: Path, wheels: Sequence, sha_of: Callable[[object], str]) -> Path:
    """Un lock en TOML con ``wheels``: sus URL, las ``file://`` de las ruedas; sus huellas,
    ``sha_of(rueda)``."""
    tables = []
    for wheel in wheels:
        tables.append(
            "\n[[package]]\n"
            f"name = {json.dumps(wheel.name)}\n"
            f"version = {json.dumps(wheel.version)}\n"
            f"filename = {json.dumps(wheel.filename)}\n"
            f"url = {json.dumps(wheel.path.as_uri())}\n"
            f'sha256 = "{sha_of(wheel)}"\n'
            f"size = {wheel.size}\n"
            "installed_size = 1000000\n"
            'license = "MIT"\n'
            "bundled_licenses = []\n"
            'required_by = ["004"]\n'
        )
    path.write_text(LOCK_HEADER + "".join(tables), encoding="utf-8", newline="\n")
    return path


def _run(argv: Sequence[str], lock: Path, environ: Mapping[str, str] | None = None
         ) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = fetch_runtime_wheels.main(list(argv), root=ROOT, lock_path=lock,
                                         environ={} if environ is None else environ)
    return code, out.getvalue()


def _altered(sha256: str) -> str:
    return ("1" if sha256[0] == "0" else "0") + sha256[1:]


class FetchRuntimeWheelsTest(unittest.TestCase):
    """RF-004-24: el almacén de ruedas del motor de cálculo."""

    def setUp(self) -> None:
        tmp = _support.jobs_tmp()
        self.tmp = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)
        source = self.tmp / "pypi"
        self.wheels = [_support.make_wheel(source),
                       _support.make_wheel(source, name="gbtestdos", version="2.0.0")]
        self.lock = _write_lock(self.tmp / "lock.toml", self.wheels, lambda w: w.sha256)
        self.store = self.tmp / "almacen"
        self.store.mkdir()

    def test_fills_the_wheelhouse_checking_hashes(self) -> None:
        """RF-004-24: el almacén queda con las ruedas del lock y sus huellas (descargadas
        con ``runtime.fetch_wheel``); otra vez, con el almacén de
        ``GEOBLENDER_WHEELHOUSE``, no se descarga nada."""
        store, wheels = self.store, self.wheels
        code, out = _run(["--wheelhouse", str(store)], self.lock)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in store.iterdir()),
                         sorted(w.filename for w in wheels))
        for wheel in wheels:
            self.assertEqual(_support.sha256_file(store / wheel.filename), wheel.sha256)

        before = {p.name: p.stat().st_mtime_ns for p in store.iterdir()}
        code, out = _run([], self.lock, {"GEOBLENDER_WHEELHOUSE": str(store)})
        self.assertEqual(code, 0, out)
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in store.iterdir()}, before)
        self.assertIn("ya está", out)

    def test_wrong_wheels_are_not_kept(self) -> None:
        """RF-004-24: una rueda del almacén con otra huella no se toca (código 1, con su
        nombre), una descarga con otra huella que la del lock no deja nada (código 1) y,
        sin almacén, con uno que no existe o con una opción que no existe, código 2."""
        tampered = self.store / self.wheels[0].filename
        tampered.write_bytes(b"no es la rueda del lock")
        code, out = _run(["--wheelhouse", str(self.store)], self.lock)
        self.assertEqual(code, 1, out)
        self.assertIn(self.wheels[0].filename, out)
        self.assertEqual(tampered.read_bytes(), b"no es la rueda del lock")

        other = self.tmp / "otro"
        other.mkdir()
        bad = _write_lock(self.tmp / "lock_mal.toml", self.wheels[:1],
                          lambda w: _altered(w.sha256))
        code, out = _run(["--wheelhouse", str(other)], bad)
        self.assertEqual(code, 1, out)
        self.assertEqual(list(other.iterdir()), [])

        for argv in ([], ["--wheelhouse", str(self.tmp / "no_existe")], ["--otra"]):
            with self.subTest(opciones=argv):
                code, out = _run(argv, self.lock)
                self.assertEqual(code, 2, out)


if __name__ == "__main__":
    unittest.main()
