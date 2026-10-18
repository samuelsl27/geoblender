# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión activa de la sesión (spec 009, T18; HU-009-1; RF-009-10; plan 009 §5.3.4, §5.5,
A11, D-8, D-25, D-38 y D-42).

Con un proyecto sintético nuevo (``core.project.create_project`` con los ajustes de
``tests.support.core_fixtures``) y sus versiones hechas como las harán las órdenes
(``core.versions.store`` y ``core.versions.freeze``): V01 «Definitiva» en BORRADOR (r1 abierta),
V02 «Ampliación» SUPERADO (r1 congelada y r2 cerrada al superarse), V03 «Fase sur» VIGENTE (r1
congelada y r2 abierta) y V04 «Norte» DESCARTADO (r1 cerrada). En ``blender -b`` no hay interfaz
(``docs/trampas.md`` §3): el control 8, su ventana, el menú y la barra de estado se dibujan con un
*layout* simulado, y ``load_post`` y ``save_pre`` corren al cargar y guardar la vista.

- **al abrir** (D-25): la versión activa es la de la vista (``Scene.geoblender.active_version_uid``,
  si la escena es de este proyecto y la versión existe), la de este equipo
  (``projects/<uid>/session.json`` de los datos de usuario), la VIGENTE o ninguna, en ese orden;
  elegirla no escribe en el proyecto;
- **cambiarla** desde el control 8 (los botones de su ventana, ``GEOBLENDER_PT_core_version``) y
  desde Proyecto ▸ Versiones ▸ Versión activa (``GEOBLENDER_MT_core_versions``) con
  ``geoblender.core_set_active_version``: todas las escenas del proyecto y los datos de usuario,
  nunca el proyecto (su contador de cambios y sus ficheros, iguales), también en solo lectura y
  con una versión SUPERADO o DESCARTADO, para consultar (D-42); «Sin versión»; una versión que no
  existe se rechaza con su texto y nada cambia;
- **el control** dibuja «V03.r2» con el icono de su estado (``gb_state_<estado>``; en ``-b``, su
  reserva nativa) y solo el icono en el nivel C; sin versiones, «Sin versión»; **la barra de
  estado**, tras el nombre del proyecto, «V03.r2 VIGENTE» (en inglés, «V03.r2 CURRENT»), que abre
  la ventana de la versión activa;
- los textos **caben** a 1920 px con escala 1,0 y 1,25: el del control no pasa del ancho que
  reserva el modelo de la barra superior (el de «Versión activa»), la barra de estado llena de la
  008 cabe con la versión y la ventana, en su ancho;
- **la vista**: al guardarla lleva la versión activa de la sesión (``save_pre``) y al cargarla
  ``load_post`` vuelve a elegir: la suya o, si no trae ninguna, la de este equipo;
- **registro y desregistro sin rastro**: las clases reales de la entrada «009», entregada (ni
  provisionales ni «Disponible en R-07»), ``Scene.geoblender.active_version_uid``,
  ``Collection.geoblender`` y ``WindowManager.geoblender_version_panels``, los manejadores
  ``@persistent``, la escucha del proyecto y de los indicadores y el texto del control;
  deshabilitada, la huella de Blender como al principio de la sesión de pruebas.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.blender.test_statusbar import RESERVED_PX, drawn_px
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import fingerprint_diff
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, Item, draw
from tests.support.trees import temp_folder

PANEL = "GEOBLENDER_PT_core_version"
MENU = "GEOBLENDER_MT_core_versions"
SET_ACTIVE = "geoblender.core_set_active_version"
ENTRY = "009"
ENTRY_TITLE = ("Versions, revisions and snapshots", "Versiones, revisiones e instantáneas")
PROJECT_NAME = "Cantera Prueba"  # el de tests.support.core_fixtures
REASON = "Alternativa de la prueba de la sesión"
NO_VERSION = "Sin versión"
REGION_PX = 1920.0
VERSIONS = (("definitiva", "Definitiva"), ("ampliacion", "Ampliación"), ("sur", "Fase sur"),
            ("norte", "Norte"))
