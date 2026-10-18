# SPDX-License-Identifier: GPL-3.0-or-later
"""Mallas ``npz`` por trozos (spec 009, T11; RF-009-07, RNF-009-05; plan 009 §2.2 y D-30).

Al congelar una revisión, la copia de cada malla se comprueba con su lector y su normalizador
(``core.npz_mesh@1``, ``gbch/1``) por pasos en el hilo de Blender, y lo propio de cada llamada
no pasa de 0,2 s (RNF-009-05). Antes, ``np.load`` de un array entero y el hash de toda la
malla eran una llamada cada uno: 0,6 s con la malla de §2.2 del plan (1,5 M de vértices y 3 M
de caras). Ahora el lector lee cada miembro del zip una sola vez, en trozos de
``chunk_bytes`` (como mucho ``NPZ_CHUNK_BYTES``, 8 MiB), y hashea la malla por pasos
(``ContentHasher.begin_mesh`` y ``MeshEncoder.finish_steps``, trozos de 8 MiB de celdas), con
la misma salida: el mismo hash que de una vez (los vectores de referencia de ``gbch/1`` y la
malla grande, con el hash que da el código de partida), el mismo avance en una malla pequeña
y el mismo error con una malla dañada; el lector sigue siendo ``core.npz_mesh@1`` (ADR-0024
§6).

``_at_once`` es la lectura de antes (la 008): la referencia de «el mismo hash» y de «el mismo
error que antes».
"""

from __future__ import annotations

import json
import struct
import tempfile
import time
import unittest
import warnings
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import content_golden, timing
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.trees import age_folders

content = import_geoblender("core.content")
encoder = import_geoblender("core.content.encoder")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")

NPZ_MESH = builtin.NPZ_MESH
DECLARATIONS = {"conventions": {}, "crs_h": {"epsg": 25830}, "crs_v": {"epsg": 5782}}
META = {"schema": 1, "kind": "surface", "crs_epsg": 25830, "closed": False}
MIB = 1 << 20
STEP_BUDGET_S = 0.2  # RNF-009-05: lo propio de cada llamada en el hilo de Blender
WRITERS = ("savez", "compressed", "level1")
"""Cómo se escribe un npz en las pruebas: ``np.savez`` (sin comprimir, como los de la
demostración y los sondeos), ``np.savez_compressed`` y *deflate* de nivel 1 con Zip64 (como
``gis.tin``)."""

LARGE_SIDE = 1225
"""Vértices por lado de la malla grande: 1 500 625 vértices y 2 996 352 caras (plan 009 §2.2:
1,5 M y 3 M)."""
LARGE_DATA_SHA256 = "6728612bb874978ea2ea77c8ead546a9be865d40eb699169f04776581e31f398"
LARGE_CONTENT_SHA256 = "6aa722de02d1b85f28bcf8f50650a345f898de26d7133bdea7caaa5050b5729a"
"""Los hashes de la malla grande con ``DECLARATIONS`` y ``META``, calculados con el código de
partida de la T11 (commit ``c8c9641``: ``np.load`` y ``ContentHasher.mesh`` de una vez)."""


# --- Escribir y leer mallas -----------------------------------------------------------------


def write_npz(
    path: Path,
    arrays: dict[str, np.ndarray],
    meta: object = META,
    *,
    writer: str = "level1",
    version: tuple[int, int] | None = None,
) -> Path:
    """``arrays`` y ``meta`` (un diccionario, que va en JSON como texto 0-d; un array, tal
    cual; ``None``, sin ``meta``) en un npz escrito con ``writer`` (:data:`WRITERS`).
    ``version``: la del formato ``.npy`` de los miembros (solo con ``level1``)."""
    members = dict(arrays)
    if meta is not None:
        members["meta"] = meta if isinstance(meta, np.ndarray) else np.array(json.dumps(meta))
    if writer == "savez":
        np.savez(path, **members)
    elif writer == "compressed":
        np.savez_compressed(path, **members)
    else:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1,
                             allowZip64=True) as archive:
            for name, array in members.items():
                with archive.open(f"{name}.npy", "w", force_zip64=True) as member:
                    np.lib.format.write_array(member, array, version=version,
                                              allow_pickle=False)
    return path


