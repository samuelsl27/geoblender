# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación de accesibilidad con lo que cambia el proyecto y la medida de preparar y calcular (spec 017, T17 y T17b; HU-017-3; RF-017-24, RF-017-25, RF-017-30 y RF-009-21;
RF-015-02, RF-015-03 y RF-015-16; RNF-017-05, RNF-017-06 y RNF-017-10; plan 017 §5.3.2 y §7.3), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las
suyas en ``test_access_operation.py``. La T17b añade lo que cambia el proyecto al **crear, recalcular y reproducir** y la lectura para la 012:

- **Crear** (:class:`AccessCreateTest`): en una transacción (la base sube una vez), con los cinco datos, las cifras con su ámbito, los parámetros de la entidad, las entradas con su papel,
  las capas de entrada sin cambio y el tamaño de lo que guarda; y **la lectura para la 012** (``accessibilities_on``): solo la accesibilidad al día hecha sobre esa superficie, con su tabla de zonas.
- **Obsoleta y recalcular en orden** (:class:`AccessStaleTest`): cambiar una entrada, la superficie y una berma o un parámetro la deja obsoleta con su causa y «Recalcular lo obsoleto» la repite
  con lo nuevo.
- **Reproducir** (:class:`AccessReproduceTest`): un V01.r1 congelado da el mismo hash de cada dato y las mismas cifras, sin escribir nada en el proyecto.

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

import dataclasses
import json
import time
from types import MappingProxyType
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
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
builtin = import_geoblender("core.content.builtin")
contract = import_geoblender("core.provenance.contract")
core_params = import_geoblender("core.params")
datasets = import_geoblender("core.datasets.model")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities_module = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
gis = import_geoblender("gis")
gis_store = import_geoblender("gis.store")
messages = import_geoblender("design.messages")
operations = import_geoblender("core.provenance.operations")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
road_model = import_geoblender("design.road_model")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
surfaces = import_geoblender("design.surfaces")
versions_model = import_geoblender("core.versions.model")
zones_module = import_geoblender("gis.masks.zones")

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


class QuarryVersionCase(PrepareCase):
    """Lo de ``PrepareCase`` más lo que la versión tiene además de la superficie: las bermas de la 013 y las dos superficies de una cantera de la 014 (tres datos de V01 que escribe
    una operación de prueba: ``des_brm_cantera``, ``des_exp_cantera`` y ``des_fin_cantera``) y los de una segunda cantera **obsoleta**."""

    quarry_uid: ClassVar[str]

    @classmethod
    def write_quarry(cls, name: str, *, shift: float = 0.0, supersedes: str | None = None, berms: Any = None) -> str:
        """Escribe en V01 las bermas y las dos superficies de una cantera de nombre ``name`` (``des_brm_``, ``des_exp_`` y ``des_fin_``: la final, 20 m más arriba) con una
        operación de prueba; ``shift`` sube las dos superficies, ``berms`` pone otras cotas de berma y ``supersedes`` es la operación de prueba anterior de la misma cantera, que la
        nueva sustituye (los mismos nombres, otro contenido). Devuelve su uid."""
        begun = store._start(cls.project, PROBE, name, cls.v1, None, {"name": name}, (), (), supersedes)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, PROBE, name, version=cls.v1.uid, supersedes=supersedes) as writer:
            exploitation = rd.bank_surface(GRID_2M) + shift
            levels = rd.bank_berms(GRID_2M) if berms is None else berms
            drive(writer.grid_steps(provenance.BERMS_GRID, gis.Raster(GRID_2M, levels, rd.CRS, rd.VERTICAL)))
            drive(writer.grid_steps(provenance.EXPLOITATION_GRID, gis.Raster(GRID_2M, exploitation, rd.CRS, rd.VERTICAL)))
            drive(writer.grid_steps(provenance.FINAL_GRID, gis.Raster(GRID_2M, exploitation + 20.0, rd.CRS, rd.VERTICAL)))
            stored = writer.commit(begun, message="Bermas y superficies de la prueba de preparar la accesibilidad")
        cls.clock.advance(minutes=1)
        return str(stored.handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        probe = provenance.OperationType(PROBE, "Surfaces of a version of the tests",
                                         (provenance.BERMS_GRID, provenance.EXPLOITATION_GRID, provenance.FINAL_GRID), ())
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType({**provenance.OPERATION_TYPES_BY_NAME, PROBE: probe})))
        cls.enterClassContext(registered(probe.definition(never)))
        cls.quarry_uid = cls.write_quarry(QUARRY)
        cls.write_quarry(OTHER, shift=1.0)
        with cls.project.read() as conn:
            uid = conn.execute("SELECT uid FROM gb_dataset WHERE name = ?", (OTHER_BERMS,)).fetchone()[0]
        with cls.project.write_transaction() as conn:  # los datos de «Otra» están obsoletos: ni los toca la 008 aquí ni se usan por defecto
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) VALUES ('dataset', ?, 'dataset_changed', ?, '2026-11-21T00:00:00Z')", (uid, uid))


