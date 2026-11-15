# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar una plataforma leyendo solo su ventana (spec 015, T37; RNF-015-03, RNF-015-08; RF-015-06 a RF-015-09,
RF-015-16, RF-015-29; plan 015 §5.4 A0 y §8; decisión de la sesión principal, opción (b) del informe de la T33).

«Recalcular lo obsoleto» crea la operación de cada plataforma en **una** llamada del hilo de Blender (el contrato de
``recompute_run``: devuelve el *handle* ya empezado) y esa llamada leía las dos rejillas enteras (la superficie de
partida y las máscaras de clases: 2 × 49 teselas con 2,81 M de celdas) para tocar de ellas una o cuatro. Ahora lee **solo
las teselas de la ventana de la plataforma** (la caja de su geometría ampliada por el ancho y el alcance de A0), y la
rejilla entera de la partida —que solo hace falta para escribir la superficie de salida— se lee **por pasos** dentro del
cálculo. El resultado es el mismo **bit a bit**:

- **La ventana** (:func:`~geoblender.design.platform.reading_window`): contiene siempre la ventana de trabajo de la
  huella (lo que el cálculo toca: huella, alcance y dos celdas), para líneas y polígonos con y sin eje enlazado, con
  las dos métricas y con alcances y anchos al azar; lo que no puede juzgar (una capa de puntos, un alcance que falta o
  sale de rango) lee la rejilla entera, como antes.
- **El trabajo** (``PlatformJob.region``): sus arrays son de la ventana leída; pedir otra parte es un error del
  programa; con una ventana que no basta para decidir (el rango de cotas de RF-015-08 de la rejilla entera, una ventana
  sin dato) cae a leer la rejilla entera, con el mismo resultado y el mismo rechazo.
- **La llamada** de recalcular decodifica solo las teselas de la ventana (de la superficie de partida y de las
  máscaras) y nada más; con la rejilla entera, todas.
- **El resultado es el de leer la rejilla entera** (``reading_window`` forzada a ``None``: lo que se hacía antes de la
  T37): la superficie, la tabla y el informe con el mismo hash, el mismo borde, las mismas cifras y los mismos avisos,
  para una línea, una L, un polígono con eje enlazado y uno sin él, con apoyo, en corte y relleno y con la métrica
  *chamfer*; en «Calcular» y al recalcular; también los rechazos (la cota fuera de rango, la huella sin dato).

