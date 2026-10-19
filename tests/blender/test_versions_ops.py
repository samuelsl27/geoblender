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

T21 (HU-009-1; RF-009-06, RF-009-07, RF-009-08; RNF-009-02; plan 009 A5 a A7, §5.3.5 y §5.5), con
el hueco de la demostración (``demo.pit``) calculado en V02:

- **Nueva revisión…** (``geoblender.core_new_revision``): el diálogo «Congelar V02.r1 y abrir
  V02.r2» con el motivo; desde la interfaz, el modal de pasos (``_StepsModal``, un evento del
  temporizador cada vez), con su avance «Congelando V02.r1: …» en la barra de estado: deja V02.r1
  congelada (su instantánea) y V02.r2 abierta con el motivo dado y dice «V02.r1 congelada (…
  copiados); V02.r2 abierta»; ninguna llamada del modal pasa de 0,2 s; desde un guion, de una
  vez. Esc a mitad (dos eventos): «Congelación cancelada: no ha quedado nada a medias» y nada
  queda (ficheros, base y revisión abierta).
- **Lo que hay que aceptar y lo que lo impide** (RF-009-08): con obsoletos, el diálogo los lista
  («Hay 3 resultados obsoletos: …») con «Aceptar y congelar»; sin aceptarlos no congela; con una
  entrada aguas arriba cambiada sin decidir, una ventana sin aceptar que lo dice, y la orden se
  rechaza; los avisos de la congelación, con ``report_later``.
- **«Versión no editable»** (RF-009-21): sin versión, desactivada con el motivo; con la activa
  SUPERADO, su ``poll``, su descripción y los menús lo dicen y se rechaza sin escribir.

T23 (HU-009-2; RF-009-11, RF-009-09; plan 009 A9, §5.3.5 y §5.5), con el hueco y su volumen de la
demostración calculados en V02 y V02.r1 congelada:

- **Reproducir…** (``geoblender.core_reproduce_version``): desde la interfaz, el modal de pasos
  con su avance «Reproduciendo V02.r1: «demo.pit» (1 de 2)…» y Esc; reproduce la última revisión
  congelada de la versión activa y dice «V02.r1 reproducida: coinciden 3 de 3 salidas y 1 de 1
  cifras…», con la ventana del informe (``GEOBLENDER_PT_core_reproduce_report``) y su JSON en
  la caché. Con el algoritmo de ``demo.pit`` subido a 1.1, el informe dice qué no coincide y su
  causa («demo.pit 1.1 instalada, congelada con 1.0»), en los dos idiomas. El proyecto no cambia
  (ni un fichero fuera de la caché, ni la base).
- **Cuándo no se puede**: sin versión activa, o sin revisión congelada, desactivada con el
  motivo; con un fichero de V02.r1 cambiado, se rechaza con lo que no coincide (sin dejar nada en
  la caché) y, marcada la revisión alterada, la orden queda desactivada con el motivo.

T24 (HU-009-4; RF-009-13; plan 009 A10, D-33, §5.3.5 y §5.5), con el acta de la propiedad (un PDF
sintético) registrada como entrada de tipo documento y ``demo.swell_factor`` en el proyecto:

- **Encargos y decisiones de la propiedad…** (``geoblender.core_show_decisions``): la ventana
  ``GEOBLENDER_PT_core_decisions`` con las decisiones (fecha, quién, qué, documento o referencia
  y a qué afecta), «Registrar decisión…» y los encargos de las versiones; también en solo
  lectura, sin «Registrar decisión…».
- **Registrar decisión…** (``geoblender.core_add_decision``, interna): el diálogo con quién
  decide, el día (hoy, por defecto), qué, el documento (los registrados), la referencia, los
  parámetros y las versiones (la activa, por defecto); registrada enlazada a
  ``demo.swell_factor`` y a V02, aparece en la lista, como decisor del parámetro en Parámetros
  del proyecto («Propiedad: D. Juan Prueba · 03/10/2026 · «…»», junto al suyo) y en el control 8
  con V02 activa. Los rechazos, con su texto y sin escribir nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import json
