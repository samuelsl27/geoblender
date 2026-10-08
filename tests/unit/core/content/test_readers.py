# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido (spec 008, T11; RF-008-08, RF-008-09; ADR-0024 §5 y §6, ADR-0025 §2 y
§7; plan 008 §5.3.1 y §5.4.1).

Cada importador declara un **lector de contenido** (``ContentReader``) con su identificador y
su versión (``gis.geotiff@1``), los tipos que da, si lee sobre una copia, si su fuente es
SQLite, su estimación de tiempo y su función ``read``: un generador que escribe lo leído en el
``ContentHasher`` de su petición (``ReadRequest``) y da su progreso (0–1) tras cada trozo, y
cada ``yield`` es un punto de cancelación. Lo registra el módulo dueño desde ``bl/`` y lo quita
al desactivarse; ``READERS`` es la vista de solo lectura del registro y ``reader("x@n")`` lo
busca por su identificador con versión, que cada entrada y cada dato guardan para siempre
(ADR-0024 §6). ``plan_hash`` decide dónde se hashea: lo que está dentro del proyecto, siempre en
el hilo de Blender por trozos; una fuente externa estimada en más de 1 s, en un trabajo de la
004 (``core_content_hash``).

El lector de prueba ``test.npy_grid@1`` (``tests/support/provenance_readers.py``) lee una
rejilla de un ``.npy`` por bandas de filas: su hash es el de ``ContentHasher.grid`` con la
misma cabecera y las mismas celdas, el de los vectores de referencia de ``gbch/1``.
"""

from __future__ import annotations

import inspect
import math
import os
import tempfile
import unittest
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.support import content_golden
from tests.support import provenance_readers as test_readers
from tests.support.package import import_geoblender

readers = import_geoblender("core.content.readers")
content = import_geoblender("core.content")
errors = import_geoblender("core.errors")

NPY_GRID = test_readers.NPY_GRID
NPY_GRID_ID = test_readers.NPY_GRID_ID
DECLARATIONS = {
    "conventions": {},
    "crs_h": {"epsg": 25830},
    "crs_v": {"epsg": 5782},
}
SETTINGS = {
    "x0": 715000.0,
    "y0": 4378000.0,
    "dx": 5.0,
    "dy": 5.0,
    "cell": "area",
    "nodata": -9999.0,
    "crs": {"epsg": 25830},
}
MB = 1_000_000


def _unused_reader(request: object) -> Iterator[float]:
    """Un lector que nunca se ejecuta (solo se registra)."""
    yield 1.0


def _demo_reader(
    reader_id: str = "test.demo",
    version: int = 1,
    *,
    read: object = _unused_reader,
    kinds: tuple[str, ...] = ("table",),
    estimate_s: object = None,
    worker: bool = True,
) -> object:
    return readers.ContentReader(
        reader_id, version, kinds, False, False, estimate_s, read, worker
    )


def _grid() -> np.ndarray:
    """Una rejilla float32 de 11 × 7 con NaN de otra carga, −0,0 y el sin dato."""
    values = np.arange(77, dtype="<f4").reshape(11, 7) * np.float32(0.25) + np.float32(600.0)
    values[0, 3] = np.float32("nan")
    values.view("<u4")[4, 4] = 0x7FC00001  # NaN con carga
    values[2, 1] = np.float32(-0.0)
    values[9, 6] = np.float32(-9999.0)
    return values


def _expected(array: np.ndarray, settings: dict = SETTINGS, declarations: dict = DECLARATIONS):
    """Lo que da ``ContentHasher.grid`` con la cabecera escrita a mano y todas las filas de
    una vez."""
    value_class = {"f": "float", "i": "int", "u": "int", "b": "bool"}[array.dtype.kind]
    header = {
        "rows": array.shape[0],
        "columns": array.shape[1],
        "class": value_class,
        **settings,
    }
    hasher = content.ContentHasher("raster", declarations=declarations, reader=NPY_GRID_ID)
    return hasher.grid(header, [array]).digest()


class _TempCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-rd-")
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

    def npy(self, array: np.ndarray, name: str = "rejilla.npy") -> Path:
        return test_readers.write_grid(self.tmp / name, array)

    def request(self, path: Path, *, chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES,
                settings: dict = SETTINGS):
        return NPY_GRID.request(
            "raster", DECLARATIONS, {"main": path}, settings, chunk_bytes=chunk_bytes
        )


class RegistryTest(unittest.TestCase):
    """RF-008-08 y RF-008-09 (ADR-0024 §5 y §6; ADR-0025 §2): el registro de los lectores."""

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-008-08: un lector se registra y se quita sin dejar rastro: después, el
        registro es el de antes, ``reader`` ya no lo encuentra y se puede volver a
        registrar."""
        before = dict(readers.READERS)
        demo = _demo_reader()
        self.addCleanup(readers.unregister_reader, "test.demo")
        readers.register_reader(demo)
        self.assertIs(readers.READERS["test.demo@1"], demo)
        self.assertIs(readers.reader("test.demo@1"), demo)
        self.assertIs(content.READERS, readers.READERS)
        self.assertEqual(readers.unregister_reader("test.demo@1"), 1)
        self.assertEqual(dict(readers.READERS), before)
        with self.assertRaises(errors.ValidationError) as caught:
            readers.reader("test.demo@1")
        self.assertEqual(caught.exception.code, "core.reader_unregistered")
        self.assertIn("test.demo@1", str(caught.exception))
        self.assertEqual(readers.unregister_reader("test.demo@1"), 0)  # idempotente
        readers.register_reader(demo)
        self.assertIs(readers.reader("test.demo@1"), demo)

    def test_same_id_and_version_rejected(self) -> None:
        """RF-008-08 (ADR-0024 §6): dos lectores con el mismo identificador y la misma
        versión se rechazan y el registrado se queda; otra versión del mismo lector convive
        con él (las versiones antiguas se conservan) y quitar el identificador sin versión
        quita todas."""
        first = _demo_reader()
        self.addCleanup(readers.unregister_reader, "test.demo")
        readers.register_reader(first)
        with self.assertRaises(ValueError) as caught:
            readers.register_reader(_demo_reader(kinds=("vector",)))
        self.assertIn("test.demo@1", str(caught.exception))
        self.assertIs(readers.reader("test.demo@1"), first)
        second = _demo_reader(version=2)
        readers.register_reader(second)
        self.assertIs(readers.reader("test.demo@1"), first)
        self.assertIs(readers.reader("test.demo@2"), second)
        self.assertEqual(readers.unregister_reader("test.demo"), 2)
        self.assertNotIn("test.demo@1", readers.READERS)
        self.assertNotIn("test.demo@2", readers.READERS)

    def test_registry_is_read_only(self) -> None:
        """RF-008-08: ``READERS`` es una vista de solo lectura; solo se registra un
        ``ContentReader``."""
        with self.assertRaises(TypeError):
            readers.READERS["test.demo@1"] = _demo_reader()  # type: ignore[index]
        with self.assertRaises(TypeError):
            readers.register_reader("test.demo@1")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            readers.reader("test.demo")  # sin versión

    def test_definition_is_checked(self) -> None:
        """RF-008-08 (ADR-0024 §5): identificador ``<módulo>.<nombre>`` sin versión, versión
        entera positiva, tipos de ``gbch/1`` y funciones donde tocan."""
        demo = _demo_reader(kinds=("raster", "vector"))
        self.assertEqual(demo.id, "test.demo@1")
        self.assertEqual(demo.module, "test")
        self.assertEqual(demo.kinds, ("raster", "vector"))
        for bad_id in ("Test.demo", "demo", "test.demo@1", "test..demo", "", "test.demo "):
            with self.subTest(reader_id=bad_id), self.assertRaises(ValueError):
                _demo_reader(bad_id)
        for bad_version in (0, -1, True, 1.0, "1"):
            with self.subTest(version=bad_version), self.assertRaises((ValueError, TypeError)):
                _demo_reader(version=bad_version)  # type: ignore[arg-type]
        for bad_kinds in ((), ("rejilla",), ("raster", "raster"), "raster"):
            with self.subTest(kinds=bad_kinds), self.assertRaises((ValueError, TypeError)):
                _demo_reader(kinds=bad_kinds)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            readers.ContentReader("test.demo", 1, ("table",), 1, False, None, _unused_reader)
        with self.assertRaises(TypeError):
            readers.ContentReader("test.demo", 1, ("table",), False, "no", None, _unused_reader)
        with self.assertRaises(TypeError):
            _demo_reader(read="leer")
        with self.assertRaises(TypeError):
            _demo_reader(estimate_s=2.0)
        with self.assertRaises(TypeError):
            _demo_reader(worker=1)  # type: ignore[arg-type]


