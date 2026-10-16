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

Los lectores de ``core`` (T12, ``core.content.builtin``; RF-008-08, RF-008-14):
``core.gpkg_layer@1`` (capa o tabla de un GeoPackage, del proyecto o externo, con selector
fijo o de entradas vigentes, sobre una copia privada si la base tiene ``-wal``, la cabecera en
WAL o un diario caliente), ``core.document@1`` (los bytes) y ``core.npz_mesh@1`` (una malla
``npz`` de ``meshes/``). Ninguno crea, cambia ni borra nada junto a la fuente.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tests.support import content_golden, dataset_tables, wkb_build
from tests.support import provenance_readers as test_readers
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_data import (
    BOUNDARY_V1,
    BOUNDARY_V1_QGIS,
    BOUNDARY_V2,
    DATA_DIR,
    LAYER,
    PARCELS_V1,
    PARCELS_V2,
    REPORT,
    make_wal_variant,
)
from tests.support.trees import age_folders
from tests.unit.core.provenance.test_schema import input_row, operation_row

readers = import_geoblender("core.content.readers")
content = import_geoblender("core.content")
errors = import_geoblender("core.errors")
builtin = import_geoblender("core.content.builtin")
hashing = import_geoblender("core.hashing")
gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
provenance_schema = import_geoblender("core.provenance.schema")

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


# --- Lectores de core (T12) ------------------------------------------------------------------

GPKG_LAYER = builtin.GPKG_LAYER
DOCUMENT = builtin.DOCUMENT
NPZ_MESH = builtin.NPZ_MESH
EPSG = {"epsg": 25830}
NOT_APPLICABLE = {"crs_h": {"not_applicable": True}, "crs_v": {"not_applicable": True}}
TABLE_DECLARATIONS = {"conventions": {"decimal": ","}, **NOT_APPLICABLE}
BOUNDARY_FIELDS = {"codigo": "text", "tipo": "text"}
SHARED_COLUMNS = [["input_uid", "text"], ["codigo", "text"], ["ley", "float"], ["nota", "text"]]
CURRENT_INPUTS = {"column": "input_uid", "of": "current_inputs"}
OTHER_OPERATION = "00000000-0000-4000-8000-0000000000c2"


def _gpkg_request(
    path: Path,
    layer: str = LAYER,
    selector: dict | None = None,
    *,
    kind: str = "vector",
    chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES,
):
    settings: dict = {"layer": layer}
    if selector is not None:
        settings["selector"] = selector
    declarations = DECLARATIONS if kind == "vector" else TABLE_DECLARATIONS
    return GPKG_LAYER.request(
        kind, declarations, {"main": path}, settings, chunk_bytes=chunk_bytes
    )


def _features(features: list, fields: dict = BOUNDARY_FIELDS, dims: str = "XY",
              crs: dict | None = EPSG):
    """Lo que da ``ContentHasher.features`` con las entidades escritas a mano."""
    hasher = content.ContentHasher("vector", declarations=DECLARATIONS, reader=GPKG_LAYER.id)
    return hasher.features(fields, dims, crs, features).digest()


def _boundary(parcels: tuple) -> object:
    """El hash esperado de una capa de límites, con el WKB escrito por otro camino."""
    return _features(
        [
            (wkb_build.iso_le(("Polygon", [list(ring)])), {"codigo": code, "tipo": kind})
            for code, kind, ring in parcels
        ]
    )


def _rows(columns: list, rows: list) -> object:
    """Lo que da ``ContentHasher.rows`` sin orden con las filas escritas a mano."""
    hasher = content.ContentHasher("table", declarations=TABLE_DECLARATIONS, reader=GPKG_LAYER.id)
    return hasher.rows(columns, False, rows).digest()


def _insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


FID = "fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "


def _attributes(
    path: Path, columns: str, rows: list, table: str = "ensayos", *, key: str = FID
) -> Path:
    """Un GeoPackage nuevo con una tabla de atributos ``table`` de columnas ``columns``
    (SQL, tras la clave ``key``) y sus filas."""
    crs = georef.load_catalog().horizontal(25830)
    with gpkg.GpkgConnection.open_write(path, create=True) as db, db.transaction() as conn:
        base.create_base(conn, crs)
        conn.execute(f'CREATE TABLE "{table}" ({key}{columns})')
        conn.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier) "
            "VALUES (?, 'attributes', ?)",
            (table, table),
        )
        if rows:
            marks = ", ".join("?" for _ in rows[0])
            names = ", ".join(column.split()[0] for column in columns.split(", "))
            conn.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', rows)
    return path


def _private_files(root: Path) -> list[str]:
    return sorted(path.name for path in root.rglob("*") if path.is_file())


