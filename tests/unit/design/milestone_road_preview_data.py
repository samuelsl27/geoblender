# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de la pista: lo que se dibuja, sin ``gpu`` (spec 017, T28; HU-017-1; RF-017-26, RF-015-26, RF-017-09, RF-017-15, RF-017-17, RNF-017-06; plan 017 §5.5 y §7.3; comprobación manual M5).

**Spec 017, T34b: pasó del «verde» al paso «hito»** (RNF-017-09: el A/B de ``check.py`` con y sin las pruebas de la 017 daba +3,7 s y esta clase suma 1,4 s con un proyecto por prueba; lo que el «verde»
conserva de la vista previa es ``tests/blender/test_road_preview.py`` y los de dominio de ``test_road_operation``).

``design.preview.road_preview_steps`` prepara, por pasos y **solo leyendo**, los datos de lo que dibuja ``bl.draw.entity`` (los lotes se arman allí y se prueban en
``tests/blender/test_road_preview.py``):

- **Antes de calcular** (:class:`RoadPreviewTest`, de la a a la h y la m): el origen y el destino de la pista, el **pasillo** de la ruta (RF-017-09: los nodos de la red 2D cuya longitud mínima desde el origen
  más la que les queda hasta el destino no pasa de la más corta más la holgura; la misma de ``road_net`` que usa el cálculo) y, en un destino por cota, la zona; la línea que sigue un eje.
  Lo que rechazaría «Calcular» es ``RoadPreview.refusal``, y las máscaras sin compilar o sin estar al día, el aviso; **no escribe nada** y cerrar los pasos a mitad no deja nada.
- **Tras calcular** (:class:`RoadPreviewTest`, de la i a la l): lo calculado de la ``Calculation`` (``RoadAsk``): el eje con sus curvas, la rasante por tramos coloreados por pd y pm, los bordes de la
  sección, el origen y el destino que alcanzó.
- **Los tramos de la rasante** (:class:`GradientStretchTest`) y **los bordes de la sección** (:class:`SectionEdgesTest`): funciones puras, sin proyecto.

Sobre el proyecto de las pistas (``tests.support.road_data``, rejilla de 2 m, 200 × 200 celdas) con el perfil de referencia de IMGA (**solo de las pruebas**, D-2) en V01. Lo que cambia el proyecto
(una pista creada, lo que se le apoya) es de ``milestone_road_preview``.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_prepare import BY, GRID, RAMP, PrepareCase, absolute, request

design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
road_net = import_geoblender("design.road_net")
road_profiles = import_geoblender("design.road_profiles")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")

LOW_MEAN = "pm_baja"
"""Un perfil de la prueba cuya pendiente media máxima (3 %) está por debajo de la de la rampa (4 %): sus tramos van «por encima de pm»."""
EPS = 1e-9


def last(work: Any) -> Any:
    """Lo que lleva el último ``Progress`` de ``work`` que lo trae."""
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


def area_of(rings: tuple[np.ndarray, ...]) -> float:
    """El área neta (m²) de unos anillos: el exterior antihorario suma y los huecos, horarios, restan (la fórmula del cordón)."""
    total = 0.0
    for ring in rings:
        points = np.asarray(ring, dtype=np.float64)
        if not np.array_equal(points[0], points[-1]):
            points = np.vstack([points, points[:1]])
        x, y = points[:, 0], points[:, 1]
        total += 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
    return total


# --- Los tramos de la rasante (RF-017-26, RF-017-15, RF-017-17) --------------------------------------------------------------------------------


