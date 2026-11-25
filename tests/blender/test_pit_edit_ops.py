# SPDX-License-Identifier: GPL-3.0-or-later
"""«Roseta de taludes…» y «Rampa…» en Blender (spec 018, T32; HU-018-1, HU-018-3; RF-018-07, RF-018-15, RF-018-34, RF-015-28; plan 018 §5.3.3, §5.5 y H-5; comprobación manual M2).

Las órdenes ``geoblender.des_edit_pit_rose`` y ``geoblender.des_edit_pit_ramp`` abren sus ventanas (``GEOBLENDER_PT_des_pit_roses`` y ``GEOBLENDER_PT_des_pit_ramps``, de
``bl/ui/pit_panels.py``: lo ya leído del proyecto) y las internas ``geoblender.des_save_pit_rose`` y ``geoblender.des_save_pit_ramp`` crean, completan y renombran con
``design.pit_rose.edit_pit_roses`` y ``design.pit_ramp_def.edit_pit_ramps`` (``des.edit_pit_roses`` y ``des.edit_pit_ramps``: operaciones **de proyecto**, en una transacción). Es la
copia, para la corta, de «Perfil de pista…» (``test_road_profile_ops.py``). Un proyecto por clase (24 × 24 celdas de 1 m, V01) y las pruebas, en el orden de sus letras sobre el
mismo estado. Los valores son **de prueba**: ninguno es un valor por defecto del producto (D-5, D-6, D-19).

- RF-018-34, RF-015-28 (a): las cuatro órdenes y las dos ventanas son clases reales de sus operaciones, con su orden de catálogo; las propiedades tienen nombre y descripción y los
  decimales son texto.
- RF-018-07 (b): una roseta con un hueco se rechaza **nombrando la roseta y el rango** y no deja nada (0 transacciones).
- RF-018-07 (c): crear una roseta guarda su fila y sus rangos como parámetros con tipo, fuente y decisor; la ventana los enseña con su fuente; el avance y el talud general que
  enseña son los del dominio, no son parámetros (ninguna fila) y no se editan (ningún botón los acompaña).
- RF-018-15 (d): crear una rampa guarda sus valores con su fuente; la ventana enseña la longitud necesaria por banco (h / g) y la sección del perfil de pista, que no son parámetros;
  una pendiente por encima de la máxima del perfil de pista se rechaza con el campo y no deja nada.
- RF-018-07, RF-018-15 (e): renombrar no cambia el código; el nombre es único; la operación de proyecto deja su operación apuntada en el diario y no toca la versión.
- RF-018-34, RF-015-28 (f): las órdenes salen desactivadas con su motivo sin proyecto escribible.
- Principio 8 (z): desactivar Geoblender quita las órdenes, las ventanas y las listas.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import math
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.trees import remove_tree

OPEN_ROSE, SAVE_ROSE = "geoblender.des_edit_pit_rose", "geoblender.des_save_pit_rose"
OPEN_RAMP, SAVE_RAMP = "geoblender.des_edit_pit_ramp", "geoblender.des_save_pit_ramp"
PANELS = ("GEOBLENDER_PT_des_pit_roses", "GEOBLENDER_UL_des_pit_roses", "GEOBLENDER_PT_des_pit_ramps", "GEOBLENDER_UL_des_pit_ramps")
REASON = "Prueba de la roseta y de la rampa"
PERSON = "Samuel (IMGA)"
SOURCE = "Proyecto de referencia de IMGA (spec 018, solo pruebas)"
ROSE = "ROSETA NORTE"
RAMP = "ESPIRAL A"
RANGES = "0 180 60 6; 180 360 55 8"
"""Los rangos como los teclea una persona: «desde hasta α B», separados por «;»."""
HEIGHT = 10.0
BENCH = "EXPL_10_60_6"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class PitEditOpsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01, un perfil de banco y un perfil de pista para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-p32-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.des_pit = _module("bl.ops.des_pit")
        cls.pit_panels = _module("bl.ui.pit_panels")
        cls.pit_rose = _module("design.pit_rose")
        cls.pit_ramp = _module("design.pit_ramp_def")
        cls.profiles = _module("design.profiles")
        cls.road_profiles = _module("design.road_profiles")
        cls.provenance = _module("design.provenance")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=(700_000.0, 4_400_000.0, 700_024.0, 4_400_024.0), grid_step_m=1.0))
        cls.project = core_project.create_project(folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva", title="Definitiva", reason=REASON)
        cls.project.refresh_header()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        by_hand = {"source": SOURCE, "decided_by": PERSON, "reason": REASON}
        cls.profiles.edit_bench_profiles(
            cls.project, (cls.profiles.ProfileEdit(name=BENCH, values={"height_m": HEIGHT, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 100.0}),),
            cls.profiles.ProfileDeclaration(**by_hand))
        values = {"vehicle_width_m": 3.5, "lane_factor": 3.0, "shoulder_m": 0.0, "berm_m": 1.0, "max_gradient_pct": 10.0, "station_step_m": 1.0,
                  "max_mean_gradient_pct": 10.0, "curve_radius_m": 20.0, "min_radius_m": 12.0, "cut_angle_deg": 60.0, "fill_angle_deg": 35.0, "reach_m": 60.0,
                  "class": "Pista de acceso"}
        cls.road_profiles.edit_road_profiles(cls.project, (cls.road_profiles.ProfileEdit(name="PISTA PRINCIPAL", values=values),),
                                             cls.road_profiles.ProfileDeclaration(**by_hand))
        cls.des_pit.refresh_ramp_choices(cls.project)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, "geoblender_design")

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def counts(self) -> tuple[int, int, int, int]:
        """Operaciones, rosetas, rampas y parámetros de ellas (lo que un rechazo no cambia: 0 transacciones)."""
        found = []
        with self.project.read() as conn:
            for table in ("des_pit_rose", "des_pit_ramp"):
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone()
                found.append(int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) if exists else 0)
            operations = int(conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0])
            keys = int(conn.execute("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.rose.%' OR key LIKE 'des.pitramp.%'").fetchone()[0])
        return operations, found[0], found[1], keys

    def save_rose(self, **values: Any) -> set[str]:
        given = {"kind": "ADOPTADO", "source": SOURCE, "source_kind": "DOCUMENT", "decided_by": PERSON, "reason": REASON, "scope": "PROJECT", **values}
        return bpy.ops.geoblender.des_save_pit_rose(**given)

    def save_ramp(self, **values: Any) -> set[str]:
        given = {"kind": "ADOPTADO", "source": SOURCE, "source_kind": "DOCUMENT", "decided_by": PERSON, "reason": REASON, "scope": "PROJECT", **values}
        return bpy.ops.geoblender.des_save_pit_ramp(**given)

    def rejected(self, saver: Any, **values: Any) -> str:
        """Lo que dice una orden que se rechaza (``ERROR``: desde un guion es una excepción con su texto); no deja nada."""
        with self.assertRaises(RuntimeError) as caught:
            saver(**values)
        return str(caught.exception)

    def opened(self, idname: str) -> Any:
        with mock.patch.object(self.des_pit, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(getattr(bpy.ops.geoblender, idname.split(".")[1])(), {"FINISHED"})
        return self.view

    def rose(self, name: str) -> Any:
        found = [item for item in self.opened(OPEN_ROSE).pit_roses if item.name == name]
        self.assertEqual(len(found), 1, f"{name}: {[item.name for item in self.view.pit_roses]}")
        return found[0]

    def ramp(self, name: str) -> Any:
        found = [item for item in self.opened(OPEN_RAMP).pit_ramps if item.name == name]
        self.assertEqual(len(found), 1, f"{name}: {[item.name for item in self.view.pit_ramps]}")
        return found[0]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_and_the_windows_are_registered(self) -> None:
        """RF-018-34, RF-015-28 (plan §5.3.3, H-5): las cuatro órdenes son clases reales de ``bl.ops.des_pit``, de la puerta de la procedencia y de su operación **de proyecto**; sus
        ventanas y listas están registradas; son del catálogo; los decimales son texto (``StringProperty``, trampa 1)."""
        expected = {OPEN_ROSE: self.provenance.EDIT_PIT_ROSES, SAVE_ROSE: self.provenance.EDIT_PIT_ROSES,
                    OPEN_RAMP: self.provenance.EDIT_PIT_RAMPS, SAVE_RAMP: self.provenance.EDIT_PIT_RAMPS}
        for idname, op_type in expected.items():
            with self.subTest(orden=idname):
                cls = self.commands.registered_class(idname)
                self.assertIn(cls, self.des_pit.classes)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
                self.assertEqual(cls.provenance_op_type, op_type)
                self.assertEqual(cls.bl_options & {"UNDO"}, set())  # escribe en el proyecto: Ctrl+Z no lo deshace (el diario lo apunta)
        self.assertEqual(self.provenance.PIT_ROSE_COMMAND, OPEN_ROSE)
        self.assertEqual(self.provenance.PIT_RAMP_COMMAND, OPEN_RAMP)
        for name in PANELS:
            self.assertIsNotNone(getattr(bpy.types, name, None), name)
        catalog = self.commands.catalog()
        for idname, label, kind in ((OPEN_ROSE, "Roseta de taludes…", "operator"), (OPEN_RAMP, "Rampa…", "operator"),
                                    (SAVE_ROSE, "Guardar roseta de taludes…", "internal"), (SAVE_RAMP, "Guardar rampa…", "internal")):
            command = catalog.commands[idname]
            self.assertEqual((command.kind, command.module, command.label_es), (kind, "des", label))
        annotations = _module("bl.registry").annotations(self.commands.registered_class(SAVE_RAMP))
        for prop in ("gradient", "transition", "turn_radius", "min_platform"):
            self.assertEqual(annotations[prop].function, bpy.props.StringProperty, prop)
        annotations = _module("bl.registry").annotations(self.commands.registered_class(SAVE_ROSE))
        self.assertEqual(annotations["ranges"].function, bpy.props.StringProperty)

    def test_b_a_rose_with_a_gap_is_rejected_with_the_range(self) -> None:
        """RF-018-07: una roseta con un hueco de azimut se rechaza nombrando la roseta y el rango (el campo y lo escrito) y no deja nada (0 transacciones); sin nombre y con un
        texto que no son cuatro números, también."""
        before = self.counts()
        reports = [self.rejected(self.save_rose, name=ROSE, ranges="0 90 60 6; 120 360 55 8"), self.rejected(self.save_rose, name=ROSE, ranges="0 90 60"),
                   self.rejected(self.save_rose, name="", ranges=RANGES)]
        self.assertEqual(self.counts(), before)
        self.assertIn("ROSETA NORTE", reports[0])
        self.assertIn("90", reports[0])
        self.assertIn("120", reports[0])
        self.assertIn("«0 90 60»", reports[1])

    def test_c_create_a_rose_with_its_ranges_and_derived_values(self) -> None:
        """RF-018-07, RF-018-08: crear la roseta guarda su fila (código inmutable) y sus rangos como parámetros del proyecto con su tipo, su fuente y su decisor; la ventana los enseña
        con su fuente y el avance h/tan α + B y el talud general atan(h/avance) de cada rango para la altura de cada perfil de banco, **que son los del dominio, no son parámetros
        y no se editan**; la operación de proyecto queda apuntada en el diario."""
        before = self.counts()
        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.save_rose(name=ROSE, ranges=RANGES), {"FINISHED"})
        self.assertEqual(self.counts(), (before[0] + 1, before[1] + 1, before[2], before[3] + 8))  # dos rangos de cuatro valores
        self.assertEqual(len(journal.entries), noted + 1)
        self.assertEqual(journal.entries[-1].label, "des.edit_pit_roses")
        self.assertEqual(self.rows("SELECT code, name FROM des_pit_rose"), [("roseta_norte", ROSE)])
        self.assertEqual(self.rows("SELECT DISTINCT kind, decided_by FROM gb_parameter WHERE key LIKE 'des.rose.roseta_norte.%'"), [("ADOPTADO", PERSON)])
        item = self.rose(ROSE)
        self.assertEqual(item.code, "roseta_norte")
        self.assertEqual(item.badge, "[ADO]")
        self.assertEqual(item.scope, "el proyecto")
        self.assertEqual(item.problem, "")
        self.assertEqual(len(item.parameters), 8)
        self.assertTrue(all(line.registered and line.source.startswith("Fuente: ") for line in item.parameters))
        self.assertEqual(item.summary, "0°–180°: α 60°, B 6 m · 180°–360°: α 55°, B 8 m")
        # los derivados, del dominio: h = 10 m del perfil de banco
        first = self.pit_rose.advance_m(HEIGHT, 60.0, 6.0)
        slope = self.pit_rose.overall_slope_deg(HEIGHT, 60.0, 6.0)
        lines = [line.name for line in item.lines]
        self.assertTrue(any(f"{first:.2f}".replace(".", ",") in line and f"{slope:.2f}".replace(".", ",") in line for line in lines), lines)
        self.assertTrue(any(BENCH in line for line in lines), lines)
        self.assertAlmostEqual(first / (HEIGHT / math.tan(math.radians(60.0)) + 6.0), 1.0, delta=1e-9)
        self.assertEqual(self.counts()[3], before[3] + 8)  # nada derivado se guardó como parámetro
        self.assertFalse([key for (key,) in self.rows("SELECT key FROM gb_parameter WHERE key LIKE 'des.rose.%'") if "advance" in key or "slope" in key])

    def test_d_create_a_ramp_with_its_length_per_bench(self) -> None:
        """RF-018-15: crear la rampa guarda sus valores con su fuente; la ventana enseña la longitud necesaria por banco h / g (125 m con 10 m y el 8 %) y la sección del perfil de pista,
        que no son parámetros; una pendiente por encima de la máxima del perfil de pista (10 %) se rechaza con el campo y no deja nada."""
        before = self.counts()
        spiral = {"ramp_type": "spiral", "sense": "ccw", "start": "fondo", "road_profile": "pista_principal", "transition": "0"}
        reported = self.rejected(self.save_ramp, name=RAMP, gradient="12", **spiral)
        self.assertEqual(self.counts(), before)
        self.assertIn("12", reported)
        self.assertIn("gradient_pct", reported)
        self.assertEqual(self.save_ramp(name=RAMP, gradient="8", **spiral), {"FINISHED"})
        self.assertEqual(self.counts(), (before[0] + 1, before[1], before[2] + 1, before[3] + 6))  # sin radio ni plataforma: es una espiral
        item = self.ramp(RAMP)
        self.assertEqual(item.code, "espiral_a")
        self.assertEqual(item.badge, "[ADO]")
        self.assertEqual(item.problem, "")
        self.assertEqual(len(item.parameters), 8)
        self.assertEqual(item.summary, "espiral · antihorario · inicio fondo · g 8 % · PISTA PRINCIPAL")
        lines = [line.name for line in item.lines]
        self.assertTrue(any("125" in line and BENCH in line for line in lines), lines)  # h / g = 10 / 0,08
        self.assertTrue(any("11,5" in line for line in lines), lines)  # la sección del perfil de pista
        self.assertEqual(self.counts()[3], before[3] + 6)

    def test_e_rename_keeps_the_code_and_names_are_unique(self) -> None:
        """RF-018-07, RF-018-15: renombrar no cambia el código ni los valores; el nombre es único sin distinguir mayúsculas; completar lo que el ámbito ya tiene se rechaza."""
        before = self.counts()
        self.assertEqual(self.save_rose(code="roseta_norte", name="Roseta del norte"), {"FINISHED"})
        self.assertEqual(self.rows("SELECT code, name FROM des_pit_rose"), [("roseta_norte", "Roseta del norte")])
        self.assertEqual(self.counts()[0], before[0] + 1)
        self.assertEqual(self.counts()[3], before[3])
        self.rejected(self.save_rose, name="ROSETA DEL NORTE", ranges=RANGES)  # el nombre es único sin distinguir mayúsculas
        self.assertEqual(self.counts()[0], before[0] + 1)
        self.rejected(self.save_rose, code="roseta_norte", name="Roseta del norte")  # no cambia nada
        self.assertEqual(self.save_ramp(code="espiral_a", name="Espiral A2"), {"FINISHED"})
        self.assertEqual(self.rows("SELECT code, name FROM des_pit_ramp"), [("espiral_a", "Espiral A2")])
        self.assertEqual(self.ramp("Espiral A2").code, "espiral_a")

    def test_f_the_commands_are_disabled_with_their_reason(self) -> None:
        """RF-018-34, RF-015-28: sin proyecto escribible las órdenes salen desactivadas con su motivo (la puerta de la procedencia)."""
        for idname in (OPEN_ROSE, OPEN_RAMP):
            with self.subTest(orden=idname):
                cls = self.commands.registered_class(idname)
                with mock.patch.object(cls, "poll_message_set") as said, \
                        mock.patch.object(self.session, "write_unavailable", return_value="Abra un proyecto"), \
                        mock.patch.object(self.des_ops, "write_unavailable", return_value="Abra un proyecto"):
                    self.assertFalse(cls.poll(bpy.context))
                said.assert_called_once_with("Abra un proyecto")

    def test_g_the_windows_draw_the_derived_values_without_buttons(self) -> None:
        """RF-018-07, RF-018-15 (M2): las ventanas dibujan el avance, el talud general y la longitud por banco como texto, **sin ningún botón** (no se editan); los valores con
        fila llevan «Cambiar…» y la fuente; con el proyecto en solo lectura lo que escribe sale desactivado."""
        from tests.support.fake_layout import draw

        for name, opener, panel, kind, derived, rows in (("rosa", OPEN_ROSE, "GEOBLENDER_PT_des_pit_roses", "roses", "avance", 8),
                                                   ("rampa", OPEN_RAMP, "GEOBLENDER_PT_des_pit_ramps", "ramps", "longitud de eje", 6)):
            with self.subTest(ventana=name):
                shown = self.opened(opener)
                shown.pit_details = False
                folded = draw(getattr(bpy.types, panel), bpy.context)
                self.assertNotIn(derived, " ".join(folded.texts()), "T40k: plegada por defecto, la ventana cabe")
                self.assertTrue([item for item in folded.items if item.target == "pit_details"], "el pliegue se ve")
                self.assertIn("Esc", " ".join(folded.texts()), "T40k: dice cómo se cierra")
                self.assertLess(len(folded.items), 40)
                shown.pit_details = True
                layout = draw(getattr(bpy.types, panel), bpy.context)
                texts = " ".join(layout.texts())
                self.assertIn(derived, texts)
                self.assertIn("Valores derivados (no son parámetros)", texts)
                self.assertFalse(any(item.kind in ("prop", "operator") and derived in item.text for item in layout.items))
                changes = [item for item in layout.items if item.kind == "operator" and item.target == "geoblender.core_set_parameter"]
                self.assertEqual(len(changes), rows)  # «Cambiar…» solo de los valores con fila (8 de dos rangos; 6 de una espiral)
                self.assertEqual(len(getattr(shown, f"pit_{kind}")), 1)

    def test_z_disabling_removes_everything(self) -> None:
        """Principio 8: desactivar Geoblender quita las órdenes, las ventanas, las listas y las propiedades de la vista."""
        blender_ext.release()
        for name in PANELS:
            self.assertIsNone(getattr(bpy.types, name, None), name)
        for name in ("GEOBLENDER_OT_des_edit_pit_rose", "GEOBLENDER_OT_des_save_pit_rose", "GEOBLENDER_OT_des_edit_pit_ramp", "GEOBLENDER_OT_des_save_pit_ramp"):
            self.assertIsNone(getattr(bpy.types, name, None), name)
        self.assertFalse(hasattr(bpy.types.WindowManager, "geoblender_design"))


if __name__ == "__main__":
    unittest.main()
