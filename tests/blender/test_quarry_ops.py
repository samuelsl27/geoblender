# SPDX-License-Identifier: GPL-3.0-or-later
"""Las órdenes de la cantera con dos superficies en Blender (spec 014; plan 014 §5.3.3, §5.5;
comprobación manual M1).

**«Límite desde el perímetro…»** (T20; HU-014-1; RF-014-01): la orden
``geoblender.des_create_limit_from_perimeter`` (``bl.ops.des``) calcula el **recinto excavable** de la
versión activa —el corte admitido de sus máscaras con dato en la superficie de partida— con
``design.steps.excavation_area_run``: **Calcular** lanza el modal por pasos (``_StepsModal``, con el
avance «Calculando el recinto excavable… 40 % · Esc: cancelar») hasta el resumen, sin registrar nada
(D-14 de la 013); **Crear** (la misma orden con ``confirm=True``) lo registra en una transacción como
``des_rcn_<nombre>`` con su área (``des.rcn_area_m2``); **Cancelar**, cerrar la ventana o Esc no dejan
nada. El cargador de ``des_rcn_`` (``bl.scene.des_views``) lo dibuja como objeto ``DESIGN`` sobre la
superficie de partida, y la barra N «Diseño» enseña su ficha.

Un proyecto por clase, pequeño y con las cifras a mano (ventana de 60 × 60 m con celdas de 2 m, V01 y
V02; el límite legal de (4, 4) a (52, 52) con 2 m hacia dentro, el perímetro de actuación de (2, 10) a
(56, 56) y una zona «sin corte» de (20, 20) a (30, 30) sin resguardo; una ladera ``100 + 0,25·y +
0,0625·x`` y una rejilla «sin dato» con dato solo en la primera columna, fuera del perímetro). El
recinto, a mano: los centros de celda con ``7 ≤ x ≤ 49`` e ``11 ≤ y ≤ 49`` (22 × 20 = 440 celdas)
menos las 5 × 5 de la zona sin corte, **415 celdas, 1.660 m²**; lo que lo separa del perímetro (621
celdas): 117 fuera del límite legal (468 m²), 64 del resguardo hacia dentro (256 m²) y 25 sin corte
(100 m²). Las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-014-01 (a): la orden es la real (con la puerta de la procedencia y los pasos con Esc) de
  ``des.excavation_area``; su diálogo pide el nombre y la superficie de partida y propone el terreno
  (T45 de la 013); el de la confirmación propone «Crear».
- RF-014-01, D-14 (b; M1): Calcular da el resumen («Recinto «Límite»: 415 celdas (1660 m²)») sin
  registrar nada; Crear registra la operación, el dato (1 en las 415 celdas a mano, sin dato fuera),
  su cifra (1.660 m² a ≤ 10⁻⁹ relativo), sus ajustes y sus entradas; cada llamada del modal dura menos
  de 0,2 s; el resumen y el avance, en los dos idiomas.
- RF-014-01 (c): un recinto vacío se rechaza nombrando la versión y el área de cada parte que lo vacía,
  en los dos idiomas, y no deja nada.
- D-14 (d): Esc a mitad, con el temporal ya escrito, «Cancelar» la confirmación y un nombre que falta
  no dejan nada.
- RF-014-01 (e; M1): cargar ``des_rcn_límite`` da un objeto ``DESIGN`` «Recinto excavable …» con un
  vértice en el centro de cada celda del recinto a la cota de la superficie de partida (relativo al
  GeoOrigin, matriz identidad); la barra N enseña su ficha (su superficie de partida y su cifra, sin las
  semillas de una envolvente); el diálogo sigue proponiendo el terreno, no el recinto.
- Principio 8 (z): desactivar Geoblender quita la orden y el cargador y descarta el cálculo abierto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import tempfile
import time
import unittest
import uuid
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

LIMIT = "geoblender.des_create_limit_from_perimeter"
LIMIT_CLASS = "GEOBLENDER_OT_des_create_limit_from_perimeter"
LOAD = "geoblender.core_load_into_view"
PANEL = "GEOBLENDER_PT_des_design"
VIEW_PROPERTY = "geoblender_design"
AREA_TYPE = "des.excavation_area"
AREA_FIGURE = "des.rcn_area_m2"
KIND = "DESIGN"
REASON = "Prueba de «Límite desde el perímetro…»"
PERSON = "Samuel (IMGA)"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 10.0, 56.0, 56.0)
NO_CUT = (20.0, 20.0, 30.0, 30.0)
NAME = "Límite"
AREA_CELLS = 415
AREA_M2 = 1_660.0
PROPERTIES = {
    "name": ("Name", "Name of the excavation boundary, unique in the active version"),
    "surface": ("Start surface", "Ground of the project or of the active version: its cells "
                                 "without data stay out of the excavation boundary"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción."""
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 5_000


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def centers() -> tuple[np.ndarray, np.ndarray]:
    """Los centros de celda locales ``(x, y)`` de la ventana (fila 0 al norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    x = STEP_M * index + STEP_M / 2
    y = SIZE_M - (STEP_M * index + STEP_M / 2)
    return np.meshgrid(x, y)


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (exacta en binario)."""
    x, y = centers()
    return 100.0 + 0.25 * y + 0.0625 * x