class ReadRequestTest(_TempCase):
    """RF-008-08 (ADR-0024 §5 y §6): la petición lleva su propio ``ContentHasher`` con el
    identificador del lector, su tipo, sus declaraciones y su normalizador."""

    def test_request_carries_its_hasher(self) -> None:
        """RF-008-08: la petición crea su ``ContentHasher`` (de un solo uso) con el lector y
        el normalizador; sus ficheros y ajustes son copias de solo lectura y lo que se le
        pasó no cambia."""
        settings = dict(SETTINGS)
        files = {"main": str(self.tmp / "rejilla.npy")}
        request = NPY_GRID.request("raster", DECLARATIONS, files, settings)
        self.assertEqual(request.reader, NPY_GRID_ID)
        self.assertEqual(request.kind, "raster")
        self.assertEqual(request.normalizer, content.NORMALIZER)
        self.assertEqual(request.files, {"main": self.tmp / "rejilla.npy"})
        self.assertIsInstance(request.files["main"], Path)
        self.assertEqual(request.hasher.reader, NPY_GRID_ID)
        self.assertEqual(request.hasher.kind, "raster")
        with self.assertRaises(TypeError):
            request.settings["x0"] = 0.0  # type: ignore[index]
        with self.assertRaises(TypeError):
            request.files["prj"] = self.tmp  # type: ignore[index]
        settings["x0"] = 1.0
        self.assertEqual(request.settings["x0"], SETTINGS["x0"])
        self.assertEqual(files, {"main": str(self.tmp / "rejilla.npy")})

    def test_request_is_checked(self) -> None:
        """RF-008-08: un tipo que el lector no da, sin fichero principal, un papel mal
        escrito, un normalizador desconocido o un tamaño de trozo no positivo se
        rechazan."""
        path = self.tmp / "rejilla.npy"
        with self.assertRaises(ValueError):
            NPY_GRID.request("vector", DECLARATIONS, {"main": path}, SETTINGS)
        with self.assertRaises(ValueError):
            NPY_GRID.request("raster", DECLARATIONS, {}, SETTINGS)
        with self.assertRaises(ValueError):
            NPY_GRID.request("raster", DECLARATIONS, {"prj": path}, SETTINGS)
        with self.assertRaises(ValueError):
            NPY_GRID.request("raster", DECLARATIONS, {"main": path, "Prj": path}, SETTINGS)
        with self.assertRaises(ValueError):
            NPY_GRID.request("raster", DECLARATIONS, {"main": path}, SETTINGS,
                             normalizer="gbch/0")
        for chunk in (0, -1):
            with self.subTest(chunk=chunk), self.assertRaises(ValueError):
                NPY_GRID.request("raster", DECLARATIONS, {"main": path}, SETTINGS,
                                 chunk_bytes=chunk)
        with self.assertRaises(TypeError):
            NPY_GRID.request("raster", DECLARATIONS, {"main": path}, SETTINGS,
                             chunk_bytes=1.5)  # type: ignore[arg-type]

    def test_request_of_another_reader_is_rejected(self) -> None:
        """RF-008-08 (ADR-0024 §6): cada dato se hashea con **su** lector: una petición
        hecha para otro lector no se lee."""
        request = _demo_reader(kinds=("raster",)).request(
            "raster", DECLARATIONS, {"main": self.tmp / "rejilla.npy"}, SETTINGS
        )
        with self.assertRaises(ValueError) as caught:
            list(readers.read_steps(NPY_GRID, request))
        self.assertIn("test.demo@1", str(caught.exception))


