# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia de un proyecto por pasos con huellas (spec 002, T19; RF-002-20, RNF-002-06; plan
002 §5.4, «Copia con huellas»).

La copia previa a una migración, la copia local y la publicación copian carpetas enteras:
por pasos (cada trozo de fichero es un paso de progreso, y cerrar el generador cancela),
con el sha256 de cada fichero calculado al leerlo, comprobando el espacio libre (con un
margen del 10 %) antes de copiar nada, reintentando los ficheros que retiene un
antivirus o el indexador, y comprobando al final que la copia tiene las mismas huellas
(se vuelve a leer). Se copia en una carpeta temporal junto al destino que se renombra al
final: cancelar o fallar a mitad no deja ninguna copia parcial.
"""

import hashlib
import os
import random
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import FakeClock, project_tmp
from tests.support.package import import_geoblender

copytree = import_geoblender("core.project.copytree")
model = import_geoblender("core.project.model")
errors = import_geoblender("core.errors")

CHUNK = 64 * 1024  # trozo pequeño para las pruebas (el real es de 8 MiB)
EXCLUDE = ("cache", ".lock")


def _bytes(seed: int, size: int) -> bytes:
    return random.Random(seed).randbytes(size)


def _make_tree(root: Path) -> None:
    """Un proyecto sintético: base, cabecera, ráster, carpetas vacías, instantánea, un
    fichero vacío, uno de exactamente un trozo, la caché y el cerrojo."""
    files: dict[str, bytes] = {
        "project.gpkg": _bytes(1, 5 * CHUNK + 123),
        "manifest.json": b'{"format": "geoblender-project"}\n',
        "rasters/gis_dtm_base.tif": _bytes(2, 3 * CHUNK + 7),
        "snapshots/V1.r1/manifest.json": b'{"schema": 1}\n',
        "snapshots/V1.r1/vector/gis_bnd_limite.parquet": _bytes(3, CHUNK // 2),
        "exports/vacio.txt": b"",
        "exports/un_trozo.bin": _bytes(4, CHUNK),
        "cache/jobs/j1/salida.npz": _bytes(5, 2 * CHUNK),
        ".lock": b'{"session_uid": "x"}' + b" " * 100 + b"\n",
    }
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for folder in ("meshes", "scenes"):
        (root / folder).mkdir()
    old = 1_700_000_000_000_000_000
    os.utime(root / "rasters" / "gis_dtm_base.tif", ns=(old, old))


def _snapshot(root: Path) -> dict[str, tuple[int, str, int] | str]:
    found: dict[str, tuple[int, str, int] | str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns)
    return found


def _flip_byte(path: Path, offset: int = 10) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


class Tree:
    def __init__(self, tmp: Path) -> None:
        self.source = tmp / "Cantera.gbproj"
        self.source.mkdir()
        _make_tree(self.source)
        self.parent = tmp / "destino"
        self.parent.mkdir()
        self.dest = self.parent / "Cantera.gbproj.respaldo-esquema-1"
        self.clock = FakeClock()

    def steps(self, **kwargs):
        kwargs.setdefault("exclude", EXCLUDE)
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("chunk_size", CHUNK)
        return copytree.copy_steps(self.source, self.dest, **kwargs)

    def leftovers(self) -> list[str]:
        return sorted(path.name for path in self.parent.iterdir())


def _run(steps) -> list:
    return list(steps)


class CopyTreeTest(unittest.TestCase):
    def test_copy_has_the_same_prints(self) -> None:
        """RF-002-20: la copia de un árbol sintético tiene los mismos ficheros, bytes y
        huellas (sha256) que el original, también las carpetas vacías y los ficheros
        vacíos o de un trozo exacto; sin ``cache/`` ni ``.lock`` si se excluyen; conserva
        las fechas de modificación y no cambia el original."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            before = _snapshot(tree.source)
            steps = _run(tree.steps())
            result = steps[-1].result
            self.assertIsInstance(result, copytree.CopyResult)
            self.assertEqual(result.dest, tree.dest)
            self.assertEqual(tree.leftovers(), [tree.dest.name])
            expected = {
                rel: value for rel, value in before.items()
                if rel.split("/")[0] not in EXCLUDE
            }
            copied = _snapshot(tree.dest)
            self.assertEqual(sorted(copied), sorted(expected))
            for rel, value in expected.items():
                if value == "carpeta":
                    self.assertEqual(copied[rel], "carpeta", rel)
                else:
                    self.assertEqual(copied[rel][:2], value[:2], rel)  # tamaño y sha256
                    self.assertEqual(copied[rel][2], value[2], rel)  # fecha de modificación
            source_prints = copytree.fingerprint(tree.source, exclude=EXCLUDE)
            self.assertEqual(result.prints, source_prints)
            self.assertEqual(copytree.fingerprint(tree.dest), source_prints)
            self.assertEqual(copytree.compare_prints(source_prints, result.prints), ())
            self.assertIn("meshes", result.prints.folders)
            self.assertIsNone(result.prints.file("cache/jobs/j1/salida.npz"))
            gpkg = result.prints.file("project.gpkg")
            self.assertEqual(
                gpkg.sha256, hashlib.sha256((tree.source / "project.gpkg").read_bytes()).hexdigest()
            )
            self.assertEqual(_snapshot(tree.source), before)

    def test_progress_in_chunks(self) -> None:
        """RNF-002-06: progreso por pasos (comprobar el espacio, copiar, comprobar la
        copia), en bytes hechos de un total, sin que un paso trate más de un trozo; el
        último lleva el resultado."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            prints = copytree.fingerprint(tree.source, exclude=EXCLUDE)
            total = prints.total_bytes
            steps = _run(tree.steps())
            phases = [step.phase for step in steps]
            self.assertEqual(phases[0], "espacio")
            self.assertEqual(
                [phase for index, phase in enumerate(phases) if phase not in phases[:index]],
                ["espacio", "copia", "comprobación"],
            )
            for phase in ("copia", "comprobación"):
                done = [step.done for step in steps if step.phase == phase]
                self.assertTrue(all(step.total == total for step in steps if step.phase == phase))
                self.assertEqual(done[-1], total, phase)
                increments = [b - a for a, b in zip([0, *done], done, strict=False)]
                self.assertTrue(all(0 <= item <= CHUNK for item in increments), phase)
                chunks = sum(-(-item.size // CHUNK) for item in prints.files)
                self.assertGreaterEqual(len(done), chunks, phase)
            self.assertTrue(all(step.result is None for step in steps[:-1]))
            self.assertTrue(all(step.message for step in steps))

    def test_large_files_are_synced_as_they_are_copied(self) -> None:
        """RNF-002-06: cada fichero se fuerza a disco (``fsync``) cada ``SYNC_BYTES``
        mientras se copia y al terminar, en orden: el ``fsync`` final de un fichero
        grande nunca tiene más de ``SYNC_BYTES`` pendientes, que con uno solo al final
        dejaba un paso de más de 1 s sin progreso (1 GiB en el PC de referencia, T36)."""
        synced: list[int] = []
        real_fsync = os.fsync

        def recording(fd: int) -> None:
            synced.append(os.fstat(fd).st_size)
            real_fsync(fd)

        with project_tmp() as tmp:
            tree = Tree(tmp)
            sizes = [size for _rel, size in copytree._listing(tree.source, EXCLUDE)[1]]
            every = 2 * CHUNK
            with (
                mock.patch.object(copytree, "SYNC_BYTES", every),
                mock.patch.object(copytree.os, "fsync", recording),
            ):
                _run(tree.steps())
        expected = [
            mark for size in sizes for mark in [*range(every, size + 1, every), size]
        ]
        self.assertEqual(synced, expected)
        self.assertGreater(len(synced), len(sizes))  # algún fichero se sincronizó a medias

    def test_altered_byte_in_the_copy_is_detected(self) -> None:
        """RF-002-20: si un byte de la copia no es el que se leyó del original (fallo de
        escritura), la comprobación final lo detecta: error con el fichero y sin copia
        parcial."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            steps = tree.steps()
            with self.assertRaises(errors.ProjectError) as caught:
                for step in steps:
                    if step.phase == "comprobación" and step.done == 0:
                        (temporary,) = [
                            path for path in tree.parent.iterdir()
                            if path.name.startswith(tree.dest.name + copytree.COPYING_MARK)
                        ]
                        _flip_byte(temporary / "rasters" / "gis_dtm_base.tif")
            self.assertEqual(caught.exception.code, "core.copy_mismatch")
            self.assertIn("rasters/gis_dtm_base.tif", str(caught.exception))
            self.assertEqual(tree.leftovers(), [])

    def test_altered_copy_detected_by_comparing_prints(self) -> None:
        """RF-002-20: un byte alterado, un fichero que falta o uno que sobra en el destino
        se detectan al comparar sus huellas con las de la copia."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            result = _run(tree.steps())[-1].result
            _flip_byte(tree.dest / "project.gpkg", 1000)
            (tree.dest / "exports" / "un_trozo.bin").unlink()
            (tree.dest / "scenes" / "principal.blend").write_bytes(b"x")
            found = copytree.compare_prints(result.prints, copytree.fingerprint(tree.dest))
            kinds = {item.path: item.kind for item in found}
            self.assertEqual(
                kinds,
                {
                    "project.gpkg": "changed",
                    "exports/un_trozo.bin": "missing",
                    "scenes/principal.blend": "extra",
                },
            )
            self.assertTrue(all(item.path in item.describe() for item in found))

    def test_refreshes_the_listing_after_renaming(self) -> None:
        """RF-002-20, RF-002-32 (docs/trampas.md §6): la copia, ya con su nombre definitivo,
        se vuelve a listar con ese nombre: en una carpeta de red (SMB) que se listó con el
        nombre anterior (la comprobación de la copia), Windows no deja sustituir después un
        fichero de dentro (``os.replace`` de la cabecera) hasta que se lista con el nuevo."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            seen: list[tuple[Path, bool]] = []
            real = copytree.refresh_listing

            def spy(folder: Path) -> None:
                seen.append((Path(folder), Path(folder).is_dir()))
                real(folder)

            with mock.patch.object(copytree, "refresh_listing", spy):
                _run(tree.steps())
            self.assertEqual(seen, [(tree.dest, True)])
            copytree.refresh_listing(tmp / "no-existe")  # no falla: es una ayuda

    def test_tree_digest_and_json(self) -> None:
        """RF-002-31, RF-002-32 (T31): una sola huella de la carpeta, la de partida de una
        copia local, es la misma para las mismas huellas y cambia si cambia un byte, sobra
        un fichero o una carpeta; las huellas van y vuelven por JSON."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            prints = copytree.fingerprint(tree.source)
            digest = copytree.tree_digest(prints)
            self.assertEqual(copytree.tree_digest(copytree.fingerprint(tree.source)), digest)
            self.assertEqual(len(digest), 64)
            self.assertEqual(copytree.TreePrints.from_dict(prints.to_dict()), prints)
            for bad in (None, [], {"folders": [], "files": [["a", "1", "b"]]}, {"files": []}):
                self.assertIsNone(copytree.TreePrints.from_dict(bad))
            _flip_byte(tree.source / "project.gpkg", 1000)
            flipped = copytree.tree_digest(copytree.fingerprint(tree.source))
            (tree.source / "exports" / "nuevo.txt").write_bytes(b"")
            extra_file = copytree.tree_digest(copytree.fingerprint(tree.source))
            (tree.source / "exports" / "vacia").mkdir()
            extra_folder = copytree.tree_digest(copytree.fingerprint(tree.source))
            self.assertEqual(len({digest, flipped, extra_file, extra_folder}), 4)

    def test_cancel_midway_leaves_no_partial_copy(self) -> None:
        """RNF-002-06: cerrar el generador a mitad de la copia o de la comprobación
        cancela sin dejar copia parcial ni carpeta temporal, y el original no cambia."""
        for phase, after in (("copia", 3), ("comprobación", 2)):
            with self.subTest(phase=phase), project_tmp() as tmp:
                tree = Tree(tmp)
                before = _snapshot(tree.source)
                steps = tree.steps()
                seen = 0
                for step in steps:
                    if step.phase == phase:
                        seen += 1
                        if seen == after:
                            break
                self.assertTrue(any(tree.parent.iterdir()))  # la temporal existe aún
                steps.close()
                self.assertEqual(tree.leftovers(), [])
                self.assertEqual(_snapshot(tree.source), before)

    def test_no_space_fails_before_copying(self) -> None:
        """RNF-002-06: sin espacio libre para la copia más un 10 % de margen, error con
        lo necesario y lo disponible antes de copiar nada (ni carpeta temporal); con el
        espacio justo, se copia."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            total = copytree.fingerprint(tree.source, exclude=EXCLUDE).total_bytes
            needed = total + -(-total // 10)

            def usage(free: int):
                return lambda path: mock.Mock(total=10 * needed, used=0, free=free)

            steps = tree.steps(disk_usage=usage(needed - 1))
            with self.assertRaises(errors.ProjectError) as caught:
                for _step in steps:
                    self.assertEqual(tree.leftovers(), [])
            self.assertEqual(caught.exception.code, "core.copy_no_space")
            self.assertIn("10 %", str(caught.exception))
            self.assertEqual(tree.leftovers(), [])
            result = _run(tree.steps(disk_usage=usage(needed)))[-1].result
            self.assertEqual(result.dest, tree.dest)

    def test_retries_a_file_held_by_another_program(self) -> None:
        """RNF-002-06: un fichero que retiene otro programa (antivirus, indexador) se
        reintenta 3 veces cada 0,5 s; si sigue retenido, error con el fichero y sin
        copia parcial."""
        real_open = copytree._open_source

        def held(times: int):
            state = {"left": times}

            def opener(path: Path):
                if Path(path).name == "project.gpkg" and state["left"] > 0:
                    state["left"] -= 1
                    raise PermissionError(13, "El proceso no tiene acceso al archivo", str(path))
                return real_open(path)

            return opener

        with project_tmp() as tmp:
            tree = Tree(tmp)
            start = tree.clock.monotonic()
            with mock.patch.object(copytree, "_open_source", held(copytree.RETRIES)):
                result = _run(tree.steps())[-1].result
            self.assertAlmostEqual(tree.clock.monotonic() - start, copytree.RETRIES * 0.5)
            self.assertEqual(
                result.prints.file("project.gpkg").sha256,
                hashlib.sha256((tree.source / "project.gpkg").read_bytes()).hexdigest(),
            )
        with project_tmp() as tmp:
            tree = Tree(tmp)
            with mock.patch.object(copytree, "_open_source", held(copytree.RETRIES + 1)):
                with self.assertRaises(errors.ProjectError) as caught:
                    _run(tree.steps())
            self.assertEqual(caught.exception.code, "core.copy_failed")
            self.assertIn("project.gpkg", str(caught.exception))
            self.assertEqual(tree.leftovers(), [])

    def test_refuses_existing_destination_and_missing_folders(self) -> None:
        """RNF-002-06: un destino que ya existe, un original que no existe o una carpeta
        de destino que no existe se rechazan sin tocar nada."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            tree.dest.mkdir()
            (tree.dest / "otro.txt").write_bytes(b"de otro")
            with self.assertRaises(errors.ProjectError) as caught:
                _run(tree.steps())
            self.assertEqual(caught.exception.code, "core.copy_dest_exists")
            self.assertEqual((tree.dest / "otro.txt").read_bytes(), b"de otro")
            self.assertEqual(tree.leftovers(), [tree.dest.name])
            with self.assertRaises(errors.ProjectError) as caught:
                _run(copytree.copy_steps(tmp / "No.gbproj", tree.parent / "copia"))
            self.assertEqual(caught.exception.code, "core.copy_source_missing")
            with self.assertRaises(errors.ProjectError) as caught:
                _run(copytree.copy_steps(tree.source, tmp / "no_existe" / "copia"))
            self.assertEqual(caught.exception.code, "core.copy_parent_missing")
            self.assertFalse((tmp / "no_existe").exists())

    def test_refuses_links(self) -> None:
        """RNF-002-06: un proyecto no tiene enlaces: una unión de carpetas dentro del
        original se rechaza antes de copiar nada (no se sigue ni se copia vacía)."""
        try:
            import _winapi
        except ImportError:
            _winapi = None
        if _winapi is None or not hasattr(_winapi, "CreateJunction"):
            self.skipTest("[ENTORNO] uniones de carpetas de Windows no disponibles")
        with project_tmp() as tmp:
            tree = Tree(tmp)
            outside = tmp / "fuera"
            outside.mkdir()
            (outside / "dato.bin").write_bytes(b"fuera del proyecto")
            _winapi.CreateJunction(str(outside), str(tree.source / "meshes" / "enlace"))
            with self.assertRaises(errors.ProjectError) as caught:
                _run(tree.steps())
            self.assertEqual(caught.exception.code, "core.copy_link")
            self.assertIn("meshes/enlace", str(caught.exception))
            self.assertEqual(tree.leftovers(), [])
            os.rmdir(tree.source / "meshes" / "enlace")

    def test_copy_tree_runs_every_step(self) -> None:
        """RF-002-20: ``copy_tree`` hace la copia completa de una vez (el mismo recorrido
        sin pausas) y devuelve el mismo resultado."""
        with project_tmp() as tmp:
            tree = Tree(tmp)
            result = copytree.copy_tree(
                tree.source, tree.dest, exclude=EXCLUDE, clock=tree.clock, chunk_size=CHUNK
            )
            self.assertEqual(result.prints, copytree.fingerprint(tree.source, exclude=EXCLUDE))
            self.assertIsInstance(result, copytree.CopyResult)
            steps = list(copytree.fingerprint_steps(tree.dest, chunk_size=CHUNK))
            self.assertEqual(steps[-1].result, result.prints)
            self.assertIsInstance(steps[0], model.Progress)


if __name__ == "__main__":
    unittest.main()
