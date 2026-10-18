# SPDX-License-Identifier: GPL-3.0-or-later
"""Nueva versión… y Cambiar estado… (spec 009, T19; HU-009-1; RF-009-01, RF-009-02, RF-009-03,
RF-009-04, RF-009-25; plan 009 §5.3.5, §5.5, A1, A2, D-3 y D-38).

Con un proyecto sintético nuevo (``core.project.create_project`` con los ajustes de
``tests.support.core_fixtures``), en la sesión. En ``blender -b`` no hay interfaz
(``docs/trampas.md`` §3): los diálogos se abren con un ``window_manager`` simulado y se dibujan
con un *layout* simulado (``tests.support.fake_layout``), y lo que dice cada orden se lee de su
``report`` con un ``self`` simulado (``operator_self``) o, en los rechazos de ``bpy.ops``, del
error que lanza.

- **Nueva versión…** (``geoblender.core_new_version``; RF-009-01): sin versión de partida y con
  encargo, V01 en BORRADOR con su r1 abierta, que pasa a ser la activa (el control 8 dice
  «V01.r1»); desde V01, V02, que hereda el parámetro de versión de V01 («Heredado de V01.r1») y
  nada más, y el control dice «V02.r1» (M1); el diálogo pide rasgo, título, motivo, de cuál parte
  («Ninguna» o una versión) y el encargo; sus textos caben. Los rechazos (sin rasgo, título o
  motivo), con su texto y sin escribir nada.
- **Cambiar estado…** (``geoblender.core_set_version_state``; RF-009-02, RF-009-03, RF-009-04,
  RF-009-25): ofrece solo las transiciones admitidas para el estado de la versión (BORRADOR:
  VIGENTE o DESCARTADO; VIGENTE: DESCARTADO; SUPERADO o DESCARTADO: ninguna, con el texto de
  RF-009-04); al declarar VIGENTE dice cuál pasará a SUPERADO y, sin revisión congelada,
  «Congele antes una revisión de V02»; al descartar la VIGENTE, «El proyecto queda sin versión
  vigente», con el motivo obligatorio. Tras cada cambio, la lista de ficheros del proyecto, sus
  huellas y sus fechas son las mismas salvo la base, su diario y la cabecera (RF-009-02); la
  revisión abierta de la que pasa a SUPERADO o DESCARTADO, «cerrada al superarse» (RF-009-25).
- **La versión de la orden**: la de la colección de una versión en el Outliner (el menú
  contextual «Versión ▾», ``GEOBLENDER_MT_core_context_version``) o, si no, la activa; sin
  ninguna, Cambiar estado… se dibuja desactivado con el motivo y no hace nada.
- **El catálogo**: las dos órdenes y el menú contextual de la versión son de la entrada «009»,
  reales y disponibles; Nueva revisión… y Reproducir… siguen en R-07 hasta su tarea.

T20 (RF-009-04, RF-009-05, RF-009-21, RF-009-29; plan 009 A3, A11, §5.3.5 y §5.5), con una orden
sintética de la demostración de un tipo de versión (``demo.pit``, ``ProvenanceAwareOperator``) que
la demostración declara entre sus ``commands`` y el catálogo enseña mientras dura la prueba:

- **Órdenes de versión**: sin versión activa, abrirla desde la interfaz abre la ventana que pide
  elegir o crear una versión (``GEOBLENDER_PT_core_choose_version``) y, desde un guion, se rechaza
  con su texto, sin escribir nada; con V02 activa, registra la operación en su revisión abierta;
  con V01 SUPERADO activa, desactivada con «V01 está en estado SUPERADO: cree una versión nueva a
  partir de ella» en su ``poll_message_set``, en su descripción y en los menús
  (``commands.register_check``, «Versión no editable»).
- **El ámbito en Parámetros** (``geoblender.core_set_parameter``): con V02 activa, cambiar
  ``demo.bench_height`` (de versión) pregunta «¿Para el proyecto o solo para V02?» y registra el
  cambio en el ámbito elegido sin tocar el otro; Parámetros del proyecto enseña los dos valores
  («V02: 12 m [HIP] · proyecto: 11 m [HIP]»); con V01 activa, solo el del proyecto, y «solo V01»
  desactivada con el texto de RF-009-04; sin versión activa o con un parámetro del proyecto, no
  pregunta.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.provenance_demo import PRODUCTION
from tests.support.repo import ROOT
from tests.support.trees import temp_folder
from tests.support.versions_demo import BENCH_HEIGHT, PIT, VersionsDemo

NEW_VERSION = "geoblender.core_new_version"
SET_STATE = "geoblender.core_set_version_state"
NEW_REVISION = "geoblender.core_new_revision"
REPRODUCE = "geoblender.core_reproduce_version"
CONTEXT_MENU = "GEOBLENDER_MT_core_context_version"
PANEL = "GEOBLENDER_PT_core_version"
ENTRY = "009"
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo único que puede cambiar al cambiar el estado de una versión: la base, su diario y la
cabecera (RF-009-02)."""
REASON = "Alternativa de la prueba de las órdenes"
NO_VERSION_NOTE = "Elija antes la versión activa: Proyecto ▸ Versiones ▸ Versión activa"
NOT_EDITABLE = "V01 está en estado SUPERADO: cree una versión nueva a partir de ella"
REQUIRED = ("Esta orden es de una versión: elija la versión activa o cree una (Proyecto ▸ "
            "Versiones)")
DATA = ROOT / "tests" / "data" / "core" / "provenance"
DEMO_COMMAND = "geoblender.core_selftest_pit"
"""La orden sintética de la demostración de un tipo de versión (``demo.pit``; T20)."""
DEMO_LABEL = "Synthetic pit design"  # sin traducción: se ve el msgid
DEMO_ABOUT = "Synthetic order of a version type"
RECOMPUTE = "geoblender.core_recompute_stale"
CHOOSE_PANEL = "GEOBLENDER_PT_core_choose_version"
SET_ACTIVE = "geoblender.core_set_active_version"
SET_PARAMETER = "geoblender.core_set_parameter"
PARAMETERS_PANEL = "GEOBLENDER_PT_core_parameters"
PIT_SETTINGS = {"benches": 3, "berm_m": 25.0, "step_m": 10.0, "top_z": 500.0}
MAX_TICKS = 2000