class StepsTest(_TempCase):
    """RF-008-09 (ADR-0024 §7, ADR-0025 §7): un lector es un generador que da su progreso
    tras cada trozo y se puede cancelar entre dos trozos."""

    def test_reader_is_a_generator_with_progress(self) -> None:
        """RF-008-09: el lector de prueba es un generador; con trozos de 3 filas, una
        rejilla de 11 filas da 4 pasos con su progreso creciente hasta 1, y
        ``read_content`` los pasa a ``progress`` y devuelve el hash."""
        self.assertTrue(inspect.isgeneratorfunction(NPY_GRID.read))
        array = _grid()
        path = self.npy(array)
        row_bytes = array.shape[1] * array.dtype.itemsize
        request = self.request(path, chunk_bytes=3 * row_bytes)
        seen: list[float] = []
        digest = readers.read_content(NPY_GRID, request, progress=seen.append)
        self.assertEqual(seen, [3 / 11, 6 / 11, 9 / 11, 1.0])
        self.assertEqual(digest, _expected(array))
        steps = list(readers.read_steps(NPY_GRID, self.request(path, chunk_bytes=row_bytes)))
        self.assertEqual(len(steps), 11)
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(steps[-1], 1.0)

    def test_cancel_between_chunks(self) -> None:
        """RF-008-09: pedir que pare tras el segundo trozo para la lectura entre dos trozos
        (``ReadCancelled`` con el progreso alcanzado), cierra el fichero (se puede borrar
        enseguida) y el hash queda sin datos."""
        array = _grid()
        path = self.npy(array)
        row_bytes = array.shape[1] * array.dtype.itemsize
        request = self.request(path, chunk_bytes=3 * row_bytes)
        seen: list[float] = []
        with self.closes_its_files(), self.assertRaises(readers.ReadCancelled) as caught:
            readers.read_content(
                NPY_GRID, request, progress=seen.append, cancelled=lambda: len(seen) >= 2
            )
        self.assertEqual(seen, [3 / 11, 6 / 11])
        self.assertEqual(caught.exception.reader, NPY_GRID_ID)
        self.assertEqual(caught.exception.progress, 6 / 11)
        self.assertIn(NPY_GRID_ID, str(caught.exception))
        os.remove(path)  # en Windows falla si el lector lo dejó abierto
        with self.assertRaises(RuntimeError):
            request.hasher.digest()

    def test_cancel_before_starting_reads_nothing(self) -> None:
        """RF-008-09: la cancelación se consulta antes de cada trozo, también antes del
        primero: si ya está pedida, el lector no llega a ejecutarse."""
        calls: list[object] = []

        def spy(request: object) -> Iterator[float]:
            calls.append(request)
            yield 1.0

        demo = _demo_reader(read=spy)
        request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
        with self.assertRaises(readers.ReadCancelled) as caught:
            readers.read_content(demo, request, cancelled=lambda: True)
        self.assertEqual(caught.exception.progress, 0.0)
        self.assertEqual(calls, [])

    def test_closing_the_steps_runs_the_reader_cleanup(self) -> None:
        """RF-008-09: cerrar los pasos a medias (cancelar) cierra el generador del lector:
        su ``finally`` se ejecuta y no lee más trozos."""
        events: list[str] = []

        def chunked(request: readers.ReadRequest) -> Iterator[float]:
            feed = request.hasher.begin_rows({"n": "int"}, True)
            try:
                for index in range(4):
                    events.append(f"trozo {index}")
                    feed.update([[index]])
                    yield (index + 1) / 4
                feed.finish()
            finally:
                events.append("cerrado")

        demo = _demo_reader(read=chunked)
        request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
        steps = readers.read_steps(demo, request)
        self.assertEqual(next(steps), 0.25)
        steps.close()
        self.assertEqual(events, ["trozo 0", "cerrado"])
        request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
        digest = readers.read_content(demo, request)
        expected = content.ContentHasher("table", declarations=DECLARATIONS, reader="test.demo@1")
        self.assertEqual(digest, expected.rows({"n": "int"}, True, [[0], [1], [2], [3]]).digest())

    def test_bad_progress_is_rejected(self) -> None:
        """RF-008-09: un progreso que retrocede, se sale de [0, 1], no es finito o no es un
        número es un fallo del lector y se dice con su identificador."""
        cases = (
            ((0.5, 0.4), ValueError),
            ((1.5,), ValueError),
            ((-0.1,), ValueError),
            ((math.nan,), ValueError),
            ((True,), TypeError),
            (("0,5",), TypeError),
        )
        for values, error in cases:
            def bad(request: object, values: tuple = values) -> Iterator[object]:
                yield from values

            demo = _demo_reader(read=bad)
            request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
            with self.subTest(values=values), self.assertRaises(error) as caught:
                list(readers.read_steps(demo, request))
            self.assertIn("test.demo@1", str(caught.exception))

    def test_reader_that_gives_no_data_fails(self) -> None:
        """RF-008-08: un lector que termina sin entregar sus datos al hasher (o que no es un
        iterador) falla con su identificador."""
        def lazy(request: object) -> Iterator[float]:
            yield 1.0

        demo = _demo_reader(read=lazy)
        request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
        with self.assertRaises(RuntimeError) as caught:
            readers.read_content(demo, request)
        self.assertIn("test.demo@1", str(caught.exception))
        demo = _demo_reader(read=lambda request: 1.0)
        request = demo.request("table", DECLARATIONS, {"main": self.tmp / "t.csv"}, {})
        with self.assertRaises(TypeError):
            readers.read_content(demo, request)