class GradientStretchTest(unittest.TestCase):
    """RF-017-26, RF-017-17: la rasante se parte en tramos y cada uno lleva el estado que dicen pd y pm."""

    @staticmethod
    def levels(stations: np.ndarray, gradients: list[tuple[float, float]]) -> np.ndarray:
        """La rasante en ``stations`` (m) desde la cota 0 con la pendiente que dice cada ``(hasta la abscisa, pendiente en tanto por uno)``, con signo."""
        slope = np.zeros(len(stations) - 1)
        start = 0.0
        for until, gradient in gradients:
            slope[(stations[:-1] >= start) & (stations[:-1] < until)] = gradient
            start = until
        return np.concatenate([[0.0], np.cumsum(slope * np.diff(stations))])

    def test_a_each_stretch_is_colored_by_pd_and_pm(self) -> None:
        """RF-017-26, RF-017-17: una rasante de 300 m con tres tramos de 100 m al 4 %, al 9 % y al 12 % con pd = 10 % y pm = 8 % se parte en tres tramos de esos límites: el primero «dentro» (≤ pm), el
        segundo «por encima de pm» y el tercero «por encima de pd»; cada uno con su pendiente media (Σ|Δcota| / S, D-7) y sus cotas, a ≤ 10⁻⁹."""
        stations = np.arange(0.0, 301.0)
        z = self.levels(stations, [(100.0, 0.04), (200.0, 0.09), (300.0, 0.12)])
        found = preview.gradient_stretches(stations, z, 10.0, 8.0, min_length_m=100.0)
        self.assertEqual([item.status for item in found], [preview.GradientStatus.WITHIN, preview.GradientStatus.ABOVE_MEAN, preview.GradientStatus.ABOVE_DESIGN])
        self.assertEqual([(item.first, item.last) for item in found], [(0, 100), (100, 200), (200, 300)])
        for item, slope in zip(found, (4.0, 9.0, 12.0), strict=True):
            self.assertAlmostEqual(item.gradient_pct, slope, delta=EPS)
            self.assertAlmostEqual(item.max_gradient_pct, slope, delta=EPS)
        self.assertEqual((found[0].start_m, found[0].end_m, found[2].end_m), (0.0, 100.0, 300.0))
        self.assertAlmostEqual(found[1].start_level_m, 4.0, delta=EPS)
        self.assertAlmostEqual(found[1].end_level_m, 13.0, delta=EPS)
        self.assertAlmostEqual(found[1].length_m, 100.0, delta=EPS)

    def test_b_one_steep_step_marks_its_whole_stretch_above_the_design_gradient(self) -> None:
        """RF-017-26, RF-017-16: pd manda sobre el paso, no sobre la media del tramo: un solo paso de 1 m al 15 % dentro de un tramo de 100 m al 2 % lo deja «por encima de pd» aunque su media (2,13 %)
        quede por debajo de pm; el mayor paso se dice."""
        stations = np.arange(0.0, 101.0)
        z = 0.02 * stations
        z[51:] += 0.13  # el paso de 50 a 51: 2 % + 13 % = 15 %
        (found,) = preview.gradient_stretches(stations, z, 10.0, 8.0, min_length_m=100.0)
        self.assertIs(found.status, preview.GradientStatus.ABOVE_DESIGN)
        self.assertAlmostEqual(found.max_gradient_pct, 15.0, delta=1e-7)
        self.assertAlmostEqual(found.gradient_pct, 2.13, delta=1e-7)  # 2 m de desnivel de la rampa del 2 % más los 0,13 m del paso
        self.assertLess(found.gradient_pct, 8.0)

    def test_c_the_stretches_are_contiguous_capped_and_descending_counts_the_same(self) -> None:
        """RF-017-26: los tramos cubren el eje entero sin huecos (cada uno empieza en la estación en que acaba el anterior), no pasan de ``max_count`` aunque el eje sea largo y bajar cuesta lo mismo que
        subir (la pendiente es el valor absoluto)."""
        stations = np.arange(0.0, 5001.0)
        z = 100.0 - 0.05 * stations
        found = preview.gradient_stretches(stations, z, 10.0, 8.0, min_length_m=50.0, max_count=40)
        self.assertEqual(len(found), 40)
        self.assertEqual((found[0].first, found[-1].last), (0, 5000))
        for before, after in zip(found, found[1:], strict=False):
            self.assertEqual(before.last, after.first)
        self.assertTrue(all(item.status is preview.GradientStatus.WITHIN and abs(item.gradient_pct - 5.0) < EPS for item in found))
        self.assertLess(found[0].end_level_m, found[0].start_level_m, "bajando: la cota final es menor, la pendiente no tiene signo")

    def test_d_a_short_axis_is_one_stretch_and_the_limits_are_inclusive(self) -> None:
        """RF-017-26, RF-017-17: un eje más corto que el tramo mínimo es un solo tramo; una pendiente igual a pm (o a pd) **no** pasa de él (≤, con el margen de 10⁻⁹ de la rasante)."""
        stations = np.arange(0.0, 21.0)
        (only,) = preview.gradient_stretches(stations, 0.08 * stations, 10.0, 8.0, min_length_m=50.0)
        self.assertEqual((only.first, only.last, only.status), (0, 20, preview.GradientStatus.WITHIN))
        (at_pd,) = preview.gradient_stretches(stations, 0.10 * stations, 10.0, 12.0, min_length_m=50.0)
        self.assertIs(at_pd.status, preview.GradientStatus.WITHIN)
        (above,) = preview.gradient_stretches(stations, 0.1001 * stations, 10.0, 12.0, min_length_m=50.0)
        self.assertIs(above.status, preview.GradientStatus.ABOVE_DESIGN)

    def test_e_what_is_not_a_rasante_is_a_program_error(self) -> None:
        """Una rasante de otra forma que sus estaciones, con menos de dos estaciones o con un límite que no es positivo es un error del programa (``ValueError``)."""
        stations = np.arange(0.0, 11.0)
        for bad in ((stations, stations[:-1], 10.0, 8.0), (stations[:1], stations[:1], 10.0, 8.0), (stations, stations, 0.0, 8.0), (stations, stations, 10.0, -1.0)):
            with self.subTest(bad=[getattr(item, "shape", item) for item in bad]), self.assertRaises(ValueError):
                preview.gradient_stretches(*bad)


