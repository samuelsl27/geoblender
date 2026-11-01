# SPDX-License-Identifier: GPL-3.0-or-later
"""Buscar elementos intocables por sector… (spec 012, T24; HU-012-3; RF-012-07, RF-012-08,
RF-012-09, RF-012-10, RF-012-28; plan 012 §5.3.4, §5.5, A6, A12, D-26).

- RF-012-07 (``geoblender.core_declare_sectors``): sin sectores declarados, el perímetro de
  actuación es el único sector; declarar los de una capa de polígonos y su campo los guarda e
  informa del área del perímetro que no cubre ningún sector; una capa con solapes, sin el campo o
  sin elegir se rechaza sin escribir nada; «Usar el perímetro» los quita.
- RF-012-08 (``geoblender.core_search_untouchables``): buscar por pasos (Esc a mitad no deja
  nada; ninguna llamada de más de 0,2 s) en un sector con las capas elegidas: el sector 2 da la
  torre a 6,0 m con sus atributos; la lista de lo hallado en la ventana. Convertirla con 8 m de
  resguardo y su motivo (``geoblender.core_convert_hit``) crea el intocable con su geometría, su
  origen y su resguardo; descartar (``geoblender.core_discard_hit``) pide un motivo.
- RF-012-09 (``geoblender.core_close_search``): cerrar registra la búsqueda (sector y huella,
  capas con su hash, lo hallado, lo convertido y lo descartado con su motivo, quién y cuándo); no
  se cierra con algo sin decidir; el sector queda vigente.
- RF-012-10: el sector 1, sin búsqueda, sale «Búsqueda pendiente» en la ventana y en las
  máscaras compiladas («Búsqueda de elementos intocables pendiente en: Sector 1»); al cerrar la
  suya, ya no.
- RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO las órdenes están
  desactivadas con su motivo; «Buscar elementos intocables por sector…» pasa a la entrada «012».

Un proyecto por clase (rejilla de 48 × 40 celdas de 5 m) y la extensión sin importar otra vez
(RNF-001-01). Se ejecuta con ``tools/run_blender_tests.py``.
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
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw
from tests.support.trees import remove_tree

ENTRY = "012"
FIND = "geoblender.core_find_untouchables"
DECLARE = "geoblender.core_declare_sectors"
SEARCH = "geoblender.core_search_untouchables"
CONVERT = "geoblender.core_convert_hit"
DISCARD = "geoblender.core_discard_hit"
CLOSE = "geoblender.core_close_search"
SET_PARAMETER = "geoblender.core_set_parameter"
REAL = (FIND, DECLARE, SEARCH, CONVERT, DISCARD, CLOSE)
INTERNAL = (DECLARE, SEARCH, CONVERT, DISCARD, CLOSE)
STILL_PROVISIONAL: tuple[str, ...] = ()  # ninguna: la T28 entregó la última provisional
PANEL = "GEOBLENDER_PT_core_search"
SECTORS_LIST = "GEOBLENDER_UL_core_sectors"
HITS_LIST = "GEOBLENDER_UL_core_hits"
WM_PROPERTY = "geoblender_constraints"
FIND_TYPE = "core.find_untouchables"
DECLARE_TYPE = "core.declare_sectors"
EDIT_TYPE = "core.edit_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M = 240.0
HEIGHT_M = 200.0
STEP_M = 5.0
REASON = "Prueba de la búsqueda de intocables de la 012"
TOWER_REASON = "Torre de alta tensión de la línea de 132 kV"
LINE_REASON = "Línea fuera de servicio desde 2024"
PERSON = "Samuel (IMGA)"
DATE_TEXT = "31/10/2026"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 800
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal (RNF-012-06)."""
LEGAL_BOX = (0.0, 0.0, 200.0, 200.0)
SECTOR_BOXES = {"Sector 1": (20.0, 20.0, 90.0, 180.0), "Sector 2": (110.0, 20.0, 180.0, 180.0)}
OVERLAPPING = {"Norte": (20.0, 20.0, 90.0, 180.0), "Sur": (80.0, 20.0, 150.0, 180.0)}
TOWER_LOCAL = (186.0, 100.0)
"""La torre: a 6,0 m del sector 2 (186 − 180) y a 96 m del sector 1."""
LINE_LOCAL = ((0.0, 195.0), (80.0, 195.0))
"""La línea eléctrica: a 15,0 m del sector 1 y a 33,5 m del sector 2 (más de los 25 m)."""
TOWER_BUFFER_M = 8.0
UNCOVERED_M2 = 200.0 * 200.0 - 2 * 70.0 * 160.0
"""El área del perímetro (la concesión, que hace de perímetro) que no cubre ningún sector."""
STEP_TEXT = "Búsqueda pendiente"
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


