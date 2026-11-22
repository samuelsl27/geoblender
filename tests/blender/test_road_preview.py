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
- RF-017-26, RF-015-26 (i): **sobre la superficie de partida elegida** (T50, H3-1): si la partida es la superficie que deja otra entidad (``des_psf_…``) se dibuja sobre ella y la leyenda lo dice; si no se
  puede leer, se dibuja sobre la rejilla más reciente **y la leyenda lo dice**; una rejilla del proyecto, la suya, no la más reciente.
- RF-017-26, RF-015-26 (j): **los nombres no se solapan** (T50, H3-3): el origen, el destino y el tramo más empinado van primero, el resto se salta si cae sobre otro ya puesto y los de lo que se apoya
  en la pista no se saltan; con la vista cerca se dibujan todos.
- Principio 8 (z): desactivar Geoblender con la vista previa de una pista activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
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
REGION_PX = (1920.0, 1080.0)
"""La región de la Vista 3D de la prueba de los nombres (px)."""
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
                             ("des_ops", "bl.ops.des"), ("entities", "design.entities"), ("access", "gis.masks.access"), ("model", "core.project.model"),
                             ("res_surfaces", "reserves.surfaces"), ("gis_messages", "gis.messages"), ("dh_overlay", "bl.draw.dh_overlay")):
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

    # --- RF-017-26, RF-015-26 (i): la superficie de partida elegida (T50, H3-1) ---------------------------

    @contextmanager
    def on_surfaces(self, *, readable: tuple[str, ...]) -> Generator[list[tuple[str, str]], None, None]:
        """Lo que hace falta para leer la superficie de partida sin proyecto: las rejillas del proyecto (``gis_dtm_a14`` y ``gis_dtm_a15``, la más reciente), la lectura de las superficies de
        ``readable`` (cada una, un plano a 130 m; las demás, ``gis.dataset_unknown``) y la interpolación (el plano). Da la lista de lo que se lee: ``(dato, versión)``."""
        read: list[tuple[str, str]] = []
        choices = tuple(SimpleNamespace(name=name, uid=f"uid-{name}", ref=self.res_surfaces.SurfaceRef(dataset=name)) for name in ("gis_dtm_a14", "gis_dtm_a15"))

        def source_of(_project: Any, ref: Any, *, version_uid: str = "") -> Any:
            read.append((ref.dataset, version_uid))
            if ref.dataset not in readable:
                raise self.gis_messages.GisError("gis.dataset_unknown", obj="Superficie", field="superficie", value=ref.dataset)
            return SimpleNamespace(grid=SimpleNamespace(shape=(2, 2), dx=2.0, dy=2.0), header=SimpleNamespace(crs=None, vertical=None))

        def bands_of(_source: Any, grid: Any) -> Any:
            yield 0, np.full(grid.shape, 130.0)

        def raster_of(grid: Any, values: Any, crs: Any, vertical: Any) -> Any:
            return SimpleNamespace(grid=grid, values=values, crs=crs, vertical=vertical)

        with ExitStack() as stack:
            for target, name, replacement in ((self.constraints, "terrain_choices", mock.Mock(return_value=choices)),
                                              (self.constraints, "_latest", mock.Mock(side_effect=lambda _project, found: found[-1])),
                                              (self.res_surfaces, "surface_source", mock.Mock(side_effect=source_of)),
                                              (self.res_surfaces, "band_reader", mock.Mock(side_effect=bands_of)),
                                              (self.constraints, "Raster", mock.Mock(side_effect=raster_of)),
                                              (self.constraints, "sample", mock.Mock(side_effect=lambda _raster, xy, method="bilinear": np.full(len(xy), 130.0)))):
                stack.enter_context(mock.patch.object(target, name, replacement))
            yield read

    def build_from(self, start: str, *, readable: tuple[str, ...]) -> tuple[Any, list[tuple[str, str]]]:
        """Lo construido para una pista calculada que parte de la superficie ``start`` (el nombre de su dato), con la superficie de verdad: ``ground_steps`` sin sustituir, y lo que se leyó."""
        found = replace(self.calculated(), start_surface=start)
        with self.on_surfaces(readable=readable) as read, mock.patch.object(self.dpreview, "road_preview_steps", side_effect=self.steps_of(found)):
            work = self.entity.build_steps(self.request(found))
            while True:
                try:
                    next(work)
                except StopIteration as done:
                    return done.value, read

    def test_i_it_draws_on_the_chosen_start_surface_even_if_it_is_the_one_an_entity_leaves_and_says_so_when_it_cannot_read_it(self) -> None:
        """RF-017-26, RF-015-26 (T50, H3-1): una pista que parte de **la superficie que deja otra entidad** (``des_psf_p1``, la de una plataforma: no es una rejilla del proyecto) se dibuja **sobre ella**
        —se lee ``des_psf_p1`` con la versión activa, como la lee el cálculo, y los lotes siguen su cota— y la leyenda lo dice; si **no se puede leer** se dibuja sobre la rejilla más reciente **y la
        leyenda lo dice** (en los dos idiomas), no en silencio; una rejilla del proyecto es la suya, no la más reciente; y sin partida elegida, la más reciente sin más."""
        entity, constraints = self.entity, self.constraints
        built, read = self.build_from("des_psf_p1", readable=("des_psf_p1", "gis_dtm_a14", "gis_dtm_a15"))
        self.assertEqual((built.lines.surface, read), ("des_psf_p1", [("des_psf_p1", VERSION.uid)]))
        self.assertEqual([row.text for row in built.lines.legend][-1], "Sobre la superficie «des_psf_p1»")
        self.assertFalse([row for row in built.lines.legend if "No se pudo leer" in row.text])
        np.testing.assert_allclose(self.batch(built, entity.AXIS).positions[:, 2], 130.0 - GROUND_M, atol=1e-4)  # los lotes siguen la cota de esa superficie
        with self.assertLogs("geoblender.bl.draw", level="WARNING"):
            built, read = self.build_from("des_psf_p9", readable=("gis_dtm_a14", "gis_dtm_a15"))
        self.assertEqual((built.lines.surface, read), ("gis_dtm_a15", [("des_psf_p9", VERSION.uid), ("gis_dtm_a15", VERSION.uid)]))
        self.assertEqual([row.text for row in built.lines.legend][-2:], ["Sobre la superficie «gis_dtm_a15»",
                                                                       "No se pudo leer la superficie de partida «des_psf_p9»: se usa la rejilla más reciente"])
        self.i18n.set_language("en")
        with self.assertLogs("geoblender.bl.draw", level="WARNING"):
            english, _read = self.build_from("des_psf_p9", readable=("gis_dtm_a14", "gis_dtm_a15"))
        self.assertEqual([row.text for row in english.lines.legend][-2:], ["On the surface «gis_dtm_a15»", "The start surface «des_psf_p9» could not be read: the latest grid is used"])
        self.i18n.set_language("es")
        built, read = self.build_from("gis_dtm_a14", readable=("gis_dtm_a14", "gis_dtm_a15"))
        self.assertEqual((built.lines.surface, read), ("gis_dtm_a14", [("gis_dtm_a14", VERSION.uid)]), "una rejilla del proyecto es la suya, no la más reciente")
        built, read = self.build_from("", readable=("gis_dtm_a14", "gis_dtm_a15"))
        self.assertEqual((built.lines.surface, read, len([row for row in built.lines.legend if row.text.startswith(("Sobre", "No se pudo"))])), ("gis_dtm_a15", [("gis_dtm_a15", VERSION.uid)], 1))
        with self.assertLogs("geoblender.bl.draw", level="WARNING"):  # la elegida es una rejilla del proyecto que no se lee (y es la más reciente): la otra, y lo dice
            built, read = self.build_from("gis_dtm_a15", readable=("gis_dtm_a14",))
        self.assertEqual((built.lines.surface, read), ("gis_dtm_a14", [("gis_dtm_a15", VERSION.uid), ("gis_dtm_a14", VERSION.uid)]))
        self.assertEqual([row.text for row in built.lines.legend][-1], "No se pudo leer la superficie de partida «gis_dtm_a15»: se usa la rejilla más reciente")
        with self.assertLogs("geoblender.bl.draw", level="WARNING"):  # y sin ninguna que se lea: a la cota del GeoOrigin
            built, _read = self.build_from("des_psf_p1", readable=())
        self.assertEqual((built.lines.surface, [row.text for row in built.lines.legend][-1]), ("", "A la cota del GeoOrigin"))
        # la superposición de las restricciones (``_surface_steps`` sin ``exact``) sigue como era: una rejilla elegida que no se lee no se sustituye (a la cota del GeoOrigin) y un nombre que no es de una
        # rejilla del proyecto se olvida (la más reciente, sin intentar leerlo ni decir nada)
        project = SimpleNamespace(origin=ORIGIN)
        with self.on_surfaces(readable=("gis_dtm_a14",)) as read, self.assertLogs("geoblender.bl.draw", level="WARNING"):
            self.assertIsNone(self.finish(constraints._surface_steps(project, "gis_dtm_a15", VERSION.uid, constraints.Pace(0.015))))
        self.assertEqual(read, [("gis_dtm_a15", VERSION.uid)])
        with self.on_surfaces(readable=("des_psf_p1", "gis_dtm_a14", "gis_dtm_a15")) as read:
            forgotten = self.finish(constraints._surface_steps(project, "des_psf_p1", VERSION.uid, constraints.Pace(0.015)))
        self.assertEqual((forgotten.name, forgotten.asked, read), ("gis_dtm_a15", "", [("gis_dtm_a15", VERSION.uid)]))

    @staticmethod
    def finish(work: Any) -> Any:
        """Un generador de pasos llevado hasta el final: su valor."""
        while True:
            try:
                next(work)
            except StopIteration as done:
                return done.value
        rows = constraints.surface_rows
        self.assertEqual([row.text for row in rows(None)], ["A la cota del GeoOrigin"])
        self.assertEqual([row.text for row in rows(constraints.Surface("x", None, asked="y"))][1:], ["No se pudo leer la superficie de partida «y»: se usa la rejilla más reciente"])

    # --- RF-017-26, RF-015-26 (j): los nombres no se solapan (T50, H3-3) -----------------------------------

    def view(self, pixels_per_m: float) -> np.ndarray:
        """La matriz de una vista ortogonal de la región de 1920 × 1080 px que enseña ``pixels_per_m`` px por metro con el sitio local (170, 50) —el medio del eje de la prueba— en el centro."""
        sx, sy = pixels_per_m / (REGION_PX[0] / 2.0), pixels_per_m / (REGION_PX[1] / 2.0)
        return np.array([[sx, 0.0, 0.0, -170.0 * sx], [0.0, sy, 0.0, -50.0 * sy], [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]])

    def drawn_labels(self, built: Any, pixels_per_m: float, *, char_px: float) -> list[Any]:
        """Los nombres (``bl.draw.dh_overlay.Text``) que dibuja ``screen_items`` con la vista de ``pixels_per_m`` px por metro y letras de ``char_px`` px de ancho."""
        names = {label.text for label in built.lines.labels}
        items = self.constraints.screen_items(built.lines, self.view(pixels_per_m), REGION_PX, measure=lambda text: char_px * len(text), scale=1.0)
        return [item for item in items if isinstance(item, self.dh_overlay.Text) and item.text in names]

    def test_j_the_names_do_not_overlap_the_origin_the_destination_and_the_steepest_stretch_go_first(self) -> None:
        """RF-017-26, RF-015-26 (T50, H3-3; M5): los nombres de una pista llevan su rango —el origen y el destino 2, el tramo más empinado 1, los demás 0, y los de lo que se apoya en ella ninguno—
        y ``screen_items`` **no dibuja dos nombres que se solapen** (a menos de una altura de texto uno de otro y con sus cajas encima): con la vista cerca (6 px/m, letras de 2 px) se dibujan **los ocho**;
        con la vista a 0,5 px/m, el origen y el destino y solo los tramos que no caen sobre ellos ni sobre otro ya puesto; con la vista lejos (0,05 px/m: toda la pista en 15 px) queda el origen, el
        primero. Los nombres de lo que se apoya no se saltan (y los demás los esquivan)."""
        dp = self.dpreview
        plain = self.build(self.calculated())
        labels = plain.lines.labels
        self.assertEqual([label.rank for label in labels[:2]], [2, 2], "el origen y el destino")
        self.assertEqual(sorted(label.rank for label in labels[2:]), [0, 0, 0, 0, 0, 1])
        self.assertTrue(next(label for label in labels[2:] if label.rank == 1).text.startswith("12,0 %"), "el más empinado")
        ring = np.array([self.absolute(*point) for point in ((100.0, 52.0), (160.0, 52.0), (160.0, 90.0), (100.0, 90.0), (100.0, 52.0))])
        held = self.build(self.calculated(resting=(dp.RestingItem("Ramal", "RDW-002", "des.road", "current", 1500.0, (ring,)),)))
        self.assertIsNone(held.lines.labels[-1].rank, "lo que se apoya en la pista no se salta")
        self.assertEqual(len(self.drawn_labels(plain, 6.0, char_px=2.0)), 8, "con la vista cerca, todos")
        middle = [item.text for item in self.drawn_labels(plain, 0.5, char_px=2.0)]
        self.assertTrue(any(text.startswith("Origen") for text in middle) and any(text.startswith("Destino") for text in middle) and len(middle) < 8, middle)
        for pixels in (6.0, 0.5, 0.05):
            shown = self.drawn_labels(plain, pixels, char_px=2.0)
            with self.subTest(pixels_per_m=pixels):
                self.assertTrue(shown)
                for index, one in enumerate(shown):
                    for other in shown[index + 1:]:
                        overlap = abs(one.y - other.y) < self.constraints.FONT_PX and one.x < other.x + 2.0 * len(other.text) and other.x < one.x + 2.0 * len(one.text)
                        self.assertFalse(overlap, (one.text, other.text))
        self.assertEqual([item.text for item in self.drawn_labels(plain, 0.05, char_px=2.0)], ["Origen · rasante 100,00 m"], "toda la pista en 15 px: queda el origen")
        self.assertIn("Ramal", " ".join(item.text for item in self.drawn_labels(held, 0.05, char_px=2.0)), "lo que no tiene rango se dibuja siempre")
        # la altura de un texto es la de la letra por la escala de la interfaz: dos nombres 15 px uno sobre otro caben a escala 1 (12 px) y no a escala 2 (24 px)
        two = self.constraints.Built(None, "", "", "", (), (self.constraints.Label("uno", (170.0, 50.0, 0.0), (1.0, 1.0, 1.0, 1.0), 0), self.constraints.Label("dos", (170.0, 65.0, 0.0), (1.0, 1.0, 1.0, 1.0), 0)), (), ())
        for scale, wanted in ((1.0, ["uno", "dos"]), (2.0, ["uno"])):
            items = self.constraints.screen_items(two, self.view(1.0), REGION_PX, measure=lambda text: 20.0, scale=scale)
            self.assertEqual([item.text for item in items if isinstance(item, self.dh_overlay.Text)], wanted, scale)
        plain_labels = tuple(self.constraints.Label(name, (170.0, 50.0, 0.0), (1.0, 1.0, 1.0, 1.0)) for name in ("uno", "dos"))  # sin rango (lo de las demás vistas previas): se dibujan siempre
        items = self.constraints.screen_items(self.constraints.Built(None, "", "", "", (), plain_labels, (), ()), self.view(1.0), REGION_PX, measure=lambda text: 20.0, scale=1.0)
        self.assertEqual([item.text for item in items if isinstance(item, self.dh_overlay.Text)], ["uno", "dos"], "los nombres sin rango no se tocan")

    def test_k_every_preview_legend_says_the_surface_it_is_drawn_on_and_when_it_could_not_read_the_start(self) -> None:
        """RF-015-26, RF-017-26 (T50, H3-1): la leyenda de la plataforma, de las marcas de una detección de acopios, de la zona de un contrafuerte y de la pista (**las cuatro vistas previas de
        ``bl.draw.entity``**) y la de las restricciones dicen sobre qué superficie se dibuja y, si no se pudo leer la de partida, **lo dicen** (la fila de ``constraints.surface_rows``); sin superficie,
        la cota del GeoOrigin."""
        entity, constraints = self.entity, self.constraints
        request = SimpleNamespace(language="es", version_code="V01", version_uid="uid-v01")
        found = SimpleNamespace(name="Pieza", code="X-001", version="V01", area_m2=1.0, resting=(), declares=None, guard_m=None, zone_area_m2=0.0, marks=(), drawable=True, max_mean_gradient_pct=1.0,
                                max_gradient_pct=1.0, section_m=1.0, carriageway_m=1.0, length_m=1.0, corridor_nodes=0, margin_m=1.0, target_level_m=None, target_tolerance_m=None)
        legends = {"platform": entity._legend, "stockpile": entity._stockpile_legend, "buttress": entity._buttress_legend, "road": entity._road_legend}
        asked = constraints.Surface("gis_dtm_a15", None, asked="des_psf_p1")
        for kind, legend in legends.items():
            with self.subTest(kind=kind):
                self.assertEqual([row.text for row in legend(request, found, constraints.Surface("des_psf_p1", None), set())][-1], "Sobre la superficie «des_psf_p1»")
                self.assertEqual([row.text for row in legend(request, found, asked, set())][-2:], ["Sobre la superficie «gis_dtm_a15»",
                                                                                                  "No se pudo leer la superficie de partida «des_psf_p1»: se usa la rejilla más reciente"])
                self.assertEqual([row.text for row in legend(request, found, None, set())][-1], "A la cota del GeoOrigin")
        rows = constraints._legend(constraints.Request(object(), None, "", "", "es", ()), "", {}, 0, False, False, asked)
        self.assertEqual([row.text for row in rows][-2:], ["Sobre la superficie «gis_dtm_a15»", "No se pudo leer la superficie de partida «des_psf_p1»: se usa la rejilla más reciente"])

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
