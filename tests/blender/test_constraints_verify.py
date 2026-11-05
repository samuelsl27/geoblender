# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificar un diseño por recinto… (spec 012, T28; HU-012-5, HU-012-7; RF-012-21, RF-012-23,
RF-012-24, RF-012-25; plan 012 §5.3.4, D-28, D-29, D-42; comprobación manual M5 y M6).

``geoblender.res_verify_constraints`` (``bl.ops.res``): el diálogo (el nombre, la superficie de
partida, las finales hasta diez y el espesor mínimo con su tipo), el modal por pasos que compila las
máscaras antes si hace falta y verifica después, la ventana de la verificación
(``GEOBLENDER_PT_res_verification``: la tabla por recinto y final y los grupos que incumplen con su
«Ir a»), el cargador de la rejilla de incumplimientos (``COMPLIANCE_GRID``, con el color de la
rejilla de diferencias de la 011) y el diálogo de congelar (``geoblender.core_new_revision``) con lo
de la 012. Un proyecto por clase (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, seis
restricciones de seis tipos y cuatro superficies: la partida llana a 100 m y tres finales) y las
pruebas, en el orden de sus letras sobre el mismo estado:

- RF-012-28 (a): la orden es la real de la entrada «012»; el diálogo ofrece las rejillas del
  proyecto (no la de clases de las máscaras) con la partida propuesta, el nombre y el espesor
  mínimo con su tipo; el cargador de ``res_chkv_`` y el tipo ``COMPLIANCE_GRID`` están
  registrados.
- RF-012-28, RF-012-16 (b): Esc a mitad, también mientras compila las máscaras, no deja nada: ni
  operaciones en curso, ni datos, ni cifras, ni ficheros.
- RF-012-21, RF-012-22, RF-012-23, RF-012-24 (c): sin máscaras, la orden las compila antes y
  verifica tres finales: la torre no cumple en la primera (600 m³ de movimiento en 100 m², 6 m de
  espesor máximo, centro (23; 23)), la balsa en la segunda (24 m³ de corte) y la tercera cumple; la
  tabla, los grupos y las cifras salen de la tabla del proyecto, con las demás zonas a 0 m³.
- RF-012-23 (d): la ventana dibuja la tabla, los grupos con «Ir a» y el botón de cargar la rejilla;
  «Ir a» encuadra el grupo.
- RF-012-23, D-42 (e): cargar la rejilla de incumplimientos da, en la colección de V01, las celdas
  que incumplen sobre la superficie final, en las clases de la 011, y la final que cumple no
  tiene rejilla.
- RF-012-25 (f, g): congelar V01.r1 lista lo que no cumple y las superficies sin verificación al
  día, y pide motivo y aceptación.
- Principio 8 (z): desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

ENTRY = "012"
VERIFY = "geoblender.res_verify_constraints"
VERIFY_TYPE = "res.verify_constraints"
COMPILE_TYPE = "gis.compile_constraints"
PANEL = "GEOBLENDER_PT_res_verification"
GO_TO = "geoblender.core_go_to_place"
LOAD = "geoblender.core_load_into_view"
NEW_REVISION = "geoblender.core_new_revision"
VIEW_PROPERTY = "geoblender_constraints"
KIND = "COMPLIANCE_GRID"
PREFIX = "res_chkv_"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
START_M = 100.0
REASON = "Prueba de la verificación por recinto"
PERSON = "Samuel (IMGA)"
NAME = "Prueba"
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
TOWER = (20.0, 20.0, 26.0, 26.0)
POND = (34.0, 10.0, 44.0, 18.0)
TRACK = ((6.0, 40.0), (52.0, 40.0))
TREE = (12.0, 12.0)
BUFFER_M = 4.0
TYPES = ("legal_limit", "action_perimeter", "untouchable", "no_cut", "requires_access", "avoid")
NAMES = {"legal_limit": "Concesión", "action_perimeter": "Perímetro", "untouchable": "Torre 132 kV",
         "no_cut": "Balsa", "requires_access": "Camino", "avoid": "Árbol"}
# Las tres finales: (profundidad rebajada en m, caja local) y lo que debe dar cada una.
PIT = (6.0, (18.0, 18.0, 28.0, 28.0))  # 25 celdas dentro del resguardo de la torre
POND_CUT = (1.0, (36.0, 12.0, 42.0, 16.0))  # 6 celdas dentro de la balsa (sin corte)
FREE_CUT = (1.0, (30.0, 46.0, 40.0, 48.0))  # 5 celdas fuera de toda zona
FINALS = {"Foso": PIT, "Corte balsa": POND_CUT, "Limpia": FREE_CUT}
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 20_000


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def number(value: float, decimals: int) -> str:
    """Un número como lo escribe la interfaz en español (espacio fino de miles, coma)."""
    return _module("core.i18n").format_number(value, decimals)


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def lowered(depth: float, box: tuple[float, float, float, float]) -> np.ndarray:
    """La rejilla de la ventana, llana a :data:`START_M` m y ``depth`` m más baja en ``box``
    (local)."""
    left, bottom, right, top = box
    values = np.full((int(SIZE_M / STEP_M), int(SIZE_M / STEP_M)), START_M, dtype=np.float64)
    values[int((SIZE_M - top) / STEP_M):int((SIZE_M - bottom) / STEP_M),
           int(left / STEP_M):int(right / STEP_M)] -= depth
    return values


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


class VerifyTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, seis restricciones y cuatro
    rejillas del proyecto, para toda la clase (las pruebas, en el orden de sus letras: cada una
    parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r28-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.views = _module("bl.scene.views")
        cls.versions = _module("bl.scene.versions")
        cls.constraint_views = _module("bl.scene.constraint_views")
        cls.res_views = _module("bl.scene.res_views")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.res_ops = _module("bl.ops.res")
        cls.versions_ops = _module("bl.ops.versions")
        cls.core_props = _module("bl.props.core")
        cls.mesh = _module("bl.scene.mesh")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.verify = _module("reserves.compliance_store")
        cls.surfaces = _module("reserves.surfaces")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="mascaras",
                                                      title="Máscaras", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.codes = cls.declare()
        cls.grids = {"Partida": cls.write_grid("Partida", lowered(0.0, (0.0, 0.0, 0.0, 0.0)))}
        for name, (depth, box) in FINALS.items():
            cls.grids[name] = cls.write_grid(name, lowered(depth, box))
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @classmethod
    def declare(cls) -> dict[str, str]:
        """Las seis restricciones como las dejará la orden (``core.edit_constraints`` con los
        parámetros que pide cada tipo); el código de cada una por su tipo."""
        m, kinds = cls.cmodel, cls.cmodel.GeometryKind

        def row(ctype: Any, kind: Any, parts: Any) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=NAMES[ctype.value], ctype=ctype, kind=kind,
                parts=parts, priority=3 if ctype is m.ConstraintType.UNTOUCHABLE else 0,
                reason=f"{REASON}: {NAMES[ctype.value]}", decided_by=PERSON,
                decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kind), fid=0)

        T = m.ConstraintType
        rows = [
            row(T.LEGAL_LIMIT, kinds.POLYGON, ((ring(LEGAL),),)),
            row(T.ACTION_PERIMETER, kinds.POLYGON, ((ring(PERIMETER),),)),
            row(T.UNTOUCHABLE, kinds.POLYGON, ((ring(TOWER),),)),
            row(T.NO_CUT, kinds.POLYGON, ((ring(POND),),)),
            row(T.REQUIRES_ACCESS, kinds.LINE,
                ((np.array([(WEST + x, SOUTH + y) for x, y in TRACK]),),)),
            row(T.AVOID, kinds.POINT, ((np.array([[WEST + TREE[0], SOUTH + TREE[1]]]),),)),
        ]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: BUFFER_M,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        edited = cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                            srs_id=cls.project.record.crs_epsg)
        return {item.ctype.value: str(item.code) for item in edited.constraints}

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto de la ventana con ``values`` (como la deja «Rejilla del
        proyecto desde un MDT», ``gis.resample``); el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

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

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def files(self) -> dict[str, str]:
        """Los ficheros de datos del proyecto (rejillas) con su hash: la base del proyecto y su
        cerrojo cambian al registrar una operación, aunque se cancele."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*.tif"))}

    def names(self) -> list[str]:
        """Todos los ficheros de la carpeta del proyecto (sin el diario de la base): lo que una
        verificación cancelada no deja, ni temporales."""
        root = Path(self.project.root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def operations(self, op_type: str, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, superseded_by FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", op_type)
        return self.rows(sql + " AND status = ? ORDER BY fid", op_type, status)

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def running(self) -> Any:
        """El modal de la verificación en marcha (el único con pasos)."""
        cls = self.commands.registered_class(VERIFY)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "la verificación no está en marcha")
        return found[0]

    def drive(self, operator: Any, *, stop_after: int | None = None
              ) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba (o ``stop_after``
        eventos): su final y lo que duró cada llamada (s: la menor de la CPU del proceso y del
        reloj de pared; la carga de otros programas del equipo alarga el reloj y los hilos de
        fondo del propio proceso alargan la CPU, y solo una llamada lenta de verdad se pasa en
        las dos; el plazo de pared lo mide la prueba de rendimiento)."""
        calls: list[float] = []
        for index in range(MAX_EVENTS):
            if stop_after is not None and index == stop_after:
                return {"RUNNING_MODAL"}, calls
            started, wall_started = time.process_time(), time.perf_counter()
            state = operator.modal(bpy.context, TIMER)
            calls.append(min(time.process_time() - started,
                             time.perf_counter() - wall_started))
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("la verificación no acaba")

    def start(self, name: str, finals: tuple[str, ...], **extra: Any) -> None:
        """Lanza la orden desde la interfaz (por pasos) con la partida y las finales dadas."""
        values = {"name": name, "start": self.grids["Partida"],
                  "finals": ",".join(self.grids[final] for final in finals),
                  "in_steps": True, **extra}
        self.assertEqual(bpy.ops.geoblender.res_verify_constraints("EXEC_DEFAULT", **values),
                         {"RUNNING_MODAL"})

    def verify_all(self, name: str, finals: tuple[str, ...], *, tiny: bool = False
                   ) -> list[float]:
        """Verifica por pasos hasta el final (con ``tiny``, un paso por evento); lo que duró
        cada llamada."""
        cls = self.commands.registered_class(VERIFY)
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9 if tiny else cls.STEP_BUDGET_S), \
                mock.patch.object(self.res_ops, "_call_panel", return_value={"FINISHED"}):
            self.start(name, finals)
            state, calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        return calls

    def table(self, name: str = NAME, version: str = "V01") -> dict[tuple[str, int, str], Any]:
        """La tabla ``res_chk_`` de la verificación ``name``: (zona, final, cantidad) → (valor,
        nota)."""
        locator = self.verify.dataset_locator(self.verify.TABLE, name, version)
        return {(zone, final, quantity): (value, note) for zone, final, quantity, value, note
                in self.rows(f'SELECT zone, "final", quantity, value, note FROM "{locator}"')}

    def grid_uids(self, name: str = NAME) -> list[str]:
        """Los uid de las rejillas de incumplimientos de la verificación ``name`` (por final)."""
        return [row[0] for row in self.rows(
            "SELECT uid FROM gb_dataset WHERE name LIKE ? AND status = 'current' ORDER BY name",
            f"{PREFIX}{_module('gis.provenance').dataset_slug(name)}_%")]

    def lines(self, final: int) -> Any:
        """La final ``final`` (desde 1) de la ventana."""
        return self.view.verify_finals[final - 1]

    def panel_texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_the_dialog_the_loader_and_the_kind_are_registered(self) -> None:
        """RF-012-28, RF-012-21, D-31: «Verificar un diseño por recinto…» es la orden real de la
        entrada «012» (``res.verify_constraints``, con la puerta de la procedencia y los pasos con
        Esc), en Diseño ▸ Límites y restricciones y como acceso cruzado en Cubicación; su diálogo
        ofrece las rejillas del proyecto (no la de clases de las máscaras) como partida y finales,
        con el nombre, las finales marcables, la cota constante y el espesor mínimo con su tipo;
        la ventana de la verificación es un panel real; el tipo ``COMPLIANCE_GRID`` y el cargador
        de ``res_chkv_`` son los de la 012."""
        cat = self.commands.catalog()
        self.assertEqual(cat.commands[VERIFY].entry, ENTRY)
        cls = self.commands.registered_class(VERIFY)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (VERIFY_TYPE, {"REGISTER"}))
        self.assertEqual(cat.commands[VERIFY].label_es, "Verificar un diseño por recinto…")
        self.assertIn(VERIFY, [item.key for item in cat.menus["GEOBLENDER_MT_ui_design"]
                               .groups[0].items])
        self.assertIn(KIND, [item[0] for item in self.core_props.OBJECT_KINDS])
        self.assertEqual(self.views.BRANCHES[KIND], (("volumetrics", "Volumetrics"),))
        loader = self.views.loader_for(f"{PREFIX}diseno_1")
        self.assertEqual((loader.prefix, loader.kind, loader.load),
                         (PREFIX, KIND, self.constraint_views.load_compliance_grid))
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type), ("TOPBAR", "HEADER"))
        self.assertIn(panel, self.panels.classes)

        # El diálogo: lo que ofrece y lo que propone (sin ventana: un gestor simulado).
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=None, selected_objects=[],
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fake = operator_self(cls, report=lambda kind, text: None, name="", start="",
                             finals="", start_elevation="", final_elevation="", in_steps=False,
                             properties=SimpleNamespace(is_property_set=lambda name: False))
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Verificar un diseño por recinto…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Verificar")
        offered = [item.name for item in self.view.verify_choices]
        self.assertEqual(sorted(offered), sorted(self.grids.values()))  # sin la de clases
        self.assertNotIn("gis_msk", " ".join(offered))
        self.assertTrue(fake.start)
        self.assertTrue(fake.name.strip())
        self.assertLessEqual(len([item for item in self.view.verify_choices if item.use]), 1)
        cls.draw(fake, bpy.context)
        shown = fake.layout.texts()
        self.assertIn("Espesor mínimo de la verificación", " ".join(shown))
        self.assertTrue(any("0,02" in text for text in shown), shown)
        self.assertEqual([item.target for item in fake.layout.of_kind("prop")
                          if item.target in ("name", "start", "final_elevation")],
                         ["name", "start", "final_elevation"])
        marks = [item for item in fake.layout.of_kind("prop") if item.target == "use"]
        self.assertEqual(len(marks), len(offered))

    def test_b_esc_midway_leaves_nothing_even_while_compiling_the_masks(self) -> None:
        """RF-012-28, RF-012-16: sin máscaras, la orden las compila antes; Esc en esos pasos y
        en los de verificar no deja nada: ninguna operación en curso, ni datos, ni cifras, ni
        ficheros nuevos, y la barra de estado y el avance quedan como estaban."""
        files = self.files()
        cls = self.commands.registered_class(VERIFY)
        self.assertEqual(self.operations(COMPILE_TYPE, "done"), [])
        for events in (2, 40):
            with self.subTest(eventos=events), \
                    mock.patch.object(cls, "STEP_BUDGET_S", 1e-9), \
                    mock.patch.object(self.res_ops, "_call_panel", return_value={"FINISHED"}):
                self.start("Cancelada", ("Foso",))
                modal = self.running()
                self.drive(modal, stop_after=events)
                self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                self.assertIsNone(modal._steps)
                self.assertEqual(self.operations(VERIFY_TYPE, "running"), [])
                self.assertEqual(self.operations(COMPILE_TYPE, "running"), [])
                self.assertEqual(self.operations(VERIFY_TYPE, "done"), [])
                self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name LIKE "
                                           "'res_chk%'"), [(0,)])
                self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key LIKE "
                                           "'res.check_%'"), [(0,)])
                self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(COMPILE_TYPE, "done"), [])

    def test_c_compile_first_and_check_each_final_by_zone(self) -> None:
        """RF-012-21, RF-012-22, RF-012-23, RF-012-24 (CE-012-02, CE-012-06; M5): sin máscaras, la
        orden las compila (una ``gis.compile_constraints``) y verifica tres finales por pasos de
        ≤ 0,2 s: la torre no cumple en el foso (25 celdas, 100 m², 600 m³ de movimiento, 6,0 m
        de espesor máximo, centro (23; 23) local), la balsa en la segunda (24 m³ de corte) y la
        tercera cumple; las demás zonas, a 0 m³; la tabla, los grupos y las cifras (CALCULADO,
        con el ámbito de la restricción) son los de la operación de la versión, con las máscaras y
        las cuatro superficies como entradas; al terminar abre la ventana con la verificación."""
        panels = []
        with mock.patch.object(self.res_ops, "_call_panel",
                               side_effect=lambda name: panels.append(name) or {"FINISHED"}):
            self.start(NAME, tuple(FINALS))
            state, calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)  # RNF-012-06
        self.assertEqual(panels, [PANEL])
        self.assertEqual(len(self.operations(COMPILE_TYPE, "done")), 1)
        (verification,) = self.operations(VERIFY_TYPE, "done")
        self.assertIsNone(verification[2])
        self.assertEqual(_module("gis.masks.access").mask_state(  # compiladas a petición
            self.project, self.v01.uid)[0].value, "current")
        table = self.table()
        tower = self.codes["untouchable"]
        for key, wanted in (("cut_m3", 600.0), ("fill_m3", 0.0), ("moved_area_m2", 100.0),
                            ("counted_m3", 600.0)):
            value = table[(tower, 1, key)][0]
            self.assertAlmostEqual(value, wanted, delta=1e-9 * max(wanted, 1.0), msg=key)
        self.assertEqual((table[(tower, 1, "counted_m3")][1], table[(tower, 1, "verdict")][1]),
                         ("any", "fails"))
        pond = self.codes["no_cut"]
        self.assertAlmostEqual(table[(pond, 2, "cut_m3")][0], 24.0, delta=1e-9 * 24.0)
        self.assertEqual(table[(pond, 2, "verdict")][1], "fails")
        self.assertEqual(table[(tower, 2, "verdict")][1], "complies")
        failing = {(zone, final) for (zone, final, quantity), (_value, note) in table.items()
                   if quantity == "verdict" and note == "fails"}
        self.assertEqual(failing, {(tower, 1), (pond, 2)})
        untouched = (self.codes["no_cut"], self.codes["requires_access"], self.codes["avoid"],
                     "outside_perimeter", "outside_legal")
        for zone in untouched:  # las demás zonas de la final 1, a 0 m³
            for quantity in ("cut_m3", "fill_m3", "moved_area_m2"):
                self.assertEqual(table[(zone, 1, quantity)][0], 0.0, (zone, quantity))
        self.assertAlmostEqual(table[(self.codes["legal_limit"], 1, "cut_m3")][0], 600.0,
                               delta=1e-9 * 600.0)  # el límite legal contiene el foso
        with self.project.read() as conn:
            locator = self.verify.dataset_locator(self.verify.GROUPS, NAME, "V01")
            stored = self.verify.read_groups(conn, locator)
        by_final = {final: (zone, cells, area, volume, top, x, y)
                    for final, zone, cells, area, volume, top, x, y in stored}
        self.assertEqual(sorted(by_final), [1, 2])
        zone, cells, area, volume, top, x, y = by_final[1]
        self.assertEqual((zone, cells), (tower, 25))
        self.assertAlmostEqual(area, 100.0, delta=1e-9 * 100.0)
        self.assertAlmostEqual(volume, 600.0, delta=1e-9 * 600.0)
        self.assertAlmostEqual(top, 6.0, delta=1e-9 * 6.0)
        self.assertAlmostEqual(x, WEST + 23.0, delta=1e-6)
        self.assertAlmostEqual(y, SOUTH + 23.0, delta=1e-6)
        figures = self.rows("SELECT key, value, scope FROM gb_figure WHERE operation_uid = ? "
                            "ORDER BY fid", verification[0])
        self.assertTrue(figures)
        self.assertTrue(all(np.isfinite(value) for _key, value, _scope in figures))
        self.assertEqual({key for key, _value, _scope in figures}, {
            "res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2",
            "res.check_nodata_area_m2", "res.check_avoid_weighted_m3"})
        inputs = {role for (role,) in self.rows(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'",
            verification[0])}
        self.assertTrue({"start", "final_1", "final_2", "final_3", "masks_classes",
                         "masks_zones", "masks_report"} <= inputs, inputs)

        # La ventana: el título, los avisos y cada final con su resumen, su tabla y sus grupos.
        view = self.view
        self.assertEqual(view.verify_title, f"Verificación «{NAME}» en V01")
        foso, corte, limpia = (self.grids[name] for name in FINALS)
        self.assertEqual([item.name for item in view.verify_finals], [foso, corte, limpia])
        self.assertEqual([item.alert for item in view.verify_finals], [True, True, False])
        self.assertEqual(self.lines(1).text, f"«{foso}»: no cumple (Torre 132 kV)")
        self.assertEqual(self.lines(2).text, f"«{corte}»: no cumple (Balsa)")
        self.assertEqual(self.lines(3).text, f"«{limpia}»: cumple")
        rows = {item.code: item for item in self.lines(1).zones}
        self.assertEqual(rows[tower].name, "Torre 132 kV")
        self.assertEqual((rows[tower].verdict, rows[tower].alert), ("No cumple", True))
        self.assertEqual((rows[tower].cut, rows[tower].fill, rows[tower].moved),
                         (number(600.0, 1), number(0.0, 1), number(100.0, 1)))
        for code in untouched:
            self.assertEqual((rows[code].cut, rows[code].fill),
                             (number(0.0, 1), number(0.0, 1)), code)
        self.assertEqual(rows[self.codes["legal_limit"]].cut, number(600.0, 1))
        self.assertIn("outside_perimeter", rows)
        self.assertEqual(rows["outside_perimeter"].name, "Fuera del perímetro de actuación")
        self.assertEqual(rows["outside_legal"].name, "Fuera del límite legal")
        self.assertEqual(len(self.lines(3).groups), 0)
        (group,) = self.lines(1).groups
        self.assertEqual(group.text, (
            f"Torre 132 kV: no cumple · movimiento {number(600.0, 1)} m³ · "
            f"{number(100.0, 1)} m² · espesor máx. {number(6.0, 1)} m · "
            f"en ({number(WEST + 23.0, 1)}; {number(SOUTH + 23.0, 1)})"))
        self.assertEqual((float(group.x), float(group.y)), (WEST + 23.0, SOUTH + 23.0))
        self.assertGreaterEqual(float(group.radius), 25.0)
        (group_2,) = self.lines(2).groups
        self.assertIn("corte " + number(24.0, 1) + " m³", group_2.text)
        self.assertEqual([item.grid for item in view.verify_finals], [*self.grid_uids(), ""])
        self.assertEqual(len(self.grid_uids()), 2)  # solo las finales que incumplen

    def test_d_the_window_draws_the_table_the_groups_with_go_to_and_loads_the_grid(self) -> None:
        """RF-012-23 (M5): la ventana dibuja el título, la tabla de cada final (recinto,
        veredicto, corte, relleno y movido), los grupos con «Ir a» y, de la final que incumple,
        «Cargar la rejilla de incumplimientos»; «Ir a» encuadra la Vista 3D en el centro del
        grupo; la que cumple no ofrece rejilla; con otra verificación elegida, la ventana
        cambia."""
        layout = draw(getattr(bpy.types, PANEL), bpy.context)
        texts = layout.texts()
        self.assertIn(f"Verificación «{NAME}» en V01", texts)
        for final in self.view.verify_finals:
            self.assertIn(final.text, texts)
            for zone in final.zones:
                self.assertIn(zone.name, texts)
        for header in ("Recinto", "Veredicto", "Corte (m³)", "Relleno (m³)", "Movido (m²)"):
            self.assertIn(header, texts)
        buttons = [item for item in layout.of_kind("operator") if item.target == GO_TO]
        self.assertEqual(len(buttons), 2)
        group = self.lines(1).groups[0]
        place = (group.x, group.y, group.radius)  # texto: volver a llenar la vista invalida `group`
        self.assertEqual((buttons[0].properties.x, buttons[0].properties.y,
                          buttons[0].properties.radius), place)
        loads = [item for item in layout.of_kind("operator") if item.target == LOAD]
        self.assertEqual([item.properties.datasets for item in loads], self.grid_uids())
        self.assertIn("Cargar la rejilla de incumplimientos", texts)
        self.assertTrue(any(item.alert for item in layout.of_kind("label")
                            if item.text == self.lines(1).text))
        # Con cientos de restricciones la ventana no dibuja todo: primero lo que no cumple y lo que
        # mueve, y dice cuánto queda sin enseñar.
        with mock.patch.object(self.panels, "MAX_ZONE_ROWS", 3),                 mock.patch.object(self.panels, "MAX_GROUP_LINES", 0):
            self.panels.fill_verification(self.project, self.v01.uid, NAME)
            first = self.lines(1)
            self.assertEqual(len(first.zones), 3)
            self.assertEqual(first.zones[0].code, self.codes["untouchable"])  # la que no cumple
            self.assertTrue(first.zones[0].alert)
            self.assertEqual(len(first.groups), 0)
            self.assertRegex(first.more, r"^Sin enseñar: \d+ recintos más; 1 grupo más, el más "
                                         r"pequeño$")
            self.assertTrue(self.lines(3).more.startswith("Sin enseñar: "))
            self.assertEqual(len(self.lines(3).zones), 3)
        self.panels.fill_verification(self.project, self.v01.uid, NAME)
        self.assertEqual(self.lines(1).more, "")
        for obj in list(bpy.context.scene.objects):  # sin objetos: la cota es la del cursor
            bpy.data.objects.remove(obj)
        origin = self.project.origin
        area = view3d_areas()[0]
        space, rv3d = area.spaces.active, area.spaces.active.region_3d
        rv3d.view_location = (0.0, 0.0, 0.0)
        rv3d.view_distance = 1.0
        space.clip_start, space.clip_end = 0.01, 1000.0
        with in_view(area):
            self.assertEqual(bpy.ops.geoblender.core_go_to_place(
                x=place[0], y=place[1], radius=place[2]), {"FINISHED"})
        self.assertAlmostEqual(rv3d.view_location.x, float(place[0]) - origin.x0, places=3)
        self.assertAlmostEqual(rv3d.view_location.y, float(place[1]) - origin.y0, places=3)

    def test_da_the_group_line_is_read_whole_and_go_to_has_its_own_row(self) -> None:
        """RF-012-23 (T46; hallazgo 2 del H3): en la ventana de la verificación, a escala 1,0 y
        1,25 y también con la ventana estrecha, la línea de cada grupo («Torre 132 kV: no cumple ·
        movimiento … m³ · … m² · espesor máx. … m · en (…; …)») se lee entera (el volumen, el área,
        el espesor máximo y las coordenadas) en etiquetas propias, partidas al ancho de la ventana
        (``labels.draw_wrapped``) y ninguna más ancha que él; «Ir a» va en su propia fila (ninguna
        etiqueta comparte fila con él: Blender se quedaría con la mitad del texto) y sigue dando
        el lugar de su grupo; ninguna cifra ni texto cambia."""
        labels, compat = _module("bl.ui.labels"), _module("bl.compat")
        groups = [(group.text, (group.x, group.y, group.radius))
                  for final in self.view.verify_finals for group in final.groups]
        self.assertEqual(len(groups), 2)
        self.assertIn("espesor máx.", groups[0][0])  # el de la torre: volumen, área, espesor, sitio
        wide = labels.dialog_width(self.panels.VERIFY_WIDTH_PX)
        for scale in (1.0, 1.25):
            for width in (wide, 300.0):  # la ventana y una estrecha, que obliga a partir
                with (self.subTest(escala=scale, ancho=width),
                      mock.patch.object(compat, "ui_scale", return_value=scale),
                      mock.patch.object(labels, "dialog_width", return_value=width)):
                    layout = draw(getattr(bpy.types, PANEL), bpy.context)
                    buttons = [item for item in layout.of_kind("operator") if item.target == GO_TO]
                    self.assertEqual(
                        [(item.properties.x, item.properties.y, item.properties.radius)
                         for item in buttons], [place for _text, place in groups])
                    for (text, _place), button in zip(groups, buttons):
                        at = layout.items.index(button)
                        mine = layout.items[at - 1].layout
                        lines = []
                        while at and layout.items[at - 1].kind == "label" \
                                and layout.items[at - 1].layout is mine:
                            at -= 1
                            lines.insert(0, layout.items[at].text)
                        self.assertEqual(" ".join(lines), text)
                        for line in lines:
                            self.assertLessEqual(labels.label_px(line, scale=scale), width, line)
                        if width < wide:
                            self.assertGreater(len(lines), 1, text)  # no cabe: partida
                        self.assertIsNot(button.layout, mine)
                        self.assertEqual([item.kind for item in layout.items
                                          if item.layout is button.layout], ["operator"])
                        self.assertTrue(button.enabled)

    def test_e_the_compliance_grid_loads_over_the_final_surface_with_the_colours_of_the_011(
            self) -> None:
        """RF-012-23, D-42 (M5): la rejilla de incumplimientos de cada final que incumple se
        carga como un objeto ``COMPLIANCE_GRID`` en la colección de V01, con una celda por celda
        que incumple (dos caras) a la cota de la superficie final y el color de la 011 por clase
        (desmonte en rojo: el espesor con signo es −6 m); la final que cumple no tiene rejilla;
        cargar de nuevo no duplica; la vista no escribe nada en el proyecto."""
        files = self.files()
        for index, (cells, depth) in enumerate(((25, 6.0), (6, 1.0)), start=1):
            with self.subTest(final=index):
                uid = self.grid_uids()[index - 1]
                self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid),
                                 {"FINISHED"})
                found = [obj for obj in bpy.data.objects
                         if obj.geoblender.kind == KIND and obj.geoblender.dataset_uid == uid]
                self.assertEqual(len(found), 1)
                obj = found[0]
                (collection,) = obj.users_collection
                self.assertIn(collection, self.versions.version_collections()[self.v01.uid]
                              .children.values())
                mesh = obj.data
                self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (4 * cells, 2 * cells))
                world = self.mesh.mesh_vertices_world(mesh, self.project.origin)
                heights = set(np.round(world[:, 2], 3))
                self.assertEqual(heights, {START_M - depth})
                box = FINALS["Foso" if index == 1 else "Corte balsa"][1]
                self.assertGreaterEqual(world[:, 0].min() - WEST, box[0] - 1e-3)
                self.assertLessEqual(world[:, 0].max() - WEST, box[2] + 1e-3)
                self.assertGreaterEqual(world[:, 1].min() - SOUTH, box[1] - 1e-3)
                self.assertLessEqual(world[:, 1].max() - SOUTH, box[3] + 1e-3)
                classes = self.mesh.attribute_values(mesh, self.res_views.CLASS_ATTRIBUTE)
                self.assertEqual(set(classes.tolist()), {self.res_views.CUT})
                colors = np.empty(len(mesh.polygons) * 4, dtype=np.float32)
                mesh.attributes[self.res_views.COLOR_ATTRIBUTE].data.foreach_get(
                    "color", colors)
                np.testing.assert_allclose(
                    colors.reshape(-1, 4), np.tile(self.res_views._RAMPS[self.res_views.CUT][1],
                                                   (len(mesh.polygons), 1)), atol=1e-6)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name = ?",
                                   f"{PREFIX}prueba_3"), [(0,)])
        before = len([obj for obj in bpy.data.objects if obj.geoblender.kind == KIND])
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=self.grid_uids()[0]),
                         {"FINISHED"})
        self.assertEqual(len([obj for obj in bpy.data.objects if obj.geoblender.kind == KIND]),
                         before)
        self.assertEqual(self.files(), files)

    def test_ea_a_constant_final_on_another_version_has_its_own_check_and_grid(self) -> None:
        """RF-012-21, RF-012-23, RF-012-16, D-43: en V02, que no tiene máscaras ni verificación,
        la final a cota constante («Cota final»: toda la ventana a 96 m, 4 m más baja) compila las
        máscaras de V02 antes y verifica: la torre y la franja fuera del perímetro no cumplen; la
        ventana es la de V02 (la de V01 sigue en V01); su rejilla de incumplimientos se carga a
        la cota constante y la de V01, intacta."""
        self.set_active(self.v02)
        try:
            with mock.patch.object(self.res_ops, "_call_panel", return_value={"FINISHED"}):
                self.assertEqual(bpy.ops.geoblender.res_verify_constraints(
                    "EXEC_DEFAULT", name="Constante", start=self.grids["Partida"],
                    final_elevation="96", in_steps=True), {"RUNNING_MODAL"})
                state, _calls = self.drive(self.running())
            self.assertEqual(state, {"FINISHED"})
            v02 = self.v02.uid
            self.assertEqual(self.rows(
                "SELECT count(*) FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = "
                "o.revision_uid WHERE r.version_uid = ? AND o.status = 'done' AND o.op_type IN "
                "(?, ?)", v02, COMPILE_TYPE, VERIFY_TYPE), [(2,)])
            self.assertEqual(self.view.verify_title, "Verificación «Constante» en V02")
            (final,) = self.view.verify_finals
            self.assertTrue(final.name.startswith("Cota constante"), final.name)
            self.assertTrue(final.alert)
            failing = {row.code for row in final.zones if row.alert}
            legal = self.codes["legal_limit"]
            self.assertEqual(failing, {self.codes["untouchable"], self.codes["no_cut"],
                                       "outside_perimeter", "outside_legal", f"{legal}:inner"})
            self.assertTrue(all(line.x for line in final.groups))
            (uid,) = self.grid_uids("Constante")
            self.assertEqual(final.grid, uid)
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
            obj = next(obj for obj in bpy.data.objects
                       if obj.geoblender.kind == KIND and obj.geoblender.dataset_uid == uid)
            world = self.mesh.mesh_vertices_world(obj.data, self.project.origin)
            self.assertEqual(set(np.round(world[:, 2], 3)), {96.0})
            (collection,) = obj.users_collection
            self.assertIn(collection, self.versions.version_collections()[v02].children.values())
            self.assertEqual(len(obj.data.polygons) % 2, 0)
            self.set_active(self.v01)
            self.panels.fill_verification(self.project, self.v01.uid)
            self.assertEqual(self.view.verify_title, f"Verificación «{NAME}» en V01")
            self.assertEqual(self.table()[(self.codes["untouchable"], 1, "verdict")][1], "fails")
        finally:
            self.set_active(self.v01)

    def test_f_freezing_lists_what_does_not_comply_and_asks_for_a_reason(self) -> None:
        """RF-012-25 (M6): repetida la verificación con una sola final (sustituye a la anterior),
        el diálogo de congelar V01.r1 lista la verificación con lo que no cumple (m³ por recinto)
        y las dos superficies que dejaron de estar verificadas, cuenta los hallazgos en su frase
        (no solo lo obsoleto) y pide el motivo; sin aceptar o sin motivo, no congela."""
        self.verify_all(NAME, ("Foso",))
        checks = self.rows(  # las de V01: la primera, sustituida, y la nueva
            "SELECT o.superseded_by IS NOT NULL FROM gb_operation AS o JOIN gb_revision AS r ON "
            "r.uid = o.revision_uid WHERE o.op_type = ? AND o.status = 'done' AND "
            "r.version_uid = ? ORDER BY o.fid", VERIFY_TYPE, self.v01.uid)
        self.assertEqual(checks, [(1,), (0,)])
        dialog = self.versions_ops.revision_dialog(self.project, self.v01.uid)
        self.assertEqual(len(dialog.accept), 3)
        by_name = {item.name: item for item in dialog.accept}
        self.assertEqual(set(by_name), {NAME, self.grids["Corte balsa"], self.grids["Limpia"]})
        verification = by_name[NAME]
        self.assertIsNotNone(verification.finding)
        self.assertIn(self.codes["untouchable"], verification.finding)
        self.assertIn("600", verification.finding)
        for name in (self.grids["Corte balsa"], self.grids["Limpia"]):
            self.assertIn("sin verificación al día", by_name[name].finding.lower())
        self.assertEqual(dialog.accept_text(), (
            "Hay 3 hallazgos de las verificaciones: si congela, quedarán anotados"))
        lines = dialog.accept_lines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line.startswith("«") and "»: " in line for line in lines), lines)
        self.assertTrue(any(NAME in line and "no cumple" in line.lower() for line in lines), lines)
        self.assertEqual(dialog.confirm_text, "Aceptar y congelar")
        # El diálogo de la orden: el motivo y la lista (con sus hallazgos), sin ventana real.
        cls = self.commands.registered_class(NEW_REVISION)
        context = SimpleNamespace(window=None, window_manager=SimpleNamespace(
            invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"})))
        fake = operator_self(cls, report=lambda kind, text: None, version_uid=self.v01.uid,
                             reason="", accept="", in_steps=False)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        cls.draw(fake, bpy.context)
        shown = fake.layout.texts()
        self.assertTrue(any("3 hallazgos" in text for text in shown), shown)
        self.assertEqual([item.target for item in fake.layout.of_kind("prop")], ["reason"])
        token = fake.accept
        self.assertEqual(sorted(part.split(":")[0] for part in token.split(",")),
                         ["dataset", "dataset", "operation"])
        # Sin aceptar o sin motivo, no congela (nada cambia).
        revisions = self.rows("SELECT count(*), max(number) FROM gb_revision WHERE version_uid = ?",
                              self.v01.uid)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_revision("EXEC_DEFAULT", version_uid=self.v01.uid,
                                                 reason="Entrega 1")
        self.assertIn("V01", str(caught.exception))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_revision("EXEC_DEFAULT", version_uid=self.v01.uid,
                                                 reason="", accept=token)
        self.assertIn("motivo", str(caught.exception).lower())
        self.assertEqual(self.rows("SELECT count(*), max(number) FROM gb_revision WHERE "
                                   "version_uid = ?", self.v01.uid), revisions)

    def test_g_freezing_with_the_acceptance_records_the_findings_in_the_revision(self) -> None:
        """RF-012-25, RF-009-08 (M6): con la aceptación y el motivo, V01.r1 se congela y la
        revisión guarda lo aceptado con la nota de cada hallazgo (``finding``) y el motivo; las
        dos operaciones (compilar y verificar) siguen siendo las de V01."""
        dialog = self.versions_ops.revision_dialog(self.project, self.v01.uid)
        reason = "Entrega para revisión de la propiedad"
        self.assertEqual(bpy.ops.geoblender.core_new_revision(
            "EXEC_DEFAULT", version_uid=self.v01.uid, reason=reason, accept=dialog.accepted),
            {"FINISHED"})
        ((state, accepted),) = self.rows("SELECT state, accepted FROM gb_revision WHERE "
                                         "version_uid = ? AND number = 1", self.v01.uid)
        self.assertEqual(state, "frozen")
        import json

        body = json.loads(accepted)
        self.assertEqual(body["reason"], reason)
        findings = {item["name"]: item.get("finding") for item in body["items"]}
        self.assertEqual(set(findings), {NAME, self.grids["Corte balsa"], self.grids["Limpia"]})
        self.assertTrue(all(findings.values()))
        self.assertIn("600", findings[NAME])

    def test_h_a_superseded_version_or_a_read_only_project_still_shows_the_verification(
            self) -> None:
        """RF-012-28, RF-012-23 (HU-012-7; M6): con el proyecto en solo lectura o la versión
        activa SUPERADO (V02, la de la verificación de la cota constante), «Verificar un diseño
        por recinto…» no está disponible y dice por qué («Proyecto en solo lectura: …»; «V02 está
        en estado SUPERADO: cree una versión nueva a partir de ella», también en su descripción);
        la ventana de la verificación sigue enseñando el título, la tabla de cada final y los
        grupos con «Ir a» y «Cargar la rejilla de incumplimientos» (activos), dice el motivo en
        alerta y deja desactivado «Verificar»."""
        enabled = draw(getattr(bpy.types, PANEL), bpy.context)
        again = [item for item in enabled.of_kind("operator") if item.target == VERIFY]
        self.assertEqual([item.enabled for item in again], [True])
        self.assertFalse([item for item in enabled.of_kind("label") if item.icon == "LOCKED"])
        self.assertTrue(bpy.ops.geoblender.res_verify_constraints.poll())
        looking = {target: len([item for item in enabled.of_kind("operator")
                                if item.target == target]) for target in (GO_TO, LOAD)}
        self.assertTrue(all(looking.values()), looking)
        cls = self.commands.registered_class(VERIFY)
        project = self.project

        def check(reason: str, buttons: dict[str, int] | None) -> None:
            self.assertFalse(bpy.ops.geoblender.res_verify_constraints.poll())
            title = self.view.verify_title
            self.assertTrue(title)
            layout = draw(getattr(bpy.types, PANEL), bpy.context)
            texts = " ".join(layout.texts())
            self.assertIn(reason, texts)
            shown = [item for item in layout.of_kind("label") if item.icon == "LOCKED"]
            self.assertEqual(len(shown), 1)
            self.assertTrue(shown[0].alert)
            self.assertIn(title, texts)
            for final in self.view.verify_finals:
                self.assertIn(final.text, texts)
            self.assertEqual([item.enabled for item in layout.of_kind("operator")
                              if item.target == VERIFY], [False])
            for target in (GO_TO, LOAD):
                found = [item for item in layout.of_kind("operator") if item.target == target]
                self.assertTrue(found and all(item.enabled for item in found), target)
                if buttons is not None:  # los mismos botones que con la versión editable
                    self.assertEqual(len(found), buttons[target])

        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            check(reason, looking)
        self.assertTrue(bpy.ops.geoblender.res_verify_constraints.poll())

        with project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.addCleanup(self.set_active, self.v01)
        note = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertEqual(self.versions.not_editable_text(), note)
        self.panels.fill_verification(project, self.v02.uid)
        self.assertIn("en V02", self.view.verify_title)
        check(note, None)
        self.assertIn(note, cls.description(bpy.context, SimpleNamespace()))
        self.set_active(self.v01)
        self.assertTrue(bpy.ops.geoblender.res_verify_constraints.poll())

    def test_z_disabling_geoblender_midway_leaves_nothing(self) -> None:
        """RF-012-28, RF-001-05, Principio 8 (plan 012 §2.1; M6): desactivar Geoblender con
        «Verificar un diseño por recinto…» a mitad (la operación en curso, ya con las rutas de
        su tabla y de sus rejillas reclamadas) la cancela como Esc antes de quitar las clases:
        «Verificación cancelada: no ha quedado nada a medias»; la operación queda «cancelada»
        y ninguna ruta reclamada, sin datos, cifras ni rejillas nuevos, ningún operador de
        Geoblender vivo; quita la ventana de la verificación, la orden y el cargador de las
        rejillas de incumplimientos, y la huella de Blender vuelve a la del principio de la
        sesión."""
        operations_module = _module("core.provenance.operations")
        operations = self.rows("SELECT uid, status FROM gb_operation ORDER BY uid")
        datasets = self.rows("SELECT name, uid, status, content_sha256 FROM gb_dataset "
                             "ORDER BY name")
        figures = self.rows("SELECT count(*) FROM gb_figure")
        files = self.names()
        cls = self.commands.registered_class(VERIFY)
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9), \
                mock.patch.object(self.res_ops, "_call_panel", return_value={"FINISHED"}):
            self.start("Interrumpida", ("Foso",))
            operator = self.running()
            for _ in range(MAX_EVENTS):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
                if operations_module.claimed_paths(self.project):
                    break
            else:
                self.fail("la verificación no llega a reclamar rutas")
        running = self.operations(VERIFY_TYPE, "running")
        self.assertEqual(len(running), 1)
        log = operator.report_log

        blender_ext.disable()
        self.assertEqual(log, ["Verificación cancelada: no ha quedado nada a medias"])
        self.assertEqual(self.operations(VERIFY_TYPE, "running"), [])
        self.assertEqual(operations_module.claimed_paths(self.project), frozenset())
        self.assertEqual(
            [row for row in self.rows("SELECT uid, status FROM gb_operation ORDER BY uid")
             if row not in operations], [(running[0][0], "cancelled")])
        self.assertEqual(self.rows("SELECT name, uid, status, content_sha256 FROM gb_dataset "
                                   "ORDER BY name"), datasets)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_figure"), figures)
        self.assertEqual(self.names(), [name for name in files if name != ".lock"])
        alive = [type(op).__name__ for window in bpy.context.window_manager.windows
                 for op in window.modal_operators if op is not None]
        self.assertEqual([name for name in alive if name.startswith("GEOBLENDER_")], [])
        self.assertFalse(hasattr(bpy.types, PANEL))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
