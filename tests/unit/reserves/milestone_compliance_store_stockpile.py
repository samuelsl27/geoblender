# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación por recinto con la base de los acopios, en el proyecto: la prueba de hito de
``test_compliance_store_stockpile`` (spec 016, T30; HU-016-2; RF-012-24, RF-012-30, RF-012-31, RF-012-25; RF-016-09;
plan 016 §5.4 A12, §5.7 P-10, §8; DIFF-012 §2 y §4; P-13: con proyecto en la rejilla de 2 m, al paso «hito» de
``tools/check.py --completo``; el «verde» lleva las que no necesitan proyecto).

Sobre la cantera de los acopios (``tests.support.stockpile_data``, rejilla de 2 m, V01 y V02) con una restricción más, «Zona
de acopios» (**sin corte**, de (70, 70) a (150, 130) m: abarca el Acopio 1 y el 2), y la detección de las cinco marcas sobre el
levantamiento del proyecto (``STK-001`` «Acopios», del proyecto; dos materiales, así que dos bases: RF-016-09) y otra sobre el de
V01 (``STK-001`` «Acopios de V01», de V01). Las finales se escriben como rejillas del proyecto: la **retirada** (cada acopio
bajado hasta su base) y la del **pozo** (la retirada y, además, una celda del acopio 0,5 m por debajo de su base y otra de
fuera de los acopios 1 m por debajo de su terreno). Las cuentas, a mano sobre las rejillas:

- **RF-012-30 (a)**: elegir la base (``select_bases``): una detección al día hecha sobre la partida se usa y se nombra (código,
  nombre, ámbito y material: una base por material); la de otra superficie —y todas, si la partida es una cota constante—
  no, con su causa.
- **RF-012-24, RF-012-30 (b)**: ``res.verify_constraints`` con la base: cada base, una **entrada** de la operación (el papel
  ``stockpile_base_<k>``), sus ajustes, su fila en la tabla y la cifra CALCULADO del corte de acopios por zona (``cut_terrain``
  en las zonas sin corte, de solo relleno, de solo restauración, de resguardo y en la banda hacia dentro): la retirada da corte
  de terreno 0 y «cumple» y el pozo, «no cumple» con lo que baja de la base; terreno + acopios = el corte de RF-012-21.
- **RF-012-30 (c), P-10**: con dos bases en una celda, la menor (cuentas a mano).
- **RF-012-31 (d)**: una detección **obsoleta** (cambiar el umbral de la 011) deja obsoleta la verificación y no se usa: todo el
  corte cuenta, como sin base, y la tabla nombra la detección con su causa; recalcular la detección y después la verificación
  vuelve a usarla (con las bases nuevas); una base en otra rejilla se rechaza como RF-011-03 sin registrar nada.
- **RF-012-25 (e)**: congelar con lo que no cumple da los m³ de corte de terreno de cada zona.
- **RF-012-24 (z)**: congelada V01.r1, reproducir da las mismas salidas y cifras (con la base congelada como entrada).
- **Sin base**: sin detecciones, las mismas entradas, ajustes, tabla y cifras que antes de la 016 (``NoStockpilesTest``).

Las pruebas de cada clase, en el orden de sus letras sobre el mismo estado.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from datetime import date
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cproject
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_stockpile_operation as top
from tests.unit.design import test_stockpile_prepare as tp

gis = import_geoblender("gis")
core_params = import_geoblender("core.params")
cmodel = import_geoblender("core.constraints.model")
cstore_constraints = import_geoblender("core.constraints.store")
cparams = import_geoblender("core.constraints.params")
registry = import_geoblender("core.datasets.registry")
access = import_geoblender("gis.masks.access")
recompute_mod = import_geoblender("core.provenance.recompute")
figures_mod = import_geoblender("core.provenance.figures")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_messages = import_geoblender("reserves.messages")
stockpile_store = import_geoblender("design.stockpile_store")
design_store = import_geoblender("design.store")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")

GRID = qfx.grid_of(qfx.COARSE_STEP_M)
SURVEY = sdata.survey(GRID)
ZONE_CODE = "acopios"
ZONE_BOX = (70.0, 70.0, 150.0, 130.0)
"""La zona sin corte (local): abarca el Acopio 1 (de 90 a 110 m) y el 2 (de 110 a 130 m)."""
CELL_M2 = 4.0
MIN_M = 0.02
NAME = "Retirada de acopios"
TERRAIN_ZONES = ("sin_corte", ZONE_CODE, "concesion:inner")
"""Los recintos que cuentan el corte de terreno con base (A12): la zona sin corte de la cantera, la nuestra y la banda hacia
dentro del límite (no hay de solo relleno, de solo restauración ni de resguardo)."""
OTHER_COUNTS = {"outside_perimeter": "any", "outside_legal": "cut", "concesion": "nothing", "perimetro": "nothing",
                "torre": "any"}