def _at_once(path: Path, declarations: dict = DECLARATIONS) -> object:
    """Lo que daba ``core.npz_mesh@1`` antes de la T11 (spec 008, T12): ``np.load``, cada
    array de una vez (con ``_array`` y ``_meta`` del lector, que no cambian) y la malla
    hasheada de una vez. El mismo ``ContentDigest`` o el mismo error."""
    request = NPZ_MESH.request("mesh", declarations, {"main": path})
    arrays: dict[str, object] = {}
    meta: dict[str, object] = {}
    with open(path, "rb") as stream:
        if stream.read(2) != b"PK":
            raise ValueError(f"«{path.name}» no es una malla npz (un zip de numpy)")
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as archive:
            for name in list(archive.files):
                value = builtin._array(archive, name, path)
                if name == builtin.META_ARRAY:
                    meta = builtin._meta(value, path)
                else:
                    arrays[name] = value
    return request.hasher.mesh(arrays, meta).digest()


def read(
    path: Path,
    *,
    chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES,
    declarations: dict = DECLARATIONS,
    progress: Callable[[float], object] | None = None,
) -> object:
    """El ``ContentDigest`` de ``core.npz_mesh@1`` leyendo en trozos de ``chunk_bytes``."""
    request = NPZ_MESH.request("mesh", declarations, {"main": path}, chunk_bytes=chunk_bytes)
    return readers.read_content(NPZ_MESH, request, progress=progress)


def outcome(action: Callable[[], object]) -> tuple[str, str, str]:
    """``("ok", hashes, "")`` o ``(clase del error, su texto, clase del error que lo causó o
    durante el que se lanzó)``: lo que se compara con antes."""
    try:
        digest = action()
    except Exception as error:  # noqa: BLE001 - se compara el error que sea
        context = error.__context__
        return (type(error).__qualname__, str(error),
                "" if context is None else type(context).__qualname__)
    return "ok", f"{digest.data_sha256} {digest.content_sha256}", ""


def large_mesh(side: int = LARGE_SIDE) -> dict[str, np.ndarray]:
    """La malla de §2.2 del plan 009: un terreno de ``side`` × ``side`` vértices cada 2 m con
    ruido en las tres coordenadas, y dos triángulos por cuadro. Sus valores salen de
    operaciones exactas sobre un hash entero de cada índice, no de un generador aleatorio: los
    mismos con cualquier numpy."""
    index = np.arange(side * side, dtype=np.uint64)
    mixed = index * np.uint64(0x9E3779B97F4A7C15)
    mixed ^= mixed >> np.uint64(29)
    mixed *= np.uint64(0xBF58476D1CE4E5B9)
    mixed ^= mixed >> np.uint64(32)
    noise = (mixed >> np.uint64(11)).astype(np.float64) * 2.0**-53
    jitter_x = ((mixed >> np.uint64(3)) & np.uint64(0xFFFFF)).astype(np.float64) * 2.0**-20
    jitter_y = ((mixed >> np.uint64(23)) & np.uint64(0xFFFFF)).astype(np.float64) * 2.0**-20
    row, column = np.divmod(np.arange(side * side, dtype=np.int64), side)
    vertices = np.empty((side * side, 3), dtype=np.float64)
    vertices[:, 0] = 700_000.0 + column * 2.0 + jitter_x * 0.5
    vertices[:, 1] = 4_400_000.0 - row * 2.0 + jitter_y * 0.5
    vertices[:, 2] = 500.0 + row * 0.03125 - column * 0.015625 + noise * 0.25
    corner = (
        np.arange(side - 1)[:, None] * side + np.arange(side - 1)[None, :]
    ).reshape(-1).astype(np.int32)
    faces = np.empty((corner.size * 2, 3), dtype=np.int32)
    faces[0::2, 0], faces[0::2, 1], faces[0::2, 2] = corner, corner + 1, corner + side
    faces[1::2, 0], faces[1::2, 1], faces[1::2, 2] = corner + 1, corner + side + 1, corner + side
    return {"vertices": vertices, "faces": faces}