class PlanHashTest(unittest.TestCase):
    """RF-008-09 (ADR-0025 §7; plan 008 §5.4.1): dónde se hashea una fuente."""

    def test_project_sources_always_inline(self) -> None:
        """RF-008-09: lo que está dentro del proyecto (un fichero o una tabla suya) se
        hashea siempre en el hilo, por trozos, aunque sea grande o su estimación no se
        sepa: nada del proyecto va a un trabajo."""
        unknown = _demo_reader(estimate_s=lambda size: None)
        for location in ("project", "project_table"):
            with self.subTest(location=location):
                self.assertEqual(readers.plan_hash(NPY_GRID, location, 10_000 * MB), "inline")
                self.assertEqual(readers.plan_hash(unknown, location, None), "inline")

    def test_external_sources_by_estimate(self) -> None:
        """RF-008-09: una fuente externa (con ruta propia o junto al proyecto original)
        estimada en ≤ 1 s se hashea en el hilo; en más de 1 s, o si no se sabe, en un
        trabajo."""
        cases = ((0.5, "inline"), (1.0, "inline"), (1.000001, "job"), (40.0, "job"),
                 (None, "job"))
        for estimate, expected in cases:
            demo = _demo_reader(estimate_s=lambda size, estimate=estimate: estimate)
            for location in ("external", "original"):
                with self.subTest(estimate=estimate, location=location):
                    self.assertEqual(readers.plan_hash(demo, location, 1), expected)
        self.assertEqual(readers.plan_hash(_demo_reader(), "external", 1), "job")

    def test_estimate_uses_all_the_files(self) -> None:
        """RF-008-09: la estimación recibe el tamaño de todos los ficheros de la fuente
        (``stat`` de cada uno, o su tamaño en bytes)."""
        sizes: list[int] = []

        def estimate(size: int) -> float:
            sizes.append(size)
            return 0.1

        demo = _demo_reader(estimate_s=estimate)
        stats = [SimpleNamespace(st_size=3 * MB), SimpleNamespace(st_size=250)]
        self.assertEqual(readers.plan_hash(demo, "external", stats), "inline")
        self.assertEqual(readers.plan_hash(demo, "external", stats[0]), "inline")
        self.assertEqual(readers.plan_hash(demo, "external", 7), "inline")
        self.assertEqual(sizes, [3 * MB + 250, 3 * MB, 7])
        with tempfile.TemporaryDirectory(prefix="gb-rd-") as tmp:
            path = Path(tmp) / "fuente.bin"
            path.write_bytes(b"0123456789")
            self.assertEqual(readers.plan_hash(demo, "external", path.stat()), "inline")
        self.assertEqual(sizes[-1], 10)

    def test_test_reader_estimate(self) -> None:
        """RF-008-09: el lector de prueba estima por el tamaño del ``.npy``: 50 MB, en el
        hilo; 200 MB, en un trabajo."""
        self.assertEqual(readers.plan_hash(NPY_GRID, "external", 50 * MB), "inline")
        self.assertEqual(readers.plan_hash(NPY_GRID, "external", 200 * MB), "job")

    def test_reader_that_cannot_go_to_a_job(self) -> None:
        """RF-008-09: un lector que no puede ir al trabajo de hash (``worker`` falso) se
        ejecuta en el hilo, por trozos, aunque su estimación pase de 1 s."""
        demo = _demo_reader(estimate_s=lambda size: 60.0, worker=False)
        self.assertEqual(readers.plan_hash(demo, "external", 1), "inline")

    def test_bad_arguments(self) -> None:
        """RF-008-09: una ubicación desconocida, una fuente externa sin tamaño o una
        estimación que no es un número de segundos se rechazan."""
        with self.assertRaises(ValueError):
            readers.plan_hash(NPY_GRID, "fuera", 1)
        with self.assertRaises(TypeError):
            readers.plan_hash(NPY_GRID, "external", None)
        with self.assertRaises(TypeError):
            readers.plan_hash(NPY_GRID, "external", True)
        with self.assertRaises(ValueError):
            readers.plan_hash(NPY_GRID, "external", -1)
        with self.assertRaises(TypeError):
            readers.plan_hash("test.npy_grid@1", "external", 1)  # type: ignore[arg-type]
        for estimate in (-1.0, math.nan, math.inf, "1", True):
            demo = _demo_reader(estimate_s=lambda size, estimate=estimate: estimate)
            with self.subTest(estimate=estimate), self.assertRaises((ValueError, TypeError)):
                readers.plan_hash(demo, "external", 1)


