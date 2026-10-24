# SPDX-License-Identifier: GPL-3.0-or-later
"""Materiales y densidades… (spec 011, T20; HU-011-3, HU-011-5; RF-011-11, RF-011-15,
RF-011-21; plan 011 §5.3.4, §5.5, D-8, D-9, D-11, D-12, D-18; ADR-0027).

- RF-011-11, D-12, D-18: la ventana de la columna de materiales del proyecto
  (``geoblender.res_edit_materials``, ``GEOBLENDER_PT_res_materials``) edita la columna en
  ``WindowManager.geoblender_res_panels`` (añadir, ordenar y quitar unidades y componentes, con
  su clase, papel, estado, base y espesor) y «Guardar la columna» la guarda como la tabla
  ``res_materials`` con una operación del proyecto (``res.edit_materials``); una columna que no
  vale se rechaza con su lista sin escribir nada; el código de cada unidad sale de su nombre al
  guardarla por primera vez y no cambia al renombrarla.
- RF-011-11, D-8: ninguna densidad ni ningún K tienen valor por defecto: sus parámetros quedan
  registrados «sin valor» y «sin confirmar», HIPÓTESIS hasta que una persona los declara.
- RF-011-11, RF-011-21, D-9, D-11: la densidad se declara con «Cambiar parámetro…» de la 008
  (que pide su tipo, su origen, quién decide y el motivo) y es solo del proyecto; el K, con la
  pregunta de la 009 («¿Para el proyecto o solo para V01?»); «Aplicar a todas» pone el K de una
  unidad en todas las demás en una sola transacción (o en ninguna).
- RF-011-15: los porcentajes de una compuesta se declaran juntos y se rechazan, sin cambiar
  ninguno, si no suman 100 % con dos decimales.
- RF-011-26: en solo lectura, la orden y lo que escribe la ventana están desactivados con su
  motivo. La orden pasa de «R-38» a la entrada «011» del catálogo (D-36).

Un proyecto por clase, rejillas de 4 × 4 celdas y la extensión sin importar otra vez
(``blender_ext.release``; RNF-001-01). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import tempfile
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
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.trees import remove_tree

ENTRY = "011"
EDIT = "geoblender.res_edit_materials"
SAVE = "geoblender.res_save_materials"
COLUMN = "geoblender.res_edit_column"
APPLY = "geoblender.res_apply_swell"
PERCENTAGES = "geoblender.res_set_percentages"
SET_PARAMETER = "geoblender.core_set_parameter"
PANEL = "GEOBLENDER_PT_res_materials"
WM_PROPERTY = "geoblender_res_panels"
CELLS = 4
GRIDS = ("Techo", "Muro", "Espesor")
REASON = "Prueba de los materiales de la cubicación"
SCOPE_QUESTION = "¿Para el proyecto o solo para V01?"
COLUMN_ROWS = [
    # position, parent, code, name, kind, role, state, base_dataset, base_elevation,
    # thickness_dataset
    (1, "", "escombro", "Escombro", "anthropic", "waste", "in_situ", "gis_dtm_techo", None,
     "gis_dtm_espesor"),
    (2, "", "montera", "Montera", "natural", "waste", "in_situ", None, "612.5", None),
    (3, "", "capa_util", "Capa útil", "compound", None, "in_situ", "gis_dtm_muro", None, None),
    (4, "", "muro", "Muro", "natural", "waste", "in_situ", None, None, None),
    (1, "capa_util", "caliza", "Caliza", "component", "useful", "in_situ", None, None, None),
    (2, "capa_util", "arcilla", "Arcilla", "component", "waste", "in_situ", None, None, None),
]
DIALOG_DEFAULTS = {
    SET_PARAMETER: {"key": "", "value": "", "unit": "", "kind": "ADOPTADO", "source": "",
                    "source_kind": "DOCUMENT", "decided_by": "", "decided_at": "", "reason": "",
                    "from_figure_uid": "", "scope": "PROJECT"},
    APPLY: {"unit": "", "component": "", "scope": "PROJECT", "reason": ""},
    PERCENTAGES: {"unit": "", "kind": "HIPOTESIS", "source": "", "source_kind": "DOCUMENT",
                  "decided_by": "", "reason": "", "scope": "PROJECT"},
}
"""Los valores por defecto de las propiedades de los diálogos que se abren a mano."""
SWELL_KEYS = ("res.unit.escombro.swell", "res.unit.montera.swell",
              "res.unit.capa_util.caliza.swell", "res.unit.capa_util.arcilla.swell",
              "res.unit.muro.swell")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Collection(list):
    """Una ``CollectionProperty`` simulada para el ``self`` de un diálogo abierto a mano."""

    def add(self) -> SimpleNamespace:
        item = SimpleNamespace(code="", name="", value="")
        self.append(item)
        return item


class ResMaterialsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 activa en la sesión, para toda la
    clase (cada prueba deja la columna guardada, que la siguiente puede reutilizar)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r20-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.ps = _module("bl.scene.project_session")
        cls.res_ops = _module("bl.ops.res")
        cls.session = _module("bl.ops.core_provenance")
        cls.params = _module("core.params")
        cls.res_params = _module("reserves.params")
        cls.provenance = _module("reserves.provenance")
        cls.commands = _module("bl.ui.commands")
        (folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=vf.WINDOW,
                                                                  grid_step_m=vf.STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = _module("core.versions.store").create_version(
                conn, cls.project, feature="definitiva", title="Definitiva", reason=REASON)
        cls.project.refresh_header()
        cls.datasets = cls.write_grids()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == \
            {"FINISHED"}

    @classmethod
    def write_grids(cls) -> list[str]:
        """Las rejillas del proyecto de :data:`GRIDS` (bases y espesores de la columna), como
        las deja «Rejilla del proyecto desde un MDT» (``gis.resample``); sus nombres de dato."""
        gis_store = _module("gis.store")
        crs, vertical = gis_store.project_references(cls.project)
        grid = _module("gis.grid").Grid(vf.WEST, vf.SOUTH + CELLS, 1.0, 1.0, CELLS, CELLS)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Bases"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        names = []
        with gis_store.ResultWriter(cls.project, handle) as out:
            for number, name in enumerate(GRIDS):
                values = np.full((CELLS, CELLS), 600.0 + number, dtype=np.float64)
                raster = _module("gis.raster").Raster(grid, values, crs, vertical)
                names.append(out.raster(name, raster).name)
            out.commit(software={library: library_version}, message=REASON)
        return names

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

    def open_window(self) -> Any:
        """«Materiales y densidades…» con su ventana sustituida (en ``blender -b``,
        ``wm.call_panel`` cierra Blender): la vista de la columna, leída del proyecto."""
        with mock.patch.object(self.res_ops, "_call_panel",
                               return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.res_edit_materials(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view()

    @staticmethod
    def edit(action: str) -> None:
        assert bpy.ops.geoblender.res_edit_column(action=action) == {"FINISHED"}

    def add_unit(self, name: str, kind: str, role: str, *, base: str = "",
                 elevation: str = "", thickness: str = "") -> Any:
        view = self.view()
        self.edit("ADD_UNIT")
        unit = view.units[view.unit_index]
        unit.name, unit.kind, unit.role = name, kind, role
        if elevation:
            unit.base_kind, unit.base_elevation = "ELEVATION", elevation
        else:
            unit.base_dataset = base
        unit.thickness_dataset = thickness
        return unit

    def add_component(self, name: str, role: str) -> None:
        view = self.view()
        self.edit("ADD_COMPONENT")
        unit = view.units[view.unit_index]
        component = unit.components[unit.component_index]
        component.name, component.role = name, role

    def build_column(self) -> None:
        """La columna de :data:`COLUMN_ROWS` en la ventana, con lo que hace una persona:
        añadir, quitar, subir y bajar unidades y componentes."""
        view = self.open_window()
        while len(view.units):
            self.edit("REMOVE_UNIT")
        top, wall, thickness = self.datasets[0], self.datasets[1], self.datasets[2]
        self.add_unit("Escombro", "ANTHROPIC", "WASTE", base=top, thickness=thickness)
        self.add_unit("Capa útil", "COMPOUND", "NONE", base=wall)
        self.add_component("Caliza", "USEFUL")
        self.add_component("Sobrante", "WASTE")
        self.edit("REMOVE_COMPONENT")
        self.add_component("Arcilla", "WASTE")
        self.add_unit("Montera", "NATURAL", "WASTE", elevation="612,5")
        self.edit("MOVE_UP")  # la montera, encima de la capa útil
        self.add_unit("Sobrante", "NATURAL", "WASTE")
        self.edit("REMOVE_UNIT")
        self.add_unit("Muro", "NATURAL", "WASTE", base=wall)  # la última: sin base
        self.edit("MOVE_UP")
        self.edit("MOVE_DOWN")

    def ensure_column(self) -> None:
        """La columna de :data:`COLUMN_ROWS` guardada, con sus códigos (si aún no lo está)."""
        if [row[2] for row in self.saved_rows()] != [row[2] for row in COLUMN_ROWS]:
            self.build_column()
            self.assertEqual(bpy.ops.geoblender.res_save_materials(), {"FINISHED"})
        self.open_window()

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def saved_rows(self) -> list[tuple[Any, ...]]:
        if not self.rows("SELECT name FROM sqlite_master WHERE name = 'res_materials'"):
            return []
        return self.rows("SELECT position, parent, code, name, kind, role, state, base_dataset, "
                         "base_elevation, thickness_dataset FROM res_materials "
                         "ORDER BY parent <> '', parent, position")

    def operations(self) -> list[tuple[str, str, str | None]]:
        return self.rows("SELECT uid, status, revision_uid FROM gb_operation "
                         "WHERE op_type = 'res.edit_materials' ORDER BY started_at, uid")

    def record(self, key: str, version: str | None = None) -> Any:
        return self.params.ParameterStore(self.project).get(key, version=version)

    def refused(self, call: Any, **values: Any) -> str:
        """El error de una orden (``RuntimeError`` de Blender) sin que cambie el proyecto."""
        counter = vf.change_counter(self.project)
        with self.assertRaises(RuntimeError) as caught:
            call(**values)
        self.assertEqual(vf.change_counter(self.project), counter)
        return str(caught.exception)

    def dialog(self, idname: str, **given: Any) -> tuple[Any, FakeLayout, Any]:
        """Abre el diálogo de ``idname`` a mano (``invoke`` con un ``window_manager``
        simulado) y lo dibuja: el ``self``, lo dibujado y el diálogo pedido."""
        cls = self.commands.registered_class(idname)
        self.assertIsNotNone(cls, idname)
        names = frozenset(given)
        values = {**DIALOG_DEFAULTS[idname], **given}
        if idname == PERCENTAGES:
            values["values"] = _Collection()
        fake = operator_self(cls, report=lambda kind, text: None,
                             properties=SimpleNamespace(is_property_set=names.__contains__),
                             **values)
        manager = SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}))
        context = SimpleNamespace(window_manager=manager, scene=bpy.context.scene)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        cls.draw(fake, bpy.context)
        return fake, fake.layout, manager.invoke_props_dialog

    @staticmethod
    def labels(layout: FakeLayout) -> list[str]:
        return [item.text for item in layout.of_kind("label")]

    @staticmethod
    def buttons(layout: FakeLayout, idname: str) -> list[Any]:
        return [item for item in layout.of_kind("operator") if item.target == idname]

    def declare(self, key: str, value: str, *, version: bool = False, kind: str = "HIPOTESIS"
                ) -> None:
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value=value, kind=kind, source="Criterio de la prueba",
            source_kind="PERSON", decided_by="Jefa de producción", reason=REASON,
            scope="VERSION" if version else "PROJECT"), {"FINISHED"})

    # --- Pruebas ------------------------------------------------------------------------------

    def test_column_is_edited_and_saved_without_densities(self) -> None:
        """RF-011-11, D-8, D-12, D-18, D-36: «Materiales y densidades…» es la orden real de la
        entrada «011» (no la provisional de R-38) y lanza la operación del proyecto
        ``res.edit_materials``; su ventana edita la columna (añadir, quitar, subir y bajar
        unidades y componentes). Una columna que no vale (una unidad sin papel) se rechaza con
        su lista y no escribe nada; la buena queda en ``res_materials`` de arriba abajo, con
        el código de cada unidad sacado de su nombre, la cota constante exacta y la última sin
        base, con una operación del proyecto hecha. Ninguna densidad, K ni porcentaje tiene
        valor por defecto: quedan registrados sin valor, HIPÓTESIS y «sin confirmar», como el
        umbral de presencia con el suyo (0,30 m). Renombrar una unidad no cambia su código."""
        command = self.commands.catalog().commands[EDIT]
        self.assertEqual(command.entry, ENTRY)
        cls = self.commands.registered_class(EDIT)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.EDIT_MATERIALS, {"REGISTER"}))
        for idname in (SAVE, COLUMN, APPLY, PERCENTAGES):
            with self.subTest(interna=idname):
                self.assertEqual(self.commands.catalog().commands[idname].entry, ENTRY)
                self.assertIn(self.commands.registered_class(idname), self.res_ops.classes)

        self.build_column()
        view = self.view()
        self.assertEqual([unit.name for unit in view.units],
                         ["Escombro", "Montera", "Capa útil", "Muro"])
        self.assertEqual([item.name for item in view.units[2].components],
                         ["Caliza", "Arcilla"])
        self.assertEqual(sorted(item.name for item in view.surfaces), sorted(self.datasets))
        before = self.operations()
        view.units[1].role = "NONE"
        text = self.refused(bpy.ops.geoblender.res_save_materials)
        self.assertIn("La columna de materiales no es válida", text)
        self.assertIn("«Montera» no es útil ni estéril: elija su papel", text)
        self.assertEqual(self.operations()[-1:], before[-1:])
        view.units[1].role = "WASTE"

        self.assertEqual(bpy.ops.geoblender.res_save_materials(), {"FINISHED"})
        self.assertEqual(self.saved_rows(), COLUMN_ROWS)
        (uid, status, revision), = self.operations()[len(before):]
        self.assertEqual((status, revision), ("done", ""))
        self.assertEqual(self.rows("SELECT role FROM gb_operation_io WHERE operation_uid = ? "
                                   "AND direction = 'out'", uid), [("materials",)])
        self.assertEqual([(unit.code, unit.saved) for unit in view.units],
                         [("escombro", True), ("montera", True), ("capa_util", True),
                          ("muro", True)])
        with self.project.read() as conn:
            column = _module("reserves.materials").read_column(conn)
        keys = self.provenance.tonnage_params(column)
        self.assertEqual(len(keys), 12)  # densidad y K de 3 unidades y 2 componentes, y sus %
        registered = {key: (value, kind, bool(unconfirmed), scope)
                      for key, value, kind, unconfirmed, scope in self.rows(
                          "SELECT key, value, kind, unconfirmed, scope FROM gb_parameter "
                          "WHERE key LIKE 'res.%'")}
        self.assertEqual({key: registered.get(key) for key in keys},
                         dict.fromkeys(keys, (None, self.params.ParamKind.HIPOTESIS.value, True,
                                              "project")))
        presence = self.record(self.res_params.ANTHROPIC_PRESENCE)
        self.assertEqual((presence.value, presence.unconfirmed), (0.30, True))

        view.units[1].name = "Montera arcillosa"  # el código no cambia (D-18)
        self.assertEqual(bpy.ops.geoblender.res_save_materials(), {"FINISHED"})
        self.assertEqual(self.saved_rows()[1][2:4], ("montera", "Montera arcillosa"))
        self.assertEqual(len(self.operations()), len(before) + 2)

    def test_read_only_disables_the_window(self) -> None:
        """RF-011-26, RF-008-32 (plan §5.3.4): en solo lectura, «Materiales y densidades…» y
        lo que escribe su ventana (guardar, «Aplicar a todas», los porcentajes) no están
        disponibles y dicen por qué («Proyecto en solo lectura: …»); la ventana lo dice y
        dibuja desactivado lo que escribe."""
        self.ensure_column()
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            for name in ("res_edit_materials", "res_save_materials", "res_apply_swell",
                         "res_set_percentages"):
                with self.subTest(orden=name):
                    self.assertFalse(getattr(bpy.ops.geoblender, name).poll())
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            self.assertIn(reason, self.labels(layout))
            self.assertTrue(self.buttons(layout, SAVE))
            for idname in (SAVE, APPLY, PERCENTAGES, SET_PARAMETER):
                for button in self.buttons(layout, idname):
                    self.assertFalse(button.enabled, idname)
        self.assertTrue(bpy.ops.geoblender.res_edit_materials.poll())

    def test_unit_parameters_from_the_window(self) -> None:
        """RF-011-11, RF-011-15, RF-011-21, D-9, D-11 (ADR-0027): en la ventana, cada unidad
        enseña su densidad y su K con su tipo y su ámbito, con «Cambiar parámetro…» de la 008
        de su clave. La densidad pide su tipo, su origen, quién decide y el motivo, y no
        pregunta por la versión (es del proyecto); el K pregunta «¿Para el proyecto o solo para
        V01?». «Aplicar a todas» pone el K de V01 de una unidad en todas las demás en una sola
        transacción (un fallo a mitad no cambia ninguno). Los porcentajes de la compuesta se
        declaran juntos y, si no suman 100 % con dos decimales, se rechazan sin cambiar
        ninguno."""
        self.ensure_column()
        view = self.view()
        escombro = view.units[0]
        density, swell = "res.unit.escombro.density", "res.unit.escombro.swell"
        self.assertEqual((escombro.density, escombro.swell),
                         ("sin valor [HIP] sin confirmar",
                          "V01: — · proyecto: sin valor [HIP] sin confirmar"))
        view.unit_index = 0
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        keys = [item.properties.key for item in self.buttons(layout, SET_PARAMETER)]
        self.assertEqual(keys, [self.res_params.ANTHROPIC_PRESENCE, density, swell])
        (apply,) = self.buttons(layout, APPLY)
        self.assertEqual((apply.properties.unit, apply.properties.component), ("escombro", ""))
        self.assertEqual(self.buttons(layout, PERCENTAGES), [])

        # La densidad: del proyecto, con su tipo, su origen, su decisor y su motivo.
        _fake, drawn, _opened = self.dialog(SET_PARAMETER, key=density)
        self.assertNotIn(SCOPE_QUESTION, self.labels(drawn))
        self.assertEqual([item.target for item in drawn.of_kind("prop")],
                         ["value", "kind", "source", "source_kind", "decided_by", "decided_at",
                          "reason"])
        text = self.refused(bpy.ops.geoblender.core_set_parameter, key=density, value="1,9",
                            kind="MEDIDO", decided_by="Laboratorio", reason=REASON)
        self.assertIn(f"Indique el origen de «{density}»", text)
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=density, value="1,9", kind="MEDIDO", source="Ensayo E-1",
            source_kind="DOCUMENT", decided_by="Laboratorio", reason=REASON), {"FINISHED"})
        found = self.record(density)
        self.assertEqual((found.value, found.kind.name, found.unconfirmed), (1.9, "MEDIDO", False))

        # El K: «¿Para el proyecto o solo para V01?»; solo V01.
        _fake, drawn, _opened = self.dialog(SET_PARAMETER, key=swell)
        self.assertIn(SCOPE_QUESTION, self.labels(drawn))
        self.declare(swell, "1,25", version=True)
        self.assertEqual(self.record(swell, version=self.v01.uid).value, 1.25)
        self.assertIsNone(self.record(swell).value)
        self.assertEqual((escombro.density, escombro.swell),
                         ("1,9 t/m³ [MED]", "V01: 1,25 [HIP] · proyecto: sin valor [HIP] "
                                            "sin confirmar"))

        # «Aplicar a todas»: propone V01 (la unidad tiene allí su K); una transacción o nada.
        fake, drawn, opened = self.dialog(APPLY, unit="escombro", component="")
        self.assertEqual(fake.scope, "VERSION")
        self.assertIn(SCOPE_QUESTION, self.labels(drawn))
        opened.assert_called_once()
        others = SWELL_KEYS[1:]
        store = self.params.ParameterStore
        change = store.change
        calls: list[str] = []

        def failing(store_self: Any, conn: Any, key: str, **values: Any) -> Any:
            calls.append(key)
            if len(calls) == 3:
                raise self.params.ParamError("core.param_not_registered", key=key)
            return change(store_self, conn, key, **values)

        with mock.patch.object(store, "change", failing):
            self.refused(bpy.ops.geoblender.res_apply_swell, unit="escombro", component="",
                         scope="VERSION", reason="Mismo K para toda la columna")
        self.assertEqual(len(calls), 3)
        for key in others:
            self.assertIsNone(self.record(key, version=self.v01.uid))
        transactions = mock.Mock(wraps=self.project.write_transaction)
        with mock.patch.object(self.project, "write_transaction", transactions):
            self.assertEqual(bpy.ops.geoblender.res_apply_swell(
                unit="escombro", component="", scope="VERSION",
                reason="Mismo K para toda la columna"), {"FINISHED"})
        self.assertEqual(transactions.call_count, 1)
        for key in others:
            with self.subTest(k=key):
                own = self.record(key, version=self.v01.uid)
                self.assertEqual((own.value, own.kind.name, own.source, own.decided_by,
                                  own.reason),
                                 (1.25, "HIPOTESIS", "Criterio de la prueba",
                                  "Jefa de producción", "Mismo K para toda la columna"))
                self.assertIsNone(self.record(key).value)
        self.assertEqual(view.units[3].swell,
                         "V01: 1,25 [HIP] · proyecto: sin valor [HIP] sin confirmar")

        # Los porcentajes de la capa útil, juntos: 97,5 % se rechaza; 100 %, en V01.
        view.unit_index = 2
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        (percentages,) = self.buttons(layout, PERCENTAGES)
        self.assertEqual(percentages.properties.unit, "capa_util")
        fake, drawn, _opened = self.dialog(PERCENTAGES, unit="capa_util")
        self.assertEqual([(item.code, item.name, item.value) for item in fake.values],
                         [("caliza", "Caliza", ""), ("arcilla", "Arcilla", "")])
        self.assertIn(SCOPE_QUESTION, self.labels(drawn))
        given = {"unit": "capa_util", "kind": "ADOPTADO", "source": "Informe de geología",
                 "source_kind": "DOCUMENT", "decided_by": "Geología", "reason": REASON,
                 "scope": "VERSION"}
        text = self.refused(bpy.ops.geoblender.res_set_percentages, values=[
            {"code": "caliza", "name": "Caliza", "value": "80"},
            {"code": "arcilla", "name": "Arcilla", "value": "17,5"}], **given)
        self.assertIn("Los porcentajes de los componentes de «Capa útil» suman 97,50 %, no "
                      "100 %", text)
        self.assertEqual(bpy.ops.geoblender.res_set_percentages(values=[
            {"code": "caliza", "name": "Caliza", "value": "82,5"},
            {"code": "arcilla", "name": "Arcilla", "value": "17,5"}], **given), {"FINISHED"})
        for code, value in (("caliza", 82.5), ("arcilla", 17.5)):
            own = self.record(f"res.unit.capa_util.{code}.percent", version=self.v01.uid)
            self.assertEqual((own.value, own.kind.name), (value, "ADOPTADO"))
        self.assertEqual(view.units[2].components[0].percent,
                         "V01: 82,5 % [ADO] · proyecto: sin valor [HIP] sin confirmar")


if __name__ == "__main__":
    unittest.main()