def _square(index: int) -> list[list[float]]:
    """El anillo de la parcela ``index`` de :func:`_parcels` (un cuadrado de 5 m)."""
    return wkb_build.square(715_000.0 + 10.0 * (index % 20), 4_378_000.0 + 10.0 * (index // 20),
                            5.0)


def _code(index: int) -> str:
    return f"P-{index:04d}"


def _parcels(path: Path, count: int) -> Path:
    """Un GeoPackage nuevo con la capa ``parcelas`` (EPSG:25830) de ``count`` cuadrados con
    su código, con ``fid`` de 1 a ``count``."""
    crs = georef.load_catalog().horizontal(25830)
    with gpkg.GpkgConnection.open_write(path, create=True) as db, db.transaction() as conn:
        base.create_base(conn, crs)
        base.create_feature_table(
            conn, "parcelas", "POLYGON", 25830, False, [base.ColumnDef("codigo", "TEXT")],
            "Parcelas",
        )
        conn.executemany(
            "INSERT INTO parcelas (geom, codigo) VALUES (?, ?)",
            ((gpkg.encode_geometry("POLYGON", [np.array(_square(index))], 25830, False),
              _code(index)) for index in range(count)),
        )
    return path


def _read_share(fraction: float) -> float:
    """El progreso de ``core.gpkg_layer@1`` con ``fraction`` de las filas leídas: entre la
    parte del recuento y la del cierre del hash (T67)."""
    return builtin.COUNT_SHARE + builtin.READ_SHARE * fraction


class BuiltinReadersTest(unittest.TestCase):
    """RF-008-08 (ADR-0024 §5 y §6): los lectores de ``core``."""

    def test_declarations(self) -> None:
        """RF-008-08 y RF-008-09: identificador, versión, tipos, si su fuente es SQLite, si
        se lee sobre una copia y su estimación (en el hilo hasta 1 s de lectura); importar el
        módulo no los registra (lo hace ``bl/``)."""
        self.assertEqual(
            [found.id for found in builtin.CONTENT_READERS],
            ["core.gpkg_layer@1", "core.document@1", "core.npz_mesh@1"],
        )
        self.assertEqual(GPKG_LAYER.kinds, ("vector", "table"))
        self.assertEqual(DOCUMENT.kinds, ("document", "report"))
        self.assertEqual(NPZ_MESH.kinds, ("mesh",))
        speeds = (
            (GPKG_LAYER, builtin.GPKG_BYTES_PER_S),
            (DOCUMENT, builtin.DOCUMENT_BYTES_PER_S),
            (NPZ_MESH, builtin.NPZ_BYTES_PER_S),
        )
        for found, speed in speeds:
            with self.subTest(reader=found.id):
                self.assertEqual(found.sqlite, found is GPKG_LAYER)
                self.assertFalse(found.needs_copy)  # la copia de un GPKG en WAL la hace él
                self.assertTrue(found.worker)
                self.assertEqual(found.module, "core")
                self.assertTrue(inspect.isgeneratorfunction(found.read))
                self.assertNotIn(found.id, readers.READERS)
                self.assertEqual(readers.plan_hash(found, "external", speed), "inline")
                self.assertEqual(readers.plan_hash(found, "external", speed + 1), "job")
                self.assertEqual(readers.plan_hash(found, "project", 100 * speed), "inline")
        self.assertEqual(
            builtin.INACTIVE_INPUT_STATUSES, provenance_schema.INACTIVE_INPUT_STATUSES
        )


class GpkgLayerReaderTest(_TempCase):
    """RF-008-08 y RF-008-14: ``core.gpkg_layer@1`` sobre GeoPackages externos."""

    def source(self, *names: str) -> Path:
        """Una carpeta de fuente con copias de los datos sintéticos, envejecida."""
        folder = self.tmp / "fuente"
        folder.mkdir(exist_ok=True)
        for name in names:
            shutil.copyfile(DATA_DIR / name, folder / name)
        age_folders(folder)
        return folder

    def test_same_content_in_another_container(self) -> None:
        """RF-008-08 y RF-008-14 (CE-008-01): ``Limites_v1.gpkg`` y ``Limites_v1_qgis.gpkg``
        (las mismas entidades reescritas por QGIS en otro orden, con otros ``fid``, otro
        ``last_change`` y ``VACUUM``) tienen otra huella y dan los mismos hashes de datos y de
        contenido, los de las entidades escritas a mano; ``Limites_v2.gpkg`` (un vértice
        movido 143 m), otros. Leerlos no deja nada junto a ellos."""
        folder = self.source(BOUNDARY_V1, BOUNDARY_V1_QGIS, BOUNDARY_V2)
        names = (BOUNDARY_V1, BOUNDARY_V1_QGIS, BOUNDARY_V2)
        with assert_source_untouched(folder), self.closes_its_files():
            v1, qgis, v2 = (
                readers.read_content(GPKG_LAYER, _gpkg_request(folder / name)) for name in names
            )
        self.assertNotEqual(
            hashing.sha256_file(folder / BOUNDARY_V1),
            hashing.sha256_file(folder / BOUNDARY_V1_QGIS),
        )
        self.assertEqual(qgis, v1)
        self.assertEqual(v1, _boundary(PARCELS_V1))
        self.assertEqual(v2, _boundary(PARCELS_V2))
        self.assertNotEqual(v2.data_sha256, v1.data_sha256)
        self.assertNotEqual(v2.content_sha256, v1.content_sha256)
        self.assertEqual(v1.reader, "core.gpkg_layer@1")

    def test_progress_and_cancel(self) -> None:
        """RF-008-09, RF-008-14 y RNF-008-11: tras abrir la base da 0 y luego el progreso
        por filas, entre la parte del recuento y la del cierre del hash (T67; tres filas se
        cuentan y se cierran en un solo trozo); cancelar entre dos trozos para la lectura,
        cierra la base (se puede borrar) y no deja nada junto a ella."""
        folder = self.source(BOUNDARY_V1)
        path = folder / BOUNDARY_V1
        seen: list[float] = []
        request = _gpkg_request(path, chunk_bytes=builtin.ROW_BYTES)
        readers.read_content(GPKG_LAYER, request, progress=seen.append)
        first, second = _read_share(1 / 3), _read_share(2 / 3)
        self.assertEqual(seen, [0.0, first, second, 1.0])
        seen.clear()
        request = _gpkg_request(path, chunk_bytes=builtin.ROW_BYTES)
        with assert_source_untouched(folder), self.closes_its_files():
            with self.assertRaises(readers.ReadCancelled) as caught:
                readers.read_content(
                    GPKG_LAYER, request, progress=seen.append, cancelled=lambda: len(seen) >= 2
                )
        self.assertEqual(seen, [0.0, first])
        self.assertEqual(caught.exception.progress, first)
        os.remove(path)  # en Windows falla si la base sigue abierta

    def test_count_and_finish_by_chunks(self) -> None:
        """RNF-008-11 (T67), RF-008-08 y RF-008-14: una capa se cuenta por trozos de la clave
        entera (``fid``) antes de leerla —nunca un ``count(*)`` de toda la tabla, que en
        ``Z:`` tarda segundos sin avisar ni poder cancelarse— con el progreso de la parte
        del recuento (la posición alcanzada) tras cada trozo y sin leer ninguna fila; luego
        la lectura, fila a fila, y el cierre del hash por trozos, con el suyo. Cancelar
        mientras cuenta o mientras cierra el hash para la lectura y cierra la base. El hash
        es el mismo que leyendo en trozos grandes y el de las entidades escritas a mano."""
        count = 200
        folder = self.tmp / "fuente"
        folder.mkdir()
        path = _parcels(folder / "parcelas.gpkg", count)
        age_folders(folder)
        expected = _features(
            [(wkb_build.iso_le(("Polygon", [_square(index)])), {"codigo": _code(index)})
             for index in range(count)],
            {"codigo": "text"},
        )
        scan = builtin.SCAN_CHUNKS  # una fila por trozo de lectura: SCAN_CHUNKS por recuento
        seen: list[tuple[float, int]] = []
        with mock.patch.object(builtin, "_add", wraps=builtin._add) as added:

            def look(value: float) -> None:
                seen.append((value, added.call_count))

            with assert_source_untouched(folder), self.closes_its_files():
                digest = readers.read_content(
                    GPKG_LAYER, _gpkg_request(path, "parcelas", chunk_bytes=builtin.ROW_BYTES),
                    progress=look,
                )
                whole = readers.read_content(GPKG_LAYER, _gpkg_request(path, "parcelas"))
        self.assertEqual(digest, expected)
        self.assertEqual(whole, expected)
        values = [value for value, _rows in seen]
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[0], values[-1]), (0.0, 1.0))
        counting = [(value, rows) for value, rows in seen[1:]
                    if value <= builtin.COUNT_SHARE]
        self.assertEqual(len(counting), math.ceil(count / scan) - 1)
        self.assertEqual({rows for _value, rows in counting}, {0})  # sin leer ninguna fila
        self.assertEqual(  # la posición alcanzada en el rango de los fid (1 a count)
            [value for value, _rows in counting],
            [builtin.COUNT_SHARE * (scan * (index + 1) / count) for index in range(len(counting))],
        )
        reading = [(value, rows) for value, rows in seen
                   if builtin.COUNT_SHARE < value < 1.0 - builtin.FINISH_SHARE]
        self.assertEqual(reading, [(_read_share(rows / count), rows) for rows in range(1, count)])
        finishing = [(value, rows) for value, rows in seen
                     if 1.0 - builtin.FINISH_SHARE <= value < 1.0]
        self.assertGreaterEqual(len(finishing), 2)
        self.assertEqual({rows for _value, rows in finishing}, {count})
        self.assertLessEqual(len(finishing), count // scan)
        for moment, stop in (
            ("contando", lambda value: 0.0 < value <= builtin.COUNT_SHARE),
            ("cerrando el hash", lambda value: value >= 1.0 - builtin.FINISH_SHARE),
        ):
            seen.clear()
            with self.subTest(moment), assert_source_untouched(folder):
                with self.closes_its_files(), self.assertRaises(readers.ReadCancelled) as caught:
                    readers.read_content(
                        GPKG_LAYER, _gpkg_request(path, "parcelas", chunk_bytes=builtin.ROW_BYTES),
                        progress=lambda value: seen.append((value, 0)),
                        cancelled=lambda: bool(seen) and stop(seen[-1][0]),
                    )
                self.assertTrue(stop(caught.exception.progress))
                self.assertLess(caught.exception.progress, 1.0)
        os.remove(path)  # en Windows falla si la base sigue abierta

    def test_no_whole_table_count(self) -> None:
        """RNF-008-11 (T67): con la conexión ya abierta (``layer_steps``), cada recuento es
        de un trozo (``LIMIT``); sin clave entera (una tabla con ``TEXT PRIMARY KEY``, fuera
        del estándar), se cuenta de una vez y el hash es el mismo."""
        path = _parcels(self.tmp / "parcelas.gpkg", 40)
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        request = _gpkg_request(path, "parcelas", chunk_bytes=builtin.ROW_BYTES)
        self.assertEqual(list(builtin.layer_steps(conn, request))[-1], 1.0)
        counts = [text for text in statements if "count(" in text.lower()]
        self.assertGreater(len(counts), 1)
        self.assertEqual([text for text in counts if "LIMIT" not in text], [])
        keyed = _attributes(self.tmp / "claves.gpkg", "codigo TEXT PRIMARY KEY, ley REAL",
                            [(f"S-{index:02d}", 0.5 * index) for index in range(20)], "claves",
                            key="")
        digest = readers.read_content(
            GPKG_LAYER, _gpkg_request(keyed, "claves", kind="table",
                                      chunk_bytes=builtin.ROW_BYTES)
        )
        self.assertEqual(digest, _rows([["codigo", "text"], ["ley", "float"]],
                                       [[f"S-{index:02d}", 0.5 * index] for index in range(20)]))

    def test_wal_variant_hashes_its_pending_edit(self) -> None:
        """RF-008-08 y RF-008-14 (CE-008-01 con la fuente en WAL): la variante en WAL de T01
        (cabecera en WAL y la edición de v2 confirmada en su ``-wal`` sin volcar) da el hash
        **con** su edición pendiente, el de ``Limites_v2.gpkg``; se lee sobre una copia
        privada en la carpeta temporal, que se borra al acabar y también al cancelar, y junto
        a la fuente no se crea, cambia ni borra nada (ni ``-wal``, ni ``-shm``, ni
        ``-journal``). Una base que QGIS dejó con la cabecera en WAL y sin ``-wal``, igual."""
        folder = self.tmp / "fuente"
        folder.mkdir()
        variant = make_wal_variant(folder)
        age_folders(folder)
        private = self.tmp / "temporal"
        private.mkdir()
        during: list[list[str]] = []

        def look(progress: float) -> None:
            during.append(_private_files(private))

        with mock.patch.object(tempfile, "tempdir", str(private)):
            with assert_source_untouched(folder), self.closes_its_files():
                digest = readers.read_content(
                    GPKG_LAYER, _gpkg_request(variant.path), progress=look
                )
                self.assertEqual(_private_files(private), [])
                read_through = list(during)
                during.clear()
                with self.assertRaises(readers.ReadCancelled):
                    readers.read_content(
                        GPKG_LAYER, _gpkg_request(variant.path), progress=look,
                        cancelled=lambda: bool(during),
                    )
        self.assertEqual(digest, _boundary(PARCELS_V2))
        self.assertEqual(read_through[0], [BOUNDARY_V1])  # la copia privada, fuera de la fuente
        self.assertEqual(during, [[BOUNDARY_V1]])  # cancelada con la copia hecha
        self.assertEqual(list(private.iterdir()), [])
        quiet = self.tmp / "sin_wal"
        quiet.mkdir()
        target = quiet / BOUNDARY_V1
        shutil.copyfile(DATA_DIR / BOUNDARY_V1, target)
        conn = sqlite3.connect(target)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        finally:
            conn.close()  # la última conexión vuelca y borra el -wal; la cabecera sigue en WAL
        header = gpkg.read_header(target)
        self.assertEqual((header.journal, header.has_wal), ("wal", False))
        age_folders(quiet)
        during.clear()
        with mock.patch.object(tempfile, "tempdir", str(private)):
            with assert_source_untouched(quiet):
                digest = readers.read_content(GPKG_LAYER, _gpkg_request(target), progress=look)
        self.assertEqual(digest, _boundary(PARCELS_V1))
        self.assertEqual(during[0], [BOUNDARY_V1])
        self.assertEqual(list(private.iterdir()), [])

    def test_classic_journal_is_read_in_place(self) -> None:
        """RF-008-14: una base en diario clásico se lee en su sitio, en solo lectura: no se
        copia a la carpeta temporal y su carpeta queda como estaba."""
        folder = self.source(BOUNDARY_V1)
        private = self.tmp / "temporal"
        private.mkdir()
        during: list[list[str]] = []
        with mock.patch.object(tempfile, "tempdir", str(private)):
            with assert_source_untouched(folder):
                readers.read_content(
                    GPKG_LAYER, _gpkg_request(folder / BOUNDARY_V1),
                    progress=lambda value: during.append(_private_files(private)),
                )
        self.assertEqual(during[0], [])
        self.assertEqual(list(private.iterdir()), [])

    def test_values_are_interpreted(self) -> None:
        """RF-008-08 (ADR-0024 §4, fila «Tabla»): los valores se hashean ya interpretados:
        «1,5» (un texto en una columna REAL, que SQLite no convierte) y «1.50» (que SQLite
        guarda como 1,5) dan el mismo hash, igual que «7,0» y 7 en una INTEGER; 1,51 da otro.
        Un texto que no es un número en una columna REAL se rechaza con la columna y el
        ``fid``."""
        columns = "codigo TEXT, ley REAL, n INTEGER"
        a = _attributes(self.tmp / "a.gpkg", columns, [("S-01", "1,5", "7,0"), ("S-02", 2.25, 3)])
        b = _attributes(self.tmp / "b.gpkg", columns, [("S-01", "1.50", 7), ("S-02", "2,25", "3")])
        c = _attributes(self.tmp / "c.gpkg", columns, [("S-01", 1.51, 7), ("S-02", 2.25, 3)])
        stored = {}
        for path in (a, b):
            conn = sqlite3.connect(path)
            try:
                stored[path.name] = conn.execute(
                    "SELECT typeof(ley), typeof(n) FROM ensayos WHERE codigo = 'S-01'"
                ).fetchone()
            finally:
                conn.close()
        self.assertEqual(stored, {"a.gpkg": ("text", "text"), "b.gpkg": ("real", "integer")})
        digests = [
            readers.read_content(GPKG_LAYER, _gpkg_request(path, "ensayos", kind="table"))
            for path in (a, b, c)
        ]
        expected = _rows(
            [["codigo", "text"], ["ley", "float"], ["n", "int"]],
            [["S-01", 1.5, 7], ["S-02", 2.25, 3]],
        )
        self.assertEqual(digests[0], expected)
        self.assertEqual(digests[1], expected)
        self.assertNotEqual(digests[2].data_sha256, expected.data_sha256)
        bad = _attributes(self.tmp / "d.gpkg", columns, [("S-01", 1.5, 7), ("S-02", "uno", 3)])
        with self.assertRaises(errors.ValidationError) as caught:
            readers.read_content(GPKG_LAYER, _gpkg_request(bad, "ensayos", kind="table"))
        self.assertEqual(caught.exception.code, "core.content_value_invalid")
        self.assertIn("ley", str(caught.exception))
        self.assertIn("fid 2", str(caught.exception))

    def test_rows_by_columns_and_errors_by_fid(self) -> None:
        """RF-008-08, RNF-005-01 (spec 005, T52): una tabla se lee por trozos y cada trozo
        va al ``RowEncoder`` por columnas: el hash de sus 3.000 filas, en trozos de 500, es el
        de ``ContentHasher.rows`` con ellas; un valor que no vale en un trozo (un 2,5 en una
        columna INTEGER, que SQLite guarda como real) se rechaza fila a fila con su
        columna y su ``fid``, como antes."""
        columns = "codigo TEXT, ley REAL, n INTEGER, ok BOOLEAN"
        rows = [(f"S-{k:04d}", None if k % 7 == 0 else k / 8, k % 11, k % 2 == 0)
                for k in range(3000)]
        path = _attributes(self.tmp / "muchas.gpkg", columns, rows)
        request = _gpkg_request(path, "ensayos", kind="table", chunk_bytes=500 * 256)
        expected = _rows([["codigo", "text"], ["ley", "float"], ["n", "int"], ["ok", "bool"]],
                         [list(row) for row in rows])
        self.assertEqual(readers.read_content(GPKG_LAYER, request), expected)
        rows[1233] = ("S-1233", 1.0, 2.5, True)
        bad = _attributes(self.tmp / "mala.gpkg", columns, rows)
        with self.assertRaises(errors.ValidationError) as caught:
            readers.read_content(GPKG_LAYER, _gpkg_request(bad, "ensayos", kind="table",
                                                           chunk_bytes=500 * 256))
        self.assertEqual(caught.exception.code, "core.content_value_invalid")
        self.assertIn("fid 1234", str(caught.exception))
        self.assertIn("«n»", str(caught.exception))

    def test_column_types(self) -> None:
        """RF-008-08: cada tipo de columna del estándar GeoPackage se hashea con su tipo
        (BOOLEAN, enteros, reales, TEXT y BLOB con tamaño, DATE y DATETIME, sin distinguir
        mayúsculas), los nulos como nulos; el ``fid`` no cuenta, pero una clave que no es
        entera (un ``TEXT PRIMARY KEY``) sí es contenido. Un tipo que no es del estándar se
        rechaza."""
        columns = (
            "b BOOLEAN, t TINYINT, s SMALLINT, m MEDIUMINT, i INT, n INTEGER, f FLOAT, "
            "d DOUBLE, r REAL, x TEXT(20), y BLOB(100), dt date, ts DateTime"
        )
        values = (1, 2, 3, 4, 5, 6, 0.5, 0.25, -0.0, "texto", b"\x00\x01", "2026-10-08",
                  "2026-10-08T09:31:00.000Z")
        path = _attributes(self.tmp / "tipos.gpkg", columns, [values, (None,) * 13], "tipos")
        digest = readers.read_content(GPKG_LAYER, _gpkg_request(path, "tipos", kind="table"))
        types = ["bool", "int", "int", "int", "int", "int", "float", "float", "float", "text",
                 "blob", "date", "datetime"]
        names = [column.split()[0] for column in columns.split(", ")]
        expected = _rows(
            [list(pair) for pair in zip(names, types, strict=True)],
            [[True, 2, 3, 4, 5, 6, 0.5, 0.25, 0.0, "texto", b"\x00\x01", "2026-10-08",
              "2026-10-08T09:31:00Z"], [None] * 13],
        )
        self.assertEqual(digest, expected)
        keyed = _attributes(self.tmp / "claves.gpkg", "codigo TEXT PRIMARY KEY, ley REAL",
                            [("S-01", 1.5), ("S-02", 2.0)], "claves", key="")
        digest = readers.read_content(GPKG_LAYER, _gpkg_request(keyed, "claves", kind="table"))
        self.assertEqual(
            digest, _rows([["codigo", "text"], ["ley", "float"]], [["S-01", 1.5], ["S-02", 2.0]])
        )
        odd = _attributes(self.tmp / "raro.gpkg", "nombre VARCHAR(10)", [("uno",)], "raro")
        with self.assertRaises(errors.ValidationError) as caught:
            readers.read_content(GPKG_LAYER, _gpkg_request(odd, "raro", kind="table"))
        self.assertEqual(caught.exception.code, "core.content_layer_invalid")
        self.assertIn("VARCHAR(10)", str(caught.exception))

    def test_dimensions_and_crs(self) -> None:
        """RF-008-08: las dimensiones de la capa salen de ``gpkg_geometry_columns`` (Z
        obligatoria u opcional: «XYZ») y su CRS de ``gpkg_spatial_ref_sys`` (``{"epsg": n}``
        si es de EPSG; si no, ``None``, y otro hash)."""
        path = self.tmp / "puntos.gpkg"
        crs = georef.load_catalog().horizontal(25830)
        point = (700_000.25, 4_400_000.5, 850.125)
        with gpkg.GpkgConnection.open_write(path, create=True) as db, db.transaction() as conn:
            base.create_base(conn, crs)
            base.create_feature_table(
                conn, "puntos", "POINT", 25830, True, [base.ColumnDef("nombre", "TEXT")],
                "Puntos",
            )
            conn.execute(
                "INSERT INTO puntos (geom, nombre) VALUES (?, 'A')",
                (gpkg.encode_geometry("POINT", np.array(point), 25830, True),),
            )
            conn.execute("UPDATE gpkg_geometry_columns SET z = 2 WHERE table_name = 'puntos'")
        feature = (wkb_build.iso_le(("Point", list(point)), "XYZ"), {"nombre": "A"})
        digest = readers.read_content(GPKG_LAYER, _gpkg_request(path, "puntos"))
        self.assertEqual(digest, _features([feature], {"nombre": "text"}, "XYZ"))
        with gpkg.GpkgConnection.open_write(path) as db, db.transaction() as conn:
            conn.execute(
                "UPDATE gpkg_spatial_ref_sys SET organization = 'IMGA' WHERE srs_id = 25830"
            )
        digest = readers.read_content(GPKG_LAYER, _gpkg_request(path, "puntos"))
        self.assertEqual(digest, _features([feature], {"nombre": "text"}, "XYZ", None))

    def test_bad_requests_are_rejected(self) -> None:
        """RF-008-08 y RF-008-14: sin capa, con un ajuste desconocido o con otro fichero
        además del principal es un error de quien llama; una capa que no está en
        ``gpkg_contents`` con ese nombre, una de otro tipo (tabla frente a capa), un
        selector de entradas vigentes fuera del proyecto o una base que no es un GeoPackage
        se rechazan con su código, y la carpeta queda como estaba."""
        folder = self.source(BOUNDARY_V1)
        path = folder / BOUNDARY_V1
        plain = self.tmp / "plana.gpkg"
        conn = sqlite3.connect(plain)
        try:
            conn.execute("CREATE TABLE limites (fid INTEGER PRIMARY KEY, codigo TEXT)")
        finally:
            conn.close()
        text = self.tmp / "texto.gpkg"
        text.write_bytes(b"no soy una base de datos" * 10)
        settings_cases = (
            ({}, ValueError),
            ({"layer": ""}, ValueError),
            ({"layer": 3}, TypeError),
            ({"layer": LAYER, "capa": LAYER}, ValueError),
            ({"layer": LAYER, "selector": "codigo"}, TypeError),
        )
        with assert_source_untouched(folder), self.closes_its_files():
            for settings, error in settings_cases:
                request = GPKG_LAYER.request("vector", DECLARATIONS, {"main": path}, settings)
                with self.subTest(settings=settings), self.assertRaises(error):
                    readers.read_content(GPKG_LAYER, request)
            request = GPKG_LAYER.request(
                "vector", DECLARATIONS, {"main": path, "wal": path}, {"layer": LAYER}
            )
            with self.assertRaises(ValueError):
                readers.read_content(GPKG_LAYER, request)
            coded = (
                (_gpkg_request(path, "Limites"), "core.content_layer_missing"),
                (_gpkg_request(path, kind="table"), "core.content_layer_kind"),
                (_gpkg_request(path, selector={"column": "codigo", "of": "current_inputs"}),
                 "core.dataset_selector_invalid"),
                (_gpkg_request(plain), "core.content_not_gpkg"),
            )
            for request, code in coded:
                with self.subTest(code=code), self.assertRaises(errors.GeoblenderError) as caught:
                    readers.read_content(GPKG_LAYER, request)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(errors.DatabaseError) as caught:
            readers.read_content(GPKG_LAYER, _gpkg_request(text))
        self.assertEqual(caught.exception.code, "core.gpkg_not_sqlite")


class GpkgProjectTableTest(dataset_tables.DatasetTablesCase):
    """RF-008-08 (plan 008 §5.2.1 y §5.3.4, «Acumular»): ``core.gpkg_layer@1`` sobre las
    tablas de ``project.gpkg``, con selector fijo y de entradas vigentes."""

    def digest(self, selector: dict | None = None, *, conn: sqlite3.Connection | None = None,
               table: str = dataset_tables.SHARED, kind: str = "table",
               chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES):
        request = _gpkg_request(self.path, table, selector, kind=kind, chunk_bytes=chunk_bytes)
        if conn is None:
            return readers.read_content(GPKG_LAYER, request)
        steps = list(builtin.layer_steps(conn, request))
        self.assertEqual(steps[-1], 1.0)
        return request.hasher.digest()

    def register_inputs(self, statuses: dict[str, str]) -> None:
        """Una importación y una entrada por uid con el estado dado."""
        with self.db.transaction() as conn:
            _insert(conn, "gb_operation", operation_row())
            for number, (uid, status) in enumerate(statuses.items()):
                row = input_row(uid=uid, name=f"Ensayos {number}", status=status)
                _insert(conn, "gb_input", row)

    def test_fixed_selector_hashes_only_its_rows(self) -> None:
        """RF-008-08: con el selector fijo de lo importado de una entrada (``{"column":
        "input_uid", "equals": <uid>}``) solo cuentan sus filas: cambiar una fila de otra
        entrada no cambia su hash y cambiar una suya, sí; sin selector cuentan todas."""
        shared = dataset_tables.SHARED_ROWS
        selector = {"column": "input_uid", "equals": dataset_tables.INPUT_A}
        first = self.digest(selector)
        self.assertEqual(first, _rows(SHARED_COLUMNS, [list(row[1:]) for row in shared[:2]]))
        self.assertEqual(self.digest(), _rows(SHARED_COLUMNS, [list(row[1:]) for row in shared]))
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE {dataset_tables.SHARED} SET ley = 9.5 WHERE codigo = 'S-03'")
        self.assertEqual(self.digest(selector), first)
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE {dataset_tables.SHARED} SET ley = 1.26 WHERE codigo = 'S-01'")
        self.assertNotEqual(self.digest(selector), first)

    def test_current_inputs_selector_excludes_superseded(self) -> None:
        """RF-008-08: el selector de un dato acumulado (``{"column": "input_uid", "of":
        "current_inputs"}``) cuenta las filas de las entradas vigentes (también las
        «cambiada · se mantiene la copia») y excluye las de una sustituida o descartada; con
        la conexión que escribe (``layer_steps``) ve lo que su transacción aún no confirmó."""
        shared = dataset_tables.SHARED_ROWS
        self.register_inputs(
            {dataset_tables.INPUT_A: "current", dataset_tables.INPUT_B: "superseded",
             dataset_tables.INPUT_C: "kept"}
        )
        vigentes = [list(row[1:]) for row in shared if row[1] != dataset_tables.INPUT_B]
        before = self.digest(CURRENT_INPUTS)
        self.assertEqual(before, _rows(SHARED_COLUMNS, vigentes))

        class Undo(Exception):
            pass

        new_row = [dataset_tables.INPUT_A, "S-05", 1.0, "a"]
        with self.assertRaises(Undo):
            with self.db.transaction() as conn:
                _insert(conn, dataset_tables.SHARED, dict(zip(
                    ("input_uid", "codigo", "ley", "nota"), new_row, strict=True
                )))
                pending = self.digest(CURRENT_INPUTS, conn=conn)
                raise Undo
        self.assertEqual(pending, _rows(SHARED_COLUMNS, [*vigentes, new_row]))
        self.assertEqual(self.digest(CURRENT_INPUTS), before)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE gb_input SET status = 'discarded' WHERE uid = ?", (dataset_tables.INPUT_C,)
            )
        self.assertEqual(self.digest(CURRENT_INPUTS), _rows(SHARED_COLUMNS, vigentes[:2]))

    def test_selectors_counted_by_chunks(self) -> None:
        """RNF-008-11 (T67) y RF-008-08: con selector, el recuento por trozos de la clave
        (de una fila de lectura, con filas de varias entradas intercaladas) da los mismos
        hashes que en un solo trozo, también con la conexión que escribe."""
        self.register_inputs(
            {dataset_tables.INPUT_A: "current", dataset_tables.INPUT_B: "superseded",
             dataset_tables.INPUT_C: "kept"}
        )
        owners = (dataset_tables.INPUT_A, dataset_tables.INPUT_B, dataset_tables.INPUT_C)
        extra = [(owners[index % 3], f"X-{index:03d}", 0.25 * index, "x") for index in range(45)]
        with self.db.transaction() as conn:
            conn.executemany(
                f"INSERT INTO {dataset_tables.SHARED} (input_uid, codigo, ley, nota) "
                "VALUES (?, ?, ?, ?)", extra,
            )
        everything = [list(row[1:]) for row in dataset_tables.SHARED_ROWS] + [
            list(row) for row in extra
        ]
        fixed = {"column": "input_uid", "equals": dataset_tables.INPUT_A}
        cases = (
            (None, everything),
            (fixed, [row for row in everything if row[0] == dataset_tables.INPUT_A]),
            (CURRENT_INPUTS, [row for row in everything if row[0] != dataset_tables.INPUT_B]),
        )
        for selector, rows in cases:
            with self.subTest(selector=selector):
                expected = _rows(SHARED_COLUMNS, rows)
                self.assertEqual(self.digest(selector), expected)
                self.assertEqual(self.digest(selector, chunk_bytes=builtin.ROW_BYTES), expected)
                with self.db.transaction() as conn:
                    self.assertEqual(
                        self.digest(selector, conn=conn, chunk_bytes=builtin.ROW_BYTES), expected
                    )

    def test_selector_errors(self) -> None:
        """RF-008-08: un selector mal escrito o con una columna que la tabla no tiene se
        rechaza (``core.dataset_selector_invalid``); uno que no es un diccionario, con
        ``TypeError``."""
        bad = (
            {"column": "input_uid"},
            {"column": "input_uid", "equals": True},
            {"column": "input_uid", "equals": 1.5},
            {"column": "", "equals": "x"},
            {"column": "input_uid", "of": "all_inputs"},
            {"column": "input_uid", "equals": "x", "of": "current_inputs"},
            {"column": "otra", "equals": "x"},
        )
        for selector in bad:
            with self.subTest(selector=selector):
                with self.assertRaises(errors.ValidationError) as caught:
                    self.digest(selector)
                self.assertEqual(caught.exception.code, "core.dataset_selector_invalid")
        with self.assertRaises(TypeError):
            self.digest(["input_uid"])  # type: ignore[arg-type]

    def test_null_geometries_and_odd_names(self) -> None:
        """RF-008-08: una capa con geometrías nulas (el byte 0x00 en lugar del WKB) y una
        tabla con espacios, comillas y mayúsculas en el nombre se leen."""
        layer = self.digest(table=dataset_tables.LAYER, kind="vector")
        self.assertEqual(
            layer,
            _features([
                (None, {"codigo": "P-01", "tipo": "concesion"}),
                (None, {"codigo": "P-02", "tipo": "concesion"}),
                (None, {"codigo": "P-03", "tipo": "exclusion"}),
            ]),
        )
        odd = self.digest(table=dataset_tables.ODD)
        self.assertEqual(odd, _rows([["nombre", "text"]], [["uno"]]))