class NpyGridReaderTest(_TempCase):
    """RF-008-08 (ADR-0024 §4 y §5): el lector de prueba ``test.npy_grid@1`` hashea una
    rejilla ``npy`` igual que ``ContentHasher.grid``."""

    def test_same_hash_as_content_hasher(self) -> None:
        """RF-008-08: con trozos de una fila, de 4 filas o de toda la rejilla, el lector da
        exactamente el ``ContentDigest`` de ``ContentHasher.grid`` (con el identificador del
        lector), y el mismo hash de datos y de contenido que sin él."""
        array = _grid()
        path = self.npy(array)
        expected = _expected(array)
        row_bytes = array.shape[1] * array.dtype.itemsize
        for chunk in (row_bytes, 4 * row_bytes, readers.DEFAULT_CHUNK_BYTES):
            with self.subTest(chunk=chunk):
                digest = readers.read_content(NPY_GRID, self.request(path, chunk_bytes=chunk))
                self.assertEqual(digest, expected)
        self.assertEqual(expected.reader, NPY_GRID_ID)
        plain = content.ContentHasher("raster", declarations=DECLARATIONS).grid(
            {"rows": 11, "columns": 7, "class": "float", **SETTINGS}, [array]
        ).digest()
        self.assertEqual(
            (plain.data_sha256, plain.content_sha256),
            (expected.data_sha256, expected.content_sha256),
        )

    def test_container_does_not_count(self) -> None:
        """RF-008-08: el mismo dato en float32 o en float64 y en uno u otro orden de bytes da
        el mismo hash; una celda cambiada o el sin dato cambiado, otro."""
        array = _grid()
        reference = readers.read_content(NPY_GRID, self.request(self.npy(array, "a.npy")))
        for name, variant in (("f8.npy", array.astype("<f8")), ("be.npy", array.astype(">f4")),
                              ("be8.npy", array.astype(">f8"))):
            with self.subTest(name=name):
                digest = readers.read_content(NPY_GRID, self.request(self.npy(variant, name)))
                self.assertEqual(digest, reference)
        changed = array.copy()
        changed[5, 5] = np.nextafter(changed[5, 5], np.float32(np.inf))
        digest = readers.read_content(NPY_GRID, self.request(self.npy(changed, "c.npy")))
        self.assertNotEqual(digest.data_sha256, reference.data_sha256)
        other = dict(SETTINGS, nodata=-32768.0)
        digest = readers.read_content(
            NPY_GRID, self.request(self.npy(array, "d.npy"), settings=other)
        )
        self.assertNotEqual(digest.content_sha256, reference.content_sha256)

    def test_golden_grids(self) -> None:
        """RF-008-08 (ADR-0024 §6): cada rejilla de los vectores de referencia de
        ``gbch/1`` (float32, float64 *big endian* con NaN de otras cargas, int16 y booleana),
        escrita en un ``.npy`` con su tipo de celda, da los hashes guardados."""
        cases = [case for case in content_golden.load()["cases"] if "grid" in case]
        self.assertEqual(len(cases), 4)
        for case in cases:
            with self.subTest(case=case["id"]):
                header, array = content_golden.decode_grid(case["grid"])
                settings = {key: header[key] for key in test_readers.SETTINGS_KEYS}
                path = self.npy(array, f"{case['id']}.npy")
                request = NPY_GRID.request(
                    case["kind"], case["declarations"], {"main": path}, settings,
                    chunk_bytes=1,
                )
                digest = readers.read_content(NPY_GRID, request)
                self.assertEqual(digest.data_sha256, case["data_sha256"])
                self.assertEqual(digest.content_sha256, case["content_sha256"])
                self.assertEqual(digest.reader, NPY_GRID_ID)

    def test_unreadable_files_are_rejected(self) -> None:
        """RF-008-08: un ``.npy`` en orden Fortran, que no es 2-D o cortado se rechaza (sin
        hash) con el motivo y el fichero queda cerrado."""
        array = _grid()
        fortran = self.npy(np.asfortranarray(array), "f.npy")
        flat = self.npy(array.ravel(), "plano.npy")
        cut = self.npy(array, "cortado.npy")
        cut.write_bytes(cut.read_bytes()[:-5])
        row_bytes = array.shape[1] * array.dtype.itemsize
        cases = ((fortran, "Fortran"), (flat, "2-D"), (cut, "cortado.*fila 9 de 11"))
        for path, reason in cases:
            with self.subTest(path=path.name):
                request = self.request(path, chunk_bytes=4 * row_bytes)
                with self.closes_its_files(), self.assertRaisesRegex(ValueError, reason):
                    readers.read_content(NPY_GRID, request)
                os.remove(path)

    def test_registered_helper(self) -> None:
        """RF-008-08: la ayuda de las pruebas registra el lector de prueba y lo quita al
        salir, sin dejar rastro."""
        before = dict(readers.READERS)
        with test_readers.registered():
            self.assertIs(readers.reader(NPY_GRID_ID), NPY_GRID)
        self.assertEqual(dict(readers.READERS), before)


if __name__ == "__main__":
    unittest.main()