"""Lo que cuenta en los demás recintos, con o sin base."""
FIGURES = {"res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2", "res.check_nodata_area_m2"}
"""Las cifras de siempre de la cantera (no hay «preferible no afectar», así que no hay volumen ponderado)."""
V = compliance.Verdict


def _no_recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de la verificación no recalculan con la función de bl")


def _last(steps: Iterator[Any]) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def hand_cut(start: np.ndarray, final: np.ndarray, box: tuple[float, float, float, float] = ZONE_BOX) -> float:
    """El corte de RF-012-21 de las celdas cuyo centro está en ``box``, a mano: lo que pasa del espesor mínimo."""
    cells = tp.hand_cells(box)
    diff = (start.ravel() - final.ravel())[cells]
    return float(diff[diff > MIN_M].sum() * CELL_M2)


def hand_terrain(start: np.ndarray, base: np.ndarray, final: np.ndarray,
                 box: tuple[float, float, float, float] = ZONE_BOX) -> float:
    """El corte de terreno de RF-012-30 en ``box``, a mano: R = mín(partida, base) donde hay base y R = partida donde no."""
    return hand_cut(np.fmin(start, base), final, box)


def zone_row(stored: Any, final: int, code: str) -> Any:
    """Lo guardado de un recinto en un final (``StoredZone``) de una verificación vigente."""
    (found,) = [item for item in stored.zones if item.zone == code and item.final == final]
    return found


