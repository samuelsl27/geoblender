# SPDX-License-Identifier: GPL-3.0-or-later
"""RF-015-13 y RF-015-14 con los tipos de la 016, **con proyecto** (spec 016, T46; HU-016-3, HU-016-4; RF-015-13, RF-015-14, RF-016-17,
RF-016-20; RF-009-11; hallazgos C-1 y C-2 de la verificación única; plan 016 §5.2.3, §5.3.2). Es la prueba de hito de
``test_supported_edge`` (el dominio): lo que el contrafuerte y el cuerpo «sobre una base» avisan de su borde y de su orden con la
cantera, en la orden de verdad y con la cantera de 2 m de los acopios.

**En orden** (``test_a`` a ``test_e``): cada una parte de lo que dejó la anterior.

- **El resumen** (``test_a``, ``test_b``): un contrafuerte con la zona de coronación que sale por el oeste de la rejilla y un cuerpo «sobre
  una base» con la huella que sale por ahí dan, en el resumen de «Calcular» y **antes** que lo demás, el aviso de lo que la rejilla
  recorta (las celdas y el lugar, contra la fuerza bruta de una rejilla mayor); «Calcular» no escribe nada. **Lo que llega al borde de la
  rejilla no sale aquí**: en esta cantera el límite legal (a 40 m del borde) no admite relleno junto a él, así que ni el pie del contrafuerte
  ni el cuerpo suben allí (el pie cortado es el aviso de siempre); ese aviso se prueba con el dominio (``test_supported_edge``).
- **El informe y lo que se reproduce** (``test_c``, ``test_d``): el aviso va al informe de la entidad (``des_prp_``) y **la reproducción
  desde lo congelado lo repite igual** (la geometría de la zona y de la huella son de lo congelado), con la misma superficie, las mismas
  tablas y las mismas cifras.
- **El orden con la cantera** (``test_e``): sin cantera (el levantamiento) ninguna de las tres órdenes avisa; con la otra superficie de la
  cantera (la de la 014, que aquí se pone en el lugar de ``entity_store.quarry_order``: lo que lee de la cantera es de la 015 y ya está
  probado con la plataforma) el contrafuerte, el cuerpo y la retirada dan ``des.entity_quarry_order`` con el área, lo que más pasa y el
  lugar a mano, **solo en el resumen** (el informe no lo lleva: se reproduce sin la cantera) y sin impedir crearlos.
- **El escalón del borde del cuerpo** (``BodyEdgeStepProjectTest``, ``test_a`` a ``test_c``; decisión de la sesión principal, 19/11/2026): un
  cuerpo «sobre una base» con espesor en el borde de su huella termina en un escalón; el resumen lo dice con **un renglón informativo**
  (``des.body_edge_step``: una nota, no un aviso, no va en ámbar) con el mayor escalón y su lugar, contra un bucle de Python; va al informe y
  **la reproducción desde lo congelado lo repite**. (El salto creado del borde del contrafuerte lo da el pie cortado de la T28.)
"""

from __future__ import annotations

import json
import math
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_buttress_operation as btr
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import test_removal_operation as rop
from tests.unit.design.test_supported_edge import hand_clipped, place
from tests.unit.design.test_thickness import hand_step

compose = import_geoblender("design.compose")
design_reproduce = import_geoblender("design.reproduce")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
provenance = import_geoblender("design.provenance")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
zones = import_geoblender("design.zones")

