# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» la pista con el proyecto: la ``Calculation``, las dos confirmaciones y el resumen (spec 017, T20b; HU-017-1 y HU-017-2; RF-017-17, RF-017-22, RF-017-12, RF-017-05, RF-017-23; RF-015-03, RF-015-13,
RF-015-29; RNF-017-06 y RNF-017-07; plan 017 §5.3.2, §5.8 H-10), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_operation.py``.

``steps.road_run`` prepara (T19), calcula (T20), arma el resumen y deja la ``Calculation`` de ``des.road``: lo calculado y **todavía sin registrar**.

- **«Calcular» no escribe** (:class:`CalculateTest`, RF-015-03): ni la base de datos, ni las operaciones, los datos, los parámetros, las cifras o los ficheros (ni un temporal: la superficie entera la escribe «Crear», T21); el
  resumen lleva las cifras, la holgura del pasillo, la magnitud sin revisión anterior y lo que quedará obsoleto; descartarla no cambia nada.
- **Cerrar los pasos a mitad no deja nada** (RF-015-29), y **un rechazo** —sin ruta por agotar su presupuesto (RF-017-12), la partida o un parámetro que falta (RF-015-08)— sale al avanzar, con la capa, la pista, el campo y el
  valor, sin escribir nada.
- **La pendiente media por encima de pm** (:class:`ConfirmationsOnTheCalculationTest`, RF-017-17, D-6, la «opción A15»: 10,5 % de media): la ``Calculation`` lo dice, pide la confirmación con un motivo y **sin ella no se crea**.
- **La calzada que no queda en su rasante** (RF-017-22): con «Sin corte» de las máscaras de V01 sobre la calzada, el resumen nombra la restricción y pide la confirmación; sin ella no se crea.
- **Sobre una cantera de la 014** (:class:`QuarryCalculateTest`, RF-017-05): el aviso de la partida «no llega al fondo» llega al resumen, el primero, y los otros diseños se leen en la ventana de trabajo.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.milestone_road_prepare import QuarryStartCase
from tests.unit.design.test_road_prepare import BY, GRID, PrepareCase, request

design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
report = import_geoblender("design.report")
road_model = import_geoblender("design.road_model")
road_profiles = import_geoblender("design.road_profiles")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")

A15 = "gis_dtm_a15"
"""El terreno de la «opción A15»: un plano del 10,5 % a lo largo del eje."""
A15_PROFILE = "acceso_a15"
"""Su perfil: pd = 12 % y la pm = 10 % de referencia (el de ``rd.PROFILE`` salvo pd)."""
NO_CUT_LAYER = "gis_fea_pistas_sincorte"
NO_CUT_AXIS = ((62.0, 300.0), (98.0, 300.0))
"""El eje (local) de 36 m que cruza la zona «Sin corte» de V01 (de (60, 280) a (100, 320)): su calzada de 10,5 m cae entera en ella."""


def steps_of(work: Any) -> list[Any]:
    """Todos los pasos de ``work`` (hasta el último, que lleva el cálculo)."""
    return list(work)


class CalculateCase(PrepareCase):
    """La copia del proyecto de las pistas (rejilla de 2 m) con las máscaras de V01, el perfil de referencia y, además, el terreno de la «opción A15» con su perfil y una capa con el eje que cruza «Sin corte»."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        x, _y = rd.local_centers(GRID)
        res_fixtures.write_grids(cls.project, [("a15", gis.Raster(GRID, rd.RAMP_Z0_M + 0.105 * x, rd.CRS, rd.VERTICAL))], message="Terreno de la «opción A15» de la T20b")
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la T20b", version=cls.v1.code)
        values = {param: getattr(rd.profile_with(max_gradient_pct=12.0), "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name="ACCESO_A15", values=values),), declared)
        line = rd.absolute(NO_CUT_AXIS, GRID)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(NO_CUT_LAYER, "line", (((line,),),), ("Eje sin corte",), {}))
        cls.clock.advance(minutes=1)

    def calculate(self, asked: Any, **options: Any) -> Any:
        """«Calcula» ``asked`` en V01 con sus máscaras: la ``Calculation`` (el último paso la lleva; nada registrado)."""
        options.setdefault("masks", self.masks_v1)
        options.setdefault("version", self.v1.uid)
        found = None
        for step in steps.road_run(self.project, asked, **options):
            found = step.result
        assert found is not None
        return found

    def refused(self, asked: Any, expected: str, **options: Any) -> Any:
        """«Calcular» ``asked`` se rechaza con ``expected`` y **no escribe nada** (ni deja un temporal); devuelve el error, cuyo texto no deja ningún marcador sin llenar en ninguno de los dos idiomas."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate(asked, **options)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        return error