# --- Los bordes de la sección (RF-017-26) ------------------------------------------------------------------------------------------------------


class SectionEdgesTest(unittest.TestCase):
    """RF-017-26, RF-017-04: la anchura de la sección se dibuja como sus dos bordes, a su semianchura del eje a cada lado."""

    def test_a_a_straight_axis_has_its_edges_at_half_the_width_on_each_side(self) -> None:
        """Un eje hacia el este: el borde izquierdo (a la izquierda del sentido de la marcha) a +y y el derecho a −y, a la semianchura, en todas las estaciones (también en las dos de los extremos)."""
        points = np.column_stack([np.arange(0.0, 11.0), np.full(11, 50.0)])
        left, right = preview.section_edges(points, 5.75)
        np.testing.assert_allclose(left, np.column_stack([points[:, 0], np.full(11, 55.75)]), atol=EPS)
        np.testing.assert_allclose(right, np.column_stack([points[:, 0], np.full(11, 44.25)]), atol=EPS)

    def test_b_on_a_curve_the_edges_are_the_concentric_arcs(self) -> None:
        """Un arco de 30 m de radio (sentido horario: el centro queda a la derecha) con estaciones cada metro: el borde derecho está a ``R − h`` del centro y el izquierdo a ``R + h`` (con el error
        de las cuerdas de un metro, ≤ 1 mm)."""
        radius, half = 30.0, 5.75
        angle = np.arange(0.0, 60.0) / radius
        points = np.column_stack([radius * np.sin(angle), radius * np.cos(angle) - radius])  # el centro en (0, −R): hacia el este, girando a la derecha
        centre = np.array([0.0, -radius])
        left, right = preview.section_edges(points, half)
        self.assertLess(float(np.abs(np.hypot(*(left - centre).T) - (radius + half)).max()), 1e-3)
        self.assertLess(float(np.abs(np.hypot(*(right - centre).T) - (radius - half)).max()), 1e-3)

    def test_c_a_repeated_point_or_a_single_one_does_not_divide_by_zero(self) -> None:
        """Un eje con dos estaciones iguales no da NaN (la dirección es la del tramo vecino) y uno de menos de dos puntos es un error del programa."""
        points = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
        left, _right = preview.section_edges(points, 2.0)
        self.assertTrue(bool(np.isfinite(left).all()))
        with self.assertRaises(ValueError):
            preview.section_edges(points[:1], 2.0)


