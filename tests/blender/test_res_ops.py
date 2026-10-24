# SPDX-License-Identifier: GPL-3.0-or-later
"""Las órdenes de la cubicación (spec 011; plan 011 §5.3.4, §5.5, A10, A11, D-19, D-25, D-30,
D-31, D-36).

**Entre dos superficies… (Mayús+Alt+M)** (T21; HU-011-1; RF-011-01, RF-011-02, RF-011-03,
RF-011-04, RF-011-06, RF-011-20, RF-011-25, RF-011-26):

- RF-011-06 (D-31): con dos superficies seleccionadas en la vista, el diálogo las propone (de
  partida, la de mayor cota media en sus celdas comunes, sea cual sea el orden de la selección)
  con el nombre «<final> − <partida>»; «Invertir» las cambia; Intro cubica. La orden es la real
  de la entrada «011» (no la provisional de R-38) con su atajo de la Vista 3D.
- RF-011-01, RF-011-04, RF-011-20, RF-011-25: desde la interfaz, ``res.volume`` por pasos en el
  modal de la orden (un evento cada vez, ninguna llamada de más de 0,2 s) con su avance en la
  barra de estado; Esc a mitad no deja ni cifra, ni tabla, ni rejilla (la operación,
  cancelada); terminada, el desmonte, el terraplén, el neto y las áreas (con dato, sin dato y
  sin movimiento) celda a celda, de la revisión abierta de la versión activa, la rejilla de
  diferencias cargada en la vista y la ventana de la cubicación.
- RF-011-02, RF-011-03: una cota constante como final; dos superficies que no casan, el rechazo
  de A1 con las dos y la orden que lo resuelve, sin escribir nada.
- D-30: repetir el nombre de una cubicación de la versión pregunta si se sustituye; la nueva
  sustituye a la anterior.
- RF-011-20, RF-011-26: sin versión activa, la ventana de elegir o crear una; con la activa
  SUPERADO o el proyecto en solo lectura, desactivada con su motivo.

Un proyecto para toda la clase (V01 activa y V02), rejillas de 8 × 8 celdas de 1 m y la extensión
sin importar otra vez (``blender_ext.release``; RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import importlib
import json
import sqlite3
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
BETWEEN = "geoblender.res_compute_volume_between_surfaces"
PANEL = "GEOBLENDER_PT_res_volumetrics"
CELLS = 8
OTHER_CELLS = 4
REASON = "Prueba de las órdenes de la cubicación"
START, FINAL, OTHER = "gis_dtm_septiembre", "gis_dtm_octubre", "gis_dtm_otra"
ELEVATION = "ELEVATION"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 400
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal (RNF-011-04)."""
CANCELLED = "Cubicación cancelada: no ha quedado nada a medias"
DIALOG = {"name": "", "start": START, "final": FINAL, "start_elevation": "",
          "final_elevation": "", "invert": False, "scope_layer": "NONE",
          "difference_grid": True, "replace": False, "confirm": False, "in_steps": False}
"""Los valores por defecto del diálogo abierto a mano."""
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo que cambia al registrar una operación sin resultados: la base, su diario y la cabecera."""
SCOPE_RING = np.array([(vf.WEST + 1.5, vf.SOUTH - 1.0), (vf.WEST + 6.0, vf.SOUTH - 1.0),
                       (vf.WEST + 6.0, vf.SOUTH + CELLS + 1.0),
                       (vf.WEST + 1.5, vf.SOUTH + CELLS + 1.0), (vf.WEST + 1.5, vf.SOUTH - 1.0)],
                      dtype=np.float64)
"""El ámbito de la prueba: de la mitad de la columna 1 al final de la 5, de norte a sur."""
SCOPE_WEIGHTS = np.array([0.0, 0.5, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0])
"""La fracción de cada columna dentro de :data:`SCOPE_RING`."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _start_values() -> np.ndarray:
    """Septiembre: 100 m en el oeste y 0,25 m más por columna."""
    return 100.0 + 0.25 * np.mgrid[0:CELLS, 0:CELLS][1].astype(np.float64)


def _final_values() -> np.ndarray:
    """Octubre: 100,75 m (la columna 3 de septiembre, sin movimiento) con un hueco en la esquina
    noroeste."""
    values = np.full((CELLS, CELLS), 100.75, dtype=np.float64)
    values[0, 0] = np.nan
    return values