GRID = rop.GRID
SURVEY = rop.SURVEY
USER = rop.USER
OUTSIDE = "des.entity_edge_outside"
BUTTRESS_CLIPPED = "des.buttress_footprint_clipped"
BODY_CLIPPED = "des.body_footprint_clipped"
ORDER = "des.entity_quarry_order"
EDGE_STEP = "des.body_edge_step"
FILL = model.BenchSense.FILL
ZONES_LAYER = "gis_fea_coronacion_al_borde"
BODIES_LAYER = "gis_fea_cuerpos_al_borde"
POINTS_LAYER = "gis_fea_espesor_al_borde"
INNER_POINTS_LAYER = "gis_fea_espesor_interior"
ZONE = "Coronación al borde oeste"
FOOTPRINT = "Cuerpo al borde oeste"
INNER = "Cuerpo en el interior"
ZONE_BOX = (-24.0, 140.0, 30.0, 170.0)
"""La zona de coronación (local): sale 24 m por el oeste de la rejilla (12 columnas de 2 m)."""
FOOTPRINT_BOX = (-16.0, 40.0, 20.0, 70.0)
"""La huella del cuerpo (local): sale 16 m por el oeste (8 columnas)."""
INNER_BOX = (100.0, 100.0, 130.0, 130.0)
"""La huella de un cuerpo en el interior de la cantera (local): dentro del límite legal, donde las máscaras admiten el relleno."""
BUTTRESS, BODY = "Contrafuerte al borde", "Cuerpo sobre el levantamiento"
PRP = provenance.ENTITY_REPORT_TABLE


def polygon(box: tuple[float, float, float, float]) -> tuple[tuple[np.ndarray, ...], ...]:
    """La geometría de un polígono (una parte, su anillo exterior) en absolutas."""
    return ((cfx.rectangle(*box),),)


def codes(notices: Any) -> list[str]:
    return [notice.code for notice in notices]


def of(notices: Any, code: str) -> Any:
    (found,) = [notice for notice in notices if notice.code == code]
    return found