Sobre la cantera sintética de la 014 con las capas de plataformas y la rejilla gruesa de 2 m (200 × 200 celdas), con la
superficie de partida y las máscaras en teselas de 16 × 16 (13 × 13 teselas cada una).
"""

from __future__ import annotations

import dataclasses
import math
import random
import unittest
from contextlib import nullcontext
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.unit.design import test_platform_edge as edge_tests
from tests.unit.design import test_platform_footprint as fp
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
entity_store = import_geoblender("design.entity_store")
design_store = import_geoblender("design.store")
gis = import_geoblender("gis")
masks_provenance = import_geoblender("gis.masks.provenance")
messages = import_geoblender("design.messages")
platform = import_geoblender("design.platform")
reader = import_geoblender("gis.geotiff.reader")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("design.surfaces")
writer = import_geoblender("gis.geotiff.writer")

DesignError = messages.DesignError
GRID = prep.GRID
FINE = fp.GRID
"""La rejilla fina de la cantera (400 × 400 celdas de 1 m) de las pruebas sin proyecto."""
TILE = 16
"""El lado de las teselas con que se escriben la superficie de la prueba, las máscaras y lo que se crea."""
T16, HOLE16, SPIKE16, DEAD16 = "gis_dtm_t16", "gis_dtm_t16hueco", "gis_dtm_t16pico", "gis_dtm_t16muerto"
P1_START = "gis_dtm_t16p1"
"""La partida de la primera entidad (``PLT-001``): una superficie propia, porque de cada una parte solo una entidad."""
LOADING, WORKSHOP, TOWER = prep.LOADING, prep.WORKSHOP, prep.TOWER
WITH_AXIS, NO_AXIS = prep.WITH_AXIS, prep.NO_AXIS
HOLE_ROWS, HOLE_COLS = (55, 62), (100, 110)
"""Un hueco sin dato dentro de la huella de la «Plataforma de carga» (filas 55–64, columnas 55–154 de 2 m)."""
DEAD_ROWS, DEAD_COLS = (30, 100), (30, 180)
"""Una zona sin dato que contiene entera la ventana de la «Plataforma de carga» y no la rejilla."""
SPIKE_M = 4000.0
"""Lo que sube un pico de la esquina del noroeste: el rango de cotas de la rejilla entera pasa de lo que ve la ventana."""


def request(name: str = LOADING, **changes: Any) -> Any:
    """La plataforma ``name`` de la capa de ejes sobre la superficie de la prueba en teselas pequeñas (``feature``:
    la geometría de la capa, por defecto la del mismo nombre)."""
    return prep.request(name, **{"start": T16, **changes})


def polygon_request(name: str, *, linked: bool = True, **changes: Any) -> Any:
    return prep.polygon_request(name, linked=linked, **{"start": T16, **changes})


def tiles(window: tuple[slice, slice]) -> int:
    """Las teselas de ``TILE`` × ``TILE`` que toca una ventana de la rejilla."""
    rows, cols = window

    def across(part: slice) -> int:
        return -(-part.stop // TILE) - part.start // TILE

    return across(rows) * across(cols)


def assert_same(test: unittest.TestCase, found: Any, expected: Any, where: str = "resultado") -> None:
    """``found`` y ``expected`` son **iguales bit a bit**: los arrays elemento a elemento (el NaN, igual al NaN),
    los datos de dato por campo, las secuencias y los diccionarios por elemento."""
    if isinstance(expected, np.ndarray):
        test.assertIsInstance(found, np.ndarray, where)
        np.testing.assert_array_equal(found, expected, err_msg=where)
    elif dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        test.assertIs(type(found), type(expected), where)
        for field in dataclasses.fields(expected):
            assert_same(test, getattr(found, field.name), getattr(expected, field.name), f"{where}.{field.name}")
    elif isinstance(expected, tuple | list):
        test.assertEqual(len(found), len(expected), where)
        for index, (one, other) in enumerate(zip(found, expected, strict=True)):
            assert_same(test, one, other, f"{where}[{index}]")
    elif isinstance(expected, dict) or hasattr(expected, "keys"):
        test.assertEqual(list(found), list(expected), where)
        for key in expected:
            assert_same(test, found[key], expected[key], f"{where}[{key!r}]")
    elif isinstance(expected, float) and math.isnan(expected):
        test.assertTrue(isinstance(found, float) and math.isnan(found), where)
    else:
        test.assertEqual(found, expected, where)


# ---------------------------------------------------------------------------------------------
# La ventana de lectura
# ---------------------------------------------------------------------------------------------


def contains(outer: tuple[slice, slice], inner: tuple[slice, slice]) -> bool:
    return all(big.start <= small.start and small.stop <= big.stop for big, small in zip(outer, inner, strict=True))


class ReadingWindowTest(unittest.TestCase):
    """RNF-015-03 (A0): ``reading_window`` contiene la ventana de trabajo de la huella."""

    def window_of(self, job: Any) -> tuple[slice, slice] | None:
        return platform.reading_window(job.geometry, job.values, job.grid)

    def test_a_it_contains_the_work_window_of_the_footprint(self) -> None:
        """RNF-015-03: para los ejes y los polígonos de la cantera (con y sin eje enlazado), la ventana de lectura
        contiene la ventana de trabajo de la huella, y es **menor** que la rejilla entera."""
        jobs = [fp.axis_job(spec.name) for spec in efx.AXES if spec.name in (LOADING, WORKSHOP, TOWER)]
        jobs += [fp.polygon_job(WITH_AXIS), fp.polygon_job(NO_AXIS, linked=False)]
        for job in jobs:
            with self.subTest(name=job.request.name):
                footprint = platform.platform_footprint(job)
                found = self.window_of(job)
                self.assertIsNotNone(found)
                assert found is not None
                self.assertTrue(contains(found, footprint.window), (found, footprint.window))
                self.assertLess(found[0].stop - found[0].start, FINE.nrows)

    def test_a_it_contains_it_for_random_lines_and_polygons(self) -> None:
        """RNF-015-03: con líneas de dos y tres tramos y polígonos al azar (anchos, alcances y las dos métricas), la
        ventana de lectura contiene siempre la ventana de trabajo: la que no contuviera es una lectura de menos."""
        rng = random.Random(15_037)
        checked = 0
        for case in range(120):
            reach = rng.choice((0.0, 3.0, 12.5, 20.0, 41.0, 90.0))
            metric = rng.choice(("exact", "chamfer5"))
            if case % 3:
                points = [(rng.uniform(0, 400), rng.uniform(0, 400))]
                for _ in range(rng.choice((1, 2))):
                    last = points[-1]
                    points.append((min(max(last[0] + rng.uniform(-150, 150), 0), 400),
                                   min(max(last[1] + rng.uniform(-150, 150), 0), 400)))
                geometry = fp.line_path(tuple(points))
                job = fp.make_job(geometry, fp.line_request(), fp.values(
                    width_m=rng.choice((2.0, 6.0, 20.0, 41.0)), reach_m=reach, metric=metric,
                    gradient_pct=rng.choice((0.0, 1.0, -2.0))))
            else:
                x, y = rng.uniform(40, 300), rng.uniform(40, 300)
                width, height = rng.uniform(8, 90), rng.uniform(8, 90)
                ring = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
                geometry = platform.PlatformGeometry("polygon", ((fp.cfx.absolute(ring),),))
                job = fp.make_job(geometry, fp.polygon_request("Al azar", linked=False),
                                  fp.values(reach_m=reach, metric=metric))
            try:
                footprint = platform.platform_footprint(job)
            except DesignError:
                continue  # una línea que se corta o fuera de la rejilla: no tiene huella que contener
            checked += 1
            found = self.window_of(job)
            self.assertIsNotNone(found, case)
            assert found is not None
            self.assertTrue(contains(found, footprint.window), (case, found, footprint.window))
        self.assertGreater(checked, 60)

    def test_a_what_it_cannot_judge_reads_everything(self) -> None:
        """Una capa de puntos, un alcance que falta, negativo o que no es un número, una métrica que no es de la
        lista o una geometría sin vértices: ``None``, la rejilla entera, y los rechazos de siempre."""
        job = fp.axis_job(LOADING)
        for name, changes in (("sin alcance", {"reach_m": None}), ("negativo", {"reach_m": -1.0}),
                              ("texto", {"reach_m": "mucho"}), ("NaN", {"reach_m": math.nan}),
                              ("métrica", {"metric": "manhattan"}), ("sin ancho", {"width_m": None})):
            with self.subTest(name):
                values = dict(job.values)
                values.update(changes)
                if changes.get("reach_m", 0) is None or changes.get("width_m", 0) is None:
                    values.pop(next(iter(changes)))
                self.assertIsNone(platform.reading_window(job.geometry, values, job.grid))
        point = platform.PlatformGeometry("point", ((fp.cfx.absolute([(150.0, 150.0)]),),))
        self.assertIsNone(platform.reading_window(point, job.values, job.grid))
        empty = platform.PlatformGeometry("line", ())
        self.assertIsNone(platform.reading_window(empty, job.values, job.grid))

    def test_a_a_long_reach_is_the_whole_grid(self) -> None:
        """Un alcance mayor que la rejilla recorta a ella: la ventana es la rejilla entera, sin salirse."""
        job = fp.axis_job(LOADING, reach_m=5000.0)
        found = self.window_of(job)
        self.assertEqual(found, (slice(0, FINE.nrows), slice(0, FINE.ncols)))


# ---------------------------------------------------------------------------------------------
# El trabajo con su ventana
# ---------------------------------------------------------------------------------------------


class JobRegionTest(unittest.TestCase):
    """``PlatformJob.region``: los arrays de la ventana leída y qué hace cuando no basta."""

    def regional(self, job: Any, region: tuple[slice, slice] | None = None) -> Any:
        region = region or platform.reading_window(job.geometry, job.values, job.grid)
        assert region is not None
        return platform.PlatformJob(job.request, job.code, job.grid, job.start[region], job.geometry,
                                    job.values, job.cut_allowed[region], job.fill_allowed[region], region=region)

    def test_a_the_arrays_are_the_ones_of_the_region(self) -> None:
        """Con ``region``, la superficie de partida y las máscaras son de la forma de la ventana (``ValueError`` si no);
        ``start_in``, ``cut_in`` y ``fill_in`` dan una parte de ella en coordenadas de la rejilla; sin ``region`` son
        de la rejilla entera, como antes."""
        job = fp.axis_job(LOADING)
        region = platform.reading_window(job.geometry, job.values, job.grid)
        assert region is not None
        found = self.regional(job)
        self.assertEqual(found.window, region)
        self.assertEqual(job.window, (slice(0, FINE.nrows), slice(0, FINE.ncols)))
        shape = (region[0].stop - region[0].start, region[1].stop - region[1].start)
        self.assertEqual(found.start.shape, shape)
        part = (slice(region[0].start + 3, region[0].start + 9), slice(region[1].start + 5, region[1].start + 20))
        np.testing.assert_array_equal(found.start_in(part), job.start[part])
        np.testing.assert_array_equal(found.cut_in(part), job.cut_allowed[part])
        np.testing.assert_array_equal(found.fill_in(part), job.fill_allowed[part])
        np.testing.assert_array_equal(job.start_in(part), job.start[part])
        with self.assertRaises(ValueError):  # los arrays de la rejilla entera con una ventana
            platform.PlatformJob(job.request, job.code, job.grid, job.start, job.geometry, job.values,
                                 job.cut_allowed, job.fill_allowed, region=region)

    def test_a_asking_for_what_was_not_read_is_a_program_error(self) -> None:
        """Una parte que se sale de lo leído, vacía o de otra forma es un error del programa."""
        found = self.regional(fp.axis_job(LOADING))
        rows, cols = found.window
        for part in ((slice(rows.start - 1, rows.stop), cols), (rows, slice(cols.start, cols.stop + 1)),
                     (slice(rows.start, rows.start), cols)):
            with self.subTest(part=part), self.assertRaises(ValueError):
                found.start_in(part)
        for bad in ((slice(-1, 4), slice(0, 4)), (slice(0, 4), slice(0, FINE.ncols + 1)), (slice(5, 5), slice(0, 4))):
            with self.subTest(region=bad), self.assertRaises(ValueError):
                platform.PlatformJob(found.request, found.code, found.grid, np.zeros((4, 4)), found.geometry,
                                     found.values, np.zeros((4, 4), bool), np.zeros((4, 4), bool), region=bad)

    def test_a_the_footprint_of_a_region_job_is_the_one_of_the_whole_job(self) -> None:
        """RNF-015-03: la huella, la rasante y la ventana de trabajo salen iguales con la ventana leída y con la
        rejilla entera, y el cálculo (aplicar y el borde) también, bit a bit."""
        for job in (fp.axis_job(LOADING, edge_angle_deg=35.0), fp.axis_job(WORKSHOP, edge_angle_deg=35.0),
                    fp.polygon_job(WITH_AXIS, edge_angle_deg=35.0),
                    fp.polygon_job(NO_AXIS, linked=False, edge_angle_deg=35.0)):
            with self.subTest(name=job.request.name):
                done = []
                for each in (job, self.regional(job)):
                    footprint = platform.platform_footprint(each)
                    applied = platform.apply_platform(each, footprint)
                    done.append((footprint, applied, platform.platform_edge(each, footprint, applied, edge_tests.PROJECT)))
                assert_same(self, done[1], done[0], "calculado")

    def test_a_a_region_that_cannot_decide_the_level_range_asks_for_everything(self) -> None:
        """RF-015-08: el rango de cotas es el de la superficie **entera** ± 1.000 m. Con la ventana, una cota que
        cabe en el rango de la ventana cabe en el entero (pasa); una que no, o una ventana sin dato, no se pueden
        decidir: ``NeedsWholeSurface``, y la rejilla entera lo decide con su rechazo."""
        job = fp.axis_job(LOADING)
        region = platform.reading_window(job.geometry, job.values, job.grid)
        assert region is not None
        spiked = job.start.copy()
        spiked[:5, :5] += SPIKE_M
        low_part, high_part = float(spiked[region].min()) - 1000.0, float(spiked[region].max()) + 1000.0
        high_whole = float(spiked.max()) + 1000.0
        self.assertLess(high_part, high_whole)
        level = (high_part + high_whole) / 2.0
        base = {"gradient_pct": 0.0}

        def job_of(start: np.ndarray, region_of: Any, **values: Any) -> Any:
            part = region_of or (slice(0, FINE.nrows), slice(0, FINE.ncols))
            allowed = np.ones(FINE.shape, dtype=bool)
            return platform.PlatformJob(job.request, job.code, job.grid, start[part], job.geometry,
                                        {**job.values, **base, **values}, allowed[part], allowed[part].copy(),
                                        region=region_of)

        for name, start_level, expected in (("dentro", (low_part + high_part) / 2.0, "pasa"),
                                            ("en el hueco", level, "pregunta"),
                                            ("fuera de todo", high_whole + 1.0, "pregunta")):
            with self.subTest(name):
                partial = job_of(spiked, region, start_level_m=start_level)
                if expected == "pasa":
                    platform.platform_footprint(partial)
                else:
                    with self.assertRaises(platform.NeedsWholeSurface):
                        platform.platform_footprint(partial)
        whole = job_of(spiked, None, start_level_m=level)
        platform.platform_footprint(whole)  # la rejilla entera sí admite esa cota
        out = job_of(spiked, None, start_level_m=high_whole + 1.0)
        with self.assertRaises(DesignError) as refused:
            platform.platform_footprint(out)
        self.assertEqual(refused.exception.code, "des.platform_level_range")
        self.assertAlmostEqual(refused.exception.values["high"], high_whole)
        self.assertAlmostEqual(refused.exception.values["low"], float(spiked.min()) - 1000.0)
        blank = job_of(np.full(FINE.shape, np.nan), region, start_level_m=level)
        with self.assertRaises(platform.NeedsWholeSurface):
            platform.platform_footprint(blank)


# ---------------------------------------------------------------------------------------------
# Con un proyecto: las superficies, la preparación, la llamada de recalcular y el resultado
# ---------------------------------------------------------------------------------------------


def terrain_with(**changes: Any) -> Any:
    """El terreno de la cantera (rejilla gruesa) con unas celdas cambiadas: ``rows`` y ``cols`` (``(desde, hasta)``)
    sin dato, o ``spike`` (m) sumado a las cinco primeras filas y columnas."""
    values = np.array(qfx.terrain(GRID), dtype=np.float64)
    if "hole" in changes:
        (r0, r1), (c0, c1) = changes["hole"]
        values[r0:r1, c0:c1] = np.nan
    if "spike" in changes:
        values[:5, :5] += changes["spike"]
    return gis.Raster(GRID, values, efx.CRS, efx.VERTICAL)


class WindowCase(ops.RecomputeCase):
    """V01 con las máscaras y la superficie de partida en teselas de 16 × 16 y la «Plataforma de carga» creada."""

    first: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(mock.patch.object(writer, "TILE_SIZE", TILE))
        res_fixtures.write_grids(cls.project, [
            ("t16", terrain_with()), ("t16p1", terrain_with()), ("t16hueco", terrain_with(hole=(HOLE_ROWS, HOLE_COLS))),
            ("t16pico", terrain_with(spike=SPIKE_M)), ("t16muerto", terrain_with(hole=(DEAD_ROWS, DEAD_COLS)))],
            message="Terrenos de la prueba en teselas pequeñas")
        cls.clock.advance(minutes=1)
        ops.finish(access.compile_masks_steps(cls.project, cls.v1.uid))  # las máscaras, ya en teselas pequeñas
        cls.clock.advance(minutes=1)
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.first = cls.made(request(start=P1_START))

    def decoded(self) -> Any:
        """Un contador de los bloques que decodifica el lector de GeoTIFF mientras dura."""
        return mock.patch.object(reader, "decode_block", wraps=reader.decode_block)

    def whole(self) -> Any:
        """Lo que se hacía antes de la T37: sin ventana de lectura, la rejilla entera."""
        return mock.patch.object(entity_store, "reading_window", return_value=None)

    def record_header(self, name: str) -> Any:
        record = self.record(name, self.v1) or self.record(name)
        path = self.root / record.locator
        with path.open("rb") as stream:
            return reader.read_header(stream, path.stat().st_size, path.name)

    def current_request(self) -> Any:
        """Lo que recibe ``bl`` para recalcular la «Plataforma de carga» (``PLT-001``), la de ahora."""
        return self.request_for(self.current("PLT-001"))

    def test_a_the_surfaces_and_the_masks_are_in_small_tiles(self) -> None:
        """La prueba es de verdad de teselas: la partida y la rejilla de clases son de 13 × 13 teselas de 16."""
        classes = masks_provenance.dataset_name(masks_provenance.CLASSES)
        for name in (T16, classes):
            header = self.record_header(name)
            self.assertTrue(header.layout.tiled, name)
            self.assertEqual((header.layout.block_w, len(header.layout.offsets)), (TILE, 13 * 13), name)

    def test_b_reading_a_surface_by_window_or_by_steps_is_reading_it_whole(self) -> None:
        """RNF-015-03, RF-013-16: ``read_surface_window`` da las celdas de la ventana de ``read_surface`` (y solo
        decodifica sus teselas) y ``read_surface_steps`` da, por bandas, la superficie entera; las dos rechazan, antes
        de leer una celda, una rejilla que no es la del proyecto."""
        frame = surfaces.project_frame(self.project)
        whole = surfaces.read_surface(self.project, T16, version_uid=self.v1.uid, expect=frame)
        for window in ((slice(40, 77), slice(40, 170)), (slice(0, 1), slice(0, 1)), (slice(0, 200), slice(0, 200)),
                       (slice(199, 200), slice(150, 200))):
            with self.subTest(window=window), self.decoded() as decoded:
                found = surfaces.read_surface_window(self.project, T16, window, version_uid=self.v1.uid,
                                                     expect=frame)
            self.assertEqual((found.name, found.window), (T16, window))
            np.testing.assert_array_equal(found.values, whole.values[window])
            self.assertEqual(decoded.call_count, tiles(window))
        with mock.patch.object(surfaces, "_READ_ROWS", 32):  # unidades de 32 filas: siete en la rejilla de 200
            done = surfaces.read_surface_steps(self.project, T16, version_uid=self.v1.uid, expect=frame)
            count = 0
            while True:
                try:
                    next(done)
                    count += 1
                except StopIteration as stop:
                    stepped = stop.value
                    break
        self.assertEqual(count, 7)
        self.assertTrue(stepped.grid.same_geometry(whole.grid))
        np.testing.assert_array_equal(stepped.values, whole.values)
        self.assertEqual((stepped.crs, stepped.vertical), (whole.crs, whole.vertical))
        other = surfaces.ProjectFrame(gis.Grid(frame.grid.west + 1.0, frame.grid.north, frame.grid.dx, frame.grid.dy,
                                               frame.grid.ncols, frame.grid.nrows), frame.crs, frame.vertical)
        for call in (lambda: surfaces.read_surface_window(self.project, T16, (slice(0, 4), slice(0, 4)),
                                                          version_uid=self.v1.uid, expect=other),
                     lambda: list(surfaces.read_surface_steps(self.project, T16, version_uid=self.v1.uid,
                                                              expect=other))):
            with self.decoded() as decoded, self.assertRaises(DesignError) as refused:
                call()
            self.assertEqual(refused.exception.code, "des.surface_mismatch")
            self.assertEqual(decoded.call_count, 0)
        for window in ((slice(0, 0), slice(0, 4)), (slice(0, 4), slice(0, 201)), (slice(-1, 4), slice(0, 4))):
            with self.subTest(bad=window), self.assertRaises(ValueError):
                surfaces.read_surface_window(self.project, T16, window, version_uid=self.v1.uid, expect=frame)

    def test_c_preparing_reads_only_the_window(self) -> None:
        """RNF-015-03: la preparación decodifica las teselas de la ventana de la partida (y de las máscaras, si las
        recibe sin cargar: ``MaskSource``), no las de toda la rejilla; con las máscaras cargadas, solo las de la
        partida. El trabajo es de esa ventana y contiene la de la huella."""
        asked = request(WORKSHOP)
        with self.decoded() as decoded:
            prepared = self.units(asked)
        window = prepared.job.window
        self.assertTrue(contains(window, prepared.footprint.window))
        self.assertLess(tiles(window), 13 * 13 // 2)
        self.assertEqual(decoded.call_count, tiles(window))
        source = access.open_masks(self.project, self.v1.uid)
        with self.decoded() as decoded:
            again = self.units(asked, masks=source)
        self.assertEqual(again.job.window, window)
        self.assertEqual(decoded.call_count, 2 * tiles(window))
        assert_same(self, again.footprint, prepared.footprint, "huella")
        np.testing.assert_array_equal(again.job.start, prepared.job.start)
        np.testing.assert_array_equal(again.job.cut_allowed, prepared.job.cut_allowed)
        np.testing.assert_array_equal(again.job.fill_allowed, prepared.job.fill_allowed)
        with self.whole():
            whole = self.units(asked)
        self.assertEqual(whole.job.window, (slice(0, GRID.nrows), slice(0, GRID.ncols)))
        np.testing.assert_array_equal(whole.job.start[window], prepared.job.start)
        np.testing.assert_array_equal(whole.job.cut_allowed[window], prepared.job.cut_allowed)
        np.testing.assert_array_equal(whole.job.fill_allowed[window], prepared.job.fill_allowed)
        for name in ("op_type", "name", "version_uid", "settings", "inputs", "params", "seen"):
            self.assertEqual(getattr(whole.start, name), getattr(prepared.start, name), name)
        self.assertEqual(whole.rows, prepared.rows)

    def test_d_the_recompute_call_reads_only_the_window(self) -> None:
        """RNF-015-03 (el contrato de ``recompute_run``: la llamada empieza la operación): la llamada que crea la
        operación de recalcular decodifica solo las teselas de la ventana, de la superficie de partida y de las
        máscaras, y no carga las máscaras ni la superficie enteras; los pasos leen después la rejilla entera de la
        partida por bandas."""
        masks_total = 13 * 13
        asked = self.current_request()
        prepared = self.units(request(start=P1_START), code="PLT-001", supersedes=self.current("PLT-001"))
        expected = 2 * tiles(prepared.job.window)
        self.assertLess(expected, masks_total)
        with self.decoded() as decoded, \
                mock.patch.object(access, "load_masks_steps", side_effect=AssertionError("máscaras enteras")), \
                mock.patch.object(surfaces, "read_surface", side_effect=AssertionError("superficie entera")):
            handle, work = design_store.recompute_run(asked)
        try:
            self.assertEqual(decoded.call_count, expected)
        finally:
            work.close()
            prep.cancel_if_running(handle)
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.current_request())
        with self.decoded() as decoded:
            stored = ops.finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertGreaterEqual(decoded.call_count, masks_total, "los pasos leen la partida entera, por bandas")

    def test_e_the_result_is_the_one_of_reading_the_whole_grid(self) -> None:
        """RNF-015-03, RF-015-03, RF-015-29: la superficie, la tabla y el informe (con el mismo hash), el borde, las
        cifras y los avisos de «Calcular» son los mismos con la ventana y con la rejilla entera, para una línea, una L,
        un polígono con eje enlazado y uno sin él, con apoyo y en corte y relleno con la métrica *chamfer*."""
        cases = (("línea", request("Eq línea", feature=LOADING)), ("L", request("Eq L", feature=WORKSHOP)),
                 ("torre, corte y relleno, chamfer",
                  request("Eq torre", feature=TOWER, mode="cut_fill", metric="chamfer5")),
                 ("apoyo", request("Eq apoyo", feature=LOADING, support=T16)),
                 ("polígono con eje", polygon_request(WITH_AXIS)),
                 ("polígono sin eje", polygon_request(NO_AXIS, linked=False)))
        for label, asked in cases:
            with self.subTest(label):
                windowed = self.calculate(asked)
                with self.whole():
                    whole = self.calculate(asked)
                self.assertLess(tiles(windowed.entity.job.window), 13 * 13, "no leyó la ventana")
                self.assertEqual(whole.entity.job.window, (slice(0, GRID.nrows), slice(0, GRID.ncols)))
                self.assertEqual([(spec.name, spec.content.content_sha256) for spec in windowed.specs],
                                 [(spec.name, spec.content.content_sha256) for spec in whole.specs])
                self.assertEqual(len(windowed.specs), 3)
                assert_same(self, windowed.outcome, whole.outcome, "outcome")
                assert_same(self, windowed.notices, whole.notices, "avisos")
                assert_same(self, windowed.summary, whole.summary, "resumen")

    def test_f_recomputing_gives_the_same_bits_as_before(self) -> None:
        """RNF-015-03, RF-015-16: recalcular la «Plataforma de carga» da los mismos datos (el mismo hash de la
        superficie, de la tabla y del informe) con la ventana y con la rejilla entera, y los que se crearon."""
        created = self.hashes_of(self.current("PLT-001"))
        self.assertEqual(sorted(created), sorted((ops.PSF, ops.EPR, ops.PRP)))
        for whole in (False, True):
            self.clock.advance(minutes=1)
            with self.whole() if whole else nullcontext():
                handle, work = design_store.recompute_run(self.current_request())
            ops.finish(work)
            self.assertEqual(self.hashes_of(handle.uid), created, "entera" if whole else "ventana")

    def test_g_what_the_window_cannot_decide_reads_everything_with_the_same_result(self) -> None:
        """RF-015-08, RF-015-09, RNF-015-03: cuando la ventana no basta —una cota que solo cabe en el rango de la
        rejilla entera, o una ventana entera sin dato— se lee la rejilla entera, y el resultado, también un rechazo
        (su código, sus valores y su texto), es el de siempre."""
        bad = dict(fields=prep.line_fields(prep.BAD_LAYER))
        impossible = "Eje con cota imposible"
        with self.subTest("la cota cabe en el rango de la rejilla entera"):
            asked = request("Eq cota", feature=impossible, **bad, start=SPIKE16)
            prepared = self.units(asked)
            self.assertEqual(prepared.job.window, (slice(0, GRID.nrows), slice(0, GRID.ncols)), "cayó a la entera")
            with self.whole():
                expected = self.units(asked)
            assert_same(self, prepared.footprint, expected.footprint, "huella")
            np.testing.assert_array_equal(prepared.job.start, expected.job.start)
        with self.subTest("la cota no cabe ni en el rango de la rejilla entera"):
            asked = request("Eq cota", feature=impossible, **bad)
            errors = []
            for mode in ("ventana", "entera"):
                with self.assertRaises(DesignError) as refused:
                    if mode == "ventana":
                        self.units(asked)
                    else:
                        with self.whole():
                            self.units(asked)
                errors.append(refused.exception)
            self.assertEqual(errors[0].code, "des.platform_level_range")
            self.assertEqual((errors[0].code, errors[0].values, errors[0].text),
                             (errors[1].code, errors[1].values, errors[1].text))
        for label, name in (("un hueco en la huella", HOLE16), ("la ventana entera sin dato", DEAD16)):
            with self.subTest(label):
                asked = request("Eq sin dato", feature=LOADING, start=name)
                errors = []
                for mode in ("ventana", "entera"):
                    with self.assertRaises(DesignError) as refused:
                        if mode == "ventana":
                            self.units(asked)
                        else:
                            with self.whole():
                                self.units(asked)
                    errors.append(refused.exception)
                self.assertEqual(errors[0].code, "des.entity_nodata")
                self.assertEqual((errors[0].code, errors[0].values, errors[0].text),
                                 (errors[1].code, errors[1].values, errors[1].text))

    def test_h_a_surface_that_changed_after_preparing_is_not_written(self) -> None:
        """RF-013-17, D-14: la rejilla entera de la partida que se lee al calcular ha de contener, en la ventana, lo
        que se leyó al preparar: si no (otra cosa cambió el dato en medio), ``des.input_changed`` y no se escribe
        nada."""
        real = surfaces.read_surface_steps

        def moved(*args: Any, **kwargs: Any) -> Any:
            found = yield from real(*args, **kwargs)
            values = np.array(found.values, copy=True)
            values[150, 100] += 1.0  # dentro de la ventana de la «Plataforma de taller»
            return gis.Raster(found.grid, values, found.crs, found.vertical)

        before = self.state()
        with mock.patch.object(entity_store, "read_surface_steps", moved), self.assertRaises(DesignError) as refused:
            ops.finish(steps.platform_run(self.project, request(WORKSHOP), masks=self.masks_v1,
                                          version=self.v1.uid))
        self.assertEqual(refused.exception.code, "des.input_changed")
        self.assertEqual(self.state(), before)

    def test_i_what_a_platform_would_rest_on_is_measured_on_the_whole_surface(self) -> None:
        """RF-015-15: ``detected_supports`` (que mide sobre la rejilla entera de la partida y del resultado) da lo
        mismo con el trabajo de la ventana que con el de la rejilla entera."""
        calculation = self.calculate(request(WORKSHOP, start=entities_surface()))
        shown = entity_store.detected_supports(self.project, calculation.entity, calculation.outcome)
        with self.whole():
            other = self.calculate(request(WORKSHOP, start=entities_surface()))
            expected = entity_store.detected_supports(self.project, other.entity, other.outcome)
        assert_same(self, shown, expected, "apoyos")


def entities_surface() -> str:
    """La superficie de la primera entidad (``PLT-001``) como partida."""
    return "entity:PLT-001"


if __name__ == "__main__":
    unittest.main()
