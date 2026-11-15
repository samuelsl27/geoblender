# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_platform_window» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_platform_window`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import res_fixtures
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_platform_window import (
    DEAD16,
    DEAD_COLS,
    DEAD_ROWS,
    DesignError,
    GRID,
    HOLE16,
    HOLE_COLS,
    HOLE_ROWS,
    LOADING,
    NO_AXIS,
    P1_START,
    SPIKE16,
    SPIKE_M,
    T16,
    TILE,
    TOWER,
    WITH_AXIS,
    WORKSHOP,
    access,
    assert_same,
    contains,
    design_store,
    entities_surface,
    entity_store,
    gis,
    masks_provenance,
    polygon_request,
    reader,
    request,
    steps,
    surfaces,
    terrain_with,
    tiles,
    writer,
)


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