class VersionDataTest(QuarryVersionCase):
    """RF-017-24, RF-017-25: lo que la versión tiene además de la superficie: las bermas de la 013 y las dos superficies de una cantera de la 014 (aquí, tres datos de V01 que
    escribe una operación de prueba: ``des_brm_cantera``, ``des_exp_cantera`` y ``des_fin_cantera``)."""

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

    def test_the_default_surface_is_the_exploitation_of_the_only_quarry_that_is_up_to_date(self) -> None:
        """RF-017-24 (T30): sin cadena de entidades, el diálogo propone la superficie de explotación de la cantera de la versión —para que la final entre en el cálculo (error 23)—; con dos
        canteras al día no elige ninguna por la persona y la de una cantera **obsoleta** (``des_exp_otra``) no cuenta. Solo lee."""
        before = self.state()
        self.assertIsNone(access_store.default_surface(self.project, self.v1), "dos canteras al día: no se elige una")
        self.assertEqual(self.state(), before)
        with self.project.read() as conn:
            uid = conn.execute("SELECT uid FROM gb_dataset WHERE name = 'des_exp_otra'").fetchone()[0]
        with self.project.write_transaction() as conn:
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) VALUES ('dataset', ?, 'dataset_changed', ?, '2026-11-21T00:00:00Z')", (uid, uid))
        self.addCleanup(self._clear_stale, uid)
        self.assertEqual(access_store.default_surface(self.project, self.v1), EXPLOITATION)

    def _clear_stale(self, uid: str) -> None:
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM gb_stale WHERE item_uid = ? AND item_kind = 'dataset'", (uid,))

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


# --- Crear, recalcular y reproducir (T17b) ------------------------------------------------------------------------------------

USER = "Samuel (IMGA)"
ACCESS_NAME, SECOND_NAME = "Accesibilidad", "Segunda"
SURFACE = bank_request().surface
"""La cantera con bancos como superficie del proyecto (``gis_dtm_banco``)."""
ACCESS_FAMILIES = (provenance.ACCESS_GRID, provenance.ACCESS_BERMS_TABLE, provenance.ACCESS_PLATFORMS_TABLE, provenance.ACCESS_ZONES_TABLE, provenance.ENTITY_REPORT_TABLE)
ACCESS_ROLES = (provenance.ROAD_ACCESS_ROLE, provenance.ROAD_ACCESS_BERMS_ROLE, provenance.ROAD_ACCESS_PLATFORMS_ROLE, provenance.ROAD_ACCESS_ZONES_ROLE, provenance.ENTITY_REPORT_ROLE)
"""Lo que escribe la operación, en su orden: lo alcanzable, las bermas, las plataformas, las zonas «requiere acceso» y el informe."""


def finish(work: Any) -> Any:
    """Los pasos de ``work`` hasta el final: lo último que llevó un ``Progress`` en ``result``."""
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.road_access``: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    finish(work)
    return handle


def rewrite_layer(project: Any, clock: Any, name: str, *, move: float) -> None:
    """Cambia la capa de entidades ``name`` como al editarla en QGIS y volver a registrarla (el contenido nuevo del mismo dato): desplaza ``move`` m al este la primera entidad."""
    srs = int(project.record.crs_epsg)
    with project.read() as conn:
        found = gis_store.read_features(conn, name)
    shift = [move, 0.0]
    parts = tuple(tuple(tuple(ring + shift if index == 0 else ring for ring in part) for part in entity) for index, entity in enumerate(found.parts))
    rows = gis_store.feature_rows(type(found)(found.kind, found.fids, parts, found.columns, found.values), srs)
    writer = contract.OperationDef(dfx.LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, dfx.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with project.write_transaction() as conn:
            for row in rows:
                conn.execute(f'UPDATE "{name}" SET geom = ? WHERE fid = ?', (row[1], row[0]))
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                                                                input_uid=None, immutable=False),), message="Capa de entradas editada")