def ext(name: str) -> Any:
    """El módulo ``name`` de la copia de la extensión que importó Blender."""
    return vf.extension(name)


def drain(steps: Any) -> Any:
    """Avanza unos pasos (``Progress``) hasta el final y devuelve el resultado del último."""
    last = None
    for step in steps:
        last = step
    return None if last is None else last.result


def files(root: Path) -> dict[str, object]:
    """Cada carpeta y cada fichero de la carpeta del proyecto, con su tamaño, su huella y su
    fecha (ns), salvo la base, su diario y la cabecera (:data:`WRITTEN`)."""
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in WRITTEN:
            continue
        if path.is_dir():
            found[rel] = "carpeta"
            continue
        stat = path.stat()
        found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                      stat.st_mtime_ns)
    return found


class VersionsOpsTest(unittest.TestCase):
    """La extensión habilitada una vez; en cada prueba, su proyecto en la sesión."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.sv = ext("bl.scene.versions")
        self.ps = ext("bl.scene.project_session")
        self.ops = ext("bl.ops.versions")
        self.commands = ext("bl.ui.commands")
        self.read = ext("core.versions.read")
        self.store = ext("core.versions.store")
        self.i18n = ext("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v9o-")
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(self.ps.close)

    # --- El proyecto ---------------------------------------------------------------------------

    def project(self) -> Any:
        """Un proyecto nuevo en escritura, sin versiones, en la sesión."""
        parent = self.folder / "proyectos"
        parent.mkdir()
        core_project = ext("core.project")
        project = core_project.create_project(
            parent, core_project.ProjectSettings(**settings_values()), self.ps.session(),
            self.ps.userdata()).project
        self.addCleanup(project.close)
        self.ps.attach(project)
        return project

    def write(self, project: Any, work: Any) -> Any:
        with project.write_transaction() as conn:
            return work(conn)

    def create(self, project: Any, feature: str, title: str) -> Any:
        """Una versión hecha como la haría la orden (sin la sesión)."""
        version, _revision = self.write(project, lambda conn: self.store.create_version(
            conn, project, feature=feature, title=title, reason=REASON))
        project.refresh_header()
        return version

    def freeze(self, project: Any, version: Any) -> None:
        outcome = drain(ext("core.versions.freeze").freeze_steps(project, version.uid,
                                                                 reason="Entrega"))
        self.assertFalse(outcome.cancelled)

    def version(self, project: Any, code: str) -> Any:
        with project.read() as conn:
            return self.read.version(conn, code)

    def revisions(self, project: Any, code: str) -> list[tuple[str, str]]:
        with project.read() as conn:
            found = self.read.version(conn, code)
            return [(item.label(code), str(item.state))
                    for item in self.read.revisions(conn, found.uid)]

    # --- Las órdenes ----------------------------------------------------------------------------

    def operator(self, idname: str, **values: Any) -> tuple[type, Any]:
        """La clase de la orden y un ``self`` simulado con ``values`` que anota lo que dice en
        ``reports``."""
        cls = self.commands.registered_class(idname)
        self.assertIsNotNone(cls, idname)
        reports: list[tuple[set[str], str]] = []
        fake = operator_self(cls, reports=reports,
                             report=lambda kind, text: reports.append((set(kind), text)),
                             **values)
        return cls, fake

    def execute(self, idname: str, **values: Any) -> tuple[set[str], list[tuple[set[str], str]]]:
        cls, fake = self.operator(idname, **values)
        return cls.execute(fake, bpy.context), fake.reports

    def dialog_context(self, **extra: Any) -> SimpleNamespace:
        """Un contexto con un ``window_manager`` que anota el diálogo que se abre."""
        manager = SimpleNamespace(
            invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}),
            invoke_popup=mock.Mock(return_value={"RUNNING_MODAL"}))
        values = {"window_manager": manager, "scene": bpy.context.scene,
                  "view_layer": bpy.context.view_layer, "space_data": None, "collection": None}
        return SimpleNamespace(**{**values, **extra})

    def state_dialog(self, version_uid: str = "", context: Any = None,
                     **values: Any) -> tuple[set[str], Any, SimpleNamespace, FakeLayout]:
        """Abre Cambiar estado… (``version_uid`` vacío: la versión de ``context``) y lo dibuja:
        lo que devuelve ``invoke``, el ``self``, el contexto y lo dibujado."""
        context = self.dialog_context() if context is None else context
        cls, fake = self.operator(SET_STATE, version_uid=version_uid,
                                  target=values.pop("target", "VIGENTE"),
                                  reason=values.pop("reason", ""), **values)
        result = cls.invoke(fake, context, None)
        if result == {"RUNNING_MODAL"}:
            cls.draw(fake, bpy.context)
        return result, fake, context, fake.layout

    @staticmethod
    def choices(layout: FakeLayout) -> list[str]:
        """Los destinos que ofrece el diálogo de Cambiar estado…"""
        return [item.text for item in layout.of_kind("prop_enum")]

    @staticmethod
    def labels(layout: FakeLayout) -> list[str]:
        return [item.text for item in layout.of_kind("label")]

    def control(self) -> str:
        return self.sv.control_text()

    def panel_item(self, key: str) -> Any:
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        (found,) = [item for item in layout.items if item.target == key]
        return found

    # --- T20: las órdenes de versión y el ámbito de los parámetros ------------------------------

    def run_checks(self) -> None:
        """Avanza a mano la comprobación de apertura de la sesión hasta que se retira (en
        ``blender -b`` no corren los temporizadores)."""
        session = ext("bl.ops.core_provenance")
        for _ in range(MAX_TICKS):
            if session.check_tick() is None:
                return
        self.fail("la comprobación no termina")

    def set_active(self, version: Any) -> None:
        """Hace activa ``version`` (``None``: «Sin versión») con su orden."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid), {"FINISHED"})

    def declare_current(self, project: Any, version: Any) -> None:
        """Congela la revisión abierta de ``version`` y la declara VIGENTE (la que lo era pasa a
        SUPERADO), como lo harían sus órdenes; después, las versiones de la sesión."""
        self.freeze(project, version)
        self.write(project, lambda conn: self.store.set_status(conn, project, version.uid,
                                                               "VIGENTE", reason=REASON))
        project.refresh_header()
        ext("bl.ui.version_panels").on_project_read(project)

    def declare_command(self, demo: VersionsDemo) -> type:
        """La orden sintética de la demostración de un tipo de versión (``demo.pit`` sobre el
        último límite importado, con la altura de banco de la versión): registrada, en el
        catálogo y entre los ``commands`` de ``demo.pit`` hasta el final de la prueba (antes de
        quitar la demostración)."""
        session = ext("bl.ops.core_provenance")
        contract = ext("core.provenance.contract")
        ui = ext("bl.ui.provenance")

        class GEOBLENDER_OT_core_selftest_pit(session.ProvenanceAwareOperator,
                                              bpy.types.Operator):
            bl_idname = DEMO_COMMAND
            bl_label = DEMO_LABEL
            bl_description = DEMO_ABOUT
            bl_options = {"REGISTER"}
            provenance_op_type = PIT

            def provenance_inputs(self, context: object) -> tuple[object, ...]:
                return demo.version_uses(PIT, boundary=demo.boundary_name(
                    session.SESSION.project))

            def execute(self, context: object) -> set[str]:
                handle = self.begin(context, settings=PIT_SETTINGS, params=(BENCH_HEIGHT,))
                if handle is None:
                    return {"CANCELLED"}
                demo.run_body(handle)
                return {"FINISHED"}

        cat = self.commands.catalog()
        command = dataclasses.replace(
            cat.commands[RECOMPUTE], key=DEMO_COMMAND, idname=DEMO_COMMAND, label=DEMO_LABEL,
            label_es=DEMO_LABEL, description=DEMO_ABOUT, description_es=DEMO_ABOUT, home="",
            aliases=())
        self.addCleanup(self.commands.clear)  # la disponibilidad, de nuevo al pedirla
        # Su texto, sin traducción, queda entre los que faltan solo mientras dura la prueba.
        self.enterContext(mock.patch.object(self.i18n._STATE, "missing",
                                            set(self.i18n._STATE.missing)))
        self.enterContext(mock.patch.dict(cat.commands, {DEMO_COMMAND: command}))
        bpy.utils.register_class(GEOBLENDER_OT_core_selftest_pit)
        self.addCleanup(bpy.utils.unregister_class, GEOBLENDER_OT_core_selftest_pit)
        self.addCleanup(ui.sync_version_checks)  # después de devolver demo.pit como estaba
        original = contract.OPERATIONS[PIT]
        contract.unregister_operation(PIT)
        contract.register_operation(dataclasses.replace(original, commands=(DEMO_COMMAND,)))

        def restore() -> None:
            contract.unregister_operation(PIT)
            contract.register_operation(original)

        self.addCleanup(restore)
        return GEOBLENDER_OT_core_selftest_pit

    @staticmethod
    def drawn(key: str) -> Any:
        """Cómo dibujan los menús la orden ``key`` (``bl.ui.drawing.draw_command``)."""
        layout = FakeLayout()
        ext("bl.ui.drawing").draw_command(layout, key, context=bpy.context)
        (item,) = layout.items
        return item

    def parameter_dialog(self, key: str, **given: Any) -> tuple[Any, FakeLayout, Any]:
        """Abre Cambiar parámetro… de ``key`` (con ``given`` puestas por quien la lanza) y lo
        dibuja: el ``self``, lo dibujado y el contexto."""
        values = {"key": key, "value": "", "unit": "", "kind": "ADOPTADO", "source": "",
                  "source_kind": "DOCUMENT", "decided_by": "", "decided_at": "", "reason": "",
                  "from_figure_uid": "", "scope": "PROJECT", **given}
        names = frozenset({"key", *given})
        cls, fake = self.operator(SET_PARAMETER, properties=SimpleNamespace(
            is_property_set=lambda name: name in names), **values)
        context = self.dialog_context()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        cls.draw(fake, bpy.context)
        return fake, fake.layout, context

    def parameters_shown(self, key: str) -> tuple[list[str], str]:
        """Lo que enseña Parámetros del proyecto de ``key`` (seleccionado): las líneas con el
        valor de cada ámbito y las marcas de su fila en la lista."""
        ui = ext("bl.ui.provenance")
        ui.fill_parameters()
        view = getattr(bpy.context.window_manager,
                       ext("bl.props.provenance").WINDOW_MANAGER_PROPERTY)
        keys = [row.key for row in view.parameters]
        view.parameter_index = keys.index(key)
        layout = draw(getattr(bpy.types, PARAMETERS_PANEL), bpy.context)
        scopes = [text for text in self.labels(layout) if " · proyecto: " in text]
        line = FakeLayout()
        ui.draw_parameter_row(line, view.parameters[view.parameter_index])
        return scopes, self.labels(line)[3]

    # --- Pruebas -------------------------------------------------------------------------------

    def test_new_version_with_and_without_parent(self) -> None:
        """RF-009-01 (plan A1, M1): Nueva versión… sin versión de partida y con encargo crea V01
        en BORRADOR con su r1 abierta y la hace activa («V01.r1» en el control); desde V01, V02
        hereda el parámetro de versión de V01 («Heredado de V01.r1»), dice qué heredó y pasa a ser
        la activa («V02.r1»); las dos en la ventana del control 8. Sin rasgo, título o motivo, el
        rechazo con su texto (en los dos idiomas) y nada escrito; ningún fichero cambia salvo la
        base, su diario y la cabecera; en solo lectura, la orden no está disponible."""
        project = self.project()
        self.enterContext(VersionsDemo(module_name()).registered())
        before = files(project.root)
        self.assertTrue(self.panel_item(NEW_VERSION).enabled)

        self.assertEqual(bpy.ops.geoblender.core_new_version(
            feature="definitiva", title="Definitiva", reason="Primera alternativa",
            request="Encargo de la propiedad: dos fases"), {"FINISHED"})
        v01 = self.version(project, "V01")
        self.assertEqual((v01.feature, v01.title, str(v01.status), v01.request, v01.parent_uid,
                          v01.reason_created),
                         ("definitiva", "Definitiva", "BORRADOR",
                          "Encargo de la propiedad: dos fases", None, "Primera alternativa"))
        self.assertEqual(self.revisions(project, "V01"), [("V01.r1", "open")])
        self.assertEqual(self.sv.active_version(), v01.uid)
        self.assertEqual(self.control(), "V01.r1")
        self.assertEqual(self.ps.userdata().active_version(project.uid), v01.uid)
        self.assertEqual(files(project.root), before)

        # V01 con su altura de banco propia; V02 parte de V01 y la hereda (D-26).
        params = ext("core.params")
        store = params.ParameterStore(project)

        def bench(conn: Any) -> None:
            store.ensure_default(conn, BENCH_HEIGHT, geoblender_version="0.0.0")
            store.change(conn, BENCH_HEIGHT, version="V01", value=12.0, kind="HIPÓTESIS",
                         source="Estudio de la prueba", decided_by="Proyectista de la prueba",
                         reason="Banco de 12 m")

        self.write(project, bench)
        result, reports = self.execute(NEW_VERSION, feature="sur", title="Fase sur",
                                       reason="Desde la definitiva", parent_uid=v01.uid,
                                       request="")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(reports, [({"INFO"}, "V02 creada en BORRADOR, con su revisión r1 "
                                              "abierta; hereda 1 parámetro de V01 (V01.r1)")])
        v02 = self.version(project, "V02")
        self.assertEqual((v02.parent_uid, v02.parent_revision_uid, v02.request),
                         (v01.uid, None, None))
        inherited = store.get(BENCH_HEIGHT, version="V02")
        self.assertEqual((inherited.value, inherited.reason), (12.0, "Heredado de V01.r1"))
        self.assertEqual(self.sv.active_version(), v02.uid)
        self.assertEqual(self.control(), "V02.r1")
        names = [item.text for item in draw(getattr(bpy.types, PANEL), bpy.context)
                 .of_kind("operator") if item.target == "geoblender.core_set_active_version"]
        self.assertEqual(names[:2], ["V01 · Definitiva [BORRADOR] r1",
                                     "V02 · Fase sur [BORRADOR] r1"])
        # Sin versión de partida; y desde una que no tiene parámetros de versión que heredar,
        # solo de cuál parte.
        result, reports = self.execute(NEW_VERSION, feature="norte", title="Norte",
                                       reason="Sin padre", parent_uid="NONE", request="")
        self.assertEqual(reports, [({"INFO"}, "V03 creada en BORRADOR, con su revisión r1 "
                                              "abierta")])
        v03 = self.version(project, "V03")
        result, reports = self.execute(NEW_VERSION, feature="este", title="Este",
                                       reason="Desde la norte", parent_uid=v03.uid, request="")
        self.assertEqual(reports, [({"INFO"}, "V04 creada en BORRADOR, con su revisión r1 "
                                              "abierta; parte de V03")])
        self.assertEqual(self.control(), "V04.r1")
        self.assertEqual(files(project.root), before)

        # Los rechazos, con su texto y sin escribir nada.
        counter = vf.change_counter(project)
        for values, text in (
            ({"feature": " "}, "Indique el rasgo de la versión nueva (lo que la distingue)"),
            ({"title": ""}, "Indique el título de la versión"),
            ({"reason": ""}, "Indique el motivo de la versión nueva"),
        ):
            with self.subTest(text=text):
                given = {"feature": "x", "title": "X", "reason": "Y", "parent_uid": "NONE",
                         "request": "", **values}
                self.assertEqual(self.execute(NEW_VERSION, **given),
                                 ({"CANCELLED"}, [({"ERROR"}, text)]))
        self.i18n.set_language("en")
        self.assertEqual(self.execute(NEW_VERSION, feature="", title="X", reason="Y",
                                      parent_uid="NONE", request=""),
                         ({"CANCELLED"},
                          [({"ERROR"}, "State the feature of the new version (what sets it "
                                       "apart)")]))
        self.i18n.set_language("es")
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_version(feature="x", title="X", reason="")
        self.assertIn("Indique el motivo de la versión nueva", str(caught.exception))
        self.assertEqual(vf.change_counter(project), counter)

        # En solo lectura, no está disponible.
        project.set_read_only(ext("core.project").ReadOnlyCode.REQUESTED, "prueba")
        self.assertFalse(bpy.ops.geoblender.core_new_version.poll())
        self.assertFalse(bpy.ops.geoblender.core_set_version_state.poll())
        self.assertEqual(files(project.root), before)

    def test_new_version_dialog(self) -> None:
        """RF-009-01 (plan §5.5): el diálogo de Nueva versión… se abre con su título y pide
        «Rasgo», «Título», «Motivo», «Parte de» («Ninguna» o cada versión con su estado) y
        «Encargo (opcional)»; sus textos caben en su ancho a escala 1,0 y 1,25; abrirlo no
        escribe nada."""
        project = self.project()
        v01 = self.create(project, "definitiva", "Definitiva")
        ext("bl.ui.version_panels").on_project_read(project)
        counter = vf.change_counter(project)
        cls, fake = self.operator(NEW_VERSION, feature="", title="", reason="",
                                  parent_uid="NONE", request="")
        context = self.dialog_context()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        dialog = context.window_manager.invoke_props_dialog
        self.assertIs(dialog.call_args.args[0], fake)
        self.assertEqual(dialog.call_args.kwargs["title"], "Nueva versión…")
        width = dialog.call_args.kwargs["width"]
        cls.draw(fake, bpy.context)
        layout = fake.layout
        self.assertEqual([(item.target, item.text) for item in layout.of_kind("prop")],
                         [("feature", "Rasgo"), ("title", "Título"), ("reason", "Motivo"),
                          ("parent_uid", "Parte de"), ("request", "Encargo (opcional)")])
        items = self.ops.parent_items(None, bpy.context)
        self.assertEqual([(identifier, name) for identifier, name, _about in items],
                         [("NONE", "Ninguna"), (v01.uid, "V01 · Definitiva [BORRADOR] r1")])
        labels = ext("bl.ui.labels")
        for scale in at_scales():
            assert_fits(self, layout, labels.dialog_width(width), scale=scale, props=True)
            for _identifier, name, _about in items:
                with self.subTest(name=name, scale=scale):
                    self.assertLessEqual(labels.label_px(name, icon=True, scale=scale),
                                         labels.dialog_width(width))
        self.assertEqual(vf.change_counter(project), counter)

    def test_change_state_offers_only_the_admitted_transitions(self) -> None:
        """RF-009-03, RF-009-02, RF-009-04, RF-009-25 (plan A2, D-3, §5.5): Cambiar estado… de
        una BORRADOR ofrece VIGENTE y DESCARTADO; de una VIGENTE, solo DESCARTADO; de una
        SUPERADO, ninguna, con el texto de RF-009-04 (sin botón de aceptar). Declarar VIGENTE dice
        cuál pasará a SUPERADO y, sin revisión congelada, «Congele antes una revisión de V02»
        (rechazado); descartar la VIGENTE dice «El proyecto queda sin versión vigente» y pide
        motivo. Cada cambio deja la revisión abierta de la que se cierra «cerrada al superarse» y
        la lista de ficheros, sus huellas y sus fechas iguales salvo la base, su diario y la
        cabecera; los rechazos no escriben nada."""
        project = self.project()
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        self.freeze(project, v01)
        ext("bl.ui.version_panels").on_project_read(project)
        bpy.ops.geoblender.core_set_active_version(version_uid=v01.uid)
        before = files(project.root)

        # V01, BORRADOR y congelada: VIGENTE o DESCARTADO; no hay otra VIGENTE.
        result, fake, context, layout = self.state_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        context.window_manager.invoke_props_dialog.assert_called_once()
        self.assertEqual(context.window_manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Cambiar estado…")
        self.assertEqual(fake.version_uid, v01.uid)
        self.assertEqual(self.choices(layout), ["VIGENTE", "DESCARTADO"])
        self.assertEqual(self.labels(layout), ["V01 · Definitiva [BORRADOR] r2", "Estado nuevo"])
        self.assertEqual([item.target for item in layout.of_kind("prop")], ["reason"])
        result, reports = self.execute(SET_STATE, version_uid=v01.uid, target="VIGENTE",
                                       reason="")
        self.assertEqual((result, reports),
                         ({"FINISHED"}, [({"INFO"}, "V01 pasa de BORRADOR a VIGENTE")]))
        self.assertEqual(str(self.version(project, "V01").status), "VIGENTE")
        self.assertEqual(self.sv.status_text(), "V01.r2 VIGENTE")
        self.assertEqual(files(project.root), before)

        # V02, BORRADOR sin congelar: VIGENTE dice que V01 pasará a SUPERADO y que hay que
        # congelar antes; se rechaza sin escribir.
        result, fake, context, layout = self.state_dialog(v02.uid)
        self.assertEqual(self.choices(layout), ["VIGENTE", "DESCARTADO"])
        self.assertEqual(self.labels(layout), ["V02 · Fase sur [BORRADOR] r1", "Estado nuevo",
                                               "Congele antes una revisión de V02",
                                               "V01 pasará a SUPERADO"])
        counter = vf.change_counter(project)
        self.assertEqual(self.execute(SET_STATE, version_uid=v02.uid, target="VIGENTE",
                                      reason=""),
                         ({"CANCELLED"}, [({"ERROR"}, "Congele antes una revisión de V02")]))
        self.assertEqual(vf.change_counter(project), counter)

        # Congelada V02.r1, V02 pasa a VIGENTE y V01 a SUPERADO, con su r2 cerrada.
        self.freeze(project, v02)
        before = files(project.root)
        result, fake, context, layout = self.state_dialog(v02.uid, target="VIGENTE")
        self.assertEqual(self.labels(layout), ["V02 · Fase sur [BORRADOR] r2", "Estado nuevo",
                                               "V01 pasará a SUPERADO"])
        result, reports = self.execute(SET_STATE, version_uid=v02.uid, target="VIGENTE",
                                       reason="Entrega a la propiedad")
        self.assertEqual((result, reports), ({"FINISHED"}, [(
            {"INFO"}, "V02 pasa de BORRADOR a VIGENTE; V01 pasa a SUPERADO; V01.r2 cerrada al "
                      "superarse")]))
        self.assertEqual(self.revisions(project, "V01"), [("V01.r1", "frozen"),
                                                          ("V01.r2", "closed")])
        self.assertEqual(str(self.version(project, "V01").reason_closed), "Superada por V02")
        self.assertEqual(self.sv.status_text(), "V01.r2 SUPERADO")
        self.assertEqual(files(project.root), before)

        # V01, SUPERADO: ninguna transición, con el texto de RF-009-04; se rechaza igual.
        result, fake, context, layout = self.state_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        context.window_manager.invoke_props_dialog.assert_not_called()
        context.window_manager.invoke_popup.assert_called_once()
        self.assertEqual(self.choices(layout), [])
        self.assertEqual(self.labels(layout), ["V01 · Definitiva [SUPERADO] r2", NOT_EDITABLE])
        self.assertEqual([item.target for item in layout.of_kind("prop")], [])
        counter = vf.change_counter(project)
        self.assertEqual(self.execute(SET_STATE, version_uid=v01.uid, target="DESCARTADO",
                                      reason="Ya no"),
                         ({"CANCELLED"}, [({"ERROR"}, NOT_EDITABLE)]))
        self.assertEqual(vf.change_counter(project), counter)

        # V02, VIGENTE: solo DESCARTADO, que deja el proyecto sin versión vigente y pide motivo.
        result, fake, context, layout = self.state_dialog(v02.uid)
        self.assertEqual(fake.target, "DESCARTADO")
        self.assertEqual(self.choices(layout), ["DESCARTADO"])
        self.assertEqual(self.labels(layout), ["V02 · Fase sur [VIGENTE] r2", "Estado nuevo",
                                               "El proyecto queda sin versión vigente"])
        self.assertEqual(self.execute(SET_STATE, version_uid=v02.uid, target="DESCARTADO",
                                      reason=" "),
                         ({"CANCELLED"}, [({"ERROR"}, "Indique el motivo para descartar V02")]))
        self.assertEqual(vf.change_counter(project), counter)
        result, reports = self.execute(SET_STATE, version_uid=v02.uid, target="DESCARTADO",
                                       reason="La propiedad no sigue")
        self.assertEqual((result, reports), ({"FINISHED"}, [
            ({"INFO"}, "V02 pasa de VIGENTE a DESCARTADO; V02.r2 cerrada al superarse"),
            ({"WARNING"}, "El proyecto queda sin versión vigente")]))
        self.assertEqual(self.revisions(project, "V02"), [("V02.r1", "frozen"),
                                                          ("V02.r2", "closed")])
        self.assertEqual(files(project.root), before)

        # En inglés, los mismos destinos con sus nombres.
        self.i18n.set_language("en")
        v03 = self.create(project, "norte", "Norte")
        result, fake, context, layout = self.state_dialog(v03.uid)
        self.assertEqual(self.choices(layout), ["CURRENT", "DISCARDED"])
        self.assertEqual(self.labels(layout)[1:], ["New state",
                                                   "Freeze a revision of V03 first"])
        for scale in at_scales():
            labels = ext("bl.ui.labels")
            width = context.window_manager.invoke_props_dialog.call_args.kwargs["width"]
            assert_fits(self, layout, labels.dialog_width(width), scale=scale, props=True)

        # Con bpy.ops (un guion): la versión activa si no se dice cuál; los rechazos, con su texto.
        self.i18n.set_language("es")
        bpy.ops.geoblender.core_set_active_version(version_uid=v03.uid)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_version_state(target="DESCARTADO")
        self.assertIn("Indique el motivo para descartar V03", str(caught.exception))
        self.assertEqual(bpy.ops.geoblender.core_set_version_state(
            target="DESCARTADO", reason="Prueba"), {"FINISHED"})
        self.assertEqual(str(self.version(project, "V03").status), "DESCARTADO")

    def test_the_version_of_the_command(self) -> None:
        """RF-009-03 (plan §5.3.5; PC §3.13): sin versión activa, Cambiar estado… se dibuja
        desactivado, su descripción dice que se elija antes la versión y no hace nada; desde el
        menú contextual «Versión ▾» de la colección de una versión en el Outliner, la de la
        colección (aunque haya otra activa), con Cambiar estado… disponible y Nueva revisión…
        aún no; fuera del Outliner, la activa."""
        project = self.project()
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        ext("bl.ui.version_panels").on_project_read(project)
        self.assertIsNone(self.sv.active_version())
        cls = self.commands.registered_class(SET_STATE)
        item = self.panel_item(SET_STATE)
        self.assertFalse(item.enabled)
        self.assertIn(NO_VERSION_NOTE, cls.description(bpy.context, SimpleNamespace(
            version_uid="")))
        result, fake, _context, _layout = self.state_dialog()
        self.assertEqual((result, fake.reports), ({"CANCELLED"}, [({"ERROR"}, NO_VERSION_NOTE)]))
        result, reports = self.execute(SET_STATE, version_uid="", target="DESCARTADO",
                                       reason="x")
        self.assertEqual((result, reports), ({"CANCELLED"}, [({"ERROR"}, NO_VERSION_NOTE)]))

        # La colección de V01 en el Outliner, con V02 activa.
        bpy.ops.geoblender.core_set_active_version(version_uid=v02.uid)
        self.assertTrue(self.panel_item(SET_STATE).enabled)
        collection = bpy.data.collections.new("V01 · Definitiva")
        self.addCleanup(bpy.data.collections.remove, collection)
        collection.geoblender.version_id = v01.uid
        outliner = self.dialog_context(space_data=SimpleNamespace(type="OUTLINER"))
        outliner.collection = collection
        self.assertEqual(self.ops.target_version(outliner), v01.uid)
        result, fake, _context, layout = self.state_dialog(context=outliner)
        self.assertEqual(fake.version_uid, v01.uid)
        self.assertEqual(self.labels(layout)[0], "V01 · Definitiva [BORRADOR] r1")
        view3d = self.dialog_context(space_data=SimpleNamespace(type="VIEW_3D"))
        view3d.collection = collection
        self.assertEqual(self.ops.target_version(view3d), v02.uid)

        # El menú contextual de la versión: disponible, con Cambiar estado… y sin Nueva
        # revisión… (R-07) todavía.
        self.assertTrue(self.commands.is_available(CONTEXT_MENU))
        menu = draw(getattr(bpy.types, CONTEXT_MENU), outliner)
        drawn = {item.target: item for item in menu.of_kind("operator")}
        self.assertTrue(drawn[SET_STATE].enabled)
        self.assertEqual(drawn[SET_STATE].text, "Cambiar estado…")
        self.assertFalse(drawn[NEW_REVISION].enabled)
        self.assertNotIn("Disponible en R-07", [item.text for item in menu.of_kind("label")])

    def test_version_commands_need_an_editable_active_version(self) -> None:
        """RF-009-05, RF-009-04, RF-009-21 (plan A3, A11, §5.5; M3), con la orden sintética de
        ``demo.pit``: sin versión activa está disponible y, desde la interfaz, abre la ventana
        que pide elegir una versión (las que se pueden editar) o crear una, sin hacer nada más;
        desde un guion, el rechazo con su texto y nada escrito. Con V02 activa, registra la
        operación en su revisión abierta (V02.r1) y sus salidas son de V02. Declarada V02
        VIGENTE, con V01 (SUPERADO) activa, «Versión no editable»: su ``poll`` dice «V01 está en
        estado SUPERADO: cree una versión nueva a partir de ella», su descripción lo añade (en
        inglés, también) y los menús la dibujan desactivada; ejecutarla igualmente lo rechaza
        sin escribir nada. Con V02 activa, otra vez como siempre."""
        project = self.project()
        demo = self.enterContext(VersionsDemo(module_name()).registered())
        cls = self.declare_command(demo)
        sources = self.folder / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        demo.import_boundary(project, source)
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        self.declare_current(project, v01)
        self.run_checks()
        ext("bl.ui.provenance").refresh(force=True)
        session = ext("bl.ops.core_provenance")

        # Sin versión activa: disponible; desde la interfaz, la ventana que pide una versión.
        self.set_active(None)
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(self.drawn(DEMO_COMMAND).enabled)
        self.assertEqual(cls.description(bpy.context, None), DEMO_ABOUT)
        counter = vf.change_counter(project)
        _cls, fake = self.operator(DEMO_COMMAND)
        with mock.patch.object(session, "_call_panel", return_value={"FINISHED"}) as panel:
            self.assertEqual(cls.invoke(fake, self.dialog_context(), None), {"CANCELLED"})
        panel.assert_called_once_with(CHOOSE_PANEL)
        layout = draw(getattr(bpy.types, CHOOSE_PANEL), bpy.context)
        self.assertEqual(" ".join(self.labels(layout)), REQUIRED)
        self.assertEqual([(item.text, item.properties.version_uid)
                          for item in layout.of_kind("operator") if item.target == SET_ACTIVE],
                         [("V01 · Definitiva [VIGENTE] r2", v01.uid),
                          ("V02 · Fase sur [BORRADOR] r1", v02.uid)])
        self.assertEqual([item.text for item in layout.of_kind("operator")
                          if item.target == NEW_VERSION], ["Nueva versión…"])
        labels = ext("bl.ui.labels")
        width = labels.dialog_width(getattr(bpy.types, CHOOSE_PANEL).bl_ui_units_x
                                    * ext("bl.compat").UI_UNIT_PX)
        for scale in at_scales():
            assert_fits(self, draw(getattr(bpy.types, CHOOSE_PANEL), bpy.context), width,
                        scale=scale)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_selftest_pit()
        self.assertIn(REQUIRED, str(caught.exception))
        self.assertEqual(vf.change_counter(project), counter)

        # Con V02 activa: la operación, en su revisión abierta; sus salidas, de V02.
        self.set_active(v02)
        with project.read() as conn:
            opened = self.read.open_revision(conn, v02.uid)
        self.assertEqual(bpy.ops.geoblender.core_selftest_pit(), {"FINISHED"})
        with project.read() as conn:
            done = conn.execute("SELECT scope, revision_uid, status FROM gb_operation "
                                "WHERE op_type = ?", (PIT,)).fetchall()
            owners = conn.execute("SELECT DISTINCT version_uid FROM gb_dataset "
                                  "WHERE version_uid <> ''").fetchall()
        self.assertEqual(done, [("version", opened.uid, "done")])
        self.assertEqual(owners, [(v02.uid,)])

        # V02 VIGENTE: V01 pasa a SUPERADO. Con V01 activa, «Versión no editable».
        self.declare_current(project, v02)
        self.set_active(v01)
        with mock.patch.object(cls, "poll_message_set") as message:
            self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with(NOT_EDITABLE)
        self.assertFalse(bpy.ops.geoblender.core_selftest_pit.poll())
        self.assertEqual(cls.description(bpy.context, None), f"{DEMO_ABOUT}\n{NOT_EDITABLE}")
        self.assertFalse(self.drawn(DEMO_COMMAND).enabled)
        counter = vf.change_counter(project)
        self.assertEqual(self.execute(DEMO_COMMAND), ({"CANCELLED"}, [({"ERROR"}, NOT_EDITABLE)]))
        self.assertEqual(vf.change_counter(project), counter)
        self.i18n.set_language("en")
        self.assertEqual(cls.description(bpy.context, None),
                         f"{DEMO_ABOUT}\nV01 is in state SUPERSEDED: create a new version from it")
        self.i18n.set_language("es")

        # Con V02, VIGENTE, otra vez como siempre.
        self.set_active(v02)
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(self.drawn(DEMO_COMMAND).enabled)
        self.assertEqual(cls.description(bpy.context, None), DEMO_ABOUT)

    def test_parameter_scope_with_the_active_version(self) -> None:
        """RF-009-29, RF-009-04, RF-009-21 (plan A3, §5.5; M3, M5): con V02 (VIGENTE) activa,
        Cambiar parámetro… de ``demo.bench_height`` (de versión) pregunta «¿Para el proyecto o
        solo para V02?»; «solo V02» crea su valor en V02 y el del proyecto no cambia; «el
        proyecto» cambia el del proyecto y el de V02 sigue; el diálogo propone después el
        ámbito de V02 con su valor, y Parámetros del proyecto enseña los dos («V02: 12 m [HIP] ·
        proyecto: 11 m [HIP]», y «V02» entre las marcas de su fila). Con V01 (SUPERADO) activa,
        solo el del proyecto, y «Solo V01», desactivada con el texto de RF-009-04 (por un guion,
        rechazada sin escribir nada). Sin versión activa, o con un parámetro del proyecto, no
        pregunta (y pedir el ámbito de versión se rechaza con su texto). Sus textos caben a
        escala 1,0 y 1,25 y se dicen en inglés."""
        project = self.project()
        self.enterContext(VersionsDemo(module_name()).registered())
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        self.declare_current(project, v01)
        self.declare_current(project, v02)
        store = ext("core.params").ParameterStore(project)
        self.write(project, lambda conn: [store.ensure_default(conn, key,
                                                               geoblender_version="0.0.0")
                                          for key in (BENCH_HEIGHT, PRODUCTION)])
        question = "¿Para el proyecto o solo para V02?"

        # Con V02 activa: pregunta el ámbito (sin valor propio en V02, propone el proyecto).
        self.set_active(v02)
        fake, layout, context = self.parameter_dialog(BENCH_HEIGHT)
        self.assertEqual(fake.scope, "PROJECT")
        self.assertIn(question, self.labels(layout))
        self.assertEqual([(item.text, item.enabled) for item in layout.of_kind("prop_enum")],
                         [("El proyecto", True), ("Solo V02", True)])
        width = ext("bl.ui.labels").dialog_width(
            context.window_manager.invoke_props_dialog.call_args.kwargs["width"])
        for scale in at_scales():
            assert_fits(self, layout, width, scale=scale, props=True)
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=BENCH_HEIGHT, scope="VERSION", value="12", source="Estudio de la prueba",
            decided_by="Proyectista de la prueba", reason="Banco de 12 m en V02"), {"FINISHED"})
        self.assertEqual((store.get(BENCH_HEIGHT).value,
                          store.get(BENCH_HEIGHT, version="V02").value), (10.0, 12.0))
        self.assertIsNone(store.get(BENCH_HEIGHT, version="V01"))
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=BENCH_HEIGHT, scope="PROJECT", value="11", source="Norma de la prueba",
            decided_by="Dirección de la prueba", reason="Banco de 11 m"), {"FINISHED"})
        self.assertEqual((store.get(BENCH_HEIGHT).value,
                          store.get(BENCH_HEIGHT, version="V02").value), (11.0, 12.0))
        fake, layout, _context = self.parameter_dialog(BENCH_HEIGHT)
        self.assertEqual((fake.scope, fake.value), ("VERSION", "12"))
        self.assertEqual(self.parameters_shown(BENCH_HEIGHT),
                         (["V02: 12 m [HIP] · proyecto: 11 m [HIP]"], "V02"))

        # Con V01 (SUPERADO) activa: solo el del proyecto; «Solo V01», desactivada.
        self.set_active(v01)
        self.assertEqual(self.parameters_shown(BENCH_HEIGHT), ([], ""))
        fake, layout, _context = self.parameter_dialog(BENCH_HEIGHT)
        self.assertEqual((fake.scope, fake.value), ("PROJECT", "11"))
        self.assertEqual([(item.text, item.enabled) for item in layout.of_kind("prop_enum")],
                         [("El proyecto", True), ("Solo V01", False)])
        self.assertIn(NOT_EDITABLE, self.labels(layout))
        counter = vf.change_counter(project)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_parameter(
                key=BENCH_HEIGHT, scope="VERSION", value="13", source="Estudio de la prueba",
                decided_by="Proyectista de la prueba", reason="Banco de 13 m en V01")
        self.assertIn(NOT_EDITABLE, str(caught.exception))

        # Sin versión activa, o con un parámetro del proyecto: no pregunta.
        self.set_active(None)
        _fake, layout, _context = self.parameter_dialog(BENCH_HEIGHT)
        self.assertEqual(layout.of_kind("prop_enum"), [])
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_parameter(key=BENCH_HEIGHT, scope="VERSION",
                                                  value="13", reason="Sin versión")
        self.assertIn(NO_VERSION_NOTE, str(caught.exception))
        self.set_active(v02)
        _fake, layout, _context = self.parameter_dialog(PRODUCTION)
        self.assertEqual(layout.of_kind("prop_enum"), [])
        self.assertNotIn(question, self.labels(layout))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_parameter(key=PRODUCTION, scope="VERSION",
                                                  reason="Solo en V02")
        self.assertIn("es del proyecto: no admite un valor propio en V02", str(caught.exception))
        self.assertEqual(vf.change_counter(project), counter)

        # En inglés.
        self.i18n.set_language("en")
        _fake, layout, _context = self.parameter_dialog(BENCH_HEIGHT)
        self.assertIn("For the project or only for V02?", self.labels(layout))
        self.assertEqual([item.text for item in layout.of_kind("prop_enum")],
                         ["The project", "Only V02"])

    def test_catalog_entry(self) -> None:
        """RF-009-01, RF-009-03 (plan 009 D-38): Nueva versión…, Cambiar estado… y el menú
        contextual de la versión son de la entrada «009», entregada: sus clases reales, ni
        provisionales ni «Disponible en R-07», con su etiqueta del catálogo; Nueva revisión… y
        Reproducir… siguen en R-07 hasta su tarea."""
        cat = self.commands.catalog()
        for key in (NEW_VERSION, SET_STATE, CONTEXT_MENU):
            with self.subTest(key=key):
                self.assertEqual(cat.commands[key].entry, ENTRY)
                cls = self.commands.registered_class(key)
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(self.commands.is_available(key))
                self.assertNotIn("Disponible en", cls.bl_description)
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_new_version").bl_label,
                         "Nueva versión…")
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_set_version_state").bl_label,
                         "Cambiar estado…")
        for key in (NEW_REVISION, REPRODUCE):
            with self.subTest(key=key):
                self.assertEqual(cat.commands[key].entry, "R-07")
                self.assertFalse(self.commands.is_available(key))


if __name__ == "__main__":
    unittest.main()
