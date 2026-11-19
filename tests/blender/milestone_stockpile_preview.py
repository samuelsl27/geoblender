# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de las marcas de los acopios y de la zona de coronación del contrafuerte (spec 016, T32; HU-016-1, HU-016-3; RF-016-23,
RF-015-26; RNF-016-03; plan 016 §5.5; comprobación manual M4).

``bl.draw.entity`` —la vista previa de una entidad de la 015— dibuja ahora, antes de calcular y **sin escribir nada en el proyecto ni crear
objetos**, las **marcas de una detección de acopios con su margen** (``EntityPlan(stockpile=…)``: lo que activará la orden de detectar de la
T35 con su botón «Vista previa») y la **zona de coronación de un contrafuerte** (``EntityPlan(buttress=…)``: el botón «Vista previa» del
diálogo de «Contrafuerte…», que ya existe), con su leyenda y su resumen; se quita al cancelar, al Esc a mitad del cálculo, al crear y al
conmutar a la interfaz de Blender. Lo que dibuja se prueba en sus lotes, sus nombres y sus textos en píxeles, no en píxeles de pantalla
(``docs/trampas.md`` §3: sin GPU en ``blender -b``); lo que prepara, en ``tests/unit/design/milestone_stockpile_preview.py``.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, la ladera ``100 + 0,25·y + 0,0625·x``) con una capa de
marcas (dos de 20 × 20 m: 10 × 10 celdas, la primera con un margen de 4 m y su material y la segunda sin ellos), otra de cien marcas de
4 × 4 m (2 × 2 celdas) y otra de dos marcas que se solapan, la capa de las zonas de coronación de ``milestone_buttress_ops`` y el perfil de banco
``EXPL_10_60_6``. Las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-016-23 (a): las piezas de la orden: el plan con una sola cosa, el botón «Vista previa» y la propiedad oculta de «Contrafuerte…», sus
  ``update`` y su ``cancel`` y ``_stop``.
- RF-016-23, RF-016-02 (b): las marcas de la detección con su margen: el contorno de sus celdas y el de la marca ampliada por su margen
  (a mano, por fuerza bruta), sus nombres, la leyenda y el resumen en los dos idiomas; nada escrito ni creado.
- RF-016-23, RF-015-08 (c): lo que rechazaría la detección (marcas solapadas) es el aviso en lugar del dibujo, con el mismo texto.
- RF-016-23 (d): la zona de coronación del contrafuerte y su resguardo con el botón del diálogo: sus lotes, sus nombres, su leyenda y
  su resumen; sin resguardo, solo la zona y el aviso; sin perfil, la orden lo dice y no toca la vista previa.
- RF-016-23 (e): cambiar un campo del diálogo del contrafuerte redibuja; uno a medias no.
- RF-016-23, RF-015-26 (f): se quita al cancelar (el diálogo y la ventana de confirmar), con Esc a mitad del cálculo, al crear el
  contrafuerte y al conmutar a la interfaz de Blender (ida y vuelta deja Blender como estaba); cerrar el proyecto también.
- RF-016-23, RNF-016-03 (g): con 100 marcas, activarla ≤ 1 s y cada redibujo ≤ 5 ms.
- Principio 8 (z): desactivar Geoblender con la vista previa activa lo quita todo.

Se ejecuta con ``tools/run_blender_tests.py``.
Spec 016, T43 (RNF-016-06): pasó del «verde» al paso «hito» (P-13), sin cambiar ninguna prueba; antes, ``test_stockpile_preview.py``.
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

from tests.blender import milestone_buttress_ops as buttress_ops
from tests.blender import test_design_preview as preview_tests
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