class DocumentReaderTest(_TempCase):
    """RF-008-08 y RF-008-14 (ADR-0024 §4, fila «Documento»): ``core.document@1``."""

    def request(self, path: Path, *, kind: str = "document", chunk_bytes: int = 7):
        return DOCUMENT.request(kind, NOT_APPLICABLE, {"main": path}, chunk_bytes=chunk_bytes)

    def test_hash_is_its_fingerprint(self) -> None:
        """RF-008-08 y RF-008-14: el hash de datos de un documento es la huella de sus bytes
        (``core.hashing.sha256_file``) con cualquier tamaño de trozo, y su progreso crece
        trozo a trozo hasta 1; leerlo no deja nada junto a él. Un fichero vacío da la huella
        de cero bytes."""
        folder = self.tmp / "fuente"
        folder.mkdir()
        path = folder / REPORT
        shutil.copyfile(DATA_DIR / REPORT, path)
        age_folders(folder)
        size = path.stat().st_size
        expected = content.ContentHasher(
            "document", declarations=NOT_APPLICABLE, reader=DOCUMENT.id
        ).document([path.read_bytes()]).digest()
        self.assertEqual(expected.data_sha256, hashing.sha256_file(path))
        with assert_source_untouched(folder), self.closes_its_files():
            for chunk in (7, 64, readers.DEFAULT_CHUNK_BYTES):
                seen: list[float] = []
                digest = readers.read_content(
                    DOCUMENT, self.request(path, chunk_bytes=chunk), progress=seen.append
                )
                with self.subTest(chunk=chunk):
                    self.assertEqual(digest, expected)
                    self.assertEqual(len(seen), math.ceil(size / chunk))
                    self.assertEqual(seen, sorted(seen))
                    self.assertEqual(seen[-1], 1.0)
        empty = self.tmp / "vacio.txt"
        empty.write_bytes(b"")
        seen = []
        digest = readers.read_content(DOCUMENT, self.request(empty, kind="report"),
                                      progress=seen.append)
        self.assertEqual(digest.data_sha256, hashing.sha256_bytes(b""))
        self.assertEqual(seen, [1.0])

    def test_cancel_closes_the_file(self) -> None:
        """RF-008-09: cancelar tras dos trozos para la lectura y deja el fichero cerrado."""
        path = self.tmp / REPORT
        shutil.copyfile(DATA_DIR / REPORT, path)
        seen: list[float] = []
        with self.closes_its_files(), self.assertRaises(readers.ReadCancelled):
            readers.read_content(
                DOCUMENT, self.request(path), progress=seen.append,
                cancelled=lambda: len(seen) >= 2,
            )
        self.assertEqual(len(seen), 2)
        os.remove(path)

    def test_request_is_checked(self) -> None:
        """RF-008-08: un documento no tiene ajustes de lectura y es un solo fichero."""
        path = self.tmp / REPORT
        shutil.copyfile(DATA_DIR / REPORT, path)
        cases = (
            DOCUMENT.request("document", NOT_APPLICABLE, {"main": path}, {"layer": "x"}),
            DOCUMENT.request("document", NOT_APPLICABLE, {"main": path, "prj": path}),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError):
                readers.read_content(DOCUMENT, request)


