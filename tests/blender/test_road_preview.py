# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de una pista en la Vista 3D (spec 017, T28; HU-017-1; RF-017-26, RF-015-26; RNF-017-06; plan 017 §5.5; comprobación manual M5; principio 8).

La vista previa (``bl.draw.entity``, con ``EntityPlan(road=…)``) es un manejador de dibujo **sin objetos ni escritura**: lo que dibuja se prueba en sus lotes (sin ``gpu``: ``docs/trampas.md`` §3), sus
nombres y su leyenda, no en píxeles de pantalla. Aquí, **sin proyecto** (la preparación de ``design`` la prueba ``tests/unit/design/milestone_road_preview_data.py`` y ``milestone_road_preview`` la hace con un
proyecto de verdad): una ``design.preview.RoadPreview`` sintética, con las mismas funciones de ``design`` (``gradient_stretches`` y ``section_edges``), entra por ``road_preview_steps`` y sale en lotes.
Las pruebas, en el orden de sus letras:

- RF-017-26 (a): **antes de calcular**, el origen y el destino (una cruz cada uno, con su cota), el pasillo de la ruta y la zona de la cota de destino; nada del eje.
- RF-017-26, RF-017-15, RF-017-17 (b): **tras calcular**, el eje con su flecha, la rasante por tramos **coloreados según pd y pm** (con su pendiente y sus cotas), los bordes de la sección y lo que se le apoya,
  con su leyenda y su resumen, en los dos idiomas; los lotes, en el orden de dibujo, lado a lado con los datos de ``design``.
- RF-017-26, RF-015-08 (c): lo que rechazaría «Calcular» (o las máscaras sin compilar, o sin versión activa) es el aviso en lugar del dibujo.
- RF-015-26 (d): la orden ``geoblender.des_entity_preview`` ofrece una pista de la versión por su código, y lo que no tiene vista previa lo dice.
- RF-015-26, RF-017-26 (e): activarla pone los manejadores de dibujo y el temporizador, la construye por pasos y **se quita** con su mismo control, al cambiar de proyecto y **al conmutar a la interfaz de
  Blender** (``switcher.add_blender_hook``): ida y vuelta deja Blender como estaba; nada se crea en la escena.
- Principio 8 (z): desactivar Geoblender con la vista previa de una pista activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Generator
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name

WEST, SOUTH, GROUND_M = 700_000, 4_400_000, 100
ORIGIN = SimpleNamespace(x0=WEST, y0=SOUTH, z0=GROUND_M)
"""El GeoOrigin de la prueba (enteros, como el de un proyecto)."""
CELL_M = 2.0
PD, PM = 10.0, 8.0
"""Los límites del perfil de la prueba (%): la pendiente de diseño y la media máxima."""
HALF_M = 5.75
MAX_PUMPS = 2_000
VERSION = SimpleNamespace(uid="uid-v01", code="V01")


def _module(name: str) -> Any:
    return importlib.import_module(f"{module_name()}.{name}")


def _hex(color: tuple[float, ...]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(float(part) * 255.0) for part in color[:3]))


def _no_ground(*_args: Any, **_kwargs: Any) -> Generator[None, None, None]:
    """``bl.draw.constraints.ground_steps`` sin superficie: se dibuja a la cota del GeoOrigin."""
    return None
    yield  # noqa: B901 - lo hace un generador