class EdgeCase(btr.ButtressCase):
    """La cantera de los acopios de 2 m con el contrafuerte, el cuerpo y la retirada registrados con sus funciones reales, la detección
    ``STK-001`` (para retirar) y tres capas: la zona de coronación y la huella del cuerpo, que salen por el oeste de la rejilla, y tres
    datos de espesor dentro de la huella."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        body_type = provenance.OPERATION_TYPES_BY_NAME[provenance.BODY].definition(ops.recompute_function, design_reproduce.reproduce_body)
        return (*super().definitions(), body_type, *provenance.BODY_FIGURES)

    @classmethod
    def calculate_body(cls, request: Any, **options: Any) -> Any:
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return ops.last(steps.body_run(cls.project, request, **options))

    @classmethod
    def calculate_removal(cls, request: Any, **options: Any) -> Any:
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return ops.last(steps.removal_run(cls.project, request, **options))

    @classmethod
    def make_body(cls, request: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» el cuerpo ``request`` (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate_body(request)
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        survey = sdata.survey(GRID)
        cls.zone_parts = polygon(ZONE_BOX)
        cls.body_parts = polygon(FOOTPRINT_BOX)
        zone = zones.polygons_cells(cls.zone_parts, GRID)
        top = float(survey[zone].max())
        cls.crown_m = 125.0 + 10.0 * math.ceil((top + 1.0 - 125.0) / 10.0)  # un ancla del perfil EXPL_10_60_6, por encima de la zona
        cls.clock.advance(minutes=1)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(
            ZONES_LAYER, "polygon", (cls.zone_parts,), (ZONE,), {"cota": (cls.crown_m,)}))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(
            BODIES_LAYER, "polygon", (cls.body_parts, polygon(INNER_BOX)), (FOOTPRINT, INNER), {}))
        for name, points in ((POINTS_LAYER, ((4.0, 60.0), (10.0, 50.0), (14.0, 66.0))),
                             (INNER_POINTS_LAYER, ((104.0, 110.0), (112.0, 120.0), (124.0, 106.0)))):
            sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(
                name, "point", tuple(((cfx.absolute([point]),),) for point in points), ("A", "B", "C"), {"espesor": (2.0, 3.0, 2.5)}))
        cls.clock.advance(minutes=1)

    def buttress(self, **changes: Any) -> Any:
        return btr.asked(BUTTRESS, feature=ZONE, crown=self.crown_m, layer=ZONES_LAYER, **changes)

    def body(self, start: str = SURVEY, *, inner: bool = False, **changes: Any) -> Any:
        """El cuerpo «sobre una base» (la superficie conocida es el levantamiento) que parte de ``start``: el de la huella que sale por el
        oeste o, con ``inner``, el de una huella en el interior de la cantera."""
        return model.BodyRequest(name=BODY, layer=BODIES_LAYER, feature=INNER if inner else FOOTPRINT,
                                 data_layer=INNER_POINTS_LAYER if inner else POINTS_LAYER, data_field="espesor", data_from="field",
                                 surface=SURVEY, sense="on_base", start=start, max_distance_m=100.0, **changes)


class SupportedEdgeProjectTest(EdgeCase):
    """RF-015-13, RF-015-14, RF-009-11, **en orden**: el contrafuerte ``BTR-001`` y el cuerpo ``BDY-001`` sobre el levantamiento de V01."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    revision: ClassVar[str]

    def test_a_the_buttress_summary_says_what_the_grid_cuts(self) -> None:
        """RF-015-13, RF-016-17 (C-1): la zona de coronación sale por el oeste de la rejilla: el resumen de «Calcular» lleva, **el primero**,
        ``des.buttress_footprint_clipped`` (las celdas de fuera y el lugar, contra la fuerza bruta), antes que el pie cortado por el límite;
        el pie no llega al borde de la rejilla (el límite legal no admite relleno junto a él): ninguna celda ni aviso de lo que llega;
        «Calcular» no escribe nada."""
        before = self.state()
        calculation = self.calculate(self.buttress())
        self.assertEqual({k: v for k, v in self.state().items() if k != "files"}, {k: v for k, v in before.items() if k != "files"})
        notices = calculation.summary.notices
        self.assertEqual(codes(notices)[:2], [BUTTRESS_CLIPPED, "des.buttress_foot_cut"])
        self.assertNotIn(OUTSIDE, codes(notices))
        self.assertFalse(calculation.outcome.outside.any())
        wanted = hand_clipped(self.zone_parts, GRID)
        self.assertIsNotNone(wanted)
        clipped = of(notices, BUTTRESS_CLIPPED)
        cells, x, y = wanted  # type: ignore[misc]
        self.assertEqual((clipped.values["cells"], clipped.values["area"], clipped.values["x"], clipped.values["y"]),
                         (cells, cells * 4.0, round(x, 2), round(y, 2)))
        self.assertEqual(clipped.values["entity"], BUTTRESS)
        self.assertEqual(calculation.outcome.clipped, wanted)
        self.assertIn("rejilla", clipped.text("es"))
        self.assertIn("grid", clipped.text("en"))
        calculation.discard()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.state(), before)

    def test_b_the_body_summary_says_the_same_for_its_footprint(self) -> None:
        """RF-015-13, RF-016-20 (C-1): la huella del cuerpo «sobre una base» sale por el oeste: ``des.body_footprint_clipped`` con las celdas
        de fuera y su lugar contra la fuerza bruta, en el resumen; sin impedir calcular."""
        calculation = self.calculate_body(self.body())
        notices = calculation.summary.notices
        self.assertEqual(codes(notices)[:1], [BODY_CLIPPED])
        cells, x, y = hand_clipped(self.body_parts, GRID)  # type: ignore[misc]
        clipped = of(notices, BODY_CLIPPED)
        self.assertEqual((clipped.values["cells"], clipped.values["area"], clipped.values["x"], clipped.values["y"]),
                         (cells, cells * 4.0, round(x, 2), round(y, 2)))
        self.assertEqual(calculation.outcome.clipped, (cells, x, y))
        self.assertGreater(calculation.outcome.volume_m3, 0.0, "no impide calcular")
        calculation.discard()

    def test_c_creating_keeps_the_notices_in_the_report_of_the_entity(self) -> None:
        """RF-015-02, RF-015-13: «Crear» los dos (no se impide) guarda los avisos nuevos en el informe de cada entidad (``des_prp_``), con el
        mismo texto que el resumen, y las cifras de siempre."""
        first, _stored = self.make(self.buttress())
        second, _stored2 = self.make_body(self.body(start="entity:BTR-001"))  # de cada superficie parte una sola entidad
        type(self).first, type(self).second = first, second
        for name, calculation, code in ((BUTTRESS, first, BUTTRESS_CLIPPED), (BODY, second, BODY_CLIPPED)):
            rows = self.query(f'SELECT quantity, note FROM "{self.locator(PRP, name)}" WHERE quantity = ?', "warning")
            found = [row[1] for row in rows]
            self.assertEqual(len([text for text in found if f'"code": "{code}"' in text]), 1, (name, code))
            self.assertGreater(calculation.outcome.volume_m3, 0.0)
        self.assertEqual(self.temporaries(), [])

    def test_d_reproducing_the_frozen_revision_repeats_them(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1``, reproducirla —**sin el proyecto**: la capa de zonas y la de huellas, las superficies,
        las máscaras y los parámetros de lo congelado— da la misma superficie, las mismas tablas (**con el informe y su aviso nuevo**) y
        las mismas cifras de los dos; reproducir no escribe nada."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe")
        for code in ("BTR-001", "BDY-001"):
            uid = self.operation_of(code)
            mine = [check for check in report.outputs if check.operation_uid == uid]
            self.assertGreaterEqual(len(mine), 3, f"{code}: {report.not_reproducible} {report.outputs}")
            self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


