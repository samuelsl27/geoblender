# SPDX-License-Identifier: GPL-3.0-or-later
"""Restricciones…, crear, completar, compilar y exportar las máscaras (spec 012, T23; HU-012-2,
HU-012-4; RF-012-01, RF-012-02, RF-012-03, RF-012-04, RF-012-06, RF-012-11, RF-012-19, RF-012-20,
RF-012-28; plan 012 §5.3.4, §5.5, D-31, D-38).

- RF-012-01, RF-012-02 (``geoblender.core_create_constraints``): crear restricciones desde una
  capa del proyecto con un tipo para todas (líneas y puntos, con su resguardo) o con el campo que
  lo da (polígonos), y los campos del nombre, el motivo, el decisor y la fecha: la geometría bit a
  bit, el origen (la entrada y la entidad), los parámetros del proyecto (resguardo, «activa») y el
  informe de las creadas y de las rechazadas con su entidad y su motivo, sin tocar la capa de
  origen; lo que no vale se rechaza sin escribir nada.
- RF-012-19, RF-012-02 (``geoblender.core_edit_constraints``): la lista de la versión activa con
  la insignia del tipo, el estado (incompleta, no válida, activa, inactiva) y los parámetros con
  su valor en la versión y en el proyecto («V01: 8 m [ADO] · proyecto: —»).
- RF-012-03, RF-012-04 (``geoblender.core_complete_constraint``): completar la dibujada en QGIS
  (código, tipo, motivo, decisor, resguardo); cambiar un resguardo solo en V01 con el diálogo de
  la 008 y el ámbito de la 009 (``geoblender.core_set_parameter``).
- RF-012-04, RF-012-06, RF-012-11, RF-012-15, RF-012-28 (``geoblender.gis_compile_constraints``):
  compilar por pasos (ninguna llamada de más de 0,2 s) con el avance, el informe de ganado y
  perdido de lo que cambió y la marca de búsqueda pendiente; Esc a mitad no deja nada en el
  proyecto; una incompleta o sin límite legal no se compila.
- RF-012-20 (``geoblender.gis_export_constraint_masks``): la rejilla de clases a GeoTIFF con su
  leyenda; no con las máscaras obsoletas ni sobre un fichero que ya existe.
- RF-012-28, D-38: sin proyecto, en solo lectura o con la versión activa SUPERADO las órdenes que
  escriben están desactivadas con su motivo; las cinco pasan a la entrada «012».

Un proyecto por clase (rejilla de 48 × 40 celdas de 5 m) y la extensión sin importar otra vez
(RNF-001-01). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw
from tests.support.trees import remove_tree

ENTRY = "012"
EDIT = "geoblender.core_edit_constraints"
CREATE = "geoblender.core_create_constraints"
COMPLETE = "geoblender.core_complete_constraint"
COMPILE = "geoblender.gis_compile_constraints"
EXPORT = "geoblender.gis_export_constraint_masks"
SET_PARAMETER = "geoblender.core_set_parameter"
REAL = (EDIT, CREATE, COMPLETE, COMPILE, EXPORT)
STILL_PROVISIONAL = ("geoblender.res_verify_constraints",)
PANEL = "GEOBLENDER_PT_core_constraints"
LIST = "GEOBLENDER_UL_core_constraints"
WM_PROPERTY = "geoblender_constraints"
EDIT_TYPE = "core.edit_constraints"
COMPILE_TYPE = "gis.compile_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M = 240.0
HEIGHT_M = 200.0
STEP_M = 5.0
REASON = "Prueba de las restricciones de la 012"
PERSON = "Samuel (IMGA)"
OWNER = "Propiedad"
DATE_TEXT = "31/10/2026"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 600
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal (RNF-012-06)."""
SHOWN_FLAG = 1 << 30
"""``UIList.bitflag_filter_item``: lo que marca una fila que se enseña."""
LEGAL_BOX = (0.0, 0.0, 200.0, 200.0)
# Las zonas: (fid, nombre, tipo escrito, caja local). La tercera tiene un tipo que no existe y la
# cuarta no tiene nombre: las dos se rechazan.
ZONES = (
    (1, "Torre 132 kV", "Intocable", (60.0, 60.0, 70.0, 70.0)),
    (2, "Balsa", "Sin corte", (140.0, 100.0, 170.0, 130.0)),
    (3, "Zona rara", "Inventado", (20.0, 20.0, 30.0, 30.0)),
    (4, "", "Exclusión", (180.0, 20.0, 190.0, 30.0)),
)
DITCH_LOCAL = ((20.0, 150.0), (100.0, 150.0))
POST_LOCAL = (150.0, 40.0)
TOWER_BOX = ZONES[0][3]
TOWER_BUFFER_M = 8.0
POST_BUFFER_M = 12.0
TOWER_BUFFER_V01_M = 12.0
DRAWN_BOX = (120.0, 20.0, 140.0, 40.0)
CELL_M2 = STEP_M * STEP_M
COLUMNS = int(WIDTH_M / STEP_M)
ROWS = int(HEIGHT_M / STEP_M)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def rectangle(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local dado."""
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def number(value: float, decimals: int) -> str:
    """Un número como lo escribe la interfaz en español (espacio fino de miles, coma)."""
    return _module("core.i18n").format_number(value, decimals)


def cells_within(box: tuple[float, float, float, float], radius: float) -> set[tuple[int, int]]:
    """Las celdas (columna, fila desde el sur) de la rejilla cuya distancia al rectángulo local
    ``box`` es menor que ``radius`` (una caja nula es un punto): la zona de una restricción por
    fuerza bruta, con la regla de la spec (D-1: la celda entera del lado seguro)."""
    found: set[tuple[int, int]] = set()
    for column in range(COLUMNS):
        for row in range(ROWS):
            left, bottom = column * STEP_M, row * STEP_M
            dx = max(box[0] - (left + STEP_M), left - box[2], 0.0)
            dy = max(box[1] - (bottom + STEP_M), bottom - box[3], 0.0)
            if (dx * dx + dy * dy) ** 0.5 < radius - 1e-9:
                found.add((column, row))
    return found


def legal_cells() -> set[tuple[int, int]]:
    """Las celdas enteras dentro del límite legal (LEGAL_BOX)."""
    return {(column, row) for column in range(int(LEGAL_BOX[2] / STEP_M))
            for row in range(int(LEGAL_BOX[3] / STEP_M))}


class ConstraintsOpsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 y las capas de la prueba
    importadas como entidades, para toda la clase (las pruebas, en el orden de sus letras: cada
    una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r23-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.folder = folder
        cls.ps = _module("bl.scene.project_session")
        cls.core_ops = _module("bl.ops.core_constraints")
        cls.gis_ops = _module("bl.ops.gis")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.cstore = _module("core.constraints.store")
        cls.cmodel = _module("core.constraints.model")
        cls.cparams = _module("core.constraints.params")
        cls.access = _module("gis.masks.access")
        cls.mask_store = _module("gis.masks.store")
        cls.params = _module("core.params")
        (folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + WIDTH_M, SOUTH + HEIGHT_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="mascaras",
                                                      title="Máscaras", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        sources = folder / "fuentes"
        sources.mkdir()
        fields = ("nombre", "tipo", "motivo", "decisor", "fecha")
        cls.names = {
            "Concesion": cls.import_layer(sources, "Concesion", "POLYGON", ("nombre",),
                                          [(1, rectangle(*LEGAL_BOX), {"nombre": "Concesión"})]),
            "Zonas": cls.import_layer(
                sources, "Zonas", "POLYGON", fields,
                [(fid, rectangle(*box), {"nombre": name, "tipo": kind, "motivo": "Plan de la "
                                         "propiedad", "decisor": OWNER, "fecha": "2026-10-01"})
                 for fid, name, kind, box in ZONES]),
            "Lineas": cls.import_layer(
                sources, "Lineas", "LINESTRING", ("nombre",),
                [(1, np.array([(WEST + x, SOUTH + y) for x, y in DITCH_LOCAL]),
                  {"nombre": "Cuneta"})]),
            "Torres": cls.import_layer(
                sources, "Torres", "POINT", ("nombre",),
                [(1, np.array([WEST + POST_LOCAL[0], SOUTH + POST_LOCAL[1]]),
                  {"nombre": "Poste 14"})]),
        }
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {
            "FINISHED"}

    @classmethod
    def import_layer(cls, folder: Path, name: str, geometry: str, columns: tuple[str, ...],
                     features: list[tuple[int, np.ndarray, dict[str, str]]]) -> str:
        """«Capas vectoriales…» de la 006 con el papel «Entidades», sin su trabajo: la capa
        ``name`` de un GeoPackage fuera del proyecto con una entidad de ``geometry`` por cada
        ``(fid, coordenadas absolutas, atributos)``; el nombre de su dato (``gis_fea_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        path = folder / f"{name}.gpkg"
        conn = sqlite3.connect(path)
        try:
            _module("core.gpkg.base").create_base(conn, crs)
            marks = ", ".join(f'"{column}" TEXT' for column in columns)
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                         f'NULL, geom GEOMETRY, {marks})')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (name, name, crs.epsg))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, geometry, crs.epsg))
            encode = _module("core.gpkg.wkb").encode_geometry
            for fid, coords, attributes in features:
                shape = [coords] if geometry == "POLYGON" else coords
                values = [attributes.get(column) for column in columns]
                conn.execute(f'INSERT INTO "{name}" VALUES (?, ?, {", ".join("?" for _ in columns)})',
                             (fid, encode(geometry, shape, crs.epsg, False), *values))
            conn.commit()
        finally:
            conn.close()
        inputs, gis_store, vector = (_module("core.inputs"), _module("gis.store"),
                                     _module("gis.vector"))
        reader = _module("gis.content").GPKG_LAYER
        settings = {"layer": name, "role": "features"}
        anchors = [inputs.locate_source(path, cls.project, cls.ps.userdata(), role="main")]
        prints = [_module("core.inputs.model").SourcePrint(
            _module("core.hashing").sha256_file(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns)]
        request = reader.request(
            reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
            dict(zip(inputs.reader_roles(anchors), [path], strict=True)), settings)
        spec = gis_store.source_input(
            reader.id, name, files=anchors, file_prints=prints,
            digest=_module("core.content.readers").read_content(reader, request), crs=crs,
            vertical=vertical, settings=settings)
        copies = folder / f"copia_{name}"
        copies.mkdir()
        read = vector.read_layer(vector.copy_source(path, copies), name)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": name},
            executor="blender")
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.declare_input(spec)
            out.features(name, vector.features_from_layer(read)[0])
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

    # --- Ayudas -------------------------------------------------------------------------------

    @staticmethod
    def view() -> Any:
        return getattr(bpy.context.window_manager, WM_PROPERTY)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def stored(self) -> dict[str, Any]:
        """Las restricciones guardadas, por código (las sin código, por nombre)."""
        with self.project.read() as conn:
            return {item.code or item.name: item for item in self.cstore.read_constraints(conn)}

    def count(self) -> tuple[int, int]:
        """(operaciones, restricciones) del proyecto: lo que un rechazo no cambia."""
        return (self.rows("SELECT count(*) FROM gb_operation")[0][0], len(self.stored()))

    def param(self, key: str, version: Any = None) -> Any:
        store = self.params.ParameterStore(self.project)
        return store.get(key, version=None if version is None else version.uid)

    def open_window(self) -> Any:
        """«Restricciones…» con su ventana sustituida (en ``blender -b``, ``wm.call_panel``
        cierra Blender): la vista, leída del proyecto."""
        with mock.patch.object(self.core_ops, "_call_panel",
                               return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.core_edit_constraints(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view()

    def listed(self) -> dict[str, Any]:
        """Las filas de la lista de la ventana, por código (las sin código, por nombre)."""
        return {item.code or item.name: item for item in self.view().constraints}

    def create(self, layer: str, **form: Any) -> None:
        """«Desde una capa…» con ``form``; el resto, vacío."""
        base = {"reason": REASON, "decided_by": PERSON, "decided_on": DATE_TEXT,
                "name_field": "nombre"}
        base.update(form)
        self.assertEqual(bpy.ops.geoblender.core_create_constraints(layer=layer, **base),
                         {"FINISHED"})

    def refused(self, command: Any, **values: Any) -> str:
        """El error de ``command`` desde un guion (``RuntimeError``) sin que cambie el
        proyecto."""
        before = self.count()
        with self.assertRaises(RuntimeError) as caught:
            command(**values)
        self.assertEqual(self.count(), before)
        return str(caught.exception)

    def texts(self) -> list[str]:
        return [line.text for line in self.view().report_lines]

    def running(self) -> Any:
        """El modal de «Compilar las máscaras» en marcha (el único con pasos)."""
        cls = self.commands.registered_class(COMPILE)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Compilar las máscaras no está en marcha")
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
        self.fail("Compilar las máscaras no acaba")

    def mask_files(self) -> list[str]:
        """Los ficheros del proyecto (lo que un Esc no cambia)."""
        root = Path(self.project.root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def masks(self, version: Any = None) -> Any:
        return self.access.load_masks(self.project, (version or self.v01).uid)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_are_real_and_in_the_012_entry(self) -> None:
        """RF-012-28, D-31, D-38: «Restricciones…», «Compilar las máscaras» y las tres internas
        (crear, completar, exportar) tienen su clase real y están en la entrada «012»; las dos
        de lanzar una operación lo hacen con su tipo; las demás de R-32 siguen provisionales."""
        cat = self.commands.catalog()
        aware = self.session.ProvenanceAwareOperator
        for idname in REAL:
            with self.subTest(orden=idname):
                self.assertEqual(cat.commands[idname].entry, ENTRY)
                cls = self.commands.registered_class(idname)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls.bl_label, (cat.commands[idname].label,
                                             cat.commands[idname].label_es))
        self.assertEqual((cat.commands[EDIT].kind, cat.commands[EDIT].action), ("operator", "P"))
        self.assertEqual((cat.commands[COMPILE].kind, cat.commands[COMPILE].action),
                         ("operator", "A"))
        for idname in (CREATE, COMPLETE, EXPORT):
            self.assertEqual(cat.commands[idname].kind, "internal")
        for idname, op_type in ((EDIT, EDIT_TYPE), (CREATE, EDIT_TYPE), (COMPLETE, EDIT_TYPE),
                                (COMPILE, COMPILE_TYPE)):
            cls = self.commands.registered_class(idname)
            self.assertTrue(issubclass(cls, aware), idname)
            self.assertEqual(cls.provenance_op_type, op_type)
        design = cat.menus["GEOBLENDER_MT_ui_design"]
        keys = [item.key for item in design.groups[0].items]
        self.assertEqual(keys[:2], ["geoblender.core_edit_limits", EDIT])
        self.assertIn(COMPILE, keys)
        for idname in STILL_PROVISIONAL:
            with self.subTest(sigue_provisional=idname):
                self.assertEqual(cat.commands[idname].entry, "R-32")
                self.assertTrue(self.commands.is_provisional(
                    self.commands.registered_class(idname)))

    def test_b_nothing_to_compile_without_a_legal_limit(self) -> None:
        """RF-012-15: sin ningún límite legal, compilar se rechaza diciendo qué falta y la orden
        que lo resuelve, y no registra nada; la ventana, sin restricciones, lo dice."""
        view = self.open_window()
        self.assertEqual(len(view.constraints), 0)
        text = self.refused(bpy.ops.geoblender.gis_compile_constraints)
        self.assertIn("no hay ningún límite legal activo", text)
        self.assertIn("Límites…", text)
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        self.assertIn("Todavía no hay ninguna restricción", " ".join(layout.texts()))

    def test_c_the_legal_limit_comes_from_the_limits_window(self) -> None:
        """RF-012-01: el límite legal se declara con la ventana de la T22 (la concesión, 10 m
        hacia dentro) y entra en la lista como una restricción más, activa."""
        with mock.patch.object(self.core_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.core_edit_limits(), {"FINISHED"})
        limits = self.view()
        for item in limits.limit_layers:
            item.legal = item.name == self.names["Concesion"]
        limits.limit_name_field = "nombre"
        limits.limit_reason = REASON
        limits.limit_decided_by = PERSON
        limits.limit_decided_on = DATE_TEXT
        limits.limit_inward = "10"
        self.assertEqual(bpy.ops.geoblender.core_declare_limits(), {"FINISHED"})
        view = self.open_window()
        self.assertEqual([(item.code, item.state) for item in view.constraints],
                         [("concesion", "active")])

    def test_d_create_from_a_layer_with_the_type_in_a_field(self) -> None:
        """RF-012-01, RF-012-02, HU-012-2: de la capa de zonas con el tipo en el campo «tipo», el
        nombre, el motivo, el decisor y la fecha de sus campos y 8 m de resguardo, se crean la
        torre (Intocable) y la balsa (Sin corte) con su geometría bit a bit, su origen (la
        entrada y la entidad) y sus parámetros del proyecto, y se informa de las dos rechazadas
        (un tipo que no existe y un nombre vacío) con su entidad y su motivo; la capa de origen no
        cambia y todo es una ``core.edit_constraints``."""
        layer = self.names["Zonas"]
        origin = self.rows("SELECT uid, input_uid, content_sha256 FROM gb_dataset WHERE name = ?",
                           layer)[0]
        before = self.count()
        self.create(layer, ctype="FIELD", type_field="tipo", reason_field="motivo",
                    decider_field="decisor", date_field="fecha", reason="", decided_by="",
                    decided_on="", buffer_out="8")
        self.assertEqual(self.count(), (before[0] + 1, before[1] + 2))
        found = self.stored()
        types = self.cmodel.ConstraintType
        for code, (name, ctype, box, fid) in {
                "torre_132_kv": ("Torre 132 kV", types.UNTOUCHABLE, ZONES[0][3], 1),
                "balsa": ("Balsa", types.NO_CUT, ZONES[1][3], 2)}.items():
            with self.subTest(restriccion=code):
                row = found[code]
                self.assertEqual((row.name, row.ctype, row.kind.value, row.reason, row.decided_by,
                                  row.decided_on.isoformat(), row.source_fid, row.source_input,
                                  row.priority),
                                 (name, ctype, "polygon", "Plan de la propiedad", OWNER,
                                  "2026-10-01", fid, origin[1], 0))
                self.assertTrue(np.array_equal(row.parts[0][0], rectangle(*box)))
                buffer_out = self.param(self.cparams.buffer_out_key(code))
                self.assertEqual(buffer_out.value, 8.0)
                self.assertEqual(self.param(self.cparams.active_key(code)).value, True)
                self.assertIsNone(self.param(self.cparams.buffer_in_key(code)))
        ((_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ? ORDER BY "
            "started_at DESC, uid LIMIT 1", EDIT_TYPE)
        self.assertEqual(status, "done")
        self.assertEqual(json.loads(settings)["created"], 2)
        self.assertEqual(json.loads(settings)["mapping"]["type_field"], "tipo")
        texts = self.texts()
        self.assertEqual(texts[0], f"Restricciones creadas desde «{layer}»: 2; entidades "
                                   "rechazadas: 2")
        self.assertTrue(any("entidad 3" in text and "«Inventado»" in text for text in texts))
        self.assertTrue(any("entidad 4" in text and "«nombre» está vacío" in text
                            for text in texts))
        self.assertTrue(all(line.alert for line in list(self.view().report_lines)[1:]))
        self.assertEqual(self.rows("SELECT uid, content_sha256 FROM gb_dataset WHERE name = ?",
                                   layer), [(origin[0], origin[2])])

    def test_e_create_with_one_type_for_lines_and_points(self) -> None:
        """RF-012-01, RF-012-02: de una capa de líneas y de otra de puntos con un tipo para todas
        (Sin corte, Intocable), el motivo, el decisor y la fecha fijos y su resguardo: las dos
        restricciones con su geometría tal cual y los parámetros que pide su tipo; un resguardo
        de 0 m en una línea o un punto no ocupa nada (sale como incompleta, RF-012-04)."""
        self.create(self.names["Lineas"], ctype="NO_CUT", buffer_out="4")
        self.create(self.names["Torres"], ctype="UNTOUCHABLE", buffer_out="12")
        found = self.stored()
        ditch, post = found["cuneta"], found["poste_14"]
        self.assertEqual((ditch.kind.value, post.kind.value), ("line", "point"))
        self.assertTrue(np.array_equal(
            ditch.parts[0][0], np.array([(WEST + x, SOUTH + y) for x, y in DITCH_LOCAL])))
        self.assertTrue(np.array_equal(post.parts[0][0].reshape(-1),
                                       [WEST + POST_LOCAL[0], SOUTH + POST_LOCAL[1]]))
        for code, buffer in (("cuneta", 4.0), ("poste_14", 12.0)):
            record = self.param(self.cparams.buffer_out_key(code))
            self.assertEqual((record.value, record.decided_by), (buffer, found[code].decided_by))
            self.assertEqual((found[code].reason, found[code].decided_on.isoformat()),
                             (REASON, "2026-10-31"))
        # Sin resguardo: se crea y queda incompleta (el resguardo no tiene valor por defecto).
        self.create(self.names["Torres"], ctype="EXCLUSION", name_field="nombre", buffer_out="")
        self.assertEqual(self.count()[1], 6)
        view = self.open_window()
        incomplete = [item for item in view.constraints if item.state == "incomplete"]
        self.assertEqual([item.code for item in incomplete], ["poste_14_2"])
        self.assertIn("«Resguardo hacia fuera»", incomplete[0].problems)

    def test_f_a_form_that_does_not_fit_is_refused_and_writes_nothing(self) -> None:
        """RF-012-01, RF-012-02: sin capa, con una que no es del proyecto, con un tipo por
        campo sin campo, con un campo que la capa no tiene, con un resguardo que no es un
        número o con una fecha que no lo es, se rechaza con su motivo, antes de crear nada."""
        layer = self.names["Zonas"]
        create = bpy.ops.geoblender.core_create_constraints
        good = {"layer": layer, "ctype": "FIELD", "type_field": "tipo", "name_field": "nombre",
                "reason": REASON, "decided_by": PERSON, "decided_on": DATE_TEXT,
                "buffer_out": "8"}
        self.assertIn("capa", self.refused(create, **{**good, "layer": ""}))
        self.assertIn("«no_existe»", self.refused(create, **{**good, "layer": "no_existe"}))
        self.assertIn("campo del tipo", self.refused(create, **{**good, "type_field": ""}))
        text = self.refused(create, **{**good, "type_field": "no_hay"})
        self.assertIn("«no_hay»", text)
        self.assertIn("«tipo»", text)  # los campos que sí tiene la capa
        self.assertIn("«mucho»", self.refused(create, **{**good, "buffer_out": "mucho"}))
        self.assertIn("«31-10»", self.refused(create, **{**good, "decided_on": "31-10"}))
        self.assertIn("motivo", self.refused(create, **{**good, "reason": " "}))
        self.assertIn("quién decide", self.refused(create, **{**good, "decided_by": ""}))
        # Un tipo que no cabe en la geometría (un límite en una línea): todas rechazadas.
        text = self.refused(create, **{**good, "layer": self.names["Lineas"],
                                       "ctype": "LEGAL_LIMIT", "type_field": ""})
        self.assertIn("no puede ser", text)
        # La correspondencia de los valores del campo del tipo: «valor = tipo; valor = tipo».
        types = self.cmodel.ConstraintType
        self.assertEqual(self.core_ops._typed_values("Inventado = Exclusión; Otro = no_fill"),
                         {"Inventado": types.EXCLUSION, "Otro": types.NO_FILL})
        self.assertIsNone(self.core_ops._typed_values("  "))
        self.assertIn("«mala»", self.refused(create, **{**good, "type_values": "mala"}))

    def test_g_the_list_shows_badge_state_and_parameters_in_the_version(self) -> None:
        """RF-012-19, RF-012-02: la lista de V01, con sus seis restricciones, el estado de cada
        una y, de cada parámetro que pide su tipo, su valor en V01 y en el proyecto («V01: —
        · proyecto: 8 m [HIP]»), y se dibuja con la insignia del tipo, el estado y, de la
        elegida, sus parámetros con «Cambiar…» y su motivo, decisor y fecha."""
        view = self.open_window()
        listed = self.listed()
        self.assertEqual(sorted(listed), ["balsa", "concesion", "cuneta", "poste_14",
                                          "poste_14_2", "torre_132_kv"])
        self.assertEqual({code: item.state for code, item in listed.items()},
                         {"balsa": "active", "concesion": "active", "cuneta": "active",
                          "poste_14": "active", "poste_14_2": "incomplete",
                          "torre_132_kv": "active"})
        tower = listed["torre_132_kv"]
        self.assertEqual((tower.ctype, tower.kind, tower.priority, tower.reason,
                          tower.decided_by, tower.decided_on),
                         ("untouchable", "polygon", 0, "Plan de la propiedad", OWNER,
                          "01/10/2026"))
        shown = {line.key: line.text for line in tower.parameters}
        out = self.cparams.buffer_out_key("torre_132_kv")
        self.assertEqual(list(shown), [out, self.cparams.active_key("torre_132_kv")])
        self.assertEqual(shown[out], "V01: — · proyecto: 8 m [HIP]")
        legal = listed["concesion"]
        self.assertEqual({line.key: line.text for line in legal.parameters}[
            self.cparams.buffer_in_key("concesion")], "V01: — · proyecto: 10 m [HIP]")
        view.item_index = [item.code for item in view.constraints].index("torre_132_kv")
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        shown_texts = layout.texts()
        for text in ("Plan de la propiedad", OWNER, "01/10/2026", "V01: — · proyecto: 8 m [HIP]"):
            self.assertTrue(any(text in each for each in shown_texts), text)
        (listing,) = [item for item in layout.items if item.kind == "template_list"]
        self.assertEqual(listing.target, LIST)
        keys = [item.properties.key for item in layout.of_kind("operator")
                if item.target == SET_PARAMETER]
        self.assertEqual(keys, [out, self.cparams.active_key("torre_132_kv")])
        targets = {item.target for item in layout.of_kind("operator")}
        self.assertTrue({CREATE, COMPLETE, COMPILE, EXPORT} <= targets, targets)
        # La fila de la lista: insignia del tipo, nombre y estado; la incompleta, en alerta.
        ul = getattr(bpy.types, LIST)
        for code, state, alert in (("torre_132_kv", "Activa", False),
                                   ("poste_14_2", "Incompleta", True)):
            row = FakeLayout()
            ul.draw_item(None, bpy.context, row, view, listed[code], 0, view, "item_index")
            text = " ".join(row.texts())
            self.assertIn(state, text)
            self.assertIn(listed[code].name, text)
            self.assertEqual(any(item.alert for item in row.items), alert, code)
        row = FakeLayout()
        ul.draw_item(None, bpy.context, row, view, listed["torre_132_kv"], 0, view, "item_index")
        self.assertIn("Intocable", " ".join(row.texts()))

    def test_h_compile_is_refused_while_a_constraint_is_incomplete(self) -> None:
        """RF-012-04: con una restricción incompleta («poste_14_2» sin resguardo), compilar se
        rechaza listando su nombre, su tipo y qué le falta, y no registra nada; el filtro de la
        ventana deja solo las que tienen problemas."""
        before = self.count()
        text = self.refused(bpy.ops.geoblender.gis_compile_constraints)
        self.assertIn("poste_14_2", text)
        self.assertIn("Exclusión", text)
        self.assertIn("«Resguardo hacia fuera»", text)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   COMPILE_TYPE)[0][0], 0)
        self.assertEqual(self.count(), before)
        view = self.open_window()
        ul = getattr(bpy.types, LIST)
        view.only_problems = True
        owner = SimpleNamespace(bitflag_filter_item=SHOWN_FLAG)
        flags, order = ul.filter_items(owner, bpy.context, view, "constraints")
        shown = [item.code for item, flag in zip(view.constraints, flags, strict=True)
                 if flag & SHOWN_FLAG]
        self.assertEqual(shown, ["poste_14_2"])
        self.assertFalse(order)
        view.only_problems = False
        # La elegida con problemas se dibuja con cada uno de ellos en alerta (T24: la línea de
        # un problema no tenía el atributo «x» de las filas de la vista y fallaba al dibujar).
        view.item_index = [item.code for item in view.constraints].index("poste_14_2")
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        self.assertTrue(any("«Resguardo hacia fuera»" in item.text and item.alert
                            for item in layout.of_kind("label")), layout.texts())

    def test_i_complete_the_one_drawn_in_qgis(self) -> None:
        """RF-012-03, RF-012-04: la restricción dibujada en QGIS (la geometría y nada más) sale
        incompleta y sin código; completarla (tipo, nombre, motivo, decisor, resguardo) le da su
        código y sus parámetros con una ``core.edit_constraints`` y, con la que no tenía
        resguardo, ya se puede compilar; el resguardo que faltaba a una con código se da de alta
        con «Completar…» sin cambiar el resto."""
        drawn = self.cmodel.Constraint(
            uid=uuid.uuid4().hex, code="", name="", ctype=None,
            kind=self.cmodel.GeometryKind.POLYGON, parts=((rectangle(*DRAWN_BOX),),), priority=0,
            reason=None, decided_by=None, decided_on=None, decision_uid=None, intention_uid=None,
            source_input=None, source_fid=None, layer=self.cstore.layer_of("polygon"), fid=0)
        with self.project.write_transaction() as conn:  # lo que haría QGIS
            self.cstore.write_constraints(conn, [drawn], srs_id=self.project.record.crs_epsg)
        view = self.open_window()
        (row,) = [item for item in view.constraints if not item.code]
        self.assertEqual(row.state, "incomplete")
        self.assertIn("Sin nombre", row.name)
        self.assertIn("código", row.problems)
        uid = row.uid
        before = self.count()
        # Sin lo que falta: se rechaza sin escribir nada.
        self.assertIn("tipo", self.refused(bpy.ops.geoblender.core_complete_constraint, uid=uid,
                                           ctype="NONE", name="Ensanche"))
        self.assertEqual(self.count(), before)
        self.assertEqual(bpy.ops.geoblender.core_complete_constraint(
            uid=uid, ctype="NO_FILL", name="Ensanche", reason="Terreno del vecino",
            decided_by=PERSON, decided_on=DATE_TEXT, buffer_out="3"), {"FINISHED"})
        found = self.stored()
        self.assertNotIn("Sin nombre", " ".join(found))
        done = found["ensanche"]
        self.assertEqual((done.uid, done.ctype.value, done.name, done.reason, done.decided_by,
                          done.fid), (uid, "no_fill", "Ensanche", "Terreno del vecino", PERSON,
                                      done.fid))
        self.assertTrue(np.array_equal(done.parts[0][0], rectangle(*DRAWN_BOX)))
        self.assertEqual(self.param(self.cparams.buffer_out_key("ensanche")).value, 3.0)
        self.assertEqual(self.param(self.cparams.active_key("ensanche")).value, True)
        ((_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ? ORDER BY "
            "started_at DESC, uid LIMIT 1", EDIT_TYPE)
        self.assertEqual((status, json.loads(settings)["completed"]), ("done", 1))
        # La que tenía código y le faltaba el resguardo: se da de alta, sin tocar lo demás.
        self.assertIsNone(self.param(self.cparams.buffer_out_key("poste_14_2")))
        self.assertEqual(bpy.ops.geoblender.core_complete_constraint(
            uid=found["poste_14_2"].uid, ctype="EXCLUSION", name="Poste 14", buffer_out="6"),
            {"FINISHED"})
        self.assertEqual(self.param(self.cparams.buffer_out_key("poste_14_2")).value, 6.0)
        self.assertEqual(self.stored()["poste_14_2"].uid, found["poste_14_2"].uid)
        view = self.open_window()
        self.assertEqual({item.state for item in view.constraints}, {"active"})

    def test_j_compile_reports_the_domain_and_the_pending_search(self) -> None:
        """RF-012-11, RF-012-13, RF-012-10, RF-012-15: compilar V01 deja la operación hecha con
        sus datos y dice, con el avance, el dominio (la concesión de 4 ha sin las zonas de las
        dos torres, con la celda entera del lado seguro), el corte, el relleno y la franja (el
        perímetro no está declarado: el límite legal hace de perímetro y se avisa) y la marca de
        la búsqueda pendiente en el perímetro. Sin lo anterior, nada de ganado ni perdido."""
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        ((_uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                      COMPILE_TYPE)
        self.assertEqual(status, "done")
        state, pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual((state, pending), (self.access.MaskState.CURRENT, ("",)))
        # Lo que quita del dominio: las dos torres (la exclusión, de 6 m, cabe en la del poste);
        # el relleno, además, lo que quita la restricción «sin relleno» del ensanche (3 m).
        taken = (cells_within(TOWER_BOX, TOWER_BUFFER_M)
                 | cells_within((*POST_LOCAL, *POST_LOCAL), POST_BUFFER_M))
        domain = legal_cells() - taken
        fill = domain - cells_within(DRAWN_BOX, 3.0)
        classes = np.asarray(self.masks().classes)
        self.assertEqual(int(((classes & 8) != 0).sum()), len(legal_cells()))  # perímetro
        self.assertEqual(int(((classes & 2) != 0).sum()), len(fill))
        self.assertLess(len(fill), len(domain))
        cut = int(((classes & 1) != 0).sum())
        self.assertLess(0, cut)
        self.assertLess(cut, len(domain))
        texts = self.texts()
        hectares = CELL_M2 / 10_000.0
        self.assertEqual(texts[0], (
            f"Máscaras de V01.r1 al día: dominio {number(len(domain) * hectares, 2)} ha, "
            f"corte {number(cut * hectares, 2)} ha, relleno {number(len(fill) * hectares, 2)} ha, "
            f"franja {number(0, 2)} ha"))
        self.assertTrue(any(text.startswith("No hay perímetro de actuación: se toma como "
                                            "perímetro el límite legal (Concesión)")
                            for text in texts), texts)
        self.assertEqual(texts[-1], "Búsqueda de elementos intocables pendiente en: el "
                                    "perímetro de actuación")
        self.assertTrue(self.view().report_lines[len(texts) - 1].alert)
        self.assertFalse(any("polígono +" in text for text in texts))

    def test_k_change_a_buffer_only_in_v01_and_compile_again(self) -> None:
        """RF-012-02, RF-012-06, RF-009-24: el resguardo de la torre de 8 a 12 m solo en V01
        (el diálogo de la 008 con el ámbito de la 009) deja las máscaras de V01 obsoletas y no las
        de V02, la lista dice «V01: 12 m [ADO] · proyecto: 8 m [HIP]», y al compilar de nuevo
        informa de lo ganado y lo perdido de esa restricción (su polígono no cambió; su zona
        ganó las celdas nuevas) y de nada más."""
        key = self.cparams.buffer_out_key("torre_132_kv")
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value="12", scope="VERSION", kind="ADOPTADO", decided_by=PERSON,
            reason="Resguardo de la línea eléctrica en V01"), {"FINISHED"})
        self.assertEqual(self.param(key).value, 8.0)
        self.assertEqual(self.param(key, self.v01).value, 12.0)
        self.assertIsNone(self.param(key, self.v02))
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual(state, self.access.MaskState.STALE)
        self.open_window()
        shown = {line.key: line.text for line in self.listed()["torre_132_kv"].parameters}
        self.assertEqual(shown[key], "V01: 12 m [ADO] · proyecto: 8 m [HIP]")
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        before = cells_within(TOWER_BOX, TOWER_BUFFER_M)
        after = cells_within(TOWER_BOX, TOWER_BUFFER_V01_M)
        gained = len(after - before) * CELL_M2
        self.assertGreater(gained, 0)
        texts = self.texts()
        changed = [text for text in texts if "Torre 132 kV" in text]
        self.assertEqual(changed, [
            f"Torre 132 kV: polígono +{number(0, 0)} m² −{number(0, 0)} m², zona "
            f"+{number(gained, 0)} m² −{number(0, 0)} m²"])
        self.assertEqual(len([text for text in texts if "polígono +" in text]), 1)
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual(state, self.access.MaskState.CURRENT)

    def test_l_escape_in_the_middle_leaves_nothing_in_the_project(self) -> None:
        """RF-012-28, RNF-012-06: por pasos, un evento cada vez; Esc antes del primer paso y a
        mitad (con la operación ya empezada) deja «cancelada» la compilación y nada en el
        proyecto (ni datos, ni cifras, ni ficheros) y las máscaras de antes, al día; hasta el
        final, con su avance en la barra de estado y ninguna llamada de más de 0,2 s."""
        before = self.mask_files()
        outputs = self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE "
                            "'gis_msk%' ORDER BY name")
        figures = self.rows("SELECT count(*) FROM gb_figure")[0][0]
        cls = self.commands.registered_class(COMPILE)
        shown: list[str] = []
        status_text = cls._status_text

        def spy(op: Any, step: Any) -> str:
            shown.append(status_text(op, step))
            return shown[-1]

        self.enterContext(mock.patch.object(cls, "_status_text", spy))
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(
            "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        self.assertEqual(self.running().modal(bpy.context, ESC), {"CANCELLED"})  # sin empezar
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # un paso por evento
            self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            operator = self.running()
            for _ in range(MAX_EVENTS):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
                if getattr(operator, "handle", None) is not None and \
                        operator.progress_log[-1][1] != "prepare":
                    break
            self.assertIsNotNone(operator.handle, operator.progress_log)
            self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"},
                             operator.progress_log)
        started = self.rows("SELECT status FROM gb_operation WHERE uid = ?",
                            operator.handle.uid)
        self.assertEqual(started, [("running",)])  # en curso: aún no ha terminado
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1],
                         "Compilación cancelada: no ha quedado nada a medias")
        self.assertEqual(self.rows("SELECT status FROM gb_operation WHERE uid = ?",
                                   operator.handle.uid), [("cancelled",)])
        self.assertEqual(self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE "
                                   "'gis_msk%' ORDER BY name"), outputs)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_figure")[0][0], figures)
        self.assertEqual(self.mask_files(), before)
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual(state, self.access.MaskState.CURRENT)
        shown.clear()
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # un paso por evento
            self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            state, calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        self.assertGreater(len(calls), 8)
        self.assertTrue(shown)
        for text in shown:
            self.assertRegex(text, r"^Compilando las restricciones… \d+ % · Esc: cancelar$")
        self.assertTrue(self.texts()[0].startswith("Máscaras de V01.r1 al día: "))

    def test_m_export_the_classes_grid_to_a_geotiff(self) -> None:
        """RF-012-20: la rejilla de clases al día se exporta a un GeoTIFF con su leyenda
        (``.qml`` al lado); no sobre un fichero que ya existe, no dentro del proyecto y no con
        las máscaras obsoletas (un parámetro de V01 que cambia)."""
        target = self.folder / "mascaras_v01.tif"
        self.assertEqual(bpy.ops.geoblender.gis_export_constraint_masks(filepath=str(target)),
                         {"FINISHED"})
        qml = target.with_suffix(".qml")
        self.assertTrue(target.is_file() and qml.is_file())
        self.assertIn("Dentro del perímetro de actuación", qml.read_text(encoding="utf-8"))
        text = self.refused(bpy.ops.geoblender.gis_export_constraint_masks,
                            filepath=str(target))
        self.assertIn("Ya existe", text)
        inside = Path(self.project.root) / "rasters" / "dentro.tif"
        self.assertIn("proyecto", self.refused(bpy.ops.geoblender.gis_export_constraint_masks,
                                               filepath=str(inside)))
        self.assertEqual(bpy.ops.geoblender.gis_export_constraint_masks(
            filepath=str(target), overwrite=True), {"FINISHED"})
        key = self.cparams.buffer_out_key("balsa")
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value="9", scope="VERSION", kind="ADOPTADO", decided_by=PERSON,
            reason="Cambia el resguardo de la balsa en V01"), {"FINISHED"})
        stale = self.folder / "obsoletas.tif"
        self.assertIn("obsoletas", self.refused(bpy.ops.geoblender.gis_export_constraint_masks,
                                                filepath=str(stale)))
        self.assertFalse(stale.exists())
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})

    def test_n_unavailable_without_a_project_read_only_or_superseded(self) -> None:
        """RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO, las
        órdenes que escriben (Restricciones…, crear, completar, compilar) no están disponibles y
        dicen por qué (también en su descripción); la ventana abierta lo dice y desactiva lo que
        escribe; exportar no es una operación y solo pide proyecto."""
        writes = (bpy.ops.geoblender.core_edit_constraints,
                  bpy.ops.geoblender.core_create_constraints,
                  bpy.ops.geoblender.core_complete_constraint,
                  bpy.ops.geoblender.gis_compile_constraints)
        for command in (*writes, bpy.ops.geoblender.gis_export_constraint_masks):
            self.assertTrue(command.poll())
        with mock.patch.object(self.session.SESSION, "_project", None):
            self.assertEqual(self.session.write_unavailable(), "Abra un proyecto")
            for command in (*writes, bpy.ops.geoblender.gis_export_constraint_masks):
                self.assertFalse(command.poll())
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            for command in writes:
                self.assertFalse(command.poll())
            self.assertTrue(bpy.ops.geoblender.gis_export_constraint_masks.poll())
            self.open_window_quiet()
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            self.assertIn(reason, layout.texts())
            disabled = {item.target for item in layout.of_kind("operator") if not item.enabled}
            self.assertTrue({CREATE, COMPILE} <= disabled, disabled)
            self.assertNotIn(EXPORT, disabled)
        self.assertTrue(bpy.ops.geoblender.core_edit_constraints.poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        note = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        for command in writes:
            self.assertFalse(command.poll())
        for idname in (EDIT, CREATE, COMPLETE, COMPILE):
            cls = self.commands.registered_class(idname)
            self.assertIn(note, cls.description(bpy.context, SimpleNamespace()))
        self.set_active(self.v01)
        self.assertTrue(bpy.ops.geoblender.gis_compile_constraints.poll())
        self.assertIsInstance(draw(getattr(bpy.types, PANEL), bpy.context), FakeLayout)

    def open_window_quiet(self) -> None:
        """Lee la vista como lo haría la orden, sin su poll (en solo lectura)."""
        self.panels.fill_constraints(self.project)


if __name__ == "__main__":
    unittest.main()
