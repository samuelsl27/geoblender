# SPDX-License-Identifier: GPL-3.0-or-later
"""Intenciones del cliente… (spec 012, T25; HU-012-6; RF-012-26, RF-012-27, RF-012-28; plan 012
§5.3.3, §5.3.4, §5.5, D-8).

- RF-012-26 (``geoblender.core_save_client_marks``): las marcas de una capa «entidades» del
  proyecto se guardan como intenciones con su rol (un campo con su correspondencia, o uno para
  todas), su cota si el rol la pide, su fecha (un campo o una fija), su documento de origen (una
  entrada de tipo documento) y la decisión enlazada; sin campo del nombre, el de la capa; las
  entidades que no sirven se rechazan con su motivo; todo lo que no vale se rechaza antes de
  escribir nada. Una marca **no cambia ninguna máscara**: las de V01 siguen al día y son las
  mismas. Se ven en la vista (``core_intention`` cargado: un objeto ``CLIENT_INTENTION`` por
  intención, con un estilo propio, en coordenadas locales que vuelven a las absolutas) sin
  escribir nada en el proyecto.
- RF-012-27 (``geoblender.core_convert_intention``): «Convertir en restricción…» crea la
  restricción con el tipo, el motivo y el decisor que se declaran, enlazada a la intención, que no
  cambia (sus filas, iguales); las máscaras, que no cambiaban, pasan a obsoletas y, compiladas, la
  cambian. La restricción hereda la decisión de la propiedad de la intención (T41).
- RF-012-02, RF-012-19 (T41; ``geoblender.core_create_constraints`` y
  ``geoblender.core_complete_constraint``): un campo opcional «Decisión de la propiedad» (entre las
  del proyecto, como en «Intenciones del cliente…») en «Desde una capa…» (la misma para todas las
  que crea) y en «Completar…» (vacío: se queda la que tiene); una que no está en el proyecto se
  rechaza sin escribir nada; la ventana y la barra N «Restricción» la enseñan como se lee
  («15/09/2025 · quién: qué») y no por su identificador.
- RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO las órdenes están
  desactivadas con su motivo; «Intenciones del cliente…» pasa a la entrada «012».

Un proyecto por clase (rejilla de 24 × 20 celdas de 5 m) y la extensión sin importar otra vez
(RNF-001-01). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import datetime as dt
import importlib
import shutil
import sqlite3
import tempfile
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
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.trees import remove_tree

ENTRY = "012"
EDIT = "geoblender.core_edit_client_marks"
SAVE = "geoblender.core_save_client_marks"
CONVERT = "geoblender.core_convert_intention"
LOAD = "geoblender.core_load_into_view"
ADD_DECISION = "geoblender.core_add_decision"
REAL = (EDIT, SAVE, CONVERT)
EDIT_TYPE = "core.edit_intentions"
CONSTRAINT_TYPE = "core.edit_constraints"
PANEL = "GEOBLENDER_PT_core_marks"
LIST = "GEOBLENDER_UL_core_intentions"
WM_PROPERTY = "geoblender_constraints"
KIND = "CLIENT_INTENTION"
PREFIX = "core_intention"
DOCUMENT = "Acta_cliente"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data" / "core" / "provenance"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M = 120.0
HEIGHT_M = 100.0
STEP_M = 5.0
LEGAL_BOX = (0.0, 0.0, 100.0, 100.0)
REASON = "Prueba de las intenciones del cliente de la 012"
PERSON = "Samuel (IMGA)"
DECISION_WHAT = "Marcas del cliente para el diseño"
DECISION_TEXT = f"15/09/2025 · {PERSON}: {DECISION_WHAT}"
MARK_DATE = "12/09/2025"
CONVERT_REASON = "La propiedad pide rellenar la hondonada"
DATE_TEXT = "20/09/2025"
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada de la vista (RNF-012-06)."""
POND_BOX = (60.0, 10.0, 80.0, 30.0)
HOLLOW_BOX = (30.0, 60.0, 50.0, 80.0)
MARKS = (
    # (fid, rol, nombre, cota, caja local)
    (2, "Rellenar", "Hondonada", "", HOLLOW_BOX),
    (3, "Explotar a una cota", "Plaza de cantera", "612,5", (10.0, 10.0, 30.0, 30.0)),
    (5, "Plataforma", "Plataforma de acopio", "", (60.0, 60.0, 90.0, 90.0)),
    (7, "Explotar a una cota", "Corta sin cota", " ", (40.0, 35.0, 55.0, 50.0)),
    (8, "Vallar", "Desconocida", "", (35.0, 90.0, 45.0, 98.0)),
    (9, "Proteger", "Balsa a proteger", "", POND_BOX),
)
"""Las marcas de la capa de polígonos: cuatro buenas y dos malas (sin cota y un rol que no es)."""
WALLS = ((1, "Conservar como está", "Muro de piedra", ((5.0, 50.0), (45.0, 50.0), (45.0, 55.0))),
         (2, "Talud a tratar", "Talud norte", ((10.0, 95.0), (90.0, 95.0))))