class CalculateTest(CalculateCase):
    """RF-015-03, RF-015-29, RF-017-12, RF-017-23, H-10: «Calcular» la rampa (E1 pequeña: de (100, 200) a (300, 200) a 4 %), sin escribir nada."""

    def test_a_calculating_writes_nothing_and_leaves_the_summary_with_its_figures(self) -> None:
        """RF-015-03, RF-017-23, H-10: «Calcular» la rampa deja la pista ``RDW-001`` preparada, el resultado con sus veintitrés cifras y el resumen con la longitud (200 m), las pendientes (4 %), la holgura del
        pasillo con su nota, la magnitud sin revisión anterior (``des.magnitude_no_reference`` con el nombre de la pista) y nada que quede obsoleto; **no escribe nada** (la base de datos, las operaciones, los datos,
        los parámetros, las cifras y los ficheros, ni un temporal); descartarla no cambia nada y la cierra."""
        asked = request()
        before = self.state()
        calculation = self.calculate(asked)
        self.assertEqual(self.state(), before, "calcular no escribe")
        self.assertTrue(calculation.open)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version, calculation.entity.code), (provenance.ROAD, "Pista de la rampa", "V01", "RDW-001"))
        self.assertIsInstance(calculation.outcome, road_model.RoadOutcome)
        self.assertIsInstance(calculation.entity, road_store.PreparedRoad)
        self.assertEqual(calculation.figures, calculation.outcome.figures)
        self.assertGreaterEqual(len(calculation.figures), 20)  # las veintitrés menos las que no existen (sin curvas, el radio mínimo; sin pared, su altura)
        self.assertEqual(calculation.specs, (), "la superficie y las tablas las prepara «Crear»")
        summary = calculation.summary
        self.assertIsInstance(summary, preview.RoadSummary)
        self.assertEqual((summary.name, summary.code, summary.version, summary.mode, summary.profile), ("Pista de la rampa", "RDW-001", "V01", "trace", "pista_principal"))
        self.assertEqual(summary.figures, calculation.outcome.figures)
        self.assertAlmostEqual(summary.length_m, 200.0, delta=1e-6)
        self.assertAlmostEqual(summary.gradient_mean_pct, 4.0, delta=1e-9)
        self.assertEqual(summary.margin_m, rd.ROUTE.margin_m)
        self.assertEqual(summary.notices[0].code, "des.road_route_margin")
        self.assertEqual(summary.obsolete, ())
        magnitude = [notice for notice in summary.notices if notice.code.startswith("des.magnitude")]
        self.assertEqual([notice.code for notice in magnitude], ["des.magnitude_no_reference"])
        self.assertEqual(magnitude[0].values["operation"], "Pista de la rampa")
        self.assertFalse(calculation.needs_mean_confirmation or calculation.needs_carriageway_confirmation)
        self.assertTrue(calculation.message.startswith("Pista «Pista de la rampa» (RDW-001) calculada: 200"))
        for language in ("es", "en"):
            self.assertTrue(all("{" not in line for line in calculation.lines(language)))
        self.assertEqual(calculation.warnings("es"), tuple(notice.text("es") for notice in calculation.notices if notice.severity == "warning"))
        calculation.discard()
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), before, "descartar no cambia nada")

    def test_b_closing_the_steps_halfway_leaves_nothing(self) -> None:
        """RF-015-29, RNF-017-06: con el presupuesto mínimo son muchos pasos y cerrar el generador a mitad (Esc), en la preparación, en la red 2D o antes del último paso, no deja nada; el último paso es el que
        lleva la ``Calculation`` y los anteriores, no."""
        before = self.state()
        every = steps_of(steps.road_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1, budget_s=1e-9))
        self.assertGreater(len(every), 20, "por pasos")
        self.assertTrue(all(step.result is None for step in every[:-1]))
        self.assertIsInstance(every[-1].result, steps.Calculation)
        every[-1].result.discard()
        self.assertEqual(self.state(), before)
        for cut in (2, len(every) // 3, len(every) - 1):
            with self.subTest(closed_after=cut):
                work = steps.road_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1, budget_s=1e-9)
                for _step in range(cut):
                    next(work)
                work.close()
                self.assertEqual(self.state(), before)

    def test_c_a_refusal_comes_out_advancing_naming_the_layer_the_road_the_field_and_the_value(self) -> None:
        """RF-017-12, RF-015-08, RF-017-04: la búsqueda que agota su presupuesto de estados (10) es ``des.road_budget``, **que no es «no hay ruta»** (los estados explorados y qué hacer); un perfil que no
        existe, ``des.road_profile_unknown``: las dos **sin escribir nada** ni dejar un temporal."""
        error = self.refused(request(search_budget=10), "des.road_budget")
        self.assertEqual((error.values["budget"], error.values["field"]), (10, design_params.entity_key("RDW-001", "search_budget")))
        self.assertIn("presupuesto", error.text)
        self.assertIn(rd.POINTS_LAYER, error.obj)
        self.refused(request(profile="no_existe"), "des.road_profile_unknown")

    def test_e_the_magnitude_is_compared_with_the_previous_revision_of_the_project(self) -> None:
        """RF-015-13, RF-013-30: ``road_run`` lee del proyecto con qué se compara el desmonte y el terraplén (``road_store.road_previous`` de la entidad ``RDW-001``) y lo pasa al cálculo: con una revisión
        anterior que movió 1 m³, la pista del 20 % transversal pasa de 1,5 veces el umbral (``des.magnitude_cut`` y ``des.magnitude_fill``) y la nota de «sin revisión anterior» desaparece."""
        previous = report.Previous("Pista de la rampa", "V01.r1", 1.0, 1.0)
        with mock.patch.object(road_store, "road_previous", return_value=previous) as read:
            calculation = self.calculate(request("Pista de la rampa", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("rampa_lateral")))
        self.assertEqual(read.call_args.args[2], "RDW-001")
        codes = [notice.code for notice in calculation.notices if notice.code.startswith("des.magnitude")]
        self.assertEqual(codes, ["des.magnitude_cut", "des.magnitude_fill"])
        calculation.discard()

    def test_d_without_other_designs_the_road_notices_none(self) -> None:
        """RF-017-05 (b): sin otros diseños de la versión que no partan de la partida (V01 solo tiene el terreno), la pista no avisa de ninguno y no hay nada que registrar como entrada."""
        calculation = self.calculate(request())
        self.assertEqual((calculation.entity.others, calculation.outcome.other_designs), ((), ()))
        self.assertNotIn("des.road_other_design_differs", [notice.code for notice in calculation.notices])
        calculation.discard()