import re
import shutil
import time
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
from tests.support.provenance_demo import PRODUCTION, SWELL_FACTOR
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
MAX_EVENTS = 500
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal de Nueva revisión… con la demostración (T21)."""
FROZEN_TEXT = re.compile(r"V02\.r1 congelada \(\d+(,\d)? [kM]?B copiados\); V02\.r2 abierta")
CANCELLED_FREEZE = "Congelación cancelada: no ha quedado nada a medias"
REPORT_PANEL = "GEOBLENDER_PT_core_reproduce_report"
REPRODUCE_LABEL = "Reproducir la versión desde sus entradas congeladas"
REPRODUCED = "V02.r1 reproducida: coinciden 3 de 3 salidas y 1 de 1 cifras"
CANCELLED_REPRODUCE = "Reproducción cancelada: no ha quedado nada a medias"
REPRODUCE_STATUS = re.compile(
    r"^Reproduciendo V02\.r1: «(?P<op>demo\.pit(?:_volume)?)» \((?P<index>[12]) de 2\)… "
    r"\d{1,3} % · Esc: cancelar$")
SHOW_DECISIONS = "geoblender.core_show_decisions"
ADD_DECISION = "geoblender.core_add_decision"
DECISIONS_PANEL = "GEOBLENDER_PT_core_decisions"
WHO = "D. Juan Prueba"
WHAT = "K = 1,20 para el balance de la fase sur"
DOCUMENT = "Acta_propiedad"
REQUEST = "Encargo de la propiedad: dos fases"
OWNER = f"Propiedad: {WHO} · 03/10/2026 · «{WHAT}»"
"""El decisor de la propiedad de ``demo.swell_factor``, como lo enseña Parámetros del proyecto."""
CONTROL_OWNER = f"Propiedad: {WHO} · 03/10/2026 «{WHAT}»"
"""El de V02 en la ventana del control 8: el decisor y, debajo, lo decidido (sus líneas
seguidas)."""


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

    def create(self, project: Any, feature: str, title: str, request: str | None = None) -> Any:
        """Una versión hecha como la haría la orden (sin la sesión), con su encargo."""
        version, _revision = self.write(project, lambda conn: self.store.create_version(
            conn, project, feature=feature, title=title, reason=REASON, request=request))
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

    # --- T21: Nueva revisión… ------------------------------------------------------------------

    def pit_project(self) -> tuple[Any, Any, Any, Any]:
        """Un proyecto con el límite importado, V01 y V02 (BORRADOR) y el hueco de la
        demostración calculado en V02 (rejilla, malla y tabla de bancos), con la comprobación de
        apertura terminada y V02 activa: el proyecto, la demostración, V01 y V02."""
        project = self.project()
        demo = self.enterContext(VersionsDemo(module_name()).registered())
        sources = self.folder / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        demo.import_boundary(project, source)
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        demo.pit(project, "V02")
        self.run_checks()
        ext("bl.ui.version_panels").on_project_read(project)
        self.set_active(v02)
        return project, demo, v01, v02

    def revision_dialog(self, context: Any = None, **values: Any
                        ) -> tuple[set[str], Any, SimpleNamespace, FakeLayout]:
        """Abre Nueva revisión… (de la versión de ``context``) y lo dibuja: lo que devuelve
        ``invoke``, el ``self``, el contexto y lo dibujado."""
        context = self.dialog_context() if context is None else context
        cls, fake = self.operator(NEW_REVISION, version_uid=values.pop("version_uid", ""),
                                  reason=values.pop("reason", ""), accept="", in_steps=False,
                                  **values)
        result = cls.invoke(fake, context, None)
        if result == {"RUNNING_MODAL"}:
            cls.draw(fake, bpy.context)
        return result, fake, context, fake.layout

    def running_revision(self) -> Any:
        """La orden Nueva revisión… que está en marcha como modal (la que aún tiene pasos)."""
        cls = getattr(bpy.types, "GEOBLENDER_OT_core_new_revision")
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Nueva revisión… no está en marcha como modal")
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
        self.fail("Nueva revisión… no acaba")

    def snapshots(self, project: Any) -> list[str]:
        return sorted(path.name for path in (project.root / "snapshots").iterdir())

    def outside_snapshot(self, project: Any, label: str) -> dict[str, object]:
        """:func:`files` del proyecto sin la carpeta de la instantánea ``label``."""
        prefix = f"snapshots/{label}"
        return {rel: value for rel, value in files(project.root).items()
                if rel != prefix and not rel.startswith(f"{prefix}/")}

    # --- T23: Reproducir… ------------------------------------------------------------------------

    def reproduce_project(self) -> tuple[Any, Any, Any, Any]:
        """:meth:`pit_project` con el volumen del hueco también calculado en V02 y V02.r1
        congelada (V02.r2 abierta), V02 activa: el proyecto, la demostración, V01 y V02."""
        project, demo, v01, v02 = self.pit_project()
        demo.pit_volume(project, "V02")
        self.freeze(project, v02)
        ext("bl.ui.version_panels").on_project_read(project)
        return project, demo, v01, v02

    @staticmethod
    def untouched(project: Any) -> tuple[dict[str, object], int]:
        """Lo que no puede cambiar al reproducir: cada fichero y cada carpeta del proyecto fuera
        de su caché (la base y la cabecera incluidas) con su tamaño, su huella y su fecha, y el
        contador de cambios de la base."""
        found: dict[str, object] = {}
        for path in sorted(project.root.rglob("*")):
            rel = path.relative_to(project.root).as_posix()
            if rel == "cache" or rel.startswith("cache/"):
                continue
            if path.is_dir():
                found[rel] = "carpeta"
                continue
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                          stat.st_mtime_ns)
        return found, vf.change_counter(project)

    @staticmethod
    def reproductions(project: Any) -> list[str]:
        """Las carpetas de las reproducciones en la caché del proyecto."""
        folder = project.cache_dir() / "reproducir"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def running_reproduction(self) -> Any:
        """La orden Reproducir… que está en marcha como modal (la que aún tiene pasos)."""
        cls = getattr(bpy.types, "GEOBLENDER_OT_core_reproduce_version")
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Reproducir… no está en marcha como modal")
        return found[0]

    def report_lines(self) -> list[str]:
        """Lo que dice la ventana del informe, línea a línea (las etiquetas que dibuja)."""
        return self.labels(draw(getattr(bpy.types, REPORT_PANEL), bpy.context))

    @staticmethod
    def joined(lines: list[str]) -> str:
        """Las líneas partidas de la ventana, otra vez seguidas."""
        return " ".join(lines)

    # --- T24: Encargos y decisiones de la propiedad ---------------------------------------------

    def register_document(self, project: Any) -> str:
        """Registra el acta de la propiedad (``fuentes/acta_propiedad.pdf``, el PDF sintético de
        la procedencia) como entrada de tipo documento, con su importación (un tipo de operación
        de la prueba, registrado mientras dura); devuelve su uid."""
        provenance = ext("core.provenance")
        contract = ext("core.provenance.contract")
        inputs_model = ext("core.inputs.model")
        registry = ext("core.inputs.registry")
        builtin = ext("core.content.builtin")
        readers = ext("core.content.readers")
        definition = provenance.OperationDef("res.import_document", "1.0", "res",
                                             "Test document import", False)
        contract.register_operation(definition)
        self.addCleanup(contract.unregister_operation, definition.op_type)
        pdf = self.folder / "fuentes" / "acta_propiedad.pdf"
        pdf.parent.mkdir(exist_ok=True)
        shutil.copyfile(DATA / "informe.pdf", pdf)
        found = pdf.stat()
        no_crs = {"not_applicable": True}
        spec = inputs_model.InputSpec(
            DOCUMENT, "document", "res", builtin.DOCUMENT.id,
            files=[registry.locate_source(pdf, project, self.ps.userdata())],
            file_prints=[inputs_model.SourcePrint(
                ext("core.hashing").sha256_file(pdf), size=found.st_size,
                mtime_ns=found.st_mtime_ns)],
            digest=readers.read_content(builtin.DOCUMENT, builtin.DOCUMENT.request(
                "document", inputs_model.input_declarations(no_crs, no_crs, {}), {"main": pdf})),
            crs_h=no_crs, crs_v=no_crs,
        )
        handle = ext("core.provenance.operations").begin_operation(
            project, definition.op_type, settings={}, executor="blender")

        def work(conn: Any) -> str:
            record = registry.register_input(conn, project, spec, operation_uid=handle.uid)
            handle.complete(conn)
            return str(record.uid)

        return self.write(project, work)

    def decisions_project(self) -> tuple[Any, Any, Any, str]:
        """Un proyecto con V01 (con su encargo) y V02, ``demo.swell_factor`` con su valor por
        defecto y el acta de la propiedad registrada como entrada de tipo documento, ya leído
        por la interfaz y con V02 activa: el proyecto, V01, V02 y el uid del acta."""
        project = self.project()
        self.enterContext(VersionsDemo(module_name()).registered())
        v01 = self.create(project, "definitiva", "Definitiva", REQUEST)
        v02 = self.create(project, "sur", "Fase sur")
        store = ext("core.params").ParameterStore(project)
        self.write(project, lambda conn: store.ensure_default(conn, SWELL_FACTOR,
                                                              geoblender_version="0.0.0"))
        document = self.register_document(project)
        ext("bl.ui.version_panels").on_project_read(project)
        self.set_active(v02)
        return project, v01, v02, document

    def decision_dialog(self, **given: Any) -> tuple[set[str], Any, SimpleNamespace]:
        """Abre Registrar decisión… (con ``given`` puestas por quien la lanza) y lo dibuja: lo
        que devuelve ``invoke``, el ``self`` (con lo dibujado en ``layout``) y el contexto."""
        values = {"decided_by": "", "decided_at": "", "what": "", "source_input_uid": "NONE",
                  "source_text": "", "parameters": "", "versions": "", **given}
        names = frozenset(given)
        cls, fake = self.operator(ADD_DECISION, properties=SimpleNamespace(
            is_property_set=lambda name: name in names), **values)
        context = self.dialog_context()
        result = cls.invoke(fake, context, None)
        if result == {"RUNNING_MODAL"}:
            cls.draw(fake, bpy.context)
        return result, fake, context

    def show_decisions(self) -> None:
        """Proyecto ▸ Control ▸ Procedencia y registro ▸ Encargos y decisiones de la
        propiedad… desde la ventana (``wm.call_panel`` sustituido: en ``blender -b`` cierra
        Blender): lee las filas y abre su ventana una vez."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.ops, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_decisions(), {"FINISHED"})
        call.assert_called_once_with(DECISIONS_PANEL)

    def decisions_shown(self) -> list[str]:
        """Lo que dice la ventana de las decisiones (sus etiquetas, en orden)."""
        return self.labels(draw(getattr(bpy.types, DECISIONS_PANEL), bpy.context))

    def owner_shown(self, key: str) -> list[str]:
        """Lo que enseña Parámetros del proyecto del parámetro ``key`` seleccionado (sus
        etiquetas)."""
        ext("bl.ui.provenance").fill_parameters()
        view = getattr(bpy.context.window_manager,
                       ext("bl.props.provenance").WINDOW_MANAGER_PROPERTY)
        view.parameter_index = [row.key for row in view.parameters].index(key)
        return self.labels(draw(getattr(bpy.types, PARAMETERS_PANEL), bpy.context))

    def control_shown(self) -> str:
        """Lo que dice la ventana del control 8: sus etiquetas, seguidas (las partidas, otra vez
        en una línea)."""
        return self.joined(self.labels(draw(getattr(bpy.types, PANEL), bpy.context)))

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
        """RF-009-03, RF-009-06 (plan §5.3.5; PC §3.13): sin versión activa, Cambiar estado… y
        Nueva revisión… se dibujan desactivados, su descripción dice que se elija antes la
        versión y no hacen nada; desde el menú contextual «Versión ▾» de la colección de una
        versión en el Outliner, la de la colección (aunque haya otra activa), con Cambiar
        estado… y Nueva revisión… (T21) disponibles; fuera del Outliner, la activa."""
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
        revision = self.commands.registered_class(NEW_REVISION)
        self.assertFalse(self.panel_item(NEW_REVISION).enabled)
        self.assertIn(NO_VERSION_NOTE, revision.description(bpy.context, None))
        counter = vf.change_counter(project)
        result, fake, _context, _layout = self.revision_dialog()
        self.assertEqual((result, fake.reports), ({"CANCELLED"}, [({"ERROR"}, NO_VERSION_NOTE)]))
        self.assertEqual(self.execute(NEW_REVISION, version_uid="", reason="x", accept="",
                                      in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, NO_VERSION_NOTE)]))
        self.assertEqual(vf.change_counter(project), counter)

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

        # El menú contextual de la versión: disponible, con Cambiar estado… y Nueva revisión…
        # (T21), de la versión de la colección.
        self.assertTrue(self.commands.is_available(CONTEXT_MENU))
        menu = draw(getattr(bpy.types, CONTEXT_MENU), outliner)
        drawn = {item.target: item for item in menu.of_kind("operator")}
        self.assertTrue(drawn[SET_STATE].enabled)
        self.assertEqual(drawn[SET_STATE].text, "Cambiar estado…")
        self.assertTrue(drawn[NEW_REVISION].enabled)
        self.assertEqual(drawn[NEW_REVISION].text, "Nueva revisión…")
        self.assertNotIn("Disponible en R-07", [item.text for item in menu.of_kind("label")])
        self.run_checks()  # congelar espera a la comprobación de apertura (D-40)
        result, fake, context, _layout = self.revision_dialog(context=outliner)
        self.assertEqual((result, fake.version_uid), ({"RUNNING_MODAL"}, v01.uid))
        self.assertEqual(context.window_manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Congelar V01.r1 y abrir V01.r2")

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

    def test_new_revision_freezes_in_steps(self) -> None:
        """RF-009-06, RF-009-07, RNF-009-02, RF-009-21 (plan A5 a A7, §5.3.5, §5.5): Nueva
        revisión… con V02 activa abre «Congelar V02.r1 y abrir V02.r2» con el motivo (y
        «Congelar»); aceptado desde la interfaz, el modal de pasos avanza con «Congelando V02.r1:
        …» (del espacio libre a la confirmación, sin retroceder) y deja V02.r1 congelada con su
        instantánea y V02.r2 abierta con el motivo dado, «V02.r1 congelada (… copiados); V02.r2
        abierta», el control 8 en «V02.r2» y nada más cambiado fuera de la instantánea; ninguna
        llamada del modal pasa de 0,2 s. En inglés, el diálogo y el avance. Con la activa
        SUPERADO, «Versión no editable»: su ``poll``, su descripción y los menús lo dicen y se
        rechaza sin escribir nada."""
        project, _demo, v01, v02 = self.pit_project()
        result, fake, context, layout = self.revision_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        dialog = context.window_manager.invoke_props_dialog
        dialog.assert_called_once()
        context.window_manager.invoke_popup.assert_not_called()
        self.assertEqual((dialog.call_args.kwargs["title"], dialog.call_args.kwargs["confirm_text"]),
                         ("Congelar V02.r1 y abrir V02.r2", "Congelar"))
        self.assertEqual((fake.version_uid, fake.accept), (v02.uid, ""))
        self.assertEqual([(item.target, item.text) for item in layout.of_kind("prop")],
                         [("reason", "Motivo")])
        self.assertEqual(self.labels(layout), [])

        # Desde la interfaz: el modal de pasos, un evento del temporizador cada vez.
        before, counter = files(project.root), vf.change_counter(project)
        self.assertEqual(self.snapshots(project), [])
        self.assertEqual(bpy.ops.geoblender.core_new_revision(
            "EXEC_DEFAULT", reason="Entrega de la fase sur", in_steps=True), {"RUNNING_MODAL"})
        operator = self.running_revision()
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, [round(call, 3) for call in calls])
        (shown,) = operator.report_log
        self.assertRegex(shown, FROZEN_TEXT)
        self.assertEqual(self.revisions(project, "V02"), [("V02.r1", "frozen"),
                                                          ("V02.r2", "open")])
        with project.read() as conn:
            opened = self.read.open_revision(conn, v02.uid)
        self.assertEqual(opened.reason, "Entrega de la fase sur")
        self.assertEqual(self.snapshots(project), ["V02.r1"])
        self.assertTrue((project.root / "snapshots" / "V02.r1" / "manifest.json").is_file())
        self.assertEqual(self.outside_snapshot(project, "V02.r1"), before)
        self.assertGreater(vf.change_counter(project), counter)
        self.assertEqual(self.control(), "V02.r2")
        progress = ext("core.project.model").Progress
        status = [self.ops.freeze_status_text("V02.r1", progress(*entry[1:]))
                  for entry in operator.progress_log]
        self.assertEqual(status[0], "Congelando V02.r1: comprobando el espacio libre… 0 % · "
                                    "Esc: cancelar")
        self.assertEqual(status[-1], "Congelando V02.r1: confirmando… 100 % · Esc: cancelar")
        done = [entry[2] for entry in operator.progress_log]
        self.assertEqual(done, sorted(done))
        self.assertEqual(self.ops.freeze_status_text(
            "V02.r1", progress("copia", 40, 100, "Copiando «demo_pit_grid_v02.tif»…")),
            "Congelando V02.r1: copiando «demo_pit_grid_v02.tif»… 40 % · Esc: cancelar")

        # En inglés.
        self.i18n.set_language("en")
        _result, _fake, context, _layout = self.revision_dialog()
        self.assertEqual(context.window_manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Freeze V02.r2 and open V02.r3")
        self.assertEqual(self.ops.freeze_status_text(
            "V02.r2", progress("comprobación", 1, 4, "Comprobando «demo_pit_mesh_v02.npz»…")),
            "Freezing V02.r2: checking «demo_pit_mesh_v02.npz»… 25 % · Esc: cancel")
        self.i18n.set_language("es")

        # Con la activa SUPERADO (V01 VIGENTE y después V02), «Versión no editable».
        self.declare_current(project, v01)
        self.write(project, lambda conn: self.store.set_status(conn, project, v02.uid,
                                                               "VIGENTE", reason=REASON))
        project.refresh_header()
        ext("bl.ui.version_panels").on_project_read(project)
        self.set_active(v01)
        cls = self.commands.registered_class(NEW_REVISION)
        with mock.patch.object(cls, "poll_message_set") as message:
            self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with(NOT_EDITABLE)
        self.assertEqual(cls.description(bpy.context, None),
                         f"{getattr(cls, 'bl_description')}\n{NOT_EDITABLE}")
        self.assertFalse(self.panel_item(NEW_REVISION).enabled)
        counter = vf.change_counter(project)
        self.assertEqual(self.execute(NEW_REVISION, version_uid="", reason="Otra", accept="",
                                      in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, NOT_EDITABLE)]))
        self.assertEqual(vf.change_counter(project), counter)

    def test_what_must_be_accepted_and_what_prevents_freezing(self) -> None:
        """RF-009-08, RF-009-06 (plan A5, D-40, §5.5): con la altura de banco de V02 cambiada
        tras calcular el hueco, el diálogo dice «Hay 3 resultados obsoletos: si congela,
        quedarán anotados», los lista y ofrece «Aceptar y congelar»; sin aceptarlos se rechaza
        sin escribir nada; aceptados (desde un guion, de una vez), V02.r1 congelada con lo
        aceptado anotado y los avisos de la congelación con ``report_later``. Con la entrada del
        límite cambiada sin decidir, una ventana sin aceptar dice que no se puede congelar V02.r2
        y la orden se rechaza sin escribir nada."""
        project, _demo, _v01, v02 = self.pit_project()
        store = ext("core.params").ParameterStore(project)
        self.write(project, lambda conn: store.change(
            conn, BENCH_HEIGHT, version="V02", value=12.0, kind="HIPÓTESIS",
            source="Estudio de la prueba", decided_by="Proyectista de la prueba",
            reason="Banco de 12 m en V02"))
        stale = [f"«{name}»: resultado obsoleto"
                 for name in ("demo_pit_benches", "demo_pit_grid", "demo_pit_mesh")]
        result, fake, context, layout = self.revision_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        dialog = context.window_manager.invoke_props_dialog
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Aceptar y congelar")
        shown = self.labels(layout)
        self.assertEqual(" ".join(shown[:-3]),
                         "Hay 3 resultados obsoletos: si congela, quedarán anotados")
        self.assertEqual(sorted(shown[-3:]), stale)
        with project.read() as conn:
            uids = {conn.execute("SELECT uid FROM gb_dataset WHERE name = ? AND version_uid = ?",
                                 (name, v02.uid)).fetchone()[0]
                    for name in ("demo_pit_grid", "demo_pit_mesh", "demo_pit_benches")}
        self.assertEqual(set(fake.accept.split(",")), {f"dataset:{uid}" for uid in uids})
        labels = ext("bl.ui.labels")
        for scale in at_scales():
            _result, _fake, _context, drawn = self.revision_dialog()
            assert_fits(self, drawn, labels.dialog_width(self.ops.DIALOG_WIDTH), scale=scale,
                        props=True)

        # Sin aceptar, no congela.
        before, counter = files(project.root), vf.change_counter(project)
        names = "«demo_pit_grid», «demo_pit_mesh», «demo_pit_benches»"
        refused = ("Para congelar V02.r1, acepte antes lo que quedará anotado tal como está "
                   f"({names})")
        result, reports = self.execute(NEW_REVISION, version_uid="", reason="Con obsoletos",
                                       accept="", in_steps=False)
        self.assertEqual(result, {"CANCELLED"})
        (kind, text), = reports
        self.assertEqual(kind, {"ERROR"})
        self.assertEqual(sorted(re.findall("«[^»]+»", text)), sorted(names.split(", ")))
        self.assertTrue(text.startswith(refused.partition("(")[0]), text)
        self.assertEqual((files(project.root), vf.change_counter(project)), (before, counter))

        # Aceptados, desde un guion (de una vez); la cabecera que no se escribe, un aviso.
        jobs = ext("bl.ops.jobs")
        with mock.patch.object(project, "refresh_header", side_effect=OSError("disco de prueba")):
            result, reports = self.execute(NEW_REVISION, version_uid="", reason="Con obsoletos",
                                           accept=fake.accept, in_steps=False)
        project.refresh_header()
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(reports), 1)
        self.assertRegex(reports[0][1], FROZEN_TEXT)
        warning = jobs.sent_reports()[-1]
        self.assertEqual(warning[0], "WARNING")
        self.assertIn("V02.r1 está congelada, pero no se ha podido actualizar la cabecera",
                      warning[1])
        with project.read() as conn:
            frozen = self.read.last_frozen(conn, v02.uid)
            states = {row[0] for row in conn.execute(
                "SELECT state FROM gb_revision_item WHERE revision_uid = ? AND item_uid IN "
                f"({', '.join('?' for _ in uids)})", (frozen.uid, *sorted(uids)))}
        self.assertEqual(frozen.label("V02"), "V02.r1")
        self.assertEqual(states, {"stale"})
        accepted = json.loads(frozen.accepted)
        self.assertEqual({entry["item_uid"] for entry in accepted["items"]}, uids)
        self.assertEqual(accepted["reason"], "Con obsoletos")

        # La entrada del límite, cambiada sin decidir: no se puede congelar V02.r2.
        with project.read() as conn:
            input_uid, input_name = conn.execute("SELECT uid, name FROM gb_input").fetchone()
        now = ext("core.timeutil").format_utc(project.clock.now())
        self.write(project, lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'changed', status_at = ?, status_by = ?, "
            "seen_sha256 = ? WHERE uid = ?", (now, project.session.user_host, "d" * 64,
                                              input_uid)))
        before, counter = files(project.root), vf.change_counter(project)
        blocked = (f"Hay entradas aguas arriba de V02.r2 cambiadas sin decidir («{input_name}»): "
                   "actualícelas o mantenga la copia antes de congelarla")
        result, fake, context, layout = self.revision_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        context.window_manager.invoke_props_dialog.assert_not_called()
        context.window_manager.invoke_popup.assert_called_once()
        self.assertEqual(layout.of_kind("prop"), [])
        shown = " ".join(self.labels(layout))
        self.assertTrue(shown.startswith("Congelar V02.r2 y abrir V02.r3"), shown)
        self.assertIn(blocked, shown)
        self.assertEqual(self.execute(NEW_REVISION, version_uid="", reason="Otra",
                                      accept=fake.accept, in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, blocked)]))
        self.assertEqual((files(project.root), vf.change_counter(project)), (before, counter))

    def test_esc_halfway_leaves_nothing(self) -> None:
        """RF-009-07 (plan A6 (5), §5.5): Esc a mitad de Nueva revisión… (dos eventos del
        temporizador, un paso cada uno, con la carpeta temporal de la instantánea ya creada)
        cancela con «Congelación cancelada: no ha quedado nada a medias»: ni la temporal, ni la
        instantánea, ni nada en la caché; la base sin cambios y V02.r1 abierta."""
        project, _demo, _v01, _v02 = self.pit_project()
        before, counter = files(project.root), vf.change_counter(project)
        self.assertEqual(bpy.ops.geoblender.core_new_revision(
            "EXEC_DEFAULT", reason="Entrega", in_steps=True), {"RUNNING_MODAL"})
        operator = self.running_revision()
        with mock.patch.object(type(operator), "STEP_BUDGET_S", 0.0):  # un paso por evento
            for _ in range(2):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
        self.assertEqual([name.partition(".congelando-")[0] for name in self.snapshots(project)],
                         ["V02.r1"])
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], CANCELLED_FREEZE)
        self.assertEqual(self.snapshots(project), [])
        self.assertEqual((files(project.root), vf.change_counter(project)), (before, counter))
        self.assertEqual(self.revisions(project, "V02"), [("V02.r1", "open")])
        self.assertEqual(self.control(), "V02.r1")

    def test_reproduce_from_the_command(self) -> None:
        """RF-009-11, RF-009-09 (plan A9, §5.3.5, §5.5; M5): con V02 activa y V02.r1 congelada,
        Reproducir… está disponible en la ventana del control 8 y, desde la interfaz, es un modal
        de pasos con su avance en la barra de estado («Reproduciendo V02.r1: comprobando las
        huellas…», «Reproduciendo V02.r1: «demo.pit» (1 de 2)…»), ninguna llamada de más de
        0,2 s. Esc a mitad (con la carpeta de trabajo ya en la caché): «Reproducción cancelada:
        no ha quedado nada a medias» y nada queda en la caché. Hasta el final: «V02.r1
        reproducida: coinciden 3 de 3 salidas y 1 de 1 cifras; 1 operación tomada de lo
        congelado (…, importación)», la ventana del informe (cada salida y la cifra, que
        coinciden, lo tomado de lo congelado y dónde quedó el informe; sus líneas caben a escala
        1,0 y 1,25) y su ``informe.json`` en ``cache/reproducir/V02.r1-<8 hex>/``. RF-009-11
        (plan A9 (3), D-32): con la versión del algoritmo de ``demo.pit`` subida a 1.1, desde un
        guion (de una vez, sin abrir la ventana), dice que no coinciden su rejilla, su malla y su
        tabla de bancos, con su causa («demo.pit 1.1 instalada, congelada con 1.0»), como aviso
        que llega al registro de Blender (``report_later``) y en la ventana del informe, en
        alerta; el volumen, que se reproduce con la rejilla congelada, coincide; en inglés, en
        inglés. El proyecto no cambia: ni un fichero fuera de la caché ni la base."""
        project, demo, _v01, _v02 = self.reproduce_project()
        item = self.panel_item(REPRODUCE)
        self.assertTrue(item.enabled)
        self.assertEqual(item.text, REPRODUCE_LABEL)
        before = self.untouched(project)

        # Esc a mitad, con la carpeta de trabajo ya creada.
        self.assertEqual(bpy.ops.geoblender.core_reproduce_version(
            "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        operator = self.running_reproduction()
        with mock.patch.object(type(operator), "STEP_BUDGET_S", 0.0):  # un paso por evento
            for _ in range(MAX_EVENTS):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
                if self.reproductions(project):
                    break
        self.assertEqual(len(self.reproductions(project)), 1)
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], CANCELLED_REPRODUCE)
        self.assertEqual(self.reproductions(project), [])
        self.assertEqual(self.untouched(project), before)

        # Hasta el final: el informe «coinciden» y su ventana.
        with mock.patch.object(self.ops, "_call_panel", return_value={"FINISHED"}) as panel:
            self.assertEqual(bpy.ops.geoblender.core_reproduce_version(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
            operator = self.running_reproduction()
            state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        panel.assert_called_once_with(REPORT_PANEL)
        self.assertLessEqual(max(calls), CALL_LIMIT_S, [round(call, 3) for call in calls])
        (shown,) = operator.report_log
        self.assertTrue(shown.startswith(f"{REPRODUCED}; 1 operación tomada de lo congelado ("),
                        shown)
        self.assertTrue(shown.endswith(", importación)"), shown)
        self.assertNotIn("no coincide", shown)
        progress = ext("core.project.model").Progress
        status = self.ops.ReproduceStatus("V02.r1")
        texts = [status.text(progress(*entry[1:])) for entry in operator.progress_log]
        self.assertRegex(texts[0], r"^Reproduciendo V02\.r1: comprobando las huellas… \d{1,3} % "
                                   r"· Esc: cancelar$")
        operations = [found.group("op", "index") for found in map(REPRODUCE_STATUS.match, texts)
                      if found]
        self.assertEqual(list(dict.fromkeys(operations)),
                         [("demo.pit", "1"), ("demo.pit_volume", "2")])
        done = [entry[2] for entry in operator.progress_log]
        self.assertEqual(done, sorted(done))

        # La ventana del informe.
        (folder,) = self.reproductions(project)
        self.assertRegex(folder, r"^V02\.r1-[0-9a-f]{8}$")
        stored = json.loads((project.cache_dir() / "reproducir" / folder / "informe.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual((stored["revision"], stored["matches"]), ("V02.r1", True))
        lines = self.report_lines()
        self.assertEqual(lines[0], "Reproducción de V02.r1")
        text = self.joined(lines)
        volume = ext("core.params.store").shown_value(3182000.0, "m3", "es")
        for expected in (REPRODUCED, "Salidas", "«demo_pit_grid» coincide",
                         "«demo_pit_mesh» coincide", "«demo_pit_benches» coincide", "Cifras",
                         f"«demo.pit_volume» coincide: {volume}", "Tomado de lo congelado",
                         ", importación",
                         f"Informe guardado en cache/reproducir/{folder}/informe.json"):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        self.assertNotIn("No reproducible", text)
        width = ext("bl.ui.labels").dialog_width(getattr(bpy.types, REPORT_PANEL).bl_ui_units_x
                                                 * ext("bl.compat").UI_UNIT_PX)
        for scale in at_scales():
            assert_fits(self, draw(getattr(bpy.types, REPORT_PANEL), bpy.context), width,
                        scale=scale)
        self.assertEqual(self.untouched(project), before)

        # Con el algoritmo de demo.pit subido a 1.1 (simulado: el borde un metro más alto),
        # desde un guion (de una vez, sin ventana): lo que no coincide y su causa, como aviso.
        contract = ext("core.provenance.contract")
        original = contract.OPERATIONS[PIT]

        def higher(request: Any) -> Any:
            settings = {**request.settings, "top_z": request.settings["top_z"] + 1.0}
            return demo._reproduce(dataclasses.replace(request, settings=settings))

        contract.unregister_operation(PIT)
        contract.register_operation(dataclasses.replace(original, version="1.1",
                                                        reproduce=higher))

        def restore() -> None:
            contract.unregister_operation(PIT)
            contract.register_operation(original)

        self.addCleanup(restore)
        jobs = ext("bl.ops.jobs")
        cause = "demo.pit 1.1 instalada, congelada con 1.0"
        with mock.patch.object(self.ops, "_call_panel", return_value={"FINISHED"}) as panel:
            result, reports = self.execute(REPRODUCE, revision_uid="", in_steps=False)
        panel.assert_not_called()
        self.assertEqual(result, {"FINISHED"})
        ((kind, shown),) = reports
        self.assertEqual(kind, {"WARNING"})
        self.assertTrue(shown.startswith("V02.r1 reproducida: coinciden 0 de 3 salidas y 1 de 1 "
                                         f"cifras; «demo_pit_grid» no coincide: {cause}; "
                                         f"«demo_pit_mesh» no coincide: {cause}; "
                                         f"«demo_pit_benches» no coincide: {cause}"), shown)
        self.assertEqual(jobs.sent_reports()[-1], ("WARNING", shown))
        rows = getattr(bpy.context.window_manager,
                       ext("bl.props.versions").WINDOW_MANAGER_PROPERTY).report
        alerts = [(row.text, row.icon) for row in rows if row.alert]
        for name in ("demo_pit_grid", "demo_pit_mesh", "demo_pit_benches"):
            with self.subTest(name=name):
                self.assertIn((f"«{name}» no coincide: {cause}", "ERROR"), alerts)
        text = self.joined(self.report_lines())
        for name in ("demo_pit_grid", "demo_pit_mesh", "demo_pit_benches"):
            self.assertIn(f"«{name}» no coincide: {cause}", text)
        self.assertIn("«demo.pit_volume» coincide", text)

        self.i18n.set_language("en")
        result, reports = self.execute(REPRODUCE, revision_uid="V02.r1", in_steps=False)
        self.assertEqual(result, {"FINISHED"})
        self.assertIn("«demo_pit_grid» does not match: demo.pit 1.1 installed, frozen with 1.0",
                      reports[0][1])
        self.assertIn("«demo_pit_grid» does not match: demo.pit 1.1 installed, frozen with 1.0",
                      self.joined(self.report_lines()))
        self.assertEqual(self.report_lines()[0], "Reproduction of V02.r1")
        self.assertEqual(len(self.reproductions(project)), 3)
        self.assertEqual(self.untouched(project), before)

    def test_reproduce_unavailable(self) -> None:
        """RF-009-11, RF-009-09 (plan A8, A9, §5.5; M6): sin versión activa, Reproducir… se
        dibuja desactivada y su descripción dice que se elija antes la versión; con V01 activa,
        que no tiene ninguna congelada, «Congele antes una revisión de V01» (su ``poll``, su
        descripción y los menús), y se rechaza igual. Con un byte de más en un fichero de V02.r1
        aún sin marcar, la orden comprueba las huellas antes de reproducir y se rechaza con lo
        que no coincide («La revisión V02.r1 está alterada (…: otro tamaño): no se reproduce»),
        sin dejar nada en la caché; marcada alterada (la comprobación entera), la orden queda
        desactivada con ese motivo y se rechaza sin escribir nada."""
        project, _demo, v01, v02 = self.reproduce_project()
        cls = self.commands.registered_class(REPRODUCE)
        about = getattr(cls, "bl_description")

        # Sin versión activa.
        self.set_active(None)
        self.assertFalse(self.panel_item(REPRODUCE).enabled)
        self.assertEqual(cls.description(bpy.context, SimpleNamespace(revision_uid="")),
                         f"{about}\n{NO_VERSION_NOTE}")
        self.assertEqual(self.execute(REPRODUCE, revision_uid="", in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, NO_VERSION_NOTE)]))

        # V01, sin ninguna congelada.
        self.set_active(v01)
        freeze_first = "Congele antes una revisión de V01"
        self.assertFalse(self.panel_item(REPRODUCE).enabled)
        self.assertFalse(self.drawn(REPRODUCE).enabled)
        with mock.patch.object(cls, "poll_message_set") as message:
            self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with(freeze_first)
        self.assertEqual(cls.description(bpy.context, SimpleNamespace(revision_uid="")),
                         f"{about}\n{freeze_first}")
        self.assertEqual(self.execute(REPRODUCE, revision_uid="", in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, freeze_first)]))

        # V02.r1 con un fichero cambiado, aún sin marcar: se rechaza al comprobar las huellas.
        self.set_active(v02)
        self.assertTrue(cls.poll(bpy.context))
        (changed,) = (project.root / "snapshots" / "V02.r1").rglob("*.tif")
        with changed.open("ab") as stream:
            stream.write(b"\0")
        rel = changed.relative_to(project.root / "snapshots" / "V02.r1").as_posix()
        refused = f"La revisión V02.r1 está alterada ({rel}: otro tamaño): no se reproduce"
        before = self.untouched(project)
        self.assertEqual(self.execute(REPRODUCE, revision_uid="", in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, refused)]))
        self.assertEqual(self.reproductions(project), [])
        self.assertEqual(self.untouched(project), before)

        # Marcada alterada: desactivada con el motivo.
        check = ext("core.versions.check")
        with project.read() as conn:
            frozen = self.read.last_frozen(conn, v02.uid)
        findings = drain(check.full_steps(project, [frozen.uid]))
        now = ext("core.timeutil").format_utc(project.clock.now())
        self.write(project, lambda conn: check.record_findings(conn, project, findings, now=now))
        ext("bl.ui.version_panels").on_project_read(project)
        self.assertFalse(self.panel_item(REPRODUCE).enabled)
        self.assertFalse(self.drawn(REPRODUCE).enabled)
        with mock.patch.object(cls, "poll_message_set") as message:
            self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with(refused)
        self.assertFalse(bpy.ops.geoblender.core_reproduce_version.poll())
        self.assertEqual(cls.description(bpy.context, SimpleNamespace(revision_uid="")),
                         f"{about}\n{refused}")
        before = self.untouched(project)
        self.assertEqual(self.execute(REPRODUCE, revision_uid="", in_steps=False),
                         ({"CANCELLED"}, [({"ERROR"}, refused)]))
        self.assertEqual(self.reproductions(project), [])
        self.assertEqual(self.untouched(project), before)

    def test_owner_decision_from_the_dialog(self) -> None:
        """RF-009-13 (HU-009-4; plan A10, D-33, §5.5; M5; «Hecho cuando» de la T24): Encargos y
        decisiones de la propiedad… lista las decisiones (ninguna, al principio) y los encargos
        de las versiones, con «Registrar decisión…»; su diálogo pide quién decide, el día (hoy,
        por defecto), qué, el documento (los registrados), la referencia, los parámetros y las
        versiones (la activa, por defecto), y sus textos caben a escala 1,0 y 1,25; abrirlo no
        escribe nada. Registrada desde él una decisión enlazada a ``demo.swell_factor`` y a V02
        con el acta: está en el proyecto, aparece en la lista (fecha, quién, qué, documento,
        afecta a), como decisor de ``demo.swell_factor`` en Parámetros del proyecto, junto al
        suyo, y en el control 8 con V02 activa (no con V01); ningún fichero cambia salvo la
        base y su diario. Otra, desde un guion, con una referencia en texto y enlazada a V01:
        la lista, por el día de la decisión. En inglés, «Owner: …»."""
        project, v01, v02, document = self.decisions_project()
        before = files(project.root)
        counter = vf.change_counter(project)

        # La ventana, sin decisiones: los encargos y «Registrar decisión…».
        self.show_decisions()
        shown = self.decisions_shown()
        self.assertIn("No hay ninguna decisión de la propiedad registrada", shown)
        self.assertIn(f"V01 · Definitiva: «{REQUEST}»", shown)
        layout = draw(getattr(bpy.types, DECISIONS_PANEL), bpy.context)
        (button,) = [item for item in layout.of_kind("operator") if item.target == ADD_DECISION]
        self.assertEqual((button.text, button.enabled), ("Registrar decisión…", True))

        # El diálogo: el día de hoy y la versión activa, el acta entre los documentos.
        result, fake, context = self.decision_dialog()
        self.assertEqual(result, {"RUNNING_MODAL"})
        dialog = context.window_manager.invoke_props_dialog
        self.assertEqual(dialog.call_args.kwargs["title"], "Registrar decisión…")
        self.assertRegex(fake.decided_at, r"^\d\d/\d\d/\d{4}$")
        self.assertEqual((fake.versions, fake.parameters, fake.source_input_uid),
                         ("V02", "", "NONE"))
        self.assertEqual([(item.target, item.text) for item in fake.layout.of_kind("prop")],
                         [("decided_by", "Quién decide"), ("decided_at", "Fecha de la decisión"),
                          ("what", "Qué se decide"), ("source_input_uid", "Documento"),
                          ("source_text", "Referencia"), ("parameters", "Parámetros"),
                          ("versions", "Versiones")])
        items = self.ops.document_items(None, bpy.context)
        self.assertEqual([(identifier, name) for identifier, name, _about in items],
                         [("NONE", "Ninguno"), (document, DOCUMENT)])
        labels = ext("bl.ui.labels")
        width = labels.dialog_width(dialog.call_args.kwargs["width"])
        for scale in at_scales():
            assert_fits(self, fake.layout, width, scale=scale, props=True)
        self.assertEqual(vf.change_counter(project), counter)

        # Registrada desde el diálogo: en el proyecto, en la lista, en Parámetros y en el
        # control 8 con V02.
        result, reports = self.execute(
            ADD_DECISION, decided_by=WHO, decided_at="03/10/2026", what=WHAT,
            source_input_uid=document, source_text="", parameters=SWELL_FACTOR, versions="V02")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(reports, [({"INFO"}, f"Decisión de la propiedad registrada: «{WHAT}» "
                                              f"({WHO}, 03/10/2026)")])
        decisions = ext("core.versions.decisions")
        with project.read() as conn:
            (decision,) = decisions.decisions(conn)
        self.assertEqual((decision.decided_by, decision.decided_at, decision.what,
                          decision.source_input_uid, decision.source_text, decision.parameters,
                          decision.version_codes),
                         (WHO, "2026-10-03", WHAT, document, None, (SWELL_FACTOR,), ("V02",)))
        shown = self.decisions_shown()
        for line in ("03/10/2026 · D. Juan Prueba", WHAT, f"Documento: {DOCUMENT}",
                     f"Afecta a: {SWELL_FACTOR}, V02"):
            self.assertIn(line, shown)
        self.assertNotIn("No hay ninguna decisión de la propiedad registrada", shown)
        owner = self.owner_shown(SWELL_FACTOR)
        self.assertIn(OWNER, owner)
        own = [line for line in owner if line.startswith("Decidido por ")]
        self.assertEqual(owner.index(OWNER), owner.index(own[0]) + 1)  # junto al suyo
        self.assertEqual(ext("core.params").ParameterStore(project).get(SWELL_FACTOR)
                         .decided_by, "Geoblender (valor por defecto)")
        self.assertIn("Decisiones de la propiedad sobre V02", self.control_shown())
        self.assertIn(CONTROL_OWNER, self.control_shown())
        self.set_active(v01)
        self.assertNotIn(CONTROL_OWNER, self.control_shown())
        self.assertEqual(files(project.root), before)

        # Desde un guion: una referencia en texto, enlazada a V01 y de un día anterior.
        self.assertEqual(bpy.ops.geoblender.core_add_decision(
            decided_by="Dirección de la propiedad", decided_at="2026-09-15",
            what="Dos fases de explotación", source_text="Correo del 15/09/2026",
            versions="V01"), {"FINISHED"})
        shown = self.decisions_shown()
        self.assertLess(shown.index("15/09/2026 · Dirección de la propiedad"),
                        shown.index("03/10/2026 · D. Juan Prueba"))
        self.assertIn("Referencia: Correo del 15/09/2026", shown)
        self.assertIn("Afecta a: V01", shown)
        second = "Propiedad: Dirección de la propiedad · 15/09/2026 «Dos fases de explotación»"
        self.assertIn(second, self.control_shown())
        self.set_active(v02)
        self.assertNotIn(second, self.control_shown())
        self.assertEqual(self.owner_shown(SWELL_FACTOR).count(OWNER), 1)

        # En inglés.
        self.i18n.set_language("en")
        self.assertIn(f"Owner: {WHO} · 03/10/2026 «{WHAT}»", self.control_shown())
        self.assertIn("Owner decisions on V02", self.control_shown())
        self.assertEqual(files(project.root), before)

    def test_owner_decision_rejections_and_read_only(self) -> None:
        """RF-009-13 (plan A10, §5.5): Registrar decisión… sin quién decide, sin documento ni
        referencia, con un día que no es DD/MM/AAAA, con un parámetro o una versión que el
        proyecto no tiene, se rechaza con su texto (en los dos idiomas) y sin escribir nada. En
        solo lectura, Encargos y decisiones de la propiedad… sigue abriéndose (solo lee), pero
        «Registrar decisión…» está desactivada con el motivo y la orden no está disponible."""
        project, _v01, _v02, document = self.decisions_project()
        counter = vf.change_counter(project)
        given = {"decided_by": WHO, "decided_at": "03/10/2026", "what": WHAT,
                 "source_input_uid": document, "source_text": "", "parameters": SWELL_FACTOR,
                 "versions": "V02"}
        for values, text in (
            ({"decided_by": " "}, "Indique quién decide"),
            ({"what": ""}, "Indique qué se decide"),
            ({"decided_at": ""}, "Indique cuándo se decidió"),
            ({"source_input_uid": "NONE"},
             "Indique el documento o la referencia de la decisión (un documento registrado como "
             "entrada o un texto, como «correo del 03/10/2026»)"),
            ({"decided_at": "3 de octubre"},
             "Fecha de la decisión «3 de octubre»: escríbala como DD/MM/AAAA"),
            ({"parameters": f"{SWELL_FACTOR}, demo.nada"},
             "No hay ningún parámetro «demo.nada» en el proyecto"),
            ({"versions": "V02; V09"}, "No hay ninguna versión V09 en el proyecto"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.execute(ADD_DECISION, **{**given, **values}),
                                 ({"CANCELLED"}, [({"ERROR"}, text)]))
        self.i18n.set_language("en")
        self.assertEqual(self.execute(ADD_DECISION, **{**given, "decided_by": ""}),
                         ({"CANCELLED"}, [({"ERROR"}, "State who decides")]))
        self.i18n.set_language("es")
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_add_decision(decided_by=WHO, decided_at="03/10/2026",
                                                 what=WHAT)
        self.assertIn("Indique el documento o la referencia de la decisión", str(caught.exception))
        self.assertEqual(vf.change_counter(project), counter)
        with project.read() as conn:
            self.assertEqual(ext("core.versions.decisions").decisions(conn), ())

        # En solo lectura: se consulta, no se registra.
        project.set_read_only(ext("core.project").ReadOnlyCode.REQUESTED, "prueba")
        self.assertTrue(bpy.ops.geoblender.core_show_decisions.poll())
        self.assertFalse(bpy.ops.geoblender.core_add_decision.poll())
        self.show_decisions()
        layout = draw(getattr(bpy.types, DECISIONS_PANEL), bpy.context)
        (button,) = [item for item in layout.of_kind("operator") if item.target == ADD_DECISION]
        self.assertFalse(button.enabled)
        self.assertTrue([line for line in self.labels(layout)
                         if line.startswith("Proyecto en solo lectura: ")], self.labels(layout))
        self.assertEqual(vf.change_counter(project), counter)

    def test_catalog_entry(self) -> None:
        """RF-009-01, RF-009-03, RF-009-06, RF-009-11, RF-009-13 (plan 009 D-38): Nueva
        versión…, Cambiar estado…, Nueva revisión… (T21), Reproducir… (T23), Encargos y
        decisiones de la propiedad… (T24) y el menú contextual de la versión son de la entrada
        «009», entregada: sus clases reales, ni provisionales ni «Disponible en R-07», con su
        etiqueta del catálogo; Registrar decisión…, su orden interna."""
        cat = self.commands.catalog()
        internal = cat.commands[ADD_DECISION]
        self.assertEqual((internal.kind, internal.entry, internal.label_es),
                         ("internal", ENTRY, "Registrar decisión…"))
        for key in (NEW_VERSION, SET_STATE, NEW_REVISION, REPRODUCE, SHOW_DECISIONS,
                    ADD_DECISION, CONTEXT_MENU):
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
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_new_revision").bl_label,
                         "Nueva revisión…")
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_reproduce_version").bl_label,
                         REPRODUCE_LABEL)
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_show_decisions").bl_label,
                         "Encargos y decisiones de la propiedad…")
        self.assertEqual(getattr(bpy.types, "GEOBLENDER_OT_core_add_decision").bl_label,
                         "Registrar decisión…")
        self.assertTrue(hasattr(bpy.types, REPORT_PANEL))
        self.assertTrue(hasattr(bpy.types, DECISIONS_PANEL))


if __name__ == "__main__":
    unittest.main()