def cells_within(point: tuple[float, float], radius: float) -> set[tuple[int, int]]:
    """Las celdas (columna, fila desde el sur) a una distancia menor que ``radius`` del punto
    local dado: la zona de una restricción puntual por fuerza bruta (D-1: la celda entera del
    lado seguro)."""
    found: set[tuple[int, int]] = set()
    for column in range(COLUMNS):
        for row in range(ROWS):
            left, bottom = column * STEP_M, row * STEP_M
            dx = max(point[0] - (left + STEP_M), left - point[0], 0.0)
            dy = max(point[1] - (bottom + STEP_M), bottom - point[1], 0.0)
            if (dx * dx + dy * dy) ** 0.5 < radius - 1e-9:
                found.add((column, row))
    return found


def legal_cells() -> set[tuple[int, int]]:
    """Las celdas enteras dentro del límite legal (LEGAL_BOX)."""
    return {(column, row) for column in range(int(LEGAL_BOX[2] / STEP_M))
            for row in range(int(LEGAL_BOX[3] / STEP_M))}


class ConstraintsSearchTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, el límite legal declarado y
    las capas de la prueba importadas como entidades, para toda la clase (las pruebas, en el
    orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r24-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.folder = folder
        cls.ps = _module("bl.scene.project_session")
        cls.core_ops = _module("bl.ops.core_constraints")
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
            cls.v01, _revision = store.create_version(conn, cls.project, feature="busqueda",
                                                      title="Búsqueda", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        sources = folder / "fuentes"
        sources.mkdir()
        sector_boxes = [(fid, rectangle(*box), {"sector": name})
                        for fid, (name, box) in enumerate(SECTOR_BOXES.items(), start=1)]
        overlapping = [(fid, rectangle(*box), {"sector": name})
                       for fid, (name, box) in enumerate(OVERLAPPING.items(), start=1)]
        cls.names = {
            "Concesion": cls.import_layer(sources, "Concesion", "POLYGON", ("nombre",),
                                          [(1, rectangle(*LEGAL_BOX), {"nombre": "Concesión"})]),
            "Sectores": cls.import_layer(sources, "Sectores", "POLYGON", ("sector",),
                                         sector_boxes),
            "Solapados": cls.import_layer(sources, "Solapados", "POLYGON", ("sector",),
                                          overlapping),
            "Torres": cls.import_layer(
                sources, "Torres", "POINT", ("nombre", "clase"),
                [(1, np.array([WEST + TOWER_LOCAL[0], SOUTH + TOWER_LOCAL[1]]),
                  {"nombre": "Torre 14", "clase": "Torre eléctrica"})]),
            "Lineas": cls.import_layer(
                sources, "Lineas", "LINESTRING", ("nombre", "clase"),
                [(2, np.array([(WEST + x, SOUTH + y) for x, y in LINE_LOCAL]),
                  {"nombre": "Línea de 20 kV", "clase": "Línea eléctrica"})]),
        }
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {
            "FINISHED"}
        with mock.patch.object(cls.core_ops, "_call_panel", return_value={"FINISHED"}):
            assert bpy.ops.geoblender.core_edit_limits() == {"FINISHED"}
        limits = getattr(bpy.context.window_manager, WM_PROPERTY)
        for item in limits.limit_layers:
            item.legal = item.name == cls.names["Concesion"]
        limits.limit_name_field = "nombre"
        limits.limit_reason = REASON
        limits.limit_decided_by = PERSON
        limits.limit_decided_on = DATE_TEXT
        limits.limit_inward = "10"
        assert bpy.ops.geoblender.core_declare_limits() == {"FINISHED"}

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
        """Las restricciones guardadas, por código."""
        with self.project.read() as conn:
            return {item.code: item for item in self.cstore.read_constraints(conn)}

    def count(self) -> tuple[int, int]:
        """(operaciones, restricciones) del proyecto: lo que un rechazo no cambia."""
        return (self.rows("SELECT count(*) FROM gb_operation")[0][0], len(self.stored()))

    def refused(self, command: Any, **values: Any) -> str:
        """El error de ``command`` desde un guion (``RuntimeError``) sin que cambie el
        proyecto."""
        before = self.count()
        with self.assertRaises(RuntimeError) as caught:
            command(**values)
        self.assertEqual(self.count(), before)
        return str(caught.exception)

    def open_window(self) -> Any:
        """«Buscar elementos intocables por sector…» con su ventana sustituida (en
        ``blender -b``, ``wm.call_panel`` cierra Blender): la vista, leída del proyecto."""
        with mock.patch.object(self.core_ops, "_call_panel", return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.core_find_untouchables(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view()

    def texts(self) -> list[str]:
        return [line.text for line in self.view().search_lines]

    def sectors(self) -> dict[str, tuple[str, bool]]:
        """Los sectores de la ventana: nombre → (código, vigente)."""
        return {item.name: (item.code, item.current) for item in self.view().sectors}

    def choose(self, sector: str) -> None:
        names = [item.name for item in self.view().sectors]
        self.view().sector_index = names.index(sector)

    def use(self, *layers: str) -> None:
        for item in self.view().search_layers:
            item.use = item.name in layers

    def running(self) -> Any:
        """El modal de la búsqueda en marcha (el único con pasos)."""
        cls = self.commands.registered_class(SEARCH)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "la búsqueda no está en marcha")
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
        self.fail("la búsqueda no acaba")

    def search(self, sector: str, *layers: str) -> list[float]:
        """Busca en ``sector`` con las capas dadas (nombres de los datos) por pasos, un evento
        cada vez, hasta el final; lo que duró cada llamada."""
        self.choose(sector)
        self.use(*layers)
        cls = self.commands.registered_class(SEARCH)
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # un paso por evento
            self.assertEqual(bpy.ops.geoblender.core_search_untouchables(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            state, calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        return calls

    def operators(self, target: str) -> list[Any]:
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        return [item for item in layout.of_kind("operator") if item.target == target]

    def searches(self) -> list[tuple[Any, ...]]:
        return self.rows("SELECT sector_code, distance_m, closed_by FROM core_untouchable_search "
                         "ORDER BY fid")

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_are_real_and_in_the_012_entry(self) -> None:
        """RF-012-28, D-31, D-38: «Buscar elementos intocables por sector…» y las cinco
        internas (declarar los sectores, buscar, convertir, descartar, cerrar) tienen su clase
        real y están en la entrada «012»; las que registran una operación lo hacen con su tipo;
        las demás de R-32 siguen provisionales."""
        cat = self.commands.catalog()
        aware = self.session.ProvenanceAwareOperator
        for idname in REAL:
            with self.subTest(orden=idname):
                self.assertEqual(cat.commands[idname].entry, ENTRY)
                cls = self.commands.registered_class(idname)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls.bl_label, (cat.commands[idname].label,
                                             cat.commands[idname].label_es))
        self.assertEqual((cat.commands[FIND].kind, cat.commands[FIND].action), ("operator", "D"))
        for idname in INTERNAL:
            self.assertEqual(cat.commands[idname].kind, "internal")
        for idname, op_type in ((FIND, FIND_TYPE), (DECLARE, DECLARE_TYPE), (CONVERT, EDIT_TYPE),
                                (CLOSE, FIND_TYPE)):
            cls = self.commands.registered_class(idname)
            self.assertTrue(issubclass(cls, aware), idname)
            self.assertEqual(cls.provenance_op_type, op_type)
        design = cat.menus["GEOBLENDER_MT_ui_design"]
        keys = [item.key for item in design.groups[0].items]
        self.assertEqual(keys[:3], ["geoblender.core_edit_limits",
                                    "geoblender.core_edit_constraints", FIND])
        for idname in STILL_PROVISIONAL:
            with self.subTest(sigue_provisional=idname):
                self.assertEqual(cat.commands[idname].entry, "R-32")
                self.assertTrue(self.commands.is_provisional(
                    self.commands.registered_class(idname)))

    def test_b_the_perimeter_is_the_only_sector_until_they_are_declared(self) -> None:
        """RF-012-07, RF-012-10, D-26: sin sectores declarados, la ventana tiene un solo sector,
        el perímetro de actuación (aquí, el límite legal), con la búsqueda pendiente; ofrece las
        capas de entidades del proyecto con su geometría (nada marcado), las de polígonos para
        declarar sectores y la distancia de búsqueda con su valor y su tipo; sin búsqueda
        abierta no enseña lista."""
        view = self.open_window()
        self.assertEqual(self.sectors(), {"el perímetro de actuación": ("", False)})
        self.assertEqual(view.sectors[0].text, STEP_TEXT)
        self.assertEqual({item.name: item.kind for item in view.search_layers}, {
            self.names["Concesion"]: "polygon", self.names["Lineas"]: "line",
            self.names["Sectores"]: "polygon", self.names["Solapados"]: "polygon",
            self.names["Torres"]: "point"})
        self.assertFalse(any(item.use for item in view.search_layers))
        self.assertEqual({item.name for item in view.sector_sources},
                         {self.names[key] for key in ("Concesion", "Sectores", "Solapados")})
        self.assertTrue(view.search_distance.startswith("25 m"), view.search_distance)
        self.assertEqual((len(view.hits), view.search_title), (0, ""))
        ul = getattr(bpy.types, SECTORS_LIST)
        row = FakeLayout()
        ul.draw_item(None, bpy.context, row, view, view.sectors[0], 0, view, "sector_index")
        self.assertIn("el perímetro de actuación", " ".join(row.texts()))
        self.assertIn(STEP_TEXT, " ".join(row.texts()))
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        targets = {item.target for item in layout.of_kind("operator")}
        self.assertTrue({DECLARE, SEARCH} <= targets, targets)
        self.assertNotIn(CLOSE, targets)  # sin búsqueda abierta no hay nada que cerrar
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   DECLARE_TYPE)[0][0], 0)

    def test_c_declare_the_sectors_from_a_layer(self) -> None:
        """RF-012-07, D-3: declarar los sectores de la capa de polígonos y su campo los guarda
        (``core.declare_sectors``, con la capa como entrada), los lista con su búsqueda
        pendiente e informa del área del perímetro que no cubre ningún sector; una capa con un
        solape, un campo que no tiene, ninguna capa o ningún campo se rechaza sin escribir
        nada."""
        view = self.open_window()
        declare = bpy.ops.geoblender.core_declare_sectors
        self.assertIn("capa", self.refused(declare))  # sin capa elegida
        view.sector_layer = self.names["Sectores"]
        self.assertIn("campo", self.refused(declare))  # sin campo
        view.sector_field = "no_hay"
        text = self.refused(declare)
        self.assertIn("«no_hay»", text)
        self.assertIn("«sector»", text)  # los campos que sí tiene la capa
        view.sector_layer = self.names["Solapados"]
        view.sector_field = "sector"
        text = self.refused(declare)
        self.assertIn("se solapan", text)
        self.assertIn(f"{number(1600, 2)} m²", text)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   DECLARE_TYPE)[0][0], 0)
        view.sector_layer = self.names["Sectores"]
        self.assertEqual(declare(), {"FINISHED"})
        self.assertEqual(self.sectors(), {"Sector 1": ("sector_1", False),
                                          "Sector 2": ("sector_2", False)})
        self.assertEqual([item.text for item in view.sectors], [STEP_TEXT, STEP_TEXT])
        self.assertEqual(self.texts()[0], (
            f"Sectores declarados: 2; área del perímetro sin sector: {number(UNCOVERED_M2, 0)} "
            "m²"))
        ((_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ?", DECLARE_TYPE)
        self.assertEqual(status, "done")
        self.assertEqual(json.loads(settings)["field"], "sector")
        self.assertEqual([row[0] for row in self.rows(
            "SELECT code FROM core_sector ORDER BY fid")], ["sector_1", "sector_2"])
        self.assertEqual(self.rows(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = "
            "io.item_uid WHERE io.direction = 'in' AND io.operation_uid = ?", _uid),
            [(self.names["Sectores"],)])

    def test_d_search_a_sector_in_steps_and_list_what_is_found(self) -> None:
        """RF-012-08, RNF-012-06: buscar en el sector 2 con las capas de la torre y de la línea
        da la torre a 6,0 m con sus atributos (la línea, a 33,5 m, no); por pasos, con el
        avance en la barra de estado y ninguna llamada de más de 0,2 s; Esc antes de empezar y
        a mitad no deja nada; sin capas elegidas se rechaza; la lista de la ventana lleva su
        capa, su distancia, sus atributos y «Convertir…» y «Descartar…»."""
        torres, lineas = self.names["Torres"], self.names["Lineas"]
        view = self.open_window()
        self.use()
        self.choose("Sector 2")
        self.assertIn("capa", self.refused(bpy.ops.geoblender.core_search_untouchables))
        self.use(torres, lineas)
        cls = self.commands.registered_class(SEARCH)
        shown: list[str] = []
        status_text = cls._status_text

        def spy(op: Any, step: Any) -> str:
            shown.append(status_text(op, step))
            return shown[-1]

        self.enterContext(mock.patch.object(cls, "_status_text", spy))
        self.assertEqual(bpy.ops.geoblender.core_search_untouchables(
            "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        self.assertEqual(self.running().modal(bpy.context, ESC), {"CANCELLED"})  # sin empezar
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # y a mitad
            self.assertEqual(bpy.ops.geoblender.core_search_untouchables(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            operator = self.running()
            self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], "Búsqueda cancelada: no ha quedado nada a medias")
        self.assertIsNone(self.core_ops.open_search())
        self.assertEqual((len(view.hits), view.search_title), (0, ""))
        shown.clear()
        calls = self.search("Sector 2", torres, lineas)
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(shown)
        for text in shown:
            self.assertRegex(text, r"^Buscando en «Sector 2»… \d+ % · Esc: cancelar$")
        (hit,) = view.hits
        self.assertEqual((hit.name, hit.layer, hit.fid, hit.kind, hit.distance, hit.state),
                         ("Torre 14", torres, 1, "point", number(6.0, 1), "pending"))
        self.assertIn("nombre: Torre 14", hit.details)
        self.assertIn("clase: Torre eléctrica", hit.details)
        self.assertEqual(view.search_title, "Hallado en Sector 2: 1 a ≤ 25 m, 1 sin decidir")
        self.assertEqual(self.texts()[0], (
            "Búsqueda en «Sector 2» (capas: lineas, torres; hasta 25 m): entidades halladas: 1"))
        opened = self.core_ops.open_search()
        self.assertEqual((opened.searched.sector_code, len(opened.searched.found)),
                         ("sector_2", 1))
        self.assertAlmostEqual(opened.searched.found[0].distance_m, 6.0, places=9)
        # Nada se ha escrito: buscar solo lee.
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   FIND_TYPE)[0][0], 0)
        # La ventana: la lista y, de la elegida, sus botones.
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        (listing,) = [item for item in layout.items if item.kind == "template_list"
                      and item.target == HITS_LIST]
        self.assertEqual(listing.target, HITS_LIST)
        shown_texts = layout.texts()
        for text in ("nombre: Torre 14", view.search_title):
            self.assertTrue(any(text in each for each in shown_texts), text)
        for target in (CONVERT, DISCARD):
            (button,) = self.operators(target)
            self.assertTrue(button.enabled)
            self.assertEqual((button.properties.layer, button.properties.fid), (torres, 1))
        self.assertEqual(len(self.operators(CLOSE)), 1)
        ul = getattr(bpy.types, HITS_LIST)
        row = FakeLayout()
        ul.draw_item(None, bpy.context, row, view, hit, 0, view, "hit_index")
        self.assertIn("Torre 14", " ".join(row.texts()))
        self.assertIn(number(6.0, 1), " ".join(row.texts()))

    def test_e_close_is_refused_while_something_is_undecided(self) -> None:
        """RF-012-09: sin decisión para la torre hallada, cerrar la búsqueda se rechaza con la
        lista de lo que falta (también sin escribir quién cierra) y no registra nada."""
        view = self.open_window()
        self.assertEqual(self.core_ops.open_search().searched.sector_code, "sector_2")
        self.assertEqual(view.hits[0].state, "pending")  # reabrir la ventana la conserva
        self.assertTrue(view.search_decided_by)  # la persona de la sesión, por defecto
        view.search_decided_by = " "
        text = self.refused(bpy.ops.geoblender.core_close_search)
        self.assertIn("quién cierra", text)
        view.search_decided_by = PERSON
        text = self.refused(bpy.ops.geoblender.core_close_search)
        self.assertIn("no tienen decisión", text)
        self.assertIn("Torre 14", text)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   FIND_TYPE)[0][0], 0)

    def test_f_convert_the_tower_with_8_m_and_its_reason(self) -> None:
        """RF-012-08, RF-012-02: convertir la torre con 8 m de resguardo y su motivo crea UN
        intocable con su geometría bit a bit, su origen (la entrada de la capa y la entidad), su
        nombre, su motivo, su decisor y su resguardo como parámetro del proyecto, con una
        ``core.edit_constraints``; sin motivo, sin resguardo, con 0 m (un punto necesita más),
        con algo que no es un número o con una entidad que no se halló se rechaza sin escribir
        nada; no se convierte dos veces ni se descarta lo convertido; mientras tanto no se
        busca en otro sector (se perdería su constancia)."""
        torres = self.names["Torres"]
        convert = bpy.ops.geoblender.core_convert_hit
        good = {"layer": torres, "fid": 1, "name": "Torre 14", "buffer_out": "8",
                "reason": TOWER_REASON, "decided_by": PERSON}
        self.assertIn("motivo", self.refused(convert, **{**good, "reason": " "}))
        self.assertIn("resguardo", self.refused(convert, **{**good, "buffer_out": ""}))
        self.assertIn("más de 0", self.refused(convert, **{**good, "buffer_out": "0"}))
        self.assertIn("«mucho»", self.refused(convert, **{**good, "buffer_out": "mucho"}))
        self.assertIn("quién", self.refused(convert, **{**good, "decided_by": ""}))
        self.assertIn("no está entre las halladas", self.refused(convert, **{**good, "fid": 9}))
        origin = self.rows("SELECT input_uid FROM gb_dataset WHERE name = ?", torres)[0][0]
        before = self.count()
        self.assertEqual(convert(**good), {"FINISHED"})
        self.assertEqual(self.count(), (before[0] + 1, before[1] + 1))
        row = self.stored()["torre_14"]
        self.assertEqual((row.name, row.ctype.value, row.kind.value, row.reason, row.decided_by,
                          row.source_fid, row.source_input, row.priority),
                         ("Torre 14", "untouchable", "point", TOWER_REASON, PERSON, 1, origin, 0))
        self.assertTrue(np.array_equal(row.parts[0][0].reshape(-1),
                                       [WEST + TOWER_LOCAL[0], SOUTH + TOWER_LOCAL[1]]))
        self.assertEqual(self.params.ParameterStore(self.project).get(
            self.cparams.buffer_out_key("torre_14")).value, TOWER_BUFFER_M)
        self.assertEqual(self.params.ParameterStore(self.project).get(
            self.cparams.active_key("torre_14")).value, True)
        ((_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ? ORDER BY "
            "started_at DESC, uid LIMIT 1", EDIT_TYPE)
        self.assertEqual((status, json.loads(settings)["created"]), ("done", 1))
        view = self.view()
        (hit,) = view.hits
        self.assertEqual((hit.state, hit.constraint, hit.reason), ("converted", "torre_14",
                                                                  TOWER_REASON))
        self.assertEqual(view.search_title, "Hallado en Sector 2: 1 a ≤ 25 m, 0 sin decidir")
        self.assertEqual(self.texts()[0], (
            "Entidad convertida: «Torre 14» es ahora un intocable con 8 m de resguardo"))
        self.assertIn("ya se convirtió", self.refused(convert, **good))
        self.assertIn("ya se convirtió", self.refused(
            bpy.ops.geoblender.core_discard_hit, layer=torres, fid=1, reason="Otra vez"))
        for target in (CONVERT, DISCARD):  # lo convertido ya no se decide de nuevo
            (button,) = self.operators(target)
            self.assertFalse(button.enabled)
        self.choose("Sector 1")
        self.use(torres)
        self.assertIn("Cierre antes la búsqueda de «Sector 2»",
                      self.refused(bpy.ops.geoblender.core_search_untouchables))

    def test_g_close_registers_the_search(self) -> None:
        """RF-012-09, RF-012-10: cerrar registra la búsqueda (``core.find_untouchables``): el
        sector y su huella, las capas consultadas con su hash (sus entradas), la distancia, lo
        hallado con su decisión, su motivo y la restricción en que se convirtió, quién y
        cuándo; el sector 2 queda vigente y el 1, «Búsqueda pendiente» en la ventana, que lo
        dice."""
        view = self.view()
        view.search_decided_by = PERSON
        torres, lineas = self.names["Torres"], self.names["Lineas"]
        self.assertEqual(bpy.ops.geoblender.core_close_search(), {"FINISHED"})
        ((sector, distance, closed_by),) = self.searches()
        self.assertEqual((sector, distance, closed_by), ("sector_2", 25.0, PERSON))
        (search_uid,) = [row[0] for row in self.rows("SELECT uid FROM core_untouchable_search")]
        ((layer, fid, hit_distance, attributes, decision, reason, code),) = self.rows(
            "SELECT layer_dataset, feature_fid, distance_m, attributes, decision, reason, "
            "constraint_code FROM core_untouchable_hit WHERE search_uid = ?", search_uid)
        self.assertEqual((layer, fid, decision, reason, code),
                         (torres, 1, "converted", TOWER_REASON, "torre_14"))
        self.assertAlmostEqual(hit_distance, 6.0, places=9)
        self.assertEqual(json.loads(attributes), {"nombre": "Torre 14", "clase": "Torre eléctrica"})
        ((op_uid, status),) = self.rows(
            "SELECT uid, status FROM gb_operation WHERE op_type = ?", FIND_TYPE)
        self.assertEqual(status, "done")
        inputs = {role: name for role, name in self.rows(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = "
            "io.item_uid WHERE io.direction = 'in' AND io.operation_uid = ?", op_uid)}
        self.assertEqual(inputs, {"sector": "core_sector", "layer_1": lineas, "layer_2": torres})
        self.assertEqual(self.params.ParameterStore(self.project).get(
            self.cparams.SEARCH_DISTANCE.key).value, 25.0)
        # La ventana: sin búsqueda abierta; sector 2 vigente, sector 1 pendiente.
        self.assertIsNone(self.core_ops.open_search())
        self.assertEqual((len(view.hits), view.search_title), (0, ""))
        self.assertEqual(self.sectors(), {"Sector 1": ("sector_1", False),
                                          "Sector 2": ("sector_2", True)})
        self.assertEqual(view.sectors[0].text, STEP_TEXT)
        self.assertTrue(view.sectors[1].text.startswith(
            f"Búsqueda vigente, cerrada por {PERSON} el "), view.sectors[1].text)
        texts = self.texts()
        self.assertEqual(texts[0], ("Búsqueda de «Sector 2» cerrada (halladas: 1, convertidas: "
                                    "1, descartadas: 0)"))
        self.assertEqual(texts[-1], "Búsqueda de elementos intocables pendiente en: Sector 1")
        self.assertTrue(view.search_lines[len(texts) - 1].alert)
        self.assertIn("No hay ninguna búsqueda abierta: busque primero",
                      self.refused(bpy.ops.geoblender.core_close_search))
        self.assertIn("25 m", view.search_distance)

    def test_h_the_masks_mark_the_pending_sector_and_take_the_new_untouchable(self) -> None:
        """RF-012-10, RF-012-11: las máscaras compiladas con el sector 1 sin búsqueda lo dicen
        («Búsqueda de elementos intocables pendiente en: Sector 1») y el intocable que salió de
        la torre (8 m) quita sus celdas del dominio."""
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        state, pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual((state, pending), (self.access.MaskState.CURRENT, ("sector_1",)))
        texts = [line.text for line in self.view().report_lines]
        self.assertEqual(texts[-1], "Búsqueda de elementos intocables pendiente en: Sector 1")
        self.assertTrue(self.view().report_lines[len(texts) - 1].alert)
        masks = self.access.load_masks(self.project, self.v01.uid)
        self.assertEqual((masks.pending_sectors, masks.pending_names), (("sector_1",),
                                                                        ("Sector 1",)))
        taken = cells_within(TOWER_LOCAL, TOWER_BUFFER_M)
        domain = legal_cells() - taken
        self.assertEqual(int(np.asarray(masks.default_domain()).sum()), len(domain))
        self.assertLess(len(domain), len(legal_cells()))

    def test_i_search_sector_1_and_discard_the_line_with_a_reason(self) -> None:
        """RF-012-08, RF-012-09: el sector 1 da la línea a 15,0 m (la torre, a 96 m, no);
        descartarla pide un motivo (sin él se rechaza); descartada, la decisión se conserva si
        se busca de nuevo en el mismo sector; Esc a mitad de otra búsqueda no pierde la abierta;
        sin cerrar, el sector 1 sigue pendiente."""
        torres, lineas = self.names["Torres"], self.names["Lineas"]
        view = self.open_window()
        self.search("Sector 1", torres, lineas)
        (hit,) = view.hits
        self.assertEqual((hit.name, hit.layer, hit.fid, hit.kind, hit.distance, hit.state),
                         ("Línea de 20 kV", lineas, 2, "line", number(15.0, 1), "pending"))
        discard = bpy.ops.geoblender.core_discard_hit
        self.assertIn("motivo", self.refused(discard, layer=lineas, fid=2, reason="  "))
        self.assertIn("no está entre las halladas", self.refused(
            discard, layer=lineas, fid=77, reason=LINE_REASON))
        self.assertEqual(discard(layer=lineas, fid=2, reason=LINE_REASON), {"FINISHED"})
        (hit,) = view.hits
        self.assertEqual((hit.state, hit.reason), ("discarded", LINE_REASON))
        self.assertEqual(view.search_title, "Hallado en Sector 1: 1 a ≤ 25 m, 0 sin decidir")
        self.assertEqual(self.texts()[0], "Entidad descartada: «Línea de 20 kV»")
        # Esc a mitad de otra búsqueda: la abierta, con su decisión, sigue.
        cls = self.commands.registered_class(SEARCH)
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):
            self.assertEqual(bpy.ops.geoblender.core_search_untouchables(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            operator = self.running()
            self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(view.hits[0].state, "discarded")
        # Buscar de nuevo en el mismo sector conserva la decisión de lo que se vuelve a hallar.
        self.search("Sector 1", torres, lineas)
        self.assertEqual((view.hits[0].state, view.hits[0].reason), ("discarded", LINE_REASON))
        self.assertEqual(len(self.searches()), 1)  # el sector 1 sigue sin cerrar
        self.assertEqual(self.sectors()["Sector 1"], ("sector_1", False))

    def test_j_close_the_last_search_and_nothing_is_pending(self) -> None:
        """RF-012-09, RF-012-10: cerrar la búsqueda del sector 1 (la línea descartada con su
        motivo) deja los dos sectores vigentes y las máscaras ya no marcan nada pendiente; la
        búsqueda registrada lleva la distancia, la decisión y su motivo."""
        view = self.view()
        view.search_decided_by = PERSON
        self.assertEqual(bpy.ops.geoblender.core_close_search(), {"FINISHED"})
        self.assertEqual([row[0] for row in self.searches()], ["sector_2", "sector_1"])
        self.assertEqual(self.rows(
            "SELECT layer_dataset, feature_fid, decision, reason, constraint_code FROM "
            "core_untouchable_hit WHERE search_uid = (SELECT uid FROM core_untouchable_search "
            "WHERE sector_code = 'sector_1')"),
            [(self.names["Lineas"], 2, "discarded", LINE_REASON, None)])
        self.assertEqual(self.sectors(), {"Sector 1": ("sector_1", True),
                                          "Sector 2": ("sector_2", True)})
        self.assertEqual(self.access.mask_state(self.project, self.v01.uid)[1], ())
        self.assertFalse(any("pendiente" in text for text in self.texts()), self.texts())
        # Una búsqueda sin nada hallado también se cierra: deja constancia de lo revisado.
        self.search("Sector 1", self.names["Torres"])
        self.assertEqual((len(self.view().hits), self.view().search_title),
                         (0, "Hallado en Sector 1: 0 a ≤ 25 m, 0 sin decidir"))
        self.assertEqual(bpy.ops.geoblender.core_close_search(), {"FINISHED"})
        self.assertEqual(len(self.searches()), 3)

    def test_k_without_sectors_the_perimeter_is_the_only_one_again(self) -> None:
        """RF-012-07, D-26: «Usar el perímetro» quita los sectores declarados; el perímetro es
        el único sector y su búsqueda está pendiente (el sector no tiene la huella de ninguna
        cerrada)."""
        self.open_window()
        self.assertEqual(bpy.ops.geoblender.core_declare_sectors(perimeter=True), {"FINISHED"})
        self.assertEqual(self.sectors(), {"el perímetro de actuación": ("", False)})
        self.assertEqual(self.texts()[0], ("Sin sectores declarados: el perímetro de actuación "
                                           "es el único sector"))
        self.assertEqual(self.rows("SELECT count(*) FROM core_sector"), [(0,)])
        self.assertEqual(self.access.mask_state(self.project, self.v01.uid)[1], ("",))

    def test_l_unavailable_without_a_project_read_only_or_superseded(self) -> None:
        """RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO las órdenes
        no están disponibles y dicen por qué (también en su descripción); la ventana abierta lo
        dice y desactiva lo que escribe, también el «Cambiar…» de la distancia de búsqueda (lo
        halló el hito H2: la ventana de la T24 lo dejaba activo)."""
        commands = (bpy.ops.geoblender.core_find_untouchables,
                    bpy.ops.geoblender.core_declare_sectors,
                    bpy.ops.geoblender.core_search_untouchables,
                    bpy.ops.geoblender.core_convert_hit, bpy.ops.geoblender.core_discard_hit,
                    bpy.ops.geoblender.core_close_search)
        for command in commands:
            self.assertTrue(command.poll())
        with mock.patch.object(self.session.SESSION, "_project", None):
            self.assertEqual(self.session.write_unavailable(), "Abra un proyecto")
            for command in commands:
                self.assertFalse(command.poll())
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            for command in commands:
                self.assertFalse(command.poll())
            self.panels.fill_search(self.project)
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            self.assertIn(reason, layout.texts())
            disabled = {item.target for item in layout.of_kind("operator") if not item.enabled}
            self.assertTrue({DECLARE, SEARCH} <= disabled, disabled)
            self.assertSearchDistanceCannotBeChanged(layout)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        note = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        for command in commands:
            self.assertFalse(command.poll())
        for idname in (FIND, DECLARE, CONVERT, CLOSE):
            cls = self.commands.registered_class(idname)
            self.assertIn(note, cls.description(bpy.context, SimpleNamespace()))
        self.panels.fill_search(self.project)
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        self.assertIn(note, layout.texts())
        self.assertSearchDistanceCannotBeChanged(layout)
        self.set_active(self.v01)
        self.assertTrue(bpy.ops.geoblender.core_find_untouchables.poll())

    def assertSearchDistanceCannotBeChanged(self, layout: FakeLayout) -> None:
        """La distancia de búsqueda ya está guardada (se cerró una búsqueda), así que la ventana
        dibuja su «Cambiar…», y con el proyecto en solo lectura o la versión no editable ese
        botón, que escribe, está desactivado como los demás (la prueba que lo llama cita el
        requisito)."""
        changes = [item for item in layout.of_kind("operator") if item.target == SET_PARAMETER]
        self.assertEqual(len(changes), 1)
        self.assertFalse(changes[0].enabled)

    def test_m_the_window_is_in_both_languages(self) -> None:
        """RF-012-28 (principio 10): la ventana, los sectores y sus estados se leen también en
        inglés, y la lista del sector 1 sigue pendiente."""
        i18n = _module("core.i18n")
        i18n.set_language("en")
        view = self.open_window()
        self.assertEqual(view.sectors[0].text, "Search pending")
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        texts = " ".join(layout.texts())
        self.assertIn("Search sectors", texts)
        self.assertNotIn("Búsqueda", texts)
        self.assertIn("Layers to consult", texts)


if __name__ == "__main__":
    unittest.main()
