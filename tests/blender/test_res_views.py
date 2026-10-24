# SPDX-License-Identifier: GPL-3.0-or-later
"""La diferencia entre superficies y su vista (spec 011, T22; HU-011-1; plan 011 §5.3.3, §5.3.4,
A15, D-25, D-29, D-36).

- RF-011-05, RF-011-20: «Diferencia entre superficies…» es la orden real de la entrada «011»
  (no la provisional de R-38): escribe la rejilla de diferencias (final − partida, m) como dato
  de la versión activa (``res.difference`` en su revisión abierta) con sus seis cifras de los
  totales (ámbito ``{"difference": nombre}``) y ninguna tabla.
- RF-011-05 (A15, D-25): el cargador de ``res_dif_`` la carga sobre la superficie **final** (una
  cota constante, a esa cota), sin caras donde falta una de las dos, con un color por cara en
  tres clases —desmonte en rojos, terraplén en azules y sin movimiento en gris—, como objeto
  ``VOLUME_DIFFERENCE`` en la colección de su versión; su menú «Diferencia ▾» lleva Exportar a
  GeoTIFF…, Cifras de la selección y la procedencia.
- RF-011-23 (RF-010-06, RF-010-08): «Elemento activo» y «Cifras de la selección» del objeto
  enseñan sus seis cifras con [CAL].
- RF-011-05, D-29 (RF-006-24): «Exportar a GeoTIFF…» escribe el entregable desde lo registrado,
  por pasos, también de una versión SUPERADO y con el proyecto en solo lectura (fuera de él);
  sobre un fichero que ya existe, solo si se pide sustituirlo.

Un proyecto para toda la clase (V01 activa y V02), rejillas de 8 × 8 celdas de 1 m y la extensión
sin importar otra vez (``blender_ext.release``; RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import importlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import operator_self
from tests.support.trees import remove_tree

ENTRY = "011"
DIFFERENCE = "geoblender.res_compute_surface_difference"
EXPORT = "geoblender.res_export_difference"
CONTEXT_MENU = "GEOBLENDER_MT_res_context_difference"
KIND = "VOLUME_DIFFERENCE"
CELLS = 8
REASON = "Prueba de la diferencia entre superficies"
START, FINAL = "gis_dtm_septiembre", "gis_dtm_octubre"
ELEVATION = "ELEVATION"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_EVENTS = 200
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal (RNF-011-04)."""
STILL, CUT, FILL = 0, 1, 2
"""Las clases de cada cara (atributo ``gb_class``): sin movimiento, desmonte y terraplén."""
DIALOG = {"name": "", "start": START, "final": FINAL, "start_elevation": "",
          "final_elevation": "", "invert": False, "replace": False, "confirm": False,
          "in_steps": False}