"""El rasgo y el título de V01 a V04."""
# El nombre de cada versión en su ventana y en el menú, con su estado y su revisión (A11).
NAMES = {
    "V01": "V01 · Definitiva [BORRADOR] r1",
    "V02": "V02 · Ampliación [SUPERADO] r2",
    "V03": "V03 · Fase sur [VIGENTE] r2",
    "V04": "V04 · Norte [DESCARTADO] r1",
}
# Lo que dice el control 8 y la barra de estado de cada una.
CONTROL = {"V01": "V01.r1", "V02": "V02.r2", "V03": "V03.r2", "V04": "V04.r1"}
STATUS = {"V01": "V01.r1 BORRADOR", "V02": "V02.r2 SUPERADO", "V03": "V03.r2 VIGENTE",
          "V04": "V04.r1 DESCARTADO"}
# El icono propio de cada estado y su reserva nativa (icons.toml), la que se ve en -b.
ICONS = {"V01": ("gb_state_draft", "COLLECTION_COLOR_03"),
         "V02": ("gb_state_superseded", "RADIOBUT_OFF"),
         "V03": ("gb_state_current", "COLLECTION_COLOR_04"),
         "V04": ("gb_state_discarded", "COLLECTION_COLOR_08")}
NO_VERSION_ICON = "RADIOBUT_ON"  # la reserva del icono del control (sin versión)
LIST_BLANK = "BLANK1"  # «Sin versión» en la lista, alineada con las versiones
FUTURE = ("geoblender.core_new_version", "geoblender.core_new_revision",
          "geoblender.core_set_version_state", "geoblender.core_reproduce_version",
          "geoblender.res_compare_versions")
"""Las órdenes de la ventana: Nueva versión… y Cambiar estado… ya llegaron (T19); las demás,
después (T21, T23; Comparar es de R-62)."""
ARRIVED = ("geoblender.core_new_version", "geoblender.core_set_version_state")
"""Las órdenes de la ventana que ya tienen su clase real (T19, ``test_versions_ops``)."""


def ext(name: str) -> Any:
    """El módulo ``name`` de la copia de la extensión que importó Blender."""
    return vf.extension(name)


def drain(steps: Any) -> Any:
    """Avanza unos pasos (``Progress``) hasta el final y devuelve el resultado del último."""
    last = None
    for step in steps:
        last = step
    return None if last is None else last.result


def files(root: Path) -> dict[str, tuple[int, str, int]]:
    """Cada fichero de la carpeta del proyecto, con su tamaño, su huella y su fecha (ns)."""
    found: dict[str, tuple[int, str, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (
                stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns)
    return found


def bar_context(width: float = REGION_PX) -> SimpleNamespace:
    """La barra superior o la de estado de una ventana en modo Geoblender de ``width`` px."""
    window = bpy.context.window_manager.windows[0]
    return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True,
                                                     use_filter_by_owner=False),
                           screen=window.screen, region=SimpleNamespace(width=width),
                           area=None, scene=bpy.context.scene, window=window,
                           space_data=None, preferences=bpy.context.preferences)


