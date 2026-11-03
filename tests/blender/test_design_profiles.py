# SPDX-License-Identifier: GPL-3.0-or-later
"""«Perfiles de banco…» en Blender (spec 013, T22; HU-013-4; RF-013-18, RF-013-19, RF-013-20,
RF-013-33; plan 013 §5.3.3 y §5.5; comprobación manual M2).

La orden ``geoblender.des_edit_bench_profiles`` abre la ventana ``GEOBLENDER_PT_des_profiles``
(lo ya leído del proyecto: nada se calcula ni se lee al dibujar) y la interna
``geoblender.des_save_bench_profile`` crea, completa y renombra perfiles con
``design.profiles.edit_bench_profiles``; cambiar un valor que ya existe es ``core_set_parameter``
(la 008, con «¿Para el proyecto o solo para V01?» de la 009). Un proyecto por clase (24 × 24 celdas
de 1 m, V01 y V02) y las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-013-33 (a): las dos órdenes y la ventana están registradas (clases reales) y la orden que abre
  la ventana dice por qué no está disponible sin proyecto.
- RF-013-18 (b): crear ``EXPL_10_60_6`` guarda su nombre, su código inmutable y sus cuatro valores
  como parámetros con su tipo, su origen y su decisor, en el proyecto; la ventana lo lee con su
  resumen «h 10 m · cara 60° · berma 6 m · ancla 125 m».
- RF-013-20 (c): los derivados de la ventana (avance y talud general) son los del dominio
  (``EXPL_10_60_6``: 11,77 m y 40,34°, que la spec escribe 40,3°; ``REST_5_35_6``: 13,14 m y
  20,83°) y un perfil que la rejilla no resuelve lo dice, en alerta.
- RF-013-18, RF-009-24 (d): completar un perfil de una versión con los valores del proyecto y
  cambiar uno solo en V02 («¿Para el proyecto o solo para V02?») deja cada ámbito con el suyo.
- RF-013-18 (e): renombrar un perfil no cambia su código ni sus valores.
- RF-013-19 (f): un perfil sin nombre, con el nombre de otro, sin un valor o con uno fuera de rango
  se rechaza nombrando el perfil, el campo y el valor, y no deja nada (ni una operación).
- RF-013-18, RF-013-33 (g, h): el diálogo y la ventana en los dos idiomas, y la ventana desactiva lo
  que escribe con la versión activa SUPERADO.
- Principio 8 (z): desactivar Geoblender quita la orden, la ventana y la lista.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import math
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
from tests.support.trees import remove_tree

OPEN = "geoblender.des_edit_bench_profiles"
SAVE = "geoblender.des_save_bench_profile"
PANEL = "GEOBLENDER_PT_des_profiles"
LIST = "GEOBLENDER_UL_des_profiles"
VIEW_PROPERTY = "geoblender_design"
REASON = "Prueba de los perfiles de banco"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
EXPL = "EXPL_10_60_6"
REST = "REST_5_35_6"
THIN = "FINO_5_85_6"  # su cara ocupa 0,44 m en planta: la rejilla de 1 m no la resuelve
EXPL_VALUES = {"height": "10", "face": "60", "berm": "6", "anchor": "125"}
REST_VALUES = {"height": "5", "face": "35", "berm": "6", "anchor": "125"}
THIN_VALUES = {"height": "5", "face": "85", "berm": "6", "anchor": "125"}
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def advance(height: float, face_deg: float, berm: float) -> float:
    """El avance a mano: ``h / tan α + B`` (RF-013-20)."""
    return height / math.tan(math.radians(face_deg)) + berm


def general_deg(height: float, face_deg: float, berm: float) -> float:
    """El talud general a mano: ``atan(h / a)`` (RF-013-20)."""
    return math.degrees(math.atan(height / advance(height, face_deg, berm)))


class BenchProfilesTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 para toda la clase (las
    pruebas, en el orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d22-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.profiles = _module("design.profiles")
        cls.params = _module("core.params")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(700_000.0, 4_400_000.0, 700_024.0, 4_400_024.0), grid_step_m=1.0))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva",
                                                      title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def counts(self) -> tuple[int, int, int]:
        """Operaciones, perfiles y parámetros de perfil del proyecto (lo que un rechazo no
        cambia)."""
        profile_rows = 0
        with self.project.read() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'des_bench_profile'"
                            ).fetchone():
                profile_rows = int(conn.execute(
                    "SELECT count(*) FROM des_bench_profile").fetchone()[0])
            operations = int(conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0])
            keys = int(conn.execute("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.bench.%'"
                                    ).fetchone()[0])
        return operations, profile_rows, keys

    def save(self, **values: Any) -> set[str]:
        """La orden interna con una declaración completa (lo que no se da: ADOPTADO, la persona,
        el proyecto)."""
        given = {"kind": "ADOPTADO", "source": SOURCE, "decided_by": PERSON, "reason": REASON,
                 "scope": "PROJECT", **values}
        return bpy.ops.geoblender.des_save_bench_profile(**given)

    def opened(self) -> Any:
        """Abre la ventana (en ``blender -b`` solo la vista) y devuelve la vista."""
        with mock.patch.object(self.des_ops, "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.des_edit_bench_profiles(), {"FINISHED"})
        return self.view

    def profile(self, name: str) -> Any:
        found = [item for item in self.opened().profiles if item.name == name]
        self.assertEqual(len(found), 1, f"{name}: {[item.name for item in self.view.profiles]}")
        return found[0]

    def values_of(self, code: str) -> dict[str, tuple[Any, str, str]]:
        """Los cinco valores del perfil ``code`` en el proyecto: último segmento → (valor, tipo,
        decisor)."""
        found = {}
        for key, value, kind, decided_by in self.rows(
                "SELECT key, value, kind, decided_by FROM gb_parameter "
                "WHERE key LIKE ? AND scope = 'project' ORDER BY key", f"des.bench.{code}.%"):
            found[key.rsplit(".", 1)[1]] = (json.loads(value), kind, decided_by)
        return found

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_and_the_window_are_registered(self) -> None:
        """RF-013-33, RF-013-20 (plan §5.3.3): «Perfiles de banco…» y la interna que los guarda
        son clases reales de ``bl.ops.des`` (con la ventana y su lista); sin proyecto, la orden no
        está disponible y dice por qué."""
        for idname in (OPEN, SAVE):
            with self.subTest(orden=idname):
                self.assertIn(self.commands.registered_class(idname), self.des_ops.classes)
        for name in (PANEL, LIST):
            self.assertIsNotNone(getattr(bpy.types, name, None), name)
        self.assertTrue(bpy.ops.geoblender.des_edit_bench_profiles.poll())
        cls = self.commands.registered_class(OPEN)
        with mock.patch.object(cls, "poll_message_set") as said, \
                mock.patch.object(_module("bl.ops.core_provenance"), "write_unavailable",
                                  return_value="Abra un proyecto"), \
                mock.patch.object(_module("bl.ops.des"), "write_unavailable",
                                  return_value="Abra un proyecto"):
            self.assertFalse(cls.poll(bpy.context))
        said.assert_called_once_with("Abra un proyecto")

    def test_b_create_a_profile_with_its_values(self) -> None:
        """RF-013-18, RF-013-20: crear ``EXPL_10_60_6`` guarda su fila (nombre y código
        inmutable) y sus cuatro valores como parámetros del proyecto, con su tipo, su decisor y su
        origen; la ventana lo enseña con su resumen, su insignia, su ámbito y sus derivados."""
        before = self.counts()
        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.save(name=EXPL, **EXPL_VALUES), {"FINISHED"})
        self.assertEqual(self.counts(), (before[0] + 1, before[1] + 1, before[2] + 4))
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no la deshace: queda apuntada
        self.assertEqual(journal.entries[-1].label, "des.edit_bench_profiles")
        self.assertEqual(self.rows("SELECT code, name FROM des_bench_profile"),
                         [("expl_10_60_6", EXPL)])
        stored = self.values_of("expl_10_60_6")
        self.assertEqual({name: value for name, (value, _k, _d) in stored.items()},
                         {"height_m": 10.0, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 125.0})
        self.assertEqual({kind for _v, kind, _d in stored.values()}, {"ADOPTADO"})
        self.assertEqual({who for _v, _k, who in stored.values()}, {PERSON})
        item = self.profile(EXPL)
        self.assertEqual(item.code, "expl_10_60_6")
        self.assertEqual(item.summary, "h 10 m · cara 60° · berma 6 m · ancla 125 m")
        self.assertEqual(item.badge, "[ADO]")
        self.assertEqual(item.scope, "el proyecto")
        self.assertEqual(item.unresolved, "")
        self.assertEqual(item.problem, "")

    def test_c_derived_values_come_from_the_domain_and_the_grid_resolves_them(self) -> None:
        """RF-013-20: el avance y el talud general que enseña la ventana son los del dominio
        (11,77 m y 40,34° de ``EXPL_10_60_6``, que la spec escribe 40,3°; 13,14 m y 20,83° de
        ``REST_5_35_6``) y un perfil cuya cara ocupa menos que el paso de la rejilla sale «no
        resuelto», en alerta."""
        self.assertEqual(self.save(name=REST, **REST_VALUES), {"FINISHED"})
        self.assertEqual(self.save(name=THIN, **THIN_VALUES), {"FINISHED"})
        view = self.opened()
        by_name = {item.name: item for item in view.profiles}
        self.assertEqual(list(by_name), [EXPL, REST, THIN])
        self.assertEqual(by_name[EXPL].derived, "avance 11,77 m · talud general 40,34°")
        self.assertEqual(by_name[REST].derived, "avance 13,14 m · talud general 20,83°")
        # a mano, con h/tan(α) + B y atan(h/a)
        self.assertAlmostEqual(advance(10, 60, 6), 11.7735, places=4)
        self.assertAlmostEqual(general_deg(10, 60, 6), 40.34, places=2)
        self.assertAlmostEqual(advance(5, 35, 6), 13.1407, places=4)
        self.assertAlmostEqual(general_deg(5, 35, 6), 20.8316, places=3)
        self.assertEqual(by_name[EXPL].unresolved, "")
        self.assertEqual(by_name[REST].unresolved, "")
        self.assertIn("no está resuelto por la rejilla", by_name[THIN].unresolved)
        self.assertIn(THIN, by_name[THIN].unresolved)
        self.i18n.set_language("en")
        shown = self.opened()
        english = {item.name: item for item in shown.profiles}
        self.assertEqual(english[EXPL].derived, "advance 11.77 m · general slope 40.34°")
        self.assertEqual(english[EXPL].summary, "h 10 m · face 60° · berm 6 m · anchor 125 m")
        self.assertIn("is not resolved by the grid", english[THIN].unresolved)
        # la ventana dibuja el sin resolver en alerta y los demás, sin ella
        self.i18n.set_language("es")
        shown = self.opened()
        names = [item.name for item in shown.profiles]
        for name in (EXPL, THIN):
            shown.profile_index = names.index(name)
            texts = draw(getattr(bpy.types, PANEL), bpy.context)
            alerts = " ".join(item.text for item in texts.items
                              if item.alert and item.kind == "label")
            self.assertEqual("no está resuelto por la rejilla" in alerts, name == THIN, alerts)
        shown.profile_index = 0

    def test_d_complete_in_the_project_and_change_only_in_a_version(self) -> None:
        """RF-013-18, RF-009-24, RF-009-29: un perfil creado solo para V01 se completa para el
        proyecto con la misma orden; y cambiar un valor solo para V02 («¿Para el proyecto o solo
        para V02?») deja el del proyecto como estaba."""
        name = "SOLO_V01"
        self.assertEqual(self.save(name=name, scope="VERSION", **EXPL_VALUES), {"FINISHED"})
        code = "solo_v01"
        self.assertEqual(self.values_of(code), {})  # nada en el proyecto
        item = self.profile(name)
        self.assertEqual(item.scope, "V01")
        height = next(line for line in item.parameters if line.key.endswith(".height_m"))
        self.assertEqual(height.text, "V01: 10 m [ADO] · proyecto: —")
        self.assertEqual(self.save(code=code, name=name, scope="PROJECT", source="", **EXPL_VALUES),
                         {"FINISHED"})
        # sin origen escrito, el decisor es el origen y es una persona
        self.assertEqual(self.rows(
            "SELECT DISTINCT source, source_kind FROM gb_parameter WHERE key LIKE ? "
            "AND scope = 'project'", f"des.bench.{code}.%"), [(PERSON, "person")])
        self.assertEqual({n: v for n, (v, _k, _d) in self.values_of(code).items()},
                         {"height_m": 10.0, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 125.0})
        item = self.profile(name)
        height = next(line for line in item.parameters if line.key.endswith(".height_m"))
        self.assertEqual(height.text, "V01: 10 m [ADO] · proyecto: 10 m [ADO]")
        # cambiar uno solo en V02: la 008 con el ámbito de la 009
        self.set_active(self.v02)
        key = f"des.bench.{code}.height_m"
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value="8", kind="HIPOTESIS", source=SOURCE, source_kind="DOCUMENT",
            decided_by=PERSON, reason=REASON, scope="VERSION"), {"FINISHED"})
        self.assertEqual(self.values_of(code)["height_m"][0], 10.0)  # el del proyecto, intacto
        # la ventana ya abierta se pone al día sola (la escucha de los indicadores), sin volver
        # a leerla
        open_item = next(item for item in self.view.profiles if item.name == name)
        self.assertEqual(next(line.text for line in open_item.parameters if line.key == key),
                         "V02: 8 m [HIP] · proyecto: 10 m [ADO]")
        item = self.profile(name)
        height = next(line for line in item.parameters if line.key == key)
        self.assertEqual(height.text, "V02: 8 m [HIP] · proyecto: 10 m [ADO]")
        self.assertEqual(item.summary, "h 8 m · cara 60° · berma 6 m · ancla 125 m")
        self.assertEqual(item.scope, "V02 y el proyecto")
        self.assertEqual(item.badge, "[HIP]")  # la del menos firme de sus valores
        self.set_active(self.v01)
        self.assertEqual(self.profile(name).badge, "[ADO]")
        self.set_active(self.v02)
        self.set_active(self.v01)
        self.assertEqual(self.profile(name).summary,
                         "h 10 m · cara 60° · berma 6 m · ancla 125 m")

    def test_e_rename_keeps_the_code_and_the_values(self) -> None:
        """RF-013-18: renombrar un perfil (el nombre es libre, el código es inmutable) no toca sus
        parámetros; la ventana lo enseña con el nombre nuevo."""
        code = "solo_v01"
        before = self.values_of(code)
        with self.assertRaises(RuntimeError) as raised:  # el mismo nombre y ningún valor
            self.save(code=code, name="SOLO_V01")
        self.assertIn("Nada que cambiar en «SOLO_V01»", str(raised.exception))
        self.assertEqual(self.save(code=code, name="SOLO_V01_B"), {"FINISHED"})
        self.assertEqual(self.values_of(code), before)
        self.assertEqual(self.rows("SELECT code, name FROM des_bench_profile WHERE code = ?",
                                   code), [(code, "SOLO_V01_B")])
        item = self.profile("SOLO_V01_B")
        self.assertEqual(item.code, code)

    def test_f_rejections_name_the_profile_the_field_and_the_value(self) -> None:
        """RF-013-19: un perfil sin nombre, con el nombre de otro (sin distinguir mayúsculas), sin
        un valor, con uno fuera de rango o que no es un número se rechaza nombrando el perfil, el
        campo y el valor, y no deja nada: ni un perfil, ni un parámetro, ni una operación."""
        before = self.counts()
        cases = {
            "sin nombre": ({"name": "  ", **EXPL_VALUES}, ("nombre",)),
            "repetido": ({"name": EXPL.lower(), **EXPL_VALUES}, ("se llama", "expl_10_60_6")),
            "sin altura": ({"name": "NUEVO", **{**EXPL_VALUES, "height": ""}},
                           ("NUEVO", "des.bench.nuevo.height_m", "no tiene valor")),
            "cara de 95°": ({"name": "NUEVO", **{**EXPL_VALUES, "face": "95"}},
                            ("NUEVO", "des.bench.nuevo.face_deg", "95")),
            "cara de 90°": ({"name": "NUEVO", **{**EXPL_VALUES, "face": "90"}},
                            ("NUEVO", "des.bench.nuevo.face_deg", "90")),
            "altura negativa": ({"name": "NUEVO", **{**EXPL_VALUES, "height": "-2"}},
                                ("NUEVO", "des.bench.nuevo.height_m", "-2")),
            "no es un número": ({"name": "NUEVO", **{**EXPL_VALUES, "berm": "seis"}},
                                ("seis",)),
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
            self.save(name="NUEVO", **{**EXPL_VALUES, "face": "95"})
        self.assertIn("is outside its range", str(raised.exception))
        self.assertIn("des.bench.nuevo.face_deg", str(raised.exception))
        self.i18n.set_language("es")
        self.assertEqual(self.counts(), before)
        # un perfil que no existe: un error del programa, dicho también sin dejar nada
        with self.assertRaises(RuntimeError):
            self.save(code="no_existe", name="OTRO")
        self.assertEqual(self.counts(), before)
        # un valor sin su origen: el del decisor; sin decisor, nada
        with self.assertRaises(RuntimeError):
            self.save(name="NUEVO", decided_by=" ", **EXPL_VALUES)
        self.assertEqual(self.counts(), before)

    def test_g_the_dialog_asks_the_scope_and_fills_what_is_known(self) -> None:
        """RF-013-18, RF-009-29: el diálogo de la orden interna pregunta «¿Para el proyecto o solo
        para V01?» (la versión activa), propone el decisor y no pide de nuevo lo que el perfil ya
        tiene en el ámbito; se cierra sin dejar nada si no se acepta."""
        cls = self.commands.registered_class(SAVE)
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
        layout = draw(cls, bpy.context, method="draw", code="", name="NUEVO", scope="PROJECT",
                      kind="ADOPTADO", source_kind="PERSON", source="", decided_by=PERSON,
                      reason="", height="", face="", berm="", anchor="", mesh="")
        texts = layout.texts()
        self.assertIn("¿Para el proyecto o solo para V01?", texts)
        self.assertIn("Solo V01", texts)
        props = [item.target for item in layout.items if item.kind == "prop"]
        for name in ("name", "height", "face", "berm", "anchor", "mesh", "kind", "source",
                     "decided_by", "reason"):
            self.assertIn(name, props)
        # completando: lo que el perfil ya tiene en el ámbito se enseña, no se pide
        existing = operator_self(cls, code="solo_v01", name="SOLO_V01_B", scope="PROJECT",
                                 decided_by="", reason="",
                                 properties=SimpleNamespace(is_property_set=lambda name: False))
        self.assertEqual(cls.invoke(existing, context, None), {"RUNNING_MODAL"})
        self.assertEqual(existing.name, "SOLO_V01_B")
        self.assertEqual(self.counts(), before)

    def test_h_the_window_draws_the_list_and_blocks_writing_in_a_superseded_version(self) -> None:
        """RF-013-33, RF-013-20: la ventana dibuja la lista y los botones, y con la versión activa
        SUPERADO dice por qué y desactiva lo que escribe (se sigue viendo)."""
        shown = self.opened()
        shown.profile_index = [item.name for item in shown.profiles].index(EXPL)
        panel = getattr(bpy.types, PANEL)
        layout = draw(panel, bpy.context)
        texts = layout.texts()
        self.assertTrue(any(EXPL in text for text in texts), texts)
        self.assertTrue(any("avance 11,77 m" in text for text in texts), texts)
        buttons = {item.target: item for item in layout.items if item.kind == "operator"}
        self.assertIn(SAVE, buttons)
        self.assertTrue(buttons[SAVE].enabled)
        self.assertIn("template_list", {item.kind for item in layout.items})
        # la versión activa SUPERADO
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.assertEqual(_module("bl.scene.versions").not_editable_text(), NOT_EDITABLE)
        blocked = draw(panel, bpy.context)
        self.assertIn(NOT_EDITABLE, " ".join(blocked.texts()))
        writes = [item for item in blocked.items
                  if item.kind == "operator" and item.target == SAVE]
        self.assertTrue(writes and not any(item.enabled for item in writes))
        changes = [item for item in blocked.items
                   if item.kind == "operator" and item.target == "geoblender.core_set_parameter"]
        self.assertTrue(changes and not any(item.enabled for item in changes))
        self.assertTrue(any(EXPL in text for text in blocked.texts()))  # se sigue viendo
        self.set_active(self.v01)

    def test_z_disabling_leaves_no_trace(self) -> None:
        """Principio 8: desactivar Geoblender quita la ventana, la lista y las dos órdenes (la
        huella entera la mira el lanzador al terminar)."""
        blender_ext.release()
        for name in (PANEL, LIST, "GEOBLENDER_OT_des_edit_bench_profiles",
                     "GEOBLENDER_OT_des_save_bench_profile"):
            with self.subTest(clase=name):
                self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(hasattr(bpy.types.WindowManager, VIEW_PROPERTY))
