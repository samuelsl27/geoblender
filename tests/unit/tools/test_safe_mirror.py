# SPDX-License-Identifier: GPL-3.0-or-later
"""El espejo seguro del NAS, ``gbtools.safe_mirror`` (spec 007, HU-007-7; plan 007 §5.2 y
§5.4.6 a §5.4.8).

Todas las pruebas trabajan en carpetas temporales locales: la carpeta del proyecto, el
destino y el perfil local (que hace de ``LOCALAPPDATA``, con los estados y las fotos).
Ninguna lee el perfil real del puesto ni toca el NAS.
"""

import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from tests.support import mirror
from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import layout, safe_mirror  # noqa: E402

SHA = "a" * 64


@contextmanager
def places() -> Iterator[tuple[Path, Path, dict[str, str]]]:
    """Un destino y un perfil local temporales: ``(destino, perfil, entorno)``."""
    with tempfile.TemporaryDirectory(prefix="geoblender-espejo-") as tmp:
        base = Path(tmp).resolve()
        dest, profile = base / "destino", base / "perfil"
        dest.mkdir()
        profile.mkdir()
        yield dest, profile, {"LOCALAPPDATA": str(profile)}


class StateTest(unittest.TestCase):
    """RF-007-30, RF-007-31: dónde está el estado de cada destino y cuál es la base de la
    comparación (el estado, o la foto en el primer espejo)."""

    def test_state_dir(self) -> None:
        """RF-007-30: el estado vive en ``%LOCALAPPDATA%\\Geoblender\\espejo`` (fuera de
        los repositorios y del destino); sin ``LOCALAPPDATA``, un error claro."""
        with places() as (_dest, profile, environ):
            self.assertEqual(
                safe_mirror.state_dir(environ), profile.joinpath(*layout.MIRROR_STATE_PARTS)
            )
        with self.assertRaises(safe_mirror.MirrorError) as ctx:
            safe_mirror.state_dir({})
        self.assertIn("LOCALAPPDATA", str(ctx.exception))

    def test_state_per_destination(self) -> None:
        """RF-007-30: un estado por destino, en un fichero cuyo nombre sale de su ruta
        real; cada destino lee el suyo."""
        with places() as (dest, profile, environ):
            other = dest.parent / "otro"
            other.mkdir()
            files = {"a.txt": {"size": 1, "mtime_ns": 5, "sha256": SHA}}
            mirror.write_state(profile, dest, files=files, folders=["docs"])
            mirror.write_state(profile, other, files={}, folders=[])
            first = safe_mirror.state_file(dest, environ)
            self.assertNotEqual(first, safe_mirror.state_file(other, environ))
            self.assertRegex(first.name, r"^estado-[0-9a-f]{16}\.json$")
            base = safe_mirror.load_base(dest, environ)
            assert base is not None
            self.assertFalse(base.photo)
            self.assertEqual(base.files, {"a.txt": safe_mirror.FileState(1, 5, SHA)})
            self.assertEqual(base.folders, {"docs"})
            base_other = safe_mirror.load_base(other, environ)
            assert base_other is not None
            self.assertEqual(base_other.files, {})
            same = safe_mirror.state_file(Path(str(dest).upper() + "\\"), environ)
            self.assertEqual(same, first)

    def test_state_same_for_unc_and_drive(self) -> None:
        """RF-007-30: una unidad de red y su ruta UNC son el mismo destino: la clave sale
        de la ruta real (``os.path.realpath``, que da la UNC de una unidad de red)."""
        drive = "Y" + ":\\espejo\\proyecto"
        unc = "\\\\servidor.invalid\\recurso\\espejo\\proyecto"

        def realpath(path: object, *_args: object, **_kwargs: object) -> str:
            text = os.fspath(path)
            return unc + text[len(drive):] if text.upper().startswith(drive.upper()) else text

        with mock.patch("os.path.realpath", side_effect=realpath):
            environ = {"LOCALAPPDATA": "C:\\perfil-de-prueba"}
            self.assertEqual(
                safe_mirror.state_file(Path(drive), environ),
                safe_mirror.state_file(Path(unc), environ),
            )
            self.assertEqual(safe_mirror.destination_key(drive), safe_mirror.destination_key(unc))

    def test_first_mirror_uses_photo(self) -> None:
        """RF-007-31: sin estado, la foto cuyo ``destino`` tiene la misma ruta real
        (escrita de otra forma) es la base: sus ficheros y, como carpetas, las madres de
        sus ficheros."""
        with places() as (dest, profile, environ):
            files = {
                "docs/adr/0001.md": {"size": 3, "mtime_ns": 7, "sha256": SHA},
                "README.md": {"size": 2, "mtime_ns": 8, "sha256": SHA},
            }
            written = str(dest).upper() + "\\"
            mirror.write_photo(profile, written, files=files)
            base = safe_mirror.load_base(dest, environ)
        assert base is not None
        self.assertTrue(base.photo)
        self.assertEqual(base.taken, mirror.TAKEN)
        self.assertEqual(base.files["README.md"], safe_mirror.FileState(2, 8, SHA))
        self.assertEqual(base.folders, {"docs", "docs/adr"})

    def test_photo_of_other_destination_ignored(self) -> None:
        """RF-007-31: la foto de otro destino no vale, y sin estado ni foto no hay base;
        una foto ilegible se salta."""
        with places() as (dest, profile, environ):
            mirror.write_photo(profile, dest.parent / "otro", files={})
            folder = mirror.state_folder(profile)
            (folder / "foto-rota.json").write_bytes(b"{no es json")
            self.assertIsNone(safe_mirror.load_base(dest, environ))
        with places() as (dest, _profile, environ):
            self.assertIsNone(safe_mirror.load_base(dest, environ))

    def test_unreadable_state_not_replaced_by_photo(self) -> None:
        """RF-007-31: un estado que existe y no se puede leer es ``StateUnreadable``,
        aunque haya foto: nunca se vuelve a la foto."""
        with places() as (dest, profile, environ):
            mirror.write_photo(profile, dest, files={})
            state = safe_mirror.state_file(dest, environ)
            for content in (b"{no es json", b"[]", json.dumps({"formato": 2}).encode()):
                with self.subTest(contenido=content):
                    state.write_bytes(content)
                    with self.assertRaises(safe_mirror.StateUnreadable) as ctx:
                        safe_mirror.load_base(dest, environ)
                    self.assertIn(state.name, str(ctx.exception))

    def test_state_paths_validated(self) -> None:
        """RF-007-30: un estado con una ruta que sale del destino («..», absoluta o con
        «\\»), un sha256 o un tamaño que no lo son, no se lee (``StateUnreadable``): el
        espejo nunca usa una ruta del estado fuera del destino."""
        bad_files = (
            {"../fuera.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"C:/x.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"docs\\x.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"x.txt": {"size": 1, "mtime_ns": 1, "sha256": "corto"}},
            {"x.txt": {"size": True, "mtime_ns": 1, "sha256": SHA}},
        )
        with places() as (dest, profile, environ):
            for files in bad_files:
                with self.subTest(ficheros=files):
                    mirror.write_state(profile, dest, files=files, folders=[])
                    with self.assertRaises(safe_mirror.StateUnreadable):
                        safe_mirror.load_base(dest, environ)
            mirror.write_state(profile, dest, files={}, folders=["../fuera"])
            with self.assertRaises(safe_mirror.StateUnreadable):
                safe_mirror.load_base(dest, environ)


if __name__ == "__main__":
    unittest.main()
