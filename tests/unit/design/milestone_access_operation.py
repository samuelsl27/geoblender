# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación de accesibilidad con lo que cambia el proyecto y la medida de preparar y calcular (spec 017, T17; HU-017-3; RF-017-24, RF-017-25, RF-017-30 y RF-009-21; RNF-017-05 y
RNF-017-06; plan 017 §5.3.2 y §7.3), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas en ``test_access_operation.py``. Crear, recalcular,
reproducir y la lectura para la 012 (la obsolescencia, el hash, la reproducción de un V01.r1 congelado y el tamaño de lo que guarda) son de la T17b, que añade aquí sus clases.

- **Una versión que no se edita** (:class:`ClosedVersionTest`): sin versión activa o con V01 SUPERADA no se prepara.
- **Lo que la versión tiene además de la superficie** (:class:`VersionDataTest`): las rejillas de cotas de berma de la 013 y las dos superficies de una cantera de la 014 (tres datos
  de V01 que escribe una operación de prueba: ``des_brm_cantera``, ``des_exp_cantera`` y ``des_fin_cantera``; y otros tres de una segunda cantera **obsoleta**, que no se leen por defecto).
- **Una plataforma de la 015** (:class:`AccessWithAPlatformTest`) y la medida.

Sobre la cantera de la 015 con la «Plataforma de carga» **creada** en V01 (``PLT-001``: un eje de 200 m y 20 m de ancho sobre celdas de 2 m, **100 columnas por 10 filas = 1.000 celdas**
y 4.000 m², a mano en ``test_platform_prepare``): la accesibilidad de V01 la lee como plataforma de la versión (la huella de su ``des_epr_``, por índice en filas, bit a bit contra un bucle
sobre sus tramos) y la anota como entrada de la operación (cambiarla la dejaría obsoleta); y, en su resumen, sale como plataforma comunicada o no. **Nada se escribe** al preparar ni al
calcular.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import Any
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_access_operation import (
    BERMS_DATASET,
    CODE,
    KEY,
    GRID as GRID_2M,
    PrepareCase,
    drive,
    request as bank_request,
    run,
)
from tests.unit.design.test_platform_operation import GRID, LOADING, START, RecomputeCase

access_store = import_geoblender("design.access_store")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
versions_model = import_geoblender("core.versions.model")

PROBE = "des.probe_access"
"""El tipo de operación de prueba de V01 que escribe las bermas y las dos superficies de una cantera (solo desde esta prueba)."""
QUARRY, OTHER = "Cantera", "Otra"
EXPLOITATION, FINAL = "des_exp_cantera", "des_fin_cantera"
OTHER_BERMS = "des_brm_otra"
"""Una segunda cantera de la versión **obsoleta** (sus datos tienen una causa en la caché de la 008): no entra en lo que se lee por defecto."""


def never(request: Any) -> Any:  # solo declara que se repite sola
    raise AssertionError("las pruebas de preparar y calcular no recalculan ni reproducen")

ENTRIES_LAYER = "gis_fea_entradas_de_la_cantera"
ENTRY = (50.0, 50.0)
"""La entrada (local): dentro del terreno de la cantera, con dato."""
BUDGET_S = 5.0
"""RNF-017-05: la accesibilidad entera, ≤ 5 s (con la rejilla de 2,81 M celdas; aquí, la de 200 × 200)."""
STEP_S = 0.2


def platform_request(name: str = "Accesibilidad de la cantera") -> Any:
    """Una accesibilidad de la capa de entradas sobre el terreno de la cantera, con los umbrales de la referencia de IMGA (solo de las pruebas)."""
    return road_model.AccessRequest(name, road_model.LayerFields(ENTRIES_LAYER, "nombre"), START, walk_slope_pct=rd.ACCESS.walk_slope_pct,
                                    walk_width_m=rd.ACCESS.walk_width_m, min_berm_area_m2=rd.ACCESS.min_berm_area_m2)