HERMITAGE_LOCAL = (95.0, 45.0)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def rectangle(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local dado."""
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def path(points: tuple[tuple[float, float], ...]) -> np.ndarray:
    return np.array([(WEST + x, SOUTH + y) for x, y in points], dtype=np.float64)


def number(value: float, decimals: int) -> str:
    """Un número como lo escribe la interfaz en español (espacio fino de miles, coma)."""
    return _module("core.i18n").format_number(value, decimals)


class ConstraintsIntentionsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, el límite legal declarado,
    las máscaras compiladas, el acta del cliente (un documento) y una decisión de la propiedad,
    más tres capas de marcas importadas como entidades, para toda la clase (las pruebas, en el
    orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r25-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.folder = folder
        cls.ps = _module("bl.scene.project_session")
        cls.core_ops = _module("bl.ops.core_constraints")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.cstore = _module("core.constraints.store")
        cls.cmodel = _module("core.constraints.model")
        cls.access = _module("gis.masks.access")
        cls.views = _module("bl.scene.views")
        cls.constraint_views = _module("bl.scene.constraint_views")
        cls.mesh = _module("bl.scene.mesh")
        (folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + WIDTH_M, SOUTH + HEIGHT_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="marcas",
                                                      title="Marcas", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        sources = folder / "fuentes"
        sources.mkdir()
        polygons = [(fid, rectangle(*box), {"rol": role, "nombre": name, "cota": elevation,
                                            "fecha": "2025-09-12"})
                    for fid, role, name, elevation, box in MARKS]
        walls = [(fid, path(points), {"rol": role, "nombre": name, "fecha": "2025-09-12"})
                 for fid, role, name, points in WALLS]
        cls.names = {
            "Concesion": cls.import_layer(sources, "Concesion", "POLYGON", ("nombre",),
                                          [(1, rectangle(*LEGAL_BOX), {"nombre": "Concesión"})]),
            "Marcas": cls.import_layer(sources, "Marcas", "POLYGON",
                                       ("rol", "nombre", "cota", "fecha"), polygons),
            "Muros": cls.import_layer(sources, "Muros", "LINESTRING", ("rol", "nombre", "fecha"),
                                      walls),
            "Ermitas": cls.import_layer(
                sources, "Ermitas", "POINT", ("nombre",),
                [(1, np.array([WEST + HERMITAGE_LOCAL[0], SOUTH + HERMITAGE_LOCAL[1]]),
                  {"nombre": "Ermita de San Roque"})]),
        }
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {
            "FINISHED"}
        cls.document = cls.register_document()
        with cls.project.write_transaction() as conn:
            cls.decision = _module("core.versions.decisions").record_decision(
                conn, cls.project, decided_by=PERSON, decided_at="2025-09-15",
                what=DECISION_WHAT, source_input_uid=cls.document)
        with mock.patch.object(cls.core_ops, "_call_panel", return_value={"FINISHED"}):
            assert bpy.ops.geoblender.core_edit_limits() == {"FINISHED"}
        limits = getattr(bpy.context.window_manager, WM_PROPERTY)
        for item in limits.limit_layers:
            item.legal = item.name == cls.names["Concesion"]
        limits.limit_name_field = "nombre"
        limits.limit_reason = REASON
        limits.limit_decided_by = PERSON
        limits.limit_decided_on = "31/10/2026"
        limits.limit_inward = "10"
        assert bpy.ops.geoblender.core_declare_limits() == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}
        cls.masks = cls.access.load_masks(cls.project, cls.v01.uid)

    @classmethod
    def import_layer(cls, folder: Path, name: str, geometry: str, columns: tuple[str, ...],
                     features: list[tuple[int, np.ndarray, dict[str, str]]]) -> str:
        """«Capas vectoriales…» de la 006 con el papel «Entidades», sin su trabajo: la capa
        ``name`` de un GeoPackage fuera del proyecto con una entidad de ``geometry`` por cada
        ``(fid, coordenadas absolutas, atributos)``; el nombre de su dato (``gis_fea_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        file = folder / f"{name}.gpkg"
        conn = sqlite3.connect(file)
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
                conn.execute(f'INSERT INTO "{name}" VALUES (?, ?, '
                             f'{", ".join("?" for _ in columns)})',
                             (fid, encode(geometry, shape, crs.epsg, False), *values))
            conn.commit()
        finally:
            conn.close()
        inputs, gis_store, vector = (_module("core.inputs"), _module("gis.store"),
                                     _module("gis.vector"))
        reader = _module("gis.content").GPKG_LAYER
        settings = {"layer": name, "role": "features"}
        anchors = [inputs.locate_source(file, cls.project, cls.ps.userdata(), role="main")]
        prints = [_module("core.inputs.model").SourcePrint(
            _module("core.hashing").sha256_file(file), size=file.stat().st_size,
            mtime_ns=file.stat().st_mtime_ns)]
        request = reader.request(
            reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
            dict(zip(inputs.reader_roles(anchors), [file], strict=True)), settings)
        spec = gis_store.source_input(
            reader.id, name, files=anchors, file_prints=prints,
            digest=_module("core.content.readers").read_content(reader, request), crs=crs,
            vertical=vertical, settings=settings)
        copies = folder / f"copia_{name}"
        copies.mkdir()
        read = vector.read_layer(vector.copy_source(file, copies), name)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": name},
            executor="blender")
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.declare_input(spec)
            out.features(name, vector.features_from_layer(read)[0])
            (record,) = out.commit(message=REASON)
        return record.name

    @classmethod
    def register_document(cls) -> str:
        """Registra el acta del cliente (el PDF sintético de la procedencia) como entrada de tipo
        documento, con su importación (un tipo de operación de la prueba, registrado mientras
        dura la clase); devuelve su uid."""
        contract = _module("core.provenance.contract")
        inputs_model = _module("core.inputs.model")
        registry = _module("core.inputs.registry")
        builtin = _module("core.content.builtin")
        definition = contract.OperationDef("res.import_document", "1.0", "res",
                                           "Test document import", False)
        contract.register_operation(definition)
        cls.addClassCleanup(contract.unregister_operation, definition.op_type)
        pdf = cls.folder / "fuentes" / "acta_cliente.pdf"
        shutil.copyfile(DATA / "informe.pdf", pdf)
        found = pdf.stat()
        no_crs = {"not_applicable": True}
        spec = inputs_model.InputSpec(
            DOCUMENT, "document", "res", builtin.DOCUMENT.id,
            files=[registry.locate_source(pdf, cls.project, cls.ps.userdata())],
            file_prints=[inputs_model.SourcePrint(_module("core.hashing").sha256_file(pdf),
                                                  size=found.st_size, mtime_ns=found.st_mtime_ns)],
            digest=_module("core.content.readers").read_content(
                builtin.DOCUMENT, builtin.DOCUMENT.request(
                    "document", inputs_model.input_declarations(no_crs, no_crs, {}),
                    {"main": pdf})),
            crs_h=no_crs, crs_v=no_crs)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, definition.op_type, settings={}, executor="blender")
        with cls.project.write_transaction() as conn:
            record = registry.register_input(conn, cls.project, spec, operation_uid=handle.uid)
            handle.complete(conn)
        return str(record.uid)

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

    def count(self) -> tuple[int, int, int]:
        """(operaciones, restricciones, intenciones): lo que un rechazo no cambia."""
        with self.project.read() as conn:
            return (conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0],
                    len(self.cstore.read_constraints(conn)),
                    len(self.cstore.read_intentions(conn)))

    def refused(self, command: Any, **values: Any) -> str:
        """El error de ``command`` desde un guion (``RuntimeError``) sin que cambie el
        proyecto."""
        before = self.count()
        with self.assertRaises(RuntimeError) as caught:
            command(**values)
        self.assertEqual(self.count(), before)
        return str(caught.exception)

    def open_window(self) -> Any:
        """«Intenciones del cliente…» con su ventana sustituida (en ``blender -b``,
        ``wm.call_panel`` cierra Blender): la vista, leída del proyecto."""
        with mock.patch.object(self.core_ops, "_call_panel", return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.core_edit_client_marks(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view()

    def texts(self) -> list[str]:
        return [line.text for line in self.view().mark_lines]

    def form(self, **values: Any) -> None:
        """Rellena el formulario de la ventana: los campos que se dan, y los demás, vacíos."""
        view = self.view()
        blank = {"mark_layer": "", "mark_role": "FIELD", "mark_role_field": "",
                 "mark_role_values": "", "mark_name_field": "", "mark_elevation_field": "",
                 "mark_elevation": "", "mark_date_field": "", "mark_date": MARK_DATE,
                 "mark_document": "", "mark_decision": ""}
        for key, value in {**blank, **values}.items():
            setattr(view, key, value)

    def marks_form(self, **values: Any) -> dict[str, Any]:
        """Lo que se rellena para las marcas de polígonos con su rol, nombre, cota y fecha de
        sus campos, el acta y la decisión."""
        return {"mark_layer": self.names["Marcas"], "mark_role_field": "rol",
                "mark_name_field": "nombre", "mark_elevation_field": "cota",
                "mark_date": "", "mark_date_field": "fecha", "mark_document": DOCUMENT,
                "mark_decision": DECISION_TEXT, **values}

    def operators(self, target: str) -> list[Any]:
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        return [item for item in layout.of_kind("operator") if item.target == target]

    def stored(self) -> dict[str, Any]:
        """Las intenciones guardadas, por nombre."""
        with self.project.read() as conn:
            return {item.name: item for item in self.cstore.read_intentions(conn)}

    def constraints(self) -> dict[str, Any]:
        with self.project.read() as conn:
            return {item.code: item for item in self.cstore.read_constraints(conn)}

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_are_real_and_in_the_012_entry(self) -> None:
        """RF-012-28, D-31, D-38: «Intenciones del cliente…» y las dos internas (guardar las
        marcas y convertir) tienen su clase real y están en la entrada «012»; las que registran
        una operación lo hacen con su tipo; el cargador de ``core_intention`` está registrado y
        «Verificar un diseño por recinto…» sigue provisional."""
        cat = self.commands.catalog()
        aware = self.session.ProvenanceAwareOperator
        for idname in REAL:
            with self.subTest(orden=idname):
                self.assertEqual(cat.commands[idname].entry, ENTRY)
                cls = self.commands.registered_class(idname)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls.bl_label, (cat.commands[idname].label,
                                             cat.commands[idname].label_es))
                self.assertTrue(issubclass(cls, aware))
        self.assertEqual((cat.commands[EDIT].kind, cat.commands[EDIT].action),
                         ("operator", "P"))
        for idname in (SAVE, CONVERT):
            self.assertEqual(cat.commands[idname].kind, "internal")
        for idname, op_type in ((EDIT, EDIT_TYPE), (SAVE, EDIT_TYPE), (CONVERT,
                                                                       CONSTRAINT_TYPE)):
            self.assertEqual(self.commands.registered_class(idname).provenance_op_type, op_type)
        loader = self.views.loader_for(PREFIX)
        self.assertEqual((loader.prefix, loader.kind), (PREFIX, KIND))
        last = "geoblender.res_verify_constraints"  # la T28 la entregó: ya no es provisional
        self.assertEqual(cat.commands[last].entry, "012")
        self.assertFalse(self.commands.is_provisional(self.commands.registered_class(last)))

    def test_b_the_window_offers_the_layers_the_documents_and_the_decisions(self) -> None:
        """RF-012-26: la ventana ofrece las capas «entidades» del proyecto con su geometría, el
        acta como documento y la decisión de la propiedad con su fecha, quién y qué; sin
        intenciones guardadas, lo dice; dibuja «Guardar las marcas» y no «Ver en la Vista 3D»."""
        view = self.open_window()
        self.assertEqual({item.name: item.kind for item in view.mark_layers}, {
            self.names["Concesion"]: "polygon", self.names["Marcas"]: "polygon",
            self.names["Muros"]: "line", self.names["Ermitas"]: "point"})
        self.assertEqual([(item.name, item.uid) for item in view.mark_documents],
                         [(DOCUMENT, self.document)])
        self.assertEqual([(item.name, item.uid) for item in view.mark_decisions],
                         [(DECISION_TEXT, self.decision.uid)])
        self.assertEqual(len(view.intentions), 0)
        self.assertEqual(view.mark_role, "FIELD")
        self.assertRegex(view.mark_date, r"^\d{2}/\d{2}/\d{4}$")
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        texts = layout.texts()
        self.assertTrue(any("Aún no hay intenciones del cliente" in text for text in texts),
                        texts)
        self.assertEqual(len(self.operators(SAVE)), 1)
        self.assertTrue(self.operators(SAVE)[0].enabled)
        self.assertEqual(self.operators(LOAD), [])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   EDIT_TYPE)[0][0], 0)

    def test_c_the_form_is_checked_before_anything_is_written(self) -> None:
        """RF-012-26: sin capa, sin campo del rol, con una correspondencia que no se lee, una cota
        o una fecha que no lo son, sin documento o con uno que no está, o con una decisión que no
        está, se rechaza con su motivo sin registrar nada; un campo que la capa no tiene, también
        (con los que sí tiene), y un documento que no lo es (la capa)."""
        self.open_window()
        save = bpy.ops.geoblender.core_save_client_marks
        self.form()
        self.assertIn("capa", self.refused(save))
        self.form(**self.marks_form(mark_role_field=""))
        self.assertIn("campo del papel", self.refused(save))
        self.form(**self.marks_form(mark_role_values="Vallar"))
        self.assertIn("«Vallar»", self.refused(save))
        self.form(**self.marks_form(mark_elevation="612"))
        self.assertIn("no los dos", self.refused(save))
        self.form(**self.marks_form(mark_date_field="", mark_date="ayer"))
        self.assertIn("«ayer»", self.refused(save))
        self.form(**self.marks_form(mark_date_field="", mark_date=""))
        self.assertIn("fecha", self.refused(save))
        self.form(**self.marks_form(mark_document=""))
        self.assertIn("documento", self.refused(save))
        self.form(**self.marks_form(mark_document="Otro"))
        self.assertIn("«Otro»", self.refused(save))
        self.form(**self.marks_form(mark_decision="Una decisión que no existe"))
        self.assertIn("«Una decisión que no existe»", self.refused(save))
        self.form(**self.marks_form(mark_layer="gis_fea_no_hay"))
        self.assertIn("«gis_fea_no_hay»", self.refused(save))
        self.form(**self.marks_form(mark_role_field="papel"))
        text = self.refused(save)
        self.assertIn("«papel»", text)
        self.assertIn("«rol»", text)  # los campos que sí tiene la capa
        self.form(**self.marks_form(mark_elevation_field="nada"))
        self.assertIn("«nada»", self.refused(save))
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   EDIT_TYPE)[0][0], 0)
        # La capa de las marcas es una entrada, no un documento (lo comprueba el dominio).
        marks_input = self.rows("SELECT input_uid FROM gb_dataset WHERE name = ?",
                                self.names["Marcas"])[0][0]
        view = self.view()
        view.mark_documents.add().name = "Marcas"
        view.mark_documents[len(view.mark_documents) - 1].uid = marks_input
        self.form(**self.marks_form(mark_document="Marcas"))
        self.assertIn("tipo documento", self.refused(save))

    def test_d_save_the_marks_of_a_polygon_layer_with_their_role_document_and_decision(
            self) -> None:
        """RF-012-26: las marcas de la capa de polígonos (rol de un campo, cota del suyo, fecha
        del suyo, nombre del suyo) se guardan con ``core.edit_intentions`` (la capa y el acta
        como entradas): las cuatro buenas, con su rol, su cota solo en «explotar a una cota», su
        fecha, el acta y la decisión; las dos malas (sin cota y con un rol que no es) se
        rechazan con su entidad y su motivo; la ventana las lista y enseña la elegida."""
        self.open_window()
        self.form(**self.marks_form())
        before = self.count()
        self.assertEqual(bpy.ops.geoblender.core_save_client_marks(), {"FINISHED"})
        self.assertEqual(self.count(), (before[0] + 1, before[1], before[2] + 4))
        saved = self.stored()
        self.assertEqual(list(saved), ["Hondonada", "Plaza de cantera", "Plataforma de acopio",
                                       "Balsa a proteger"])
        marks_input = self.rows("SELECT input_uid FROM gb_dataset WHERE name = ?",
                                self.names["Marcas"])[0][0]
        for name, role, elevation, fid in (
                ("Hondonada", "fill", None, 2), ("Plaza de cantera", "mine_to_elevation", 612.5, 3),
                ("Plataforma de acopio", "platform", None, 5),
                ("Balsa a proteger", "protect", None, 9)):
            with self.subTest(marca=name):
                item = saved[name]
                self.assertEqual((item.role.value, item.elevation_m, item.kind.value,
                                  item.stated_on, item.document_input, item.decision_uid,
                                  item.source_input, item.source_fid),
                                 (role, elevation, "polygon", dt.date(2025, 9, 12),
                                  self.document, self.decision.uid, marks_input, fid))
        ((op_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ?", EDIT_TYPE)
        self.assertEqual(status, "done")
        io = {role: item for role, item in self.rows(
            "SELECT role, item_uid FROM gb_operation_io WHERE direction = 'in' AND "
            "operation_uid = ?", op_uid)}
        self.assertEqual(io["document"], self.document)
        self.assertEqual(self.rows(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = "
            "io.item_uid WHERE io.direction = 'in' AND io.role = 'source' AND "
            "io.operation_uid = ?", op_uid), [(self.names["Marcas"],)])
        # El informe y la lista de la ventana.
        texts = self.texts()
        self.assertEqual(texts[0], ("Intenciones del cliente guardadas de «marcas»: 4; "
                                    "entidades rechazadas: 2"))
        self.assertEqual(len(texts), 3)
        self.assertTrue(all(line.alert for line in list(self.view().mark_lines)[1:]))
        self.assertIn("entidad 7", texts[1])
        self.assertIn("entidad 8", texts[2])
        self.assertIn("«Vallar»", texts[2])
        view = self.view()
        self.assertEqual([(item.name, item.role, item.kind, item.elevation, item.stated_on,
                           item.document, item.source, item.decision, item.converted)
                          for item in view.intentions],
                         [("Hondonada", "fill", "polygon", "", MARK_DATE, DOCUMENT, "Marcas",
                           DECISION_TEXT, ""),
                          ("Plaza de cantera", "mine_to_elevation", "polygon", number(612.5, 1),
                           MARK_DATE, DOCUMENT, "Marcas", DECISION_TEXT, ""),
                          ("Plataforma de acopio", "platform", "polygon", "", MARK_DATE,
                           DOCUMENT, "Marcas", DECISION_TEXT, ""),
                          ("Balsa a proteger", "protect", "polygon", "", MARK_DATE, DOCUMENT,
                           "Marcas", DECISION_TEXT, "")])
        self.assertEqual([item.uid for item in view.intentions],
                         [saved[name].uid for name in saved])
        ul = getattr(bpy.types, LIST)
        row = FakeLayout()
        ul.draw_item(None, bpy.context, row, view, view.intentions[1], 0, view,
                     "intention_index")
        shown = " ".join(row.texts())
        for expected in ("Plaza de cantera", "Explotar a una cota", MARK_DATE):
            self.assertIn(expected, shown)
        view.intention_index = 1
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        every = " ".join(layout.texts())
        for expected in (f"Documento: {DOCUMENT}", f"Decisión: {DECISION_TEXT}", "Capa: Marcas",
                         f"Cota: {number(612.5, 1)} m", "Sin convertir en restricción"):
            self.assertIn(expected, every)
        (convert,) = self.operators(CONVERT)
        self.assertEqual(convert.properties.uid, saved["Plaza de cantera"].uid)
        (load,) = self.operators(LOAD)
        self.assertEqual(load.properties.datasets, PREFIX)

    def test_e_marks_of_lines_and_points_with_a_fixed_role_and_the_name_of_the_layer(
            self) -> None:
        """RF-012-26: las líneas (rol de su campo, sin cota, con su correspondencia escrita) y el
        punto (un rol para todas, la fecha fija, sin campo del nombre: el de la capa y sin
        decisión) se guardan aparte, cada capa con su ``core.edit_intentions``; la lista suma
        siete intenciones, cada una con su geometría."""
        self.open_window()
        self.form(**self.marks_form(
            mark_layer=self.names["Muros"], mark_elevation_field="",
            mark_role_values="Conservar como está = Conservar como está; Talud a tratar = "
                             "Talud a tratar", mark_decision=""))
        self.assertEqual(bpy.ops.geoblender.core_save_client_marks(), {"FINISHED"})
        self.assertEqual(self.texts()[0], ("Intenciones del cliente guardadas de «muros»: 2; "
                                           "entidades rechazadas: 0"))
        self.form(mark_layer=self.names["Ermitas"], mark_role="PROTECT", mark_date=MARK_DATE,
                  mark_document=DOCUMENT)
        self.assertEqual(bpy.ops.geoblender.core_save_client_marks(), {"FINISHED"})
        saved = self.stored()
        self.assertEqual(len(saved), 7)
        walls = {name: saved[name] for name in ("Muro de piedra", "Talud norte")}
        self.assertEqual([(item.role.value, item.kind.value, item.decision_uid)
                          for item in walls.values()],
                         [("keep_as_is", "line", None), ("slope_to_treat", "line", None)])
        self.assertTrue(np.array_equal(walls["Muro de piedra"].parts[0][0], path(WALLS[0][3])))
        hermitage = saved["ermitas"]  # sin campo del nombre: el de la capa
        self.assertEqual((hermitage.role.value, hermitage.kind.value, hermitage.stated_on,
                          hermitage.elevation_m, hermitage.decision_uid),
                         ("protect", "point", dt.date(2025, 9, 12), None, None))
        self.assertTrue(np.array_equal(hermitage.parts[0][0].reshape(-1),
                                       [WEST + HERMITAGE_LOCAL[0], SOUTH + HERMITAGE_LOCAL[1]]))
        self.assertEqual(len(self.view().intentions), 7)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                   EDIT_TYPE)[0][0], 3)
        self.assertEqual(self.rows("SELECT json_extract(settings, '$.default_name') FROM "
                                   "gb_operation WHERE op_type = ? ORDER BY started_at DESC "
                                   "LIMIT 1", EDIT_TYPE), [("ermitas",)])

    def test_f_the_marks_change_no_mask(self) -> None:
        """RF-012-26 (error 30): las marcas guardadas (también la que cae sobre un recinto) no
        cambian ninguna máscara: las de V01 siguen al día, de la misma operación y con la misma
        rejilla de clases, y la lista de restricciones no tiene ninguna."""
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual(state, self.access.MaskState.CURRENT)
        masks = self.access.load_masks(self.project, self.v01.uid)
        self.assertEqual(masks.operation_uid, self.masks.operation_uid)
        self.assertTrue(np.array_equal(masks.classes, self.masks.classes))
        self.assertTrue(np.array_equal(masks.cut_allowed(), self.masks.cut_allowed()))
        self.assertEqual(self.constraints().keys() - {"concesion"}, set())

    def test_g_load_the_marks_into_the_view_with_their_own_style(self) -> None:
        """RF-012-26: cargar ``core_intention`` en la vista crea un objeto ``CLIENT_INTENTION``
        por intención, en la colección de su dato, con el estilo de las intenciones (alambre,
        delante, su color); sus vértices vuelven a las coordenadas absolutas de la marca (z, la
        del GeoOrigin; un punto lleva además su cruz); la vista no escribe nada en el proyecto ni
        cambia las máscaras; descargarla las quita."""
        before = self.count()
        self.addCleanup(self.views.unload_datasets, [self.rows(
            "SELECT uid FROM gb_dataset WHERE name = ?", PREFIX)[0][0]])
        # Cerrar los pasos a mitad (Esc) no deja ningún objeto ni ninguna malla a medias.
        meshes = len(bpy.data.meshes)
        steps = self.views.load_steps(bpy.context, self.project, [PREFIX])
        for _ in range(3):
            next(steps)
        self.assertGreater(len(bpy.data.meshes), meshes)
        steps.close()
        self.assertEqual(len(bpy.data.meshes), meshes)
        self.assertEqual([obj.name for obj in bpy.data.objects
                          if self.constraint_views.INTENTION_PROPERTY in obj.keys()], [])
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=PREFIX), {"FINISHED"})
        self.assertEqual(self.count(), before)
        loaded = [obj for obj in bpy.data.objects if obj.geoblender.kind == KIND]
        self.assertEqual(len(loaded), 7)
        saved = self.stored()
        record_uid = self.rows("SELECT uid FROM gb_dataset WHERE name = ?", PREFIX)[0][0]
        by_uid = {obj[self.constraint_views.INTENTION_PROPERTY]: obj for obj in loaded}
        self.assertEqual(set(by_uid), {item.uid for item in saved.values()})
        origin = self.project.origin
        style = self.constraint_views.INTENTION_STYLE
        for name, item in saved.items():
            with self.subTest(marca=name):
                obj = by_uid[item.uid]
                self.assertEqual(obj.geoblender.dataset_uid, record_uid)
                self.assertEqual((obj.display_type, obj.show_in_front),
                                 (style.display_type, style.show_in_front))
                self.assertEqual(tuple(round(value, 6) for value in obj.color),
                                 tuple(round(value, 6) for value in style.color))
                self.assertIn(name, obj.name)
                self.assertIn(item.role.label("es"), obj.name)
                self.assertEqual(obj.users_collection[0].get("geoblender_key"),
                                 f"dataset:{record_uid}")
                world = self.mesh.mesh_vertices_world(obj.data, origin)
                self.assertTrue(np.all(world[:, 2] == float(origin.z0)))
                wanted = np.vstack([ring for part in item.parts for ring in part])
                if item.kind.value == "point":  # el punto, primer vértice; la cruz, las aristas
                    self.assertEqual((len(world), len(obj.data.edges)), (5, 4))
                    np.testing.assert_allclose(world[:1, :2], wanted, atol=1e-4)
                else:
                    drawn = {tuple(np.round(row, 3)) for row in world[:, :2]}
                    for row in wanted:
                        self.assertIn(tuple(np.round(row, 3)), drawn)
                    self.assertGreaterEqual(len(obj.data.edges), len(world) - 1)
        self.assertNotEqual(tuple(style.color), (1.0, 1.0, 1.0, 1.0))
        masks = self.access.load_masks(self.project, self.v01.uid)
        self.assertEqual(masks.operation_uid, self.masks.operation_uid)
        self.assertEqual(self.views.unload_datasets([record_uid]), 7)
        self.assertFalse([obj for obj in bpy.data.objects if obj.geoblender.kind == KIND])

    def test_h_convert_one_into_a_constraint(self) -> None:
        """RF-012-27: «Convertir en restricción…» crea la restricción de «Hondonada» (solo
        relleno, con 2 m de resguardo) con el tipo, el motivo y el decisor que se declaran, su
        geometría bit a bit, enlazada a la intención y con su origen, en una
        ``core.edit_constraints`` con ``core_intention`` como entrada; la intención no cambia
        (sus filas, iguales); sin tipo, sin motivo, sin decisor, con una fecha o un resguardo que
        no valen, con un tipo que no cabe en su geometría o con una intención que ya no está se
        rechaza sin escribir nada."""
        self.open_window()
        saved = self.stored()
        hollow, wall = saved["Hondonada"], saved["Muro de piedra"]
        convert = bpy.ops.geoblender.core_convert_intention
        good = {"uid": hollow.uid, "ctype": "FILL_ONLY", "name": "", "reason": CONVERT_REASON,
                "decided_by": PERSON, "decided_on": DATE_TEXT, "buffer_out": "2"}
        self.assertIn("ya no está", self.refused(convert, **{**good, "uid": "no-existe"}))
        self.assertIn("tipo", self.refused(convert, **{**good, "ctype": "NONE"}))
        self.assertIn("motivo", self.refused(convert, **{**good, "reason": " "}))
        self.assertIn("quién", self.refused(convert, **{**good, "decided_by": ""}))
        self.assertIn("«mañana»", self.refused(convert, **{**good, "decided_on": "mañana"}))
        self.assertIn("«mucho»", self.refused(convert, **{**good, "buffer_out": "mucho"}))
        text = self.refused(convert, **{**good, "uid": wall.uid, "ctype": "LEGAL_LIMIT"})
        self.assertIn("Muro de piedra", text)
        intentions = self.rows("SELECT * FROM core_intention ORDER BY fid")
        before = self.count()
        self.assertEqual(convert(**good), {"FINISHED"})
        self.assertEqual(self.count(), (before[0] + 1, before[1] + 1, before[2]))
        self.assertEqual(self.rows("SELECT * FROM core_intention ORDER BY fid"), intentions)
        made = self.constraints()["hondonada"]
        self.assertEqual((made.name, made.ctype.value, made.kind.value, made.reason,
                          made.decided_by, made.decided_on, made.intention_uid,
                          made.source_input, made.source_fid, made.priority),
                         ("Hondonada", "fill_only", "polygon", CONVERT_REASON, PERSON,
                          dt.date(2025, 9, 20), hollow.uid, hollow.source_input,
                          hollow.source_fid, 0))
        # La decisión de la propiedad de la intención pasa a la restricción (T41, RF-012-02).
        self.assertEqual((hollow.decision_uid, made.decision_uid),
                         (self.decision.uid, self.decision.uid))
        self.assertTrue(self.cmodel.GeometryKind(made.kind) is hollow.kind)
        for ring, wanted in zip(made.parts[0], hollow.parts[0], strict=True):
            self.assertTrue(np.array_equal(ring, wanted))
        ((op_uid, status, settings),) = self.rows(
            "SELECT uid, status, settings FROM gb_operation WHERE op_type = ? ORDER BY "
            "started_at DESC, uid LIMIT 1", CONSTRAINT_TYPE)
        self.assertEqual(status, "done")
        self.assertEqual(self.rows(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = "
            "io.item_uid WHERE io.direction = 'in' AND io.role = 'intention' AND "
            "io.operation_uid = ?", op_uid), [(PREFIX,)])
        params = _module("core.params").ParameterStore(self.project)
        self.assertEqual(params.get(_module("core.constraints.params").buffer_out_key(
            "hondonada")).value, 2.0)
        view = self.view()
        self.assertEqual(self.texts()[0], ("Intención «Hondonada» convertida en la restricción "
                                           "«hondonada»"))
        self.assertEqual([item.converted for item in view.intentions],
                         ["hondonada", "", "", "", "", "", ""])
        view.intention_index = 0
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        self.assertIn("Convertida en: hondonada", " ".join(layout.texts()))

    def test_i_converted_the_masks_change_and_the_intention_does_not(self) -> None:
        """RF-012-27 (HU-012-6): la restricción convertida deja obsoletas las máscaras de V01;
        compiladas, cambian (la hondonada deja de admitir corte) y la intención sigue igual."""
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        self.assertEqual(state, self.access.MaskState.STALE)
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        masks = self.access.load_masks(self.project, self.v01.uid)
        self.assertNotEqual(masks.operation_uid, self.masks.operation_uid)
        self.assertFalse(np.array_equal(masks.cut_allowed(), self.masks.cut_allowed()))
        self.assertTrue(masks.zone("hondonada") is not None)
        taken = masks.cut_allowed() ^ self.masks.cut_allowed()
        self.assertGreater(int(np.count_nonzero(taken)), 0)
        self.assertEqual(self.stored()["Hondonada"].role.value, "fill")  # la intención, igual

    def constraints_window(self) -> Any:
        """«Restricciones…» con su ventana sustituida: la vista, leída del proyecto."""
        with mock.patch.object(self.core_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.core_edit_constraints(), {"FINISHED"})
        return self.view()

    def choose(self, code: str) -> Any:
        """La restricción ``code`` elegida en la lista de la ventana (la barra N la sigue)."""
        view = self.constraints_window()
        view.item_index = [item.code for item in view.constraints].index(code)
        return view

    def selected_texts(self) -> list[str]:
        return draw(getattr(bpy.types, "GEOBLENDER_PT_core_constraint"), bpy.context).texts()

    def test_ia_create_from_a_layer_with_the_decision_of_the_owner(self) -> None:
        """RF-012-02, RF-012-19 (T41): «Desde una capa…» con una decisión de la propiedad la
        fija en la restricción que crea, y la barra N «Restricción» la enseña con su fecha,
        quién y qué; sin decisión (la otra capa) no la tiene ni la barra dibuja la línea; una
        decisión que no está en el proyecto se rechaza con su valor, sin escribir nada."""
        create = bpy.ops.geoblender.core_create_constraints
        good = {"layer": self.names["Ermitas"], "ctype": "UNTOUCHABLE", "name_field": "nombre",
                "reason": REASON, "decided_by": PERSON, "decided_on": DATE_TEXT,
                "buffer_out": "10"}
        self.assertIn("«Una decisión que no existe»",
                      self.refused(create, **good, decision="Una decisión que no existe"))
        self.assertEqual(create(**good, decision=DECISION_TEXT), {"FINISHED"})
        self.assertEqual(create(**{**good, "layer": self.names["Muros"], "ctype": "NO_CUT",
                                   "buffer_out": "4"}), {"FINISHED"})
        found = self.constraints()
        self.assertEqual(found["ermita_de_san_roque"].decision_uid, self.decision.uid)
        self.assertEqual([found[code].decision_uid for code in ("muro_de_piedra", "talud_norte")],
                         [None, None])
        ((settings,),) = self.rows(
            "SELECT json_extract(settings, '$.decisions') FROM gb_operation WHERE op_type = ? "
            "AND json_extract(settings, '$.mapping.ctype') = 'untouchable'", CONSTRAINT_TYPE)
        self.assertEqual(settings, f'["{self.decision.uid}"]')
        # La ventana y la barra N lo enseñan como se lee la decisión, no como su uid.
        view = self.choose("ermita_de_san_roque")
        self.assertEqual(view.constraints[view.item_index].decision, DECISION_TEXT)
        self.assertEqual(view.selected.decision, DECISION_TEXT)
        self.assertIn(f"Decisión enlazada: {DECISION_TEXT}", self.selected_texts())
        self.assertNotIn(self.decision.uid, " ".join(self.selected_texts()))
        self.choose("talud_norte")
        self.assertEqual(self.view().selected.decision, "")
        self.assertFalse([text for text in self.selected_texts()
                          if text.startswith("Decisión enlazada")])

    def test_ib_complete_with_the_decision_of_the_owner(self) -> None:
        """RF-012-02, RF-012-19 (T41): «Completar…» una restricción sin decisión con una la fija
        y la barra N la enseña; completar sin elegir ninguna la deja como estaba; una que no está
        en el proyecto se rechaza sin escribir nada. El diálogo ofrece las decisiones del
        proyecto y propone la que ya tiene."""
        complete = bpy.ops.geoblender.core_complete_constraint
        row = self.constraints()["muro_de_piedra"]
        self.assertIsNone(row.decision_uid)
        before = self.count()
        self.assertIn("«Una decisión que no existe»", self.refused(
            complete, uid=row.uid, ctype="NO_CUT", decision="Una decisión que no existe"))
        self.assertEqual(complete(uid=row.uid, ctype="NO_CUT", decision=DECISION_TEXT),
                         {"FINISHED"})
        self.assertEqual(self.count(), (before[0] + 1, before[1], before[2]))
        self.assertEqual(self.constraints()["muro_de_piedra"].decision_uid, self.decision.uid)
        self.choose("muro_de_piedra")
        self.assertIn(f"Decisión enlazada: {DECISION_TEXT}", self.selected_texts())
        # Sin elegir decisión, el resto cambia y la decisión se queda.
        self.assertEqual(complete(uid=row.uid, ctype="NO_CUT", priority=2), {"FINISHED"})
        kept = self.constraints()["muro_de_piedra"]
        self.assertEqual((kept.priority, kept.decision_uid), (2, self.decision.uid))
        # El diálogo: ofrece las decisiones del proyecto y propone la de la restricción.
        cls = self.commands.registered_class("geoblender.core_complete_constraint")
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=None, selected_objects=[],
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        for code, wanted in (("muro_de_piedra", DECISION_TEXT), ("talud_norte", "")):
            with self.subTest(restriccion=code):
                fake = operator_self(
                    cls, report=lambda kind, text: None, uid=self.constraints()[code].uid,
                    ctype="NONE", name="", reason="", decided_by="", decided_on="", priority=0,
                    buffer_out="", buffer_in="", weight="", active=True, decision="")
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
                self.assertEqual(fake.decision, wanted)
                self.assertEqual([(item.name, item.uid) for item in self.view().mark_decisions],
                                 [(DECISION_TEXT, self.decision.uid)])
                cls.draw(fake, bpy.context)
                fields = [item.text for item in fake.layout.of_kind("prop_search")]
                self.assertEqual(fields, ["Decisión de la propiedad"])

    def test_ic_the_dialog_of_create_offers_the_decisions_and_says_how_to_record_one(
            self) -> None:
        """RF-012-02 (T41): el diálogo de «Desde una capa…» ofrece las decisiones del proyecto
        para elegir una (la misma para todas las restricciones que crea), igual en inglés; sin
        ninguna registrada, dice con qué orden se registra."""
        cls = self.commands.registered_class("geoblender.core_create_constraints")
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=None, selected_objects=[],
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))

        def opened() -> Any:
            fake = operator_self(
                cls, report=lambda kind, text: None, layer="", ctype="FIELD", type_field="",
                type_values="", name_field="", reason_field="", reason="", decider_field="",
                decided_by="", date_field="", decided_on="", priority=0, buffer_out="",
                buffer_in="", weight="", active=True, decision="", provenance_dialog=False)
            self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
            cls.draw(fake, bpy.context)
            return fake

        fake = opened()
        self.assertEqual([item.name for item in self.view().mark_decisions], [DECISION_TEXT])
        self.assertEqual([item.text for item in fake.layout.of_kind("prop_search")],
                         ["Capa", "Decisión de la propiedad"])
        self.assertNotIn("regístrela antes", " ".join(fake.layout.texts()))
        i18n = _module("core.i18n")
        i18n.set_language("en")
        self.assertEqual([item.text for item in opened().layout.of_kind("prop_search")],
                         ["Layer", "Decision of the owner"])
        i18n.set_language("es")
        # Sin decisiones registradas: el diálogo dice cómo registrar una.
        with mock.patch.object(self.panels.versions_decisions, "decisions", return_value=()):
            empty = opened()
        self.assertEqual(len(self.view().mark_decisions), 0)
        self.assertIn("regístrela antes con", " ".join(empty.layout.texts()))

    def test_j_unavailable_without_a_project_read_only_or_superseded(self) -> None:
        """RF-012-28: sin proyecto, en solo lectura o con la versión activa SUPERADO las órdenes
        no están disponibles y dicen por qué (también en su descripción); la ventana abierta lo
        dice y desactiva lo que escribe."""
        commands = (bpy.ops.geoblender.core_edit_client_marks,
                    bpy.ops.geoblender.core_save_client_marks,
                    bpy.ops.geoblender.core_convert_intention)
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
            self.panels.fill_intentions(self.project)
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            self.assertIn(reason, layout.texts())
            disabled = {item.target for item in layout.of_kind("operator") if not item.enabled}
            self.assertTrue({SAVE, CONVERT} <= disabled, disabled)
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
        for idname in REAL:
            cls = self.commands.registered_class(idname)
            self.assertIn(note, cls.description(bpy.context, SimpleNamespace()))
        self.set_active(self.v01)
        self.assertTrue(bpy.ops.geoblender.core_edit_client_marks.poll())

    def test_k_the_window_is_in_both_languages(self) -> None:
        """RF-012-28 (principio 10): la ventana y los papeles de las intenciones se leen
        también en inglés."""
        i18n = _module("core.i18n")
        i18n.set_language("en")
        view = self.open_window()
        view.intention_index = 0
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        texts = " ".join(layout.texts())
        self.assertIn("Saved intentions", texts)
        self.assertIn("Converted into: hondonada", texts)
        self.assertNotIn("Intenciones", texts)
        ul = getattr(bpy.types, LIST)
        row = FakeLayout()
        ul.draw_item(None, bpy.context, row, view, view.intentions[0], 0, view,
                     "intention_index")
        self.assertIn("Fill", " ".join(row.texts()))
        self.assertNotIn("Rellenar", " ".join(row.texts()))


if __name__ == "__main__":
    unittest.main()