def hand_area() -> np.ndarray:
    """El recinto a mano (véase el módulo): dentro del límite menos su resguardo de 2 m, dentro del
    perímetro y fuera de la zona sin corte."""
    x, y = centers()
    inner = (x >= 7) & (x <= 49) & (y >= 11) & (y <= 49)
    no_cut = (x >= 21) & (x <= 29) & (y >= 21) & (y <= 29)
    return inner & ~no_cut


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class LimitFromPerimeterTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, la ladera y la
    rejilla «sin dato», para toda la clase (las pruebas, en el orden de sus letras: cada una parte de
    lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t20-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.views = _module("bl.scene.views")
        cls.mesh = _module("bl.scene.mesh")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        cls.model = _module("core.project.model")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="cantera",
                                                      title="Cantera", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        hollow = np.full((CELLS, CELLS), np.nan)
        hollow[:, 0] = 100.0  # solo la primera columna, fuera del perímetro de actuación
        cls.hollow = cls.write_grid("Sin dato", hollow)
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        cls.dataset = cls.dprov.dataset_name("rcn", NAME)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y una zona sin corte (sin
        resguardo), como las dejará la orden de la 012."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 12), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.NO_CUT, "Sin corte", NO_CUT)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                   srs_id=cls.project.record.crs_epsg)

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

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no pasa a la siguiente

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(LIMIT)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operations(self, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, settings FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", AREA_TYPE)
        return self.rows(sql + " AND status = ? ORDER BY fid", AREA_TYPE, status)

    def datasets(self) -> list[str]:
        """Los recintos vivos del proyecto."""
        return [name for (name,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name LIKE 'des!_rcn!_%' ESCAPE '!' AND status = "
            "'current' ORDER BY name")]

    def names(self) -> list[str]:
        """Todos los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def temporaries(self) -> list[str]:
        """Los temporales que esperan junto a su destino (``*.tmp-*``)."""
        return [name for name in self.names() if ".tmp" in name]

    def nothing_left(self, files: list[str], done: int) -> None:
        """Ni una operación más del recinto, ni una en curso, ni un dato, una cifra o un fichero
        nuevos, ni un cálculo abierto."""
        self.assertEqual(len(self.operations("done")), done)
        self.assertEqual(self.operations("running"), [])
        self.assertEqual(len(self.datasets()), done)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key = ?", AREA_FIGURE),
                         [(done,)])
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)
        self.assertIsNone(self.des_ops.calculation())

    def running(self) -> Any:
        """El modal de la orden en marcha (el único con pasos)."""
        cls = self.cls
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{LIMIT} no está en marcha")
        return found[0]

    def drive(self, operator: Any, *, stop_after: int | None = None,
              until: Any = None) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba (o ``stop_after`` eventos,
        o hasta que ``until()`` sea verdad): su final y lo que duró cada llamada (s de CPU del
        proceso)."""
        calls: list[float] = []
        for index in range(MAX_EVENTS):
            if stop_after is not None and index == stop_after:
                return {"RUNNING_MODAL"}, calls
            if until is not None and until():
                return {"RUNNING_MODAL"}, calls
            started = time.process_time()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.process_time() - started)
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("el cálculo no acaba")

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: el recinto «Límite» sobre la ladera."""
        return {"name": NAME, "surface": self.ground, "in_steps": True, **values}

    def start(self, **values: Any) -> Any:
        """Lanza la orden desde la interfaz (por pasos) y devuelve el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **self.form(**values)), {"RUNNING_MODAL"})
        return self.running()

    def calculate(self, **values: Any) -> tuple[set[str], list[float], Any]:
        """Calcula por pasos hasta el final (la confirmación, sustituida: sin ventana, el
        temporizador no corre): el final del modal, lo que duró cada llamada y el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            self.assertEqual(bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **self.form(**values)), {"RUNNING_MODAL"})
            modal = self.running()
            state, calls = self.drive(modal)
        self.assertEqual(ask.call_count, 1 if state == {"FINISHED"} else 0)
        if state == {"FINISHED"}:
            self.assertEqual(ask.call_args.kwargs.get("idname"), LIMIT)
        return state, calls, modal

    def create(self) -> set[str]:
        """«Crear»: la misma orden con ``confirm=True``."""
        return bpy.ops.geoblender.des_create_limit_from_perimeter("EXEC_DEFAULT", confirm=True,
                                                                  in_steps=True)

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana)."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "surface": "", "confirm": False, "in_steps": False,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        fake = operator_self(self.cls, report=lambda kind, text: None, **fields)
        return fake, context, dialog

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_confirmation(self) -> None:
        """RF-014-01 (plan §5.3.3, §5.5): «Límite desde el perímetro…» es una orden real con la
        puerta de la procedencia y los pasos con Esc, de ``des.excavation_area``; su diálogo pide el
        nombre y la superficie de partida (propone «Recinto excavable» y el terreno, la primera que
        no es una rejilla de un diseño: T45 de la 013) y Calcular; el de la confirmación propone
        «Crear»; sus textos tienen su español."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (AREA_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[AREA_TYPE].commands, (LIMIT,))
        cat = self.commands.catalog()
        self.assertEqual(cat.commands[LIMIT].label_es, "Límite desde el perímetro…")
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])

        fake, context, dialog = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Límite desde el perímetro…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual(fake.name, "Recinto excavable")
        self.assertEqual(fake.surface, self.ground)  # el terreno, no «Sin dato»
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        self.assertEqual(listed[:2], [self.ground, self.hollow])  # y las máscaras, como en la 013
        shown = draw(cls, bpy.context, name="", surface=self.ground, confirm=False).texts()
        for heading in ("Nombre", "Superficie de partida"):
            self.assertIn(heading, shown)
        given, _context, _dialog = self.fake_dialog(
            name="Mío", surface=self.hollow,
            properties=SimpleNamespace(is_property_set=lambda name: name == "surface"))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.surface), ("Mío", self.hollow))  # lo dado no cambia

        # La confirmación: sin cálculo abierto se niega; con él, «Crear».
        reports: list[tuple[Any, str]] = []
        fake.confirm = True
        fake.report = lambda kind, text: reports.append((kind, text))
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports[-1][1], "No hay un cálculo abierto: calcule antes")
        held = SimpleNamespace(open=True, warnings=lambda: (), op_type=AREA_TYPE,
                               discard=lambda: None)
        with mock.patch.object(self.des_ops, "calculation", return_value=held):
            dialog.reset_mock()
            self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Crear")

    def test_b_calculate_then_create_the_excavation_boundary(self) -> None:
        """RF-014-01, D-14 de la 013 (M1): Calcular el recinto «Límite» de V01 sobre la ladera da el
        resumen (415 celdas, 1.660 m²) y deja el temporal sin registrar nada; Crear registra la
        operación hecha, el dato ``des_rcn_límite`` (1 en las 415 celdas a mano y sin dato en las
        demás), su cifra CALCULADO (1.660 m² a ≤ 10⁻⁹ relativo), sus ajustes (nombre y superficie de
        partida) y sus entradas (la superficie y las máscaras), apuntada para Ctrl+Z. Cada llamada del
        modal dura menos de 0,2 s; el avance y el resumen, en los dos idiomas (principio 10)."""
        files = self.names()
        self.i18n.set_language("en")
        state, _calls, modal = self.calculate(name="Pit")
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.view.summary_title, "Excavation boundary «Pit» in V01")
        self.assertRegex(self.view.summary[0].name,
                         r"^Excavation boundary «Pit»: 415 cells \(1\D?660 m²\)$")
        self.assertEqual(modal._status_text(self.model.Progress("area", 2, 5, "…")),
                         "Computing the excavation boundary… 40 % · Esc: cancel")
        self.des_ops.discard_calculation()
        self.nothing_left(files, 0)
        self.i18n.set_language("es")

        state, calls, modal = self.calculate()
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        self.assertEqual(modal._status_text(self.model.Progress("area", 2, 5, "…")),
                         "Calculando el recinto excavable… 40 % · Esc: cancelar")
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.version, held.open),
                         (AREA_TYPE, NAME, "V01", True))
        self.assertEqual(self.operations(), [])  # sin registrar (D-14)
        self.assertEqual(self.datasets(), [])
        self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual(self.view.summary_title, "Recinto excavable «Límite» en V01")
        lines = [(item.name, item.alert) for item in self.view.summary]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0][0], r"^Recinto excavable «Límite»: 415 celdas \(1\D?660 m²\)$")
        self.assertFalse(lines[0][1])

        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no deshace la base: apuntada
        self.assertEqual(journal.entries[-1].label, AREA_TYPE)
        ((uid, _status, settings),) = self.operations("done")
        self.assertEqual(json.loads(settings), {"name": NAME, "surface": self.ground})
        self.assertEqual(self.datasets(), [self.dataset])
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.view.summary_title, "")
        ((figure, kind),) = self.rows("SELECT value, kind FROM gb_figure WHERE operation_uid = ? "
                                      "AND key = ?", uid, AREA_FIGURE)
        self.assertEqual(kind, "CALCULADO")
        self.assertLessEqual(abs(figure - AREA_M2) / AREA_M2, 1e-9)
        roles = {role: name for name, role in self.rows(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset'", uid)}
        self.assertEqual(roles.get("surface"), self.ground)
        self.assertGreater(len(roles), 1)  # y las máscaras de V01
        raster = self.surfaces.read_surface(self.project, self.dataset, version_uid=self.v01.uid)
        wanted = hand_area()
        self.assertEqual(int(np.count_nonzero(wanted)), AREA_CELLS)
        self.assertTrue(np.array_equal(np.isfinite(raster.values), wanted))
        self.assertTrue(np.all(raster.values[wanted] == 1.0))
        self.assertTrue(set(files) <= set(self.names()))  # nada se borró

    def test_c_an_empty_boundary_is_refused_with_what_empties_it(self) -> None:
        """RF-014-01 (casos límite de la spec): sobre la rejilla «sin dato» el recinto queda vacío y
        se rechaza al calcular, nombrando la versión y el área de cada parte que lo vacía (fuera del
        límite legal 468 m², resguardo hacia dentro 256 m², sin corte 100 m², sin dato de terreno
        1.660 m²), desde la interfaz y desde un guion, en los dos idiomas; no deja nada."""
        files = self.names()
        done = len(self.operations("done"))
        parts = ("perímetro fuera del límite legal: 468 m²", "resguardo hacia dentro del límite: "
                 "256 m²", "zonas sin corte, solo relleno o solo restauración: 100 m²")
        modal = self.start(name="Vacío", surface=self.hollow)
        state, _calls = self.drive(modal)
        self.assertEqual(state, {"CANCELLED"})
        shown = " ".join(modal.report_log)
        self.assertIn("El recinto excavable de la versión V01 está vacío", shown)
        for part in parts:
            self.assertIn(part, shown)
        self.assertRegex(shown, r"sin dato de terreno: 1\D?660 m²")
        self.nothing_left(files, done)
        self.i18n.set_language("en")
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", name="Vacío", surface=self.hollow)
        self.assertIn("The excavation area of version V01 is empty", str(raised.exception))
        self.nothing_left(files, done)

    def test_d_esc_cancel_and_a_missing_field_leave_nothing(self) -> None:
        """D-14 de la 013 (M1): Esc a mitad de calcular, también con el temporal ya escrito,
        «Cancelar» la confirmación (``cancel``) y un nombre o una superficie que faltan no dejan
        nada: ni operaciones, ni datos, ni cifras, ni ficheros, ni cálculo abierto. La ventana del
        cálculo, cerrada, no descarta lo ya abierto."""
        files = self.names()
        done = len(self.operations("done"))
        with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):
            for label, events in (("al empezar", 1), ("con el temporal escrito", None)):
                with self.subTest(momento=label):
                    modal = self.start(name="Esc")
                    if events is None:
                        self.drive(modal, until=lambda: bool(self.temporaries()))
                        self.assertTrue(self.temporaries(), "no llegó a escribir el temporal")
                    else:
                        self.drive(modal, stop_after=events)
                    self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                    self.assertIsNone(modal._steps)
                    self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                    self.nothing_left(files, done)
        state, _calls, _modal = self.calculate(name="Descartado")
        self.assertEqual(state, {"FINISHED"})
        form = operator_self(self.cls, confirm=False, in_steps=False)
        self.cls.cancel(form, bpy.context)  # la ventana del cálculo: lo abierto sigue
        self.assertIsNotNone(self.des_ops.calculation())
        confirmation = operator_self(self.cls, confirm=True, in_steps=False)
        self.cls.cancel(confirmation, bpy.context)  # «Cancelar» o cerrar la ventana
        self.nothing_left(files, done)
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_create_limit_from_perimeter(
                "EXEC_DEFAULT", **{**self.form(in_steps=False), "name": " "})
        self.assertIn("Escriba el nombre del recinto excavable", str(raised.exception))
        self.nothing_left(files, done)
        reports: list[str] = []
        fake = operator_self(self.cls, name=NAME, surface="none", confirm=False, in_steps=False,
                             provenance_dialog=False,
                             report=lambda kind, text: reports.append(text))
        self.assertEqual(self.cls.execute(fake, bpy.context), {"CANCELLED"})  # sin superficies
        self.assertEqual(reports, ["Elija la superficie de partida del recinto excavable"])
        self.nothing_left(files, done)
        with self.assertRaises(RuntimeError) as raised:
            self.create()
        self.assertIn("No hay un cálculo abierto", str(raised.exception))

    def test_e_the_boundary_in_the_view_and_its_card(self) -> None:
        """RF-014-01 (M1), ADR-0005: «Cargar en la vista» del recinto da un objeto ``DESIGN``
        «Recinto excavable … · V01 [VIGENTE]» con matriz identidad y un vértice en el centro de cada
        una de las 415 celdas del recinto (y de ninguna otra), a la cota de la ladera de su
        partida; no escribe nada en el proyecto. Seleccionado, la barra N «Diseño» enseña su ficha:
        su título, su superficie de partida y su cifra, sin las semillas ni la envolvente de una
        envolvente. El diálogo sigue proponiendo la ladera como terreno, no el recinto."""
        (uid,) = [row[0] for row in self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND "
                                              "status = 'current'", self.dataset)]
        loader = self.views.loader_for(self.dataset)
        self.assertEqual((loader.prefix, loader.kind, loader.label),
                         ("des_rcn_", KIND, "Excavation boundary"))
        files = self.names()
        operations = self.rows("SELECT count(*) FROM gb_operation")
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
        self.assertEqual((self.names(), self.rows("SELECT count(*) FROM gb_operation")),
                         (files, operations))
        (obj,) = [item for item in bpy.data.objects if item.geoblender.dataset_uid == uid]
        self.assertEqual(obj.geoblender.kind, KIND)
        self.assertTrue(obj.name.startswith("Recinto excavable "), obj.name)
        self.assertTrue(obj.name.endswith(" · V01 [VIGENTE]"), obj.name)
        self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))  # nunca el origen en location
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        world = self.mesh.mesh_vertices_world(obj.data, self.project.origin)
        grid = _module("gis.grid").project_grid(self.project.record.window, STEP_M)
        columns = (world[:, 0] - grid.west) / grid.dx - 0.5
        rows = (grid.north - world[:, 1]) / grid.dy - 0.5
        np.testing.assert_allclose(columns, np.rint(columns), atol=1e-6)  # centros de celda
        np.testing.assert_allclose(rows, np.rint(rows), atol=1e-6)
        cells = np.zeros((CELLS, CELLS), dtype=bool)
        cells[np.rint(rows).astype(int), np.rint(columns).astype(int)] = True
        self.assertTrue(np.array_equal(cells, hand_area()))
        heights = ground()[np.rint(rows).astype(int), np.rint(columns).astype(int)]
        np.testing.assert_allclose(world[:, 2], heights, atol=1e-4)

        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        self.assertEqual((self.view.item_uid, self.view.item_found), (uid, True))
        self.assertEqual(self.view.item_title, f"Recinto excavable · {NAME}")
        texts = [row.name for row in self.view.item]
        self.assertIn(f"Superficie de partida: «{self.ground}»", texts)
        self.assertNotIn("Semillas y dominios", texts)
        self.assertFalse(any(text.startswith("Envolvente") for text in texts), texts)
        self.assertTrue(any("[CAL]" in text and "Área del recinto" in text for text in texts),
                        texts)
        self.assertTrue(getattr(bpy.types, PANEL).poll(bpy.context))

        fake, context, _dialog = self.fake_dialog()
        self.assertEqual(self.cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        listed = [item[0] for item in self.panels.surface_items(None, None)]
        self.assertIn(self.dataset, listed)
        self.assertEqual(listed[0], self.dataset)  # el primero de la lista…
        self.assertEqual(fake.surface, self.ground)  # …pero se propone el terreno
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()

    def test_z_disabling_geoblender_removes_the_command_and_the_loader(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta (no
        queda ningún temporal) y quita la orden y el cargador del recinto."""
        state, _calls, _modal = self.calculate(name="Al apagar")
        self.assertEqual(state, {"FINISHED"})
        self.assertTrue(self.temporaries())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, LIMIT_CLASS, None))
        self.assertIsNone(self.views.loader_for(self.dataset))
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())


if __name__ == "__main__":
    unittest.main()