def medium_mesh(vertices: int = 400_000, faces: int = 100_000) -> dict[str, np.ndarray]:
    """Una malla de ``vertices`` × 3 float64 (con los de siempre, un miembro de más de 8 MiB)
    y ``faces`` × 3 int32."""
    values = np.arange(vertices * 3, dtype=np.float64).reshape(vertices, 3)
    values *= 0.125
    values[:, 0] += 700_000.0
    corners = (np.arange(faces * 3, dtype=np.int64) % vertices).astype(np.int32)
    return {"vertices": values, "faces": corners.reshape(faces, 3)}


def odd_arrays() -> dict[str, np.ndarray]:
    """Arrays de todas las clases, órdenes de bytes y formas que admite una malla."""
    vertices = np.arange(3000, dtype=np.float64).reshape(1000, 3) * 0.25 + 4_400_000.0
    normals = np.linspace(-1.0, 1.0, 3000, dtype=np.float32).reshape(1000, 3)
    normals[7, 1] = np.float32("nan")
    normals.view("<u4")[9, 2] = 0x7FC00001  # NaN con carga
    normals[11, 0] = np.float32(-0.0)
    return {
        "vertices": vertices.astype(">f8"),
        "vertices_fortran": np.asfortranarray(vertices),
        "normals": normals,
        "faces": (np.arange(6000, dtype=np.int64) % 1000).astype("<i4").reshape(2000, 3),
        "face_ids": np.arange(2000, dtype=">i8"),
        "edge_ids": np.arange(500, dtype="<u8") * np.uint64(1 << 40),
        "vertex_source": (np.arange(1000) % 5).astype("|u1"),
        "small": np.arange(1000, dtype="<i2") - 500,
        "face_mask": (np.arange(2000) % 3 == 0),
        "blocks": np.arange(4000, dtype="<i8").reshape(1000, 2, 2),
        "blocks_fortran": np.asfortranarray(np.arange(24, dtype="<f8").reshape(2, 3, 4)),
        "scalar": np.array(2.5),
        "empty": np.empty((0, 3), dtype="<f8"),
    }


class _TempCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-npz-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    @contextmanager
    def closes_its_files(self) -> Iterator[None]:
        """Falla si el bloque deja un fichero sin cerrar (``ResourceWarning``)."""
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always", ResourceWarning)
            yield
        leaked = [str(item.message) for item in seen if item.category is ResourceWarning]
        self.assertEqual(leaked, [])