class ConfirmationsOnTheCalculationTest(CalculateCase):
    """RF-017-17, RF-017-22, D-6, N-15: las dos confirmaciones sobre la ``Calculation``: se piden, se dan y, sin ellas, la pista no se crea (y **nada se escribe**)."""

    def a15(self) -> Any:
        return self.calculate(request("Pista A15", mode="on_axis", layer=rd.AXES_LAYER, surface=A15, profile=A15_PROFILE))

    def test_a_the_option_a15_mean_over_pm_asks_for_the_confirmation_and_a_reason(self) -> None:
        """RF-017-17, D-6: la media de 10,5 % frente al 10 % del perfil: la ``Calculation`` y el resumen piden la confirmación y dicen la media, el límite y los tramos (``des.road_mean_gradient``); sin ella,
        «Crear» se rechaza con ``des.road_mean_unconfirmed`` **antes de escribir nada y sin cerrar el cálculo**; confirmada sin motivo, ``des.road_mean_reason``; con el motivo se puede crear (no se bloquea)."""
        calculation = self.a15()
        before = self.state()
        self.assertAlmostEqual(calculation.summary.gradient_mean_pct, 10.5, delta=1e-6)
        self.assertTrue(calculation.needs_mean_confirmation and calculation.summary.needs_mean_confirmation)
        self.assertEqual(calculation.summary.mean_limit_pct, 10.0)
        self.assertFalse(calculation.needs_carriageway_confirmation)
        mean = [notice for notice in calculation.summary.notices if notice.code == "des.road_mean_gradient"]
        self.assertEqual(len(mean), 1)
        self.assertIn("confirmación expresa", mean[0].text("es"))
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertTrue(calculation.open, "el cálculo sigue abierto: se confirma y se vuelve a crear")
        self.assertEqual(self.state(), before, "no escribe nada")
        calculation.confirm_road(mean=True)
        self.assertFalse(calculation.needs_mean_confirmation)
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.road_mean_reason")
        self.assertEqual(self.state(), before)
        calculation.confirm_road(mean=True, reason="Opción A15 de la propiedad (N-15)")
        self.assertIsNone(calculation.ensure_road_creatable())
        self.assertEqual(calculation.road_confirmed, (True, False, "Opción A15 de la propiedad (N-15)"))
        calculation.discard()
        self.assertEqual(self.state(), before)

    def test_b_the_carriageway_off_its_level_names_the_restriction_and_asks_for_the_confirmation(self) -> None:
        """RF-017-22, RF-015-13: con «Sin corte» de las máscaras de V01 sobre la calzada (la rampa del 20 % transversal necesita corte al norte), el resumen nombra la restricción («Sin corte (sin_corte)»), el
        área, la diferencia máxima y el lugar, dice lo que no se mueve por ella y pide la confirmación: sin ella «Crear» se rechaza (``des.road_carriageway_unconfirmed``) sin escribir nada."""
        calculation = self.calculate(request("Pista sin corte", mode="on_axis", layer=NO_CUT_LAYER, surface=rd.dataset_of("rampa_lateral"), feature="Eje sin corte"))
        before = self.state()
        summary = calculation.summary
        self.assertTrue(calculation.needs_carriageway_confirmation and summary.needs_carriageway_confirmation)
        self.assertFalse(calculation.needs_mean_confirmation)
        (group, *_rest) = calculation.outcome.off_level
        named = [notice for notice in summary.notices if notice.code == "des.road_carriageway_masks"]
        self.assertGreaterEqual(len(named), 1)
        self.assertEqual(named[0].values["blocker"], "Sin corte (sin_corte)")
        self.assertEqual((named[0].values["area"], named[0].values["x"]), (group.area_m2, round(group.x, 2)))
        held = [notice for notice in summary.notices if notice.code == "des.entity_held_constraint"]
        self.assertEqual([notice.values["constraint"] for notice in held], ["Sin corte (sin_corte)"])
        self.assertEqual(summary.carriageway_area_m2, sum(item.area_m2 for item in calculation.outcome.off_level))
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.road_carriageway_unconfirmed")
        self.assertTrue(calculation.open)
        self.assertEqual(self.state(), before)
        calculation.confirm_road(carriageway=True)
        self.assertFalse(calculation.needs_carriageway_confirmation)
        self.assertIsNone(calculation.ensure_road_creatable())
        calculation.discard()

    def test_c_a_clean_road_has_nothing_to_confirm_and_confirming_more_does_not_hinder(self) -> None:
        """RF-017-17, RF-017-22: la rampa de 4 % de media sin calzada fuera de su rasante no pide nada (``ensure_road_creatable`` no rechaza) y confirmar de más no estorba; la confirmación se sustituye
        por la siguiente."""
        calculation = self.calculate(request())
        self.assertEqual(calculation.road_confirmed, (False, False, None))
        self.assertIsNone(calculation.ensure_road_creatable())
        calculation.confirm_road(mean=True, carriageway=True, reason="De más")
        self.assertEqual(calculation.road_confirmed, (True, True, "De más"))
        self.assertIsNone(calculation.ensure_road_creatable())
        calculation.confirm_road()
        self.assertEqual(calculation.road_confirmed, (False, False, None))
        calculation.discard()


