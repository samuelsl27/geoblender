# SPDX-License-Identifier: GPL-3.0-or-later
"""Límites… (spec 012, T22; HU-012-1; RF-012-01, RF-012-02, RF-012-05, RF-012-15, RF-012-28;
plan 012 §5.3.4, §5.5, D-14, D-31, D-38).

- RF-012-01, RF-012-02 (HU-012-1): la ventana de ``geoblender.core_edit_limits``
  (``GEOBLENDER_PT_core_limits``) ofrece las capas de polígonos del proyecto (no las de puntos) y
  declara el límite legal con dos capas unidas y el perímetro de actuación con su motivo, su
  decisor, su fecha y el resguardo hacia dentro (``geoblender.core_declare_limits``): una
  ``core.edit_constraints`` por capa, con las restricciones del tipo que toca, su geometría
  bit a bit, su origen (la entrada y la entidad) y sus parámetros (el resguardo del límite legal y
  «activa» de los tres), sin tocar las capas de origen. Lo que no está completo se rechaza sin
  escribir nada.
- RF-012-05, RF-012-15: el informe de los límites al declararlos (y al abrir la ventana), en la
  versión activa: el límite legal, el perímetro, su intersección y la franja con m² y ha, la
  parte de la franja con su centro absoluto y «Ir a», y lo que queda fuera de la rejilla; sin
  perímetro, el límite legal hace de perímetro.
- «Ir a» (``geoblender.core_go_to_place``) encuadra la Vista 3D en ese lugar (coordenadas
  absolutas en texto, nunca en ``FloatProperty``: ADR-0005).
- RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO, la orden y lo que
  escribe su ventana están desactivados con su motivo. Las tres órdenes pasan a la entrada
  «012» del catálogo.

Un proyecto por clase (rejilla de 48 × 40 celdas de 5 m) y la extensión sin importar otra vez
(``blender_ext.release``; RNF-001-01). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
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
EDIT = "geoblender.core_edit_limits"
DECLARE = "geoblender.core_declare_limits"
GO_TO = "geoblender.core_go_to_place"
OTHERS: tuple[str, ...] = ()  # ninguna: la T28 entregó la última orden provisional de la 012
PANEL = "GEOBLENDER_PT_core_limits"
WM_PROPERTY = "geoblender_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M = 240.0
HEIGHT_M = 200.0
STEP_M = 5.0
REASON = "Concesión según el título minero de la prueba"
PERSON = "Samuel (IMGA)"
DATE_TEXT = "31/10/2026"
INWARD = "10"
OP_LAYERS = "gis.test_layers"
EDIT_TYPE = "core.edit_constraints"
# Locales desde (WEST, SOUTH): dos concesiones contiguas de 100 × 200 m (el límite legal, 4 ha),
# y el perímetro de 200 × 200 m que sale 50 m por el este (la franja de 1 ha) y 10 m de la
# ventana (2.000 m² fuera de la rejilla).
LAYERS = {
    "Concesion oeste": ("Concesión oeste", (0.0, 0.0, 100.0, 200.0)),
    "Concesion este": ("Concesión este", (100.0, 0.0, 200.0, 200.0)),
    "Perimetro": ("Perímetro de la obra", (50.0, 0.0, 250.0, 200.0)),
}
LEGAL_NAMES = ("gis_fea_concesion_oeste", "gis_fea_concesion_este")
PERIMETER_NAME = "gis_fea_perimetro"
POINTS_NAME = "gis_fea_torres"
STRIP_CENTRE_LOCAL = (225.0, 100.0)
STRIP_M2 = 10_000.0


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


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


def view3d_areas() -> list[bpy.types.Area]:
    return [area for area in window().screen.areas if area.type == "VIEW_3D"]


def main_region(area: bpy.types.Area) -> bpy.types.Region:
    return next(region for region in area.regions if region.type == "WINDOW")


@contextmanager
def in_view(area: bpy.types.Area) -> Any:
    """El contexto de una Vista 3D (como un botón de una ventana lanzado desde ella)."""
    with bpy.context.temp_override(window=window(), area=area, region=main_region(area)):
        yield


class ConstraintsLimitsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 activa en la sesión y tres capas de
    polígonos y una de puntos importadas como entidades, para toda la clase (las pruebas, en el
    orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r22-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.ps = _module("bl.scene.project_session")
        cls.core_ops = _module("bl.ops.core_constraints")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.cstore = _module("core.constraints.store")
        cls.cmodel = _module("core.constraints.model")
        cls.cparams = _module("core.constraints.params")
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
            cls.v01, _revision = store.create_version(conn, cls.project, feature="limites",
                                                      title="Límites", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        sources = folder / "fuentes"
        sources.mkdir()
        cls.names = {}
        for layer, (value, box) in LAYERS.items():
            cls.names[layer] = cls.import_layer(sources, layer, "POLYGON",
                                                [(1, value, rectangle(*box))])
        cls.names["Torres"] = cls.import_layer(sources, "Torres", "POINT",
                                               [(1, "Torre 14", np.array([WEST + 60.0,
                                                                          SOUTH + 60.0]))])
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @classmethod
    def import_layer(cls, folder: Path, name: str, geometry: str,
                     features: list[tuple[int, str, np.ndarray]]) -> str:
        """«Capas vectoriales…» de la 006 con el papel «Entidades», sin su trabajo (como
        ``Importer.layer`` de la 012): la capa ``name`` de un GeoPackage fuera del proyecto con
        una entidad de ``geometry`` por cada ``(fid, nombre, coordenadas)``; el nombre de su
        dato (``gis_fea_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        path = folder / f"{name}.gpkg"
        conn = sqlite3.connect(path)
        try:
            _module("core.gpkg.base").create_base(conn, crs)
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                         'NULL, geom GEOMETRY, "nombre" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (name, name, crs.epsg))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, geometry, crs.epsg))
            encode = _module("core.gpkg.wkb").encode_geometry
            for fid, value, coords in features:
                shape = [coords] if geometry == "POLYGON" else coords
                conn.execute(f'INSERT INTO "{name}" VALUES (?, ?, ?)',
                             (fid, encode(geometry, shape, crs.epsg, False), value))
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

    def stored(self) -> tuple[Any, ...]:
        """Las restricciones guardadas en el proyecto."""
        with self.project.read() as conn:
            return self.cstore.read_constraints(conn)

    def count(self) -> tuple[int, int]:
        """(operaciones, restricciones) del proyecto: lo que un rechazo no cambia."""
        return (self.rows("SELECT count(*) FROM gb_operation")[0][0], len(self.stored()))

    def open_window(self) -> Any:
        """«Límites…» con su ventana sustituida (en ``blender -b``, ``wm.call_panel`` cierra
        Blender): la vista, leída del proyecto."""
        with mock.patch.object(self.core_ops, "_call_panel",
                               return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.core_edit_limits(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view()

    def fill_form(self, *, legal: tuple[str, ...] = (), perimeter: str = "",
                  name_field: str = "nombre", reason: str = REASON, decider: str = PERSON,
                  date_text: str = DATE_TEXT, inward: str = INWARD) -> Any:
        """Rellena el formulario de la ventana abierta."""
        view = self.view()
        for item in view.limit_layers:
            item.legal = item.name in legal
            item.perimeter = item.name == perimeter
        view.limit_name_field = name_field
        view.limit_reason = reason
        view.limit_decided_by = decider
        view.limit_decided_on = date_text
        view.limit_inward = inward
        return view

    def refused(self, **form: Any) -> str:
        """Lanza «Declarar los límites» con ``form`` y devuelve su rechazo; no escribe nada."""
        before = self.count()
        self.fill_form(**form)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_declare_limits()
        self.assertEqual(self.count(), before)
        return str(caught.exception)

    def texts(self) -> list[str]:
        return [line.text for line in self.view().limit_lines]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_three_commands_are_real_and_in_the_012_entry(self) -> None:
        """RF-012-28, D-38: «Límites…» y sus dos órdenes internas (declarar, «Ir a») tienen su
        clase real y están en la entrada «012» del catálogo (la primera, con su fila de
        Diseño ▸ Límites y restricciones; las otras, internas); «Límites…» lanza
        ``core.edit_constraints``. Las demás de R-32 siguen siendo provisionales."""
        cat = self.commands.catalog()
        aware = self.session.ProvenanceAwareOperator
        for idname in (EDIT, DECLARE, GO_TO):
            with self.subTest(orden=idname):
                self.assertEqual(cat.commands[idname].entry, ENTRY)
                cls = self.commands.registered_class(idname)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls.bl_label, (cat.commands[idname].label,
                                             cat.commands[idname].label_es))
        self.assertEqual((cat.commands[EDIT].kind, cat.commands[EDIT].action), ("operator", "P"))
        for idname in (DECLARE, GO_TO):
            self.assertEqual(cat.commands[idname].kind, "internal")
        for idname in (EDIT, DECLARE):
            cls = self.commands.registered_class(idname)
            self.assertTrue(issubclass(cls, aware), idname)
            self.assertEqual(cls.provenance_op_type, EDIT_TYPE)
        design = cat.menus["GEOBLENDER_MT_ui_design"]
        self.assertEqual(design.groups[0].items[0].key, EDIT)
        for idname in OTHERS:
            with self.subTest(sigue_provisional=idname):
                self.assertEqual(cat.commands[idname].entry, "R-32")
                self.assertTrue(self.commands.is_provisional(
                    self.commands.registered_class(idname)))

    def test_b_the_window_offers_the_polygon_layers(self) -> None:
        """HU-012-1, plan §5.5: la ventana lee del proyecto las capas de polígonos (tres, no la
        de puntos), la fecha de hoy y, sin límites declarados, lo dice; dibuja una fila por capa
        con sus dos casillas, los campos del formulario y «Declarar los límites», activo."""
        view = self.open_window()
        self.assertEqual(sorted(item.name for item in view.limit_layers),
                         sorted((*LEGAL_NAMES, PERIMETER_NAME)))
        self.assertNotIn(self.names["Torres"], [item.name for item in view.limit_layers])
        self.assertTrue(re.fullmatch(r"\d\d/\d\d/\d{4}", view.limit_decided_on),
                        view.limit_decided_on)
        self.assertEqual(self.texts(), ["No hay ningún límite legal activo: elija sus capas "
                                        "más abajo"])
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        shown = layout.texts()
        for name in sorted((*LEGAL_NAMES, PERIMETER_NAME)):
            self.assertIn(name, shown)
        targets = [item.target for item in layout.of_kind("prop")]
        self.assertEqual(targets.count("legal"), 3)
        self.assertEqual(targets.count("perimeter"), 3)
        for name in ("limit_name_field", "limit_reason", "limit_decided_by",
                     "limit_decided_on", "limit_inward"):
            self.assertIn(name, targets)
        (button,) = [item for item in layout.of_kind("operator") if item.target == DECLARE]
        self.assertTrue(button.enabled)
        self.assertEqual(layout.of_kind("operator")[-1].target, DECLARE)

    def test_c_declare_the_limits_from_two_layers_and_a_perimeter(self) -> None:
        """RF-012-01, RF-012-02, HU-012-1: el límite legal con dos capas unidas y el perímetro
        con su motivo, su decisor, su fecha y 10 m hacia dentro crean sus tres restricciones
        (una ``core.edit_constraints`` por capa): del tipo que toca, con su nombre del campo, su
        geometría bit a bit y su origen (la entrada y la entidad), el resguardo del límite legal
        y «activa» de los tres como parámetros del proyecto, y las capas de origen sin
        cambiar."""
        self.open_window()
        origin = {name: self.rows("SELECT uid, input_uid, content_sha256 FROM gb_dataset WHERE "
                                  "name = ?", name)[0]
                  for name in (*LEGAL_NAMES, PERIMETER_NAME)}
        before = self.count()
        self.fill_form(legal=LEGAL_NAMES, perimeter=PERIMETER_NAME)
        self.assertEqual(bpy.ops.geoblender.core_declare_limits(), {"FINISHED"})
        self.assertEqual(self.count(), (before[0] + 3, before[1] + 3))

        found = {item.code: item for item in self.stored()}
        self.assertEqual(sorted(found), ["concesion_este", "concesion_oeste",
                                         "perimetro_de_la_obra"])
        types = self.cmodel.ConstraintType
        wanted = {"concesion_oeste": ("Concesión oeste", types.LEGAL_LIMIT, LEGAL_NAMES[0],
                                      "Concesion oeste"),
                  "concesion_este": ("Concesión este", types.LEGAL_LIMIT, LEGAL_NAMES[1],
                                     "Concesion este"),
                  "perimetro_de_la_obra": ("Perímetro de la obra", types.ACTION_PERIMETER,
                                           PERIMETER_NAME, "Perimetro")}
        store = self.params.ParameterStore(self.project)
        for code, (name, ctype, layer, key) in wanted.items():
            with self.subTest(restriccion=code):
                row = found[code]
                self.assertEqual((row.name, row.ctype, row.kind.value, row.reason,
                                  row.decided_by, row.decided_on.isoformat(), row.source_fid,
                                  row.source_input, row.priority),
                                 (name, ctype, "polygon", REASON, PERSON, "2026-10-31", 1,
                                  origin[layer][1], 0))
                box = LAYERS[key][1]
                self.assertTrue(np.array_equal(row.parts[0][0], rectangle(*box)))
                active = store.get(self.cparams.active_key(code))
                self.assertEqual((active.value, str(active.kind.name), active.decided_by),
                                 (True, "ADOPTADO", PERSON))
                inward = store.get(self.cparams.buffer_in_key(code))
                if ctype is types.LEGAL_LIMIT:
                    self.assertEqual((inward.value, inward.decided_by, inward.reason),
                                     (10.0, PERSON, REASON))
                else:
                    self.assertIsNone(inward)
        # Tres operaciones hechas, cada una con su capa como entrada «source».
        done = self.rows("SELECT uid, status, settings FROM gb_operation WHERE op_type = ? "
                         "ORDER BY started_at, uid", EDIT_TYPE)
        self.assertEqual([status for _uid, status, _settings in done], ["done"] * 3)
        used = []
        for uid, _status, settings in done:
            ((role, layer),) = self.rows(
                "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
                "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)
            self.assertEqual(role, "source")
            used.append(layer)
            self.assertEqual(json.loads(settings)["created"], 1)
        self.assertEqual(sorted(used), sorted((*LEGAL_NAMES, PERIMETER_NAME)))
        # Las capas de origen, igual (D-17).
        for name, (uid, _input, digest) in origin.items():
            self.assertEqual(self.rows("SELECT uid, content_sha256 FROM gb_dataset WHERE "
                                       "name = ?", name), [(uid, digest)])

    def test_d_the_report_of_the_limits(self) -> None:
        """RF-012-05, RF-012-15, D-12: al declararlos, la ventana enseña el límite legal (4 ha,
        40.000 m²), su resguardo, el perímetro, su intersección (3 ha) y la franja de 1 ha en una
        parte con su centro absoluto y «Ir a» (con las coordenadas en texto), y lo que queda
        fuera de la rejilla (2.000 m² del perímetro); las mismas cifras sin abrir de nuevo."""
        view = self.view()
        lines = list(view.limit_lines)
        centre_x, centre_y = (WEST + STRIP_CENTRE_LOCAL[0], SOUTH + STRIP_CENTRE_LOCAL[1])
        expected = [
            f"Límite legal {number(4, 2)} ha ({number(40000, 0)} m²)",
            "Resguardo hacia dentro del límite legal: 10 m",
            f"Perímetro de actuación {number(4, 2)} ha ({number(40000, 0)} m²)",
            f"Intersección {number(3, 2)} ha ({number(30000, 0)} m²)",
            f"Franja de solo relleno {number(1, 2)} ha ({number(10000, 0)} m²) en 1 parte",
            f"{number(STRIP_M2, 0)} m² en ({number(centre_x, 1)}; {number(centre_y, 1)})",
            f"Perímetro de la obra: {number(2000, 0)} m² fuera de la rejilla del proyecto",
        ]
        self.assertEqual([line.text for line in lines], expected)
        self.assertEqual([bool(line.x) for line in lines],
                         [False, False, False, False, False, True, False])
        self.assertEqual([line.alert for line in lines],
                         [False, False, False, False, False, False, True])
        place = lines[5]
        self.assertEqual((float(place.x), float(place.y)), (centre_x, centre_y))
        self.assertGreaterEqual(float(place.radius), 25.0)
        # Lo mismo al volver a abrir la ventana (lo lee del proyecto), y dibujado con «Ir a».
        self.open_window()
        self.assertEqual(self.texts(), expected)
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        shown = layout.texts()
        for text in expected:
            self.assertIn(text, shown)
        (goto,) = [item for item in layout.of_kind("operator") if item.target == GO_TO]
        self.assertEqual((goto.properties.x, goto.properties.y, goto.properties.radius),
                         (place.x, place.y, place.radius))
        self.assertTrue(goto.enabled)
        # «Ir a» en su propia fila, y la línea de la parte entera encima de él (T46).
        self.assertEqual([item.kind for item in layout.items if item.layout is goto.layout],
                         ["operator"])
        self.assertEqual(layout.items[layout.items.index(goto) - 1].text, expected[5])
        outside =[item for item in layout.of_kind("label") if "fuera de la rejilla" in item.text]
        self.assertTrue(outside)
        self.assertTrue(all(item.alert for item in outside))

    def test_e_go_to_frames_the_part_of_the_strip(self) -> None:
        """RF-012-05: «Ir a» centra la Vista 3D de destino en el centro de la parte de la franja
        (absoluto → local con el GeoOrigin, en float64) con la distancia que deja entera su
        zona; sin ninguna Vista 3D, no se puede y el mensaje lo dice; las coordenadas no son
        números (se rechaza el texto)."""
        views = _module("bl.ui.views")
        for obj in list(bpy.context.scene.objects):  # sin objetos: la cota es la del cursor
            bpy.data.objects.remove(obj)
        project = self.ps.current()
        origin = project.origin
        (line,) = [line for line in self.view().limit_lines if line.x]
        area = view3d_areas()[0]
        space, rv3d, region = area.spaces.active, area.spaces.active.region_3d, main_region(area)
        rv3d.view_location = (0.0, 0.0, 0.0)
        rv3d.view_distance = 1.0
        space.clip_start, space.clip_end = 0.01, 1000.0
        with in_view(area):
            self.assertEqual(bpy.ops.geoblender.core_go_to_place(
                x=line.x, y=line.y, radius=line.radius), {"FINISHED"})
        self.assertAlmostEqual(rv3d.view_location.x, float(line.x) - origin.x0, places=3)
        self.assertAlmostEqual(rv3d.view_location.y, float(line.y) - origin.y0, places=3)
        # La esfera que contiene el cuadro de lado 2 r y la cota del cursor ± 50 m (sin objetos).
        radius = float(line.radius)
        sphere = (2.0 * radius ** 2 + 50.0 ** 2) ** 0.5
        wanted = views.frame_distance(sphere, ortho=rv3d.view_perspective == "ORTHO",
                                      lens=space.lens, width=region.width, height=region.height)
        self.assertAlmostEqual(rv3d.view_distance, wanted, places=3)
        self.assertLessEqual(space.clip_end / space.clip_start, 1e5 * (1 + 1e-6))
        self.assertGreater(space.clip_end, 2 * rv3d.view_distance)
        with in_view(area), self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_go_to_place(x="no", y=line.y, radius=line.radius)
        self.assertIn("«no»", str(caught.exception))
        for each in view3d_areas():
            each.type = "OUTLINER"
            self.addCleanup(setattr, each, "type", "VIEW_3D")
        with self.assertRaisesRegex(RuntimeError, "Vista 3D"):
            bpy.ops.geoblender.core_go_to_place(x=line.x, y=line.y, radius=line.radius)

    def test_f_a_form_that_is_not_complete_is_refused_and_writes_nothing(self) -> None:
        """RF-012-02, RF-012-04: sin capas, con una capa a la vez de límite legal y de perímetro,
        con dos perímetros, sin motivo, sin decisor, con una fecha que no lo es, sin resguardo
        o con uno que no vale, o con un campo del nombre que la capa no tiene, se rechaza con su
        motivo, antes de crear nada (ni una operación); una capa que ya está declarada como lo
        mismo, también. Un perímetro solo no pide resguardo."""
        self.open_window()
        self.assertIn("Elija", self.refused())
        self.assertIn(f"«{LEGAL_NAMES[0]}»", self.refused(legal=(LEGAL_NAMES[0],),
                                                          perimeter=LEGAL_NAMES[0]))
        view = self.fill_form()
        for item in view.limit_layers:
            item.perimeter = True
        before = self.count()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_declare_limits()
        self.assertIn("un solo perímetro", str(caught.exception))
        self.assertEqual(self.count(), before)
        legal = (LEGAL_NAMES[0],)
        self.assertIn("motivo", self.refused(legal=legal, reason="  "))
        self.assertIn("quién decide", self.refused(legal=legal, decider=""))
        self.assertIn("«31-10»", self.refused(legal=legal, date_text="31-10"))
        for typed in ("", "-2", "mucho", "3 kg"):
            with self.subTest(resguardo=typed):
                self.assertIn("resguardo hacia dentro", self.refused(legal=legal, inward=typed))
        text = self.refused(legal=legal, name_field="no_existe")
        self.assertIn("«no_existe»", text)
        self.assertIn("«nombre»", text)  # los campos que sí tiene la capa
        # Una capa que ya está declarada como lo mismo no se declara otra vez.
        text = self.refused(legal=legal)
        self.assertIn(f"«{LEGAL_NAMES[0]}» ya está declarada como Límite legal", text)
        text = self.refused(perimeter=PERIMETER_NAME)
        self.assertIn(f"«{PERIMETER_NAME}» ya está declarada como Perímetro de actuación", text)
        # Un perímetro solo no pide el resguardo del límite legal; con él, en metros.
        self.fill_form(perimeter=PERIMETER_NAME, inward="")
        request = self.core_ops.limits_request(self.view())
        self.assertEqual((request.legal, request.perimeter, request.inward_m),
                         ((), PERIMETER_NAME, None))
        self.fill_form(legal=legal, inward="2,5 m")
        self.assertEqual(self.core_ops.limits_request(self.view()).inward_m, 2.5)

    def test_g_the_report_follows_the_active_version(self) -> None:
        """RF-012-05, D-4, D-14: el perímetro desactivado solo en V02 (su «activa» de versión):
        en V02 la ventana dice que el límite legal hace de perímetro (sin franja) y que el
        perímetro no está activo en V02; en V01 no cambia."""
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        store = self.params.ParameterStore(self.project)
        key = self.cparams.active_key("perimetro_de_la_obra")
        with self.project.write_transaction() as conn:
            store.create(conn, key, False, kind="ADOPTADO", source=PERSON, source_kind="person",
                         decided_by=PERSON, reason=REASON, version=self.v02.code)
        self.open_window()
        self.assertEqual(self.texts(), [
            f"Límite legal {number(4, 2)} ha ({number(40000, 0)} m²)",
            "Resguardo hacia dentro del límite legal: 10 m",
            "No hay perímetro de actuación: se toma como perímetro el límite legal",
            "«Perímetro de la obra» (Perímetro de actuación) no está activo en V02",
        ])
        self.set_active(self.v01)
        self.open_window()
        self.assertEqual(len(self.texts()), 7)

    def test_h_unavailable_without_a_project_read_only_or_superseded(self) -> None:
        """RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO, «Límites…»
        y «Declarar los límites» no están disponibles y dicen por qué (también en su
        descripción); la ventana abierta lo dice y dibuja desactivado lo que escribe. «Ir a» solo
        lee: sigue disponible."""
        edit = self.commands.registered_class(EDIT)
        declare = self.commands.registered_class(DECLARE)
        self.assertTrue(bpy.ops.geoblender.core_edit_limits.poll())
        self.assertTrue(bpy.ops.geoblender.core_declare_limits.poll())

        with mock.patch.object(self.session.SESSION, "_project", None):
            self.assertEqual(self.session.write_unavailable(), "Abra un proyecto")
            self.assertFalse(bpy.ops.geoblender.core_edit_limits.poll())
            self.assertFalse(bpy.ops.geoblender.core_declare_limits.poll())

        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.core_edit_limits.poll())
            self.assertFalse(bpy.ops.geoblender.core_declare_limits.poll())
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            self.assertIn(reason, layout.texts())
            for button in [item for item in layout.of_kind("operator")
                           if item.target == DECLARE]:
                self.assertFalse(button.enabled)
            for item in layout.of_kind("prop"):
                self.assertFalse(item.enabled, item.target)
        self.assertTrue(bpy.ops.geoblender.core_edit_limits.poll())

        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        note = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(bpy.ops.geoblender.core_edit_limits.poll())
        self.assertFalse(bpy.ops.geoblender.core_declare_limits.poll())
        for cls in (edit, declare):
            self.assertIn(note, cls.description(bpy.context, SimpleNamespace()))
        self.set_active(self.v01)
        self.assertTrue(bpy.ops.geoblender.core_edit_limits.poll())
        self.assertIsInstance(draw(getattr(bpy.types, PANEL), bpy.context), FakeLayout)


if __name__ == "__main__":
    unittest.main()