class _ReadSpy:
    """Mientras está activo, anota cada ``ZipFile.open`` (el miembro) y cada
    ``ZipExtFile.read`` (miembro, bytes pedidos y bytes devueltos) de cualquier zip."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.reads: list[tuple[str, int, int]] = []
        self._patches: list[object] = []

    def __enter__(self) -> _ReadSpy:
        spy = self
        original_open = zipfile.ZipFile.open
        original_read = zipfile.ZipExtFile.read

        def open_member(archive: zipfile.ZipFile, name: object, *args: object, **kw: object):
            member = original_open(archive, name, *args, **kw)
            spy.opened.append(member.name)
            return member

        def read_member(member: zipfile.ZipExtFile, size: int = -1) -> bytes:
            data = original_read(member, size)
            spy.reads.append((member.name, size, len(data)))
            return data

        self._patches = [
            mock.patch.object(zipfile.ZipFile, "open", open_member),
            mock.patch.object(zipfile.ZipExtFile, "read", read_member),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for patch in reversed(self._patches):
            patch.stop()

    def read_bytes(self, member: str) -> int:
        return sum(got for name, _size, got in self.reads if name == member)


class GoldenVectorsTest(_TempCase):
    """RF-009-07 (D-30; ADR-0024 §6): las mallas de los vectores de referencia de ``gbch/1``
    leídas por trozos dan sus hashes guardados."""

    def test_golden_meshes_by_chunks(self) -> None:
        """RF-009-07: cada malla de ``golden_gbch1.json``, escrita con o sin compresión y leída
        en trozos de 1, 5, 64 bytes y 1 MiB (el de siempre), da sus dos hashes guardados, los
        de leerla de una vez."""
        document = content_golden.load()
        cases = [case for case in document["cases"] if "mesh" in case]
        self.assertEqual(len(cases), 3)
        for case in cases:
            spec = case["mesh"]
            arrays = {
                name: content_golden.decode_array(array["values"], array["dtype"],
                                                  array["shape"])
                for name, array in spec["arrays"].items()
            }
            expected = (case["data_sha256"], case["content_sha256"])
            for writer in WRITERS:
                path = write_npz(self.tmp / f"{case['id']}-{writer}.npz", arrays, spec["meta"],
                                 writer=writer)
                at_once = _at_once(path, case["declarations"])
                self.assertEqual((at_once.data_sha256, at_once.content_sha256), expected)
                for chunk in (1, 5, 64, readers.DEFAULT_CHUNK_BYTES):
                    with self.subTest(case=case["id"], writer=writer, chunk=chunk):
                        digest = read(path, chunk_bytes=chunk,
                                      declarations=case["declarations"])
                        self.assertEqual((digest.data_sha256, digest.content_sha256), expected)
                        self.assertEqual(digest.reader, "core.npz_mesh@1")


class SameAsAtOnceTest(_TempCase):
    """RF-009-07 (D-30): por trozos, el mismo hash que de una vez con cualquier array."""

    def test_classes_byte_orders_and_layouts(self) -> None:
        """RF-009-07: flotantes de 4 y 8 bytes (*big endian*, NaN con carga y −0,0), enteros de
        1 a 8 bytes con y sin signo, booleanos, arrays 0-d, vacíos, de 3 dimensiones y en orden
        de Fortran, escritos de las tres formas (y uno con miembros ``.npy`` 3.0, que se leen de
        una vez), en trozos de 7 bytes, 4 KiB, 1 MiB y 64 MiB, dan el hash de leerlos de una
        vez; el avance llega a 1 sin retroceder."""
        arrays = odd_arrays()
        files = [write_npz(self.tmp / f"{writer}.npz", arrays, writer=writer)
                 for writer in WRITERS]
        files.append(write_npz(self.tmp / "v3.npz", arrays, version=(3, 0)))
        for path in files:
            expected = outcome(lambda path=path: _at_once(path))
            self.assertEqual(expected[0], "ok")
            for chunk in (7, 4096, MIB, 64 * MIB):
                with self.subTest(file=path.name, chunk=chunk):
                    seen: list[float] = []
                    self.assertEqual(
                        outcome(lambda path=path, chunk=chunk: read(
                            path, chunk_bytes=chunk, progress=seen.append)),
                        expected,
                    )
                    self.assertEqual(seen[-1], 1.0)
                    self.assertEqual(seen, sorted(seen))

    def test_small_mesh_progress_by_members(self) -> None:
        """RF-009-07: una malla cuyos miembros caben en un trozo avanza como antes, por
        miembros (0,25, 0,5 y 0,75 con dos arrays y su ``meta``) y 1 con el hash hecho."""
        arrays = {"vertices": np.arange(12, dtype=np.float64).reshape(4, 3),
                  "faces": np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)}
        path = write_npz(self.tmp / "a.npz", arrays)
        seen: list[float] = []
        read(path, progress=seen.append)
        self.assertEqual(seen, [0.25, 0.5, 0.75, 1.0])


class ChunksTest(_TempCase):
    """RF-009-07 y RNF-009-05 (D-30): cada miembro del zip, una sola vez y en trozos de
    ``chunk_bytes`` (8 MiB como mucho), y la malla hasheada en trozos de 8 MiB de celdas."""

    def test_each_member_read_once_in_chunks(self) -> None:
        """RF-009-07 y RNF-009-05: con un miembro de 9,6 MB, cada miembro se abre una vez y
        cada byte se lee una vez, en lecturas de ``chunk_bytes`` como mucho (1 MiB; 8 MiB si
        se piden 64); cada lectura grande es un paso propio y las celdas se convierten y se
        hashean en trozos del mismo tamaño (128 Ki o 1 Mi celdas: 1 o 8 MiB en float64); la
        fuente queda como estaba y sus ficheros, cerrados; el mismo hash que de una vez."""
        folder = self.tmp / "fuente"
        folder.mkdir()
        arrays = medium_mesh()
        path = write_npz(folder / "media.npz", arrays)
        expected = outcome(lambda: content.ContentHasher(
            "mesh", declarations=DECLARATIONS).mesh(arrays, META).digest())
        with zipfile.ZipFile(path) as archive:
            sizes = {info.filename: info.file_size for info in archive.infolist()}
        self.assertGreater(sizes["vertices.npy"], 8 * MIB)
        age_folders(folder)
        converted: list[int] = []
        float_cells = encoder._float_cells

        def spy_cells(block: np.ndarray) -> np.ndarray:
            converted.append(block.size)
            return float_cells(block)

        for chunk, limit in ((MIB, MIB), (64 * MIB, builtin.NPZ_CHUNK_BYTES)):
            with self.subTest(chunk=chunk):
                seen: list[float] = []
                converted.clear()
                with assert_source_untouched(folder), self.closes_its_files(), _ReadSpy() as spy, \
                        mock.patch.object(encoder, "_float_cells", spy_cells):
                    found = outcome(lambda chunk=chunk: read(path, chunk_bytes=chunk,
                                                             progress=seen.append))
                self.assertEqual(found, expected)
                self.assertEqual(builtin.NPZ_CHUNK_BYTES, 8 * MIB)
                self.assertEqual(sorted(spy.opened), sorted(sizes))
                for member, size in sizes.items():
                    self.assertEqual(spy.read_bytes(member), size)
                self.assertLessEqual(max(asked for _n, asked, _g in spy.reads), limit)
                data = sum(sizes.values())
                self.assertGreaterEqual(len(seen), data // limit)
                self.assertTrue(converted)
                self.assertLessEqual(max(converted), limit // 8)
                self.assertLessEqual(limit // 8, encoder.GRID_CHUNK_CELLS)


class LargeMeshTest(unittest.TestCase):
    """RF-009-07 y RNF-009-05 (plan 009 §2.2 y D-30): la malla de 1,5 M de vértices y 3 M de
    caras, comprimida como la escribe ``gis.tin`` (33,5 MB)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="gb-npz-")
        cls.path = write_npz(Path(cls._tmp.name) / "grande.npz", large_mesh())

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_same_hash_and_short_calls(self) -> None:
        """RF-009-07 y RNF-009-05: leída en trozos de 8 MiB (se piden 64 MiB), da el hash del
        código de partida y ninguna llamada del generador pasa de 0,2 s de lo propio (el tiempo
        de CPU del hilo, sin las esperas del disco ni de otros procesos, como pide RNF-009-05;
        la mejor de hasta cinco vueltas, con la prioridad del hilo subida)."""
        digests: list[object] = []
        runs: list[timing.StepsRun] = []

        def longest_call() -> float:
            request = NPZ_MESH.request("mesh", DECLARATIONS, {"main": self.path},
                                       chunk_bytes=64 * MIB)
            with timing.raised_priority():
                run = timing.drive_steps(readers.read_steps(NPZ_MESH, request),
                                         clock=time.thread_time)
            digests.append(request.hasher.digest())
            runs.append(run)
            return run.longest_s

        longest = timing.least_of(longest_call, STEP_BUDGET_S, max_attempts=5)
        for digest in digests:
            self.assertEqual(digest.data_sha256, LARGE_DATA_SHA256)
            self.assertEqual(digest.content_sha256, LARGE_CONTENT_SHA256)
        self.assertLessEqual(longest, STEP_BUDGET_S)
        self.assertGreaterEqual(runs[0].steps, 72_000_000 // builtin.NPZ_CHUNK_BYTES)


class MeshEncoderTest(unittest.TestCase):
    """RF-009-07 (D-30): ``ContentHasher.begin_mesh`` y ``MeshEncoder.finish_steps``."""

    def test_steps_give_the_same_hash(self) -> None:
        """RF-009-07: por pasos de 1 000 celdas o de 1 Mi, el mismo hash que ``mesh`` de una
        vez y que ``mesh_sha256``; el avance (0–1) no retrocede y no llega a 1 antes del final;
        lo entrega al acabar (``digest``)."""
        arrays = odd_arrays()
        expected = content.ContentHasher("mesh", declarations=DECLARATIONS).mesh(
            arrays, META).digest()
        self.assertEqual(content.mesh_sha256(arrays, META), expected.data_sha256)
        for step in (1000, encoder.GRID_CHUNK_CELLS):
            with self.subTest(step=step):
                hasher = content.ContentHasher("mesh", declarations=DECLARATIONS)
                feed = hasher.begin_mesh(arrays, META)
                self.assertIsInstance(feed, content.MeshEncoder)
                steps = feed.finish_steps(step)
                seen: list[float] = []
                while True:
                    try:
                        seen.append(next(steps))
                    except StopIteration as stop:
                        data = stop.value
                        break
                self.assertEqual(data, expected.data_sha256)
                self.assertEqual(hasher.digest(), expected)
                self.assertEqual(seen, sorted(seen))
                self.assertTrue(all(0.0 <= value < 1.0 for value in seen))
                if step == 1000:  # unas 25 000 celdas: un paso cada 1 000 a 2 000
                    self.assertGreater(len(seen), 12)

    def test_states(self) -> None:
        """RF-009-07: a medias, la malla no entrega nada (``digest``: ``RuntimeError``); no se
        cierra dos veces ni el hasher admite otros datos; ``step`` es un entero positivo."""
        hasher = content.ContentHasher("mesh", declarations=DECLARATIONS)
        feed = hasher.begin_mesh(odd_arrays(), META)
        with self.assertRaises(RuntimeError):
            hasher.mesh(odd_arrays(), META)
        steps = feed.finish_steps(1)
        next(steps)
        steps.close()
        with self.assertRaisesRegex(RuntimeError, "a medias"):
            hasher.digest()
        with self.assertRaises(RuntimeError):
            feed.finish()
        for step, error in ((0, ValueError), (1.5, TypeError), (True, TypeError)):
            with self.subTest(step=step), self.assertRaises(error):
                content.ContentHasher("mesh", declarations={}).begin_mesh(
                    odd_arrays(), META).finish_steps(step)

    def test_errors_in_the_same_order(self) -> None:
        """RF-009-07: los arrays se comprueban por nombre y cada uno entero (en trozos de 1 Mi
        celdas) antes del siguiente y de hashear nada, como ``mesh``: el mismo error y el mismo
        texto, también el de la celda de ``uint64`` que no cabe (el máximo de su trozo)."""
        huge = np.full(1_500_000, 7, dtype="<u8")
        huge[10] = np.uint64(2**63 + 1)
        huge[900_000] = np.uint64(2**64 - 1)
        cases = {
            "uint64 antes que textos": {"a": huge, "b": np.array(["x", "y"])},
            "textos antes que uint64": {"a": np.array(["x", "y"]), "b": huge},
            "objetos": {"vertices": np.arange(3.0).astype(object)},
        }
        for name, arrays in cases.items():
            with self.subTest(name):
                expected = outcome(
                    lambda arrays=arrays: content.ContentHasher(
                        "mesh", declarations={}).mesh(arrays, META).digest())
                self.assertNotEqual(expected[0], "ok")
                for step in (1000, encoder.GRID_CHUNK_CELLS):
                    hasher = content.ContentHasher("mesh", declarations={})

                    def stepped(hasher=hasher, arrays=arrays, step=step) -> object:
                        for _value in hasher.begin_mesh(arrays, META).finish_steps(step):
                            pass
                        return hasher.digest()

                    self.assertEqual(outcome(stepped), expected)
        self.assertIn(str(2**64 - 1), outcome(lambda: content.mesh_sha256({"a": huge}, META))[1])


class DamagedMeshTest(_TempCase):
    """RF-009-07 (D-30): una malla dañada da el mismo error que leerla de una vez."""

    def damaged(self) -> dict[str, tuple[Path, str]]:
        """Los ficheros dañados y la clase de su error."""
        arrays = {"vertices": np.arange(6000, dtype=np.float64).reshape(2000, 3) * 0.5,
                  "faces": (np.arange(12_000) % 2000).astype(np.int32).reshape(4000, 3)}
        found: dict[str, tuple[Path, str]] = {}

        def bytes_of(path: Path) -> bytearray:
            return bytearray(path.read_bytes())

        def member_offset(path: Path, member: str) -> int:
            """Dónde empiezan los datos de ``member`` en el zip (tras su cabecera local)."""
            with zipfile.ZipFile(path) as archive:
                info = archive.getinfo(member)
            raw = path.read_bytes()
            name_length, extra_length = struct.unpack("<HH", raw[info.header_offset + 26:
                                                                 info.header_offset + 30])
            return info.header_offset + 30 + name_length + extra_length

        def custom(name: str, members: dict[str, bytes], error: str) -> None:
            path = self.tmp / f"{name}.npz"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for member, data in members.items():
                    archive.writestr(member, data)
            found[name] = (path, error)

        def npy(array: np.ndarray, *, header: dict | None = None,
                version: tuple[int, int] = (1, 0), data: bytes | None = None) -> bytes:
            text = repr(header if header is not None else
                        np.lib.format.header_data_from_array_1_0(array))
            text = text.encode("latin1")
            body = text + b" " * (63 - (len(text) + 10) % 64) + b"\n"
            magic = np.lib.format.MAGIC_PREFIX + bytes(version)
            return magic + struct.pack("<H", len(body)) + body + (
                array.tobytes() if data is None else data)

        good = {f"{name}.npy": npy(array) for name, array in arrays.items()}
        good["meta.npy"] = npy(np.array(json.dumps(META)))

        source = write_npz(self.tmp / "base-deflate.npz", arrays)
        raw = bytes_of(source)
        cut = self.tmp / "truncado.npz"
        cut.write_bytes(bytes(raw[: len(raw) * 6 // 10]))
        found["truncado"] = (cut, "BadZipFile")

        flipped = bytes_of(source)
        start = member_offset(source, "vertices.npy")
        flipped[start + 300] ^= 0xFF
        path = self.tmp / "byte-deflate.npz"
        path.write_bytes(bytes(flipped))
        found["byte cambiado con deflate"] = (path, "")

        stored = write_npz(self.tmp / "base-stored.npz", arrays, writer="savez")
        flipped = bytes_of(stored)
        start = member_offset(stored, "vertices.npy")
        flipped[start + 20_000] ^= 0x01
        path = self.tmp / "byte-stored.npz"
        path.write_bytes(bytes(flipped))
        found["byte cambiado sin comprimir"] = (path, "BadZipFile")

        header = bytes_of(stored)
        with zipfile.ZipFile(stored) as archive:
            offset = archive.getinfo("faces.npy").header_offset
        header[offset:offset + 4] = b"PK\x09\x09"
        path = self.tmp / "cabecera-local.npz"
        path.write_bytes(bytes(header))
        found["cabecera local dañada"] = (path, "BadZipFile")

        short = {**np.lib.format.header_data_from_array_1_0(arrays["vertices"]),
                 "shape": (2010, 3)}
        custom("faltan datos", {**good, "vertices.npy": npy(arrays["vertices"], header=short)},
               "ValueError")
        custom("objetos", {**good, "faces.npy": npy(
            np.zeros(2), header={"descr": "|O", "fortran_order": False, "shape": (2,)},
            data=b"\x80\x04N.")}, "ValueError")
        custom("versión 9", {**good, "faces.npy": npy(arrays["faces"], version=(9, 0))},
               "ValueError")
        custom("cabecera ilegible", {**good, "faces.npy": np.lib.format.MAGIC_PREFIX
                                     + b"\x01\x00" + struct.pack("<H", 8) + b"{'shape'"},
               "TokenError")
        custom("no es npy", {**good, "notas.txt": b"hola"}, "TypeError")
        custom("meta no es JSON", {**good, "meta.npy": npy(np.array("hola"))}, "ValueError")
        custom("sin datos tras la cabecera", {**good, "faces.npy": npy(
            arrays["faces"], data=b"")}, "ValueError")
        huge = np.full(1_200_000, 7, dtype="<u8")
        huge[10] = np.uint64(2**63 + 1)
        huge[900_000] = np.uint64(2**64 - 1)
        custom("uint64 que no cabe", {**good, "ids.npy": npy(huge)}, "ValueError")
        path = self.tmp / "no-es-zip.npz"
        path.write_bytes(b"PK" + bytes(range(200)))
        found["PK sin zip"] = (path, "ValueError")
        return found

    def test_same_error_as_before(self) -> None:
        """RF-009-07: un zip truncado, un byte cambiado (con y sin compresión), una cabecera
        local dañada, un array con menos datos de los que dice o sin datos, de objetos, de otra
        versión del formato o con la cabecera ilegible, un miembro que no es ``.npy``, un
        ``meta`` que no es JSON, un entero que no cabe en 64 bits y un fichero que empieza por
        «PK» sin ser un zip: leídos en trozos de 1 000 bytes o de 1 MiB, el mismo error (clase y
        texto) que leerlos de una vez, sin dejar ficheros abiertos."""
        cases = self.damaged()
        self.assertEqual(len(cases), 13)
        for name, (path, kind) in cases.items():
            expected = outcome(lambda path=path: _at_once(path))
            with self.subTest(name):
                self.assertNotEqual(expected[0], "ok")
                if kind:
                    self.assertEqual(expected[0], kind)
                for chunk in (1000, MIB):
                    with self.closes_its_files():
                        found = outcome(lambda path=path, chunk=chunk: read(
                            path, chunk_bytes=chunk))
                    self.assertEqual(found, expected)
        self.assertIn(str(2**64 - 1), outcome(lambda: _at_once(cases["uint64 que no cabe"][0]))[1])

    def test_cancel_between_chunks(self) -> None:
        """RF-009-07: parar entre dos trozos (al leer un miembro o al hashear) da
        ``ReadCancelled``, cierra el fichero y no entrega ningún hash."""
        path = write_npz(self.tmp / "media.npz", medium_mesh(100_000))
        total = len(_steps_of(path, 64 * 1024))
        self.assertGreater(total, 20)
        for stop in (2, total // 2, total - 2):
            with self.subTest(stop=stop):
                request = NPZ_MESH.request("mesh", DECLARATIONS, {"main": path},
                                           chunk_bytes=64 * 1024)
                calls = iter(range(10**9))
                with self.closes_its_files(), self.assertRaises(readers.ReadCancelled):
                    readers.read_content(NPZ_MESH, request,
                                         cancelled=lambda: next(calls) >= stop)
                with self.assertRaises(RuntimeError):
                    request.hasher.digest()


def _steps_of(path: Path, chunk: int) -> list[float]:
    seen: list[float] = []
    read(path, chunk_bytes=chunk, progress=seen.append)
    return seen


if __name__ == "__main__":
    unittest.main()