class VersionsSessionTest(unittest.TestCase):
    """La extensión habilitada una vez; en cada prueba, su proyecto con sus versiones."""

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
        if not blender_ext.is_enabled():  # tras la prueba del registro, que la deshabilita
            blender_ext.enable()
        self.sv = ext("bl.scene.versions")
        self.ps = ext("bl.scene.project_session")
        self.panels = ext("bl.ui.version_panels")
        self.i18n = ext("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v9s-")
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(self.ps.close)

    # --- El proyecto ---------------------------------------------------------------------------

    def project(self, *, versions: bool = True) -> Any:
        """Un proyecto nuevo en escritura (aún no en la sesión) y, con ``versions``, V01 a V04
        (:attr:`versions`, por código)."""
        parent = self.folder / "proyectos"
        parent.mkdir()
        core_project = ext("core.project")
        project = core_project.create_project(
            parent, core_project.ProjectSettings(**settings_values()), self.ps.session(),
            self.ps.userdata()).project
        self.addCleanup(project.close)
        self.versions: dict[str, Any] = {}
        if versions:
            self.make_versions(project)
        return project

    def write(self, project: Any, work: Any) -> Any:
        with project.write_transaction() as conn:
            return work(conn)

    def make_versions(self, project: Any) -> None:
        """V01 a V04 como las dejarán las órdenes: V02 y después V03 congeladas y declaradas
        VIGENTE (V02 pasa a SUPERADO y su r2 se cierra), V04 descartada."""
        store = ext("core.versions.store")
        freeze = ext("core.versions.freeze")
        made = []
        for feature, title in VERSIONS:
            version, _revision = self.write(project, lambda conn, f=feature, t=title:
                                            store.create_version(conn, project, feature=f,
                                                                 title=t, reason=REASON))
            made.append(version)
        for version in made[1:3]:
            outcome = drain(freeze.freeze_steps(project, version.uid, reason="Entrega"))
            self.assertFalse(outcome.cancelled)
            self.write(project, lambda conn, uid=version.uid:
                       store.set_status(conn, project, uid, "VIGENTE"))
        self.write(project, lambda conn: store.set_status(conn, project, made[3].uid,
                                                          "DESCARTADO", reason="No sigue"))
        project.refresh_header()
        read = ext("core.versions.read")
        with project.read() as conn:
            self.versions = {version.code: version for version in read.versions(conn)}
        self.assertEqual({code: str(version.status) for code, version in self.versions.items()},
                         {"V01": "BORRADOR", "V02": "SUPERADO", "V03": "VIGENTE",
                          "V04": "DESCARTADO"})

    def uid(self, code: str) -> str:
        return self.versions[code].uid

    # --- Lo que se ve --------------------------------------------------------------------------

    def control(self, level: str = "B") -> Item:
        """El control 8 dibujado en la barra superior en el nivel ``level``."""
        layout = FakeLayout()
        width = ext("core.catalog.width")
        ext("bl.ui.quick_access").draw_project(layout, bar_context(), width.Level[level])
        (found,) = [item for item in layout.items if item.target == PANEL]
        self.assertEqual(found.kind, "popover")
        return found

    def statusbar(self, width: float = REGION_PX) -> FakeLayout:
        layout = FakeLayout()
        ext("bl.ui.statusbar").draw_statusbar(SimpleNamespace(layout=layout), bar_context(width))
        return layout

    def panel(self) -> FakeLayout:
        return draw(getattr(bpy.types, PANEL), bpy.context)

    def menu(self) -> FakeLayout:
        return draw(getattr(bpy.types, MENU), bpy.context)

    @staticmethod
    def choices(layout: FakeLayout) -> list[Item]:
        """Los botones que eligen la versión activa (las versiones y «Sin versión»)."""
        return [item for item in layout.of_kind("operator") if item.target == SET_ACTIVE]

    def click(self, item: Item) -> set[str]:
        """Lo que hace pulsar ``item``: la orden con las propiedades que le puso el dibujo."""
        return bpy.ops.geoblender.core_set_active_version(**vars(item.properties))

    def scene_values(self) -> list[str]:
        return [scene.geoblender.active_version_uid for scene in bpy.data.scenes]

    def remembered(self, project: Any) -> str | None:
        return self.ps.userdata().active_version(project.uid)

    # --- Pruebas -------------------------------------------------------------------------------

    def test_chosen_on_open_from_the_view_the_computer_the_current_or_none(self) -> None:
        """RF-009-10 (D-25, D-8): al abrir el proyecto en la sesión, la versión activa es la de
        la vista (la de su escena, si es de este proyecto y existe); si no, la de este equipo
        (los datos de usuario); si no, la VIGENTE; si no, ninguna. Elegirla no escribe en el
        proyecto ni cambia lo que recuerda el equipo; una versión de otro proyecto (en la escena
        o en los datos de usuario) o una escena de otro proyecto no cuentan."""
        project = self.project()
        scene = bpy.context.scene
        userdata = self.ps.userdata()
        scene.geoblender.project_uid = project.uid  # una vista de este proyecto
        scene.geoblender.active_version_uid = self.uid("V01")
        userdata.set_active_version(project.uid, self.uid("V04"))
        counter, before = vf.change_counter(project), files(project.root)
        self.ps.attach(project)
        self.assertEqual(self.sv.active_version(), self.uid("V01"))  # la de la vista
        self.assertEqual(self.control().text, CONTROL["V01"])
        self.assertEqual(self.remembered(project), self.uid("V04"))
        self.assertEqual((vf.change_counter(project), files(project.root)), (counter, before))

        choose = self.sv.choose_on_open
        scene.geoblender.active_version_uid = ""
        self.assertEqual(choose(project), self.uid("V04"))  # la de este equipo
        userdata.set_active_version(project.uid, None)
        self.assertEqual(choose(project), self.uid("V03"))  # la VIGENTE
        foreign = ext("core.ids").new_uid()  # una versión de otro proyecto
        scene.geoblender.active_version_uid = foreign
        userdata.set_active_version(project.uid, foreign)
        self.assertEqual(choose(project), self.uid("V03"))
        scene.geoblender.active_version_uid = self.uid("V01")
        scene.geoblender.project_uid = ext("core.ids").new_uid()  # una escena de otro proyecto
        self.assertEqual(choose(project), self.uid("V03"))
        scene.geoblender.project_uid = project.uid
        self.assertEqual(choose(project), self.uid("V01"))
        self.assertEqual((vf.change_counter(project), files(project.root)), (counter, before))

        # Sin VIGENTE (se descarta V03) ni nada que elegir: ninguna.
        store = ext("core.versions.store")
        self.write(project, lambda conn: store.set_status(conn, project, self.uid("V03"),
                                                          "DESCARTADO", reason="Prueba"))
        scene.geoblender.active_version_uid = ""
        userdata.set_active_version(project.uid, None)
        counter = vf.change_counter(project)
        self.assertIsNone(choose(project))
        self.assertEqual(vf.change_counter(project), counter)

    def test_changed_from_the_control_and_the_menu_without_writing_the_project(self) -> None:
        """RF-009-10 (D-8, D-42): la ventana del control 8 lista las versiones con su estado y su
        revisión, el icono de su estado y la activa hundida, y «Sin versión»; las revisiones de la
        activa; Nueva versión… y Cambiar estado… (T19) y las órdenes que llegan después,
        desactivadas. Elegir desde ella y desde
        Proyecto ▸ Versiones ▸ Versión activa cambia la versión activa en todas las escenas del
        proyecto y en los datos de usuario, sin escribir nada en el proyecto (contador de cambios
        y ficheros), también en solo lectura y con una SUPERADO o DESCARTADO; una que no existe
        se rechaza con su texto sin cambiar nada; sin proyecto, la orden no está disponible."""
        project = self.project()
        self.ps.attach(project)
        self.assertEqual(self.sv.active_version(), self.uid("V03"))  # la VIGENTE
        other = bpy.data.scenes.new("Otra vista")
        ext("bl.scene.georef").sync_scenes(project)
        unrelated = bpy.data.scenes.new("De nadie")  # sin proyecto: no se toca
        unrelated.geoblender.project_uid = ""
        counter, before = vf.change_counter(project), files(project.root)

        # La ventana del control 8.
        panel = self.panel()
        buttons = self.choices(panel)
        self.assertEqual([item.text for item in buttons], [*NAMES.values(), NO_VERSION])
        self.assertEqual([item.properties.version_uid for item in buttons],
                         [*(version.uid for version in self.versions.values()), ""])
        self.assertEqual([bool(item.options.get("depress")) for item in buttons],
                         [False, False, True, False, False])
        self.assertEqual([item.icon for item in buttons],
                         [*(fallback for _own, fallback in ICONS.values()), LIST_BLANK])
        labels = [item.text for item in panel.of_kind("label")]
        self.assertEqual(labels, ["Revisiones de V03", "congelada: V03.r1", "en curso (V03.r2)"])
        later = {item.target: item for item in panel.items if item.target in FUTURE}
        self.assertEqual(set(later), set(FUTURE))
        self.assertEqual({target for target, item in later.items() if item.enabled},
                         set(ARRIVED))

        # Desde el control: V01.
        self.assertEqual(self.click(buttons[0]), {"FINISHED"})
        self.assertEqual(self.sv.active_version(), self.uid("V01"))
        self.assertEqual(bpy.context.scene.geoblender.active_version_uid, self.uid("V01"))
        self.assertEqual(other.geoblender.active_version_uid, self.uid("V01"))
        self.assertEqual(unrelated.geoblender.active_version_uid, "")
        self.assertEqual(self.remembered(project), self.uid("V01"))
        self.assertEqual([item.text for item in self.panel().of_kind("label")],
                         ["Revisiones de V01", "en curso (V01.r1)"])

        # Desde el menú: la activa lo dice; V04, DESCARTADO, para consultar (D-42).
        items = self.choices(self.menu())
        self.assertEqual([item.text for item in items],
                         [f"{NAMES['V01']} · activa", *list(NAMES.values())[1:], NO_VERSION])
        self.assertEqual(self.click(items[3]), {"FINISHED"})
        self.assertEqual(self.sv.active_version(), self.uid("V04"))
        self.assertEqual(self.control().text, CONTROL["V04"])
        self.assertEqual(self.remembered(project), self.uid("V04"))

        # En solo lectura, igual: V02 (SUPERADO) y «Sin versión».
        project.set_read_only(ext("core.project").ReadOnlyCode.REQUESTED, "prueba")
        self.assertEqual(self.click(self.choices(self.menu())[1]), {"FINISHED"})
        self.assertEqual(self.sv.active_version(), self.uid("V02"))
        self.assertEqual(self.remembered(project), self.uid("V02"))
        self.assertEqual(self.click(self.choices(self.panel())[-1]), {"FINISHED"})
        self.assertIsNone(self.sv.active_version())
        self.assertIsNone(self.remembered(project))
        self.assertEqual(self.scene_values(), ["", "", ""])
        self.assertEqual(self.control().text, NO_VERSION)
        self.assertEqual([item.text for item in self.panel().of_kind("label")], [])

        # Una versión que no existe: rechazada con su texto; nada cambia.
        foreign = ext("core.ids").new_uid()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_active_version(version_uid=foreign)
        self.assertIn(f"No hay ninguna versión {foreign} en el proyecto", str(caught.exception))
        self.assertIsNone(self.sv.active_version())
        # Sin decir cuál (F3, un guion): no cambia nada.
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(), {"CANCELLED"})
        self.assertIsNone(self.sv.active_version())
        self.assertEqual((vf.change_counter(project), files(project.root)), (counter, before))

        # Sin proyecto, la orden no está disponible.
        self.ps.close()
        self.assertFalse(bpy.ops.geoblender.core_set_active_version.poll())
        self.assertIsNone(self.sv.active_version())

    def test_control_and_status_bar_show_the_active_version(self) -> None:
        """RF-009-10: sin versiones, el control 8 y la barra de estado dicen «Sin versión»; con
        una activa, el control «V03.r2» con el icono de su estado (el propio, o su reserva sin
        interfaz) y, en el nivel C, solo el icono; la barra de estado, tras el nombre del
        proyecto, «V03.r2 VIGENTE», que abre la ventana de la versión activa; cada estado con
        su icono y su texto, también en inglés. Las versiones nuevas se ven tras la lectura de
        los indicadores (``bl.ui.provenance``), que la avisa."""
        project = self.project(versions=False)
        self.ps.attach(project)
        self.assertIsNone(self.sv.active_version())
        control = self.control()
        self.assertEqual((control.text, control.icon), (NO_VERSION, NO_VERSION_ICON))
        bar = self.statusbar()
        self.assertEqual(bar.texts()[:3], [PROJECT_NAME, NO_VERSION, "EPSG:25830"])
        (version,) = [item for item in bar.items if item.target == PANEL]
        self.assertEqual((version.kind, version.text), ("popover", NO_VERSION))

        self.make_versions(project)
        self.assertEqual([item.text for item in self.choices(self.menu())],
                         [f"{NO_VERSION} · activa"])  # aún sin leer
        self.panels.on_project_read(project)  # lo que hace la lectura de los indicadores
        self.assertEqual(len(self.choices(self.menu())), 5)
        self.assertIsNone(self.sv.active_version())  # se elige al abrir, no al leer
        for code in self.versions:
            with self.subTest(code=code):
                self.assertEqual(bpy.ops.geoblender.core_set_active_version(
                    version_uid=self.uid(code)), {"FINISHED"})
                control = self.control()
                self.assertEqual((control.text, control.icon), (CONTROL[code], ICONS[code][1]))
                self.assertEqual(self.control("C").text, "")
                self.assertEqual(self.control("C").icon, ICONS[code][1])
                self.assertEqual(self.statusbar().texts()[:2], [PROJECT_NAME, STATUS[code]])
        own, fallback = ICONS["V04"]
        icons = ext("bl.ui.icons")
        with mock.patch.object(icons, "icon_id", side_effect=lambda name: 42 if name == own
                               else 0):
            control = self.control()
        self.assertEqual((control.options.get("icon_value"), control.icon), (42, "NONE"))
        self.i18n.set_language("en")
        bpy.ops.geoblender.core_set_active_version(version_uid=self.uid("V03"))
        self.assertEqual(self.statusbar().texts()[:2], [PROJECT_NAME, "V03.r2 CURRENT"])
        bpy.ops.geoblender.core_set_active_version(version_uid="")
        self.assertEqual(self.control().text, "No version")
        self.assertEqual(self.statusbar().texts()[1], "No version")

        # Sin proyecto: el control vuelve a su título y la barra de estado no dice versión.
        self.ps.close()
        self.i18n.set_language("es")
        self.assertEqual(self.control().text, "Versión activa")
        self.assertEqual([item for item in self.statusbar().items if item.target == PANEL], [])

    def test_texts_fit_at_1920_px(self) -> None:
        """RF-009-10 (M1; plan §5.5): a 1920 px con escala 1,0 y 1,25, el texto del control 8
        (cada versión y «Sin versión», en español y en inglés) no pasa del ancho de «Versión
        activa» que reserva el modelo de la barra superior (``core.catalog.width``); la barra de
        estado llena de la 008 (una entrada cambiada, tres obsoletos, la comprobación al 40 % y
        un trabajo) cabe con «V03.r2 VIGENTE» en lo que deja Blender; y cada texto de la ventana
        de la versión activa cabe en su ancho."""
        project = self.project()
        self.ps.attach(project)
        labels = ext("bl.ui.labels")
        catalog = ext("bl.ui.commands").catalog()
        for language in ("es", "en"):
            self.i18n.set_language(language)
            budget = self.i18n.tr(catalog.commands[PANEL].label)
            for code in (*self.versions, None):
                bpy.ops.geoblender.core_set_active_version(
                    version_uid="" if code is None else self.uid(code))
                text = self.control().text
                for scale in at_scales():
                    with self.subTest(language=language, code=code, scale=scale):
                        self.assertLessEqual(labels.label_px(text, icon=True, scale=scale),
                                             labels.label_px(budget, icon=True, scale=scale))
        self.i18n.set_language("es")

        bpy.ops.geoblender.core_set_active_version(version_uid=self.uid("V03"))
        provenance = ext("bl.ui.provenance")
        jobs = ext("bl.ui.jobs")
        counts = ext("core.provenance.stale").Counts(stale=3, figures=0, review=0,
                                                     inputs_changed=1)
        session = SimpleNamespace(percent=40, status_text=lambda: "Comprobando el proyecto… 40 %")
        current = SimpleNamespace(name="Autodiagnóstico: suma de 10 s", state="running",
                                  message="Trozo 16 de 50")
        view = SimpleNamespace(visible=True, active=2, current=current, percent=40, notice=None,
                               ending=None)
        compat = ext("bl.compat")
        with mock.patch.object(provenance._STATE, "counts", counts), \
                mock.patch.object(ext("bl.ops.core_provenance"), "SESSION", session), \
                mock.patch.object(jobs, "current_view", return_value=view):
            for scale in (1.0, 1.25):
                with self.subTest(scale=scale), \
                        mock.patch.object(compat, "ui_scale", return_value=scale):
                    layout = self.statusbar()
                    self.assertIn(STATUS["V03"], layout.texts())
                    self.assertLessEqual(drawn_px(layout.items),
                                         REGION_PX / scale - RESERVED_PX)

        panel = getattr(bpy.types, PANEL)
        width = labels.dialog_width(panel.bl_ui_units_x * compat.UI_UNIT_PX)
        layout = self.panel()
        for scale in at_scales():
            assert_fits(self, layout, width, scale=scale)
            for item in layout.items:
                if item.kind in ("operator", "popover", "menu") and item.text:
                    with self.subTest(text=item.text, scale=scale):
                        self.assertLessEqual(labels.label_px(item.text, icon=True, scale=scale),
                                             width)

    def test_the_view_keeps_the_active_version(self) -> None:
        """RF-009-10 (D-25, D-8; plan A11): al guardar la vista, sus escenas llevan la versión
        activa de la sesión aunque una escena la hubiera perdido (Ctrl+Z, una escena nueva:
        ``save_pre``); al cargarla, ``load_post`` vuelve a elegir la suya; y al cargar un fichero
        sin versión (la escena de fábrica), la de este equipo."""
        project = self.project()
        self.ps.attach(project)
        bpy.ops.geoblender.core_set_active_version(version_uid=self.uid("V01"))
        bpy.context.scene.geoblender.active_version_uid = ""  # como tras deshacer
        view = project.root / "scenes" / "sesion.blend"
        view.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(view)), {"FINISHED"})
        self.assertEqual(bpy.context.scene.geoblender.active_version_uid, self.uid("V01"))
        bpy.ops.geoblender.core_set_active_version(version_uid=self.uid("V04"))
        self.assertEqual(self.remembered(project), self.uid("V04"))

        blender_ext.load_file(view)
        self.assertIs(self.ps.current(), project)  # la vista es de este proyecto
        self.assertEqual(self.sv.active_version(), self.uid("V01"))
        self.assertEqual(self.control().text, CONTROL["V01"])
        self.assertEqual(self.remembered(project), self.uid("V04"))  # elegir no lo cambia

        blender_ext.load_file()  # la escena de fábrica: sin versión que elegir
        self.assertIs(self.ps.current(), project)
        self.assertEqual(self.sv.active_version(), self.uid("V04"))
        self.assertEqual(bpy.context.scene.geoblender.active_version_uid, self.uid("V04"))

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-009-10 (plan §5.2.7, §5.3.4, §5.3.5, D-38), principio 8: habilitada, la entrada
        «009» está entregada con su título y la versión activa es suya y real (la ventana del
        control 8, el menú y la orden, ni provisionales ni «Disponible en R-07»); la escena
        guarda ``active_version_uid`` en texto; ``Collection.geoblender`` marca la colección de
        una versión (``version_id``: ``bl.ui.context.collection_kind``); las filas de la ventana
        viven en ``WindowManager.geoblender_version_panels``; están los manejadores
        ``@persistent`` de ``load_post`` y ``save_pre``, la escucha del proyecto de la sesión y
        la de los indicadores y el texto del control 8. Deshabilitada, nada de eso queda y la
        huella de Blender es la del principio de la sesión de pruebas."""
        blender_ext.enable()
        commands = ext("bl.ui.commands")
        cat = commands.catalog()
        entry = cat.entries[ENTRY]
        self.assertEqual((entry.title, entry.title_es, entry.delivered), (*ENTRY_TITLE, True))
        for key in (PANEL, MENU, SET_ACTIVE):
            with self.subTest(key=key):
                self.assertEqual(cat.commands[key].entry, ENTRY)
                cls = commands.registered_class(key)
                self.assertIsNotNone(cls)
                self.assertFalse(commands.is_provisional(cls))
                self.assertTrue(commands.is_available(key))
                self.assertNotIn("Disponible en", cls.bl_description)
        for key in FUTURE[:-1]:  # las demás órdenes de la 009, aún en R-07 hasta su tarea
            self.assertEqual(cat.commands[key].entry, ENTRY if key in ARRIVED else "R-07")
        self.assertEqual(getattr(bpy.types, PANEL).bl_label, "Versión activa")
        scene_property = ext("bl.props.core").SCENE_PROPERTY
        props = bpy.types.Scene.bl_rna.properties[scene_property].fixed_type.properties
        self.assertEqual(props["active_version_uid"].type, "STRING")
        collection = bpy.data.collections.new("V01 · Definitiva")
        context_mod = ext("bl.ui.context")
        self.assertEqual(context_mod.collection_kind(collection), "")
        collection.geoblender.version_id = ext("core.ids").new_uid()
        self.assertEqual(context_mod.collection_kind(collection), context_mod.VERSION_KIND)
        bpy.data.collections.remove(collection)
        props_versions = ext("bl.props.versions")
        self.assertTrue(hasattr(bpy.context.window_manager,
                                props_versions.WINDOW_MANAGER_PROPERTY))
        for handlers, function in ((bpy.app.handlers.load_post, self.sv.on_load_post),
                                   (bpy.app.handlers.save_pre, self.sv.on_save_pre)):
            self.assertIn(function, handlers)
            self.assertTrue(hasattr(function, "_bpy_persistent"))
        self.assertIn(self.sv.on_project_changed, self.ps.listeners())
        provenance = ext("bl.ui.provenance")
        self.assertIn(self.panels.on_project_read, provenance.change_listeners())
        quick = ext("bl.ui.quick_access")
        self.assertIs(quick.label_provider(PANEL), self.panels.control_label)
        self.assertIn(self.panels.redraw, self.sv.listeners())

        blender_ext.disable()
        self.assertNotIn(self.sv.on_load_post, bpy.app.handlers.load_post)
        self.assertNotIn(self.sv.on_save_pre, bpy.app.handlers.save_pre)
        self.assertNotIn(self.sv.on_project_changed, self.ps.listeners())
        self.assertNotIn(self.panels.on_project_read, provenance.change_listeners())
        self.assertIsNone(quick.label_provider(PANEL))
        self.assertEqual(self.sv.listeners(), ())
        self.assertFalse(hasattr(bpy.types.Collection, props_versions.COLLECTION_PROPERTY))
        self.assertFalse(hasattr(bpy.types.WindowManager,
                                 props_versions.WINDOW_MANAGER_PROPERTY))
        self.assertFalse(hasattr(bpy.types, "GEOBLENDER_OT_core_set_active_version"))
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()
