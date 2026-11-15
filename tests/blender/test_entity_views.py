# SPDX-License-Identifier: GPL-3.0-or-later
"""La entidad de diseño en la vista y la barra N «Entidad» (spec 015, T28; HU-015-1; RF-015-25, RF-010-06,
RF-010-08; D-12; plan 015 §5.1, §5.2.3 y §5.5; comprobación manual M3).

«Cargar en la vista» de la tabla de una entidad (``des_epr_<nombre>``): ``bl.scene.entity_views`` la carga como un
objeto ``DESIGN_ENTITY`` (``Object.geoblender.kind``) con su huella y su eje en alambre, a la cota de su superficie,
con el nombre generado de la vista («Entidad de diseño carga · V01 [VIGENTE]») y en la colección de su versión; y lo
que enseñan la barra N «Entidad» (``GEOBLENDER_PT_des_entity``, de la Vista 3D) y «Elemento activo» y «Cifras de la
selección» de la 010 del objeto seleccionado, **leído del proyecto**: sus parámetros con su insignia de tipo y su
origen, sus restricciones declaradas con su estado, su cadena, en qué se apoya y lo que se le apoya (una sola lista
con sus m³), sus cifras y su estado (al día, obsoleta con su causa, descartada, «apoyo retirado» o sin calcular).

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, la ladera
``100 + 0,25·y + 0,0625·x``), con una capa de plataformas más («Sobre Carga»), y cuatro entidades hechas con las
órdenes reales en V01: «Rampa» (PLT-001, **protege** con 4 m, lejos de las demás: se crea la primera para que las
máscaras que lee el resto ya lleven su restricción), «Carga» (PLT-002, corta del todo a 105 m), «Taller» (PLT-003,
**parte de la superficie** de «Carga») y «Sobre Carga» (PLT-004, de otro terreno, «en corte y relleno»: **se apoya** en
«Carga»). La huella de «Carga» (eje de 20 m, 8 m de ancho) son 10 × 4 = 40 celdas, de x = 20 a 40 y de y = 26 a 34. Las
pruebas, en el orden de sus letras sobre el mismo estado:

- RF-015-25 (a): ``DESIGN_ENTITY`` es un tipo de ``Object.geoblender`` con su rama «Design» y su icono; la tabla de la
  entidad tiene su cargador (no su superficie ni su informe) y la barra N es un panel real de la Vista 3D.
- RF-015-25 (b, c): cargar da un objeto por entidad con su huella y su eje, **a la cota de su superficie**, relativos al
  GeoOrigin y con matriz identidad; la vista no escribe nada; cerrar los pasos a mitad no deja nada; borrar el objeto y
  cargar de nuevo da **lo mismo** (los ``.blend`` son vistas, no la fuente).
- RF-015-25 (d, e): la barra N enseña el estado «al día», los parámetros con su insignia y su origen, la cadena, lo que se
  apoya en cada entidad y en qué se apoya (una sola lista con su volumen), las cifras, y de la que protege, su restricción
  declarada con su tipo, su resguardo y su estado «activa»; «Elemento activo» y «Cifras de la selección», las mismas
  líneas.
- RF-015-25, D-12 (f): un parámetro cambiado la deja **obsoleta con su causa**, y lo que se apoya en ella.
- RF-015-25, RF-015-11 (g): su restricción declarada, «bloqueada» por una edición fuera de Geoblender y, aceptada,
  «divergente».
- RF-015-25, RF-015-17, D-12 (h): **descartada** (registro, no usar) y, lo que se apoyaba en ella, «apoyo retirado» con su causa.
- RF-015-25, D-12 (i): una entidad **sin calcular** (la que deja «Traer las entidades de…»).
- RF-015-25, principio 10 (j): en inglés todo sale en inglés; cada lectura del proyecto tarda menos de 0,2 s de CPU; un
  objeto del usuario o de otro proyecto no tiene ficha.
- Principio 8 (z): desactivar Geoblender quita el cargador, la barra N y su lectura y deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import json
import sqlite3
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw

KIND = "DESIGN_ENTITY"
PANEL = "GEOBLENDER_PT_des_entity"
LOAD = "geoblender.core_load_into_view"
VIEW_PROPERTY = "geoblender_design"
OVER = "Sobre Carga"
LOADING, WORKSHOP, RAMP = platform_ops.LOADING, platform_ops.WORKSHOP, platform_ops.RAMP
CODES = {RAMP: "PLT-001", LOADING: "PLT-002", WORKSHOP: "PLT-003", OVER: "PLT-004"}
WHY = "La propiedad cambia el plan: la carga no se hace"
EDGE_FLAG = "gb_axis"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_TICKS = 400
LEVELS = {RAMP: 100.0, LOADING: 105.0, WORKSHOP: 107.5}
"""La cota de la rasante de cada plataforma (la de su capa: «Taller» a 107,5 m con el diálogo)."""


def _module(name: str) -> Any:
    return platform_ops._module(name)


class EntityViewsTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con una capa más, otro terreno
    y las cuatro entidades de la prueba (b)."""

    ground2: str
    ground3: str
    uids: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        extra = (OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0)
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, extra)):
            super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.ground3 = cls.write_grid("Ladera 3", platform_ops.ground())  # de cada superficie parte una sola entidad
        cls.refresh()
        cls.view_panels = _module("bl.ui.view_panels")
        cls.views = _module("bl.scene.views")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.mesh = _module("bl.scene.mesh")
        cls.core_props = _module("bl.props.core")
        cls.ui_provenance = _module("bl.ui.provenance")
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.cstore = _module("gis.masks.store")
        cls.uids = {}

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def origin(self) -> Any:
        return self.project.origin

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``: sus
        temporizadores no corren en ``blender -b``, se avanzan a mano); si queda algo pendiente."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        pending = bool(self.des_ops.pending_runs() or gis_ops.pending_mask_runs() or res_ops.pending_runs())
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()
        return pending

    def recompute(self) -> None:
        """Lanza «Recalcular lo obsoleto» y lo lleva hasta el final (el modal, con la cola de ``des`` avanzada a mano), sin
        pedir ninguna confirmación: lo que sigue a crear la entidad que protege (D-21: la que consumió las máscaras de antes
        queda obsoleta)."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale)
                     and getattr(op, "_steps", None) is not None]
            self.assertEqual(len(found), 1)
            operator = found[0]
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
        for _ in range(MAX_TICKS):
            state = operator.modal(bpy.context, TIMER)
            self.tick()
            if state != {"RUNNING_MODAL"}:
                ask.assert_not_called()
                return
        self.fail("el recálculo no termina")

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que ver no cambia)."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def loaded(self) -> dict[str, Any]:
        """Los objetos ``DESIGN_ENTITY`` de la escena por el uid de su dato."""
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects if obj.geoblender.kind == KIND}

    def load(self, *names: str) -> None:
        for name in names:
            self.assertEqual(getattr(bpy.ops.geoblender, "core_load_into_view")(datasets=self.uids[name]), {"FINISHED"})

    def choose(self, name: str) -> Any:
        """Selecciona y activa el objeto de la entidad ``name`` y lee su ficha como lo hace Blender al cambiar el objeto
        activo."""
        obj = self.loaded()[self.uids[name]]
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        return obj

    def refresh_card(self) -> None:
        """El proyecto cambió: la escucha vuelve a leer la ficha del objeto activo."""
        self.project.refresh_header()
        self.ui_provenance.refresh(force=True)  # la escucha de los indicadores lee la ficha otra vez (haya cambiado o no su cuenta)

    def panel_texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    def lines(self) -> list[tuple[str, str, bool]]:
        """Las líneas de la barra N ya leídas: (cómo se dibuja, texto, si va en alerta)."""
        return [(row.kind, row.name, bool(row.alert)) for row in self.view.item]

    def texts(self) -> list[str]:
        return [text for _kind, text, _alert in self.lines()]

    def section(self, heading: str) -> list[tuple[str, bool]]:
        """Las líneas de un apartado de la barra N (hasta el siguiente título): (texto, alerta)."""
        found: list[tuple[str, bool]] = []
        inside = False
        for kind, text, alert in self.lines():
            if kind == "heading":
                if inside:
                    break
                inside = text == heading
            elif inside:
                found.append((text, alert))
        return found

    def state_line(self) -> tuple[str, bool]:
        kind, text, alert = self.lines()[0]
        self.assertEqual(kind, "field")
        return text, alert

    def entry(self, name: str) -> Any:
        return self.entities.registry(self.project, self.v01.uid).get(CODES[name])

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas locales de la prueba (desde el SO de la ventana) respecto al GeoOrigin."""
        return (platform_ops.WEST + x - self.origin.x0, platform_ops.SOUTH + y - self.origin.y0)

    def alert_texts(self) -> str:
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        return " ".join(item.text for item in layout.of_kind("label") if item.alert)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_kind_the_loader_and_the_side_panel(self) -> None:
        """RF-015-25 (plan §5.1): ``DESIGN_ENTITY`` es un tipo de ``Object.geoblender`` con su nombre y su descripción y su
        rama «Design»; la tabla ``des_epr_`` de la entidad tiene su cargador (su superficie ``des_psf_`` y su informe
        ``des_prp_``, no: son un dato más de la entidad); la barra N «Entidad» es un panel real de la Vista 3D y su pestaña,
        la del menú «Entidad ▾» del catálogo; el icono del tipo (``gb_kind_design_entity``) está declarado y «Elemento
        activo» da las líneas más de su tipo."""
        kinds = {item[0]: item for item in self.core_props.OBJECT_KINDS}
        self.assertIn(KIND, kinds)
        self.assertTrue(all(kinds[KIND][1:]), "con nombre y descripción")
        self.assertEqual(self.views.BRANCHES[KIND], (("design", "Design"),))
        loader = self.views.loader_for("des_epr_carga")
        self.assertEqual((loader.prefix, loader.kind, loader.label), ("des_epr_", KIND, "Design entity"))
        self.assertEqual(self.entity_views.KIND, KIND)
        for name in ("des_psf_carga", "des_prp_carga", "des_decl", "des_enl"):
            self.assertIsNone(self.views.loader_for(name), name)
        panel = getattr(bpy.types, PANEL)
        self.assertIn(panel, self.panels.classes)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_category, panel.bl_label),
                         ("VIEW_3D", "UI", "Entidad", "Entidad"))
        catalog = self.commands.catalog()
        self.assertEqual(self.commands.text(catalog.commands[catalog.contexts[KIND].id].label), "Entidad")
        self.assertFalse(panel.poll(bpy.context), "sin objeto de entidad")
        self.assertIn("gb_kind_design_entity", catalog.icons)
        self.assertIn(KIND, self.view_panels._OBJECT_LINES)  # noqa: SLF001

    def test_b_four_entities_are_made_with_the_real_commands(self) -> None:
        """RF-015-25 (el mundo de estas pruebas): «Rampa» protege (y, como consumió las máscaras de antes, «Recalcular lo
        obsoleto» la rehace: D-21); «Carga» corta del todo; «Taller» parte de la superficie de «Carga» y «Sobre Carga», de
        otro terreno, se apoya en ella; todas al día."""
        self.made(name=RAMP, feature=RAMP, protect=True, guard="4", start=self.ground3)
        self.assertEqual(self.entry(RAMP).record.state.value, "stale", "consumió las máscaras de antes de declarar")
        self.recompute()
        self.made()
        self.made(name=WORKSHOP, feature=WORKSHOP, start="entity:PLT-002", start_level="107,5", gradient="0", width="5",
                  reach="6")
        self.made(name=OVER, feature=OVER, start=self.ground2, mode="CUT_FILL")
        registry = self.entities.registry(self.project, self.v01.uid)
        self.assertEqual({entry.record.name: (entry.record.code, str(entry.record.state)) for entry in registry},
                         {name: (code, "current") for name, code in CODES.items()})
        type(self).uids = {name: self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'",
                                           self.dprov.dataset_name("epr", name))[0][0] for name in CODES}

    def test_c_load_one_object_per_entity_on_the_surface_and_regenerate_it(self) -> None:
        """RF-015-25, ADR-0005 (M3): «Cargar en la vista» de una entidad da un objeto ``DESIGN_ENTITY`` con el nombre de la
        vista («Entidad de diseño carga · V01 [VIGENTE]»), en la colección de su dato bajo la de su versión, con matriz
        identidad, y su huella (el contorno de sus 40 celdas, de x = 20 a 40 y de y = 26 a 34) y su eje (de (20, 30) a
        (40, 30)) en alambre, con sus vértices —vueltos a absolutos— **a la cota de su superficie** (105 m); la vista no
        escribe nada, cerrar los pasos a mitad no deja nada y **borrar el objeto y cargar de nuevo da lo mismo**."""
        files, operations = self.files(), self.operations()
        meshes = len(bpy.data.meshes)
        steps = self.views.load_steps(bpy.context, self.project, [self.uids[LOADING]])
        for _ in range(50):  # hasta que la malla está creada, antes del último paso
            step = next(steps)
            if len(bpy.data.meshes) > meshes:
                break
            self.assertIsNone(step.result, "se cargó sin pasar por la malla")
        self.assertGreater(len(bpy.data.meshes), meshes)
        steps.close()
        self.assertEqual((len(bpy.data.meshes), self.loaded()), (meshes, {}))

        self.load(*CODES)
        self.assertEqual((self.files(), self.operations()), (files, operations))
        found = self.loaded()
        self.assertEqual(set(found), set(self.uids.values()))
        for name, code in CODES.items():
            with self.subTest(entidad=name):
                obj = found[self.uids[name]]
                self.assertEqual(obj.name, f"Entidad de diseño {self.dprov.dataset_name('epr', name)[8:]} · V01 [VIGENTE]")
                self.assertEqual((obj.geoblender.kind, obj.geoblender.project_uid), (KIND, self.project.uid))
                self.assertEqual(obj.users_collection[0].get("geoblender_key"), f"dataset:{self.uids[name]}")
                path = self.views.collection_path(obj.users_collection[0])
                self.assertTrue(path[-1].startswith("Entidad de diseño"), path)
                self.assertTrue(path[-2].startswith("V01"), path)
                self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))  # nunca el origen en location
                self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
                self.assertEqual(obj.display_type, "WIRE")
                world = self.mesh.mesh_vertices_world(obj.data, self.origin)
                self.assertTrue(np.isfinite(world).all())
                axis = self.mesh.edge_flags(obj.data, EDGE_FLAG)
                self.assertIsNotNone(axis, "las aristas del eje van marcadas")
                self.assertTrue(axis.any() and not axis.all(), "la huella y el eje")
        # La huella y el eje de «Carga», a mano, a su cota.
        obj = found[self.uids[LOADING]]
        world = self.mesh.mesh_vertices_world(obj.data, self.origin)
        edges, axis = self.mesh.mesh_edges(obj.data), self.mesh.edge_flags(obj.data, EDGE_FLAG)
        outline = np.unique(edges[~axis])
        spine = np.unique(edges[axis])
        self.assertEqual(world[outline, :2].min(axis=0).tolist(), [platform_ops.WEST + 20.0, platform_ops.SOUTH + 26.0])
        self.assertEqual(world[outline, :2].max(axis=0).tolist(), [platform_ops.WEST + 40.0, platform_ops.SOUTH + 34.0])
        self.assertEqual(sorted(world[spine, :2].tolist()),
                         [[platform_ops.WEST + 20.0, platform_ops.SOUTH + 30.0],
                          [platform_ops.WEST + 40.0, platform_ops.SOUTH + 30.0]])
        np.testing.assert_allclose(world[:, 2], LEVELS[LOADING], atol=1e-3)
        for name in (RAMP, WORKSHOP):  # la cota de cada una es la de su rasante
            other = self.mesh.mesh_vertices_world(found[self.uids[name]].data, self.origin)
            np.testing.assert_allclose(other[:, 2], LEVELS[name], atol=1e-3)
        # Cargar de nuevo lo sustituye (no se duplica) y regenerar un objeto borrado da lo mismo (RF-015-25).
        before = (world.tolist(), edges.tolist(), axis.tolist(), obj.name)
        collection = obj.users_collection[0]
        mesh = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(collection)
        self.assertNotIn(self.uids[LOADING], self.loaded())
        self.load(LOADING)
        again = self.loaded()[self.uids[LOADING]]
        self.assertEqual(len(self.loaded()), 4)
        self.assertEqual((self.mesh.mesh_vertices_world(again.data, self.origin).tolist(),
                          self.mesh.mesh_edges(again.data).tolist(),
                          self.mesh.edge_flags(again.data, EDGE_FLAG).tolist(), again.name), before)
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_c_b_the_height_of_a_vertex_is_the_mean_of_the_footprint_cells_that_touch_it(self) -> None:
        """RF-015-25 (a mano): la cota de un vértice de rejilla es la media de las celdas de la huella **con dato** que lo
        tocan; en el borde de la rejilla solo cuentan las que existen; un vértice que ninguna toca es NaN (y la vista le da
        la media de la huella)."""
        values = np.arange(16, dtype=np.float64).reshape(4, 4)
        mask = np.zeros((4, 4), dtype=bool)
        mask[1:3, 1:3] = True  # las celdas de valores 5, 6, 9 y 10
        values[1, 1] = np.nan  # una sin dato no cuenta
        rows = np.array([2, 3, 2, 1, 0, 0])
        cols = np.array([2, 3, 1, 1, 0, 4])
        found = self.entity_views.corner_heights(rows, cols, values, mask)
        # (2, 2): las cuatro celdas de la huella (5 sin dato): 6, 9 y 10; (3, 3): solo la de valor 10; (2, 1): la sin dato y la de 9.
        np.testing.assert_allclose(found[:3], [(6.0 + 9.0 + 10.0) / 3, 10.0, 9.0])
        self.assertTrue(np.isnan(found[3:]).all(), "solo toca la de la huella sin dato, o ninguna de la huella, o la rejilla acaba")

    def test_d_the_side_panel_shows_state_parameters_chain_what_rests_on_it_and_figures(self) -> None:
        """RF-015-25, RF-015-15, RF-010-06 (M3): seleccionar el objeto de «Carga» lee su ficha del proyecto (al cambiar el
        objeto activo, no al dibujar) y la barra N enseña su título, su estado «al día», sus **parámetros con su insignia
        de tipo y su origen** («capa «gis_fea_plataformas», campo «pendiente», entidad «Carga»»), su **cadena** (de qué
        superficie parte, qué entidad parte de la suya y cuál es la última), **en qué se apoya** y **lo que se le apoya en
        una sola lista con sus m³** (el taller que parte de su superficie y «Sobre Carga» con lo que apoya, tal como lo dice
        el dominio) y sus cifras con su insignia; no declara ninguna restricción."""
        panel = getattr(bpy.types, PANEL)
        files, operations = self.files(), self.operations()
        self.choose(LOADING)
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((self.view.item_uid, self.view.item_project, self.view.item_found),
                         (self.uids[LOADING], self.project.uid, True))
        with mock.patch.object(self.project, "read", side_effect=AssertionError("se lee al dibujar")):
            shown = self.panel_texts()  # nada se lee al dibujar
        self.assertEqual(self.view.item_title, "Plataforma Carga (PLT-002)")
        self.assertIn("Plataforma Carga (PLT-002)", shown)
        self.assertEqual(self.state_line(), ("Al día", False))
        params = [text for text, _alert in self.section("Parámetros")]
        slope = next(text for text in params if text.startswith("Pendiente de la rasante de la plataforma: "))
        for part in ("0 %", "[ADO]", "V01", "capa «gis_fea_plataformas», campo «pendiente», entidad «Carga»"):
            self.assertIn(part, slope)
        start = next(text for text in params if text.startswith("Cota inicial de la plataforma: "))
        self.assertIn("105 m [ADO]", start)
        self.assertIn("campo «cota_inicial»", start)
        mode = next(text for text in params if text.startswith("Modo de la plataforma: "))
        self.assertIn("cut [ADO] · V01 · diálogo de «Plataforma…», entidad «Carga»", mode)  # lo elegido en el diálogo
        mesh = next(text for text in params if text.startswith("Factor de malla del borde de la plataforma: "))
        self.assertIn("1 [ADO] · V01 · Spec 015, D-7", mesh)  # un valor por defecto: el origen es el de su definición
        surface = next(text for text in params if text.startswith("Superficie de partida de la entidad: "))
        self.assertIn(self.ground, surface)
        self.assertFalse([text for text in params if text.startswith("Nombre")], "el nombre es el título")
        self.assertTrue(all(not alert for _text, alert in self.section("Parámetros")))
        self.assertEqual(self.section("Restricciones declaradas"), [("No declara ninguna restricción", False)])
        chain = [text for text, _alert in self.section("Cadena")]
        self.assertEqual(chain, [f"Parte de: {self.ground}", f"De su superficie parte: {WORKSHOP} (PLT-003)",
                                 f"Última de su cadena: {WORKSHOP} (PLT-003)"])
        rests_on = [text for text, _alert in self.section("Se apoya en")]
        self.assertEqual(len(rests_on), 1, rests_on)
        self.assertIn(self.ground, rests_on[0])
        by_name = {row.name: row for row in self.entities.dependents(self.project, self.v01.uid, "PLT-002")}
        self.assertEqual(set(by_name), {WORKSHOP, OVER})
        self.assertIsNone(by_name[WORKSHOP].volume_m3)
        self.assertGreater(by_name[OVER].volume_m3, 100.0)
        dependents = [text for text, _alert in self.section("Lo que se apoya en ella")]
        self.assertEqual(dependents, [by_name[WORKSHOP].text("es"), by_name[OVER].text("es")])
        self.assertIn("superficie de partida", dependents[0])
        self.assertIn("m³ apoyados", dependents[1])
        # Las cifras registradas, con su insignia, menos los volúmenes apoyados (van en las listas).
        figures_mod = _module("core.provenance.figures")
        stored = [figures_mod.FigureRecord.from_row(row) for row in self.rows(
            f"SELECT {figures_mod.RECORD_COLUMNS} FROM gb_figure AS f WHERE operation_uid = "
            "(SELECT operation_uid FROM gb_dataset WHERE uid = ?) ORDER BY fid", self.uids[LOADING])]
        wanted = [f"[CAL] {self.dprov.figure_text(figure, language='es')}" for figure in stored
                  if figure.key != "des.supported_m3"]
        self.assertGreater(len(wanted), 8)
        self.assertEqual(self.section("Cifras"), [(text, False) for text in wanted])
        self.assertEqual({row.kind for row in self.view.item if row.uid}, {"figure"})
        self.assertEqual((self.files(), self.operations()), (files, operations))
        # La que sobre ella se apoya, la que parte de ella y la última de su cadena, por su lado.
        self.choose(WORKSHOP)
        self.assertEqual(self.view.item_title, "Plataforma Taller (PLT-003)")
        self.assertEqual([text for text, _alert in self.section("Cadena")],
                         [f"Parte de la superficie de {LOADING} (PLT-002)", "Ninguna entidad parte de su superficie",
                          "Es la última de su cadena"])
        up = [text for text, _alert in self.section("Se apoya en")]
        self.assertEqual(up, [next(row for row in self.entities.dependencies_of(
            self.project, self.v01.uid, "PLT-003")).text("es")])
        self.assertIn(f"{LOADING} (Plataforma): superficie de partida", up[0])
        self.assertEqual(self.section("Lo que se apoya en ella"), [("Nada se apoya en ella", False)])
        self.choose(OVER)
        self.assertEqual([text for text, _alert in self.section("Se apoya en")][0],
                         next(row for row in self.entities.dependencies_of(
                             self.project, self.v01.uid, "PLT-004")).text("es"))
        self.assertIn("m³ apoyados", self.section("Se apoya en")[0][0])

    def test_e_a_protecting_entity_shows_its_declared_constraint_and_the_active_item_the_same_lines(self) -> None:
        """RF-015-25, RF-015-10, RF-010-06, RF-010-08 (M3): la entidad que protege («Rampa») enseña su restricción declarada
        —su tipo («Sin relleno»), su nombre como se lee («Plataforma Rampa (declarada)»), su resguardo, su motivo, quién
        la decidió y su estado «Activa»—; «Elemento activo» enseña, tras su ficha, las mismas líneas (sin las cifras, que ya
        son las de su ficha) y «Cifras de la selección», también; un objeto del usuario no las tiene."""
        self.choose(RAMP)
        self.assertEqual(self.view.item_title, "Plataforma Rampa (PLT-001)")
        declared = self.section("Restricciones declaradas")
        self.assertEqual(len(declared), 5, declared)
        self.assertEqual(declared[0], ("Sin relleno · Plataforma Rampa (declarada)", False))
        self.assertEqual(declared[1], ("Activa", False))
        self.assertEqual(declared[2], ("Resguardo: 4 m", False))
        self.assertEqual(declared[3], ("Motivo: declarada por la plataforma Rampa", False))
        self.assertTrue(declared[4][0].startswith("Decidida por: "), declared[4])
        parameters = [text for text, _alert in self.section("Parámetros")]
        self.assertTrue([text for text in parameters if text.startswith("La plataforma protege su zona: sí [ADO]")],
                        parameters)
        self.assertTrue([text for text in parameters if text.startswith("Resguardo de la zona protegida: 4 m [ADO]")],
                        parameters)
        wanted = [text for kind, text, _alert in self.lines() if kind != "figure"]
        wanted = wanted[:wanted.index("Cifras")] if "Cifras" in wanted else wanted
        manager = bpy.context.window_manager
        self.assertTrue(self.view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(manager, self.view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(wanted):], wanted)
        self.assertEqual(self.view_panels.fill_selection_figures(bpy.context), 1)  # un dato
        selection = [row.text for row in getattr(manager, self.view_panels.WINDOW_MANAGER_PROPERTY).selection]
        self.assertTrue(set(wanted) <= set(selection))

    def test_f_a_changed_parameter_makes_it_stale_with_its_cause_and_what_rests_on_it(self) -> None:
        """RF-015-25, RF-015-16, D-12 (M3): si cambia la pendiente de la rasante de «Carga», la barra N dice, en alerta,
        «Obsoleto: …» con la causa que da la entidad (``stale_reason``: con **su nombre**, no su código); la de «Taller»,
        que parte de su superficie, también, con su causa, y en la lista de lo que se apoya en «Carga» salen las dos
        obsoletas, en alerta; la de «Rampa», que no depende de «Carga», sigue al día."""
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).change(
                conn, "des.platform.plt_002.gradient_pct", value=0.5, version=self.v01.uid, reason="Prueba de la barra N")
        self.choose(LOADING)
        self.refresh_card()
        text, alert = self.state_line()
        self.assertEqual(text, self.entities.stale_reason(self.project, self.v01.uid, "PLT-002"))
        self.assertTrue(text.startswith("Obsoleto: cambió Pendiente de la rasante de la plataforma · Carga"), text)
        self.assertTrue(alert)
        self.assertNotIn("Al día", self.texts())
        self.assertIn(text, " ".join(self.panel_texts()))  # partida al ancho de la barra N
        self.assertIn(text, self.alert_texts())
        stale = {row.name: row for row in self.entities.dependents(self.project, self.v01.uid, "PLT-002")}
        self.assertEqual({row.name: str(row.state) for row in stale.values()}, {WORKSHOP: "stale", OVER: "stale"})
        dependents = self.section("Lo que se apoya en ella")
        self.assertEqual([alert for _text, alert in dependents], [True, True])
        self.assertTrue(all(text.endswith(" · obsoleta") for text, _alert in dependents), dependents)
        self.choose(WORKSHOP)
        self.assertEqual(self.state_line()[0], self.entities.stale_reason(self.project, self.v01.uid, "PLT-003"))
        self.assertTrue(self.state_line()[1])
        self.choose(RAMP)
        self.assertEqual(self.state_line(), ("Al día", False))

    def test_g_the_declared_constraint_blocked_by_an_outside_edit_and_then_divergent(self) -> None:
        """RF-015-25, RF-015-11, RF-012-19 (M3): si la tabla de las declaradas de la versión se edita en QGIS, la barra N de
        «Rampa» dice «Bloqueada por una edición fuera de Geoblender», en alerta y con qué hacer; al aceptar la edición con un
        motivo (``core_resolve_dataset``), vuelve a «Activa» y avisa de que la declaración **difiere** de la de las
        entidades."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)  # QGIS, su conexión
        try:
            conn.execute('UPDATE "des_decl_v01" SET reason = ?', ("Retocada en QGIS",))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         ("2031-01-01T00:00:00.000Z", "des_decl_v01"))
        finally:
            conn.close()
        with self.assertRaises(RuntimeError) as refused:  # la puerta de la 008 lo ve al compilar y bloquea la tabla
            bpy.ops.geoblender.gis_compile_constraints()
        self.assertIn("se editó fuera de Geoblender", str(refused.exception))
        self.choose(RAMP)
        self.refresh_card()
        declared = self.section("Restricciones declaradas")
        self.assertEqual(declared[1], ("Bloqueada por una edición fuera de Geoblender", True))
        self.assertIn(("Acepte la edición con un motivo o recalcule la declaración: la entidad la vuelve a poner", True),
                      declared)
        self.assertNotIn("La declaración difiere de la de las entidades", [text for text, _alert in declared])
        uid = self.rows("SELECT uid FROM gb_dataset WHERE name = 'des_decl'")[0][0]
        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset("EXEC_DEFAULT", dataset_uid=uid, decision="ACCEPT",
                                                                 reason="La propiedad lo pide"), {"FINISHED"})
        self.refresh_card()
        declared = self.section("Restricciones declaradas")
        self.assertEqual(declared[1], ("Activa", False))
        self.assertIn(("La declaración difiere de la de las entidades", True), declared)
        self.assertIn(("Motivo: Retocada en QGIS", False), declared)

    def test_h_a_discarded_entity_is_a_record_and_what_rested_on_it_has_its_support_removed(self) -> None:
        """RF-015-25, RF-015-17, D-12 (M3): descartada «Carga», su barra N dice «Descartada» (queda como registro, no se
        usa), en alerta; «Taller» y «Sobre Carga», que se apoyaban en ella, «Apoyo retirado: se descartó la plataforma
        Carga», en alerta, y la lista de lo que se apoya en «Carga» las sigue enseñando, en «apoyo retirado»."""
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-002", reason=WHY, in_steps=False),
                         {"FINISHED"})
        self.choose(LOADING)
        self.refresh_card()
        self.assertEqual(self.entry(LOADING).record.state.value, "discarded")
        self.assertEqual(self.state_line(), ("Descartada: queda en el proyecto como registro y no se usa", True))
        self.assertTrue(self.view.item_found)
        retired = [text for text, _alert in self.section("Lo que se apoya en ella")]
        self.assertEqual(len(retired), 2)
        self.assertTrue(all(text.endswith(" · apoyo retirado") for text in retired), retired)
        for name in (WORKSHOP, OVER):
            self.choose(name)
            self.assertEqual(self.entry(name).record.state.value, "support_removed")
            self.assertEqual(self.state_line(), (f"Apoyo retirado: se descartó la plataforma {LOADING}", True))
            self.assertNotIn("Al día", self.texts())
        self.choose(RAMP)
        self.assertEqual(self.state_line(), ("Al día", False))

    def test_i_an_entity_without_calculating_shows_its_parameters_and_no_result(self) -> None:
        """RF-015-25, RF-015-18, D-12: una entidad **sin calcular** (la que deja «Traer las entidades de…»: sus parámetros en
        la versión y ningún resultado) dice «Sin calcular», enseña sus parámetros con su origen y su cadena y no tiene
        cifras ni se apoya en nada; no escribe nada. Como no tiene datos, no tiene objeto en la vista: la ficha por su
        código (``entity_card``) es lo que lee quien la elija."""
        _module("design.entity_store").bring_entities(self.project, self.v01.uid, self.v02.uid, codes=[WORKSHOP])
        self.assertEqual(self.entities.registry(self.project, self.v02.uid).get("PLT-003").record.state.value,
                         "uncalculated")
        files, operations = self.files(), self.operations()
        with self.project.read() as conn:
            found = self.panels.entity_card(self.project, self.v02.uid, "PLT-003", conn=conn)
        self.assertEqual(found.title, "Plataforma Taller (PLT-003)")
        lines = [(line.kind, line.text, line.alert) for line in found.lines]
        self.assertEqual(lines[0], ("field", "Sin calcular: tiene sus parámetros en esta versión y ningún resultado", False))
        self.assertTrue([text for _kind, text, _alert in lines if text.startswith("Pendiente de la rasante de la plataforma: ")
                         and "[ADO]" in text and " · V02 · capa «gis_fea_plataformas», campo «pendiente»" in text])
        self.assertIn(("none", "No se apoya en nada", False), lines)
        self.assertIn(("none", "Nada se apoya en ella", False), lines)
        self.assertEqual([line.text for line in found.figures], ["Cifras", "Sin cifras registradas"])
        # La partida que no existe en la versión queda sin valor (RF-015-18): lo dice, sin inventarla.
        self.assertEqual([text.split(" [")[0] for _k, text, _a in lines if text.startswith("Superficie de partida")],
                         ["Superficie de partida de la entidad: sin valor"])
        self.assertEqual((self.files(), self.operations()), (files, operations))
        with self.project.read() as conn:
            self.assertIsNone(self.panels.entity_card(self.project, self.v02.uid, "PLT-009", conn=conn))

    def test_j_in_english_and_each_read_is_short_and_what_is_not_an_entity_has_no_card(self) -> None:
        """RF-015-25, principio 10, RNF-013-07: en inglés todo sale en inglés (la pestaña, el título, los apartados y las
        líneas); cada lectura del proyecto para la barra N tarda menos de 0,2 s de CPU; un objeto del usuario o uno de
        entidad de otro proyecto no tienen ficha de este y no abren la barra N."""
        panel = getattr(bpy.types, PANEL)
        self.choose(RAMP)
        started = time.process_time()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertLess(time.process_time() - started, 0.2)
        spanish = self.panel_texts()
        self.ui_i18n.apply("en")
        self.addCleanup(self.ui_i18n.apply, "es")
        self.assertEqual((panel.bl_category, panel.bl_label), ("Entity", "Entity"))
        self.assertTrue(self.panels.read_selected(bpy.context))
        english = self.panel_texts()
        self.assertEqual(self.view.item_title, "Platform Rampa (PLT-001)")
        for wanted in ("Up to date", "Parameters", "Declared constraints", "Chain", "Rests on", "What rests on it", "Figures",
                       "No fill · Platform Rampa (declared)", "Active", "Guard: 4 m"):
            self.assertIn(wanted, self.texts())
        self.assertNotEqual(english, spanish)
        for text in self.texts():
            if not text.startswith("Reason: "):  # el motivo es un dato, tal como se guardó (en español)
                self.assertNotRegex(text, "(Al día|Parámetros|Restricciones|Cadena|apoya)", text)
        user = bpy.data.objects.new("Mío", None)
        foreign = bpy.data.objects.new("De otro proyecto", None)
        foreign.geoblender.kind = KIND
        foreign.geoblender.dataset_uid = self.uids[RAMP]
        foreign.geoblender.project_uid = "otro-proyecto"
        for obj in (user, foreign):
            bpy.context.scene.collection.objects.link(obj)
            self.addCleanup(bpy.data.objects.remove, obj)
            bpy.context.view_layer.objects.active = obj
            self.view_panels.on_active_changed()
            self.assertEqual(self.view.item_uid, "", obj.name)
            self.assertFalse(panel.poll(bpy.context), obj.name)

    def test_z_disable_leaves_nothing_of_the_entity_views(self) -> None:
        """Principio 8: con un objeto de entidad seleccionado, desactivar Geoblender quita el cargador, el panel de la barra
        N y su lectura, y la huella de Blender vuelve a la del principio de la sesión."""
        self.choose(RAMP)
        self.assertEqual(self.view.item_uid, self.uids[RAMP])
        self.assertIn(KIND, self.view_panels._OBJECT_LINES)  # noqa: SLF001
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertIsNone(getattr(bpy.types, PANEL, None))
        self.assertNotIn(KIND, self.view_panels._OBJECT_LINES)  # noqa: SLF001
        self.assertIsNone(self.views.loader_for("des_epr_carga"))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityViewsTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