class LifecycleCase(QuarryVersionCase):
    """Lo de ``QuarryVersionCase`` con el tipo ``des.road_access`` registrado con sus funciones **reales** de recalcular y reproducir (las que registra ``bl``), las cifras y los
    parámetros de la entidad, y las ayudas de las historias de crear, recalcular y reproducir."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ACCESS_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(provenance.operation_def(provenance.ROAD_ACCESS, recompute_function, design_reproduce.reproduce_road_access), *provenance.ACCESS_FIGURES))

    @classmethod
    def create(cls, asked: Any, *, masks: Any = None) -> tuple[Any, Any]:
        """«Calcula» y «Crea» ``asked`` en V01 (con sus máscaras por defecto): la ``Calculation`` y lo guardado."""
        calculation = run(steps.access_run(cls.project, asked, version=cls.v1.uid, masks=cls.masks_v1 if masks is None else masks))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def current(self, code: str) -> str:
        """El uid de la operación vigente de la accesibilidad ``code`` de V01 (el registro de las entidades)."""
        entry = entities_module.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def request_for(self, uid: str) -> Any:
        """Lo que recibe ``bl`` para recalcular la operación ``uid``: su tipo, sus ajustes y su versión."""
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, op_type, json.loads(settings), (), (), version=self.v1.uid)

    def outputs(self, uid: str) -> list[tuple[str, str, str, str]]:
        """Lo que escribió la operación ``uid``: ``(nombre, ubicación, papel, hash)`` de cada dato, en su orden."""
        return [tuple(row) for row in self.query(
            "SELECT d.name, d.locator, io.role, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures_of(self, uid: str) -> dict[str, tuple[float, dict[str, str]]]:
        """Las cifras que registró la operación ``uid``: ``clave → (valor, ámbito)``."""
        return {key: (value, json.loads(scope)) for key, scope, value in self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)}

    def table(self, name: str, family: str) -> list[dict[str, Any]]:
        """Las filas de la tabla ``family`` de la accesibilidad ``name`` de V01, por el nombre de cada columna."""
        names = [column.name for column in store.columns_of(provenance.ROAD_ACCESS, family)]
        found = self.query(f'SELECT {", ".join(names)} FROM "{provenance.dataset_locator(family, name, "V01")}" ORDER BY fid')
        return [dict(zip(names, row, strict=True)) for row in found]

    def change(self, key: str, value: Any) -> None:
        """Cambia el parámetro de V01 ``key`` (un minuto después)."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key, value=value, source="prueba de recalcular (T17b)", source_kind="person", decided_by=USER,
                                                            reason="Se cambia un parámetro de la accesibilidad", version=self.v1.uid)

    @classmethod
    def hashes(cls, *names: str) -> dict[str, tuple[str, ...]]:
        """El hash de contenido (y el estado) del dato vigente de cada ``names`` en el registro."""
        with cls.project.read() as conn:
            return {name: tuple(conn.execute("SELECT content_sha256, status FROM gb_dataset WHERE name = ? AND status = 'current'", (name,)).fetchone()) for name in names}