class QuarryOrderProjectTest(EdgeCase):
    """RF-015-14 con proyecto: el orden con la otra superficie de la cantera en el resumen del contrafuerte, del cuerpo y de la retirada."""

    def fake(self, side: str, other: np.ndarray) -> Any:
        """La cantera de mentira que ``entity_store.quarry_order`` daría para el levantamiento: la otra superficie ``other``."""
        return mock.patch.object(entity_store, "quarry_order", return_value=platform.QuarryOrder(
            "Cantera E", side, SURVEY, "des_exp_cantera_e" if side == "final" else "des_fin_cantera_e", other))

    def test_a_without_a_quarry_none_of_the_three_warns(self) -> None:
        """RF-015-14: sobre el levantamiento (no es de una cantera: no hay otra superficie con la que comparar) no se avisa del orden, y la
        orden real (``entity_store.quarry_order`` con lo preparado de cada tipo) no falla."""
        for calculation in (self.calculate(self.buttress()), self.calculate_body(self.body()),
                            self.calculate_removal(rop.asked("Retirada", "Acopio 1"))):
            self.assertNotIn(ORDER, codes(calculation.summary.notices))
            calculation.discard()
        self.assertEqual(self.temporaries(), [])

    def test_b_the_buttress_on_the_final_surface_above_the_exploitation_warns(self) -> None:
        """RF-015-14, RF-016-17: un contrafuerte sobre la superficie final de una cantera cuya explotación está 2 m por encima del
        levantamiento: avisa donde sube más de 2 m (el área, lo que más pasa y el lugar de la primera, a mano), solo en el resumen, y se
        puede crear."""
        start = self.grid_of(SURVEY)
        with self.fake("final", start + 2.0):
            calculation = self.calculate(self.buttress())
        outcome = calculation.outcome
        order = of(calculation.summary.notices, ORDER)
        excess = outcome.compose(start) - (start + 2.0)
        broken = excess > 0.001
        self.assertTrue(broken.any())
        first = tuple(int(i) for i in np.argwhere(broken)[0])
        self.assertEqual((order.values["cells"], order.values["area"], order.values["above"]),
                         (int(broken.sum()), float(broken.sum()) * 4.0, round(float(excess[broken].max()), 3)))
        self.assertEqual((order.values["x"], order.values["y"]), tuple(round(v, 2) for v in place(GRID, first)))
        self.assertEqual((order.values["quarry"], order.values["surface"], order.values["entity"]), ("Cantera E", SURVEY, BUTTRESS))
        self.assertLess(codes(calculation.summary.notices).index(ORDER), len(codes(calculation.summary.notices)))
        self.assertFalse(calculation.needs_confirmation)
        calculation.discard()

    def test_c_the_body_on_base_warns_and_under_a_roof_does_not(self) -> None:
        """RF-015-14, RF-016-20: igual con el cuerpo «sobre una base»; «bajo un techo» no cambia la superficie y no se compara."""
        start = self.grid_of(SURVEY)
        with self.fake("final", start + 1.0):
            calculation = self.calculate_body(self.body(inner=True))
        order = of(calculation.summary.notices, ORDER)
        excess = calculation.outcome.compose(start) - (start + 1.0)
        broken = excess > 0.001
        self.assertEqual((order.values["cells"], order.values["area"]), (int(broken.sum()), float(broken.sum()) * 4.0))
        self.assertEqual(order.values["entity"], BODY)
        calculation.discard()
        under = model.BodyRequest(name="Cuerpo bajo techo", layer=BODIES_LAYER, feature=INNER, data_layer=INNER_POINTS_LAYER,
                                  data_field="espesor", data_from="field", surface=SURVEY, sense="under_roof", max_distance_m=100.0)
        with self.fake("final", start - 50.0):
            roofed = self.calculate_body(under)
        self.assertNotIn(ORDER, codes(roofed.summary.notices))
        roofed.discard()

    def test_d_the_removal_on_the_exploitation_surface_lowered_below_the_final_warns(self) -> None:
        """RF-015-14, RF-016-11: retirar el Acopio 1 desde la superficie de explotación de una cantera cuya final está 1 m por debajo del
        levantamiento: avisa donde la retirada baja más de 1 m (a mano); la del lado final no baja de la explotación y no avisa."""
        start = self.grid_of(SURVEY)
        with self.fake("exploitation", start - 1.0):
            calculation = self.calculate_removal(rop.asked("Retirada", "Acopio 1"))
        outcome = calculation.outcome
        whole = start.copy()
        whole[outcome.window] = outcome.surface
        deficit = (start - 1.0) - whole
        broken = deficit > 0.001
        self.assertTrue(broken.any())
        order = of(calculation.summary.notices, ORDER)
        self.assertEqual((order.values["cells"], order.values["area"], order.values["above"]),
                         (int(broken.sum()), float(broken.sum()) * 4.0, round(float(deficit[broken].max()), 3)))
        self.assertEqual(order.values["entity"], "Retirada")
        calculation.discard()
        with self.fake("final", start + 5.0):
            quiet = self.calculate_removal(rop.asked("Retirada", "Acopio 1"))
        self.assertNotIn(ORDER, codes(quiet.summary.notices))
        quiet.discard()
        self.assertEqual(self.temporaries(), [])

    def test_e_the_order_is_not_in_the_report(self) -> None:
        """RF-015-02: el aviso del orden depende de algo que la operación no consume (la otra superficie de la cantera) y el informe se
        reproduce sin el proyecto: **no** va a ``des_prp_`` aunque se cree con él en el resumen."""
        start = self.grid_of(SURVEY)
        with self.fake("final", start + 2.0):
            calculation = self.calculate(self.buttress())
        self.assertIn(ORDER, codes(calculation.summary.notices))
        calculation.create(decided_by=USER)
        rows = self.query(f'SELECT note FROM "{self.locator(PRP, BUTTRESS)}" WHERE quantity = ?', "warning")
        self.assertFalse([row for row in rows if ORDER in row[0]])
        self.assertTrue([row for row in rows if BUTTRESS_CLIPPED in row[0]], "el informe sí lleva lo que no depende de la cantera")