def _mesh_arrays() -> dict[str, np.ndarray]:
    vertices = np.array(
        [[700_000.25, 4_400_000.5, 850.0], [700_010.25, 4_400_000.5, 851.5],
         [700_000.25, 4_400_010.5, 849.25], [700_010.25, 4_400_010.5, 850.75]],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    return {"vertices": vertices, "faces": faces}


MESH_META = {
    "schema": 1,
    "kind": "surface",
    "crs_epsg": 25830,
    "closed": False,
    "operation_uid": "00000000-0000-4000-8000-0000000000c1",
}


def _write_npz(path: Path, arrays: dict, meta: object, *, compressed: bool = True) -> Path:
    save = np.savez_compressed if compressed else np.savez
    text = meta if isinstance(meta, np.ndarray) else np.array(json.dumps(meta))
    save(path, **arrays, meta=text)
    return path


class NpzMeshReaderTest(_TempCase):
    """RF-008-08 y RF-008-14 (ADR-0024 §4, fila «Malla»): ``core.npz_mesh@1``."""

    def read(self, path: Path, progress=None):
        request = NPZ_MESH.request("mesh", DECLARATIONS, {"main": path})
        return readers.read_content(NPZ_MESH, request, progress=progress)

    def test_operation_uid_does_not_count(self) -> None:
        """RF-008-08 y RF-008-14: una malla ``npz`` con otro ``meta.operation_uid`` (y otro
        volumen, que tampoco es contenido), comprimida o no, da los mismos hashes, los de
        ``ContentHasher.mesh``; un vértice movido o ``meta.closed`` cambiado dan otros.
        Leerla no deja nada junto a ella y el progreso va por arrays."""
        folder = self.tmp / "fuente"
        folder.mkdir()
        arrays = _mesh_arrays()
        a = _write_npz(folder / "a.npz", arrays, MESH_META)
        other = {**MESH_META, "operation_uid": OTHER_OPERATION, "volume_m3": 12.5}
        b = _write_npz(folder / "b.npz", arrays, other, compressed=False)
        age_folders(folder)
        seen: list[float] = []
        with assert_source_untouched(folder), self.closes_its_files():
            first = self.read(a, seen.append)
            second = self.read(b)
        expected = content.ContentHasher(
            "mesh", declarations=DECLARATIONS, reader=NPZ_MESH.id
        ).mesh(arrays, MESH_META).digest()
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(seen, [0.25, 0.5, 0.75, 1.0])
        moved = {**arrays, "vertices": arrays["vertices"].copy()}
        moved["vertices"][3, 2] += 0.001
        changed = self.read(_write_npz(self.tmp / "c.npz", moved, MESH_META))
        self.assertNotEqual(changed.data_sha256, expected.data_sha256)
        closed = self.read(_write_npz(self.tmp / "d.npz", arrays, {**MESH_META, "closed": True}))
        self.assertNotEqual(closed.content_sha256, expected.content_sha256)

    def test_unreadable_files_are_rejected(self) -> None:
        """RF-008-08: un fichero que no es un ``npz``, un ``meta`` que no es un texto JSON
        con un objeto o un array de textos se rechazan con el fichero, que queda cerrado."""
        arrays = _mesh_arrays()
        not_npz = self.tmp / "texto.npz"
        not_npz.write_bytes(b"no soy un npz")
        cases = (
            (not_npz, ValueError, "texto.npz"),
            (_write_npz(self.tmp / "lista.npz", arrays, [1, 2]), ValueError, "meta"),
            (_write_npz(self.tmp / "numero.npz", arrays, np.arange(3)), ValueError, "meta"),
            (_write_npz(self.tmp / "nombres.npz", {**arrays, "face_name": np.array(["a", "b"])},
                        MESH_META), TypeError, "face_name"),
        )
        for path, error, word in cases:
            with self.subTest(path=path.name):
                with self.closes_its_files(), self.assertRaisesRegex(error, word):
                    self.read(path)
                os.remove(path)

    def test_request_is_checked(self) -> None:
        """RF-008-08: una malla no tiene ajustes de lectura y es un solo fichero."""
        path = _write_npz(self.tmp / "a.npz", _mesh_arrays(), MESH_META)
        cases = (
            NPZ_MESH.request("mesh", DECLARATIONS, {"main": path}, {"layer": "x"}),
            NPZ_MESH.request("mesh", DECLARATIONS, {"main": path, "prj": path}),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError):
                readers.read_content(NPZ_MESH, request)


if __name__ == "__main__":
    unittest.main()