class AccessCreateTest(LifecycleCase):
    """RF-017-24, RF-017-25, RF-015-02, RF-015-04, RF-015-29, RNF-017-10: «Crear» la accesibilidad de V01 —``ACC-001``, sobre la explotación de una cantera con su final y sus bermas, con
    las dos entradas— y ``ACC-002``, sobre la superficie del proyecto con las dos zonas «requiere acceso» (**simuladas** en las máscaras: el proyecto de pruebas no tiene ninguna)."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    first_stored: ClassVar[Any]
    second_stored: ClassVar[Any]
    counters: ClassVar[tuple[int, int]]
    inputs_before: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.inputs_before = cls.hashes(*(EXPLOITATION, FINAL, BERMS_DATASET, SURFACE, rd.ENTRIES_LAYER))
        before = change_counter(cls.root)
        cls.first, cls.first_stored = cls.create(bank_request(ACCESS_NAME, surface=EXPLOITATION))
        cls.counters = (before, change_counter(cls.root))
        zones = {name.lower().replace(" ", "_"): zones_module.Runs.from_mask(rd.bank_zone_mask(name, GRID_2M)) for name in rd.BANK_ZONE_BOXES}
        simulated = dataclasses.replace(cls.masks_v1, zones=MappingProxyType(zones), ctypes=MappingProxyType(dict.fromkeys(zones, "requires_access")))
        cls.second, cls.second_stored = cls.create(bank_request(SECOND_NAME, surface=SURFACE), masks=simulated)

    def uid(self, which: Any) -> str:
        return str(which.handle.uid)

    def test_a_creating_writes_one_done_operation_with_the_five_datasets(self) -> None:
        """RF-017-24, RF-015-02: «Crear» deja **una** operación ``des.road_access`` hecha en V01 con los cinco datos de su tipo —lo alcanzable, las bermas, las plataformas, las zonas
        «requiere acceso» y el informe—, cada uno con su nombre, su ubicación (con el código de la versión) y el papel con que lo leen la 012 y R-44."""
        found = self.outputs(self.uid(self.first_stored))
        slug = "accesibilidad"
        self.assertEqual([row[0] for row in found], [f"des_{family}_{slug}" for family in ACCESS_FAMILIES])
        self.assertEqual([row[2] for row in found], list(ACCESS_ROLES))
        self.assertEqual([row[1] for row in found], [provenance.dataset_locator(family, ACCESS_NAME, "V01") for family in ACCESS_FAMILIES])
        self.assertTrue((self.root / found[0][1]).is_file())
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", self.uid(self.first_stored)), [(provenance.ROAD_ACCESS, "version", "done")])
        self.assertEqual((self.first.op_type, self.first.open), (provenance.ROAD_ACCESS, False))
        self.assertEqual(self.first_stored.handle.op_type, provenance.ROAD_ACCESS)
        self.assertEqual(len(self.first_stored.records), 5)

    def test_b_the_grid_and_the_tables_are_what_was_computed(self) -> None:
        """RF-017-24, RF-017-25: la rejilla guardada es la de lo alcanzable (1 y 0, bit a bit) y cada tabla tiene las filas de lo calculado (las bermas con su cota real y su área, la
        plataforma ninguna —V01 no tiene—, las zonas, el informe con las cifras y cada aviso con su código); las cotas de lo guardado son las de la cantera a mano (115 y 140 m)."""
        outcome = self.first.outcome
        grid = drive(surfaces.read_surface_steps(self.project, provenance.dataset_name(provenance.ACCESS_GRID, ACCESS_NAME), version_uid=self.v1.uid)).values
        np.testing.assert_array_equal(grid, access_store.reachable_grid(outcome))
        self.assertEqual(set(np.unique(grid).tolist()), {0.0, 1.0})
        self.assertEqual((outcome.z_min_m, outcome.z_max_m), (115.0, 140.0))
        self.assertEqual(float(grid.sum()) * GRID_2M.cell_area, outcome.area_m2)
        berms = self.table(ACCESS_NAME, provenance.ACCESS_BERMS_TABLE)
        self.assertEqual(len(berms), 4)
        self.assertEqual([(row["stretch"], row["source"], row["level_m"], row["area_m2"], bool(row["connected"]), row["x"], row["y"]) for row in berms],
                         [(item.number, item.source, item.level_m, item.area_m2, item.connected, item.x, item.y) for item in outcome.berms])
        self.assertEqual({row["level_m"]: bool(row["connected"]) for row in berms}, {135.0: True, 125.0: True, 115.0: True, 105.0: False})
        self.assertEqual(self.table(ACCESS_NAME, provenance.ACCESS_PLATFORMS_TABLE), [])
        self.assertEqual(self.table(ACCESS_NAME, provenance.ACCESS_ZONES_TABLE), [])
        report = self.table(ACCESS_NAME, provenance.ENTITY_REPORT_TABLE)
        self.assertEqual([tuple(row.values()) for row in report], access_store.access_report_rows(outcome))
        self.assertIn("des.access_entry_not_walkable", [json.loads(row["note"])["code"] for row in report if row["quantity"] in ("warning", "note")])

    def test_c_the_figures_are_registered_with_the_scope_of_the_entity(self) -> None:
        """RF-017-24, RF-017-25, RF-015-02: las cifras CALCULADO (las nueve, con la cota sobre la final: la superficie es la explotación de una cantera) quedan registradas con su
        unidad y el ámbito de la entidad (su nombre y su código); son las que calculó «Calcular»."""
        found = self.figures_of(self.uid(self.first_stored))
        self.assertEqual(sorted(found), sorted(figure.key for figure in self.first.figures))
        self.assertEqual(len(found), 9)
        for figure in self.first.figures:
            value, scope = found[figure.key]
            self.assertEqual((value, scope), (figure.value, provenance.entity_figure_scope(ACCESS_NAME, "ACC-001")), figure.key)
        self.assertEqual((found["des.acc_z_min_m"][0], found["des.acc_z_max_m"][0], found["des.acc_berms_reached"][0], found["des.acc_berms_total"][0]), (115.0, 140.0, 3.0, 4.0))
        self.assertIn("des.acc_z_min_final_m", found)

    def test_d_the_parameters_of_the_entity_are_written_with_their_origin(self) -> None:
        """RF-015-01, RF-015-08, D-17: los parámetros de ``ACC-001`` quedan escritos como filas **de la versión** con su origen (el diálogo) y el decisor de quien creó (nombre, superficie,
        capa de entradas y los tres umbrales: ninguno con valor por defecto) y es una entidad al día de tipo ``access`` sin cadena (nadie parte de ella)."""
        rows = self.first.entity.rows
        self.assertEqual([row.key for row in rows], [f"{KEY}{name}" for name in ("name", "surface", "entries_layer", "walk_slope_pct", "walk_width_m", "min_berm_area_m2")])
        parameters = core_params.ParameterStore(self.project)
        for row in rows:
            record = parameters.get(row.key, version=self.v1.uid)
            self.assertIsNotNone(record, row.key)
            self.assertEqual((record.value, record.source, record.decided_by), (row.value, row.source, USER), row.key)
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.access.acc_001.%' AND scope = 'version'"), [(6,)])
        entry = entities_module.registry(self.project, self.v1.uid).get("ACC-001")
        self.assertEqual((entry.record.kind, entry.record.state, entry.record.name, entry.record.start), (entities_module.EntityKind.ACCESS, entities_module.EntityState.CURRENT,
                                                                                                           ACCESS_NAME, None))
        self.assertEqual(str(entry.operation_uid), self.uid(self.first_stored))
        with self.project.read() as conn:
            self.assertEqual(entities_module.chain_tail_surfaces(conn, self.v1.uid), ())  # no deja ninguna superficie de diseño

    def test_e_it_is_one_transaction_and_the_inputs_are_not_modified(self) -> None:
        """RF-015-02, RF-015-29, principio 7: «Crear» es **una** transacción (el contador de cambios de la base sube **una vez**) y la capa de entradas, la superficie, la final y las
        bermas son entradas, no salidas: su hash y su estado en el registro son los de antes de crear las dos accesibilidades."""
        before, after = self.counters
        self.assertEqual(after - before, 1)
        self.assertEqual(self.hashes(*self.inputs_before), self.inputs_before)
        written = {row[0] for uid in (self.uid(self.first_stored), self.uid(self.second_stored)) for row in self.outputs(uid)}
        self.assertFalse(written & set(self.inputs_before))

    def test_f_the_inputs_of_the_operation_are_the_surface_the_final_the_entries_the_masks_and_the_berms(self) -> None:
        """RF-017-24, RF-017-25, RF-008-24, D-18: las entradas que anota la operación son las que la dejarán obsoleta si cambian: la superficie, la final de la cantera, la capa de entradas,
        las máscaras de V01 y las rejillas de cotas de berma (cada una con su papel); la segunda accesibilidad, sin cantera, no lleva final."""
        def inputs(uid: str) -> list[tuple[str, str]]:
            return [(name, role) for name, role in self.query(
                "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
                "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

        first = inputs(self.uid(self.first_stored))
        self.assertEqual(first[:3], [(EXPLOITATION, "surface"), (FINAL, "surface_final"), (rd.ENTRIES_LAYER, "access_entries")])
        self.assertIn((BERMS_DATASET, "berms"), first)
        self.assertTrue(self.masks_v1.uses())
        self.assertLessEqual({str(use.role) for use in self.masks_v1.uses()}, {role for _name, role in first})  # las máscaras, con los papeles que les dio la 012
        second = inputs(self.uid(self.second_stored))
        self.assertEqual(second[:2], [(SURFACE, "surface"), (rd.ENTRIES_LAYER, "access_entries")])
        self.assertNotIn("surface_final", [role for _name, role in second])

    def test_g_what_it_keeps_is_small(self) -> None:
        """RNF-017-10: lo que guarda una accesibilidad —la rejilla de lo alcanzable (un GeoTIFF) y cuatro tablas— ocupa mucho menos que la rejilla entera sin comprimir (≤ 1/4; con la de
        2,81 M celdas, la T34 lo mide entero: ≤ 25 MiB por operación)."""
        whole = GRID_2M.nrows * GRID_2M.ncols * 8
        sizes = {name: (self.root / locator).stat().st_size for name, locator, _role, _hash in self.outputs(self.uid(self.first_stored)) if locator.endswith(".tif")}
        self.assertEqual(len(sizes), 1)
        for name, size in sizes.items():
            self.assertLess(size, whole / 4, name)
        self.assertLess(sum(sizes.values()), 25 * 1024 * 1024)

    def test_h_the_reading_for_the_012_gives_only_the_current_one_made_on_that_surface(self) -> None:
        """RF-017-25, RF-012-22 (DIFF-017), P-9: ``accessibilities_on(version, surface)`` da la accesibilidad **al día hecha sobre esa superficie** con sus datos por su papel (lo
        alcanzable, las bermas, las plataformas, las zonas —por el papel ``access_zones``— y el informe), su tabla de zonas leída y los códigos de zona **comunicados**; sobre otra
        superficie, ninguna; con una versión que no existe, ``core.version_unknown``; con la conexión de lectura de quien llama da lo mismo."""
        (first,) = access_store.accessibilities_on(self.project, self.v1.uid, EXPLOITATION)
        self.assertEqual((first.code, first.name, first.version, first.version_uid, first.operation, first.surface, first.final),
                         ("ACC-001", ACCESS_NAME, "V01", self.v1.uid, self.uid(self.first_stored), EXPLOITATION, FINAL))
        for data, family, role in zip((first.reachable, first.berms, first.platforms, first.zones, first.report), ACCESS_FAMILIES, ACCESS_ROLES, strict=True):
            self.assertEqual((data.name, data.locator, data.role), (provenance.dataset_name(family, ACCESS_NAME), provenance.dataset_locator(family, ACCESS_NAME, "V01"), role), family)
        self.assertEqual(first.zones.role, provenance.ROAD_ACCESS_ZONES_ROLE)
        self.assertEqual((first.zone_rows, first.communicated), ((), frozenset()))
        (second,) = access_store.accessibilities_on(self.project, "V01", SURFACE)  # por su código
        self.assertEqual((second.code, second.name, second.final, second.operation), ("ACC-002", SECOND_NAME, None, self.uid(self.second_stored)))
        by_code = {row.code: row for row in second.zone_rows}
        self.assertEqual(sorted(by_code), ["zona_con_acceso", "zona_sin_acceso"])
        self.assertEqual(second.communicated, frozenset({"zona_con_acceso"}))
        self.assertTrue(by_code["zona_con_acceso"].connected)
        missing = by_code["zona_sin_acceso"]
        self.assertEqual((missing.connected, missing.distance_m, missing.level_difference_m), (False, 18.0, 10.0))
        self.assertEqual((missing.x, missing.y), (699861.0, 4399841.0))
        self.assertEqual(access_store.accessibilities_on(self.project, self.v1.uid, FINAL), ())  # otra superficie
        self.assertEqual(access_store.accessibilities_on(self.project, self.v1.uid, "des_exp_no_existe"), ())
        with self.assertRaises(versions_model.VersionError) as caught:
            access_store.accessibilities_on(self.project, "V99", EXPLOITATION)
        self.assertEqual(caught.exception.code, "core.version_unknown")
        with self.project.read() as conn:
            self.assertEqual(access_store.accessibilities_on(self.project, self.v1.uid, EXPLOITATION, conn=conn), (first,))
        self.assertEqual(access_store.read_access_zones(self.project, second.zones.locator), second.zone_rows)

    def test_i_a_calculation_is_created_once(self) -> None:
        """RF-015-02: lo calculado se crea una sola vez: una ``Calculation`` ya creada se rechaza otra vez (``RuntimeError``) y no está abierta."""
        self.assertFalse(self.first.open)
        with self.assertRaises(RuntimeError):
            self.first.create()
        with self.assertRaises(RuntimeError):
            list(self.first.create_steps())

    def test_j_an_input_that_changed_since_calculating_leaves_nothing(self) -> None:
        """RF-015-02, RF-013-17: lo que consume la operación se comprueba otra vez al crear: si una entrada cambió entre «Calcular» y «Crear» (aquí, la capa de entradas), el resultado ya
        no le corresponde (``des.input_changed``), no queda nada (ni operación, ni dato, ni parámetro, ni temporal) y el cálculo queda descartado."""
        calculation = run(steps.access_run(self.project, bank_request("Cambiada", surface=EXPLOITATION), version=self.v1.uid, masks=self.masks_v1))
        before = self.state()
        rewrite_layer(self.project, self.clock, rd.ENTRIES_LAYER, move=2.0)
        changed = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), changed)
        self.assertEqual({key: before[key] for key in ("parameters", "files")}, {key: changed[key] for key in ("parameters", "files")})


class AccessStaleTest(LifecycleCase):
    """RF-017-24, RF-008-24, RF-015-16, RF-008-26, D-18: la accesibilidad **queda obsoleta** al cambiar una entrada, la superficie, una berma o un parámetro, con su causa, y «Recalcular lo
    obsoleto» la repite **con lo nuevo** y en orden. **En orden** (``test_a`` a ``test_c``): cada una parte de lo que dejó la anterior."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(bank_request(ACCESS_NAME, surface=EXPLOITATION))
        cls.create(bank_request(SECOND_NAME, surface=SURFACE))

    def recompute(self) -> list[str]:
        """«Recalcular lo obsoleto» de V01: lo que repite, por unidades, en su orden (los uid de las operaciones nuevas)."""
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * len(outcome.results))
        return [str(uid) for result in outcome.results for uid in result.operations]

    def test_a_a_changed_entry_makes_both_stale_and_recomputing_repeats_them_in_order(self) -> None:
        """RF-017-24, RF-008-24, RF-008-26: mover un punto de la capa de entradas deja obsoletas las dos accesibilidades (con la causa: el dato de la capa) y recalcular las repite en
        orden (``ACC-001`` y ``ACC-002``) como operaciones nuevas que sustituyen a las anteriores, con la capa nueva por entrada, sin escribir otra vez los parámetros de la entidad y sin
        dejar nada obsoleto."""
        old = {code: self.current(code) for code in ("ACC-001", "ACC-002")}
        parameters = self.query("SELECT key, value, rev FROM gb_parameter WHERE key LIKE 'des.access.%' ORDER BY key, scope")
        entries_before = {uid: dict(self.query("SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? "
                                               "AND io.direction = 'in'", uid)) for uid in old.values()}
        rewrite_layer(self.project, self.clock, rd.ENTRIES_LAYER, move=2.0)
        for uid in old.values():
            self.assertEqual({name for _kind, name in self.stale_causes(uid)}, {rd.ENTRIES_LAYER})
        for surface in (EXPLOITATION, SURFACE):  # lo obsoleto no se da a la 012: es de otra cosa que lo que hay ahora
            self.assertEqual(access_store.accessibilities_on(self.project, self.v1.uid, surface), (), surface)
        self.assertEqual(self.recompute_plan(), [(provenance.ROAD_ACCESS,), (provenance.ROAD_ACCESS,)])
        self.clock.advance(minutes=1)
        made = self.recompute()
        self.assertEqual(len(made), 2)
        self.assertEqual([self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", uid) for uid in made],
                         [[(old["ACC-001"], "done")], [(old["ACC-002"], "done")]])
        self.assertEqual({code: self.current(code) for code in old}, dict(zip(old, made, strict=True)))
        for uid, was in zip(made, old.values(), strict=True):
            now = dict(self.query("SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid))
            self.assertNotEqual(now[rd.ENTRIES_LAYER], entries_before[was][rd.ENTRIES_LAYER], "se recalculó con la capa nueva")
            self.assertEqual(self.stale_causes(uid), set())
            self.assertEqual([row[0] for row in self.outputs(uid)], [provenance.dataset_name(family, self.name_of(uid)) for family in ACCESS_FAMILIES])
        self.assertEqual(self.query("SELECT key, value, rev FROM gb_parameter WHERE key LIKE 'des.access.%' ORDER BY key, scope"), parameters)
        self.assertEqual(self.recompute_plan(), [])
        for surface, uid in ((EXPLOITATION, made[0]), (SURFACE, made[1])):  # al día otra vez: la lectura da la operación nueva
            (current,) = access_store.accessibilities_on(self.project, self.v1.uid, surface)
            self.assertEqual(current.operation, uid)

    def name_of(self, uid: str) -> str:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return str(json.loads(settings)["name"])

    def test_b_a_changed_surface_or_berm_makes_it_stale_and_the_new_values_are_read(self) -> None:
        """RF-017-24, RF-017-25, RF-008-24: sustituir los datos de la cantera (la explotación, la final y las bermas, 1 m más arriba y **sin la berma de 135 m**) deja obsoleta la
        accesibilidad de la explotación con la causa de cada dato y la del proyecto solo con la de las bermas (su superficie es del proyecto); recalcular las repite: la cota mínima
        sube 1 m (116 y 141 m) y ya no hay la berma de 135 m (tres tramos, dos comunicados)."""
        old = {code: self.current(code) for code in ("ACC-001", "ACC-002")}
        levels = rd.bank_berms(GRID_2M).copy()
        levels[levels == 135.0] = np.nan
        type(self).quarry_uid = self.write_quarry(QUARRY, shift=1.0, supersedes=self.quarry_uid, berms=levels)
        self.assertEqual({name for _kind, name in self.stale_causes(old["ACC-001"])}, {EXPLOITATION, FINAL, BERMS_DATASET})
        self.assertEqual({name for _kind, name in self.stale_causes(old["ACC-002"])}, {BERMS_DATASET})
        self.clock.advance(minutes=1)
        made = self.recompute()
        self.assertEqual(len(made), 2)
        first, second = (self.figures_of(uid) for uid in made)
        self.assertEqual((first["des.acc_z_min_m"][0], first["des.acc_z_max_m"][0]), (116.0, 141.0))
        self.assertEqual((second["des.acc_z_min_m"][0], second["des.acc_z_max_m"][0]), (115.0, 140.0))  # su superficie no cambió
        for found in (first, second):
            self.assertEqual((found["des.acc_berms_total"][0], found["des.acc_berms_reached"][0]), (3.0, 2.0))
        for code, uid in zip(("ACC-001", "ACC-002"), made, strict=True):
            self.assertEqual(self.current(code), uid)
            self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_c_a_changed_parameter_is_applied_when_recomputing(self) -> None:
        """RF-015-02, RF-015-16, RF-008-26: cambiar un umbral de la entidad (la pendiente transitable de ``ACC-001``) deja obsoleta **solo esa** accesibilidad con la causa de su parámetro y
        recalcular la repite con el valor vigente de la entidad (una pendiente de 3 % alcanza menos área que una de 16 %)."""
        before = self.current("ACC-001")
        area_before = self.figures_of(before)["des.acc_area_m2"][0]
        other = self.current("ACC-002")
        self.change(f"{KEY}walk_slope_pct", 3.0)
        self.assertEqual(self.stale_causes(before), {("parameter_changed", f"{KEY}walk_slope_pct")})
        self.assertEqual(self.stale_causes(other), set())
        self.clock.advance(minutes=1)
        (made,) = self.recompute()
        self.assertEqual((self.current("ACC-001"), self.current("ACC-002")), (made, other))
        self.assertLess(self.figures_of(made)["des.acc_area_m2"][0], area_before)
        self.assertEqual(self.stale_causes(made), set())


    def test_d_a_parameter_that_changed_between_preparing_and_starting_is_refused(self) -> None:
        """RF-013-17, RF-015-02, D-14: lo que leyó el cálculo se comprueba contra lo que anotó la operación al empezar: si un parámetro cambió entre prepararla y empezarla, el resultado ya no
        le corresponde (``des.input_changed``, al avanzar y antes de escribir nada): la operación nueva queda fallida y la anterior, vigente."""
        before = self.current("ACC-001")
        request = self.request_for(before)
        real = store.OperationStart.begin

        def begin(start: Any, project: Any, **options: Any) -> Any:
            self.change(f"{KEY}walk_width_m", 6.0)
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(store.OperationStart, "begin", begin):
            handle, work = store.recompute_run(request)
        written = self.query("SELECT count(*) FROM gb_dataset")
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?", handle.uid), [("failed", before)])
        self.assertEqual(self.current("ACC-001"), before)
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset"), written, "no escribió ningún dato")


class AccessReproduceTest(LifecycleCase):
    """RF-017-24, RF-017-25, RF-015-02, RF-009-11, RF-009-19: la accesibilidad de V01 (sobre la explotación de una cantera, con su final, sus bermas y las dos entradas) congelada en
    ``V01.r1``, reproducida **sin proyecto**."""

    revision: ClassVar[str]
    uid: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        _calculation, stored = cls.create(bank_request(ACCESS_NAME, surface=EXPLOITATION))
        cls.uid = str(stored.handle.uid)
        with cls.project.write_transaction() as conn:  # congelar no admite lo obsoleto sin aceptarlo: los datos de la segunda cantera, que no lee la accesibilidad, dejan de estarlo
            conn.execute("DELETE FROM gb_stale")
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto (los ficheros y el contador de cambios de la base, sin la caché donde reproduce)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        return report

    def assert_same(self, report: Any) -> None:
        """La accesibilidad reprodujo cada dato que escribió (el mismo papel y nombre, en su orden) y cada cifra, todos iguales."""
        mine = [check for check in report.outputs if check.operation_uid == self.uid]
        self.assertEqual([(check.role, check.name) for check in mine], [(row[2], row[0]) for row in self.outputs(self.uid)])
        self.assertEqual(len(mine), 5)
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        found = [check for check in report.figures if check.operation_uid == self.uid]
        self.assertEqual(len(found), len(self.figures_of(self.uid)))
        self.assertEqual(len(found), 9)
        self.assertTrue(all(check.same for check in found), [check for check in found if not check.same])
        self.assertNotIn(self.uid, [note.operation_uid for note in report.not_reproducible])  # (la de prueba que escribe la cantera no se reproduce: no cuenta aquí)

    def test_a_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-017-24, RF-017-25, RF-015-02, RF-009-11: reproducir V01.r1 —sin proyecto, desde la capa de entradas, la superficie, la final, las bermas, las máscaras y los parámetros
        congelados— da de cada dato de la accesibilidad (lo alcanzable, las bermas, las plataformas, las zonas y el informe) el **mismo hash** que registró la operación y las mismas
        cifras, sin escribir nada en el proyecto."""
        self.assert_same(self.reproduce())

    def test_b_changing_and_recomputing_after_freezing_leaves_the_frozen_revision_as_it_was(self) -> None:
        """RF-015-02, RF-015-16, RF-009-19, RF-008-26: congelada V01.r1, cambiar un umbral deja obsoleta la accesibilidad y «Recalcular lo obsoleto» la repite **en la revisión abierta**;
        lo congelado no cambia (la revisión sigue congelada, sus elementos son los mismos, la operación sustituida queda en ella como historia) y V01.r1 se reproduce otra vez igual."""
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision)
        self.assertTrue(items)
        frozen = {row[0]: row[3] for row in self.outputs(self.uid)}
        self.change(f"{KEY}walk_slope_pct", 3.0)
        self.assertEqual(self.stale_causes(self.uid), {("parameter_changed", f"{KEY}walk_slope_pct")})
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE])
        (made,) = outcome.results[0].operations
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'", self.v1.uid)[0]
        self.assertEqual(self.query("SELECT supersedes_uid, revision_uid FROM gb_operation WHERE uid = ?", made), [(self.uid, opened)])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?", self.uid), [(self.revision,)])
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", self.revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision), items)
        self.assertNotEqual({row[0]: row[3] for row in self.outputs(str(made))}[provenance.dataset_name(provenance.ACCESS_GRID, ACCESS_NAME)],
                            frozen[provenance.dataset_name(provenance.ACCESS_GRID, ACCESS_NAME)], "lo vivo cambió")
        self.assert_same(self.reproduce())


if __name__ == "__main__":
    import unittest

    unittest.main()
