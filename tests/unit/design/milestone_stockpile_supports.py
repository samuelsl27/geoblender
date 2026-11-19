# SPDX-License-Identifier: GPL-3.0-or-later
"""Los acopios apoyables, con proyecto (spec 016, T15; HU-016-2; RF-016-14 —la parte de «se apoya»—, RF-015-15, RF-015-17, RF-009-11,
CE-016-04; plan 016 §5.2.3 «Dependencias» y §5.4 A13, P-1; ADR-0031 §4). Va al paso «hito» de ``check.py --completo`` (P-13: la
rejilla de 2 m con proyecto); el cálculo puro está en ``test_stockpile_supports.py``, en el «verde».

La cantera de los acopios de 2 m (cinco marcas: V01 con su levantamiento) con la detección ``Acopios`` (``STK-001``) hecha en V01 y
dos plataformas «en corte y relleno» de la 015 que parten de ese levantamiento y **rellenan por encima de un acopio**: «Sobre el
acopio 4» (``PLT-001``, 60 × 40 m a una cota un metro por encima del Acopio 4, que cubre entero: ``Σ (cota − z)·4`` m³ a mano) y «Sobre
el acopio 3» (``PLT-002``, sobre el Acopio 3, a media cota). La operación que rellena se apoya en **el acopio** y no en la detección
entera: sus entradas ``supported_on`` (``des_stp_``, la superficie con que se detectó) y ``support_footprint`` (``des_stk_``, su tabla)
y la cifra ``des.supported_m3`` con el código de la detección y la **clave del acopio** en su ámbito.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design import test_platform_operation as platform_ops
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
dataset_registry = import_geoblender("core.datasets.registry")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
model = import_geoblender("design.model")
operations = import_geoblender("core.provenance.operations")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")
stockpile_store = import_geoblender("design.stockpile_store")

GRID = qfx.grid_of(qfx.COARSE_STEP_M)
CELL_M2 = 4.0
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 por defecto (``res.verify.min_thickness_m``)."""
USER = "Samuel (IMGA)"
LAYER = "gis_fea_plataformas_sobre_acopios"
FOUR, THREE = "Sobre el acopio 4", "Sobre el acopio 3"
DETECTION = "Acopios"
DETECTED = provenance.dataset_name(provenance.STOCKPILE_SURFACE_GRID, DETECTION)
TABLE = provenance.dataset_name(provenance.STOCKPILES_TABLE, DETECTION)
SURVEY = tp.VERSION_SURFACE
"""El levantamiento como superficie de V01: de la que parte la detección y de la que parten las dos plataformas."""
UP_4_M, UP_3_M = 1.0, 0.5
"""Lo que la rasante de cada plataforma queda por encima del punto más alto de su acopio (m)."""


def level_over(name: str, up_m: float) -> float:
    """La cota de la rasante sobre el acopio ``name``: la del punto más alto del levantamiento en la caja de su pie, redondeada hacia
    arriba al metro, más ``up_m`` (m): una plataforma plana **por encima de todo el acopio**, que cubre entero."""
    found = sdata.survey(GRID)[sdata.in_box(sdata.survey_mound(name).foot_box, GRID)]
    return float(math.ceil(float(found.max()))) + up_m


LEVEL_4, LEVEL_3 = level_over("Acopio 4", UP_4_M), level_over("Acopio 3", UP_3_M)


def axes_layer() -> Any:
    """Los ejes de las dos plataformas (arrays nuevos): 60 m de eje y 40 de ancho (± 20 m) centrados en el acopio, planas (0 %)."""
    specs = ((FOUR, ((100.0, 220.0), (160.0, 220.0)), 40.0, LEVEL_4, 0.0),
             (THREE, ((210.0, 100.0), (270.0, 100.0)), 40.0, LEVEL_3, 0.0))
    return qfx.LayerData(
        LAYER, "line", tuple(((cfx.absolute(path),),) for _name, path, *_rest in specs), tuple(item[0] for item in specs),
        {"ancho": tuple(item[2] for item in specs), "cota_inicial": tuple(item[3] for item in specs),
         "pendiente": tuple(item[4] for item in specs)})


def over(name: str, **changes: Any) -> Any:
    """La plataforma ``name`` de la capa de ejes, «en corte y relleno», del levantamiento de V01 (el de las detecciones)."""
    base: dict[str, Any] = {"fields": prep.line_fields(LAYER), "start": SURVEY, "mode": model.PlatformMode.CUT_FILL}
    return prep.request(name, **{**base, **changes})