ADD = "geoblender.des_add_buttress"
MARKS_LAYER = "gis_fea_marcas_previa"
MANY_LAYER = "gis_fea_cien_marcas"
OVERLAP_LAYER = "gis_fea_marcas_solapadas"
CROWN_LAYER = buttress_ops.CROWN_LAYER
MARKS = (("Acopio 1", (6.0, 20.0, 26.0, 40.0), 4.0, "mineral"), ("Acopio 2", (34.0, 20.0, 54.0, 40.0), None, None))
"""Las marcas de la capa (nombre, caja local, margen y material): 10 × 10 celdas cada una, a 8 m una de otra."""
DEFAULT_MARGIN_M = 2.0
"""El margen de la detección que se pide (el de las marcas sin campo ``margen``)."""
OVERLAPPING = (("A", (6.0, 20.0, 26.0, 40.0)), ("B", (20.0, 20.0, 40.0, 40.0)))
HUNDRED = 100
"""Las marcas de la capa de la medida: 10 × 10, de 4 × 4 m cada una a 6 m de paso."""
PREVIEW_NAME = "Acopios"
FIRST = buttress_ops.FIRST
CROWN_ZONE = buttress_ops.CROWNS[0]
"""La «Cima»: 10 × 10 m (5 × 5 celdas) en el centro de la ventana."""
GUARD_M = 5.0
PROFILE_CODE = buttress_ops.PROFILE.lower()
"""El código con que «Perfiles de banco…» guarda el perfil ``EXPL_10_60_6`` (``expl_10_60_6``): lo que lleva la petición."""
WEST, SOUTH, STEP_M = platform_ops.WEST, platform_ops.SOUTH, platform_ops.STEP_M
MAX_PUMPS = 20_000
SIZE = (1920.0, 1080.0)
"""La región de la Vista 3D de los redibujos: la de la barra a 1920 px de las comprobaciones manuales."""
ACTIVATE_BUDGET_S = 1.0  # RNF-016-03
REDRAW_BUDGET_S = 0.005  # RNF-016-03
TICK_WAIT_S = 0.005  # bl.draw.entity.TICK_INTERVAL_S (lo comprueba la prueba)
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
EDITABLE = ("name", "layer", "feature", "start", "profile", "crown", "protect", "guard")
"""Los campos de «Contrafuerte…» que redibujan la vista previa de su zona de coronación al cambiarlos."""
FIELDS = {"name": FIRST, "layer": CROWN_LAYER, "feature": CROWN_ZONE[0], "support": "none", "profile": buttress_ops.PROFILE, "crown": "115",
          "reach": "", "metric": "EXACT", "protect": True, "guard": "5", "reason": ""}


def _module(name: str) -> Any:
    return platform_ops._module(name)


def box_cells(box: tuple[float, float, float, float]) -> np.ndarray:
    """A mano: las celdas de la ventana con el centro dentro de la caja local ``box``, como máscara (un bucle de numpy, no el código)."""
    left, bottom, right, top = box
    x, y = platform_ops.centers()
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def grown(mask: np.ndarray, radius_cells: float) -> np.ndarray:
    """A mano, por fuerza bruta: las celdas a una distancia entre centros de ``radius_cells`` celdas o menos de alguna de ``mask``."""
    reach = int(radius_cells)
    padded = np.pad(mask, reach)
    found = np.zeros_like(mask)
    rows, cols = mask.shape
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            if di * di + dj * dj <= radius_cells ** 2:
                found |= padded[reach + di:reach + di + rows, reach + dj:reach + dj + cols]
    return found


def within(mask: np.ndarray, distance_m: float) -> np.ndarray:
    """A mano: las celdas cuyo centro está a ``distance_m`` m o menos del de alguna de ``mask`` (distancia euclídea entre centros)."""
    x, y = platform_ops.centers()
    found = np.zeros_like(mask)
    for row, col in zip(*np.nonzero(mask), strict=True):
        found |= np.hypot(x - x[row, col], y - y[row, col]) <= distance_m + 1e-9
    return found


class StockpilePreviewTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con las capas de marcas y de las zonas de
    coronación y el perfil de banco."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_polygons(MARKS_LAYER, tuple(box for _name, box, _margin, _material in MARKS), tuple(name for name, *_rest in MARKS),
                           doubles={"margen": tuple(margin for _name, _box, margin, _material in MARKS)},
                           texts={"material": tuple(material for _name, _box, _margin, material in MARKS)})
        pitch = 6.0
        many = tuple((pitch * i, pitch * j, pitch * i + 4.0, pitch * j + 4.0) for j in range(10) for i in range(10))
        cls.write_polygons(MANY_LAYER, many, tuple(f"Marca {number:03d}" for number in range(1, HUNDRED + 1)))
        cls.write_polygons(OVERLAP_LAYER, tuple(box for _name, box in OVERLAPPING), tuple(name for name, _box in OVERLAPPING))
        cls.write_polygons(CROWN_LAYER, tuple(box for _name, box in buttress_ops.CROWNS), tuple(name for name, _box in buttress_ops.CROWNS))
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=buttress_ops.PROFILE, kind="ADOPTADO", source=buttress_ops.SOURCE, decided_by=platform_ops.PERSON,
            reason=platform_ops.REASON, scope="PROJECT", height="10", face="60", berm="6", anchor="125") == {"FINISHED"}
        cls.refresh()
        cls.entity = _module("bl.draw.entity")
        cls.design_draw = _module("bl.draw.design")
        cls.constraints = _module("bl.draw.constraints")
        cls.dpreview = _module("design.preview")
        cls.dmodel = _module("design.model")
        cls.switcher = _module("bl.ui.switcher")
        cls.stockpile_store = _module("design.stockpile_store")
        cls.grid = _module("gis.grid").project_grid(cls.project.record.window, float(cls.project.record.grid_step_m))
        cls.addClassCleanup(cls.entity.disable)

    @classmethod
    def write_polygons(cls, name: str, boxes: tuple[tuple[float, float, float, float], ...], names: tuple[str, ...], *,
                       doubles: dict[str, tuple[Any, ...]] | None = None, texts: dict[str, tuple[Any, ...]] | None = None) -> None:
        """La capa ``name`` de polígonos (un rectángulo por caja local), con su campo ``nombre`` y los campos numéricos ``doubles`` y de
        texto ``texts`` (valor por polígono; ``None`` donde falta), como la deja la importación de la 006."""
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        doubles, texts = doubles or {}, texts or {}
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), *(vector.FieldColumn(field, field, "DOUBLE") for field in doubles),
                   *(vector.FieldColumn(field, field, "TEXT") for field in texts))
        layer = vector.FeatureLayer("polygon", tuple(range(1, len(boxes) + 1)), tuple(((platform_ops.ring(box),),) for box in boxes),
                                    columns, {"nombre": names, **doubles, **texts})
        rows = gis_store.feature_rows(layer, srs)
        defined = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = platform_ops._module("core.provenance.operations").begin_operation(
            cls.project, platform_ops.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, {defined})')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                         "VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                         "VALUES (?, 'geom', ?, ?, 0, 0)", (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                input_uid=None, immutable=False),), message="Capa de la prueba de la vista previa de los acopios")

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las del contrafuerte), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        super().refresh()
        if cls.project.record is not None:
            cls.panels.refresh_buttress_choices(cls.project)

    def tearDown(self) -> None:
        if self.entity.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.entity.disable()
        super().tearDown()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(ADD)

    @property
    def origin(self) -> Any:
        return self.project.origin

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no corren) hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.entity.tick() is None:
                built = self.entity.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def stockpile(self, layer: str = MARKS_LAYER, **changes: Any) -> Any:
        """La petición de la detección de las marcas de ``layer`` sobre la ladera (del proyecto), con 2 m de margen por defecto."""
        fields = self.dmodel.StockpileFields(layer, name_field="nombre", margin_field="margen" if layer == MARKS_LAYER else None,
                                             material_field="material" if layer == MARKS_LAYER else None)
        return self.dmodel.StockpileRequest(PREVIEW_NAME, fields, self.ground, **{"margin_m": DEFAULT_MARGIN_M, **changes})

    def show_marks(self, **changes: Any) -> Any:
        """Activa la vista previa de las marcas (lo que hará el botón de la orden de detectar, T35) y la lleva hasta el final."""
        self.entity.enable(self.entity.EntityPlan(stockpile=self.stockpile(**changes)))
        return self.pump()

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo de «Contrafuerte…»: la «Cima» sobre la ladera con el perfil, la coronación a 115 m y 5 m de resguardo."""
        return {**FIELDS, "start": self.ground, "in_steps": False, **values}

    def show(self, **values: Any) -> set[str]:
        """El botón «Vista previa» del diálogo de «Contrafuerte…»: la orden con ``preview`` y lo pedido."""
        return bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", preview=True, **self.form(**values))

    def fake_dialog(self, **values: Any) -> Any:  # type: ignore[override]
        """El operador de mentira del diálogo de «Contrafuerte…» con lo pedido (para ``cancel`` y los ``update`` de sus campos)."""
        fields: dict[str, Any] = {**self.form(), "confirm": False, "preview": False, "provenance_dialog": False,
                                  "report": lambda kind, text: None, **values}
        return operator_self(self.cls, **fields)

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{ADD} no está en marcha")
        return found[0]

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

    def edges(self, built: Any, key: str) -> set[tuple[str, int, int]]:
        """Los lados de celda que cubre el lote ``key`` (con sus segmentos ajustados a la ladera)."""
        segments, height = self.absolute(self.batch(built, key))
        xy = self.batch(built, key).positions[:, :2].astype(np.float64) + [self.origin.x0 - WEST, self.origin.y0 - SOUTH]
        np.testing.assert_allclose(height, [self.ground_z(x, y) for x, y in xy], atol=2e-3)  # sobre la ladera
        return preview_tests.covered_edges(segments, self.grid)

    def untouched(self) -> tuple[Any, ...]:
        """Lo que la vista previa no cambia: el proyecto (operaciones, datos, parámetros, cifras y ficheros) y la escena (objetos y mallas)."""
        return (self.state(), len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_plan_the_dialog_button_the_updates_and_the_cancel_of_the_buttress(self) -> None:
        """RF-016-23 (M4): el plan de la vista previa es de **una sola cosa** (la plataforma que se prepara, una entidad de la versión, las
        marcas de una detección o la zona de un contrafuerte) y dice cuál; «Contrafuerte…» tiene la propiedad oculta ``preview`` (sin
        nombre ni descripción: la pone quien la lanza), dibuja el botón «Vista previa» —la misma orden con ``preview`` y todo lo pedido—,
        redibuja al cambiar el nombre, la capa, la zona, la partida, el perfil, la coronación y el resguardo (su ``update``) y no al cambiar
        lo demás, y quita la vista previa al cancelar y al Esc (``_ClearsEntityPreview``, antes de ``_CalculateAndCreate``)."""
        entity, des_ops = self.entity, self.des_ops
        for asked, kind in (({"request": object()}, "platform"), ({"code": "PLT-001"}, "entity"), ({"stockpile": object()}, "stockpile"),
                            ({"buttress": object()}, "buttress")):
            self.assertEqual(entity.EntityPlan(**asked).kind, kind)
        for wrong in ({}, {"request": object(), "code": "PLT-001"}, {"stockpile": object(), "buttress": object()},
                      {"code": "PLT-001", "insert_before": "PLT-002"}):
            with self.assertRaises(ValueError, msg=str(wrong)):
                entity.EntityPlan(**wrong)
        cls = self.cls
        self.assertIn("preview", cls.__annotations__)
        self.assertNotIn("name", cls.__annotations__["preview"].keywords)
        self.assertEqual(des_ops._BUTTRESS_HIDDEN, {"confirm", "in_steps", "preview"})
        self.assertEqual(set(des_ops._buttress_fields()), set(buttress_ops.PROPERTIES))
        self.assertLess(cls.__mro__.index(des_ops._ClearsEntityPreview), cls.__mro__.index(des_ops._CalculateAndCreate))
        for prop in cls.__annotations__:
            if prop in des_ops._BUTTRESS_HIDDEN:
                continue
            with self.subTest(propiedad=prop):
                update = cls.__annotations__[prop].keywords.get("update")
                self.assertIs(update, des_ops._refresh_buttress_preview if prop in EDITABLE else None)
        shown = draw(cls, bpy.context, **{**FIELDS, "start": self.ground, "confirm": False})
        (button,) = [item for item in shown.of_kind("operator") if item.target == ADD]
        self.assertEqual((button.text, button.icon, button.operator_context), ("Vista previa", "HIDE_OFF", "EXEC_DEFAULT"))
        self.assertEqual(vars(button.properties), {**FIELDS, "start": self.ground, "preview": True})
        self.assertFalse(entity.enabled())

    def test_b_the_marks_and_their_margin_are_drawn_before_calculating(self) -> None:
        """RF-016-23, RF-016-02 (M4): la vista previa de las marcas, sin calcular ni escribir nada en el proyecto ni crear objetos, se
        construye por pasos con el temporizador: **el contorno de las dos marcas** (cada una, 10 × 10 celdas, lado a lado, igual al de
        sus celdas, sobre la ladera) y **el de cada marca ampliada por su margen** (4 m el de la primera, por su campo, y 2 m el de la
        segunda, el de la detección; la dilatación de las celdas con un disco, por fuerza bruta), el nombre de cada una junto a ella con
        su margen y su material, la leyenda con una fila por pieza y el resumen de ``design``, en español y en inglés. La detección es
        del proyecto (la ladera lo es). El mismo control la quita."""
        entity = self.entity
        before = self.untouched()
        entity.enable(entity.EntityPlan(stockpile=self.stockpile()))
        self.assertTrue(entity.enabled() and entity.drawing() and entity.building())
        self.assertIsNotNone(entity.plan().stockpile)
        self.assertEqual(entity.plan().kind, "stockpile")
        self.assertIsNone(self.des_ops.calculation())
        self.assertFalse(self.design_draw.enabled())
        self.assertIn(entity.disable, self.switcher.blender_hooks())
        built = self.pump()
        self.assertFalse(entity.building())
        self.assertEqual((built.lines.version_code, built.lines.masks, built.lines.surface), ("V01", "", self.ground))
        self.assertIsNone(built.seeds)
        self.assertEqual(built.sectors, ())
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.MARKS, entity.MARGIN])
        self.assertEqual({batch.role for batch in built.lines.batches}, {self.constraints.OUTLINE})
        found = entity.preview()
        self.assertEqual((found.name, found.code, found.scope, found.version, found.surface, found.margin_m),
                         (PREVIEW_NAME, "STK-001", "project", "", self.ground, DEFAULT_MARGIN_M))
        self.assertEqual([(mark.key, mark.cells, mark.margin_m, mark.own_margin) for mark in found.marks],
                         [("Acopio 1", 100, 4.0, True), ("Acopio 2", 100, DEFAULT_MARGIN_M, False)])

        marks = [box_cells(box) for _name, box, _margin, _material in MARKS]
        margins = [4.0, DEFAULT_MARGIN_M]
        own = set().union(*(preview_tests.unit_edges(mask) for mask in marks))
        self.assertEqual(self.edges(built, entity.MARKS), own)  # el borde de sus celdas, lado a lado
        self.assertEqual(self.batch(built, entity.MARKS).color, entity.MARK_COLOR)
        enlarged = set().union(*(preview_tests.unit_edges(grown(mask, margin / STEP_M)) for mask, margin in zip(marks, margins, strict=True)))
        self.assertEqual(self.edges(built, entity.MARGIN), enlarged)  # la marca ampliada por su margen
        self.assertEqual(self.batch(built, entity.MARGIN).color, entity.MARGIN_COLOR)
        self.assertNotEqual(self.batch(built, entity.MARGIN).color, self.batch(built, entity.MARKS).color)
        labels = {label.text: label for label in built.lines.labels}
        self.assertEqual(sorted(labels), ["«Acopio 1» · margen 4,0 m · material mineral", "«Acopio 2» · margen 2,0 m"])
        for text, (x, y) in (("«Acopio 1» · margen 4,0 m · material mineral", (16.0, 30.0)), ("«Acopio 2» · margen 2,0 m", (44.0, 30.0))):
            np.testing.assert_allclose(labels[text].xyz[:2], self.local(x, y), atol=1e-3)
            self.assertAlmostEqual(labels[text].xyz[2], self.ground_z(x, y), places=3)
            self.assertEqual(labels[text].color, entity.MARK_COLOR)
        self.assertEqual(self.legend(built), [
            "Vista previa de «Acopios» (STK-001) · Proyecto", "Marcas (2, 800 m²): las celdas que leerá la detección",
            "Marcas ampliadas por su margen (2,0 – 4,0 m)", f"Sobre la superficie «{self.ground}»"])
        self.assertEqual([row.color is None for row in built.lines.legend], [True, False, False, True])
        self.assertEqual(built.summary, found.lines("es"))
        self.assertTrue(built.summary[0][0].startswith("Vista previa de «Acopios» (STK-001) en el proyecto: 2 marcas con un área total de 800 m²"))
        self.assertFalse(any(alert for _text, alert in built.summary))
        self.assertEqual([(line.name, line.alert) for line in self.view.preview], list(built.summary))
        self.assertEqual(self.untouched(), before)  # nada escrito en el proyecto ni creado en la escena

        self.i18n.set_language("en")  # en inglés todo sale en inglés
        entity.rebuild()
        english = self.pump()
        self.assertEqual(self.legend(english)[:2], ["Preview of «Acopios» (STK-001) · Project", "Marks (2, 800 m²): the cells the detection will read"])
        self.assertIn("«Acopio 1» · margin 4.0 m · material mineral", {label.text for label in english.lines.labels})
        self.assertTrue(english.summary[0][0].startswith("Preview of «Acopios» (STK-001) in the project: 2 marks with a total area of 800 m²"))
        self.i18n.set_language("es")
        entity.disable()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(len(self.view.preview), 0)

    def test_c_overlapping_marks_are_drawn_and_the_pair_is_warned(self) -> None:
        """RF-016-23, RF-016-04, RF-015-08 (M4; T48, hallazgo A-2 de la verificación única): dos marcas que se solapan **ya no son un rechazo**
        de la preparación (solo esas dos se rechazan al calcular): la vista previa **las dibuja** (el contorno de las dos y el de cada una
        ampliada) y avisa de la pareja en el resumen, en alerta, con **el mismo texto** que la preparación en los dos idiomas y nombrando las
        dos y el área común (a mano: 3 columnas × 10 filas de celdas de 2 m = 120 m²); nada escrito."""
        entity = self.entity
        before = self.untouched()
        built = self.show_marks(layer=OVERLAP_LAYER)
        found = entity.preview()
        self.assertIsNone(found.refusal)
        self.assertEqual((found.drawable, [mark.key for mark in found.marks]), (True, ["A", "B"]))
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.MARKS, entity.MARGIN])
        prepared = self.stockpile_store.prepare_detection(self.project, self.stockpile(OVERLAP_LAYER), version=None)
        notice = prepared.job.refused[0].notice
        common = np.count_nonzero(box_cells(OVERLAPPING[0][1]) & box_cells(OVERLAPPING[1][1])) * STEP_M * STEP_M
        self.assertEqual((notice.code, notice.values["mark"], notice.values["other"], notice.values["area"]),
                         ("des.stockpile_marks_overlap", "A", "B", common))
        self.assertEqual(common, 120.0)
        self.assertEqual(sum(1 for text, _alert in built.summary if "«A»" in text and "«B»" in text), 1)
        self.assertIn((notice.text("es"), True), built.summary)
        self.assertIn("«A»", notice.text("es"))
        self.assertIn("«B»", notice.text("es"))
        self.i18n.set_language("en")
        entity.rebuild()
        self.assertIn((notice.text("en"), True), self.pump().summary)
        self.i18n.set_language("es")
        self.assertEqual(self.untouched(), before)
        entity.disable()

    def test_d_the_crown_zone_of_the_buttress_and_its_guard_with_the_dialog_button(self) -> None:
        """RF-016-23, RF-016-17, RF-015-10 (M4): el botón «Vista previa» del diálogo de «Contrafuerte…» activa la de la zona de coronación
        sin calcular ni escribir nada: **la zona** (la «Cima», 5 × 5 celdas, el borde de sus celdas sobre la ladera) y **la zona que declarará
        «sin corte»** con el resguardo de 5 m (a mano: las celdas a ≤ 5 m entre centros), la cota de coronación (115 m) en el nombre de la
        zona y el resguardo en el de la otra, la leyenda y el resumen, en los dos idiomas. Sin resguardo (que no tiene valor por defecto)
        se dibuja solo la zona y se avisa; sin perfil, la orden lo dice y no toca la vista previa. El mismo control (la orden de la 015) la
        quita."""
        entity = self.entity
        before = self.untouched()
        self.assertEqual(self.show(), {"FINISHED"})
        self.assertTrue(entity.enabled() and entity.drawing() and entity.building())
        self.assertEqual(entity.plan().kind, "buttress")
        self.assertEqual(entity.plan().buttress.name, FIRST)
        self.assertIsNone(self.des_ops.calculation())
        self.assertIn(entity.disable, self.switcher.blender_hooks())
        built = self.pump()
        self.assertEqual((built.lines.version_code, built.lines.masks, built.lines.surface), ("V01", "", self.ground))
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.CROWN, entity.ZONE])
        found = entity.preview()
        zone = box_cells(CROWN_ZONE[1])
        guarded = within(zone, GUARD_M)
        self.assertEqual((found.name, found.code, found.crown_cells, found.crown_area_m2, found.zone_cells, found.zone_area_m2),
                         (FIRST, "BTR-001", 25, 100.0, int(guarded.sum()), 4.0 * float(guarded.sum())))
        self.assertEqual(self.edges(built, entity.CROWN), preview_tests.unit_edges(zone))
        self.assertEqual(self.batch(built, entity.CROWN).color, entity.CROWN_COLOR)
        self.assertEqual(self.edges(built, entity.ZONE), preview_tests.unit_edges(guarded))
        self.assertEqual(self.batch(built, entity.ZONE).color, self.constraints.color_of("no_cut"))
        labels = {label.text: label for label in built.lines.labels}
        crown_text = f"Zona de coronación de «{FIRST}» (BTR-001) · coronación a 115,00 m"
        guard_text = f"{FIRST} (declarada) · resguardo 5,0 m"
        self.assertEqual(sorted(labels), sorted([crown_text, guard_text]))
        np.testing.assert_allclose(labels[crown_text].xyz[:2], self.local(27.0, 27.0), atol=1e-3)  # el centro de la zona
        np.testing.assert_allclose(labels[guard_text].xyz[:2], self.local(27.0, 36.0), atol=1e-3)  # arriba de la zona con su resguardo (a 4 m: celdas a ≤ 5 m)
        self.assertEqual(self.legend(built), [
            f"Vista previa de «{FIRST}» (BTR-001) · V01", "Zona de coronación (25 celdas, 100 m²)",
            f"Declara «Sin corte» con un resguardo de 5,0 m ({int(guarded.sum()) * 4} m²)", f"Sobre la superficie «{self.ground}»"])
        self.assertEqual(built.summary, found.lines("es"))
        self.assertIn("zona de coronación de 25 celdas (100 m²), el polígono «Cima» de la capa «gis_fea_coronaciones»", built.summary[0][0])
        self.assertIn(f"Coronación a 115,00 m con el perfil de banco {PROFILE_CODE}.", [text for text, _alert in built.summary])
        self.assertFalse(any(alert for _text, alert in built.summary))
        self.assertEqual(self.untouched(), before)
        self.i18n.set_language("en")
        entity.rebuild()
        english = self.pump()
        self.assertEqual(self.legend(english)[:2], [f"Preview of «{FIRST}» (BTR-001) · V01", "Crown zone (25 cells, 100 m²)"])
        self.assertIn(f"Crown at 115.00 m with the bench profile {PROFILE_CODE}.", [text for text, _alert in english.summary])
        self.i18n.set_language("es")

        self.assertEqual(self.show(guard=""), {"FINISHED"})  # protege por defecto y aún sin resguardo: solo la zona de coronación
        again = self.pump()
        self.assertEqual([batch.key for batch in again.lines.batches], [entity.CROWN])
        self.assertTrue(any(alert and "resguardo" in text for text, alert in again.summary))
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.show(protect=False, guard=""), {"FINISHED"})  # sin proteger: no declara nada
        loose = self.pump()
        self.assertEqual([batch.key for batch in loose.lines.batches], [entity.CROWN])
        self.assertIn("No protege su zona de coronación: no declara ninguna restricción.", [text for text, _alert in loose.summary])
        last = entity.plan()
        with self.assertRaises(RuntimeError) as asked:  # sin perfil: la orden lo dice y la vista previa sigue la última completa
            self.show(profile="")
        self.assertIn("perfil", str(asked.exception))
        self.assertIs(entity.plan(), last)
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})  # el mismo control la quita
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertEqual(self.untouched(), before)

    def test_e_changing_a_field_of_the_buttress_dialog_redraws_the_preview(self) -> None:
        """RF-016-23 (M4): cambiar un campo del diálogo de «Contrafuerte…» (su ``update``) redibuja la vista previa activa de **esa** zona
        con lo que dice ahora el diálogo (aquí, el resguardo de 5 a 8 m y otra zona); uno a medias (sin perfil, una cota que no es un
        número) no la cambia; sin la vista previa activa, o con la de las marcas de una detección, no hace nada."""
        entity, update = self.entity, self.des_ops._refresh_buttress_preview
        update(self.fake_dialog(), bpy.context)  # sin vista previa: nada
        self.assertFalse(entity.enabled())
        self.assertEqual(self.show(), {"FINISHED"})
        first = self.pump()
        self.assertEqual(entity.preview().guard_m, GUARD_M)
        update(self.fake_dialog(guard="8", feature=buttress_ops.CROWNS[2][0]), bpy.context)
        self.assertTrue(entity.building())
        second = self.pump()
        self.assertEqual((entity.preview().guard_m, entity.preview().feature, entity.preview().crown_cells), (8.0, "Segunda", 16))
        self.assertNotEqual(second.summary, first.summary)
        before = entity.plan()
        for half in ({"profile": ""}, {"crown": "unos"}, {"guard": "mucho"}, {"feature": ""}):
            with self.subTest(medias=half):
                update(self.fake_dialog(**half), bpy.context)
                self.assertIs(entity.plan(), before)
                self.assertFalse(entity.building())
        entity.disable()
        self.show_marks()  # con la de las marcas activa, el diálogo del contrafuerte no la cambia
        marks_plan = entity.plan()
        update(self.fake_dialog(guard="9"), bpy.context)
        self.assertIs(entity.plan(), marks_plan)
        entity.disable()

    def test_f_cancel_esc_create_and_leaving_for_the_blender_interface_remove_it(self) -> None:
        """RF-016-23, RF-015-26 (M4): la vista previa de la zona de coronación se quita **al cancelar** la orden (el diálogo y la ventana de
        confirmar tras «Calcular»), con **Esc a mitad del cálculo** (``_stop``), **al crear** el contrafuerte (ya existe) y **al conmutar a la
        interfaz de Blender** (ida y vuelta deja Blender como estaba: los manejadores de dibujo, el temporizador y los ganchos; y volver no la
        pone sola); la de las marcas, también al conmutar y al cerrar el proyecto. «Calcular» no la quita. Nada escrito mientras tanto."""
        entity, switcher = self.entity, self.switcher
        before_fingerprint = blender_ext.state_fingerprint()
        before = self.untouched()
        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form()), {"FINISHED"})  # «Calcular»: se sigue viendo
        self.assertTrue(entity.enabled())
        self.assertIsNotNone(self.des_ops.calculation())
        self.cls.cancel(self.fake_dialog(confirm=True), bpy.context)  # «Cancelar» en la ventana de confirmar
        self.assertFalse(entity.enabled() or entity.drawing())
        self.assertIsNone(self.des_ops.calculation())

        self.assertEqual(self.show(), {"FINISHED"})  # el diálogo cancelado sin calcular
        self.cls.cancel(self.fake_dialog(), bpy.context)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertFalse(bpy.app.timers.is_registered(entity.tick))
        self.assertEqual(self.untouched(), before)

        self.assertEqual(self.show(), {"FINISHED"})  # Esc a mitad del cálculo
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form(in_steps=True)), {"RUNNING_MODAL"})
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
        self.show_marks()  # la de las marcas: lo mismo
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            switcher.toggle(window, "GEOBLENDER")
        diff = blender_ext.fingerprint_diff(before_fingerprint, blender_ext.state_fingerprint())
        mine = [line for line in diff if line.startswith(("draw_handlers", "handlers", "timers")) and "switcher" not in line]
        self.assertEqual(mine, [], diff)  # sin el temporizador que el propio conmutador deja
        self.assertEqual(self.untouched(), before)

        self.show_marks()  # cerrar el proyecto
        self.assertIn(entity.on_project_changed, self.ps.listeners())
        self.ps.listeners()[self.ps.listeners().index(entity.on_project_changed)](None)
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertNotIn(entity.on_project_changed, self.ps.listeners())

        self.assertEqual(self.show(), {"FINISHED"})  # crear el contrafuerte la quita: ya existe
        self.pump()
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **self.form()), {"FINISHED"})
        self.assertTrue(entity.enabled())
        with mock.patch.object(self.des_ops.GEOBLENDER_OT_des_add_buttress, "_update_declared", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertFalse(entity.enabled() or entity.drawing())
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get(FIRST).record.code, "BTR-001")

    def test_g_with_100_marks_it_activates_in_a_second_and_each_redraw_takes_five_milliseconds(self) -> None:
        """RF-016-23, RNF-016-03: con **100 marcas** de la capa de verdad, **activarla ≤ 1 s** (la preparación de ``design`` —la capa, sus
        campos, las marcas rasterizadas, su ampliada por el margen y su contorno—, los pasos de su temporizador y los 5 ms de espera de cada
        uno) y **cada redibujo ≤ 5 ms** (los lotes, los nombres, la leyenda y el resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python
        de Geoblender; la GPU de verdad, M4). Se mide la mediana de 5; sin escribir nada. Se exige."""
        entity, constraints = self.entity, self.constraints
        before = self.untouched()
        interval = entity.TICK_INTERVAL_S
        self.assertEqual(interval, TICK_WAIT_S)
        walls: list[float] = []
        cpus: list[float] = []
        for _ in range(5):
            started, cpu = time.perf_counter(), time.process_time()
            entity.enable(entity.EntityPlan(stockpile=self.stockpile(MANY_LAYER)))
            ticks = 0
            for _tick in range(MAX_PUMPS):
                ticks += 1
                if entity.tick() is None:
                    break
            walls.append(time.perf_counter() - started + interval * max(0, ticks - 1))
            cpus.append(time.process_time() - cpu)
            built = entity.built()
            self.assertIsNotNone(built)
            if len(walls) < 5:
                entity.disable()
        self.assertEqual(len(entity.preview().marks), HUNDRED)
        self.assertEqual([batch.key for batch in built.lines.batches], [entity.MARKS, entity.MARGIN])
        self.assertEqual(self.batch(built, entity.MARKS).segments, 4 * HUNDRED)  # 2 × 2 celdas: un cuadrado de cuatro lados
        self.assertEqual(len(built.lines.labels), HUNDRED)
        self.assertEqual(len(built.lines.legend), 4)
        print(f"RNF-016-03 (T32): activarla con {HUNDRED} marcas (la preparación de verdad): mediana {statistics.median(walls) * 1000:.1f} ms de pared "
              f"y {statistics.median(cpus) * 1000:.1f} ms de CPU, la peor {max(walls) * 1000:.1f} ms (presupuesto 1000 ms)")
        self.assertLessEqual(statistics.median(walls), ACTIVATE_BUDGET_S)
        self.assertLessEqual(max(walls), ACTIVATE_BUDGET_S)
        self.assertEqual(self.untouched(), before)

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
        print(f"RNF-016-03 (T32): cada redibujo con {HUNDRED} marcas: mediana {statistics.median(redraws) * 1000:.2f} ms, "
              f"p95 {sorted(redraws)[int(0.95 * len(redraws))] * 1000:.2f} ms, la peor {max(redraws) * 1000:.2f} ms, "
              f"{len(items_on_screen)} elementos en pantalla (presupuesto 5 ms)")
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S)
        self.assertLessEqual(sorted(redraws)[int(0.95 * len(redraws))], REDRAW_BUDGET_S)  # y el percentil 95: la carga ajena no cuenta de más
        entity.disable()

    def test_z_disabling_geoblender_with_the_preview_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa de la zona de coronación activa, desactivar Geoblender quita los manejadores de dibujo, los
        ganchos, los avisos, el temporizador y los lotes, y la huella de Blender vuelve a la del principio de la sesión."""
        entity = self.entity
        self.assertEqual(self.show(), {"FINISHED"})
        self.assertTrue(entity.drawing())
        self.assertTrue(bpy.app.timers.is_registered(entity.tick))  # la construcción, sin acabar
        blender_ext.release()
        self.assertFalse(entity.enabled() or entity.drawing() or entity.building())
        self.assertIsNone(entity.built())
        self.assertIsNone(getattr(bpy.types, buttress_ops.ADD_CLASS, None))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(StockpilePreviewTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