class BodyEdgeStepProjectTest(EdgeCase):
    """RF-015-13, RF-016-20, RF-009-11, **en orden**: el cuerpo «sobre una base» del interior de la cantera (la huella de 30 × 30 m dentro del
    límite legal, donde las máscaras admiten el relleno, con tres datos de espesor de 2 a 3 m y sin «cero en el borde») sobre el levantamiento:
    termina en un escalón en su borde."""

    calculation: ClassVar[Any]
    revision: ClassVar[str]

    def by_hand(self, calculation: Any) -> tuple[float, tuple[int, int]]:
        """El mayor escalón del borde a mano (un bucle de Python sobre lo que sale del cálculo): ``(escalón, (fila, columna) de la rejilla
        entera)`` de la primera celda del borde de la huella que más sube la superficie donde se admite el relleno."""
        outcome = calculation.outcome
        rows, cols = outcome.window
        start = self.grid_of(SURVEY)[outcome.window]
        fill = compose.admitted(self.masks_v1, FILL)[outcome.window]
        found = hand_step(outcome.footprint, start, start, fill, outcome.thickness)
        self.assertIsNotNone(found)
        assert found is not None
        step, (row, col) = found
        return step, (rows.start + row, cols.start + col)

    def test_a_the_summary_tells_the_step_as_an_informative_line(self) -> None:
        """RF-015-13, RF-016-20: el resumen de «Calcular» lleva **un** renglón del escalón (el cuerpo, el mayor escalón al centímetro y el
        lugar de la primera celda del borde con él, a mano), que es **una nota**: sale en las líneas del resumen y **no** en sus avisos (no
        va en ámbar), en los dos idiomas; «Calcular» no escribe nada y no impide calcular."""
        before = self.state()
        calculation = self.calculate_body(self.body(inner=True))
        step, cell = self.by_hand(calculation)
        self.assertGreater(step, 1.0, "el cuerpo termina en un escalón de varios metros")
        self.assertEqual(codes(calculation.summary.notices).count(EDGE_STEP), 1)
        found = of(calculation.summary.notices, EDGE_STEP)
        x, y = place(GRID, cell)
        self.assertEqual(found.severity, "note")
        self.assertEqual(dict(found.values), {"entity": BODY, "step": round(step, 2), "x": round(x, 2), "y": round(y, 2)})
        for language in ("es", "en"):
            text = found.text(language)
            self.assertNotIn("{", text)
            self.assertIn(text, calculation.summary.lines(language))
            self.assertNotIn(text, calculation.summary.warnings(language), "un renglón informativo no es un aviso (no va en ámbar)")
        self.assertIn("escalón de hasta", found.text("es"))
        self.assertIn("step of up to", found.text("en"))
        self.assertGreater(calculation.outcome.volume_m3, 0.0, "no impide calcular")
        calculation.discard()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.state(), before)

    def test_b_creating_it_keeps_the_line_in_the_report_of_the_entity(self) -> None:
        """RF-015-02, RF-016-20: «Crear» (no se impide) guarda el renglón en el informe de la entidad (``des_prp_``) como **una nota** (no
        como un aviso), con el mismo escalón y el mismo lugar que el resumen."""
        calculation, _stored = self.make_body(self.body(inner=True))
        type(self).calculation = calculation
        found = of(calculation.summary.notices, EDGE_STEP)
        notes = [json.loads(row[1]) for row in self.query(f'SELECT quantity, note FROM "{self.locator(PRP, BODY)}" WHERE quantity = ?', "note")]
        self.assertEqual([item for item in notes if item["code"] == EDGE_STEP], [{"code": EDGE_STEP, "values": dict(found.values)}])
        warnings = [row[1] for row in self.query(f'SELECT quantity, note FROM "{self.locator(PRP, BODY)}" WHERE quantity = ?', "warning")]
        self.assertFalse([text for text in warnings if EDGE_STEP in text])
        self.assertEqual(self.temporaries(), [])

    def test_c_reproducing_the_frozen_revision_repeats_it(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1``, reproducirla —sin el proyecto— da el mismo informe (**con el renglón**), la misma
        superficie y las mismas cifras del cuerpo; reproducir no escribe nada."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe")
        mine = [check for check in report.outputs if check.operation_uid == self.operation_of("BDY-001")]
        self.assertGreaterEqual(len(mine), 3, f"{report.not_reproducible} {report.outputs}")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


if __name__ == "__main__":
    import unittest

    unittest.main()
