# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de una entidad de diseño (spec 015, T29; HU-015-3; RF-015-26, RF-015-25; RNF-015-06;
plan 015 §5.1, §5.3.3 y §5.5; comprobación manual M4).

La vista previa de la Vista 3D (``bl.draw.entity``, el botón «Vista previa» del diálogo de «Plataforma…» y
``geoblender.des_entity_preview``) es un manejador de dibujo **sin objetos ni escritura**: dibuja antes de calcular
la huella de una plataforma, su eje con la flecha de su sentido, las cotas de la rasante en sus extremos, lo que se le
apoya y las restricciones que declarará, con su leyenda. Lo que dibuja se prueba en sus lotes, sus nombres y sus
textos en píxeles, no en píxeles de pantalla (``docs/trampas.md`` §3: sin GPU en ``blender -b``).

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, la ladera
``100 + 0,25·y + 0,0625·x``, las máscaras de V01 al día) con tres entidades hechas con las órdenes reales en V01:
«Carga» (PLT-001, eje de (20, 30) a (40, 30), 8 m de ancho, rasante de 105 m al 0 %: 10 × 4 = 40 celdas), «Taller» (PLT-002,
**parte de la superficie** de «Carga») y «Sobre Carga» (PLT-003, de otro terreno, «en corte y relleno»: **se apoya** en
«Carga»). Las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-015-26 (a): ``geoblender.des_entity_preview`` es una orden real (con el ``poll`` de las de Diseño: dice por qué
  no está disponible, salvo para quitarla); su propiedad tiene nombre y descripción; el diálogo de «Plataforma…»
  dibuja el botón «Vista previa» (la misma orden con la propiedad oculta ``preview`` y todo lo pedido).
- RF-015-26 (b): el mundo, con las órdenes reales.
- RF-015-26 (c): activar la vista previa de la plataforma que se prepara: la huella, el eje con su flecha, las cotas de
  los extremos (a mano), la leyenda y el resumen son los de ``design``, en los dos idiomas; **nada escrito en el
  proyecto ni creado en la escena**; el mismo control la quita.
- RF-015-26, RF-015-10 (d): si protege, la zona que declarará con su resguardo (a mano, por fuerza bruta), su nombre
  y su fila en la leyenda.
- RF-015-26, RF-015-08, RF-015-09 (e): lo que rechazaría «Calcular» (la geometría, el modo, la falta de dato) es el
  aviso de la vista previa, con el mismo mensaje y en lugar del dibujo; sin las máscaras al día, también; cambiar de
  versión la rehace.
- RF-015-26, RF-015-15 (f): la de una entidad de la versión (la seleccionada o por su código): lo que se le apoya
  con sus huellas, su nombre y su volumen, que son los de ``design.entities.dependents``; lo que no se puede
  previsualizar (otra versión, sin entidad, sin calcular) se dice.
- RF-015-26 (g): cambiar un campo del diálogo redibuja; uno a medias no.
- RF-015-26 (h): se quita al cancelar la orden (su diálogo y su ventana de confirmar), al crear la plataforma y al
  **conmutar a la interfaz de Blender**, y volver deja Blender como estaba.
- RF-015-26, RNF-015-06 (i): con 200 entidades, activarla ≤ 1 s y cada redibujo ≤ 5 ms.
- Principio 8 (z): desactivar Geoblender con la vista previa activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import statistics
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.blender import test_design_preview as preview_tests
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw, operator_self

PREVIEW = "geoblender.des_entity_preview"
WM_PROPERTY = "geoblender_design_preview"
OVER = "Sobre Carga"
LOADING, WORKSHOP, NO_WIDTH = platform_ops.LOADING, platform_ops.WORKSHOP, platform_ops.NO_WIDTH
WEST, SOUTH, STEP_M = platform_ops.WEST, platform_ops.SOUTH, platform_ops.STEP_M
NEW = "Previa"
MAX_PUMPS = 20_000
SIZE = (1920.0, 1080.0)
"""La región de la Vista 3D de los redibujos: la de la barra a 1920 px de las comprobaciones manuales."""
ACTIVATE_BUDGET_S = 1.0  # RNF-015-06
REDRAW_BUDGET_S = 0.005  # RNF-015-06
ENTITIES = 200  # RNF-015-06
TICK_WAIT_S = 0.005  # bl.draw.entity.TICK_INTERVAL_S (lo comprueba la prueba)
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")


def _module(name: str) -> Any:
    return platform_ops._module(name)


class EntityPreviewTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con una capa más y otros
    dos terrenos (de cada superficie parte una sola entidad)."""

    ground2: str
    ground3: str

    @classmethod
    def setUpClass(cls) -> None:
        extra = (OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0)
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, extra)):
            super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.ground3 = cls.write_grid("Ladera 3", platform_ops.ground())
        cls.refresh()
        cls.entity = _module("bl.draw.entity")
        cls.design_draw = _module("bl.draw.design")
        cls.constraints = _module("bl.draw.constraints")
        cls.dpreview = _module("design.preview")
        cls.dmodel = _module("design.model")
        cls.switcher = _module("bl.ui.switcher")
        cls.access = _module("gis.masks.access")
        cls.grid = _module("gis.grid").project_grid(cls.project.record.window, float(cls.project.record.grid_step_m))
        cls.addClassCleanup(cls.entity.disable)

    def tearDown(self) -> None:
        if self.entity.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.entity.disable()
        super().tearDown()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no corren) hasta que
        acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.entity.tick() is None:
                built = self.entity.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def request_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo para la plataforma que se prepara: «Previa» con la geometría de «Carga», sobre el
        tercer terreno (cada superficie, una entidad), con el borde a 35° y 10 m de alcance; cambiado por ``values``."""
        return self.form(**{"name": NEW, "feature": LOADING, "start": self.ground3, **values})

    def show(self, **values: Any) -> set[str]:
        """El botón «Vista previa» del diálogo: la orden de la plataforma con ``preview`` y lo pedido."""
        return bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", preview=True, **self.request_form(**values))

    def set_active(self, version: Any) -> None:
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=version.uid), {"FINISHED"})

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas de la prueba (desde el SO de la ventana) respecto al GeoOrigin."""
        return (WEST + x - self.origin.x0, SOUTH + y - self.origin.y0)

    def ground_z(self, x: float, y: float) -> float:
        """La cota local de la ladera en (x, y) de la prueba."""
        return 100.0 + 0.25 * y + 0.0625 * x - self.origin.z0

    def absolute(self, batch: Any) -> tuple[np.ndarray, np.ndarray]:
        """Los segmentos ``(k, 2, 2)`` absolutos de un lote y la cota local de sus vértices."""
        xyz = batch.positions.astype(np.float64)
        xy = xyz[:, :2] + np.array([self.origin.x0, self.origin.y0], dtype=np.float64)
        return xy.reshape(-1, 2, 2), xyz[:, 2]

    def batch(self, built: Any, key: str) -> Any:
        return built.lines.batch(key, self.constraints.OUTLINE)

    def legend(self, built: Any) -> list[str]:
        return [row.text for row in built.lines.legend]

    def cells_mask(self, rows: range, cols: range) -> np.ndarray:
        mask = np.zeros(self.grid.shape, dtype=bool)
        mask[rows.start:rows.stop, cols.start:cols.stop] = True
        return mask

    def footprint_of_loading(self) -> np.ndarray:
        """La huella de «Carga» a mano: x de 20 a 40 (columnas 10 a 19) e y de 26 a 34 (filas 13 a 16)."""
        return self.cells_mask(range(13, 17), range(10, 20))

    def untouched(self) -> tuple[Any, ...]:
        """Lo que la vista previa no cambia: el proyecto (operaciones, datos, parámetros, cifras y ficheros) y la
        escena (objetos y mallas)."""
        return (self.state(), len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))

    def message_of_calculate(self, **values: Any) -> str:
        """El texto con que «Calcular» rechaza lo pedido (lo que dice el error de la orden)."""
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.request_form(**values))
        return str(caught.exception)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_the_property_and_the_button_of_the_dialog(self) -> None:
        """RF-015-26, RF-015-28 (plan §5.3.3, §5.5; M4): ``geoblender.des_entity_preview`` es una orden real (no la
        provisional) con el ``poll`` de las de Diseño —dice por qué no está disponible—, salvo para quitar la vista
        previa; su propiedad tiene nombre y descripción; es una interna del catálogo de la entrada 015. El diálogo
        de «Plataforma…» dibuja el botón «Vista previa»: la misma orden con ``preview`` y todo lo pedido, sin abrir
        otro diálogo; ``preview`` es una propiedad oculta (sin nombre ni descripción)."""
        cls = self.commands.registered_class(PREVIEW)
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.bl_idname, cls.bl_options, cls.provenance_op_type), (PREVIEW, {"REGISTER"}, "des.platform"))
        command = self.commands.catalog().commands[PREVIEW]
        self.assertEqual((command.kind, command.entry, command.label_es), ("internal", "015", "Vista previa de la entidad"))
        keywords = cls.__annotations__["entity"].keywords
        self.assertEqual((keywords["name"], keywords["description"]),
                         ("Entidad", self.i18n.translate("es", "Code or name of the design entity to preview (empty: the "
                                                               "one of the object selected in the 3D view)")))
        self.assertTrue(cls.poll(bpy.context))
        for reason in ("Abra un proyecto", "Proyecto en solo lectura: prueba"):
            with mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                self.assertFalse(cls.poll(bpy.context), reason)
        self.assertFalse(self.entity.enabled())

        platform = self.cls
        self.assertIn("preview", platform.__annotations__)
        self.assertNotIn("name", platform.__annotations__["preview"].keywords)  # la pone quien la lanza
        self.assertNotIn("preview", {name for name in platform.__annotations__ if name not in self.des_ops._PLATFORM_HIDDEN})
        shown = draw(platform, bpy.context, confirm=False, **{**self.drawn_fields(), "name": NEW, "feature": LOADING})
        (button,) = [item for item in shown.of_kind("operator") if item.target == platform_ops.PLATFORM]
        self.assertEqual((button.text, button.icon, button.operator_context), ("Vista previa", "HIDE_OFF", "EXEC_DEFAULT"))
        self.assertEqual(vars(button.properties), {**self.drawn_fields(), "name": NEW, "feature": LOADING, "preview": True})

    def drawn_fields(self) -> dict[str, Any]:
        """Lo que dibuja el diálogo por defecto (los campos de la orden, sin las propiedades ocultas salvo ``insert_before``
        —la entidad que se inserta, vacía—, que el botón «Vista previa» también lleva: T31)."""
        return {"name": platform_ops.LOADING, "layer": platform_ops.LAYER, "feature": platform_ops.LOADING,
                "start_level_field": "cota_inicial", "gradient_field": "pendiente", "width_field": "ancho",
                "axis_layer": "none", "axis_field": "eje", "start_level": "", "gradient": "", "width": "",
                "start": self.ground3, "support": "none", "mode": "CUT", "edge_angle": "35", "reach": "10",
                "mesh_factor": "", "metric": "EXACT", "counter_tolerance": "", "protect": False, "guard": "",
                "insert_before": ""}

    def test_b_three_entities_are_made_with_the_real_commands(self) -> None:
        """RF-015-26 (el mundo de estas pruebas): «Carga» corta del todo; «Taller» parte de la superficie de «Carga» y
        «Sobre Carga», de otro terreno, se apoya en ella; las tres al día y las máscaras de V01 también."""
        self.made()
        self.made(name=WORKSHOP, feature=WORKSHOP, start="entity:PLT-001", start_level="107,5", gradient="0",
                  width="5", reach="6")
        self.made(name=OVER, feature=OVER, start=self.ground2, mode="CUT_FILL")
        registry = self.entities.registry(self.project, self.v01.uid)
        self.assertEqual({entry.record.name: (entry.record.code, str(entry.record.state)) for entry in registry},
                         {LOADING: ("PLT-001", "current"), WORKSHOP: ("PLT-002", "current"), OVER: ("PLT-003", "current")})
        self.assertIs(self.access.mask_state(self.project, self.v01.uid)[0], self.access.MaskState.CURRENT)

    def test_c_the_footprint_the_axis_with_its_arrow_and_the_levels_at_its_ends(self) -> None:
        """RF-015-26 (M4): el botón «Vista previa» activa la de la plataforma que se prepara, sin calcular ni escribir
        nada en el proyecto ni crear objetos en la escena (ni un cálculo abierto); se construye por pasos con el
        temporizador. Con la cota inicial de la capa (105 m) y una pendiente del 2 % corregida en el diálogo: **la
        huella** de 40 celdas (de x = 20 a 40 e y = 26 a 34), su borde, lado a lado, igual al de sus celdas, sobre la
        ladera; **el eje** de (20, 30) a (40, 30) y **la flecha de su sentido**, que sale de su último vértice hacia atrás
        a 25° de él; las cotas de la rasante en los extremos (a mano: 105 y 105 + 20·2/100 = 105,4 m) junto a cada uno,
        con la abscisa 0 en el primero; la leyenda con una fila por pieza y el resumen de ``design``, en español y en
        inglés. Lo que se le apoya no sale (es una entidad nueva) y no declara nada. El mismo control la quita."""
        entity = self.entity
        before = self.untouched()
        self.assertEqual(self.show(gradient="2"), {"FINISHED"})
        self.assertTrue(entity.enabled() and entity.drawing() and entity.building())
        self.assertEqual(entity.plan().request.name, NEW)
        self.assertIsNone(entity.plan().code)
        self.assertIsNone(self.des_ops.calculation())
        self.assertFalse(self.design_draw.enabled())
        self.assertIn(entity.disable, self.switcher.blender_hooks())
        built = self.pump()
        self.assertFalse(entity.building())
        self.assertEqual((built.lines.version_code, built.lines.masks, built.lines.surface), ("V01", "current", self.ground3))
        self.assertIsNone(built.seeds)
        self.assertEqual(built.sectors, ())
        keys = [batch.key for batch in built.lines.batches]
        self.assertEqual(keys, [entity.FOOTPRINT, entity.AXIS, entity.ARROW])
        self.assertEqual({batch.role for batch in built.lines.batches}, {self.constraints.OUTLINE})
        shown = entity.preview()
        self.assertEqual((shown.name, shown.code, shown.cells, shown.area_m2, shown.length_m), (NEW, "PLT-004", 40, 160.0, 20.0))
        self.assertEqual((shown.resting, shown.protects, shown.zone, shown.declares), ((), False, (), None))

        footprint = self.batch(built, entity.FOOTPRINT)  # la huella: el borde de sus celdas, sobre la ladera
        self.assertEqual(footprint.color, entity.FOOTPRINT_COLOR)
        segments, height = self.absolute(footprint)
        self.assertEqual(preview_tests.covered_edges(segments, self.grid), preview_tests.unit_edges(self.footprint_of_loading()))
        for (x0, y0), (x1, y1) in segments.tolist():
            self.assertTrue(WEST + 20.0 <= min(x0, x1) and max(x0, x1) <= WEST + 40.0)
            self.assertTrue(SOUTH + 26.0 <= min(y0, y1) and max(y0, y1) <= SOUTH + 34.0)
        xy = footprint.positions[:, :2].astype(np.float64) + [self.origin.x0 - WEST, self.origin.y0 - SOUTH]
        np.testing.assert_allclose(height, [self.ground_z(x, y) for x, y in xy], atol=2e-3)

        axis = self.batch(built, entity.AXIS)  # el eje, de (20, 30) a (40, 30)
        axis_segments, _height = self.absolute(axis)
        self.assertEqual(axis_segments[0, 0].tolist(), [WEST + 20.0, SOUTH + 30.0])
        self.assertEqual(axis_segments[-1, 1].tolist(), [WEST + 40.0, SOUTH + 30.0])
        self.assertTrue(np.all(axis_segments[:, :, 1] == SOUTH + 30.0))

        arrow = self.batch(built, entity.ARROW)  # la flecha: sale del último vértice, hacia atrás, a ±25°
        arrow_segments, _height = self.absolute(arrow)
        self.assertEqual(arrow_segments.shape, (2, 2, 2))
        np.testing.assert_allclose(arrow_segments[:, 0], [[WEST + 40.0, SOUTH + 30.0]] * 2, atol=1e-4)
        signs = set()
        for tip in arrow_segments[:, 1]:
            back = tip - arrow_segments[0, 0]
            self.assertAlmostEqual(float(np.hypot(*back)), 4.0, places=3)  # dos celdas: más que la décima parte del eje (2 m)
            self.assertLess(back[0], 0.0)  # hacia atrás: contra el sentido del eje
            self.assertAlmostEqual(abs(float(np.degrees(np.arctan2(back[1], -back[0])))), 25.0, places=3)
            signs.add(float(np.sign(back[1])))
        self.assertEqual(signs, {1.0, -1.0})  # uno a cada lado del eje

        labels = {label.text: label for label in built.lines.labels}
        self.assertEqual(sorted(labels), ["Final · rasante 105,40 m", "Inicio (abscisa 0) · rasante 105,00 m"])
        for text, (x, y) in (("Inicio (abscisa 0) · rasante 105,00 m", (20.0, 30.0)), ("Final · rasante 105,40 m", (40.0, 30.0))):
            label = labels[text]
            np.testing.assert_allclose(label.xyz[:2], self.local(x, y), atol=1e-3)
            self.assertAlmostEqual(label.xyz[2], self.ground_z(x, y), places=3)
        self.assertEqual((shown.ends[0].which, shown.ends[0].level_m, shown.ends[1].which, shown.ends[1].level_m),
                         ("start", 105.0, "end", 105.4))
        self.assertEqual(self.legend(built), [
            "Vista previa de «Previa» (PLT-004) · V01", "Huella (160 m²)",
            "Eje: la flecha muestra su sentido; la abscisa 0 está en su primer vértice",
            "Cota de la rasante de la plataforma en los extremos del eje (m)", f"Sobre la superficie «{self.ground3}»"])
        self.assertEqual([row.color is None for row in built.lines.legend], [True, False, False, True, True])
        self.assertEqual(
            built.summary,
            (("Vista previa de «Previa» (PLT-004) en V01: huella de 40 celdas (160 m²), eje de 20,0 m, rasante de 105,00 m "
              "en su primer vértice (abscisa 0) a 105,40 m en el último, pendiente del 2,00 %.", False),
             ("No protege su huella: no declara ninguna restricción.", False)))
        self.assertEqual([(line.name, line.alert) for line in self.view.preview], list(built.summary))
        self.assertEqual(self.untouched(), before)  # nada escrito en el proyecto ni creado en la escena

        self.i18n.set_language("en")  # en inglés todo sale en inglés
        entity.rebuild()
        english = self.pump()
        self.assertEqual(self.legend(english)[:2], ["Preview of «Previa» (PLT-004) · V01", "Footprint (160 m²)"])
        self.assertTrue(english.summary[0][0].startswith("Preview of «Previa» (PLT-004) in V01: footprint of 40 cells (160 m²)"))
        self.assertEqual(english.summary[1][0], "It does not protect its footprint: it declares no constraint.")
        self.assertIn("End · level 105.40 m", {label.text for label in english.lines.labels})
        self.i18n.set_language("es")

        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})  # el mismo control la quita
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(len(self.view.preview), 0)
        self.assertFalse(bpy.app.timers.is_registered(entity.tick))
        self.assertNotIn(entity.disable, self.switcher.blender_hooks())
        self.assertEqual(self.untouched(), before)

    def test_d_a_platform_that_protects_shows_the_zone_it_will_declare_with_its_guard(self) -> None:
        """RF-015-26, RF-015-10 (M4): si protege (con un resguardo de 4 m), la vista previa enseña **la zona que declarará**:
        las celdas a ≤ 4 m de la huella (por fuerza bruta, a mano) con su contorno lado a lado, en el color de su tipo
        («sin relleno»), su nombre como se leerá («Plataforma Previa (declarada) · resguardo 4,0 m») y su fila en la
        leyenda; el resumen dice su área; sin resguardo no hay zona que dibujar y la orden la rechaza."""
        entity, constraints = self.entity, self.constraints
        self.assertEqual(self.show(protect=True, guard="4"), {"FINISHED"})
        built = self.pump()
        shown = entity.preview()
        footprint = self.footprint_of_loading()
        rows, cols = np.indices(self.grid.shape)
        near = np.zeros(self.grid.shape, dtype=bool)
        for row, col in zip(*np.nonzero(footprint), strict=True):
            near |= np.hypot(rows - row, cols - col) * STEP_M <= 4.0 + 1e-9
        self.assertLess(int(near.sum()) * 4, 1000)  # sin separador de miles en el texto
        self.assertGreater(int(near.sum()), 40)
        self.assertEqual((shown.zone_cells, shown.zone_area_m2), (int(near.sum()), int(near.sum()) * 4.0))
        self.assertTrue(shown.protects and shown.guard_m == 4.0)
        no_fill = _module("core.constraints.model").ConstraintType.NO_FILL
        self.assertIs(shown.declares, no_fill)
        zone = self.batch(built, entity.ZONE)
        self.assertEqual(zone.color, constraints.color_of(no_fill.value))
        segments, _height = self.absolute(zone)
        self.assertEqual(preview_tests.covered_edges(segments, self.grid), preview_tests.unit_edges(near))
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.FOOTPRINT, entity.AXIS, entity.ARROW, entity.ZONE])
        name = next(label for label in built.lines.labels if label.text.startswith("Plataforma Previa (declarada)"))
        self.assertEqual(name.text, "Plataforma Previa (declarada) · resguardo 4,0 m")
        self.assertEqual(name.color, zone.color)
        self.assertIn(f"Declara «Sin relleno» con un resguardo de 4,0 m ({int(near.sum()) * 4} m²)", self.legend(built))
        self.assertEqual(built.summary[1], (f"Declarará su huella como una zona protegida con un resguardo de 4,0 m: "
                                            f"{int(near.sum()) * 4} m² con el resguardo.", False))
        self.assertEqual(self.untouched()[0], self.state())
        entity.disable()

        self.assertEqual(self.show(protect=True, guard="0"), {"FINISHED"})  # resguardo 0: la propia huella
        zero = self.pump()
        self.assertEqual(entity.preview().zone_cells, 40)
        segments, _height = self.absolute(self.batch(zero, entity.ZONE))
        self.assertEqual(preview_tests.covered_edges(segments, self.grid), preview_tests.unit_edges(footprint))
        entity.disable()

        text = self.message_of_calculate(protect=True, guard="")  # sin resguardo: lo rechaza «Calcular»
        self.assertEqual(self.show(protect=True, guard=""), {"FINISHED"})
        refused = self.pump()
        self.assertEqual(refused.lines.batches, ())
        self.assertIn(refused.summary[0][0], text)
        self.assertTrue(refused.summary[0][1])

    def test_e_what_calculate_would_refuse_is_the_warning_of_the_preview_instead_of_the_drawing(self) -> None:
        """RF-015-26, RF-015-08, RF-015-09, RF-015-12 (M4): lo que rechazaría «Calcular» —proteger en «corte y relleno»,
        una geometría sin el ancho en su capa— es el aviso de la vista previa, con **el mismo mensaje** (en alerta y en
        el idioma de Geoblender) y **en lugar del dibujo**: ningún lote, ningún nombre, solo la leyenda con su título;
        la falta de dato en la superficie de partida (RF-015-09) también. Sin las máscaras de la versión al día no se
        puede dibujar y lo dice; cambiar de versión la rehace; todo sin escribir nada."""
        entity = self.entity
        hole = np.array(platform_ops.ground(), dtype=np.float64)  # sin dato en la huella (x de 24 a 28, y de 28 a 32)
        hole[14:16, 12:14] = np.nan
        empty = self.write_grid("Ladera con hueco", hole)  # lo único que escribe esta prueba: antes de mirar
        self.refresh()
        before = self.untouched()
        for what, values, wanted in (
                ("proteger en corte y relleno (RF-015-12)", {"mode": "CUT_FILL", "protect": True, "guard": "4"}, "corte y relleno"),
                ("una geometría sin el ancho (RF-015-08)", {"feature": NO_WIDTH}, "ancho")):
            with self.subTest(pedido=what):
                text = self.message_of_calculate(**values)
                self.assertEqual(self.show(**values), {"FINISHED"})
                built = self.pump()
                self.assertEqual((built.lines.batches, built.lines.labels, built.seeds), ((), (), None))
                ((warning, alert), *rest) = built.summary
                self.assertEqual(rest, [])
                self.assertTrue(alert)
                self.assertIn(warning, text, "el mismo mensaje que «Calcular»")
                self.assertIn(wanted, warning.lower())
                self.assertEqual(self.legend(built), ["Vista previa de «Previa» · V01"])
                self.assertIsNotNone(entity.preview().refusal)
                self.assertFalse(entity.preview().drawable)
                self.assertEqual([(line.name, line.alert) for line in self.view.preview], [(warning, True)])
                self.i18n.set_language("en")
                entity.rebuild()
                self.assertNotEqual(self.pump().summary[0][0], warning)  # y en inglés, en inglés
                self.i18n.set_language("es")
                entity.disable()

        text = self.message_of_calculate(start=empty)
        self.assertEqual(self.show(start=empty), {"FINISHED"})
        nodata = self.pump()
        self.assertEqual(nodata.lines.batches, ())
        self.assertIn(nodata.summary[0][0], text)
        self.assertIn("no tienen dato", nodata.summary[0][0])
        entity.disable()

        self.assertEqual(self.show(), {"FINISHED"})  # sin las máscaras de la versión al día: lo dice, no dibuja
        self.assertEqual(self.pump().lines.masks, "current")
        self.set_active(self.v02)
        self.assertTrue(entity.building())
        other = self.pump()
        self.assertEqual((other.lines.version_code, other.lines.masks, other.lines.batches), ("V02", "missing", ()))
        self.assertTrue(other.summary[0][0].startswith("Las máscaras de V02 no se han compilado, así que no se puede dibujar "
                                                       "la vista previa de «Previa»"))
        self.assertTrue(other.summary[0][1])
        self.assertEqual(self.legend(other), ["Vista previa de «Previa» · V02"])
        self.set_active(self.v01)
        self.assertEqual(len(self.pump().lines.batches), 3)
        entity.disable()
        self.assertEqual(self.untouched(), before)

    def test_f_the_preview_of_an_entity_of_the_version_shows_what_rests_on_it(self) -> None:
        """RF-015-26, RF-015-15 (M4): la de una entidad de la versión (por su código o la del objeto seleccionado en
        la Vista 3D), con sus parámetros vigentes: lo que se le apoya y lo que parte de su superficie, con las
        huellas de las entidades (de «Sobre Carga», las mismas celdas que las de «Carga»; de «Taller», las suyas), su
        nombre y su volumen, que son los de ``design.entities.dependents`` (y la leyenda y el resumen lo cuentan); lo
        que se le apoya queda en su lote, con su nombre; la entidad sin nada apoyado lo dice. Lo que no se puede
        previsualizar —una entidad que no es de la versión, sin objeto seleccionado, de otra versión, sin calcular— se dice
        y no activa nada."""
        entity = self.entity
        before = self.untouched()
        truth = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertEqual({row.name for row in truth}, {WORKSHOP, OVER})
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="PLT-001"), {"FINISHED"})
        self.assertEqual(entity.plan().code, "PLT-001")
        self.assertIsNone(entity.plan().request)
        built = self.pump()
        shown = entity.preview()
        self.assertEqual((shown.name, shown.code, shown.cells, shown.area_m2), (LOADING, "PLT-001", 40, 160.0), built.summary)
        self.assertEqual([(item.name, item.entity, item.op_type, item.state, item.volume_m3) for item in shown.resting],
                         [(row.name, row.entity, row.op_type, row.state.value, row.volume_m3) for row in truth])
        over = next(item for item in shown.resting if item.name == OVER)
        self.assertGreater(over.volume_m3, 0.0)
        workshop = next(item for item in shown.resting if item.name == WORKSHOP)
        self.assertIsNone(workshop.volume_m3)
        outline = np.vstack(over.rings)  # las mismas celdas que «Carga»
        self.assertEqual([outline.min(axis=0).tolist(), outline.max(axis=0).tolist()],
                         [[WEST + 20.0, SOUTH + 26.0], [WEST + 40.0, SOUTH + 34.0]])
        outline = np.vstack(workshop.rings)
        self.assertEqual((outline.min(axis=0)[0], outline.max(axis=0)[0]), (WEST + 20.0, WEST + 40.0))
        self.assertTrue(SOUTH + 40.0 <= outline.min(axis=0)[1] < outline.max(axis=0)[1] <= SOUTH + 48.0)
        resting = self.batch(built, entity.RESTING)
        self.assertEqual(resting.color, entity.RESTING_COLOR)
        segments, _height = self.absolute(resting)
        entity_store = _module("design.entity_store")
        with self.project.read() as conn:
            workshop_cells = entity_store.runs_mask(
                entity_store.read_entity_footprint(conn, self.entity_table(conn, "PLT-002")).runs, self.grid.shape)
        self.assertEqual(preview_tests.covered_edges(segments, self.grid),  # el borde de sus celdas, lado a lado
                         preview_tests.unit_edges(self.footprint_of_loading()) | preview_tests.unit_edges(workshop_cells))
        labels = {label.text for label in built.lines.labels}
        self.assertIn(f"«{OVER}» · {self.i18n.format_number(round(over.volume_m3), 0)} m³ apoyados en ella", labels)
        self.assertIn(f"«{WORKSHOP}» parte de su superficie", labels)
        self.assertIn("Se apoya en ella o parte de ella (2)", self.legend(built))
        names = ", ".join(f"«{row.name}»" for row in truth)
        self.assertEqual(built.summary[2], (f"Se apoyan en ella o parten de ella 2 diseños: {names}.", False))
        self.assertEqual(self.untouched(), before)
        entity.disable()

        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity=OVER), {"FINISHED"})  # por su nombre
        self.assertEqual(entity.plan().code, "PLT-003")
        nothing = self.pump()
        self.assertEqual(entity.preview().resting, ())
        self.assertEqual(nothing.summary[2], ("Nada se apoya en ella ni parte de ella.", False))
        self.assertEqual([batch.key for batch in nothing.lines.batches], [entity.FOOTPRINT, entity.AXIS, entity.ARROW])
        entity.disable()

        for values, wanted in (({"entity": "PLT-099"}, "«PLT-099» no es una entidad de V01"),
                               ({}, "Elija la entidad de la que ver la vista previa")):
            with self.subTest(pedido=values), self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", **values)
            self.assertIn(wanted, str(caught.exception))
            self.assertFalse(entity.enabled())

        # La entidad del objeto seleccionado: se carga en la vista y se previsualiza sin decir cuál.
        uid = self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'",
                        self.dprov.dataset_name("epr", LOADING))[0][0]
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
        loaded = next(obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid)
        self.addCleanup(self.remove_object, loaded)
        for other in bpy.data.objects:
            other.select_set(False)
        loaded.select_set(True)
        bpy.context.view_layer.objects.active = loaded
        self.assertEqual(self.des_ops._selected_entity(bpy.context), ("PLT-001", self.v01.uid))
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(entity.plan().code, "PLT-001")
        self.assertEqual(len(self.pump().lines.batches), 4)
        objects = len(bpy.data.objects)
        entity.disable()
        self.assertEqual(len(bpy.data.objects), objects, "la vista previa no crea ni quita objetos")
        self.set_active(self.v02)  # el objeto es de V01 y la versión activa es V02
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT")
        self.assertIn("La entidad seleccionada no es de la versión activa", str(caught.exception))
        self.set_active(self.v01)

        # Sin calcular (la que deja «Traer las entidades de…»): se dice. Con V02 al día de máscaras, para llegar a ello.
        self.set_active(self.v02)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="Carga"), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="Carga"), {"FINISHED"})
        bare = self.pump()
        self.assertEqual((bare.lines.batches, entity.preview().drawable), ((), False))
        self.assertEqual(bare.summary, (("«Carga» (PLT-001) aún no tiene resultado, así que no hay de dónde sacar su vista previa; "
                                         "calcúlela antes (menú Entidad ▾ ▸ Calcular…).", True),))
        entity.disable()
        self.set_active(self.v01)

    def entity_table(self, conn: Any, code: str) -> str:
        """La ubicación de la tabla ``des_epr_`` de la entidad ``code`` (la de su operación vigente)."""
        registry = self.entities.registry(self.project, self.v01.uid, conn=conn)
        return _module("design.entity_store").entity_surfaces(conn, registry)[code].locator

    @staticmethod
    def remove_object(obj: Any) -> None:
        if obj.name in bpy.data.objects:
            for collection in list(obj.users_collection):
                collection.objects.unlink(obj)
            mesh = obj.data
            bpy.data.objects.remove(obj)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    def test_g_changing_a_field_of_the_dialog_redraws_the_preview(self) -> None:
        """RF-015-26 (M4): cambiar un campo del diálogo redibuja la vista previa activa de esa plataforma (el ``update`` de
        sus propiedades, :func:`_refresh_preview`): con otra pendiente, otras cotas en los extremos; con otra capa o
        geometría, otra huella; con un campo a medias (la geometría sin escribir, un número que no lo es) sigue la última
        completa y no falla; la de una entidad de la versión no la cambia el diálogo; sin vista previa, no hace nada."""
        entity = self.entity
        fields = self.drawn_fields()
        fake = operator_self(self.cls, **{**fields, "name": NEW, "feature": LOADING, "gradient": ""})
        self.des_ops._refresh_preview(fake, None)  # sin vista previa activa: nada
        self.assertFalse(entity.enabled())
        self.assertEqual(self.show(), {"FINISHED"})
        first = self.pump()
        self.assertIn("rasante de 105,00 m en su primer vértice (abscisa 0) a 105,00 m en el último", first.summary[0][0])
        fake.gradient = "-1"
        self.des_ops._refresh_preview(fake, None)
        self.assertTrue(entity.building())
        second = self.pump()
        self.assertIsNot(second, first)
        self.assertIn("a 104,80 m en el último, pendiente del -1,00 %", second.summary[0][0])
        self.assertIn("Final · rasante 104,80 m", {label.text for label in second.lines.labels})
        fake.feature = ""  # a medias: sigue la última completa
        self.des_ops._refresh_preview(fake, None)
        self.assertFalse(entity.building())
        self.assertIs(entity.built(), second)
        fake.feature, fake.gradient = LOADING, "una"
        self.des_ops._refresh_preview(fake, None)
        self.assertFalse(entity.building())
        fake.gradient, fake.start_level, fake.feature = "", "110", WORKSHOP
        self.des_ops._refresh_preview(fake, None)
        third = self.pump()
        self.assertIn("rasante de 110,00 m", third.summary[0][0])
        self.assertEqual(entity.plan().request.feature, WORKSHOP)
        self.assertGreater(entity.preview().cells, 0)
        chosen = platform_ops.WORKSHOP
        entity.replace(entity.EntityPlan(request=entity.plan().request))  # replace: lo mismo, otra vez
        self.assertTrue(entity.building())
        self.pump()
        entity.disable()
        self.assertEqual(chosen, WORKSHOP)

        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="PLT-001"), {"FINISHED"})
        self.pump()
        self.des_ops._refresh_preview(fake, None)  # la de una entidad de la versión: el diálogo no la cambia
        self.assertFalse(entity.building())
        self.assertEqual(entity.plan().code, "PLT-001")
        with self.assertRaises(ValueError):  # una o la otra
            entity.EntityPlan(request=object(), code="PLT-001")
        with self.assertRaises(ValueError):
            entity.EntityPlan()
        entity.disable()

    def test_h_cancel_create_and_leaving_for_the_blender_interface_remove_it(self) -> None:
        """RF-015-26 (M4): la vista previa se quita **al cancelar** la orden (el diálogo, la ventana de confirmar tras
        «Calcular» y Esc a mitad del cálculo: ``cancel``), **al crear** la plataforma (ya existe) y **al conmutar a la
        interfaz de Blender** (``switcher.add_blender_hook``): ida y vuelta deja Blender como estaba (los
        manejadores de dibujo, el temporizador y los ganchos, igual que antes) y volver a Geoblender no la pone sola;
        cerrar el proyecto también. «Calcular» no la quita: se ve la huella mientras se confirma. Nada escrito."""
        entity, switcher = self.entity, self.switcher
        before_fingerprint = blender_ext.state_fingerprint()
        before = self.untouched()
        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        self.calculate(name=NEW, feature=LOADING, start=self.ground3)  # «Calcular»: la huella se sigue viendo
        self.assertTrue(entity.enabled())
        self.assertIsNotNone(self.des_ops.calculation())
        confirming, _context, _dialog = self.fake_dialog(confirm=True)
        self.cls.cancel(confirming, bpy.context)  # «Cancelar» en la ventana de confirmar
        self.assertFalse(entity.enabled() or entity.drawing())
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.untouched(), before)

        self.assertEqual(self.show(), {"FINISHED"})  # el diálogo cancelado sin calcular
        dialog, _context, _dialog = self.fake_dialog()
        self.cls.cancel(dialog, bpy.context)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertFalse(bpy.app.timers.is_registered(entity.tick))

        self.assertEqual(self.show(), {"FINISHED"})  # Esc a mitad del cálculo
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.request_form(in_steps=True)),
                         {"RUNNING_MODAL"})
        running = self.running()
        self.assertTrue(entity.enabled())
        self.assertEqual(running.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertFalse(entity.enabled())
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.untouched(), before)

        self.assertEqual(self.show(), {"FINISHED"})  # conmutar a la interfaz de Blender: ida y vuelta
        self.pump()
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(len(self.view.preview), 0)
        other_space = next(space.name for space in bpy.data.workspaces if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
        self.assertFalse(entity.enabled())  # volver no la pone sola
        diff = blender_ext.fingerprint_diff(before_fingerprint, blender_ext.state_fingerprint())
        mine = [line for line in diff if line.startswith(("draw_handlers", "handlers", "timers")) and "switcher" not in line]
        self.assertEqual(mine, [], diff)  # sin el temporizador que el propio conmutador deja
        self.assertEqual(self.untouched(), before)

        self.assertEqual(self.show(), {"FINISHED"})  # cerrar el proyecto
        self.pump()
        self.assertIn(entity.on_project_changed, self.ps.listeners())
        self.ps.listeners()[self.ps.listeners().index(entity.on_project_changed)](None)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertNotIn(entity.on_project_changed, self.ps.listeners())

        self.assertEqual(self.show(), {"FINISHED"})  # crear la plataforma la quita: ya existe
        self.pump()
        self.calculate(name=NEW, feature=LOADING, start=self.ground3)
        self.assertTrue(entity.enabled())
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertFalse(entity.enabled() or entity.drawing())
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get(NEW).record.code, "PLT-004")

    def test_i_with_200_entities_it_activates_in_a_second_and_each_redraw_takes_five_milliseconds(self) -> None:
        """RF-015-26, RNF-015-06: con 200 entidades —la peor vista previa: las otras 199 de la versión se apoyan en la que se
        previsualiza, cada una con su huella, su nombre y su volumen—, **activarla ≤ 1 s** (la orden, los pasos de su
        temporizador y los 5 ms de espera de cada uno) y **cada redibujo ≤ 5 ms** (los lotes, los nombres, la leyenda y el
        resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python de Geoblender; la GPU de verdad, M4). Se mide con lotes
        sintéticos (la preparación de 200 entidades reales —el registro y las dependencias— es de la T33). Se exige."""
        entity, constraints = self.entity, self.constraints
        rings = tuple(np.array([(WEST + 4.0 * i, SOUTH + 4.0 * j), (WEST + 4.0 * i + 2.0, SOUTH + 4.0 * j),
                                (WEST + 4.0 * i + 2.0, SOUTH + 4.0 * j + 2.0), (WEST + 4.0 * i, SOUTH + 4.0 * j + 2.0),
                                (WEST + 4.0 * i, SOUTH + 4.0 * j)]) for j in range(14) for i in range(15))[:ENTITIES - 1]
        self.assertEqual(len(rings), ENTITIES - 1)
        items = tuple(self.dpreview.RestingItem(f"Entidad {number:03d}", f"PLT-{number:03d}", "des.platform", "current",
                                                1000.0 + number, (ring,)) for number, ring in enumerate(rings, start=2))
        guard = tuple(np.array([(WEST + 20.0, SOUTH + 20.0), (WEST + 40.0, SOUTH + 20.0), (WEST + 40.0, SOUTH + 40.0),
                                (WEST + 20.0, SOUTH + 40.0), (WEST + 20.0, SOUTH + 20.0)]) for _ in range(1))
        synthetic = self.dpreview.EntityPreview(
            "Entidad 001", "PLT-001", "V01", self.access.MaskState.CURRENT, self.ground, guard,
            ((WEST + 20.0, SOUTH + 30.0), (WEST + 40.0, SOUTH + 30.0)), False,
            (self.dpreview.EntityEnd("start", WEST + 20.0, SOUTH + 30.0, 105.0),
             self.dpreview.EntityEnd("end", WEST + 40.0, SOUTH + 30.0, 105.4)), 40, 160.0, STEP_M, 20.0, 2.0, items, True, 4.0,
            guard, 100, 400.0, _module("core.constraints.model").ConstraintType.NO_FILL,
            (self.dpreview.Notice("des.preview_entity_declares_none"),))

        def fake_steps(*_args: Any, **_kwargs: Any) -> Any:
            yield _module("core.project.model").Progress("preview_entity", 1, 1, "listo", result=synthetic)

        interval = entity.TICK_INTERVAL_S
        self.assertEqual(interval, TICK_WAIT_S)
        walls: list[float] = []
        cpus: list[float] = []
        for _ in range(5):
            with mock.patch.object(entity.design_preview, "entity_preview_steps", fake_steps):
                started, cpu = time.perf_counter(), time.process_time()
                entity.enable(entity.EntityPlan(code="PLT-001"))
                ticks = 0
                for _tick in range(MAX_PUMPS):
                    ticks += 1
                    if entity.tick() is None:
                        break
                wall = time.perf_counter() - started + interval * max(0, ticks - 1)
                walls.append(wall)
                cpus.append(time.process_time() - cpu)
            built = entity.built()
            self.assertIsNotNone(built)
            if len(walls) < 5:
                entity.disable()
        self.assertEqual([batch.key for batch in built.lines.batches],
                         [entity.FOOTPRINT, entity.AXIS, entity.ARROW, entity.RESTING, entity.ZONE])
        self.assertEqual(len(built.lines.legend), 7)
        self.assertEqual(self.batch(built, entity.RESTING).segments, 4 * (ENTITIES - 1))
        self.assertGreater(len(built.lines.labels), 190)
        print(f"RNF-015-06 (T29): activarla con {ENTITIES} entidades: mediana {statistics.median(walls) * 1000:.1f} ms de pared "
              f"y {statistics.median(cpus) * 1000:.1f} ms de CPU, la peor {max(walls) * 1000:.1f} ms (presupuesto 1000 ms)")
        self.assertLessEqual(statistics.median(walls), ACTIVATE_BUDGET_S)
        self.assertLessEqual(max(walls), ACTIVATE_BUDGET_S)

        matrix = preview_tests.top_view(self.local(30.0, 30.0))
        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        view = dict(view_matrix=Matrix.Identity(4), projection_matrix=Matrix.Identity(4), perspective=True,
                    view_distance=100.0, viewport_size=SIZE, pixel_size=1.0)
        measure = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        redraws: list[float] = []
        with mock.patch.object(constraints, "gpu", gpu), mock.patch.object(constraints, "batch_for_shader") as lots:
            for index in range(120):
                started = time.perf_counter()  # el reloj de CPU de Windows mide de 16 ms en 16 ms: aquí, el de pared
                drawn = constraints.draw_lines(built.lines, **view)
                items_on_screen = self.design_draw.screen_items(built, matrix, SIZE, measure=measure, scale=1.0)
                if index >= 20:  # las primeras: los lotes de gpu se crean una vez
                    redraws.append(time.perf_counter() - started)
            self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        self.assertGreater(len(items_on_screen), 20)
        print(f"RNF-015-06 (T29): cada redibujo con {ENTITIES} entidades: mediana {statistics.median(redraws) * 1000:.2f} ms, "
              f"p95 {sorted(redraws)[int(0.95 * len(redraws))] * 1000:.2f} ms, la peor {max(redraws) * 1000:.2f} ms, "
              f"{len(items_on_screen)} elementos en pantalla (presupuesto 5 ms)")
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S)
        self.assertLessEqual(sorted(redraws)[int(0.95 * len(redraws))], REDRAW_BUDGET_S)  # y el percentil 95: la carga ajena no cuenta de más
        entity.disable()

    def test_j_with_200_entities_in_the_version_the_real_preparation_activates_in_a_second(self) -> None:
        """RNF-015-06: la preparación de verdad —el registro de las entidades, la partida y la cadena, las máscaras, la
        geometría y la huella, ``design.preview.entity_preview_steps``— con **200 entidades** más en la versión (sus
        parámetros, sin calcular, en una cadena de 200: en V02, con sus máscaras al día): activar la vista previa de una nueva con la orden real,
        los pasos de su temporizador y los 5 ms de espera de cada uno, ≤ 1 s (mediana de 5); y sin escribir nada. La medida
        formal, con las entidades calculadas y sus dependencias, es de la T33."""
        entity = self.entity
        entity_store, params = _module("design.entity_store"), _module("design.params")
        fields = self.dmodel.PlatformFields(platform_ops.LAYER, "cota_inicial", "pendiente", width_field="ancho")
        layer_values = {params.PlatformParam.WIDTH: 8.0, params.PlatformParam.START_LEVEL: 105.0,
                        params.PlatformParam.GRADIENT: 0.0}
        rows = []
        for number in range(100, 100 + ENTITIES):  # una cadena: cada una parte de la superficie de la anterior
            code = f"PLT-{number:03d}"
            previous = "PLT-001" if number == 100 else f"PLT-{number - 1:03d}"
            asked = self.dmodel.PlatformRequest(f"Entidad {number}", fields, "1", self.entities.surface_ref(previous),
                                                edge_angle_deg=35.0, reach_m=10.0)
            values = entity_store.entity_values(asked, code, 1, layer_values, line=True)
            rows.extend(entity_store._rows(asked, code, values, {}))  # noqa: SLF001 - las filas de una entidad
        self.set_active(self.v02)
        entity_store.set_entity_params(self.project, rows, version=self.v02.uid)
        self.assertEqual(len(self.entities.registry(self.project, self.v02.uid)), ENTITIES + 1)  # y la «Carga» traída
        self.assertIs(self.access.mask_state(self.project, self.v02.uid)[0], self.access.MaskState.CURRENT)
        self.refresh()  # las listas del diálogo, de V02
        before = self.untouched()
        walls: list[float] = []
        for _ in range(5):
            started = time.perf_counter()
            self.assertEqual(self.show(), {"FINISHED"})
            ticks = 0
            for _tick in range(MAX_PUMPS):
                ticks += 1
                if entity.tick() is None:
                    break
            walls.append(time.perf_counter() - started + TICK_WAIT_S * max(0, ticks - 1))
            built = entity.built()
            self.assertIsNotNone(built)
            self.assertEqual((built.lines.version_code, built.lines.masks, len(built.lines.batches)), ("V02", "current", 3))
            entity.disable()
        print(f"RNF-015-06 (T29): activarla con {ENTITIES} entidades en la versión (la preparación de verdad): "
              f"mediana {statistics.median(walls) * 1000:.1f} ms, la peor {max(walls) * 1000:.1f} ms (presupuesto 1000 ms)")
        self.assertLessEqual(statistics.median(walls), ACTIVATE_BUDGET_S)
        self.assertEqual(self.untouched(), before)
        self.set_active(self.v01)
        self.refresh()

    def test_z_disabling_geoblender_with_the_preview_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa de una entidad activa, desactivar Geoblender quita los manejadores de dibujo, los
        ganchos, los avisos, el temporizador y los lotes, y la huella de Blender vuelve a la del principio de la sesión."""
        entity = self.entity
        self.assertEqual(self.show(), {"FINISHED"})
        self.assertTrue(entity.drawing())
        self.assertTrue(bpy.app.timers.is_registered(entity.tick))  # la construcción, sin acabar
        blender_ext.release()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertIsNone(getattr(bpy.types, platform_ops.PLATFORM_CLASS, None))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityPreviewTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