"""Los valores por defecto del diálogo abierto a mano."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _start_values() -> np.ndarray:
    """Septiembre: 100 m en el oeste y 0,25 m más por columna."""
    return 100.0 + 0.25 * np.mgrid[0:CELLS, 0:CELLS][1].astype(np.float64)


def _moved() -> np.ndarray:
    """Lo que cambia cada columna de septiembre a octubre: +1 m en las tres del oeste
    (terraplén), nada en las dos del centro y −2 m en las tres del este (desmonte)."""
    return np.repeat(np.array([[1.0, 1.0, 1.0, 0.0, 0.0, -2.0, -2.0, -2.0]]), CELLS, axis=0)


def _final_values() -> np.ndarray:
    """Octubre: septiembre más :func:`_moved`, con un hueco en la esquina noroeste."""
    values = _start_values() + _moved()
    values[0, 0] = np.nan
    return values


def _expected(start: np.ndarray, final: np.ndarray | float) -> dict[str, float]:
    """Las seis cifras de los totales con espesor mínimo 0 y celdas de 1 m², sumadas aquí."""
    moved = np.broadcast_to(np.asarray(final, dtype=np.float64), start.shape) - start
    known = np.isfinite(moved)
    cut = float(np.where(known & (moved < 0), -moved, 0.0).sum())
    fill = float(np.where(known & (moved > 0), moved, 0.0).sum())
    return {"res.cut_m3": cut, "res.fill_m3": fill, "res.net_m3": cut - fill,
            "res.area_m2": float(known.sum()), "res.nodata_area_m2": float((~known).sum()),
            "res.still_area_m2": float((known & (moved == 0)).sum())}


def _surface(uid: str) -> SimpleNamespace:
    """Un objeto de la vista que muestra la rejilla ``uid`` (lo que lee ``invoke``)."""
    return SimpleNamespace(geoblender=SimpleNamespace(kind="DTM", dataset_uid=uid))


class ResDifferenceViewTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 activa en la sesión, para toda la
    clase (cada prueba con su propia diferencia)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.folder = Path(tempfile.mkdtemp(prefix="gb-r22-"))
        cls.addClassCleanup(remove_tree, cls.folder)
        cls.ps = _module("bl.scene.project_session")
        cls.res_ops = _module("bl.ops.res")
        cls.session = _module("bl.ops.core_provenance")
        cls.views = _module("bl.scene.views")
        cls.commands = _module("bl.ui.commands")
        cls.provenance = _module("reserves.provenance")
        (cls.folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=vf.WINDOW,
                                                                  grid_step_m=vf.STEP_M))
        cls.project = core_project.create_project(
            cls.folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva",
                                                      title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="sur",
                                                      title="Fase sur", reason=REASON)
        cls.project.refresh_header()
        cls.uids = cls.write_grids()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @classmethod
    def write_grids(cls) -> dict[str, str]:
        """Septiembre y octubre (8 × 8 celdas de 1 m), como las deja «Rejilla del proyecto
        desde un MDT» (``gis.resample``); el uid de cada una por su nombre de dato."""
        gis_store = _module("gis.store")
        Grid, Raster = _module("gis.grid").Grid, _module("gis.raster").Raster
        crs, vertical = gis_store.project_references(cls.project)
        grid = Grid(vf.WEST, vf.SOUTH + CELLS, 1.0, 1.0, CELLS, CELLS)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Meses"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            for name, values in (("Septiembre", _start_values()), ("Octubre", _final_values())):
                out.raster(name, Raster(grid, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return {record.name: record.uid for record in records}

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.enterContext(mock.patch.object(self.res_ops, "_call_panel",
                                            return_value={"FINISHED"}))

    # --- Ayudas -------------------------------------------------------------------------------

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def difference(self, name: str, **values: Any) -> tuple[str, str]:
        """«Diferencia entre superficies…» desde un guion (de una vez): el uid de su operación
        ``res.difference`` (hecha) y el de su rejilla ``res_dif_``."""
        self.assertEqual(bpy.ops.geoblender.res_compute_surface_difference(name=name, **values),
                         {"FINISHED"})
        found = [(uid, status) for uid, status, settings in self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = 'res.difference'")
            if json.loads(settings)["name"] == name]
        ((op_uid, status),) = found
        self.assertEqual(status, "done")
        slug = _module("gis.provenance").dataset_slug(name)
        ((grid_uid,),) = self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = "
                                   "'current'", f"res_dif_{slug}")
        return op_uid, grid_uid

    def shown(self, grid_uid: str) -> Any:
        """El único objeto de la vista que muestra la rejilla ``grid_uid``."""
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == grid_uid]
        self.assertEqual(len(found), 1)
        return found[0]

    def classes_by_column(self, mesh: Any) -> dict[int, set[int]]:
        """Las clases de las caras de ``mesh`` por el par de columnas de celdas que unen (la
        columna de la izquierda: 0 a 6), de su centro."""
        centers = np.empty(len(mesh.polygons) * 3, dtype=np.float32)
        mesh.polygons.foreach_get("center", centers)
        world_x = _module("core.georef").local_to_world(
            centers.reshape(-1, 3).astype(np.float64), self.project.origin)[:, 0]
        classes = np.empty(len(mesh.polygons), dtype=np.intc)
        mesh.attributes["gb_class"].data.foreach_get("value", classes)
        found: dict[int, set[int]] = {}
        for x, klass in zip(world_x, classes, strict=True):
            found.setdefault(int(np.floor(x - vf.WEST - 0.5)), set()).add(int(klass))
        return found

    def running(self, cls: type) -> Any:
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "la orden no está en marcha")
        return found[0]

    def drive(self, operator: Any) -> tuple[set[str], list[float]]:
        calls: list[float] = []
        for _ in range(MAX_EVENTS):
            started = time.perf_counter()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.perf_counter() - started)
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("la orden no acaba")

    # --- Pruebas ------------------------------------------------------------------------------

    def test_command_of_011_its_dialog_and_its_context_menu(self) -> None:
        """D-36, RF-011-05, RF-011-06: «Diferencia entre superficies…» es la orden real de la
        entrada «011» (``res.difference``, con la puerta de la procedencia y los pasos con
        Esc); su diálogo propone las dos superficies seleccionadas (de partida, la de mayor
        cota media) con el nombre, «Invertir» y nada más. El cargador de ``res_dif_`` es el de
        la 011 (tipo ``VOLUME_DIFFERENCE``) y el menú «Diferencia ▾» lleva Exportar a GeoTIFF…
        (interna de la 011), Cifras de la selección y la procedencia."""
        cat = self.commands.catalog()
        self.assertEqual(cat.commands[DIFFERENCE].entry, ENTRY)
        cls = self.commands.registered_class(DIFFERENCE)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.DIFFERENCE, {"REGISTER"}))
        context = SimpleNamespace(window=None, selected_objects=[
            _surface(self.uids[name]) for name in (FINAL, START)])
        fake = operator_self(cls, report=lambda kind, text: None,
                             properties=SimpleNamespace(is_property_set=lambda name: False),
                             **DIALOG)
        context.window_manager = SimpleNamespace(
            invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}))
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        cls.draw(fake, bpy.context)
        self.assertEqual((fake.start, fake.final, fake.name),
                         (START, FINAL, "octubre − septiembre"))
        self.assertEqual(
            context.window_manager.invoke_props_dialog.call_args.kwargs["title"],
            "Diferencia entre superficies…")
        self.assertEqual([item.target for item in fake.layout.of_kind("prop")],
                         ["name", "start", "invert", "final"])

        loader = self.views.loader_for("res_dif_x")
        self.assertEqual((loader.kind, loader.load),
                         (KIND, _module("bl.scene.res_views").load_difference))
        self.assertEqual((cat.commands[EXPORT].entry, cat.commands[EXPORT].kind),
                         (ENTRY, "internal"))
        self.assertFalse(self.commands.is_provisional(self.commands.registered_class(EXPORT)))
        spec = cat.contexts[KIND]
        self.assertEqual(spec.id, CONTEXT_MENU)
        self.assertEqual([item.key for item in spec.items],
                         [EXPORT, "geoblender.core_show_selection_figures",
                          "geoblender.core_show_lineage"])
        self.assertIsNotNone(getattr(bpy.types, CONTEXT_MENU, None))

    def test_difference_grid_of_the_version_and_its_view(self) -> None:
        """RF-011-05, RF-011-20, RF-011-23 (A15, D-25; RF-010-06, RF-010-08): la rejilla de
        diferencias es un dato de la revisión abierta de V01 con sus seis cifras (y ninguna
        tabla), que una cubicación con el mismo nombre no puede sustituir sin escribir nada; se
        carga sobre la superficie final, sin la celda sin dato, con sus caras en
        tres clases (terraplén en azules al oeste, sin movimiento en gris en el centro y
        desmonte en rojos al este), en la colección de V01; «Elemento activo» y «Cifras de la
        selección» enseñan sus seis cifras con [CAL]."""
        name = "Diferencia octubre"
        op_uid, grid_uid = self.difference(name, start=START, final=FINAL)
        ((revision,),) = self.rows("SELECT revision_uid FROM gb_operation WHERE uid = ?", op_uid)
        self.assertEqual(self.rows("SELECT version_uid FROM gb_revision WHERE uid = ?",
                                   revision), [(self.v01.uid,)])
        slug = _module("gis.provenance").dataset_slug(name)
        self.assertEqual(self.rows("SELECT name FROM gb_dataset WHERE operation_uid = ?",
                                   op_uid), [(f"res_dif_{slug}",)])
        scope = _module("core.provenance.figures").scope_json({"difference": name})
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ? AND "
                                 "scope = ?", op_uid, scope))
        expected = _expected(_start_values(), _final_values())
        self.assertEqual(figures, expected)
        self.assertEqual((expected["res.cut_m3"], expected["res.fill_m3"],
                          expected["res.still_area_m2"]), (48.0, 23.0, 16.0))
        counter = vf.change_counter(self.project)  # una cubicación no comparte su rejilla
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.res_compute_volume_between_surfaces(name=name, start=START,
                                                                   final=FINAL)
        self.assertIn(f"Ya hay una rejilla de diferencias «{name}» en V01, de «Diferencia entre "
                      "superficies»", str(caught.exception))
        self.assertEqual(vf.change_counter(self.project), counter)

        obj = self.shown(grid_uid)
        self.assertEqual(obj.geoblender.kind, KIND)
        (collection,) = obj.users_collection
        version_collection = _module("bl.scene.versions").version_collections()[self.v01.uid]
        self.assertIn(collection, version_collection.children.values())
        mesh = obj.data
        world = _module("bl.scene.mesh").mesh_vertices_world(mesh, self.project.origin)
        columns = np.floor(world[:, 0] - vf.WEST).astype(int)
        rows = np.floor(vf.SOUTH + CELLS - world[:, 1]).astype(int)
        self.assertEqual(len(world), CELLS * CELLS - 1)  # sin la celda sin dato
        self.assertFalse(((rows == 0) & (columns == 0)).any())
        np.testing.assert_allclose(world[:, 2], _final_values()[rows, columns], atol=1e-3)
        self.assertEqual(len(mesh.polygons), 2 * (CELLS - 1) ** 2 - 1)
        self.assertEqual(self.classes_by_column(mesh),
                         {0: {FILL}, 1: {FILL}, 2: {FILL}, 3: {STILL}, 4: {CUT}, 5: {CUT},
                          6: {CUT}})
        attribute = mesh.attributes["gb_color"]
        self.assertEqual((attribute.domain, attribute.data_type), ("FACE", "FLOAT_COLOR"))
        colors = np.empty(len(mesh.polygons) * 4, dtype=np.float32)
        attribute.data.foreach_get("color", colors)
        colors = colors.reshape(-1, 4)
        classes = np.empty(len(mesh.polygons), dtype=np.intc)
        mesh.attributes["gb_class"].data.foreach_get("value", classes)
        self.assertTrue((colors[classes == CUT, 0] > colors[classes == CUT, 2]).all())
        self.assertTrue((colors[classes == FILL, 2] > colors[classes == FILL, 0]).all())
        still = colors[classes == STILL]
        self.assertTrue(((still[:, 0] == still[:, 1]) & (still[:, 1] == still[:, 2])).all())
        self.assertEqual(len(mesh.materials), 1)

        self.assertEqual(sorted((item.key, item.kind) for item in obj.geoblender.figures),
                         sorted((key, "CALCULADO") for key in expected))
        view_panels = _module("bl.ui.view_panels")
        manager = bpy.context.window_manager
        bpy.context.view_layer.objects.active = obj
        self.assertTrue(view_panels.read_card(bpy.context))
        view = getattr(manager, view_panels.WINDOW_MANAGER_PROPERTY)
        card = [row.text for row in view.card if row.kind == view_panels.ROW_FIGURE]
        self.assertEqual(len(card), 6)
        self.assertTrue(all(text.startswith("[CAL] ") for text in card), card)
        self.assertEqual(view_panels.fill_selection_figures(
            SimpleNamespace(selected_objects=[obj], window_manager=manager)), 1)
        selection = [row.text for row in view.selection if row.kind == view_panels.ROW_FIGURE]
        self.assertEqual(len(selection), 6)
        self.assertTrue(all(text.startswith("[CAL] ") for text in selection), selection)

    def test_constant_final_elevation_is_drawn_at_that_elevation(self) -> None:
        """RF-011-05, RF-011-02 (A15): con una cota constante de final, la rejilla se carga a
        esa cota, con la celda sin dato de septiembre incluida (la cota tiene dato en todas)
        y sus cifras."""
        name = "Contra cota"
        op_uid, grid_uid = self.difference(name, start=START, final=ELEVATION,
                                           final_elevation="101")
        mesh = self.shown(grid_uid).data
        world = _module("bl.scene.mesh").mesh_vertices_world(mesh, self.project.origin)
        self.assertEqual(len(world), CELLS * CELLS)
        np.testing.assert_allclose(world[:, 2], 101.0, atol=1e-3)
        classes = np.empty(len(mesh.polygons), dtype=np.intc)
        mesh.attributes["gb_class"].data.foreach_get("value", classes)
        self.assertEqual(set(classes.tolist()), {CUT, FILL})
        scope = _module("core.provenance.figures").scope_json({"difference": name})
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ? AND "
                                 "scope = ?", op_uid, scope))
        self.assertEqual(figures, _expected(_start_values(), 101.0))

    def test_export_to_geotiff_also_of_a_superseded_version(self) -> None:
        """RF-011-05, D-29 (RF-006-24, RF-008-15): «Exportar a GeoTIFF…» escribe, por pasos
        (ninguna llamada del modal de más de 0,2 s), el entregable con las diferencias
        registradas de una rejilla de V02 aunque V02 esté SUPERADO; sobre el mismo fichero,
        desde un guion, se rechaza si no se pide sustituirlo, y con el proyecto en solo lectura
        sigue escribiendo fuera de él."""
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        _op_uid, grid_uid = self.difference("Superada", start=START, final=FINAL)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v01)
        target = self.folder / "entregas" / "superada.tif"
        target.parent.mkdir()
        cls = self.commands.registered_class(EXPORT)
        self.assertTrue(cls.poll(bpy.context))
        self.assertEqual(bpy.ops.geoblender.res_export_difference(
            "EXEC_DEFAULT", source=grid_uid, filepath=str(target), in_steps=True),
            {"RUNNING_MODAL"})
        state, calls = self.drive(self.running(cls))
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        written = _module("gis.geotiff.reader").read_geotiff(target, max_cells=CELLS * CELLS)
        np.testing.assert_array_equal(written.values, _final_values() - _start_values())

        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.res_export_difference(source=grid_uid, filepath=str(target))
        self.assertIn("Ya existe «superada.tif»", str(caught.exception))
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertTrue(cls.poll(bpy.context))
            self.assertEqual(bpy.ops.geoblender.res_export_difference(
                source=grid_uid, filepath=str(target), overwrite=True), {"FINISHED"})
        self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