def _expected(start: np.ndarray, final: np.ndarray | float,
              weights: np.ndarray | float = 1.0) -> dict[str, float]:
    """Las seis cifras de los totales con espesor mínimo 0 y celdas de 1 m², sumadas aquí; con
    ``weights``, la fracción de cada celda dentro del ámbito (por columnas)."""
    moved = np.broadcast_to(np.asarray(final, dtype=np.float64), start.shape) - start
    weight = np.broadcast_to(np.asarray(weights, dtype=np.float64), start.shape)
    known = np.isfinite(moved)
    cut = float((weight * np.where(known & (moved < 0), -moved, 0.0)).sum())
    fill = float((weight * np.where(known & (moved > 0), moved, 0.0)).sum())
    return {"res.cut_m3": cut, "res.fill_m3": fill, "res.net_m3": cut - fill,
            "res.area_m2": float((weight * known).sum()),
            "res.nodata_area_m2": float((weight * ~known).sum()),
            "res.still_area_m2": float((weight * (known & (moved == 0))).sum())}


def _files(root: Path) -> list[str]:
    """Los ficheros de la carpeta del proyecto (sin la base, su diario y la cabecera)."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*")
                  if path.is_file() and path.relative_to(root).as_posix() not in WRITTEN)


def _surface(uid: str) -> SimpleNamespace:
    """Un objeto de la vista que muestra la rejilla ``uid`` (lo que lee ``invoke``)."""
    return SimpleNamespace(geoblender=SimpleNamespace(kind="DTM", dataset_uid=uid))


def _load_empty(request: Any) -> Any:
    """El cargador de la prueba de las rejillas de diferencias (el real es de la T22): un
    objeto vacío."""
    return _module("bl.scene.views").ViewParts((bpy.data.objects.new(request.name, None),),
                                               None)


class ResBetweenSurfacesTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 activa en la sesión, para toda la
    clase (cada prueba cubica con su propio nombre)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r21-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.ps = _module("bl.scene.project_session")
        cls.res_ops = _module("bl.ops.res")
        cls.panels = _module("bl.ui.res_panels")
        cls.session = _module("bl.ops.core_provenance")
        cls.views = _module("bl.scene.views")
        cls.commands = _module("bl.ui.commands")
        cls.provenance = _module("reserves.provenance")
        (folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=vf.WINDOW,
                                                                  grid_step_m=vf.STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva",
                                                      title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="sur",
                                                      title="Fase sur", reason=REASON)
        cls.project.refresh_header()
        cls.uids = cls.write_grids()
        cls.scope = cls.import_boundary(folder / "fuentes")
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        if cls.views.loader_for("res_dif_x") is None:  # hasta la T22, el de la prueba
            cls.views.register_loader("res_dif_", "DTM", "DTM", _load_empty)
            cls.addClassCleanup(cls.views.unregister_loader, "res_dif_")
        cls.set_active(cls.v01)

    @classmethod
    def write_grids(cls) -> dict[str, str]:
        """Septiembre, octubre (8 × 8 celdas de 1 m) y «otra» (4 × 4 de 2 m, la misma
        ventana), como las deja «Rejilla del proyecto desde un MDT» (``gis.resample``); el uid
        de cada una por su nombre de dato."""
        gis_store = _module("gis.store")
        Grid, Raster = _module("gis.grid").Grid, _module("gis.raster").Raster
        crs, vertical = gis_store.project_references(cls.project)
        grid = Grid(vf.WEST, vf.SOUTH + CELLS, 1.0, 1.0, CELLS, CELLS)
        other = Grid(vf.WEST, vf.SOUTH + CELLS, 2.0, 2.0, OTHER_CELLS, OTHER_CELLS)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Meses"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        coarse = np.full((OTHER_CELLS, OTHER_CELLS), 99.0)
        with gis_store.ResultWriter(cls.project, handle) as out:
            for name, values, where in (("Septiembre", _start_values(), grid),
                                        ("Octubre", _final_values(), grid),
                                        ("Otra", coarse, other)):
                out.raster(name, Raster(where, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return {record.name: record.uid for record in records}

    @classmethod
    def import_boundary(cls, folder: Path) -> str:
        """«Capas vectoriales…» de la 006 sin su trabajo (como ``res_fixtures.import_layer``):
        el contorno :data:`SCOPE_RING` de un GeoPackage fuera del proyecto, importado con el
        papel «contorno»; el nombre de su dato (``gis_bnd_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        folder.mkdir()
        path = folder / "Ambito.gpkg"
        conn = sqlite3.connect(path)
        try:
            _module("core.gpkg.base").create_base(conn, crs)
            conn.execute("CREATE TABLE ambito (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "
                         "geom GEOMETRY)")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES ('ambito', 'features', 'ambito', '', ?)",
                         (crs.epsg,))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES ('ambito', 'geom', 'POLYGON', "
                         "?, 0, 0)", (crs.epsg,))
            conn.execute("INSERT INTO ambito VALUES (1, ?)", (_module("core.gpkg.wkb")
                         .encode_geometry("POLYGON", [SCOPE_RING], crs.epsg, False),))
            conn.commit()
        finally:
            conn.close()
        inputs, gis_store, vector = (_module("core.inputs"), _module("gis.store"),
                                     _module("gis.vector"))
        reader = _module("gis.content").GPKG_LAYER
        settings = {"layer": "ambito", "role": "boundary"}
        anchors = [inputs.locate_source(path, cls.project, cls.ps.userdata(), role="main")]
        prints = [_module("core.inputs.model").SourcePrint(
            _module("core.hashing").sha256_file(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns)]
        request = reader.request(
            reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
            dict(zip(inputs.reader_roles(anchors), [path], strict=True)), settings)
        spec = gis_store.source_input(
            reader.id, "Ámbito", files=anchors, file_prints=prints,
            digest=_module("core.content.readers").read_content(reader, request), crs=crs,
            vertical=vertical, settings=settings)
        copies = folder / "copia"
        copies.mkdir()
        features = vector.read_layer(vector.copy_source(path, copies), "ambito")
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": "Ámbito"},
            executor="blender")
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.declare_input(spec)
            out.boundary("Ámbito", features.geometries)
            (record,) = out.commit(message=REASON)
        return record.name

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
        self.panel = self.enterContext(mock.patch.object(self.res_ops, "_call_panel",
                                                         return_value={"FINISHED"}))

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> type:
        return self.commands.registered_class(BETWEEN)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def figures(self, op_uid: str, name: str) -> dict[str, float]:
        scope = _module("core.provenance.figures").scope_json({"cubication": name})
        return dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ? AND "
                              "scope = ?", op_uid, scope))

    def operations(self, name: str) -> list[tuple[str, str, str | None, str | None]]:
        """Las ``res.volume`` de la cubicación ``name``: uid, estado, lo que sustituye y quien
        la sustituye, por orden."""
        return [(uid, status, supersedes, superseded)
                for uid, status, supersedes, superseded, settings in self.rows(
                    "SELECT uid, status, supersedes_uid, superseded_by, settings FROM "
                    "gb_operation WHERE op_type = 'res.volume' ORDER BY started_at, uid")
                if json.loads(settings)["name"] == name]

    def datasets(self, name: str) -> list[str]:
        slug = _module("gis.provenance").dataset_slug(name)
        return [found for (found,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name IN (?, ?) AND status = 'current'",
            f"res_vol_{slug}", f"res_dif_{slug}")]

    def dialog(self, context: Any = None, **given: Any) -> tuple[Any, Any, Any]:
        """Abre el diálogo a mano (``invoke`` con un ``window_manager`` simulado) y lo dibuja:
        el ``self``, lo dibujado y el diálogo pedido."""
        names = frozenset(given)
        fake = operator_self(self.cls, report=lambda kind, text: None,
                             properties=SimpleNamespace(is_property_set=names.__contains__),
                             **{**DIALOG, **given})
        manager = SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}),
                                  invoke_confirm=mock.Mock(return_value={"RUNNING_MODAL"}))
        if context is None:
            context = SimpleNamespace(window_manager=manager, window=None, selected_objects=[])
        else:
            context.window_manager = manager
        self.assertEqual(self.cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.cls.draw(fake, bpy.context)
        return fake, fake.layout, manager

    def running(self) -> Any:
        """La orden que está en marcha como modal (la que aún tiene pasos)."""
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Entre dos superficies… no está en marcha")
        return found[0]

    def drive(self, operator: Any) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba: su final y lo que duró
        cada llamada (s)."""
        calls: list[float] = []
        for _ in range(MAX_EVENTS):
            started = time.perf_counter()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.perf_counter() - started)
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("Entre dos superficies… no acaba")

    def refused(self, **values: Any) -> str:
        """El error de la orden desde un guion (``RuntimeError``) sin que cambie el proyecto."""
        counter = vf.change_counter(self.project)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.res_compute_volume_between_surfaces(**values)
        self.assertEqual(vf.change_counter(self.project), counter)
        return str(caught.exception)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_command_of_011_with_its_shortcut(self) -> None:
        """D-36, RF-011-06, RF-003-18: «Cubicar entre dos superficies…» es la orden real de la
        entrada «011» (no la provisional de R-38), lanza ``res.volume`` con la puerta de la
        procedencia y los pasos con Esc, y conserva su atajo Mayús+Alt+M en la Vista 3D (que en
        modo Blender queda para Blender, con su motivo)."""
        command = self.commands.catalog().commands[BETWEEN]
        self.assertEqual(command.entry, ENTRY)
        cls = self.cls
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.VOLUME, {"REGISTER"}))
        items = [(keymap.name, item.type, item.shift, item.alt, item.ctrl)
                 for keymap, item in _module("bl.ui.keymap").registered_items()
                 if item.idname == BETWEEN]
        self.assertEqual(items, [("3D View", "M", True, True, False)])
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        self.assertFalse(window.workspace.geoblender_mode)
        with mock.patch.object(cls, "poll_message_set") as message:
            with bpy.context.temp_override(window=window, area=area, region=region):
                self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with("Solo en modo Geoblender (Ctrl+F10) o desde "
                                        "Geoblender ▾")
        self.assertTrue(cls.poll(bpy.context))

    def test_dialog_proposes_the_selected_surfaces(self) -> None:
        """RF-011-06, RF-011-02, RF-011-04 (D-31): con las dos superficies seleccionadas en
        cualquier orden, el diálogo propone de partida la de mayor cota media (septiembre) y de
        final la otra, con el nombre «octubre − septiembre»; ofrece las rejillas del proyecto y
        la cota constante, el ámbito opcional y la rejilla de diferencias (sí), y dice el
        espesor mínimo con su valor y su tipo. «Invertir» las cambia, con su nombre."""
        for order in ((FINAL, START), (START, FINAL)):
            with self.subTest(selección=order):
                context = SimpleNamespace(window=None, selected_objects=[
                    _surface(self.uids[name]) for name in order])
                fake, layout, manager = self.dialog(context)
                self.assertEqual((fake.start, fake.final, fake.name),
                                 (START, FINAL, "octubre − septiembre"))
        self.assertEqual(manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Cubicar entre dos superficies…")
        self.assertEqual([item[0] for item in self.panels.surface_items(None, None)],
                         [FINAL, OTHER, START, ELEVATION])
        self.assertEqual([item[0] for item in self.panels.scope_items(None, None)],
                         ["NONE", self.scope])
        self.assertEqual([item.target for item in layout.of_kind("prop")],
                         ["name", "start", "invert", "final", "scope_layer", "difference_grid"])
        labels = [item.text for item in layout.of_kind("label")]
        self.assertIn("Espesor mínimo: 0 m [ADO] sin confirmar (se cambia en Proyecto ▸ Control "
                      "▸ Parámetros del proyecto…)", labels)

        fake.invert = True
        self.res_ops.invert_surfaces(fake, None)
        self.assertEqual((fake.start, fake.final, fake.name, fake.invert),
                         (FINAL, START, "septiembre − octubre", False))
        fake.final, fake.final_elevation = ELEVATION, "100,5"
        fake.invert = True
        self.res_ops.invert_surfaces(fake, None)
        self.assertEqual((fake.start, fake.start_elevation, fake.final, fake.final_elevation),
                         (ELEVATION, "100,5", FINAL, ""))
        self.cls.draw(fake, bpy.context)
        self.assertIn("start_elevation", [item.target for item in fake.layout.of_kind("prop")])

    def test_cubicate_in_steps_esc_and_finish(self) -> None:
        """RF-011-01, RF-011-04, RF-011-20, RF-011-25 (A10, A11, D-25; RNF-011-04): por pasos,
        un evento cada vez; Esc antes del primer paso o a mitad (leyendo, con su avance en la
        barra de estado) deja la operación cancelada y ni cifra, ni tabla, ni rejilla, ni
        fichero. Otra vez hasta el final, con su avance en la barra de estado y
        ninguna llamada de más de 0,2 s: las seis cifras de los totales (las de la prueba), de
        la revisión abierta de V01, la tabla y la rejilla de diferencias, cargada en la vista, y
        la ventana de la cubicación."""
        name = "Mensual octubre"
        values = {"name": name, "start": START, "final": FINAL, "in_steps": True}
        before = _files(self.project.root)
        shown: list[str] = []
        status_text = self.cls._status_text

        def spy(op: Any, step: Any) -> str:
            shown.append(status_text(op, step))
            return shown[-1]

        self.enterContext(mock.patch.object(self.cls, "_status_text", spy))
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
        self.assertEqual(self.running().modal(bpy.context, ESC), {"CANCELLED"})  # sin empezar
        with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):  # un paso por evento
            self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
                "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
            operator = self.running()
            for _ in range(2):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            self.assertEqual(operator.progress_log[-1][1], "bands")  # a mitad
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], CANCELLED)
        self.assertEqual(shown[-1][:len(f"Cubicando «{name}»: leyendo… ")],
                         f"Cubicando «{name}»: leyendo… ")
        cancelled = self.operations(name)
        self.assertEqual([status for _uid, status, _old, _new in cancelled],
                         ["cancelled", "cancelled"])
        for uid, _status, _old, _new in cancelled:
            self.assertEqual(self.figures(uid, name), {})
        self.assertEqual(self.datasets(name), [])
        self.assertEqual(_files(self.project.root), before)

        shown.clear()
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
        operator = self.running()
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        self.assertTrue(shown)
        for text in shown:
            self.assertTrue(text.startswith((f"Cubicando «{name}»: ", f"Cargando «{name}» "))
                            and text.endswith((" % · Esc: cancelar", " en la vista… 100 %",
                                               " en la vista… 0 %")), text)
        expected = _expected(_start_values(), _final_values())
        (*_cancelled, (uid, status, _old, _new)) = self.operations(name)
        self.assertEqual(status, "done")
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(expected["res.still_area_m2"], 8.0)  # RF-011-04: la columna 3
        ((revision, inputs),) = self.rows(
            "SELECT o.revision_uid, (SELECT group_concat(io.role) FROM gb_operation_io AS io "
            "WHERE io.operation_uid = o.uid AND io.direction = 'in') FROM gb_operation AS o "
            "WHERE o.uid = ?", uid)
        self.assertEqual(self.rows("SELECT version_uid FROM gb_revision WHERE uid = ?",
                                   revision), [(self.v01.uid,)])
        self.assertEqual(sorted(inputs.split(",")), ["final", "start"])
        self.assertEqual(sorted(self.datasets(name)),
                         ["res_dif_mensual_octubre", "res_vol_mensual_octubre"])
        format_number = _module("core.i18n").format_number
        self.assertIn(f"{name} (V01.r1, en curso): desmonte "
                      f"{format_number(expected['res.cut_m3'], 1)} m³, terraplén "
                      f"{format_number(expected['res.fill_m3'], 1)} m³, neto "
                      f"{format_number(expected['res.net_m3'], 1)} m³", operator.report_log)
        (grid_uid,) = [found for (found,) in self.rows(
            "SELECT uid FROM gb_dataset WHERE name = 'res_dif_mensual_octubre'")]
        self.assertEqual(len([obj for obj in bpy.data.objects
                              if obj.geoblender.dataset_uid == grid_uid]), 1)
        self.panel.assert_called_with(PANEL)

    def test_constant_final_and_refusals(self) -> None:
        """RF-011-02, RF-011-03: desde un guion, de una vez, una cota constante como final da
        sus cifras; dos superficies que no casan (otro paso), dos cotas constantes o una cota
        que no es un número se rechazan con las dos superficies, la diferencia y la orden que
        lo resuelve, sin escribir nada (ni la operación)."""
        name = "Contra cota"
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name=name, start=START, final=ELEVATION, final_elevation="100,5",
            difference_grid=False), {"FINISHED"})
        ((uid, status, _old, _new),) = self.operations(name)
        self.assertEqual(status, "done")
        expected = _expected(_start_values(), 100.5)
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(self.datasets(name), ["res_vol_contra_cota"])

        text = self.refused(name="Otra rejilla", start=START, final=OTHER)
        self.assertIn(f"No se pueden cubicar «{START}» y «{OTHER}»: ", text)
        self.assertIn("Topografía ▸ Rejilla de proyecto desde un MDT…", text)
        text = self.refused(name="Dos cotas", start=ELEVATION, start_elevation="101",
                            final=ELEVATION, final_elevation="100,5")
        self.assertIn("son las dos cotas constantes", text)
        text = self.refused(name="Sin cota", start=START, final=ELEVATION, final_elevation="x")
        self.assertIn("Cota final: «x» no es un número de metros", text)
        for refused in ("Otra rejilla", "Dos cotas", "Sin cota"):
            self.assertEqual(self.operations(refused), [])

    def test_needs_an_editable_version_and_writing(self) -> None:
        """RF-011-20, RF-011-26 (RF-009-05, RF-009-21): sin versión activa, lanzada desde la
        interfaz abre la ventana de elegir o crear una y no hace nada más; con la activa
        SUPERADO o el proyecto en solo lectura, no está disponible y dice por qué."""
        cls = self.cls
        self.set_active(None)
        self.addCleanup(self.set_active, self.v01)
        fake = operator_self(cls, report=lambda kind, text: None, **DIALOG)
        with mock.patch.object(self.session, "open_version_dialog") as opened:
            self.assertEqual(cls.invoke(fake, SimpleNamespace(window=None), None),
                             {"CANCELLED"})
        opened.assert_called_once_with()

        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        with mock.patch.object(cls, "poll_message_set") as message:
            self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with("V02 está en estado SUPERADO: cree una versión nueva a "
                                        "partir de ella")
        self.set_active(self.v01)
        self.assertTrue(cls.poll(bpy.context))

        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            with mock.patch.object(cls, "poll_message_set") as message:
                self.assertFalse(cls.poll(bpy.context))
            message.assert_called_once_with(reason)
        self.assertTrue(cls.poll(bpy.context))

    def test_scope_layer_limits_the_cubication(self) -> None:
        """RF-011-01, RF-011-20 (D-32): con un ámbito (una capa de contornos importada), solo
        cuenta lo que queda dentro, con la fracción exacta de cada celda (media columna en su
        borde); la operación consume la capa con el papel «scope» y la nombra en sus
        ajustes."""
        name = "Con ámbito"
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name=name, start=START, final=FINAL, scope_layer=self.scope,
            difference_grid=False), {"FINISHED"})
        ((uid, status, _old, _new),) = self.operations(name)
        self.assertEqual(status, "done")
        expected = _expected(_start_values(), _final_values(), SCOPE_WEIGHTS)
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(expected["res.area_m2"], 36.0)
        (settings,) = [json.loads(found) for (found,) in self.rows(
            "SELECT settings FROM gb_operation WHERE uid = ?", uid)]
        self.assertEqual(settings["scope"], self.scope)
        self.assertIn(("scope",), self.rows("SELECT role FROM gb_operation_io WHERE "
                                            "operation_uid = ? AND direction = 'in'", uid))

    def test_repeated_name_asks_before_replacing(self) -> None:
        """D-30 (RF-011-20): repetir el nombre de una cubicación de la versión activa, desde un
        guion, se rechaza sin escribir nada; desde la interfaz, pregunta si se sustituye
        («Ya hay una cubicación «Repetida» en V01: ¿sustituirla?») y, aceptado, la nueva
        sustituye a la anterior."""
        name = "Repetida"
        values = {"name": name, "start": START, "final": FINAL, "difference_grid": False}
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(**values),
                         {"FINISHED"})
        ((first, _status, _old, _new),) = self.operations(name)
        text = self.refused(**values)
        self.assertIn("Ya hay una cubicación «Repetida» en V01", text)

        fake = operator_self(self.cls, report=lambda kind, text: None, provenance_dialog=True,
                             **{**DIALOG, **values})
        with mock.patch.object(self.res_ops, "_confirm_later") as later:
            self.assertEqual(self.cls.execute(fake, bpy.context), {"CANCELLED"})
        (asked,), _kw = later.call_args
        self.assertEqual({key: asked[key] for key in values}, values)
        self.assertEqual(len(self.operations(name)), 1)
        _fake, _layout, manager = self.dialog(confirm=True, **values)
        self.assertEqual(manager.invoke_confirm.call_args.kwargs["message"],
                         "Ya hay una cubicación «Repetida» en V01: ¿sustituirla?")
        self.assertTrue(_fake.replace)

        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            replace=True, **values), {"FINISHED"})
        ((old, _s1, _o1, replaced), (new, status, supersedes, _n2)) = self.operations(name)
        self.assertEqual((old, replaced, status, supersedes), (first, new, "done", first))


if __name__ == "__main__":
    unittest.main()