# --- Antes de calcular y tras calcular, con el proyecto ---------------------------------------------------------------------------------------


class RoadPreviewTest(PrepareCase):
    """RF-017-26, RF-017-09, RF-015-26, RNF-017-06: lo que se dibuja **antes de calcular** y **tras calcular**, sin escribir nada. Una copia del proyecto de las pistas con las máscaras de V01 y el perfil de
    referencia, un perfil más cuya pendiente media máxima (3 %) está por debajo de la de la rampa y la rampa **calculada** una vez (``Calculation``: nada registrado)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la T28", version=cls.v1.code)
        values = {param: getattr(rd.profile_with(max_mean_gradient_pct=3.0), "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name=LOW_MEAN.upper(), values=values),), declared)
        cls.asked = request()
        cls.calculation = last(steps.road_run(cls.project, cls.asked, version=cls.v1.uid, masks=cls.masks_v1))
        cls.addClassCleanup(cls.calculation.discard)

    def preview_of(self, ask: Any, version: Any = None, **options: Any) -> Any:
        """La vista previa de ``ask`` en V01 (o ``version``), llevada hasta el final."""
        found = last(preview.road_preview_steps(self.project, ask, (version or self.v1).uid, **options))
        assert found is not None
        return found

    def calculate(self, asked: Any) -> Any:
        """«Calcular» ``asked`` en V01 con sus máscaras: la ``Calculation`` (nada registrado)."""
        found = last(steps.road_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1))
        assert found is not None
        return found

    def texts(self, found: Any) -> list[str]:
        """Todo lo que dice la vista previa, en los dos idiomas, sin un solo marcador sin llenar."""
        said: list[str] = []
        for language in ("es", "en"):
            for text, _alert in found.lines(language):
                self.assertNotIn("{", text)
                said.append(text)
        return said

    def ask(self, **changes: Any) -> Any:
        """La petición de la rampa con lo que dejó «Calcular»: su preparación y su resultado."""
        return preview.RoadAsk(request=self.asked, prepared=self.calculation.entity, outcome=self.calculation.outcome, **changes)

    # --- Antes de calcular (RF-017-26, RF-017-09, RF-015-26, RNF-017-06) ---

    def test_a_origin_destination_and_corridor_are_drawn_writing_nothing(self) -> None:
        """RF-017-26, RF-017-09, RF-015-26: la rampa («trazar», 200 m al 4 %) da el origen y el destino de su capa (absolutas, float64) con las cotas de su superficie de partida, el **pasillo** (el de ``road_net``
        con la holgura de la ruta: sus nodos, el área de sus anillos es ``nodos · malla²``, a ≤ 10⁻⁹ relativo, y los dos puntos están en su caja) y la cota inferior de la longitud (la de la red 2D: no menos
        que la recta de 200 m); no hay eje ni tramos (no se ha calculado); y **no se escribe nada** (la base de datos, las operaciones, los datos, los parámetros y los ficheros)."""
        asked = request()
        before = self.state()
        found = self.preview_of(preview.RoadAsk(request=asked))
        self.assertEqual(self.state(), before, "la vista previa no escribe")
        self.assertIsNone(found.refusal)
        self.assertEqual((found.name, found.code, found.version, found.mode, found.start_surface), ("Pista de la rampa", "RDW-001", "V01", "trace", RAMP))
        self.assertEqual(found.masks.value, "current")
        self.assertFalse(found.calculated)
        self.assertTrue(found.drawable)
        prepared = self.prepare(asked)
        by_kind = {item.which: item for item in found.points}
        self.assertEqual(set(by_kind), {"origin", "destination"})
        self.assertEqual((by_kind["origin"].x, by_kind["origin"].y), absolute(rd.RAMP_ORIGIN))
        self.assertEqual((by_kind["destination"].x, by_kind["destination"].y), absolute(rd.RAMP_DESTINATION))
        self.assertEqual((by_kind["origin"].level_m, by_kind["destination"].level_m), (prepared.job.start_level_m, prepared.job.end_level_m))
        mesh, corridor = rd.route_corridor(prepared.job)
        self.assertEqual((found.mesh_m, found.margin_m, found.corridor_nodes, found.reachable), (mesh.mesh_m, prepared.job.route.margin_m, corridor.nodes, True))
        self.assertAlmostEqual(found.lower_bound_m, corridor.lower_bound_m, delta=EPS)
        self.assertGreaterEqual(found.lower_bound_m, 200.0 - 1e-6)
        self.assertGreater(len(found.corridor), 0)
        self.assertAlmostEqual(area_of(found.corridor), corridor.nodes * mesh.mesh_m**2, delta=EPS * corridor.nodes * mesh.mesh_m**2)
        every = np.concatenate([np.asarray(ring) for ring in found.corridor])
        low, high = every.min(axis=0), every.max(axis=0)
        for point in found.points:
            self.assertTrue(low[0] <= point.x <= high[0] and low[1] <= point.y <= high[1], point.which)
        self.assertIsNone(found.axis)
        self.assertEqual(found.stretches, ())
        self.assertEqual(found.line, None)
        self.assertEqual([notice.code for notice in found.notices][:2], ["des.preview_road_trace", "des.preview_road_corridor"])
        self.assertGreater(len(self.texts(found)), 2)

    def test_b_the_corridor_is_the_one_the_calculation_searches_in(self) -> None:
        """RF-017-09: la holgura manda: con 0 m de holgura el pasillo es el más estrecho y con 60 m, más ancho (más nodos), siempre alrededor de los mismos puntos; el pasillo del dibujo y el de «Calcular»
        (``RouteReport.corridor_nodes``) tienen los mismos nodos."""
        narrow = self.preview_of(preview.RoadAsk(request=request(margin_m=4.0)))
        wide = self.preview_of(preview.RoadAsk(request=request(margin_m=60.0)))
        self.assertLess(narrow.corridor_nodes, wide.corridor_nodes)
        self.assertEqual((narrow.margin_m, wide.margin_m), (4.0, 60.0))
        calculation = self.calculate(request(margin_m=60.0))
        self.assertEqual(calculation.outcome.route.corridor_nodes, wide.corridor_nodes)
        calculation.discard()

    def test_c_a_level_destination_draws_its_zone_and_no_destination_point(self) -> None:
        """RF-017-26, RF-017-02, D-4: la rampa a una cota (125 m en la zona del fondo, a ±0,5 m) dibuja la **zona** del destino (su polígono), dice la cota pedida y su tolerancia y solo tiene el punto
        del origen (el destino lo alcanza la ruta); el pasillo va a esos nodos."""
        asked = request(destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", origin="Origen tajo", surface=rd.dataset_of("tajo"))
        found = self.preview_of(preview.RoadAsk(request=asked))
        self.assertIsNone(found.refusal)
        self.assertEqual([item.which for item in found.points], ["origin"])
        self.assertGreater(len(found.zone), 0)
        self.assertAlmostEqual(abs(area_of(found.zone)), (120.0 - 80.0) * (180.0 - 140.0), delta=1e-6)
        self.assertEqual((found.target_level_m, found.target_tolerance_m), (rd.PIT_FLOOR_M, 0.5))
        self.assertTrue(found.reachable and found.corridor_nodes > 0)

    def test_d_a_line_mode_draws_the_line_it_follows_and_no_corridor(self) -> None:
        """RF-017-26, RF-017-02: «sobre un eje» sigue la línea de su capa: la dibuja (sus vértices, absolutos) con el origen y el destino en sus extremos, sin red 2D ni pasillo (no busca ruta), y lo dice."""
        asked = request(mode="on_axis", layer=rd.AXES_LAYER)
        found = self.preview_of(preview.RoadAsk(request=asked))
        self.assertIsNone(found.refusal)
        self.assertEqual(found.mode, "on_axis")
        prepared = self.prepare(asked)
        np.testing.assert_array_equal(found.line, np.asarray(prepared.job.geometry.line)[:, :2])
        self.assertEqual((found.corridor, found.corridor_nodes, found.mesh_m, found.reachable), ((), 0, None, None))
        by_kind = {item.which: item for item in found.points}
        self.assertEqual((by_kind["origin"].x, by_kind["origin"].y), tuple(float(value) for value in found.line[0]))
        self.assertEqual((by_kind["destination"].x, by_kind["destination"].y), tuple(float(value) for value in found.line[-1]))
        self.assertEqual(found.notices[0].code, "des.preview_road_line")

    def test_e_what_calculating_would_refuse_is_the_notice_in_place_of_the_drawing(self) -> None:
        """RF-015-26, RF-015-08, RF-017-04: un perfil que no existe (lo que rechazaría «Calcular») no es un error: es ``refusal`` con el mismo mensaje y sin dibujo; sin escribir nada."""
        before = self.state()
        found = self.preview_of(preview.RoadAsk(request=request(profile="no_existe")))
        self.assertEqual(self.state(), before)
        self.assertEqual(found.refusal.code, "des.road_profile_unknown")
        self.assertFalse(found.drawable)
        lines = found.lines("es")
        self.assertTrue(lines[0][1], "el rechazo va en alerta")
        self.assertIn("no_existe", lines[0][0])
        self.assertEqual(found.lines("en")[0][0], found.refusal.text_in("en"))
        wrong = self.preview_of(preview.RoadAsk(request=request(mode="on_axis")))  # una capa de puntos para un modo que necesita líneas
        self.assertEqual(wrong.refusal.code, "des.road_layer_kind")
        self.assertEqual(self.state(), before)

    def test_f_without_the_masks_up_to_date_it_says_so_instead_of_drawing(self) -> None:
        """RF-015-26: V02 no tiene las máscaras compiladas: no se dibuja nada y la vista previa lo dice (``des.preview_entity_masks_missing``, el aviso de la plataforma, con la pista y la versión)."""
        found = self.preview_of(preview.RoadAsk(request=request()), version=self.v2)
        self.assertFalse(found.drawable)
        self.assertEqual(found.masks.value, "missing")
        self.assertEqual([notice.code for notice in found.notices], ["des.preview_entity_masks_missing"])
        self.assertIn("V02", found.lines("es")[0][0])

    def test_g_closing_the_steps_halfway_leaves_nothing_and_each_step_is_short(self) -> None:
        """RNF-017-06, RF-015-29: con un presupuesto mínimo son muchos pasos (la preparación, la red 2D desde el destino y desde el origen y el pasillo), cerrar el generador a mitad no deja nada y el
        último paso es el único que lleva la vista previa."""
        before = self.state()
        every = list(preview.road_preview_steps(self.project, preview.RoadAsk(request=request()), self.v1.uid, budget_s=1e-9))
        self.assertGreater(len(every), 10, "por pasos")
        self.assertTrue(all(step.result is None for step in every[:-1]))
        self.assertIsInstance(every[-1].result, preview.RoadPreview)
        for cut in (1, len(every) // 2, len(every) - 1):
            with self.subTest(closed_after=cut):
                work = preview.road_preview_steps(self.project, preview.RoadAsk(request=request()), self.v1.uid, budget_s=1e-9)
                for _step in range(cut):
                    next(work)
                work.close()
                self.assertEqual(self.state(), before)

    def test_h_the_ask_is_one_thing_a_road_being_prepared_or_one_of_the_version(self) -> None:
        """La vista previa es de una sola cosa: la pista que se prepara (su petición) o una de la versión (su código); ninguna o las dos, y un resultado sin su petición, son errores del programa."""
        for bad in ({}, {"request": request(), "code": "RDW-001"}, {"code": "RDW-001", "outcome": object()}, {"request": request(), "prepared": None, "outcome": None, "code": ""}):
            with self.subTest(bad=sorted(bad)), self.assertRaises(ValueError):
                preview.RoadAsk(**bad)


    def test_m_a_road_of_the_version_without_a_result_says_so_and_what_is_not_a_road_is_a_program_error(self) -> None:
        """RF-015-26, RF-017-26: la pista **de la versión** sin calcular (registrada y sin operación) no se dibuja: la vista previa dice que aún no tiene resultado (``des.preview_entity_uncalculated``,
        con su nombre y su código), sin leer ni escribir nada; una entidad que no es una pista, o que no es de la versión, es un error del programa (``ValueError``). (La pista calculada de la versión, con
        su eje guardado y lo que se le apoya, es de ``milestone_road_preview``.)"""
        kind = entities.EntityKind
        road = SimpleNamespace(record=SimpleNamespace(kind=kind.ROAD, name="Pista", code="RDW-001"), operation_uid=None)
        platform = SimpleNamespace(record=SimpleNamespace(kind=kind.PLATFORM, name="P1", code="PLT-001"), operation_uid="una-operacion")
        before = self.state()
        with mock.patch.object(road_store.entities, "registry", return_value={"RDW-001": road, "PLT-001": platform}):
            found = self.preview_of(preview.RoadAsk(code="RDW-001"))
            self.assertEqual([notice.code for notice in found.notices], ["des.preview_entity_uncalculated"])
            self.assertEqual((found.name, found.code, found.drawable, found.calculated), ("Pista", "RDW-001", False, False))
            self.assertIn("RDW-001", found.lines("es")[0][0])
            for wrong in ("PLT-001", "RDW-009"):
                with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                    self.preview_of(preview.RoadAsk(code=wrong))
        self.assertEqual(self.state(), before)

    # --- Tras calcular (RF-017-26, RF-017-15, RF-017-17): lo que dejó «Calcular» ---

    def test_i_the_axis_the_levels_and_the_stretches_are_those_of_the_calculation(self) -> None:
        """RF-017-26, RF-017-15: tras «Calcular» la vista previa lleva el eje por estaciones (bit a bit el del resultado), la rasante, su longitud, su pendiente media (4 %), el perfil, la anchura de la calzada
        y de la sección (10,5 y 11,5 m, los derivados del perfil) y los tramos (cada 50 m como mucho: 4), todos «dentro» (4 % ≤ pm = 10 %); el origen y el destino son los extremos del eje con la rasante
        ahí; ya no hay pasillo; y no escribe nada."""
        outcome = self.calculation.outcome
        before = self.state()
        found = self.preview_of(self.ask())
        self.assertEqual(self.state(), before)
        self.assertIsNone(found.refusal)
        self.assertTrue(found.calculated and found.drawable)
        self.assertEqual((found.name, found.code, found.mode, found.profile), ("Pista de la rampa", "RDW-001", "trace", "PISTA_PRINCIPAL"))
        np.testing.assert_array_equal(found.axis, outcome.axis.points)
        np.testing.assert_array_equal(found.stations, outcome.axis.stations)
        np.testing.assert_array_equal(found.levels, outcome.levels)
        self.assertAlmostEqual(found.length_m, 200.0, delta=1e-6)
        self.assertAlmostEqual(found.gradient_mean_pct, 4.0, delta=EPS)
        self.assertEqual((found.carriageway_m, found.section_m), (10.5, 11.5))
        self.assertEqual((found.max_gradient_pct, found.max_mean_gradient_pct), (10.0, 10.0))
        self.assertEqual((found.curves, found.min_radius_m), (outcome.axis.curve_count, outcome.axis.min_radius_m))
        self.assertEqual(len(found.stretches), 4)
        self.assertTrue(all(item.status is preview.GradientStatus.WITHIN for item in found.stretches))
        self.assertEqual((found.stretches[0].first, found.stretches[-1].last), (0, len(found.stations) - 1))
        ends = {item.which: item for item in found.points}
        self.assertEqual((ends["origin"].x, ends["origin"].y, ends["origin"].level_m), (*outcome.axis.points[0], float(outcome.levels[0])))
        self.assertEqual((ends["destination"].x, ends["destination"].y, ends["destination"].level_m), (*outcome.axis.points[-1], float(outcome.levels[-1])))
        self.assertEqual((found.corridor, found.zone), ((), ()))
        self.assertEqual(found.notices[0].code, "des.preview_road_calculated")
        self.assertGreater(len(self.texts(found)), 1)

    def test_j_the_edges_of_the_section_are_at_half_its_width(self) -> None:
        """RF-017-26, RF-017-08: los bordes de la sección están a su semianchura (5,75 m) del eje a cada lado en todas las estaciones: la distancia al punto del eje es 5,75 m, a ≤ 10⁻⁹, y a la
        izquierda del sentido de la marcha (la rampa va de oeste a este: el borde izquierdo queda al norte)."""
        found = self.preview_of(self.ask())
        left, right = found.edges
        self.assertEqual(left.shape, found.axis.shape)
        np.testing.assert_allclose(np.hypot(*(left - found.axis).T), 5.75, atol=EPS * 10)
        np.testing.assert_allclose(np.hypot(*(right - found.axis).T), 5.75, atol=EPS * 10)
        self.assertGreater(float((left[:, 1] - right[:, 1]).mean()), 0.0)

    def test_k_a_profile_with_a_lower_mean_limit_paints_the_stretches_above_pm(self) -> None:
        """RF-017-26, RF-017-17: con un perfil de pm = 3 % la misma rampa del 4 % va «por encima de pm» en todos sus tramos (y por debajo de pd = 10 %: ninguno «por encima de pd»), y la leyenda dice los
        dos límites."""
        asked = request(profile=LOW_MEAN)
        calculation = self.calculate(asked)
        found = self.preview_of(preview.RoadAsk(request=asked, prepared=calculation.entity, outcome=calculation.outcome))
        calculation.discard()
        self.assertEqual((found.max_gradient_pct, found.max_mean_gradient_pct), (10.0, 3.0))
        self.assertTrue(all(item.status is preview.GradientStatus.ABOVE_MEAN for item in found.stretches), [item.status for item in found.stretches])
        self.assertTrue(all(abs(item.gradient_pct - 4.0) < EPS for item in found.stretches))

    def test_l_the_preparation_is_made_when_the_dialog_did_not_hold_it(self) -> None:
        """RF-017-26: con solo el resultado (sin la preparación) se prepara la pista y sale lo mismo; con solo la preparación (sin resultado), es lo de antes de calcular pero **sin repetir la
        preparación** (el origen y el destino salen de la ya hecha)."""
        whole = self.preview_of(self.ask())
        only = self.preview_of(preview.RoadAsk(request=self.asked, outcome=self.calculation.outcome))
        np.testing.assert_array_equal(only.axis, whole.axis)
        self.assertEqual(only.stretches, whole.stretches)
        held = self.preview_of(preview.RoadAsk(request=self.asked, prepared=self.calculation.entity))
        self.assertFalse(held.calculated)
        self.assertEqual({item.which for item in held.points}, {"origin", "destination"})
        self.assertGreater(held.corridor_nodes, 0)