class RoadPreviewTest(unittest.TestCase):
    """La extensión habilitada una vez; la vista previa se prueba con datos de ``design`` hechos a mano y los pasos de su preparación sustituidos."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        for name, module in (("entity", "bl.draw.entity"), ("design_draw", "bl.draw.design"), ("constraints", "bl.draw.constraints"), ("dpreview", "design.preview"),
                             ("switcher", "bl.ui.switcher"), ("ps", "bl.scene.project_session"), ("scene_versions", "bl.scene.versions"), ("i18n", "core.i18n"),
                             ("des_ops", "bl.ops.des"), ("entities", "design.entities"), ("access", "gis.masks.access"), ("model", "core.project.model")):
            setattr(cls, name, _module(module))
        cls.addClassCleanup(cls.entity.disable)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        if self.entity.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.entity.disable()

    # --- Datos de la prueba ------------------------------------------------------------------

    def absolute(self, x: float, y: float) -> tuple[float, float]:
        """El punto local (x, y) de la prueba como absoluto (float64)."""
        return (WEST + x, SOUTH + y)

    def corridor_before(self) -> Any:
        """Lo que la vista previa dice **antes de calcular** una rampa a una cota: el origen con su cota, la zona del destino, el pasillo (un rectángulo y un hueco) y su nota."""
        dp = self.dpreview
        rectangle = np.array([self.absolute(*point) for point in ((20.0, 40.0), (220.0, 40.0), (220.0, 100.0), (20.0, 100.0), (20.0, 40.0))])
        hole = np.array([self.absolute(*point) for point in ((100.0, 60.0), (100.0, 80.0), (120.0, 80.0), (120.0, 60.0), (100.0, 60.0))])
        zone = np.array([self.absolute(*point) for point in ((200.0, 50.0), (216.0, 50.0), (216.0, 90.0), (200.0, 90.0), (200.0, 50.0))])
        ox, oy = self.absolute(30.0, 70.0)
        return dp.RoadPreview("Pista de la rampa", "RDW-001", "V01", self.access.MaskState.CURRENT, mode="trace", start_surface="gis_dtm_rampa", profile="PISTA_PRINCIPAL", cell_m=CELL_M,
                              points=(dp.RoadPoint("origin", ox, oy, 104.0),), zone=(zone,), target_level_m=125.0, target_tolerance_m=0.5, mesh_m=4.0, margin_m=60.0,
                              corridor=(rectangle, hole), corridor_nodes=700, lower_bound_m=200.0, reachable=True, carriageway_m=10.5, section_m=11.5, max_gradient_pct=PD,
                              max_mean_gradient_pct=PM, notices=(dp.Notice("des.preview_road_trace", {"entity": "Pista de la rampa", "code": "RDW-001", "version": "V01", "surface": "gis_dtm_rampa",
                                                                                                      "profile": "PISTA_PRINCIPAL", "section": 11.5, "carriageway": 10.5}),))

    def levels_of(self, stations: np.ndarray, slopes: tuple[tuple[float, float], ...]) -> np.ndarray:
        """La rasante en ``stations`` desde la cota 100 m con la pendiente de cada ``(hasta la abscisa, pendiente en tanto por uno)``."""
        slope = np.zeros(len(stations) - 1)
        start = 0.0
        for until, gradient in slopes:
            slope[(stations[:-1] >= start) & (stations[:-1] < until)] = gradient
            start = until
        return GROUND_M + np.concatenate([[0.0], np.cumsum(slope * np.diff(stations))])

    def calculated(self, *, resting: tuple[Any, ...] = (), slopes: tuple[tuple[float, float], ...] = ((100.0, 0.04), (200.0, 0.09), (300.0, 0.12))) -> Any:
        """Lo que la vista previa dice **tras calcular**: un eje recto de 300 m al este con tres tramos de 100 m de rasante (por defecto al 4 %, al 9 % y al 12 %: dentro, por encima de pm = 8 % y por
        encima de pd = 10 %), sus bordes a 5,75 m y los tramos de ``design`` (un tramo cada 50 m)."""
        dp = self.dpreview
        stations = np.arange(0.0, 301.0)
        levels = self.levels_of(stations, slopes)
        points = np.array([self.absolute(20.0 + s, 50.0) for s in stations])
        stretches = dp.gradient_stretches(stations, levels, PD, PM)
        notice = dp.Notice("des.preview_road_calculated", {"entity": "Pista", "code": "RDW-001", "version": "V01", "length": 300.0, "curves": 0, "start_level": float(levels[0]),
                                                           "end_level": float(levels[-1]), "gradient": 8.3333, "limit": PM, "section": 11.5, "carriageway": 10.5})
        return dp.RoadPreview("Pista", "RDW-001", "V01", self.access.MaskState.CURRENT, mode="trace", start_surface="gis_dtm_rampa", profile="PISTA_PRINCIPAL", cell_m=CELL_M,
                              points=(dp.RoadPoint("origin", *points[0], float(levels[0])), dp.RoadPoint("destination", *points[-1], float(levels[-1]))), calculated=True, axis=points,
                              stations=stations, levels=levels, edges=dp.section_edges(points, HALF_M), length_m=300.0, curves=0, gradient_mean_pct=8.3333, carriageway_m=10.5, section_m=11.5,
                              max_gradient_pct=PD, max_mean_gradient_pct=PM, stretches=stretches, resting=resting, notices=(notice,))

    def request(self, found: Any, *, version: Any = VERSION, language: str = "es") -> Any:
        """Lo que se construye para ``found`` (con un proyecto de mentira: solo lleva su GeoOrigin)."""
        plan = self.entity.EntityPlan(road=self.dpreview.RoadAsk(request=object()))
        return self.entity.Request(SimpleNamespace(origin=ORIGIN), None if version is None else version.uid, "" if version is None else version.code, plan, language, ("sello",))

    def steps_of(self, found: Any) -> Any:
        """Lo que sustituye a ``road_preview_steps``: un solo paso, que lleva ``found``."""
        def steps(_project: Any, _ask: Any, _version_uid: str, *, budget_s: float = 0.0) -> Any:
            return iter([self.model.Progress("preview_road", 1, 1, "Vista previa de la pista lista", result=found)])
        return steps

    def build(self, found: Any, **options: Any) -> Any:
        """Los pasos de ``bl.draw.entity.build_steps`` (la construcción de lo que dibuja) llevados hasta el final: lo construido (un ``bl.draw.design.Built``)."""
        with mock.patch.object(self.dpreview, "road_preview_steps", side_effect=self.steps_of(found)), mock.patch.object(self.constraints, "ground_steps", side_effect=_no_ground):
            work = self.entity.build_steps(self.request(found, **options))
            while True:
                try:
                    next(work)
                except StopIteration as done:
                    return done.value

    @staticmethod
    def batch(built: Any, key: str) -> Any:
        return next((batch for batch in built.lines.batches if batch.key == key), None)

    def local(self, batch: Any) -> np.ndarray:
        """Los vértices de ``batch`` como absolutos (float64): lo local de ``bl`` más el GeoOrigin."""
        return batch.positions[:, :2].astype(np.float64) + [ORIGIN.x0, ORIGIN.y0]

    # --- RF-017-26 (a): antes de calcular --------------------------------------------------------

    def test_a_before_calculating_it_draws_the_origin_the_destination_zone_and_the_corridor(self) -> None:
        """RF-017-26, RF-017-09 (M5): antes de calcular, el origen es una cruz (2 rayas de 6 m de brazo: 3 celdas de 2 m) en su lugar y con su cota, la zona de la cota de destino y el pasillo (el
        rectángulo y su hueco: 8 lados) son lotes de su color; no hay eje, flecha, bordes ni tramos; la leyenda dice el pasillo (700 nodos, 60 m de holgura), el origen y la zona; y lo que dice la
        vista previa, el resumen (una nota, sin alerta)."""
        found = self.corridor_before()
        built = self.build(found)
        keys = [batch.key for batch in built.lines.batches]
        self.assertEqual(keys, [self.entity.CORRIDOR, self.entity.TARGET, self.entity.ORIGIN])
        corridor, target, origin = (self.batch(built, key) for key in keys)
        self.assertEqual((corridor.segments, target.segments, origin.segments), (8, 4, 2))
        self.assertEqual((corridor.color, target.color, origin.color), (self.entity.CORRIDOR_COLOR, self.entity.DESTINATION_COLOR, self.entity.ORIGIN_COLOR))
        self.assertEqual(corridor.role, self.constraints.OUTLINE)
        arms = self.local(origin).reshape(-1, 2, 2)
        np.testing.assert_allclose(arms.mean(axis=1), [self.absolute(30.0, 70.0)] * 2, atol=1e-6)
        np.testing.assert_allclose(np.abs(arms[:, 1] - arms[:, 0]).max(axis=1), [12.0, 12.0], atol=1e-6)  # de punta a punta: 2 × 6 m
        np.testing.assert_allclose(origin.positions[:, 2], 0.0, atol=1e-6)  # sin superficie: a la cota del GeoOrigen
        self.assertEqual([label.text for label in built.lines.labels], ["Origen · rasante 104,00 m"])
        text = [row.text for row in built.lines.legend]
        self.assertEqual(text[0], "Vista previa de «Pista de la rampa» (RDW-001) · V01")
        self.assertIn("Pasillo de la ruta (700 nodos, holgura de 60,0 m)", text)
        self.assertIn("Origen", text)
        self.assertIn("Zona del destino: cota 125,00 m, tolerancia 0,50 m", text)
        self.assertNotIn("Destino", text, "el destino de una rampa no es un punto")
        self.assertEqual(text[-1], "A la cota del GeoOrigin")
        self.assertEqual([row.color for row in built.lines.legend if row.color], [_hex(self.entity.CORRIDOR_COLOR), _hex(self.entity.ORIGIN_COLOR), _hex(self.entity.DESTINATION_COLOR)])
        self.assertEqual([alert for _text, alert in built.summary], [False])
        self.assertTrue(built.summary[0][0].startswith("Vista previa de «Pista de la rampa» (RDW-001) en V01: la ruta se buscará"))
        self.assertEqual((built.lines.masks, built.lines.surface, built.lines.stamp), ("current", "", ("sello",)))

    # --- RF-017-26 (b): tras calcular ---------------------------------------------------------------

    def test_b_after_calculating_the_axis_the_arrow_the_stretches_by_pd_and_pm_and_the_section(self) -> None:
        """RF-017-26, RF-017-15, RF-017-17 (M5): tras calcular, el eje (300 tramos) con su flecha (2 rayas desde su último punto, hacia atrás), la rasante en tres lotes según su estado (100 tramos cada
        uno: dentro de pm, por encima de pm y por encima de pd, cada uno en su color y a partir de su abscisa), los dos bordes de la sección (600 tramos a 5,75 m del eje) y las cruces del origen y el
        destino; los lotes en el orden de dibujo (los de debajo primero) y los nombres (los dos extremos con su cota y cada tramo con su pendiente y sus cotas); la leyenda con pd y pm y la sección."""
        found = self.calculated()
        built = self.build(found)
        keys = [batch.key for batch in built.lines.batches]
        entity = self.entity
        self.assertEqual(keys, [entity.SECTION, entity.GRADIENT_WITHIN, entity.GRADIENT_MEAN, entity.GRADIENT_DESIGN, entity.AXIS, entity.ARROW, entity.ORIGIN, entity.DESTINATION])
        counts = {key: self.batch(built, key).segments for key in keys}
        self.assertEqual(counts, {entity.SECTION: 600, entity.GRADIENT_WITHIN: 100, entity.GRADIENT_MEAN: 100, entity.GRADIENT_DESIGN: 100, entity.AXIS: 300, entity.ARROW: 2,
                                  entity.ORIGIN: 2, entity.DESTINATION: 2})
        for key in (entity.GRADIENT_WITHIN, entity.GRADIENT_MEAN, entity.GRADIENT_DESIGN):
            self.assertEqual(self.batch(built, key).color, entity.GRADIENT_COLORS[key])
        self.assertNotEqual(len({entity.GRADIENT_COLORS[key] for key in entity.GRADIENT_COLORS}), 1)
        for key, first in ((entity.GRADIENT_WITHIN, 0), (entity.GRADIENT_MEAN, 100), (entity.GRADIENT_DESIGN, 200)):
            vertices = self.local(self.batch(built, key))
            np.testing.assert_allclose(vertices[0], found.axis[first], atol=1e-6, err_msg=key)
            np.testing.assert_allclose(vertices[-1], found.axis[first + 100], atol=1e-6, err_msg=key)
        axis = self.local(self.batch(built, entity.AXIS)).reshape(-1, 2, 2)
        np.testing.assert_allclose(axis[:, 0], found.axis[:-1], atol=1e-6)
        np.testing.assert_allclose(axis[:, 1], found.axis[1:], atol=1e-6)
        arrow = self.local(self.batch(built, entity.ARROW)).reshape(-1, 2, 2)
        np.testing.assert_allclose(arrow[:, 0], [found.axis[-1]] * 2, atol=1e-6)  # las dos rayas salen del último punto
        self.assertTrue(bool((arrow[:, 1, 0] < arrow[:, 0, 0]).all()), "hacia atrás: la flecha apunta al final")
        edges = self.local(self.batch(built, entity.SECTION)).reshape(-1, 2, 2)
        np.testing.assert_allclose(np.abs(edges[:, 0, 1] - (SOUTH + 50.0)), HALF_M, atol=1e-6)
        names = [label.text for label in built.lines.labels]
        self.assertEqual(names[:2], ["Origen · rasante 100,00 m", "Destino · rasante 125,00 m"])
        self.assertEqual(len(names), 2 + 6)
        self.assertEqual(names[2], "4,0 % · rasante de 100,00 a 102,00 m")
        self.assertEqual(names[-1], "12,0 % · rasante de 119,00 a 125,00 m")
        text = [row.text for row in built.lines.legend]
        self.assertIn("Eje con sus curvas (300,0 m): la flecha muestra su sentido; la abscisa 0 está en el origen", text)
        self.assertIn("Tramo dentro de los límites del perfil (media hasta el 8,0 %)", text)
        self.assertIn("Tramo con la pendiente media por encima de la media máxima pm (8,0 %)", text)
        self.assertIn("Tramo con un paso por encima de la pendiente de diseño pd (10,0 %)", text)
        self.assertIn("Bordes de la sección: 11,5 m de ancho (calzada de 10,5 m)", text)
        colored = {row.text: row.color for row in built.lines.legend if row.color}
        self.assertEqual(colored["Tramo con la pendiente media por encima de la media máxima pm (8,0 %)"], _hex(entity.GRADIENT_COLORS[entity.GRADIENT_MEAN]))
        self.assertEqual(built.summary[0][0][:60], "Vista previa de «Pista» (RDW-001) en V01: eje de 300,0 m (cu")
        self.i18n.set_language("en")
        english = self.build(found, language="en")
        self.assertTrue(english.summary[0][0].startswith("Preview of «Pista» (RDW-001) in V01: axis of 300.0 m (curves: 0)"))
        texts = [row.text for row in english.lines.legend]
        self.assertIn("Stretch with a mean gradient above the mean limit pm (8.0 %)", texts)
        self.assertIn("Stretch with a step above the design gradient pd (10.0 %)", texts)
        self.assertEqual(english.lines.labels[0].text, "Origin · level 100.00 m")
        self.assertEqual(english.lines.labels[2].text, "4.0 % · level 100.00 → 102.00 m")

    def test_c_a_road_that_rests_on_the_axis_draws_what_rests_on_it_with_its_name_and_volume(self) -> None:
        """RF-017-26, RF-015-15: lo que se apoya en la pista (un ramal con su huella y un relleno sin huella propia, ``design.preview.RestingItem``) es un lote con su nombre y su volumen en el lugar de su
        huella y una fila de la leyenda; el que no tiene huella dice que es «sin una huella propia»."""
        dp = self.dpreview
        ring = np.array([self.absolute(*point) for point in ((100.0, 52.0), (160.0, 52.0), (160.0, 90.0), (100.0, 90.0), (100.0, 52.0))])
        resting = (dp.RestingItem("Ramal", "RDW-002", "des.road", "current", 1500.0, (ring,)), dp.RestingItem("Relleno", None, "des.fill", "current", None))
        built = self.build(self.calculated(resting=resting))
        self.assertEqual(self.batch(built, self.entity.RESTING).segments, 4)
        names = [label.text for label in built.lines.labels]
        self.assertTrue(names[-1].startswith("«Ramal» · 1") and names[-1].endswith("m³ apoyados en ella"), names[-1])  # su volumen, con el separador de miles
        self.assertEqual(len(names), 2 + 6 + 1, "el relleno sin huella no tiene dónde nombrarse")
        text = [row.text for row in built.lines.legend]
        self.assertIn("Se apoya en ella o parte de ella (2)", text)

    # --- RF-017-26, RF-015-08 (c): en lugar del dibujo -----------------------------------------------

    def test_d_what_calculating_would_refuse_the_masks_and_the_missing_version_are_the_warning(self) -> None:
        """RF-017-26, RF-015-08, RF-015-26: con el rechazo de «Calcular» (un perfil que no existe), sin las máscaras al día o sin versión activa **no hay dibujo**: el aviso, con el mismo mensaje y en
        alerta, y la leyenda solo con su título."""
        dp = self.dpreview
        error = _module("design.messages").DesignError("des.road_profile_unknown", obj="Pista «Pista» de la capa «puntos»", field="des.road.rdw_001.profile", value="no_existe", layer="puntos",
                                                       entity="Pista", profiles="PISTA_PRINCIPAL")
        for found, alert in ((dp.RoadPreview("Pista", "", "V01", self.access.MaskState.CURRENT, refusal=error), True),
                             (dp.RoadPreview("Pista", "", "V01", self.access.MaskState.MISSING, notices=(dp.Notice("des.preview_entity_masks_missing", {"version": "V01", "entity": "Pista"}),)), True)):
            with self.subTest(refusal=found.refusal is not None):
                built = self.build(found)
                self.assertEqual(built.lines.batches, ())
                self.assertEqual(built.lines.labels, ())
                self.assertEqual([row.text for row in built.lines.legend], ["Vista previa de «Pista» · V01"])
                self.assertEqual([item[1] for item in built.summary], [alert])
        shown = self.build(dp.RoadPreview("Pista", "", "V01", self.access.MaskState.CURRENT, refusal=error))
        self.assertIn("no_existe", shown.summary[0][0])
        none = self.build(found, version=None)
        self.assertEqual((none.lines.batches, none.summary[0][1]), ((), True))
        self.assertEqual([row.text for row in none.lines.legend], ["Vista previa de una entidad", "Sin versión activa: no hay nada que previsualizar"])

    # --- RF-015-26 (d): la orden ----------------------------------------------------------------------

    def test_e_the_command_offers_a_road_of_the_version_by_its_code_and_says_what_has_no_preview(self) -> None:
        """RF-015-26, RF-017-26: ``geoblender.des_entity_preview`` previsualiza **una pista de la versión** (``EntityPlan(road=RoadAsk(code=…))``, sin calcular nada: lo dice la vista previa si no está
        calculada); una accesibilidad no tiene vista previa y la orden lo dice con las cuatro cosas que sí la tienen."""
        entry = SimpleNamespace(record=SimpleNamespace(kind=self.entities.EntityKind.ROAD, code="RDW-001", name="Pista"), operation_uid=None)
        plan = self.des_ops.GEOBLENDER_OT_des_entity_preview._plan(SimpleNamespace(), VERSION, entry)
        self.assertEqual((plan.kind, plan.road.code, plan.road.request, plan.request, plan.code), ("road", "RDW-001", None, None, None))
        access = SimpleNamespace(record=SimpleNamespace(kind=self.entities.EntityKind.ACCESS, code="ACC-001", name="Entradas"), operation_uid=None)
        with self.assertRaises(ValueError) as caught:
            self.des_ops.GEOBLENDER_OT_des_entity_preview._plan(SimpleNamespace(), VERSION, access)
        self.assertIn("no tiene vista previa: solo la tienen una plataforma, una detección de acopios (sus marcas), un contrafuerte (su zona de coronación) y una pista (su eje)", str(caught.exception))

    def test_f_a_preview_is_of_one_thing(self) -> None:
        """La vista previa de una entidad es de una sola cosa: ninguna, dos o una inserción con una pista son errores del programa; ``cross_segments`` da dos rayas por punto."""
        entity, asked = self.entity, self.dpreview.RoadAsk(code="RDW-001")
        self.assertEqual(entity.EntityPlan(road=asked).kind, "road")
        for bad in ({}, {"road": asked, "code": "PLT-001"}, {"road": asked, "request": object()}, {"road": asked, "insert_before": "PLT-002"}):
            with self.subTest(bad=sorted(bad)), self.assertRaises(ValueError):
                entity.EntityPlan(**bad)
        crosses = entity.cross_segments([(10.0, 20.0), (30.0, 40.0)], 3.0)
        self.assertEqual(crosses.shape, (4, 2, 2))
        np.testing.assert_array_equal(crosses[0], [[7.0, 20.0], [13.0, 20.0]])
        np.testing.assert_array_equal(crosses[3], [[30.0, 37.0], [30.0, 43.0]])
        self.assertEqual(entity.cross_segments([], 3.0).shape, (0, 2, 2))

    # --- RF-015-26, RF-017-26 (e): activar y quitar -----------------------------------------------------

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no corren) hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.entity.tick() is None:
                built = self.entity.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def patched(self, found: Any) -> ExitStack:
        """Lo que hace falta para activarla sin proyecto: el de la sesión, la versión activa, el sello, la preparación y la superficie, sustituidos mientras dura el ``ExitStack``."""
        stack = ExitStack()
        stack.enter_context(mock.patch.object(self.ps, "current", return_value=SimpleNamespace(origin=ORIGIN)))
        stack.enter_context(mock.patch.object(self.scene_versions, "active", return_value=VERSION))
        stack.enter_context(mock.patch.object(self.entity, "stamp", return_value=("sello",)))
        stack.enter_context(mock.patch.object(self.dpreview, "road_preview_steps", side_effect=self.steps_of(found)))
        stack.enter_context(mock.patch.object(self.constraints, "ground_steps", side_effect=_no_ground))
        return stack

    def test_g_it_is_activated_built_by_steps_and_removed_by_every_way_out(self) -> None:
        """RF-015-26, RF-017-26, RNF-017-06 (M5): ``enable`` pone los dos manejadores de dibujo y el temporizador, la construye por pasos (``tick``) con lo de ``design`` y deja el resumen; cambiarla
        (``replace``) la rehace; se quita **con su control**, **al cambiar de proyecto** y **al conmutar a la interfaz de Blender** (``switcher.add_blender_hook``: ida y vuelta deja Blender como estaba, y
        volver no la pone sola); y **no crea ningún objeto** ni escribe nada."""
        entity, switcher = self.entity, self.switcher
        before_fingerprint = blender_ext.state_fingerprint()
        scene = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.curves), len(bpy.data.collections))
        found = self.calculated()
        with self.patched(found):
            entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(request=object())))
            self.assertTrue(entity.enabled() and entity.drawing() and entity.building())
            self.assertTrue(bpy.app.timers.is_registered(entity.tick))
            self.assertIn(entity.disable, switcher.blender_hooks())
            self.assertEqual(entity.plan().kind, "road")
            built = self.pump()
            self.assertIs(entity.preview(), found)
            self.assertEqual([batch.key for batch in built.lines.batches][:2], [entity.SECTION, entity.GRADIENT_WITHIN])
            entity.replace(entity.EntityPlan(road=self.dpreview.RoadAsk(request=object())))  # lo de antes se sigue dibujando hasta que acabe la nueva
            self.assertTrue(entity.building())
            self.assertIs(entity.built(), built)
            self.pump()
            entity.disable()  # el mismo control
            self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
            self.assertIsNone(entity.built())
            self.assertFalse(bpy.app.timers.is_registered(entity.tick))
            self.assertNotIn(entity.disable, switcher.blender_hooks())

            entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(request=object())))  # conmutar a la interfaz de Blender: ida y vuelta
            self.pump()
            window = bpy.context.window_manager.windows[0]
            self.addCleanup(switcher.forget)
            with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
                self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
            self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
            self.assertIsNone(entity.built())
            other_space = next(space.name for space in bpy.data.workspaces if space.name != window.workspace.name)
            with mock.patch.object(switcher, "_marked", return_value={other_space}):
                self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
            self.assertFalse(entity.enabled(), "volver no la pone sola")

            entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(request=object())))  # cerrar el proyecto
            self.pump()
            self.assertIn(entity.on_project_changed, self.ps.listeners())
            entity.on_project_changed(None)
            self.assertFalse(entity.enabled() or entity.drawing())
            self.assertNotIn(entity.on_project_changed, self.ps.listeners())
        diff = blender_ext.fingerprint_diff(before_fingerprint, blender_ext.state_fingerprint())
        mine = [line for line in diff if line.startswith(("draw_handlers", "handlers", "timers")) and "switcher" not in line]
        self.assertEqual(mine, [], diff)  # sin el temporizador que el propio conmutador deja
        self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.curves), len(bpy.data.collections)), scene, "no crea nada en la escena")

    def test_h_a_failing_step_warns_and_removes_it(self) -> None:
        """RF-015-26: si falla un paso de la construcción (una versión o una pista que ya no están), avisa con el motivo y la quita: nunca una traza por fotograma."""
        entity = self.entity

        def failing(*_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("la pista RDW-009 no es de la versión V01")

        with (self.patched(self.calculated()), mock.patch.object(self.dpreview, "road_preview_steps", side_effect=failing), mock.patch.object(self.ps, "notify") as told,
              self.assertLogs("geoblender.bl.draw", level="WARNING")):
            entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(code="RDW-009")))
            for _ in range(MAX_PUMPS):
                if entity.tick() is None:
                    break
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIn("RDW-009", told.call_args.args[0])

    def test_z_disabling_geoblender_with_the_preview_of_a_road_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa de una pista activa (a medio construir), desactivar Geoblender quita los manejadores de dibujo, los ganchos, el temporizador y los lotes, y la huella de Blender
        vuelve a la del principio de la sesión."""
        entity = self.entity
        with self.patched(self.calculated()):
            entity.enable(entity.EntityPlan(road=self.dpreview.RoadAsk(request=object())))
            self.assertTrue(entity.drawing())
            self.assertTrue(bpy.app.timers.is_registered(entity.tick))
            blender_ext.release()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