class AccessWithAPlatformTest(RecomputeCase):
    """RF-017-25, RF-017-24, RF-015-03: la plataforma ``PLT-001`` de V01 es una **entrada** y una plataforma del resumen; preparar y calcular no escriben y caben en el plazo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        # «Plataforma de taller» (PLT-002) está en la versión **sin calcular** (solo sus parámetros): no tiene huella ni se lee
        workshop = prep.drive(entity_store.prepare_platform_units(cls.project, prep.request(prep.WORKSHOP, start="entity:PLT-001"), cls.v1, cls.masks_v1))
        entity_store.set_entity_params(cls.project, workshop.rows, version=cls.v1.uid, decided_by="Samuel (IMGA)")
        x, y = rd.absolute([ENTRY], GRID)[0]
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(ENTRIES_LAYER, "point", (((np.array([[float(x), float(y)]]),),),), ("Entrada",), {}))
        cls.clock.advance(minutes=1)

    def test_the_platform_is_read_as_a_platform_of_the_version_and_as_an_input(self) -> None:
        """RF-017-25, RF-017-24: ``PLT-001`` es la única plataforma **calculada** de V01 (``PLT-002`` está sin calcular: sin huella no se lee): sus celdas son las de su huella (sus
        tramos de fila, un bucle a mano), **1.000** (100 × 10 de 2 m), y su ``des_epr_`` es una entrada de la operación con el papel ``entity``; nada se escribe."""
        before = self.state()
        prepared = access_store.prepare_access(self.project, platform_request(), version=self.v1.uid, masks=self.masks_v1)
        self.assertEqual(self.state(), before)
        self.assertEqual(prepared.platforms, ("PLT-001",))
        (platform,) = prepared.job.platforms
        self.assertEqual((platform.code, platform.name, platform.cells.size), ("PLT-001", LOADING, 1000))
        table = provenance.dataset_locator(provenance.ENTITY_TABLE, LOADING, self.v1.code)
        with self.project.read() as conn:
            footprint = entity_store.read_entity_footprint(conn, table)
        by_hand = sorted(row * GRID.ncols + column for row, first, last in footprint.runs for column in range(first, last))
        self.assertEqual(platform.cells.tolist(), by_hand)
        dataset = provenance.dataset_name(provenance.ENTITY_TABLE, LOADING)
        self.assertIn((dataset, "entity"), [(use.item, str(use.role)) for use in prepared.start.inputs])
        self.assertEqual(prepared.start.params, provenance.access_params("ACC-001"))

    def test_calculating_with_the_platform_writes_nothing_and_is_fast(self) -> None:
        """RF-017-25, RF-015-03, RNF-017-05, RNF-017-06: «Calcular» da la plataforma en el resumen (comunicada o no: según el terreno), no escribe nada, y preparar y calcular juntos
        caben en el plazo de la medida (cada llamada ≤ 0,2 s; la accesibilidad, ≤ 5 s con una rejilla de 200 × 200)."""
        before = self.state()
        started = time.perf_counter()
        last = started
        longest = 0.0
        calculation = None
        for step in steps.access_run(self.project, platform_request(), version=self.v1.uid, masks=self.masks_v1):
            now = time.perf_counter()
            longest = max(longest, now - last)
            last = now
            calculation = step.result if step.result is not None else calculation
        total = time.perf_counter() - started
        try:
            self.assertEqual(self.state(), before)
            self.assertIsNotNone(calculation)
            summary = calculation.summary
            self.assertEqual([item.code for item in summary.platforms], ["PLT-001"])
            self.assertEqual(summary.notices[0].values["platforms"], 1)
            self.assertLessEqual(longest, STEP_S, f"un paso tardó {longest:.3f} s")
            self.assertLessEqual(total, BUDGET_S, f"preparar y calcular tardó {total:.3f} s")
            self.assertEqual(qfx.COARSE_STEP_M, 2.0)
        finally:
            if calculation is not None:
                calculation.discard()


class ClosedVersionTest(PrepareCase):
    """RF-009-21: una accesibilidad de una versión no se prepara si la versión no se edita (su propia copia del proyecto: la prueba cierra V01)."""

    def test_a_version_that_is_not_editable(self) -> None:
        """RF-009-21: sin versión activa (``core.version_required``) o con V01 SUPERADA (``core.version_not_editable``) no se prepara, ni por la preparación entera ni por la
        orden «Calcular» (``steps.access_run``), sin escribir nada."""
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(bank_request(), version=None)
        self.assertEqual(caught.exception.code, "core.version_required")
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v1.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", ("Prueba de la 017", self.v1.uid))
        closed = self.state()
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(bank_request())
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        with self.assertRaises(versions_model.VersionError) as caught:
            run(steps.access_run(self.project, bank_request(), version=self.v1.uid, masks=self.masks_v1))
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(self.state(), closed)


class VersionDataTest(PrepareCase):
    """RF-017-24, RF-017-25: lo que la versión tiene además de la superficie: las bermas de la 013 y las dos superficies de una cantera de la 014 (aquí, tres datos de V01 que
    escribe una operación de prueba: ``des_brm_cantera``, ``des_exp_cantera`` y ``des_fin_cantera``)."""

    @classmethod
    def write_quarry(cls, name: str, *, shift: float = 0.0) -> None:
        """Escribe en V01 las bermas y las dos superficies de una cantera de nombre ``name`` (``des_brm_``, ``des_exp_`` y ``des_fin_``: la final, 20 m más arriba) con una
        operación de prueba; ``shift`` sube las dos superficies."""
        begun = store._start(cls.project, PROBE, name, cls.v1, None, {"name": name}, (), (), None)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, PROBE, name, version=cls.v1.uid) as writer:
            exploitation = rd.bank_surface(GRID_2M) + shift
            drive(writer.grid_steps(provenance.BERMS_GRID, gis.Raster(GRID_2M, rd.bank_berms(GRID_2M), rd.CRS, rd.VERTICAL)))
            drive(writer.grid_steps(provenance.EXPLOITATION_GRID, gis.Raster(GRID_2M, exploitation, rd.CRS, rd.VERTICAL)))
            drive(writer.grid_steps(provenance.FINAL_GRID, gis.Raster(GRID_2M, exploitation + 20.0, rd.CRS, rd.VERTICAL)))
            writer.commit(begun, message="Bermas y superficies de la prueba de preparar la accesibilidad")
        cls.clock.advance(minutes=1)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        probe = provenance.OperationType(PROBE, "Surfaces of a version of the tests",
                                         (provenance.BERMS_GRID, provenance.EXPLOITATION_GRID, provenance.FINAL_GRID), ())
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType({**provenance.OPERATION_TYPES_BY_NAME, PROBE: probe})))
        cls.enterClassContext(registered(probe.definition(never)))
        cls.write_quarry(QUARRY)
        cls.write_quarry(OTHER, shift=1.0)
        with cls.project.read() as conn:
            uid = conn.execute("SELECT uid FROM gb_dataset WHERE name = ?", (OTHER_BERMS,)).fetchone()[0]
        with cls.project.write_transaction() as conn:  # los datos de «Otra» están obsoletos: ni los toca la 008 aquí ni se usan por defecto
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) VALUES ('dataset', ?, 'dataset_changed', ?, '2026-11-21T00:00:00Z')", (uid, uid))

    def test_the_final_surface_of_the_quarry_and_every_berm_of_the_version(self) -> None:
        """RF-017-24, RF-017-25: sobre la superficie de **explotación** de una cantera, su final (``des_fin_<cantera>``) es la segunda superficie del trabajo (bit a bit) y, por
        defecto, todas las rejillas de cotas de berma al día de la versión (``BermGrid`` con el nombre de su dato), ambas como **entradas** (la final con su papel y las bermas con el
        suyo); nada se escribe."""
        before = self.state()
        prepared = self.prepare(bank_request(surface=EXPLOITATION))
        self.assertEqual(self.state(), before)
        job = prepared.job
        np.testing.assert_array_equal(job.surface, rd.bank_surface(GRID_2M))
        np.testing.assert_array_equal(job.final, rd.bank_surface(GRID_2M) + 20.0)
        self.assertEqual([berm.name for berm in job.berms], [BERMS_DATASET])
        np.testing.assert_array_equal(job.berms[0].levels, rd.bank_berms(GRID_2M))
        self.assertEqual((prepared.final, prepared.berms), (FINAL, (BERMS_DATASET,)))  # las bermas de «Otra» están obsoletas: no entran por defecto
        self.assertEqual([(use.item, str(use.role)) for use in prepared.start.inputs[:4]],
                         [(EXPLOITATION, "surface"), (FINAL, "surface_final"), (rd.ENTRIES_LAYER, "access_entries"), *((use.item, str(use.role)) for use in self.masks_v1.uses())][:4])
        self.assertIn((BERMS_DATASET, "berms"), [(use.item, str(use.role)) for use in prepared.start.inputs])
        self.assertEqual(prepared.start.params, provenance.access_params(CODE))

    def test_a_surface_that_is_not_the_exploitation_has_no_final(self) -> None:
        """RF-017-24: la superficie del proyecto (o la final misma) no tiene otra superficie con que compararse: sin cantera de dos superficies, ninguna final."""
        self.assertIsNone(self.prepare(bank_request()).job.final)
        self.assertIsNone(self.prepare(bank_request(surface=FINAL)).job.final)

    def test_the_berms_can_be_chosen(self) -> None:
        """RF-017-25: los datos de bermas que pide la persona son parámetro de la entidad (``berms``: sus nombres separados por comas) y se leen como parámetros de la operación;
        uno que no es un dato de cotas de berma de la versión se rechaza nombrándolo (``des.access_berm_unknown``) sin escribir nada."""
        prepared = self.prepare(bank_request(berms=(BERMS_DATASET,)))
        self.assertEqual(dict(prepared.values)["berms"], BERMS_DATASET)
        self.assertIn(f"{KEY}berms", [row.key for row in prepared.rows])
        self.assertEqual(prepared.start.params, provenance.access_params(CODE, berms=True))
        stale = self.prepare(bank_request(berms=(OTHER_BERMS,)))  # lo que pide la persona se lee aunque esté obsoleto: lo dice la procedencia (RF-008-24)
        self.assertEqual(stale.berms, (OTHER_BERMS,))
        np.testing.assert_array_equal(stale.job.berms[0].levels, rd.bank_berms(GRID_2M))
        both = self.prepare(bank_request(berms=(BERMS_DATASET, OTHER_BERMS)))
        self.assertEqual((both.berms, dict(both.values)["berms"]), ((BERMS_DATASET, OTHER_BERMS), f"{BERMS_DATASET}, {OTHER_BERMS}"))
        error = self.refused(bank_request(berms=("des_brm_no_existe",)), "des.access_berm_unknown")
        self.names(error, entity="Accesibilidad", field=f"{KEY}berms", value="des_brm_no_existe")
        error = self.refused(bank_request(berms=(EXPLOITATION,)), "des.access_berm_unknown")
        self.names(error, value=EXPLOITATION)