class SupportsCase(ops.RecomputeCase):
    """Lo de ``RecomputeCase`` de la detección (con sus funciones reales de recalcular y reproducir) más las operaciones de la
    plataforma con las suyas, la capa de ejes y los ayudantes de lo que queda registrado: las entradas ``supported_on`` y
    ``support_footprint`` de una operación, sus cifras por acopio y la huella de cada acopio de la tabla de la detección."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        detection = tuple(provenance.OPERATION_TYPES_BY_NAME[op_type].definition(
            ops.recompute_function, design_reproduce.reproduce_stockpile_detect)
            for op_type in provenance.STOCKPILE_DETECT_TYPES)
        return (*detection, *platform_ops.real_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS, *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")

    @classmethod
    def detect(cls) -> Any:
        """«Calcula» y «crea» la detección ``Acopios`` (las cinco marcas, sin candidatos) sobre el levantamiento de V01."""
        _calculation, stored = cls.create(tp.request(DETECTION, surface=SURVEY))
        return stored

    @classmethod
    def made(cls, asked: Any) -> Any:
        """«Calcula» y «crea» la plataforma ``asked`` en V01 (un minuto después de lo anterior): su ``Stored``."""
        cls.clock.advance(minutes=1)
        calculation = platform_ops.finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return stored

    @classmethod
    def change(cls, key: str, value: object) -> None:  # type: ignore[override]
        """Cambia el parámetro de la versión ``key`` (un minuto después)."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(
                conn, key, value=value, version=cls.v1.uid, reason="Prueba de la T15")

    # --- Lo que apoya una operación -------------------------------------------------------------

    def supports_of(self, uid: str) -> list[tuple[str, str]]:
        """Los pares ``(dato, papel)`` de lo que apoya la operación ``uid`` (``supported_on`` y ``support_footprint``), en el orden en que
        los anotó."""
        return self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role IN ('supported_on', 'support_footprint') "
            "ORDER BY io.fid", uid)

    def supported_of(self, uid: str) -> dict[tuple[str, str | None], float]:
        """Las cifras ``des.supported_m3`` de la operación ``uid`` por ``(entidad, clave de acopio)``."""
        found: dict[tuple[str, str | None], float] = {}
        for key, scope, value in self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid):
            if key == "des.supported_m3":
                where = json.loads(scope)
                found[(where["entity"], where.get("stockpile"))] = value
        return found

    def scopes_of(self, uid: str) -> list[dict[str, str]]:
        """El ámbito de cada cifra ``des.supported_m3`` de la operación ``uid``, en su orden."""
        return [json.loads(scope) for scope in (found for (found,) in self.query(
            "SELECT scope FROM gb_figure WHERE operation_uid = ? AND key = 'des.supported_m3' ORDER BY fid", uid))]

    @classmethod
    def uid_of(cls, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` de V01."""
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def cells_of(self, key: str) -> tuple[np.ndarray, np.ndarray]:
        """Las celdas de la huella del acopio ``key`` de la detección vigente, de su fila de ``des_stk_`` (tramos de fila)."""
        found = stockpile_store.read_detection_table(self.project, provenance.STOCKPILES_TABLE, DETECTION, version_uid=self.v1.uid)
        (row,) = [item for item in found if item["key"] == key]
        return entities.runs_cells(tuple(tuple(run) for run in json.loads(row["footprint"])))

    def grid_of(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` de V01 tal como está en su fichero."""
        return geotiff_reader.read_geotiff(self.root / self.record(name, self.v1).locator).values

    def by_hand(self, key: str, level: float) -> float:
        """Lo que sube una plataforma plana a la cota ``level`` sobre las celdas de la huella del acopio ``key``: ``Σ (cota − z)·4`` de
        las que pasan del espesor mínimo, con ``z`` el levantamiento de la cantera **calculado aparte** (``stockpile_data.survey``), en
        un bucle, no con el código que se prueba."""
        survey = sdata.survey(GRID)
        rows, cols = self.cells_of(key)
        return math.fsum(level - survey[row, col] for row, col in zip(rows, cols, strict=True)
                         if level - survey[row, col] > THICKNESS_M) * CELL_M2

    def from_files(self, platform: str, key: str) -> float:
        """Lo apoyado por la superficie de ``platform`` sobre el acopio ``key`` leído de los **ficheros**: ``r − máx(partida, acopio)`` en las
        celdas de su huella, y el volumen de las que pasan del espesor mínimo (4 m² cada una)."""
        rows, cols = self.cells_of(key)
        result = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, platform))
        start, ground = sdata.survey(GRID), self.grid_of(DETECTED)
        with np.errstate(invalid="ignore"):
            found = result[rows, cols] - np.maximum(start[rows, cols], ground[rows, cols])
        return float(found[found > THICKNESS_M].sum()) * CELL_M2

    def assertRelative(self, value: float, wanted: float, what: str = "") -> None:  # noqa: N802
        self.assertGreater(wanted, 0.0, what)
        self.assertLessEqual(abs(value - wanted) / wanted, 1e-9, f"{what}: {value!r} frente a {wanted!r}")


class SupportsTest(SupportsCase):
    """RF-016-14, RF-015-15, RF-015-17, RF-009-11, CE-016-04, P-1 (A13), **en orden** (``test_a`` a ``test_f``): la detección ``Acopios``
    (``STK-001``, V01) y las dos plataformas, congeladas en ``V01.r1``; cada prueba parte de lo que dejó la anterior."""

    revision: ClassVar[str]
    uids: ClassVar[dict[str, str]]
    volume_4: ClassVar[float]
    volume_3: ClassVar[float]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        cls.made(over(FOUR))
        cls.made(over(THREE, start="entity:PLT-001"))  # de cada superficie parte una sola entidad (RF-015-04)
        cls.uids = {code: cls.uid_of(code) for code in ("STK-001", "PLT-001", "PLT-002")}
        cls.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_a_platform_that_fills_over_a_stockpile_rests_on_that_stockpile_by_its_key(self) -> None:
        """RF-016-14, RF-015-15, P-1, A13: «Sobre el acopio 4» rellena sobre el Acopio 4 (y solo sobre él) y se apoya **en ese acopio**: sus
        entradas son la superficie con que se detectó (``des_stp_``, ``supported_on``) y la tabla de los acopios (``des_stk_``,
        ``support_footprint``), una sola vez, y su cifra ``des.supported_m3`` lleva el ámbito de la detección (``STK-001``) **y la clave
        del acopio**, con el volumen **a mano** (``Σ (cota − z)·4`` m³ sobre las celdas de su huella, con el levantamiento calculado
        aparte) y el de los ficheros (``r − máx(partida, acopio)``) a ≤ 10⁻⁹ relativo; sobre los demás acopios, nada: ninguna otra cifra."""
        uid = self.uids["PLT-001"]
        self.assertEqual(self.supports_of(uid), [(DETECTED, "supported_on"), (TABLE, "support_footprint")])
        self.assertEqual(list(self.supported_of(uid)), [("STK-001", "Acopio 4")], "un acopio por cada clave, y solo el que rellena")
        self.assertEqual(self.scopes_of(uid), [{"name": "sobre_el_acopio_4", "entity": "STK-001", "stockpile": "Acopio 4"}])
        found = self.supported_of(uid)[("STK-001", "Acopio 4")]
        self.assertRelative(found, self.by_hand("Acopio 4", LEVEL_4), "a mano")
        self.assertRelative(found, self.from_files(FOUR, "Acopio 4"), "de los ficheros")
        type(self).volume_4 = found
        other = self.uids["PLT-002"]
        self.assertEqual(self.supports_of(other), self.supports_of(uid))
        self.assertEqual(list(self.supported_of(other)), [("STK-001", "Acopio 3")])
        self.assertRelative(self.supported_of(other)[("STK-001", "Acopio 3")], self.by_hand("Acopio 3", LEVEL_3), "Acopio 3, a mano")
        type(self).volume_3 = self.supported_of(other)[("STK-001", "Acopio 3")]

    def test_a_the_detection_itself_rests_on_nothing(self) -> None:
        """RF-015-15: la detección, que deja datos dispersos y ninguna superficie de diseño, no se apoya en nada (ni en sí misma): sin
        entradas ``supported_on`` ni ``support_footprint`` ni cifra ``des.supported_m3``."""
        uid = self.uids["STK-001"]
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.supported_of(uid), {})

    def test_b_what_rests_on_a_stockpile_is_one_list_with_name_type_and_volume_by_key(self) -> None:
        """RF-016-14, RF-015-15, RF-015-17, P-1 (la lista «lo que se apoya en un acopio», una consulta de entradas y cifras): sobre la
        detección hay **una sola lista** —una fila por operación y acopio— con nombre, tipo, volumen y la clave del acopio; con la
        clave del Acopio 4, **solo** «Sobre el acopio 4»; con la del Acopio 1 (sin nada), ninguna; por nombre vale como por código."""
        found = entities.dependents(self.project, self.v1.uid, "STK-001")
        self.assertEqual([(row.name, row.op_type, row.entity, row.roles, row.stockpile, row.state) for row in found],
                         [(FOUR, "des.platform", "PLT-001", ("supported_on",), "Acopio 4", entities.EntityState.CURRENT),
                          (THREE, "des.platform", "PLT-002", ("supported_on",), "Acopio 3", entities.EntityState.CURRENT)])
        self.assertEqual([row.operation_uid for row in found], [self.uids["PLT-001"], self.uids["PLT-002"]])
        self.assertEqual([row.volume_m3 for row in found], [self.volume_4, self.volume_3])
        only_four = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        self.assertEqual(only_four, found[:1])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3"), found[1:])
        for key in ("Acopio 1", "Acopio 5", "Acopio que no existe"):
            with self.subTest(key=key):
                self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile=key), ())
        self.assertEqual(entities.dependents(self.project, self.v1.uid, DETECTION), found)
        self.assertIn("m³", found[0].text("es"))
        self.assertTrue(found[0].text("es").startswith(f"{FOUR} (Plataforma): "), found[0].text("es"))

    def test_b_what_an_operation_rests_on_names_the_stockpile_and_its_start(self) -> None:
        """RF-016-14, RF-015-15 («en qué se apoya»): «Sobre el acopio 4» se apoya en la detección, **en el Acopio 4** (con su volumen), y
        parte del levantamiento (sin volumen); una plataforma de la 015 sobre otra plataforma sigue dando lo de siempre."""
        found = entities.dependencies_of(self.project, self.v1.uid, "PLT-001")
        first, second = found
        self.assertEqual((first.name, first.op_type, first.entity, first.roles, first.stockpile, first.state),
                         (DETECTION, "des.stockpile_detect", "STK-001", ("supported_on",), "Acopio 4",
                          entities.EntityState.CURRENT))
        self.assertEqual(first.volume_m3, self.volume_4)
        self.assertEqual((second.roles, second.entity, second.volume_m3, second.stockpile), (("surface",), None, None, None))
        third, fourth = entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
        self.assertEqual((third.stockpile, third.volume_m3), ("Acopio 3", self.volume_3))
        self.assertEqual((fourth.entity, fourth.roles, fourth.volume_m3, fourth.stockpile),
                         ("PLT-001", ("surface",), None, None), "parte de la superficie de la primera")
        self.assertEqual(entities.dependencies_of(self.project, self.v1.uid, "STK-001")[0].roles, ("surface",))

    def test_c_reproducing_the_frozen_revision_gives_the_same_figures_by_stockpile(self) -> None:
        """RF-009-11, RF-016-14, RF-015-15 (CE-016-04): reproducir ``V01.r1`` —sin proyecto, desde la superficie del acopio y la tabla de su huella
        congeladas— da, de cada plataforma, la **misma cifra por acopio** (``des.supported_m3`` con la clave en su ámbito), y de todo lo
        demás el mismo hash, sin escribir nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before,
                         "reproducir no escribe en el proyecto")
        for code, key in (("PLT-001", "Acopio 4"), ("PLT-002", "Acopio 3")):
            found = [check for check in report.figures
                     if check.operation_uid == self.uids[code] and check.key == "des.supported_m3"]
            self.assertEqual(len(found), 1, f"{code}: la cifra de lo apoyado en {key}")
            self.assertTrue(found[0].same, found[0])
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_d_recomputing_the_platform_measures_what_it_rests_on_again(self) -> None:
        """RF-015-15, RF-009-19 (C-1): congelada ``V01.r1``, subir un metro la rasante de «Sobre el acopio 4» y recalcularla **vuelve a medir** lo
        apoyado en el Acopio 4 sobre el resultado nuevo (a mano: más celdas y más relleno en cada una), sin repetir sus entradas
        (la superficie del acopio y la tabla, una sola vez) y con **una** cifra por acopio; lo congelado no cambia y se reproduce igual."""
        frozen = self.uids["PLT-001"]
        self.change(design_params.entity_key("PLT-001", "start_level_m"), LEVEL_4 + 1.0)
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 2,
                         "P1 y P2, que parte de su superficie")
        again = self.uid_of("PLT-001")
        self.assertNotEqual(again, frozen)
        self.assertEqual(self.supports_of(again), [(DETECTED, "supported_on"), (TABLE, "support_footprint")])
        self.assertEqual(list(self.supported_of(again)), [("STK-001", "Acopio 4")])
        now = self.supported_of(again)[("STK-001", "Acopio 4")]
        self.assertRelative(now, self.by_hand("Acopio 4", LEVEL_4 + 1.0), "a mano")
        self.assertGreater(now, self.volume_4 + 0.9 * 4.0 * len(self.cells_of("Acopio 4")[0]), "un metro más sobre cada celda")
        self.assertEqual(self.supported_of(frozen), {("STK-001", "Acopio 4"): self.volume_4}, "lo congelado no cambia")
        listed = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        self.assertEqual([(row.operation_uid, row.volume_m3) for row in listed], [(again, now)])
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertTrue(report.matches, report.not_reproducible)
        type(self).volume_4 = now

    def test_e_a_recompute_that_no_longer_fills_over_a_stockpile_registers_no_figure_for_any(self) -> None:
        """RF-016-14, RF-015-15 (A13): bajada la rasante de «Sobre el acopio 4» por debajo del terreno (corta en vez de rellenar) y
        recalculada, ya no se apoya en ningún acopio: **ninguna** cifra ``des.supported_m3`` (no se declaran con 0 m³ los cinco acopios de
        la detección: la entrada no dice cuáles se apoyaban), pero sigue arrastrando lo que consumía (la superficie y la tabla, una vez),
        así que la detección sigue siendo lo que la deja obsoleta; la lista de la detección entera la da una vez, sin acopio y con 0 m³, y
        la del Acopio 4, ninguna; lo de «Sobre el acopio 3», intacto."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), LEVEL_4 - 10.0)
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 2)
        again = self.uid_of("PLT-001")
        self.assertEqual(self.supported_of(again), {})
        self.assertEqual(self.supports_of(again), [(DETECTED, "supported_on"), (TABLE, "support_footprint")])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4"), ())
        listed = {row.name: (row.stockpile, row.volume_m3, row.state)
                  for row in entities.dependents(self.project, self.v1.uid, "STK-001")}
        self.assertEqual(listed, {FOUR: (None, 0.0, entities.EntityState.CURRENT),
                                  THREE: ("Acopio 3", self.volume_3, entities.EntityState.CURRENT)})
        (rests,) = [row for row in entities.dependencies_of(self.project, self.v1.uid, "PLT-001") if row.entity == "STK-001"]
        self.assertEqual((rests.stockpile, rests.volume_m3), (None, 0.0))

    def test_f_discarding_the_detection_leaves_what_rested_on_it_with_support_removed(self) -> None:
        """RF-015-17, RF-015-15 (D-12): descartados los datos de la detección (nada se borra), la entidad ``STK-001`` queda «descartada» y lo
        que se le apoyaba, en «apoyo retirado», **con su lista** (cada fila con su volumen y la clave de su acopio): el aviso de lo que
        se apoyaba; el motivo lo dice con la detección por su nombre."""
        names = [name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'", self.uids["STK-001"])]
        self.assertGreater(len(names), 8)
        before = entities.dependents(self.project, self.v1.uid, "STK-001")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for name in names:
                dataset_registry.set_status(conn, self.project, self.record(name, self.v1).uid, "discarded")
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"STK-001": entities.EntityState.DISCARDED, "PLT-001": entities.EntityState.SUPPORT_REMOVED,
                                  "PLT-002": entities.EntityState.SUPPORT_REMOVED})
        after = entities.dependents(self.project, self.v1.uid, "STK-001")
        self.assertEqual([(row.name, row.volume_m3, row.stockpile, row.roles) for row in after],
                         [(row.name, row.volume_m3, row.stockpile, row.roles) for row in before])
        self.assertEqual([row.state for row in after], [entities.EntityState.SUPPORT_REMOVED] * 2)
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("Apoyo retirado"), reason)  # type: ignore[union-attr]
        self.assertIn(DETECTION, reason)  # type: ignore[operator]


class ScaleTest(SupportsCase):
    """RNF-015-02, RF-016-14 (la consulta «lo que se apoya en un acopio»): con **200 entidades** en la versión (la detección, una
    plataforma real y 199 sintéticas que se apoyan en el Acopio 4 las impares y en el Acopio 3 las pares, con su cifra), la consulta
    de lo apoyado en un acopio tarda ≤ 1 s en disco local: son entradas y cifras, sin leer ninguna superficie."""

    ENTITIES = 200

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        cls.made(over(FOUR))
        keys: dict[int, list[str]] = {}
        cls.clock.advance(minutes=1)
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            for number in range(2, cls.ENTITIES + 1):
                code = f"PLT-{number:03d}"
                before = "entity:PLT-001" if number == 2 else f"entity:PLT-{number - 1:03d}"
                keys[number] = []
                for param, value in (("name", f"E{number}"), ("start", before)):
                    keys[number].append(design_params.entity_key(code, param))
                    store.create(conn, keys[number][-1], value, kind="ADOPTADO", source="Prueba de T15", source_kind="person",
                                 decided_by=USER, reason="Prueba de T15", version=cls.v1.code)
        for number in range(2, cls.ENTITIES + 1):
            cls.synthetic(number, keys[number])

    @classmethod
    def synthetic(cls, number: int, keys: list[str]) -> None:
        """La operación de la entidad ``PLT-nnn`` (sintética: lee sus parámetros, consume la superficie con que se detectó como
        ``supported_on`` y deja su cifra de lo apoyado en el Acopio 4 —las impares— o el 3 —las pares—; sin datos)."""
        name = f"E{number}"
        key = "Acopio 3" if number % 2 == 0 else "Acopio 4"
        cls.clock.advance(seconds=1)
        handle = operations.begin_operation(
            cls.project, "des.platform", settings={"code": f"PLT-{number:03d}", "name": name}, params=keys,
            inputs=[operations.Use(DETECTED, "supported_on")], executor="blender", version=cls.v1.uid)
        with cls.project.write_transaction() as conn:
            handle.complete(conn, figures=provenance.supported_figures(
                name, {provenance.support_ref("STK-001", key): float(number)}))

    def test_a_the_list_of_what_rests_on_a_stockpile_of_200_entities_takes_at_most_a_second(self) -> None:
        """RNF-015-02, RF-016-14, RF-015-15: sobre el Acopio 4 están la plataforma real y las 99 sintéticas impares (con el volumen de su
        cifra), sobre el 3 las 99 pares y sobre el 1, ninguna; cada consulta (en frío, con la versión de 200 entidades) ≤ 1 s, sin leer
        ninguna superficie."""
        self.assertEqual(len(entities.registry(self.project, self.v1.uid)), self.ENTITIES + 1, "las 200 y la detección")
        began = time.perf_counter()
        four = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        four_s = time.perf_counter() - began
        began = time.perf_counter()
        three = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3")
        three_s = time.perf_counter() - began
        began = time.perf_counter()
        everything = entities.dependents(self.project, self.v1.uid, "STK-001")
        everything_s = time.perf_counter() - began
        self.assertEqual([row.entity for row in four], ["PLT-001", *[f"PLT-{number:03d}" for number in range(3, 201, 2)]])
        self.assertEqual([row.volume_m3 for row in four[1:]], [float(number) for number in range(3, 201, 2)])
        self.assertEqual([row.entity for row in three], [f"PLT-{number:03d}" for number in range(2, 201, 2)])
        self.assertEqual(len(everything), len(four) + len(three))
        self.assertEqual({row.stockpile for row in everything}, {"Acopio 3", "Acopio 4"})
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 1"), ())
        for seconds, what in ((four_s, "el Acopio 4"), (three_s, "el Acopio 3"), (everything_s, "la detección entera")):
            self.assertLessEqual(seconds, 1.0, f"«lo que se apoya en {what}» con {self.ENTITIES} entidades")
        (rests,) = [row for row in entities.dependencies_of(self.project, self.v1.uid, "PLT-200") if row.entity == "STK-001"]
        self.assertEqual((rests.stockpile, rests.volume_m3), ("Acopio 3", 200.0))


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