class _Case(top.RecomputeCase):
    """La cantera con la restricción «Zona de acopios», lo de la verificación registrado y las máscaras de V01 al día."""

    start: ClassVar[Any]
    version_start: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(cstore.operation_def(_no_recompute, cstore.REPRODUCE[cstore.VERIFY]),
                                         *cstore.FIGURES))
        core_params.register_definitions(cstore.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        kinds, types = cmodel.GeometryKind, cmodel.ConstraintType
        row = cmodel.Constraint(
            uid=f"{ZONE_CODE:0<32}"[:32], code=ZONE_CODE, name="Zona de acopios", ctype=types.NO_CUT, kind=kinds.POLYGON,
            parts=((cfx.rectangle(*ZONE_BOX),),), priority=0, reason="Prueba de la verificación con la base",
            decided_by="Samuel (IMGA)", decided_on=date(2026, 11, 19), decision_uid=None, intention_uid=None,
            source_input=None, source_fid=None, layer=cstore_constraints.layer_of(kinds.POLYGON), fid=0)
        cls.clock.advance(minutes=1)
        cproject.edit_constraints(cls.project, (row,))
        cproject.declare(cls.project, cls.clock, {cparams.active_key(ZONE_CODE): True,
                                                  cparams.buffer_out_key(ZONE_CODE): 0.0})
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v1.uid):
            pass
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.start = surfaces.SurfaceRef(dataset=sdata.SURVEY_DATASET, label="Levantamiento")
        cls.version_start = surfaces.SurfaceRef(dataset=tp.VERSION_SURFACE, label="Levantamiento de V01")

    @classmethod
    def write_finals(cls, *grids: tuple[str, np.ndarray], grid: Any = None) -> None:
        """Escribe ``grids`` (etiqueta, cotas) como rejillas del proyecto (``gis_dtm_<etiqueta>``)."""
        cls.clock.advance(minutes=1)
        found = cls.grid if grid is None else grid
        write_grids(cls.project, [(label, gis.Raster(found, values, sdata.CRS, sdata.VERTICAL))
                                  for label, values in grids], message="Finales de la verificación con la base")

    def ops(self, op_type: str) -> list[str]:
        return [row[0] for row in self.query("SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY rowid", op_type)]

    def op_named(self, name: str) -> str:
        """La verificación vigente (sin sustituir) llamada ``name``."""
        for uid, text in self.query("SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                                    "superseded_by IS NULL ORDER BY rowid DESC", cstore.VERIFY):
            if json.loads(text)["name"] == name:
                return str(uid)
        raise AssertionError(f"no hay una verificación «{name}»")

    def stale(self, uid: str) -> bool:
        return bool(self.query("SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid))

    def verify(self, finals: Any, *, name: str = NAME, start: Any = None, **options: Any) -> Any:
        """Verifica ``finals`` (etiquetas de rejillas del proyecto) en V01 y da lo guardado (``StoredCheck``)."""
        self.clock.advance(minutes=1)
        return _last(cstore.verify_project_steps(
            self.project, version=self.v1.uid, name=name, start=self.start if start is None else start,
            finals=tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_{label}") for label in finals), **options))

    def read(self, name: str = NAME) -> Any:
        with self.project.read() as conn:
            return cstore.read_verification(conn, self.v1.uid, name)

    def table_rows(self, name: str = NAME) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            record = registry.get(conn, cstore.dataset_name(cstore.TABLE, name), version_uid=self.v1.uid)
            return cstore.read_table(conn, record.locator)

    def inputs(self, uid: str) -> dict[str, str]:
        """Lo que consumió la operación ``uid``: papel → nombre del dato."""
        return dict(self.query("SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d "
                               "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid))

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def settings_of(self, uid: str) -> dict[str, Any]:
        (text,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0]
        return json.loads(text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------------------------
# Sin acopios: lo mismo que antes
# ---------------------------------------------------------------------------------------------


class NoStockpilesTest(_Case):
    """RF-012-24 («sin base, las mismas entradas y ajustes que en la 0.4»), RF-012-30 (sin acopios detectados, el resultado
    de siempre): sin ninguna detección, la verificación no lee ninguna base ni deja nada de más."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cut = SURVEY.copy()
        cut.ravel()[tp.hand_cells(ZONE_BOX)] -= 1.0
        cls.write_finals(("cortada", cut))
        cls.stored = cls("test_a_no_detection_no_base").verify(("cortada",))

    def test_a_no_detection_no_base(self) -> None:
        """RF-012-30, RF-012-31: ninguna detección, ninguna base ni nada que avisar; ``select_bases`` da una selección
        vacía (aunque la partida sea una cota constante)."""
        for ref in (self.start, surfaces.SurfaceRef(elevation=100.0), self.version_start):
            with self.subTest(partida=ref.shown):
                found = cstore.select_bases(self.project, self.v1.uid, ref)
                self.assertEqual((found.bases, found.skipped, found.refs), ((), (), ()))

    def test_b_same_inputs_settings_figures_and_table_as_before(self) -> None:
        """RF-012-24: las entradas son las máscaras, la partida y la final (ningún ``stockpile_base_<k>``); los ajustes, los
        de siempre; las cifras, las de siempre; la tabla, sin el corte de acopios ni filas de bases; y lo que cuenta en
        las zonas sigue siendo el corte (``cut``): el de la zona sin corte pasa entero a ser terreno."""
        uid = self.op_named(NAME)
        roles = sorted(self.inputs(uid))
        self.assertEqual([role for role in roles if role.startswith(("start", "final"))], ["final_1", "start"])
        self.assertFalse([role for role in roles if "base" in role])
        self.assertEqual(sorted(self.settings_of(uid)), ["finals", "name", "pending_names", "pending_sectors", "start"])
        self.assertEqual({key for key, _scope in self.figures_of(uid)}, FIGURES)
        stored = self.read()
        self.assertEqual((stored.bases, stored.skipped), ((), ()))
        self.assertTrue(all(zone.stockpile_cut_m3 is None for zone in stored.zones))
        self.assertEqual({zone.zone: zone.counts for zone in stored.zones if zone.final == 1},
                         {**OTHER_COUNTS, **dict.fromkeys(TERRAIN_ZONES, "cut")})
        quantities = {row[2] for row in self.table_rows()}
        self.assertFalse({"stockpile_cut_m3", "stockpile_base", "stockpile_skipped"} & quantities)
        zone = zone_row(stored, 1, ZONE_CODE)
        self.assertEqual(zone.verdict, V.FAILS.value)
        self.assertAlmostEqual(zone.counted_m3 / (1.0 * CELL_M2 * len(tp.hand_cells(ZONE_BOX))), 1.0, places=9)
        self.assertEqual(zone.counted_m3, zone.cut_m3)

    def test_c_settings_and_inputs_helpers_without_a_base_are_the_old_ones(self) -> None:
        """RF-012-24: ``verify_settings`` y ``verify_inputs`` sin base (con o sin la selección vacía) son lo de la 0.4."""
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_cortada"),)
        old = cstore.verify_settings(NAME, self.start, finals, ["s1"], ["Sector 1"])
        self.assertEqual(sorted(old), ["finals", "name", "pending_names", "pending_sectors", "start"])
        self.assertEqual(cstore.verify_settings(NAME, self.start, finals, ["s1"], ["Sector 1"], bases=cstore.BaseSelection()),
                         old)
        plain = cstore.verify_inputs(self.project, self.v1.uid, self.start, finals)
        self.assertEqual([(use.item, use.role) for use in plain],
                         [(sdata.SURVEY_DATASET, "start"), ("gis_dtm_cortada", "final_1")])
        self.assertEqual(cstore.verify_inputs(self.project, self.v1.uid, self.start, finals, bases=cstore.BaseSelection()),
                         plain)

    def test_d_the_role_of_a_base_and_the_message_of_a_terrain_cut(self) -> None:
        """RF-012-25: el rol de una base se cuenta de 1 en 1 y el modo de contar del corte de terreno (``cut_terrain``) tiene su
        mensaje de congelar (m³ de corte de terreno)."""
        self.assertEqual(cstore.base_role(1), "stockpile_base_1")
        self.assertEqual(cstore.base_role(12), "stockpile_base_12")
        with self.assertRaises(ValueError):
            cstore.base_role(0)
        text = res_messages.render("res.freeze_cut_terrain", zone="«acopios»", volume="2,0")
        self.assertIn("2,0 m³", text)
        self.assertIn("terreno", text)
        self.assertIn("terrain", res_messages.render("res.freeze_cut_terrain", language="en", zone="«a»", volume="2.0"))


# ---------------------------------------------------------------------------------------------
# Con la base de una detección
# ---------------------------------------------------------------------------------------------


class _WithDetections(_Case):
    """Además, la detección del proyecto (``Acopios``) sobre el levantamiento del proyecto y la de V01 (``Acopios de V01``)
    sobre el suyo, y la retirada y el pozo como finales."""

    project_calculation: ClassVar[Any]
    version_calculation: ClassVar[Any]
    bases: ClassVar[dict[str, np.ndarray]]
    lowest: ClassVar[np.ndarray]
    removal: ClassVar[np.ndarray]
    dug: ClassVar[np.ndarray]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project_calculation, _ = cls.create(tp.request("Acopios"), version=None, masks=None)
        cls.version_calculation, _ = cls.create(tp.request("Acopios de V01", surface=tp.VERSION_SURFACE))
        cls.bases = {material: cls.project_calculation.outcome.base_grid(material) for material in ("mineral", "estéril")}
        cls.lowest = np.fmin(*cls.bases.values())
        cls.removal = np.fmin(SURVEY, cls.lowest)
        zone = tp.hand_cells(ZONE_BOX)
        under = np.isfinite(cls.lowest.ravel()[zone])
        pit, outside = int(zone[under][0]), int(zone[~under][0])
        cls.dug = cls.removal.copy()
        cls.dug.ravel()[pit] = cls.lowest.ravel()[pit] - 0.5
        cls.dug.ravel()[outside] = SURVEY.ravel()[outside] - 1.0
        cls.write_finals(("retirada", cls.removal), ("pozo", cls.dug))


class SelectionTest(_WithDetections):
    """RF-012-30, RF-012-31 (a): elegir las bases de una partida."""

    def test_a_a_current_detection_is_used_and_named(self) -> None:
        """Sobre el levantamiento del proyecto, la detección del proyecto, al día, se usa —una base por material, en el orden
        de sus acopios, con el uid del dato y un nombre que nombra la detección y el material— y la de V01, hecha sobre
        otra superficie, no: se avisa con su causa. La partida se indica por su nombre o por su uid."""
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)
        (uid,) = self.query("SELECT uid FROM gb_dataset WHERE name = ?", sdata.SURVEY_DATASET)[0]
        for ref in (self.start, surfaces.SurfaceRef(dataset=uid)):
            with self.subTest(partida=ref.dataset):
                found = cstore.select_bases(self.project, self.v1.uid, ref)
                self.assertEqual([(item.detection, item.name, item.scope, item.material) for item in found.bases],
                                 [("STK-001", "Acopios", "project", "mineral"),
                                  ("STK-001", "Acopios", "project", "estéril")])
                self.assertEqual([item.ref.dataset for item in found.bases], [item.base.uid for item in mine.materials])
                self.assertEqual(found.refs, tuple(item.ref for item in found.bases))
                self.assertTrue(all("STK-001" in item.ref.shown and "Acopios" in item.ref.shown for item in found.bases))
                (skipped,) = found.skipped
                self.assertEqual((skipped.detection, skipped.name, skipped.scope, skipped.reason, skipped.surface),
                                 ("STK-001", "Acopios de V01", "version", stockpile_store.EXCLUDED_OTHER_SURFACE,
                                  tp.VERSION_SURFACE))
        first = found.bases[0].text()
        self.assertIn("STK-001", first)
        self.assertIn("Acopios", first)
        self.assertIn("mineral", first)

    def test_b_the_detection_of_a_version_is_used_on_its_surface(self) -> None:
        """Sobre el levantamiento de V01, se usa la de V01 (dos bases; ámbito ``version``) y se avisa de la del proyecto."""
        found = cstore.select_bases(self.project, self.v1.uid, self.version_start)
        self.assertEqual([(item.detection, item.name, item.scope, item.material) for item in found.bases],
                         [("STK-001", "Acopios de V01", "version", "mineral"),
                          ("STK-001", "Acopios de V01", "version", "estéril")])
        self.assertEqual([(item.name, item.scope, item.reason) for item in found.skipped],
                         [("Acopios", "project", stockpile_store.EXCLUDED_OTHER_SURFACE)])

    def test_c_another_surface_or_a_constant_uses_no_base_and_warns_of_every_detection(self) -> None:
        """Una partida que no es la de ninguna detección (otro levantamiento o una cota constante) no usa ninguna base y
        avisa de las dos, con su causa y la superficie en que se hicieron (RF-012-31)."""
        for ref in (surfaces.SurfaceRef(dataset=sdata.PREVIOUS_DATASET), surfaces.SurfaceRef(elevation=100.0)):
            with self.subTest(partida=ref.shown):
                found = cstore.select_bases(self.project, self.v1.uid, ref)
                self.assertEqual(found.bases, ())
                self.assertEqual([(item.name, item.reason, item.surface) for item in found.skipped],
                                 [("Acopios", stockpile_store.EXCLUDED_OTHER_SURFACE, sdata.SURVEY_DATASET),
                                  ("Acopios de V01", stockpile_store.EXCLUDED_OTHER_SURFACE, tp.VERSION_SURFACE)])
        text = found.skipped[0].text("100.0 m")
        self.assertIn("STK-001", text)
        self.assertIn("«Acopios»", text)
        self.assertIn(sdata.SURVEY_DATASET, text)
        self.assertIn("100.0 m", text)
        self.assertNotIn("?", text)

    def test_d_the_inputs_of_the_operation_are_the_bases_by_role(self) -> None:
        """RF-012-24: ``verify_inputs`` da, además de la partida y las finales, cada base como entrada con su papel
        ``stockpile_base_<k>`` (de 1 en 1), por el uid de su dato; con la selección dada, esa (y vacía, ninguna)."""
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_retirada"),)
        found = cstore.select_bases(self.project, self.v1.uid, self.start)
        uses = cstore.verify_inputs(self.project, self.v1.uid, self.start, finals)
        self.assertEqual([(use.item, use.role) for use in uses],
                         [(sdata.SURVEY_DATASET, "start"), ("gis_dtm_retirada", "final_1"),
                          (found.bases[0].ref.dataset, "stockpile_base_1"), (found.bases[1].ref.dataset, "stockpile_base_2")])
        self.assertEqual(cstore.verify_inputs(self.project, self.v1.uid, self.start, finals, bases=found), uses)
        empty = cstore.verify_inputs(self.project, self.v1.uid, self.start, finals, bases=cstore.BaseSelection())
        self.assertEqual([use.role for use in empty], ["start", "final_1"])


class VerifyWithBaseTest(_WithDetections):
    """RF-012-24, RF-012-30, RF-012-31, RF-012-25: verificar con la base automática, recalcular, congelar. En orden: cada
    prueba parte de lo que dejó la anterior."""

    def test_a_the_removal_complies_and_the_pit_does_not(self) -> None:
        """RF-012-30, RF-012-22, CE-016-03: la retirada (cada acopio, a su base) da en la zona sin corte corte de terreno 0 m³
        y «cumple», con el corte de acopios aparte; el pozo, «no cumple» con 2 m³ de la celda bajo la base y 4 m³ de la de
        fuera de los acopios; terreno + acopios = el corte de RF-012-21 (a ≤ 10⁻⁹ relativo, a mano) y lo que cuenta en los
        demás recintos no cambia."""
        result = self.verify(("retirada", "pozo")).result
        for position, final in ((1, self.removal), (2, self.dug)):
            cut = hand_cut(SURVEY, final)
            terrain = hand_terrain(SURVEY, self.lowest, final)
            found = result.finals[position - 1].zone(ZONE_CODE)
            with self.subTest(final=position):
                self.assertEqual(found.counts, compliance.Counts.CUT_TERRAIN)
                self.assertAlmostEqual(found.cut_m3 / cut, 1.0, places=9)
                self.assertAlmostEqual(found.counted_m3, terrain, places=9)
                self.assertAlmostEqual(found.stockpile_cut_m3 / (cut - terrain), 1.0, places=9)
                self.assertAlmostEqual((found.counted_m3 + found.stockpile_cut_m3) / found.cut_m3, 1.0, places=9)
        removed = result.finals[0].zone(ZONE_CODE)
        self.assertEqual((removed.counted_m3, removed.verdict), (0.0, V.COMPLIES))
        self.assertGreater(removed.stockpile_cut_m3, 700.0)
        dug = result.finals[1].zone(ZONE_CODE)
        self.assertAlmostEqual(dug.counted_m3, 0.5 * CELL_M2 + 1.0 * CELL_M2, places=9)
        self.assertEqual(dug.verdict, V.FAILS)
        self.assertEqual(result.fails, (False, True))
        for zone in result.finals[0].totals:
            if zone.code not in TERRAIN_ZONES:
                self.assertEqual((zone.counts.value, zone.stockpile_cut_m3), (OTHER_COUNTS[zone.code], 0.0), zone.code)

    def test_b_the_operation_consumes_the_bases_and_records_them(self) -> None:
        """RF-012-24, RF-012-31: la operación consume las dos bases como ``stockpile_base_1`` y ``_2`` (los datos de la
        detección), sus ajustes dicen cuáles (detección, material y dato) y qué detección no se usó y por qué; las cifras
        son las de siempre y, de cada recinto de terreno y final, la del corte de acopios (CALCULADO, con el mismo
        ámbito); las de los demás recintos, no."""
        uid = self.op_named(NAME)
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)
        inputs = self.inputs(uid)
        self.assertEqual((inputs["stockpile_base_1"], inputs["stockpile_base_2"]),
                         (mine.materials[0].base.name, mine.materials[1].base.name))
        settings = self.settings_of(uid)
        self.assertEqual([(item["detection"], item["name"], item["scope"], item["material"]) for item in settings["bases"]],
                         [("STK-001", "Acopios", "project", "mineral"), ("STK-001", "Acopios", "project", "estéril")])
        self.assertEqual([item["dataset"] for item in settings["bases"]], [item.base.uid for item in mine.materials])
        (skipped,) = settings["skipped"]
        self.assertEqual((skipped["name"], skipped["reason"], skipped["surface"]),
                         ("Acopios de V01", "other_surface", tp.VERSION_SURFACE))
        figures = self.figures_of(uid)
        self.assertEqual({key for key, _scope in figures}, {*FIGURES, "res.check_stockpile_cut_m3"})
        for position in (1, 2):
            for code in (*TERRAIN_ZONES, *OTHER_COUNTS):
                scope = figures_mod.scope_json({"check": NAME, "final": position, "zone": code})
                self.assertEqual(("res.check_stockpile_cut_m3", scope) in figures, code in TERRAIN_ZONES, (position, code))
        scope = figures_mod.scope_json({"check": NAME, "final": 1, "zone": ZONE_CODE})
        self.assertAlmostEqual(figures[("res.check_stockpile_cut_m3", scope)] / hand_cut(SURVEY, self.removal), 1.0, places=9)
        self.assertEqual(self.query("SELECT DISTINCT kind FROM gb_figure WHERE operation_uid = ? AND key = "
                                    "'res.check_stockpile_cut_m3'", uid), [("CALCULADO",)])
        self.assertTrue(all(np.isfinite(value) for value in figures.values()))

    def test_c_the_table_names_the_bases_and_the_unused_detections(self) -> None:
        """RF-012-24, RF-012-31: la tabla guarda, por recinto de terreno y final, el corte de acopios (y ``cut_terrain`` como
        lo que cuenta) y, en el final 0, una fila por base (la detección, su nombre y el material) y otra por detección
        que no se usó con su causa; ``read_verification`` las lee."""
        stored = self.read()
        self.assertEqual(len(stored.bases), 2)
        self.assertTrue(all("STK-001" in text and "Acopios" in text for text in stored.bases))
        self.assertIn("mineral", stored.bases[0])
        self.assertIn("estéril", stored.bases[1])
        (skipped,) = stored.skipped
        self.assertIn("Acopios de V01", skipped)
        self.assertIn(tp.VERSION_SURFACE, skipped)
        self.assertIn("Levantamiento", skipped)
        zone = zone_row(stored, 1, ZONE_CODE)
        self.assertEqual((zone.counts, zone.verdict), ("cut_terrain", V.COMPLIES.value))
        self.assertAlmostEqual(zone.stockpile_cut_m3 / hand_cut(SURVEY, self.removal), 1.0, places=9)
        self.assertEqual({item.counts for item in stored.zones if item.zone in TERRAIN_ZONES}, {"cut_terrain"})
        self.assertTrue(all(item.stockpile_cut_m3 is None for item in stored.zones if item.zone not in TERRAIN_ZONES))
        self.assertEqual(zone_row(stored, 2, ZONE_CODE).verdict, V.FAILS.value)
        self.assertFalse(self.stale(self.op_named(NAME)))
        # T42 (RF-012-30, RF-012-31): lo que anotan los ajustes de la operación, para que la ventana escriba esas líneas en el idioma de la
        # interfaz: la selección (la misma que dan los textos de la tabla, en el idioma pedido) y el nombre de la partida.
        selection = stored.selection
        self.assertEqual(len(selection.bases), 2)
        self.assertEqual(stored.start_name, self.start.shown)
        self.assertEqual(tuple(item.text("es") for item in selection.bases), stored.bases)
        self.assertEqual(tuple(item.text(stored.start_name, "es") for item in selection.skipped), stored.skipped)
        self.assertEqual(selection, cstore.BaseSelection.of_settings(self.settings_of(self.op_named(NAME))))
        self.assertIn("Stockpile base: detection STK-001", selection.bases[0].text("en"))

    def test_d_without_the_base_all_the_cut_counts_as_terrain(self) -> None:
        """RF-012-30, RF-012-31: pedida sin base (la selección vacía), la misma verificación cuenta todo el corte: la retirada
        «no cumple» con el corte entero y no hay corte de acopios ni filas de bases; la de antes, sustituida."""
        before = self.op_named(NAME)
        found = self.verify(("retirada",), bases=cstore.BaseSelection()).result.finals[0].zone(ZONE_CODE)
        self.assertEqual((found.counts, found.verdict), (compliance.Counts.CUT, V.FAILS))
        self.assertEqual((found.counted_m3, found.stockpile_cut_m3), (found.cut_m3, 0.0))
        self.assertAlmostEqual(found.cut_m3 / hand_cut(SURVEY, self.removal), 1.0, places=9)
        uid = self.op_named(NAME)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", before), [(uid,)])
        self.assertFalse([role for role in self.inputs(uid) if "base" in role])
        self.assertNotIn("bases", self.settings_of(uid))
        read = self.read()
        self.assertEqual((read.bases, read.skipped), ((), ()))
        self.assertEqual((read.selection, read.start_name), (cstore.BaseSelection(), self.start.shown))
        self.verify(("retirada", "pozo"))  # la de las dos finales, otra vez con la base automática

    def test_e_two_bases_in_a_cell_count_the_lower_one(self) -> None:
        """RF-012-30, P-10: con dos bases que cubren una misma celda, la menor; a mano, sobre 9 celdas de un acopio de la zona
        (final a 5 m bajo la partida): la base A (3 m bajo la partida en las 9), la B (4 m bajo en 4 de ellas): terreno =
        (4 · 1 + 5 · 2) · 4 = 56 m³; solo A daría 72 y solo B, 116; el orden de las bases no importa."""
        zone = tp.hand_cells(ZONE_BOX)
        footprint = zone[np.isfinite(self.lowest.ravel()[zone])][:9]
        a, b, final = np.full(GRID.shape, np.nan), np.full(GRID.shape, np.nan), SURVEY.copy()
        a.ravel()[footprint] = SURVEY.ravel()[footprint] - 3.0
        b.ravel()[footprint[:4]] = SURVEY.ravel()[footprint[:4]] - 4.0
        final.ravel()[footprint] -= 5.0
        self.write_finals(("base_a", a), ("base_b", b), ("cinco", final))

        def base(label: str, name: str) -> Any:
            return cstore.StockpileBase("STK-X", name, "project", None,
                                        surfaces.SurfaceRef(dataset=f"gis_dtm_{label}", label=name))

        for labels in ((("base_a", "A"), ("base_b", "B")), (("base_b", "B"), ("base_a", "A"))):
            selection = cstore.BaseSelection(tuple(base(label, name) for label, name in labels))
            found = self.verify(("cinco",), name="Dos bases", bases=selection).result.finals[0].zone(ZONE_CODE)
            with self.subTest(orden=[name for _label, name in labels]):
                self.assertAlmostEqual(found.counted_m3, 56.0, places=9)
                self.assertAlmostEqual(found.cut_m3, 9 * 5.0 * CELL_M2, places=9)
                self.assertAlmostEqual(found.stockpile_cut_m3, 180.0 - 56.0, places=9)
        for label, wanted in (("base_a", 72.0), ("base_b", 116.0)):
            selection = cstore.BaseSelection((base(label, "X"),))
            found = self.verify(("cinco",), name="Una base", bases=selection).result.finals[0].zone(ZONE_CODE)
            self.assertAlmostEqual(found.counted_m3, wanted, places=9, msg=label)

    def test_f_a_base_in_another_grid_is_rejected_without_registering_anything(self) -> None:
        """RF-012-31, RF-011-03: una base en otra rejilla se rechaza al llamar (``res.surfaces_mismatch``, nombrando la base)
        sin registrar nada; ``check_sources`` también."""
        fine = gis.Grid(GRID.west, GRID.north, 1.0, 1.0, 300, 300)
        self.write_finals(("rejilla_fina", np.full(fine.shape, 100.0)), grid=fine)
        selection = cstore.BaseSelection((cstore.StockpileBase(
            "STK-X", "Fina", "project", None, surfaces.SurfaceRef(dataset="gis_dtm_rejilla_fina", label="Base fina")),))
        operations_before = self.query("SELECT count(*) FROM gb_operation")
        figures_before = self.query("SELECT count(*) FROM gb_figure")
        with self.assertRaises(res_messages.ResError) as caught:
            self.verify(("retirada",), name="Rechazada", bases=selection)
        self.assertEqual(caught.exception.code, "res.surfaces_mismatch")
        self.assertIn("Base fina", caught.exception.text)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), operations_before)
        self.assertEqual(self.query("SELECT count(*) FROM gb_figure"), figures_before)
        self.assertIsNone(self.read("Rechazada"))
        sources = {cstore.START_ROLE: surfaces.surface_source(self.project, self.start, version_uid=self.v1.uid),
                   cstore.base_role(1): surfaces.surface_source(self.project, selection.bases[0].ref,
                                                                version_uid=self.v1.uid)}
        with self.assertRaises(res_messages.ResError) as direct:
            cstore.check_sources(sources, self.masks_v1, (sdata.CRS, sdata.VERTICAL))
        self.assertEqual(direct.exception.code, "res.surfaces_mismatch")

    def test_g_freezing_lists_the_terrain_cut_of_the_zones_that_do_not_comply(self) -> None:
        """RF-012-25, RF-012-30: congelar con la verificación del pozo (vigente, con base) lista el recinto que no cumple con
        los m³ de **corte de terreno** (los del pozo: 6,0) y la final que no cumple, no la retirada, que cumple."""
        stored = self.verify(("retirada", "pozo"), name="Pozo")
        with self.project.read() as conn:
            found = cstore.freeze_findings(conn, self.v1.uid)
        texts = [finding.text for finding in found if finding.name == "Pozo"]
        self.assertEqual(len(texts), 1, texts)
        self.assertIn("«acopios»: 6,0 m³ de corte de terreno", texts[0])
        self.assertIn("gis_dtm_pozo", texts[0])
        self.assertNotIn("gis_dtm_retirada", texts[0])
        self.assertEqual(stored.result.fails, (False, True))

    def test_h_a_stale_detection_makes_the_check_stale_and_is_not_used(self) -> None:
        """RF-012-24, RF-012-31: cambiar el umbral de la 011 deja obsoleta la detección y, con ella, la verificación (la base
        es una de sus entradas); ya no se usa —la selección lo dice con su causa— y una verificación nueva cuenta todo el
        corte, como sin base, nombrando la detección y lo que cambió."""
        current = self.op_named(NAME)
        self.assertFalse(self.stale(current))
        self.change_threshold(0.6)
        self.assertTrue(self.stale(self.current(version=False)), "la detección")
        self.assertTrue(self.stale(current), "la verificación, por su base")
        found = cstore.select_bases(self.project, self.v1.uid, self.start)
        self.assertEqual(found.bases, ())
        self.assertEqual({(item.name, item.reason) for item in found.skipped},
                         {("Acopios", stockpile_store.EXCLUDED_STALE),
                          ("Acopios de V01", stockpile_store.EXCLUDED_OTHER_SURFACE)})
        (stale,) = [item for item in found.skipped if item.reason == stockpile_store.EXCLUDED_STALE]
        self.assertTrue(stale.cause)
        text = stale.text("Levantamiento")
        self.assertIn("obsoleta", text)
        self.assertIn(stale.cause, text)
        zone = self.verify(("retirada",), name="Sin base obsoleta").result.finals[0].zone(ZONE_CODE)
        self.assertEqual((zone.counts, zone.verdict, zone.stockpile_cut_m3), (compliance.Counts.CUT, V.FAILS, 0.0))
        read = self.read("Sin base obsoleta")
        self.assertEqual(read.bases, ())
        self.assertTrue(any("«Acopios»" in text and "obsoleta" in text and stale.cause in text for text in read.skipped),
                        read.skipped)

    def test_i_recomputing_the_detection_and_then_the_check_uses_the_new_base(self) -> None:
        """RF-012-24, RF-008-26: «Recalcular lo obsoleto» repite la detección y, después, la verificación obsoleta, que
        vuelve a usar la base (la nueva: otros datos, el umbral nuevo) y sustituye a la anterior."""
        old = self.op_named(NAME)
        used = self.settings_of(old)["bases"]
        self.assertTrue(self.stale(old))

        def hashes() -> list[str]:
            return [self.query("SELECT content_sha256 FROM gb_dataset WHERE uid = ?", item["dataset"])[0][0] for item in used]

        before = hashes()
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(self.current(version=False), version=False))
        top.finish(work)
        self.assertFalse(self.stale(handle.uid))
        self.assertTrue(self.stale(old), "la base que usó fue sustituida")
        self.assertTrue(any("res.verify_constraints" in unit for unit in self.recompute_plan()))
        self.clock.advance(minutes=1)
        request = recompute_mod.RecomputeRequest(self.project, old, cstore.VERIFY, self.settings_of(old), (), (),
                                                 version=self.v1.uid)
        new_handle, steps = cstore.recompute_run(request)
        self.assertEqual(new_handle.supersedes, old)
        stored = _last(steps)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", new_handle.uid), [("done",)])
        now = self.settings_of(new_handle.uid)["bases"]
        self.assertEqual([item["name"] for item in now], [item["name"] for item in used])
        self.assertNotEqual(hashes(), before, "la base recalculada con el umbral nuevo es otra")
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET)
        self.assertEqual([item["dataset"] for item in now], [item.base.uid for item in mine.materials])
        self.assertEqual(stored.result.finals[0].zone(ZONE_CODE).counts, compliance.Counts.CUT_TERRAIN)
        self.assertFalse(self.stale(new_handle.uid))


class ReproduceTest(_WithDetections):
    """RF-012-24, RF-012-30 (RF-009-07): la verificación con la base, congelada y reproducida."""

    def test_a_a_frozen_check_with_a_base_reproduces_the_same(self) -> None:
        """RF-012-24, RF-012-30: congelada V01.r1, reproducir la verificación con la base (las dos como entradas congeladas)
        da las mismas salidas (con su hash: la tabla con las filas de las bases) y las mismas cifras bit a bit —también
        la del corte de acopios—, sin escribir nada en el proyecto."""
        self.verify(("retirada", "pozo"), name="Reproducida")
        uid = self.op_named("Reproducida")
        figures = self.figures_of(uid)
        self.assertIn("res.check_stockpile_cut_m3", {key for key, _scope in figures})
        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega"))
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, str(outcome.frozen.uid)))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before)
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual(sorted(check.role for check in mine), ["groups", "table", "violations_2"])
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced
                      for check in report.figures if check.operation_uid == uid}
        self.assertEqual(reproduced, figures)


if __name__ == "__main__":
    unittest.main()