class QuarryCalculateTest(QuarryStartCase):
    """RF-017-05, RF-015-14, D-3: «Calcular» sobre las superficies de una cantera de la 014 de la versión (la de explotación de «Cantera» y la final, 20 m más arriba)."""

    def road(self, surface: str, **changes: Any) -> Any:
        """La pista «sobre un eje» del eje de 200 m sobre la superficie ``surface`` de la cantera."""
        return request("Pista de la cantera", mode="on_axis", layer=rd.AXES_LAYER, surface=surface, **changes)

    def calculate(self, asked: Any) -> Any:
        found = None
        for step in steps.road_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1):
            found = step.result
        assert found is not None
        return found

    def test_a_road_on_the_restored_final_warns_in_the_summary_that_it_does_not_reach_the_bottom(self) -> None:
        """RF-017-05 (a): el aviso de la partida que arma la preparación («no llega al fondo», con las cotas mínimas sobre la final y sobre la de explotación) llega al resumen, **el primero**, sin impedir
        calcularla ni crearla; sobre la de explotación, ninguno. «Calcular» no escribe nada."""
        before = self.state()
        final = self.calculate(self.road("des_fin_cantera"))
        first = final.summary.notices[0]
        self.assertEqual((first.code, first.values["surface"]), ("des.road_start_is_final", "des_fin_cantera"))
        self.assertAlmostEqual(first.values["z_final"] - first.values["z_pit"], 20.0, places=9)
        self.assertEqual(final.notices[0], first)
        final.discard()
        pit = self.calculate(self.road("des_exp_cantera"))
        self.assertNotIn("des.road_start_is_final", [notice.code for notice in pit.summary.notices])
        pit.discard()
        self.assertEqual(self.state(), before, "calcular no escribe")

    def test_the_other_designs_are_read_in_the_working_window(self) -> None:
        """RF-017-05 (b), RF-015-03: los otros diseños de la versión (los de «Otra», que parten de otra superficie y difieren de la partida en 1 m, más que el espesor mínimo) se leen **en la ventana de
        trabajo** de la pista y dan su aviso con el área, la diferencia y el lugar; el resultado dice cuáles (lo que la T21 registra como entradas). Las superficies de la prueba las escribe una operación
        que no es ``des.quarry``: el orden con la otra superficie de la cantera (RF-015-14) no se comprueba aquí (es de ``test_road_operation``)."""
        calculation = self.calculate(self.road("des_exp_cantera"))
        other = [notice for notice in calculation.summary.notices if notice.code == "des.road_other_design_differs"]
        self.assertEqual(sorted(notice.values["other"] for notice in other), ["des_exp_otra", "des_fin_otra"])
        self.assertAlmostEqual(other[0].values["difference"], 1.0, places=9)
        self.assertEqual(calculation.outcome.other_designs, ("des_exp_otra", "des_fin_otra"))
        self.assertEqual(calculation.entity.others, ("des_exp_otra", "des_fin_otra"))
        calculation.discard()


if __name__ == "__main__":
    unittest.main()
