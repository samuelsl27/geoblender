# SPDX-License-Identifier: GPL-3.0-or-later
"""«Perfil de pista…» en Blender (spec 017, T29; HU-017-1; RF-017-07, RF-017-08, RF-017-29, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M2).

La orden ``geoblender.des_edit_road_profile`` abre la ventana ``GEOBLENDER_PT_des_road_profiles`` (lo ya leído del proyecto: nada se lee ni se
calcula al dibujar) y la interna ``geoblender.des_save_road_profile`` crea, completa y renombra perfiles con
``design.road_profiles.edit_road_profiles`` (``des.edit_road_profiles``: una operación **de proyecto** en una transacción); cambiar un valor que
ya existe es ``core_set_parameter`` (la 008, con «¿Para el proyecto o solo para V01?» de la 009). Es la copia, para la pista, de «Perfiles de banco…»
de la 013 (``test_design_profiles.py``). Un proyecto por clase (24 × 24 celdas de 1 m, V01 y V02) y las pruebas, en el orden de sus letras sobre el
mismo estado. **Los valores son los del proyecto de referencia de IMGA** (``tests.support.road_data.PROFILE``, ``spec.md`` §11: **solo para pruebas**;
la estación, pm y el alcance son HIPÓTESIS de la prueba): ninguno es un valor por defecto del producto (D-2).

- RF-017-29, RF-015-28 (a): las dos órdenes y la ventana están registradas (clases reales) y la orden que abre la ventana dice por qué no está
  disponible sin proyecto; sus propiedades tienen nombre y descripción y los decimales son texto.
- RF-017-07 (b): crear ``PISTA_PRINCIPAL`` guarda su fila (nombre y código inmutable) y sus trece valores como parámetros del proyecto, **con su tipo,
  su fuente y su decisor**, sin valor por defecto (el factor de malla y la métrica quedan sin fila y valen sus defectos); la ventana lo enseña con su
  resumen, su clase normativa, su insignia, su ámbito y la fuente de cada valor.
- RF-017-08 (c): los derivados de la ventana (calzada f·A, sección, semianchura y la longitud mínima H/pd) son los del dominio, **no son parámetros**
  (ninguna fila) y no se editan (ningún botón); 10,5, 11,5, 5,75 y 300 m con el perfil de referencia y H = 30 m.
- RF-017-07, RF-009-24 (d): completar un perfil creado solo para V01 para el proyecto y cambiar un valor solo en V02 deja cada ámbito con el suyo.
- RF-017-07 (e): renombrar un perfil no cambia su código ni sus valores; el nombre es único sin distinguir mayúsculas.
- RF-017-07, RF-017-04 (f): un perfil sin nombre, con el nombre de otro, sin un valor, con uno fuera de rango, que no es un número o con los radios que
  no caben se rechaza **nombrando el perfil, el campo y el valor** y no deja nada (0 transacciones: ni un perfil, ni un parámetro, ni una operación).
- RF-017-07, RF-009-05 (g): el diálogo pregunta el ámbito, propone el decisor, no vuelve a pedir lo que el perfil ya tiene en el ámbito y no deja nada
  si no se acepta; sin versión activa, el perfil se crea para el proyecto y «solo la versión» se rechaza.
- RF-017-29, RF-015-28, RF-009-21 (h): la ventana dibuja la lista y los botones, y la orden y la ventana salen **desactivadas con su motivo** sin proyecto,
  con el proyecto en solo lectura y con la versión activa SUPERADO.
- RF-017-07 (i): el factor de malla y la métrica, si se dan, se guardan; con la métrica «por defecto» no.
- Principio 8 (z): desactivar Geoblender quita la orden, la ventana, la lista y las propiedades de la vista.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.road_data import PROFILE
from tests.support.trees import remove_tree

OPEN = "geoblender.des_edit_road_profile"
SAVE = "geoblender.des_save_road_profile"
PANEL = "GEOBLENDER_PT_des_road_profiles"
LIST = "GEOBLENDER_UL_des_road_profiles"
VIEW_PROPERTY = "geoblender_design"
REASON = "Prueba de los perfiles de pista"
PERSON = "Samuel (IMGA)"
SOURCE = "Proyecto de referencia de IMGA (spec 017, solo pruebas)"
MAIN = "PISTA_PRINCIPAL"
ACCESS = "ACCESO_AL_TAJO"
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
REFERENCE = {  # PROFILE (spec 017 §11) tecleado como lo teclea una persona, con coma decimal
    "vehicle": "3,5", "lane_factor": "3", "shoulder": "0", "windrow": "1", "max_gradient": "10", "station_step": "1",
    "max_mean_gradient": "10", "curve_radius": "20", "min_radius": "12", "cut_angle": "60", "fill_angle": "35",
    "reach": "60", "road_class": "Pista de acceso"}
OTHER = {  # calzada 6 m, sección 7 m, semianchura 3,5 m y pd 8 %: 12,5 m por cada metro de desnivel
    "vehicle": "3", "lane_factor": "2", "shoulder": "0.5", "windrow": "0.5", "max_gradient": "8", "station_step": "2",
    "max_mean_gradient": "7", "curve_radius": "15", "min_radius": "4", "cut_angle": "50", "fill_angle": "30",
    "reach": "40", "road_class": "Acceso al tajo"}
VALUE_KEYS = {  # la propiedad del diálogo → el valor del perfil (último segmento de su clave)
    "vehicle": "vehicle_width_m", "lane_factor": "lane_factor", "shoulder": "shoulder_m", "windrow": "berm_m",
    "max_gradient": "max_gradient_pct", "station_step": "station_step_m", "max_mean_gradient": "max_mean_gradient_pct",
    "curve_radius": "curve_radius_m", "min_radius": "min_radius_m", "cut_angle": "cut_angle_deg",
    "fill_angle": "fill_angle_deg", "reach": "reach_m", "road_class": "class", "mesh": "mesh_factor", "metric": "metric"}
PROPERTIES = {  # la propiedad → su nombre y su descripción (msgid en inglés; en español al registrarse)
    "name": ("Name", "Name of the profile, such as PISTA_PRINCIPAL: it can change, its code cannot"),
    "vehicle": ("Design vehicle width A (m)", "Width of the design vehicle in metres, more than 0"),
    "lane_factor": ("Carriageway factor f", "Factor that multiplies the width of the vehicle to give the carriageway, more than 0"),
    "shoulder": ("Shoulder width (m)", "Width of the shoulder in metres, 0 or more"),
    "windrow": ("Windrow width (m)", "Width of the windrow in metres, 0 or more"),
    "max_gradient": ("Maximum design gradient pd (%)", "Maximum gradient of the haul road in per cent, more than 0"),
    "station_step": ("Step of the level profile w (m)",
                     "Distance between the stations where the gradient is checked, in metres, more than 0"),
    "max_mean_gradient": ("Maximum mean gradient pm (%)", "Maximum mean gradient of the whole haul road in per cent, more than 0"),
    "curve_radius": ("Curve radius R (m)", "Radius of the curves in metres, more than 0"),
    "min_radius": ("Minimum radius Rmin (m)",
                   "Smallest radius allowed in metres, more than 0, at most R and at least the half width of the section"),
    "cut_angle": ("Cut angle (°)",
                  "Inclination of the cut slope at the edge of the haul road in degrees, between 0 and 90 (both excluded)"),
    "fill_angle": ("Fill angle (°)",
                   "Inclination of the fill slope at the edge of the haul road in degrees, between 0 and 90 (both excluded)"),
    "reach": ("Reach of the edge (m)", "How far the cut and fill slopes of the edge reach, in metres, more than 0"),
    "road_class": ("Normative class", "Class of the haul road in the standard it follows, such as «main» or «access to the pit»"),
    "mesh": ("Mesh factor", "Factor between 0 (excluded) and 1 that reduces the slope of the edge for the grid (empty: 1)"),
    "metric": ("Metric", "How the distance of the edge is measured: the exact Euclidean distance (the default) or the 5×5 chamfer"),
    "kind": ("Type", "Type of the values: adopted or hypothesis"),
    "source": ("Source", "Document, standard, person, operation or algorithm the values come from (empty: the decider)"),
    "source_kind": ("Source type", "Whether the source is a document, a standard, a person, an operation or an algorithm"),
    "decided_by": ("Decided by", "Who decided the values (the owner, a laboratory, a person)"),
    "reason": ("Reason", "Why the profile has these values (recorded in its history)"),
    "scope": ("Scope", "Whether the change is for the project or only for the active version (a parameter that its module admits "
                       "by version)"),
}
HIDDEN = {"code"}
"""Las que pone quien la lanza (el botón de la ventana): sin descripción propia que la persona lea."""
NUMBERS = ("vehicle", "lane_factor", "shoulder", "windrow", "max_gradient", "station_step", "max_mean_gradient", "curve_radius",
           "min_radius", "cut_angle", "fill_angle", "reach", "mesh")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class RoadProfilesTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 para toda la clase (las pruebas, en el orden de sus letras: cada una parte
    de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r29-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.road_profiles = _module("design.road_profiles")
        cls.params = _module("core.params")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(700_000.0, 4_400_000.0, 700_024.0, 4_400_024.0), grid_step_m=1.0))
        cls.project = core_project.create_project(folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva", title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa", title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(SAVE)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def counts(self) -> tuple[int, int, int]:
        """Operaciones, perfiles y parámetros de perfil de pista del proyecto (lo que un rechazo no cambia: 0 transacciones)."""
        profile_rows = 0
        with self.project.read() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'des_road_profile'").fetchone():
                profile_rows = int(conn.execute("SELECT count(*) FROM des_road_profile").fetchone()[0])
            operations = int(conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0])
            keys = int(conn.execute("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.roadprofile.%'").fetchone()[0])
        return operations, profile_rows, keys

    def save(self, **values: Any) -> set[str]:
        """La orden interna con una declaración completa (lo que no se da: ADOPTADO, de un documento, la persona, el proyecto)."""
        given = {"kind": "ADOPTADO", "source": SOURCE, "source_kind": "DOCUMENT", "decided_by": PERSON, "reason": REASON,
                 "scope": "PROJECT", **values}
        return bpy.ops.geoblender.des_save_road_profile(**given)

    def opened(self) -> Any:
        """Abre la ventana (en ``blender -b`` solo la vista) y devuelve la vista."""
        with mock.patch.object(self.des_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.des_edit_road_profile(), {"FINISHED"})
        return self.view

    def profile(self, name: str) -> Any:
        found = [item for item in self.opened().road_profiles if item.name == name]
        self.assertEqual(len(found), 1, f"{name}: {[item.name for item in self.view.road_profiles]}")
        return found[0]

    def line(self, item: Any, value: str) -> Any:
        """La línea del valor ``value`` (último segmento de su clave) de un perfil de la vista."""
        (found,) = [line for line in item.parameters if line.key.endswith(f".{value}")]
        return found

    def values_of(self, code: str) -> dict[str, tuple[Any, str, str]]:
        """Los valores del perfil ``code`` en el proyecto: último segmento → (valor, tipo, decisor)."""
        found = {}
        for key, value, kind, decided_by in self.rows(
                "SELECT key, value, kind, decided_by FROM gb_parameter WHERE key LIKE ? AND scope = 'project' ORDER BY key",
                f"des.roadprofile.{code}.%"):
            found[key.rsplit(".", 1)[1]] = (json.loads(value), kind, decided_by)
        return found

    def domain_profile(self, code: str, name: str, values: dict[str, str]) -> Any:
        """El perfil del dominio con lo tecleado (coma o punto decimal)."""
        typed: dict[str, Any] = {VALUE_KEYS[prop]: (text if prop == "road_class" else float(text.replace(",", ".")))
                                 for prop, text in values.items()}
        return self.road_profiles.RoadProfile.from_values(code, name, typed)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_and_the_window_are_registered(self) -> None:
        """RF-017-29, RF-015-28 (plan §5.3.3): «Perfil de pista…» y la interna que los guarda son clases reales de ``bl.ops.des`` (con la
        ventana y su lista) y de la operación ``des.edit_road_profiles``; sin proyecto, la orden no está disponible y dice por qué; las
        propiedades de la interna tienen nombre y descripción en español y **los decimales son texto** (``StringProperty``, trampa 1)."""
        provenance = _module("design.provenance")
        for idname in (OPEN, SAVE):
            with self.subTest(orden=idname):
                cls = self.commands.registered_class(idname)
                self.assertIn(cls, self.des_ops.classes)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
                self.assertEqual(cls.provenance_op_type, provenance.EDIT_ROAD_PROFILES)
                self.assertEqual(cls.bl_options & {"UNDO"}, set())  # escribe en el proyecto: Ctrl+Z no lo deshace (el diario lo apunta)
        self.assertEqual(self.commands.registered_class(OPEN).bl_idname, provenance.ROAD_PROFILE_COMMAND)
        self.assertIn("INTERNAL", self.cls.bl_options)
        for name in (PANEL, LIST):
            self.assertIsNotNone(getattr(bpy.types, name, None), name)
        self.assertTrue(bpy.ops.geoblender.des_edit_road_profile.poll())
        cls = self.commands.registered_class(OPEN)
        with mock.patch.object(cls, "poll_message_set") as said, \
                mock.patch.object(self.session, "write_unavailable", return_value="Abra un proyecto"), \
                mock.patch.object(self.des_ops, "write_unavailable", return_value="Abra un proyecto"):
            self.assertFalse(cls.poll(bpy.context))
        said.assert_called_once_with("Abra un proyecto")
        # las dos están en el catálogo, de la entrada 017 (entregada por la T33b): «Perfil de pista…» con su casa en Diseño ▸ Pistas y entidades y la interna de su ventana, sin ella
        catalog = self.commands.catalog()
        for idname, label, kind, home in ((OPEN, "Perfil de pista…", "operator", "GEOBLENDER_MT_ui_design"),
                                          (SAVE, "Guardar perfil de pista…", "internal", "")):
            command = catalog.commands[idname]
            self.assertEqual((command.kind, command.module, command.entry, command.home, command.label_es),
                             (kind, "des", "017", home, label))
            self.assertTrue(self.commands.is_available(idname), idname)
        # las propiedades (evaluadas, como las lee el registro): cada una con su nombre y su descripción, con traducción en messages.toml
        annotations = _module("bl.registry").annotations(self.cls)
        self.assertEqual({name for name in annotations if name not in HIDDEN}, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():
            with self.subTest(propiedad=prop):
                keywords = annotations[prop].keywords
                self.assertIn(keywords["name"], (label, self.i18n.translate("es", label)))
                self.assertIn(keywords["description"], (about, self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in NUMBERS:
            self.assertEqual(annotations[prop].function, bpy.props.StringProperty, prop)
        self.assertEqual(annotations["metric"].function, bpy.props.EnumProperty)

    def test_b_create_a_profile_with_its_values_and_their_source(self) -> None:
        """RF-017-07, D-2: crear ``PISTA_PRINCIPAL`` guarda su fila (nombre y código inmutable) y sus trece valores como parámetros del
        proyecto con su tipo, su fuente y su decisor (ningún valor por defecto: el factor de malla y la métrica no tienen fila); la ventana
        lo enseña con su resumen, su clase normativa, su insignia, su ámbito y la fuente de cada valor."""
        before = self.counts()
        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.save(name=MAIN, **REFERENCE), {"FINISHED"})
        self.assertEqual(self.counts(), (before[0] + 1, before[1] + 1, before[2] + 13))
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no la deshace: queda apuntada
        self.assertEqual(journal.entries[-1].label, "des.edit_road_profiles")
        self.assertEqual(self.rows("SELECT code, name FROM des_road_profile"), [("pista_principal", MAIN)])
        stored = self.values_of("pista_principal")
        self.assertEqual({name: value for name, (value, _k, _d) in stored.items()},
                         {"vehicle_width_m": 3.5, "lane_factor": 3.0, "shoulder_m": 0.0, "berm_m": 1.0, "max_gradient_pct": 10.0,
                          "station_step_m": 1.0, "max_mean_gradient_pct": 10.0, "curve_radius_m": 20.0, "min_radius_m": 12.0,
                          "cut_angle_deg": 60.0, "fill_angle_deg": 35.0, "reach_m": 60.0, "class": "Pista de acceso"})
        self.assertEqual({kind for _v, kind, _d in stored.values()}, {"ADOPTADO"})
        self.assertEqual({who for _v, _k, who in stored.values()}, {PERSON})
        self.assertEqual(self.rows("SELECT DISTINCT source, source_kind FROM gb_parameter WHERE key LIKE ? AND scope = 'project'",
                                   "des.roadprofile.pista_principal.%"), [(SOURCE, "document")])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_parameter WHERE key IN (?, ?)",
                                   "des.roadprofile.pista_principal.mesh_factor", "des.roadprofile.pista_principal.metric"), [(0,)])
        item = self.profile(MAIN)
        self.assertEqual(item.code, "pista_principal")
        self.assertEqual(item.road_class, "Pista de acceso")
        self.assertEqual(item.summary, "A 3,5 m · f 3 · pd 10 % · pm 10 % · Rmín 12 m")
        self.assertEqual(item.badge, "[ADO]")
        self.assertEqual(item.scope, "el proyecto")
        self.assertEqual(item.problem, "")
        self.assertEqual(len(item.parameters), 15)  # los quince valores, uno por línea
        vehicle = self.line(item, "vehicle_width_m")
        self.assertEqual(vehicle.text, "V01: — · proyecto: 3,5 m [ADO]")
        self.assertEqual(vehicle.source, f"Fuente: {SOURCE} · decidido por {PERSON}")
        self.assertTrue(vehicle.registered)
        self.assertEqual(self.line(item, "class").text, "V01: — · proyecto: Pista de acceso [ADO]")
        mesh = self.line(item, "mesh_factor")  # sin fila: lo que valdría por defecto, «sin confirmar», y sin fuente ni «Cambiar…»
        self.assertEqual((mesh.text, mesh.source, mesh.registered), ("1 [ADO] sin confirmar", "", False))
        self.assertEqual(self.line(item, "metric").text, "exact [ADO] sin confirmar")
        self.i18n.set_language("en")
        shown = self.profile(MAIN)
        self.assertEqual(shown.summary, "A 3.5 m · f 3 · pd 10 % · pm 10 % · Rmin 12 m")
        self.assertEqual(self.line(shown, "vehicle_width_m").source, f"Source: {SOURCE} · decided by {PERSON}")

    def test_c_derived_values_come_from_the_domain_and_are_not_parameters(self) -> None:
        """RF-017-08: la calzada f·A, la anchura de la sección, su semianchura y la longitud mínima H/pd que enseña la ventana son los del
        dominio (``design.road_profiles.derived``: 10,5, 11,5 y 5,75 m y 300 m con pd = 10 % y H = 30 m, los del proyecto de referencia), con
        error ≤ 10⁻⁹ relativo; **no son parámetros** (ninguna fila en el proyecto) y no se editan (ningún botón los acompaña)."""
        self.assertEqual(self.save(name=ACCESS, **OTHER), {"FINISHED"})
        by_name = {item.name: item for item in self.opened().road_profiles}
        self.assertEqual(list(by_name), [MAIN, ACCESS])
        self.assertEqual(by_name[MAIN].derived, "calzada 10,5 m · sección 11,5 m · semianchura 5,75 m")
        self.assertEqual(by_name[MAIN].min_length, "Longitud mínima H/pd: 10 m por cada metro de desnivel")
        self.assertEqual(by_name[ACCESS].derived, "calzada 6 m · sección 7 m · semianchura 3,5 m")
        self.assertEqual(by_name[ACCESS].min_length, "Longitud mínima H/pd: 12,5 m por cada metro de desnivel")
        # a mano, con f·A, la calzada más el arcén y el caballón, y H/pd; y los del dominio, con ≤ 10⁻⁹ relativo
        reference = self.road_profiles.derived(self.domain_profile("pista_principal", MAIN, REFERENCE))
        for found, expected in ((reference.carriageway_m, 3.0 * 3.5), (reference.section_m, 3.0 * 3.5 + 0.0 + 1.0),
                                (reference.half_width_m, (3.0 * 3.5 + 1.0) / 2.0), (reference.min_length_m(30.0), 30.0 / 0.10)):
            self.assertAlmostEqual(found / expected, 1.0, delta=1e-9)
        self.assertEqual((PROFILE.carriageway_m, PROFILE.section_m, PROFILE.half_section_m, reference.min_length_m(30.0)),
                         (10.5, 11.5, 5.75, 300.0))
        other = self.road_profiles.derived(self.domain_profile("acceso_al_tajo", ACCESS, OTHER))
        self.assertAlmostEqual(other.min_length_m(1.0), 12.5, delta=1e-9)
        self.assertEqual((other.carriageway_m, other.section_m, other.half_width_m), (6.0, 7.0, 3.5))
        # no son parámetros: ni una fila de más, ni una clave de los derivados; los valores son los quince
        names = {key.rsplit(".", 1)[1] for (key,) in self.rows("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE 'des.roadprofile.%'")}
        self.assertEqual(names, set(VALUE_KEYS.values()) - {"mesh_factor", "metric"})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.roadprofile.%' AND "
                                   "(key LIKE ? OR key LIKE ? OR key LIKE ?)", "%carriageway%", "%section%", "%half%"), [(0,)])
        # y en inglés
        self.i18n.set_language("en")
        english = {item.name: item for item in self.opened().road_profiles}
        self.assertEqual(english[MAIN].derived, "carriageway 10.5 m · section 11.5 m · half-width 5.75 m")
        self.assertEqual(english[ACCESS].min_length, "Minimum length H/pd: 12.5 m per metre of height difference")
        # la ventana dibuja los derivados sin ningún botón: lo único que se edita son los valores
        self.i18n.set_language("es")
        shown = self.opened()
        shown.road_profile_index = [item.name for item in shown.road_profiles].index(MAIN)
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        texts = layout.texts()
        self.assertIn("calzada 10,5 m · sección 11,5 m · semianchura 5,75 m", " ".join(texts))
        self.assertIn("Longitud mínima H/pd: 10 m por cada metro de desnivel", " ".join(texts))
        derived = [item for item in layout.items if item.kind == "label" and "semianchura" in item.text]
        self.assertTrue(derived)
        self.assertFalse(any(item.kind in ("prop", "operator") and "semianchura" in item.text for item in layout.items))
        changes = [item for item in layout.items if item.kind == "operator" and item.target == "geoblender.core_set_parameter"]
        self.assertEqual(len(changes), 13)  # «Cambiar…» solo de los trece valores con fila, ninguno de los derivados
        shown.road_profile_index = 0

    def test_d_complete_in_the_project_and_change_only_in_a_version(self) -> None:
        """RF-017-07, RF-009-24, RF-009-29: un perfil creado solo para V01 se completa para el proyecto con la misma orden; y cambiar un valor
        solo para V02 («¿Para el proyecto o solo para V02?») deja el del proyecto como estaba."""
        name, code = "SOLO_V01", "solo_v01"
        self.assertEqual(self.save(name=name, scope="VERSION", **REFERENCE), {"FINISHED"})
        self.assertEqual(self.values_of(code), {})  # nada en el proyecto
        item = self.profile(name)
        self.assertEqual(item.scope, "V01")
        self.assertEqual(self.line(item, "vehicle_width_m").text, "V01: 3,5 m [ADO] · proyecto: —")
        self.assertEqual(self.save(code=code, name=name, scope="PROJECT", source="", **REFERENCE), {"FINISHED"})
        # sin origen escrito, el decisor es el origen y es una persona
        self.assertEqual(self.rows("SELECT DISTINCT source, source_kind FROM gb_parameter WHERE key LIKE ? AND scope = 'project'",
                                   f"des.roadprofile.{code}.%"), [(PERSON, "person")])
        self.assertEqual(self.values_of(code)["vehicle_width_m"][0], 3.5)
        self.assertEqual(self.line(self.profile(name), "vehicle_width_m").text, "V01: 3,5 m [ADO] · proyecto: 3,5 m [ADO]")
        # cambiar uno solo en V02: la 008 con el ámbito de la 009
        self.set_active(self.v02)
        key = f"des.roadprofile.{code}.vehicle_width_m"
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value="3", kind="HIPOTESIS", source=SOURCE, source_kind="DOCUMENT", decided_by=PERSON, reason=REASON,
            scope="VERSION"), {"FINISHED"})
        self.assertEqual(self.values_of(code)["vehicle_width_m"][0], 3.5)  # el del proyecto, intacto
        # la ventana ya abierta se pone al día sola (la escucha de los indicadores), sin volver a leerla
        open_item = next(item for item in self.view.road_profiles if item.name == name)
        self.assertEqual(self.line(open_item, "vehicle_width_m").text, "V02: 3 m [HIP] · proyecto: 3,5 m [ADO]")
        item = self.profile(name)
        self.assertEqual(item.summary, "A 3 m · f 3 · pd 10 % · pm 10 % · Rmín 12 m")
        self.assertEqual(item.scope, "V02 y el proyecto")
        self.assertEqual(item.badge, "[HIP]")  # la del menos firme de sus valores
        self.assertEqual(item.derived, "calzada 9 m · sección 10 m · semianchura 5 m")  # los derivados siguen al valor de la versión
        self.set_active(self.v01)
        self.assertEqual(self.profile(name).badge, "[ADO]")
        self.assertEqual(self.profile(name).summary, "A 3,5 m · f 3 · pd 10 % · pm 10 % · Rmín 12 m")

    def test_e_rename_keeps_the_code_and_the_values_and_the_name_is_unique(self) -> None:
        """RF-017-07: renombrar un perfil (el nombre es libre y único sin distinguir mayúsculas, el código es inmutable) no toca sus
        parámetros; la ventana lo enseña con el nombre nuevo y un nombre repetido se rechaza sin dejar nada."""
        code = "solo_v01"
        before_values = self.values_of(code)
        with self.assertRaises(RuntimeError) as raised:  # el mismo nombre y ningún valor
            self.save(code=code, name="SOLO_V01")
        self.assertIn("Nada que cambiar en «SOLO_V01»", str(raised.exception))
        before = self.counts()
        with self.assertRaises(RuntimeError) as raised:  # el nombre de otro perfil, con otras mayúsculas
            self.save(code=code, name=MAIN.lower())
        for part in (code, MAIN.lower(), "pista_principal"):
            self.assertIn(part, str(raised.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.save(code=code, name="SOLO_V01_B"), {"FINISHED"})
        self.assertEqual(self.values_of(code), before_values)
        self.assertEqual(self.rows("SELECT code, name FROM des_road_profile WHERE code = ?", code), [(code, "SOLO_V01_B")])
        self.assertEqual(self.counts()[2], before[2])  # los valores, los mismos
        self.assertEqual(self.profile("SOLO_V01_B").code, code)
        self.assertEqual(self.rows("SELECT count(*) FROM des_road_profile"), [(3,)])

    def test_f_rejections_name_the_profile_the_field_and_the_value(self) -> None:
        """RF-017-07, RF-017-04: un perfil sin nombre, con el nombre de otro (sin distinguir mayúsculas), sin un valor, con uno fuera de rango o
        que no es un número, o con los radios que no caben, se rechaza **nombrando el perfil, el campo y el valor** y no deja nada: ni un perfil,
        ni un parámetro, ni una operación (0 transacciones)."""
        before = self.counts()
        key = "des.roadprofile.nuevo."
        cases = {
            "sin nombre": ({"name": "  ", **REFERENCE}, ("nombre",)),
            "repetido": ({"name": MAIN.lower(), **REFERENCE}, ("se llama", "pista_principal")),
            "sin pd": ({"name": "NUEVO", **{**REFERENCE, "max_gradient": ""}}, ("NUEVO", f"{key}max_gradient_pct", "no tiene valor")),
            "sin clase": ({"name": "NUEVO", **{**REFERENCE, "road_class": "  "}}, ("NUEVO", f"{key}class", "no tiene valor")),
            "pd de 0": ({"name": "NUEVO", **{**REFERENCE, "max_gradient": "0"}}, ("NUEVO", f"{key}max_gradient_pct", "= 0", "fuera de su rango")),
            "pd negativa": ({"name": "NUEVO", **{**REFERENCE, "max_gradient": "-4"}}, ("NUEVO", f"{key}max_gradient_pct", "-4")),
            "ángulo de 90°": ({"name": "NUEVO", **{**REFERENCE, "cut_angle": "90"}}, ("NUEVO", f"{key}cut_angle_deg", "90")),
            "ángulo de 0°": ({"name": "NUEVO", **{**REFERENCE, "fill_angle": "0"}}, ("NUEVO", f"{key}fill_angle_deg", "= 0")),
            "caballón negativo": ({"name": "NUEVO", **{**REFERENCE, "windrow": "-1"}}, ("NUEVO", f"{key}berm_m", "-1")),
            "factor de calzada de 0": ({"name": "NUEVO", **{**REFERENCE, "lane_factor": "0"}}, ("NUEVO", f"{key}lane_factor", "= 0")),
            "factor de malla de 2": ({"name": "NUEVO", **REFERENCE, "mesh": "2"}, ("NUEVO", f"{key}mesh_factor", "2")),
            "no es un número": ({"name": "NUEVO", **{**REFERENCE, "shoulder": "cero"}}, ("cero",)),
            "Rmín mayor que R": ({"name": "NUEVO", **{**REFERENCE, "min_radius": "25"}},
                                 ("NUEVO", f"{key}min_radius_m", "25", "mayor que el radio")),
            "Rmín menor que la semianchura": ({"name": "NUEVO", **{**REFERENCE, "min_radius": "5"}},
                                              ("NUEVO", f"{key}min_radius_m", "5", "semianchura")),
        }
        for label, (values, expected) in cases.items():
            with self.subTest(caso=label):
                with self.assertRaises(RuntimeError) as raised:
                    self.save(**values)
                message = str(raised.exception)
                for part in expected:
                    self.assertIn(part, message)
                self.assertEqual(self.counts(), before)
        # y en inglés, con el texto en inglés (no el español del error)
        self.i18n.set_language("en")
        with self.assertRaises(RuntimeError) as raised:
            self.save(name="NUEVO", **{**REFERENCE, "cut_angle": "95"})
        self.assertIn("is outside its range", str(raised.exception))
        self.assertIn(f"{key}cut_angle_deg", str(raised.exception))
        self.assertIn("95", str(raised.exception))
        self.i18n.set_language("es")
        self.assertEqual(self.counts(), before)
        # un perfil que no existe: un error del programa, dicho también sin dejar nada
        with self.assertRaises(RuntimeError):
            self.save(code="no_existe", name="OTRO")
        self.assertEqual(self.counts(), before)
        # un valor sin su origen: el del decisor; sin decisor, nada
        with self.assertRaises(RuntimeError):
            self.save(name="NUEVO", decided_by=" ", **REFERENCE)
        self.assertEqual(self.counts(), before)
        # completar un perfil con un valor fuera de rango: el perfil que existe, con su nombre, el campo y el valor
        with self.assertRaises(RuntimeError) as raised:
            self.save(code="pista_principal", name=MAIN, source="", max_gradient="150", scope="PROJECT")
        for part in (MAIN, "des.roadprofile.pista_principal.max_gradient_pct", "150"):
            self.assertIn(part, str(raised.exception))
        self.assertEqual(self.counts(), before)

    def test_g_the_dialog_asks_the_scope_and_fills_what_is_known(self) -> None:
        """RF-017-07, RF-009-29: el diálogo de la orden interna pregunta «¿Para el proyecto o solo para V01?» (la versión activa), propone el
        decisor y no pide de nuevo lo que el perfil ya tiene en el ámbito; se cierra sin dejar nada si no se acepta. Sin versión activa, el
        perfil se crea para el proyecto (la edición es de proyecto) y «solo la versión» se rechaza sin dejar nada."""
        cls = self.cls
        asked: list[dict[str, Any]] = []

        def dialog(operator: Any, **options: Any) -> set[str]:
            asked.append(options)
            return {"RUNNING_MODAL"}

        manager = SimpleNamespace(invoke_props_dialog=dialog)
        context = SimpleNamespace(window_manager=manager, window=object())
        fresh = operator_self(cls, code="", name="", scope="PROJECT", decided_by="", reason="",
                              properties=SimpleNamespace(is_property_set=lambda name: False))
        self.assertEqual(cls.invoke(fresh, context, None), {"RUNNING_MODAL"})
        self.assertEqual(len(asked), 1)
        self.assertEqual(fresh.decided_by, self.project.session.user_host)
        before = self.counts()
        layout = draw(cls, bpy.context, method="draw", code="", name="NUEVO", scope="PROJECT", kind="ADOPTADO", source_kind="PERSON",
                      source="", decided_by=PERSON, reason="", **{prop: "" for prop in NUMBERS}, road_class="", metric="DEFAULT")
        texts = layout.texts()
        self.assertIn("¿Para el proyecto o solo para V01?", texts)
        self.assertIn("Solo V01", texts)
        props = [item.target for item in layout.items if item.kind == "prop"]
        for prop in PROPERTIES:
            if prop != "scope":  # el ámbito se dibuja con sus dos botones
                self.assertIn(prop, props)
        # completando: lo que el perfil ya tiene en el ámbito se enseña, no se pide
        existing = operator_self(cls, code="pista_principal", name=MAIN, scope="PROJECT", decided_by="", reason="",
                                 properties=SimpleNamespace(is_property_set=lambda name: False))
        self.assertEqual(cls.invoke(existing, context, None), {"RUNNING_MODAL"})
        self.assertEqual(existing.name, MAIN)
        shown_attributes = {prop: "" for prop in NUMBERS}
        shown_attributes.update(road_class="", metric="DEFAULT", kind="ADOPTADO", source_kind="PERSON", source="", reason="",
                                decided_by=PERSON, scope="PROJECT", code="pista_principal", name=MAIN)
        layout = draw(cls, bpy.context, method="draw", _known=existing._known, **shown_attributes)
        props = [item.target for item in layout.items if item.kind == "prop"]
        for prop in (*NUMBERS[:-1], "road_class"):
            self.assertNotIn(prop, props)  # ya valen en el proyecto: se cambian con «Cambiar…»
        self.assertIn("mesh", props)  # el factor de malla no tiene valor en el proyecto: se puede dar
        self.assertIn("Ancho del vehículo de diseño A (m): 3,5 m [ADO]", layout.texts())
        self.assertIn("Los valores ya declarados se cambian con «Cambiar…» en la lista", layout.texts())
        self.assertEqual(self.counts(), before)
        # sin versión activa: la edición es de proyecto y vale; «solo la versión» se rechaza sin dejar nada
        self.addCleanup(self.set_active, self.v01)
        self.set_active(None)
        self.assertTrue(bpy.ops.geoblender.des_edit_road_profile.poll())
        self.assertTrue(bpy.ops.geoblender.des_save_road_profile.poll())
        scope_less = draw(cls, bpy.context, method="draw", code="", name="NUEVO", scope="PROJECT", kind="ADOPTADO", source_kind="PERSON",
                          source="", decided_by=PERSON, reason="", **{prop: "" for prop in NUMBERS}, road_class="", metric="DEFAULT")
        self.assertFalse(any("¿Para el proyecto" in text for text in scope_less.texts()))  # sin versión activa no hay ámbito que elegir
        with self.assertRaises(RuntimeError) as raised:
            self.save(name="SOLO_VERSION", scope="VERSION", **REFERENCE)
        self.assertIn("versión activa", str(raised.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.save(name="SIN_VERSION", **OTHER), {"FINISHED"})
        self.assertEqual(self.counts(), (before[0] + 1, before[1] + 1, before[2] + 13))
        self.assertEqual(self.profile("SIN_VERSION").scope, "el proyecto")

    def test_h_the_commands_and_the_window_are_disabled_with_their_reason(self) -> None:
        """RF-017-29, RF-015-28, RF-009-21 (M2): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable
        (V02 SUPERADO: «V02 está en estado SUPERADO: …», que dice también la descripción de la orden), las dos órdenes salen desactivadas con
        su motivo y no se pueden lanzar; la ventana se sigue viendo, con lo que escribe desactivado y el motivo dicho; con V01, activas."""
        messages: list[str] = []
        for idname in (OPEN, SAVE):
            cls = self.commands.registered_class(idname)

            def poll(cls: Any = cls) -> bool:
                messages.clear()
                with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                    return bool(cls.poll(bpy.context))

            with self.subTest(orden=idname):
                self.assertTrue(poll())
                self.assertEqual(messages, [])
                with mock.patch.object(self.project, "_status", self.project.status):  # solo lectura
                    self.project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
                    self.assertFalse(poll())
                    (reason,) = messages
                    self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
                    before = self.counts()
                    with self.assertRaises(RuntimeError):
                        self.save(name="NO_DEBE", **OTHER)
                    self.assertEqual(self.counts(), before)
                    blocked = draw(getattr(bpy.types, PANEL), bpy.context)
                    self.assertTrue(any(text.startswith("Proyecto en solo lectura: ") for text in blocked.texts()), blocked.texts())
                self.assertTrue(poll())
        # la versión activa SUPERADO
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (REASON, self.v02.uid))
        self.addCleanup(self.set_active, self.v01)
        self.set_active(self.v02)
        self.assertEqual(_module("bl.scene.versions").not_editable_text(), NOT_EDITABLE)
        for idname in (OPEN, SAVE):
            cls = self.commands.registered_class(idname)
            with self.subTest(orden=idname, versión="V02 SUPERADO"):
                messages.clear()
                with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                    self.assertFalse(cls.poll(bpy.context))
                self.assertEqual(messages, [NOT_EDITABLE])
                self.assertIn(NOT_EDITABLE, cls.description(bpy.context, SimpleNamespace()))
        self.assertFalse(bpy.ops.geoblender.des_edit_road_profile.poll())
        self.assertFalse(bpy.ops.geoblender.des_save_road_profile.poll())
        # la ventana, ya leída, dibuja la lista y desactiva lo que escribe con el motivo; los valores se siguen viendo
        shown = self.view
        self.assertTrue(len(shown.road_profiles))
        shown.road_profile_index = [item.name for item in shown.road_profiles].index(MAIN)
        panel = getattr(bpy.types, PANEL)
        layout = draw(panel, bpy.context)
        self.assertIn(NOT_EDITABLE, " ".join(layout.texts()))
        self.assertIn("template_list", {item.kind for item in layout.items})
        writes = [item for item in layout.items if item.kind == "operator" and item.target in (SAVE, "geoblender.core_set_parameter")]
        self.assertTrue(writes and not any(item.enabled for item in writes))
        self.assertTrue(any(MAIN in text for text in layout.texts()))  # se sigue viendo
        self.assertTrue(any("calzada 10,5 m" in text for text in layout.texts()))
        self.set_active(self.v01)
        enabled = draw(panel, bpy.context)
        buttons = {item.target: item for item in enabled.items if item.kind == "operator"}
        self.assertIn(SAVE, buttons)
        self.assertTrue(buttons[SAVE].enabled)

    def test_i_mesh_factor_and_metric_are_saved_only_when_given(self) -> None:
        """RF-017-07, D-2: el factor de malla y la métrica son lo único con valor por defecto (1,0 y la euclídea exacta): si se dan se guardan
        con su fuente (la métrica «por defecto» no) y la ventana los lee; el dominio arma el perfil con ellos."""
        self.assertEqual(self.save(name="CON_MALLA", **REFERENCE, mesh="0,5", metric="CHAMFER5"), {"FINISHED"})
        stored = self.values_of("con_malla")
        self.assertEqual((stored["mesh_factor"][0], stored["metric"][0]), (0.5, "chamfer5"))
        self.assertEqual(len(stored), 15)
        item = self.profile("CON_MALLA")
        self.assertEqual(self.line(item, "mesh_factor").text, "V01: — · proyecto: 0,5 [ADO]")
        self.assertEqual(self.line(item, "metric").text, "V01: — · proyecto: chamfer5 [ADO]")
        self.assertEqual(self.save(name="SIN_MALLA", **REFERENCE, mesh="", metric="DEFAULT"), {"FINISHED"})
        self.assertEqual(len(self.values_of("sin_malla")), 13)
        with self.project.read() as conn:
            codes = {row.code: row for row in self.road_profiles.read_profiles(conn)}
        self.assertEqual(set(codes), {"pista_principal", "acceso_al_tajo", "solo_v01", "sin_version", "con_malla", "sin_malla"})

    def test_z_disabling_leaves_no_trace(self) -> None:
        """Principio 8: desactivar Geoblender quita la ventana, la lista y las dos órdenes (la huella entera la mira el lanzador al
        terminar) y las propiedades de la vista."""
        blender_ext.release()
        for name in (PANEL, LIST, "GEOBLENDER_OT_des_edit_road_profile", "GEOBLENDER_OT_des_save_road_profile"):
            with self.subTest(clase=name):
                self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(hasattr(bpy.types.WindowManager, VIEW_PROPERTY))
