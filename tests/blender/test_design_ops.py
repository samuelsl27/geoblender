# SPDX-License-Identifier: GPL-3.0-or-later
"""«Envolventes y escalonado…» en Blender (spec 013, T24 y T28; HU-013-3, HU-013-5, HU-013-6; RF-013-17,
RF-013-21, RF-013-31, RF-013-33, RF-013-34; plan 013 §5.3.3, §5.5, D-14, D-27, D-30; comprobación manual
M4 a M7).

La orden ``geoblender.des_compute_envelope`` (``bl.ops.des``): una sola ventana con la envolvente y,
si se pide, su escalonado (D-30). **Calcular** lanza el modal por pasos (``_StepsModal``, con el
avance «Calculando la envolvente… 40 % · Esc: cancelar») sobre ``design.steps`` hasta el resumen con
sus avisos, sin registrar nada (D-14); **Crear** (la misma orden con ``confirm=True``) lo registra en
una transacción y **Cancelar** o cerrar la ventana borra los temporales. Un proyecto por clase
(ventana de 60 × 60 m con celdas de 2 m, V01 y V02, un límite legal, un perímetro, una zona «Hoyo»,
dos sectores y una ladera llana a 100 m) y las pruebas, en el orden de sus letras sobre el mismo
estado:

- RF-013-33 (a): la orden es la real (con la puerta de la procedencia y los pasos con Esc), su diálogo
  ofrece las listas del proyecto y lo que dice la spec (semillas, dirección, métrica, pendiente,
  alcance, acotar a, escalonar y nombre), y el de la confirmación propone «Crear» (con el número de
  avisos si los hay).
- RF-013-05, RF-013-16 (b): con un sector con la búsqueda pendiente el cálculo se niega nombrando el
  sector y la orden de la 012, en los dos idiomas; con una pendiente fuera de rango, unas semillas sin
  zona, un perfil que falta o una puerta cerrada, también, nombrando el campo y el valor; ninguno deja
  una operación, un dato ni un temporal de la 013.
- RF-013-33, D-14 (c, d): Esc a mitad de calcular, con el temporal ya escrito, y la cancelación del
  modal por Blender no dejan nada, ni el escalonado pendiente.
- RF-013-17, RF-013-31, D-14 (e): Calcular una envolvente ascendente desde una cota fija da el
  resumen sin registrar nada (con su temporal); Crear la registra (operación, dato, cifras CALCULADO
  finitas, Ctrl+Z apuntado) y sigue con el escalonado en corte, con su propio resumen; Crear lo
  registra (superficie de diseño, bermas, tabla e informe); cada llamada del modal dura menos de
  0,2 s.
- RF-013-21, RF-013-23 (f): un relleno con pendiente por sectores y un perfil por sector se calcula
  y se registra con los perfiles entre sus ajustes.
- RF-013-16 (g): un escalonado que se rechaza tras crear la envolvente dice qué falló y que la
  envolvente ya está creada.
- D-14 (h): Cancelar o cerrar la ventana de la confirmación borra los temporales y el escalonado
  pendiente; un cálculo nuevo borra el anterior al empezar; cambiar de proyecto o desactivar Geoblender
  también; Crear sin cálculo abierto se niega.
- Principio 10 (i): el avance, el resumen y los avisos, en los dos idiomas.
- RF-013-34 (j, T28; M7): «Exportar rejilla a GeoTIFF…» (``geoblender.des_export_design_grid``, la
  interna del botón de la barra N «Diseño») escribe por pasos las tres rejillas de V01 como GeoTIFF
  entregable sin escribir nada en el proyecto; sustituir, Esc, solo lectura, rechazos, el diálogo y la
  rejilla del objeto activo.
- RF-013-31, RF-013-17 (k, T28; M7): «Recalcular lo obsoleto» rehace por la cola de ``des`` lo que
  dejó obsoleto un parámetro, sin pedir confirmación y con su avance.
- RF-013-33, D-14 (l, T37): cerrar el proyecto a mitad de un cálculo lo para sin dejar nada y lo dice
  con su propio texto («Se cerró el proyecto mientras se calculaba «Cierre»…»), no el de la cubicación.
- Principio 8 (z): desactivar Geoblender quita la orden y descarta el cálculo abierto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import os
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

OPEN = "geoblender.des_compute_envelope"
EXPORT = "geoblender.des_export_design_grid"
RECOMPUTE = "geoblender.core_recompute_stale"
PANEL = "GEOBLENDER_PT_des_design"
VIEW_PROPERTY = "geoblender_design"
ENVELOPE_TYPE = "des.envelope"
STEPPED_TYPE = "des.stepped_design"
REASON = "Prueba de las envolventes y el escalonado"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
CLOSED_AT = "2026-11-02T10:00:00Z"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
GROUND_M = 100.0
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
PIT = (22.0, 22.0, 34.0, 34.0)
SECTORS = {"Sector 1": (2.0, 2.0, 30.0, 56.0), "Sector 2": (30.0, 2.0, 56.0, 56.0)}
EXPL = "EXPL_5_60_3"
REST = "REST_5_35_3"
EXPL_VALUES = {"height": "5", "face": "60", "berm": "3", "anchor": "100"}
REST_VALUES = {"height": "5", "face": "35", "berm": "3", "anchor": "100"}
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 20_000


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


def json_name(settings: str) -> str:
    """El nombre de la envolvente o del escalonado de unos ajustes guardados (JSON)."""
    return str(json.loads(settings)["name"])


class ComputeEnvelopeTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, dos sectores
    (el segundo, con la búsqueda pendiente al empezar), una ladera llana y dos perfiles de banco para
    toda la clase (las pruebas, en el orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d24-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.masks_store = _module("gis.masks.store")
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
            cls.v01, _revision = store.create_version(conn, cls.project, feature="diseno",
                                                      title="Diseño", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.codes = cls.declare()
        cls.declare_sectors()
        cls.close_search("sector_1", 1)
        cls.ground = cls.write_grid("Ladera", np.full((int(SIZE_M / STEP_M),) * 2, GROUND_M))
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        for name, values in ((EXPL, EXPL_VALUES), (REST, REST_VALUES)):
            assert bpy.ops.geoblender.des_save_bench_profile(
                name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
                scope="PROJECT", **values) == {"FINISHED"}

    @classmethod
    def declare(cls) -> dict[str, str]:
        """El límite legal, el perímetro de actuación y una zona «Hoyo» que se puede excavar (como
        las dejará la orden de la 012); el código de cada una por su tipo."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 2), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.AVOID, "Hoyo", PIT)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        edited = cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                            srs_id=cls.project.record.crs_epsg)
        return {item.ctype.value: str(item.code) for item in edited.constraints}

    @classmethod
    def declare_sectors(cls) -> None:
        """Los dos sectores de búsqueda (``core_sector``), como los dejará «Declarar de nuevo desde
        una capa…»."""
        sectors = tuple(
            cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name, (ring(box),))
            for index, (name, box) in enumerate(SECTORS.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str, minutes: int) -> None:
        """Cierra la búsqueda de intocables de un sector (con su huella), como hará la orden de la
        012: queda sin la marca de pendiente."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(f"search{minutes}{'0' * 25}", handle.uid, code,
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON, CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

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
        return self.commands.registered_class(OPEN)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operations(self, op_type: str, status: str | None = None) -> list[tuple[Any, ...]]:
        sql = "SELECT uid, status, superseded_by FROM gb_operation WHERE op_type = ?"
        if status is None:
            return self.rows(sql + " ORDER BY fid", op_type)
        return self.rows(sql + " AND status = ? ORDER BY fid", op_type, status)

    def datasets(self) -> list[str]:
        """Los datos vivos de la 013 (envolventes, superficies, bermas, tablas e informes), sin la
        tabla de los perfiles de banco, que es del proyecto."""
        return [name for (name,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name LIKE 'des!_%' ESCAPE '!' AND status = "
            "'current' AND name <> 'des_bench_profile' ORDER BY name")]

    def names(self) -> list[str]:
        """Todos los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".gpkg-journal")

    def temporaries(self) -> list[str]:
        """Los temporales que esperan junto a su destino (``*.tmp-*``)."""
        return [name for name in self.names() if ".tmp" in name]

    def figures(self, op_type: str) -> dict[str, float]:
        """Las cifras vigentes de la operación hecha de ``op_type`` (clave → valor)."""
        (uid,) = [row[0] for row in self.operations(op_type, "done")][-1:]
        return {key: value for key, value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def figures_of(self, op_uid: str) -> dict[str, float]:
        """Las cifras registradas por la operación ``op_uid`` (clave → valor)."""
        return {key: value for key, value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", op_uid)}

    def running(self, command: str = OPEN) -> Any:
        """El modal de ``command`` en marcha (el único con pasos): por defecto, el del cálculo."""
        cls = self.commands.registered_class(command)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{command} no está en marcha")
        return found[0]

    def drive(self, operator: Any, *, stop_after: int | None = None,
              until: Any = None) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba (o ``stop_after``
        eventos, o hasta que ``until()`` sea verdad): su final y lo que duró cada llamada (s de CPU
        del proceso, que no se contagia de la carga de otros programas del equipo; el plazo de pared
        lo mide la tarea T31)."""
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
        """Lo pedido en el diálogo: un hoyo ascendente desde los 90 m de su zona, con pendiente
        constante de 45° y sin escalonar."""
        return {"name": "Hoyo", "seeds_from": "FIXED", "zone": f"constraint:{self.codes['avoid']}",
                "elevation": "90", "direction": "UP", "metric": "CHAMFER5",
                "slope_mode": "CONSTANT", "slope": "45", "in_steps": True, **values}

    def start(self, **values: Any) -> Any:
        """Lanza la orden desde la interfaz (por pasos) y devuelve el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT",
                                                                     **self.form(**values)),
                             {"RUNNING_MODAL"})
        return self.running()

    def calculate(self, **values: Any) -> tuple[set[str], list[float], Any]:
        """Calcula por pasos hasta el final (la confirmación, sustituida: sin ventana, el temporizador
        no corre): el final del modal, lo que duró cada llamada y el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT",
                                                                     **self.form(**values)),
                             {"RUNNING_MODAL"})
            modal = self.running()
            state, calls = self.drive(modal)
        self.assertEqual(ask.call_count, 1 if state == {"FINISHED"} else 0)
        return state, calls, modal

    def create(self, **values: Any) -> set[str]:
        """«Crear»: la misma orden con ``confirm=True`` (con el escalonado encadenado, el modal)."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            return bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT", confirm=True,
                                                           in_steps=True, **values)

    def sector_row(self, code: str) -> Any:
        return next(item for item in self.view.sectors if item.code == code)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_the_dialog_and_the_confirmation(self) -> None:
        """RF-013-33, D-30 (plan §5.3.3, §5.5): «Envolventes y escalonado…» es una orden real con la
        puerta de la procedencia y los pasos con Esc, de los dos tipos de la 013; su diálogo ofrece las
        superficies, las zonas y las capas del proyecto, los perfiles y los sectores, y dibuja las
        secciones de la spec; el de la confirmación propone «Crear» (y, con avisos, los cuenta)."""
        cls = self.cls
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (ENVELOPE_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        cat = self.commands.catalog()
        self.assertEqual(cat.commands[OPEN].label_es, "Envolventes y escalonado…")
        self.assertTrue(cat.commands[OPEN].background)

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        values: dict[str, Any] = {
            "name": "", "seeds_from": "SURFACE", "surface": "", "zone": "", "elevation": "",
            "direction": "DOWN", "metric": "CHAMFER5", "slope_mode": "CONSTANT", "slope": "",
            "mesh": "", "reach": "", "bound": "ALL", "bound_layer": "none", "stepped": False,
            "sense": "CUT", "start": "", "base_profile": "", "anchor": "none", "confirm": False,
            "in_steps": False, "properties": SimpleNamespace(is_property_set=lambda name: False)}
        fake = operator_self(cls, report=lambda kind, text: None, **values)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Envolventes y escalonado…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual(sorted(item.name for item in self.view.profiles), [EXPL, REST])
        self.assertEqual([item.code for item in self.view.sectors], ["sector_1", "sector_2"])
        self.assertTrue(fake.name.strip())  # un nombre propuesto
        self.assertFalse(any(item.use for item in self.view.sectors))
        self.assertEqual(fake.start, self.ground)  # la ladera, propuesta como superficie de partida
        zones = [item[0] for item in self.panels.zone_items(None, None)]
        self.assertEqual(zones[:2], ["none", "domain"])
        self.assertIn(f"constraint:{self.codes['avoid']}", zones)
        self.assertIn("sector:sector_2", zones)
        self.assertEqual([item[0] for item in self.panels.surface_items(None, None)],
                         [self.ground])
        self.assertEqual([item[0] for item in self.panels.anchor_items(None, None)],
                         ["none", self.ground])

        shown = draw(cls, bpy.context, **values).texts()
        for heading in ("Nombre", "Semillas", "Dirección de la envolvente", "Métrica", "Pendiente",
                        "Alcance", "Acotar a", "Escalonar"):
            self.assertIn(heading, shown)
        stepped = draw(cls, bpy.context, **{**values, "stepped": True, "slope_mode": "SECTORS",
                                            "bound": "SECTORS"})
        for heading in ("Sentido", "Superficie de partida", "Ancla", "Perfil base", "Sectores"):
            self.assertIn(heading, stepped.texts())
        # El perfil base y el de cada sector se buscan entre los perfiles; las casillas de acotar.
        self.assertEqual(len(stepped.of_kind("prop_search")), 3)
        self.assertEqual(len([item for item in stepped.of_kind("prop") if item.target == "use"]), 2)

        # La confirmación: sin cálculo abierto se niega; con él, «Crear» o «Crear con N avisos».
        fake.confirm = True
        reports: list[tuple[Any, str]] = []
        fake.report = lambda kind, text: reports.append((kind, text))
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports[-1][1], "No hay un cálculo abierto: calcule antes")
        for warnings, wanted in ((0, "Crear"), (1, "Crear con 1 aviso"), (3, "Crear con 3 avisos")):
            held = SimpleNamespace(open=True, warnings=lambda warnings=warnings: ("aviso",) * warnings,
                                   op_type=ENVELOPE_TYPE, discard=lambda: None)
            with mock.patch.object(self.des_ops, "calculation", return_value=held):
                dialog.reset_mock()
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
            self.assertEqual(dialog.call_args.kwargs["confirm_text"], wanted)

    def test_b_a_pending_sector_and_a_wrong_request_refuse_and_leave_nothing(self) -> None:
        """RF-013-05, RF-013-16 (M6): con el sector 2 sin búsqueda de intocables el cálculo se niega
        nombrando el sector y la orden de la 012 («Buscar elementos intocables por sector…»), en los
        dos idiomas; una pendiente de 95°, un campo sin escribir y unas semillas sin zona lo hacen
        nombrando el campo y el valor. Ninguno deja una operación, un dato, una cifra ni un temporal
        de la 013 (lo único que sobrevive es la compilación de las máscaras, que es suya)."""
        before = self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'des.%'")

        def nothing_left() -> None:
            self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE "
                                       "'des.%'"), before)
            self.assertEqual(self.datasets(), [])
            self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
                             [(0,)])
            self.assertEqual([name for name in self.names() if "des_" in name], [])
            self.assertEqual(self.temporaries(), [])
            self.assertIsNone(self.des_ops.calculation())

        for language, order in (("es", "Buscar elementos intocables por sector…"),
                                ("en", "Find untouchable elements by sector…")):
            with self.subTest(idioma=language):
                self.i18n.set_language(language)
                modal = self.start()
                state, _calls = self.drive(modal)
                self.assertEqual(state, {"CANCELLED"})
                texts = " ".join(modal.report_log)
                self.assertIn("Sector 2", texts)
                self.assertIn(order, texts)
                nothing_left()
        self.i18n.set_language("es")
        self.close_search("sector_2", 2)
        for label, change, wanted in (
                ("pendiente", {"slope": "95"}, ("95", "pendiente")),
                ("sin semillas", {"zone": "none"}, ("elevation_m", "zone"))):
            with self.subTest(petición=label):
                modal = self.start(**change)
                state, _calls = self.drive(modal)
                self.assertEqual(state, {"CANCELLED"})
                shown = " ".join(modal.report_log).lower()
                self.assertTrue(any(word in shown for word in wanted), shown)
                nothing_left()
        for label, change, word in (("no es un número", {"slope": "muy empinada"}, "muy empinada"),
                                    ("sin nombre", {"name": ""}, "nombre"),
                                    ("sin perfil base", {"stepped": True, "start": self.ground},
                                     "perfil base"),
                                    ("perfil que no existe", {"stepped": True, "start": self.ground,
                                                              "base_profile": "NO_EXISTE"},
                                     "NO_EXISTE")):
            with self.subTest(petición=label):
                with self.assertRaises(RuntimeError) as raised:
                    bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT", **self.form(**change))
                self.assertIn(word, str(raised.exception))
                nothing_left()
        with mock.patch.object(self.des_ops, "ensure_ready", return_value=None) as gate:
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT", **self.form()),
                             {"CANCELLED"})  # la puerta de la procedencia no deja pasar
        gate.assert_called_once()
        nothing_left()

    def test_c_esc_midway_leaves_nothing(self) -> None:
        """RF-013-33, D-14 (M6): Esc a mitad de calcular, también con el temporal ya escrito, no deja
        nada: ni operaciones en curso, ni datos, ni cifras, ni ficheros nuevos, ni cálculo abierto,
        y el avance y el texto de la barra de estado quedan como estaban; el escalonado pendiente
        (la segunda fase) tampoco sigue."""
        cls = self.cls
        state, _calls, _modal = self.calculate(name="Preparación")  # las máscaras, al día
        self.assertEqual(state, {"FINISHED"})
        self.des_ops.discard_calculation()
        files = self.names()
        with mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):
            for label, events in (("al empezar", 2), ("con el temporal escrito", None)):
                with self.subTest(momento=label):
                    modal = self.start(stepped=True, base_profile=EXPL, sense="CUT",
                                       start=self.ground)
                    if events is None:
                        self.drive(modal, until=lambda: bool(self.temporaries()))
                        self.assertTrue(self.temporaries(), "no llegó a escribir el temporal")
                    else:
                        self.drive(modal, stop_after=events)
                    self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                    self.assertIsNone(modal._steps)
                    self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                    self.assertEqual(self.operations(ENVELOPE_TYPE, "running"), [])
                    self.assertEqual(self.operations(ENVELOPE_TYPE, "done"), [])
                    self.assertEqual(self.operations(STEPPED_TYPE), [])
                    self.assertEqual(self.datasets(), [])
                    self.assertEqual(self.rows("SELECT count(*) FROM gb_figure WHERE key LIKE "
                                               "'des.%'"), [(0,)])
                    self.assertEqual(self.names(), files)
                    self.assertIsNone(self.des_ops.calculation())
                    self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001 - el escalonado pendiente

    def test_d_blender_cancelling_a_running_modal_closes_its_steps(self) -> None:
        """RF-013-33, D-14: si Blender cancela el modal en curso (``cancel``, como Esc), sus pasos se
        cierran, el temporal se borra y el escalonado pendiente no sigue."""
        files = self.names()
        with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):
            modal = self.start(stepped=True, base_profile=EXPL, start=self.ground)
            self.drive(modal, until=lambda: bool(self.temporaries()))
            self.assertTrue(self.temporaries())
            self.assertEqual(len(self.des_ops._NEXT), 1)  # noqa: SLF001
            modal.cancel(bpy.context)
        self.assertIsNone(modal._steps)
        self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)
        self.assertEqual(self.operations(ENVELOPE_TYPE, "running"), [])

    def test_e_calculate_then_create_the_envelope_then_the_benching(self) -> None:
        """RF-013-17, RF-013-21, RF-013-31, D-14 (M4): una envolvente ascendente de 45° desde los 90 m
        de la zona «Hoyo» con su escalonado en corte (perfil EXPL_5_60_3): Calcular da el resumen
        con sus cifras y deja el temporal sin registrar nada; Crear registra la envolvente (una
        operación hecha, su dato, sus seis cifras finitas) y sigue con el escalonado, con su propio
        resumen (desmonte, inclinación, bermas); Crear registra la superficie de diseño, la rejilla y
        la tabla de bermas y el informe, con el perfil entre sus ajustes. Cada llamada del modal
        dura menos de 0,2 s y el avance dice «Calculando la envolvente… 40 % · Esc: cancelar»."""
        state, calls, modal = self.calculate(stepped=True, base_profile=EXPL, sense="CUT",
                                             start=self.ground)
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)  # RNF-013-07
        self.assertEqual(modal._status_text(self.model.Progress("envelope", 2, 5, "…")),
                         "Calculando la envolvente… 40 % · Esc: cancelar")
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.version, held.open),
                         (ENVELOPE_TYPE, "Hoyo", "V01", True))
        self.assertEqual(self.operations(ENVELOPE_TYPE), [])  # sin registrar (D-14)
        self.assertEqual(self.datasets(), [])
        self.assertTrue(self.temporaries())
        view = self.view
        self.assertEqual(view.summary_title, "Envolvente «Hoyo» en V01")
        lines = [(item.name, item.alert) for item in view.summary]
        self.assertRegex(lines[0][0], r"^Envolvente «Hoyo»: .+ celdas \(.+ m²\)$")
        self.assertTrue(any(text.startswith("Cotas 90,0 a ") for text, _alert in lines), lines)

        # Crear: la envolvente se registra y sigue el escalonado (otra fase del modal).
        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.create(), {"RUNNING_MODAL"})
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no deshace la base: apuntada
        self.assertEqual(journal.entries[-1].label, ENVELOPE_TYPE)
        (made,) = self.operations(ENVELOPE_TYPE, "done")
        self.assertEqual(self.datasets(), ["des_env_hoyo"])
        self.assertEqual(self.temporaries(), [])
        figures = self.figures(ENVELOPE_TYPE)
        self.assertEqual(sorted(figures), ["des.env_area_m2", "des.env_cells", "des.env_max_m",
                                           "des.env_min_m"])  # sin desmonte: semillas de cota fija
        self.assertTrue(all(np.isfinite(value) for value in figures.values()))
        self.assertGreater(figures["des.env_cells"], 36.0)
        self.assertAlmostEqual(figures["des.env_min_m"], 90.0, places=9)
        self.assertIsNone(made[2])
        self.assertIsNone(self.des_ops.calculation())  # la envolvente ya está creada

        modal = self.running()
        self.assertEqual(modal._status_text(self.model.Progress("benching", 2, 5, "…")),
                         "Calculando el escalonado… 40 % · Esc: cancelar")
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask:
            state, calls = self.drive(modal)
        ask.assert_called_once()
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.2)
        held = self.des_ops.calculation()
        self.assertEqual((held.op_type, held.name, held.open), (STEPPED_TYPE, "Hoyo", True))
        self.assertEqual(self.operations(STEPPED_TYPE), [])
        self.assertEqual(self.datasets(), ["des_env_hoyo"])
        self.assertEqual(view.summary_title, "Escalonado «Hoyo» en V01")
        lines = [item.name for item in view.summary]
        self.assertTrue(lines[0].startswith("Escalonado «Hoyo»: desmonte "), lines)
        self.assertTrue(any(text.endswith(" m") and "bermas, cotas reales" in text
                            for text in lines), lines)

        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(journal.entries[-1].label, STEPPED_TYPE)
        self.assertEqual(len(self.operations(STEPPED_TYPE, "done")), 1)
        self.assertEqual(self.datasets(), ["des_bmt_hoyo", "des_brm_hoyo", "des_env_hoyo",
                                           "des_rpt_hoyo", "des_srf_hoyo"])
        self.assertEqual(self.temporaries(), [])
        stepped = self.figures(STEPPED_TYPE)
        self.assertGreater(stepped["des.cut_m3"], 0.0)
        self.assertTrue(all(np.isfinite(value) for value in stepped.values()))
        settings = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND status = "
                             "'done'", STEPPED_TYPE)[0][0]
        self.assertIn("expl_5_60_3", settings)  # el perfil base, entre los ajustes (RF-013-21)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001
        # Un nombre repetido en la versión se rechaza antes de calcular y no cambia nada.
        modal = self.start()
        self.assertEqual(self.drive(modal)[0], {"CANCELLED"})
        self.assertIn("Hoyo", " ".join(modal.report_log))
        self.assertEqual(len(self.operations(ENVELOPE_TYPE, "done")), 1)

    def test_f_a_fill_by_sectors_with_a_profile_for_each_sector(self) -> None:
        """RF-013-21, RF-013-23, RF-013-13 (M5): un montículo descendente de 45° desde los 108 m de la
        zona «Hoyo», con la pendiente por sectores y un perfil para cada sector (REST_5_35_3 en el
        sector 2, EXPL_5_60_3 como base), se escalona en relleno; los perfiles se anotan en la
        vista de los sectores y quedan entre los ajustes de las dos operaciones."""
        shown = self.view
        self.assertTrue(len(shown.sectors))  # leídos por el diálogo de la prueba a
        self.sector_row("sector_1").profile_pick = EXPL
        self.sector_row("sector_2").profile_pick = REST
        state, _calls, _modal = self.calculate(
            name="Monticulo", elevation="108", direction="DOWN", slope_mode="SECTORS", slope="",
            stepped=True, base_profile=EXPL, sense="FILL", start=self.ground)
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual([item.profile_name for item in shown.sectors], [EXPL, REST])
        self.assertEqual(self.create(), {"RUNNING_MODAL"})
        state, _calls = self.drive(self.running())
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.des_ops.calculation().op_type, STEPPED_TYPE)
        self.assertEqual(self.create(), {"FINISHED"})
        for op_type in (ENVELOPE_TYPE, STEPPED_TYPE):
            (settings,) = self.rows("SELECT settings FROM gb_operation WHERE op_type = ? AND "
                                    "status = 'done' AND settings LIKE '%Monticulo%'", op_type)
            self.assertIn("rest_5_35_3", settings[0])
            self.assertIn("expl_5_60_3", settings[0])
        stepped = self.figures(STEPPED_TYPE)
        self.assertGreater(stepped["des.fill_m3"], 0.0)
        self.assertEqual(stepped["des.cut_m3"], 0.0)
        self.assertEqual(self.temporaries(), [])

    def test_g_a_benching_that_fails_says_the_envelope_is_already_created(self) -> None:
        """RF-013-16, D-14: si el escalonado se rechaza tras crear la envolvente (una rejilla de
        anclas con huecos dentro del dominio), dice qué falló y que la envolvente ya está creada;
        no queda ni un temporal ni el escalonado pendiente."""
        holes = np.full((int(SIZE_M / STEP_M),) * 2, GROUND_M)
        holes[11:17, 11:17] = np.nan  # el hoyo
        anchors = self.write_grid("Anclas", holes)
        self.panels.refresh_choices(self.project)  # la rejilla nueva, en las listas
        state, _calls, _modal = self.calculate(name="Anclada", stepped=True, base_profile=EXPL,
                                               start=self.ground, anchor=anchors)
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.create(), {"RUNNING_MODAL"})
        modal = self.running()
        state, _calls = self.drive(modal)
        self.assertEqual(state, {"CANCELLED"})
        shown = " ".join(modal.report_log)
        self.assertIn("rejilla de anclas", shown)
        self.assertIn("La envolvente «Anclada» ya está creada: solo falta calcular su escalonado",
                      shown)
        self.assertEqual(len(self.operations(ENVELOPE_TYPE, "done")), 3)
        self.assertEqual([row for row in self.operations(STEPPED_TYPE, "done")
                          if "anclada" in row[0]], [])
        self.assertIn("des_env_anclada", self.datasets())
        self.assertNotIn("des_srf_anclada", self.datasets())
        self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.temporaries(), [])

    def test_h_cancel_or_close_the_confirmation_discards_the_temporaries(self) -> None:
        """D-14 (M6): con un cálculo hecho, «Cancelar» o cerrar la ventana de la confirmación
        (``cancel``) borra los temporales y no registra nada; la ventana del cálculo (el diálogo del
        formulario) no descarta lo ya abierto; Crear sin cálculo abierto se niega; cambiar de
        proyecto lo descarta; cerrar el generador de un cálculo con el temporal escrito, también."""
        files = self.names()
        ops = self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'des.%'")
        state, _calls, _modal = self.calculate(name="Descartada", stepped=True, base_profile=EXPL,
                                                start=self.ground)
        self.assertEqual(state, {"FINISHED"})
        self.assertTrue(self.temporaries())
        self.assertEqual(len(self.des_ops._NEXT), 1)  # noqa: SLF001 - el escalonado que espera
        form = operator_self(self.cls, confirm=False, in_steps=False)
        self.cls.cancel(form, bpy.context)  # el diálogo del formulario: lo abierto sigue
        self.assertIsNotNone(self.des_ops.calculation())
        confirmation = operator_self(self.cls, confirm=True, in_steps=False)
        self.cls.cancel(confirmation, bpy.context)  # «Cancelar» o cerrar la ventana
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001 - ni el escalonado que esperaba
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'des.%'"),
                         ops)
        with self.assertRaises(RuntimeError) as raised:
            self.create()
        self.assertIn("No hay un cálculo abierto", str(raised.exception))

        self.calculate(name="Descartada")  # un cálculo nuevo borra el anterior al empezar
        first = self.des_ops.calculation()
        modal = self.start(name="Otra")
        self.assertFalse(first.open)  # antes de su primer paso
        self.assertEqual(self.temporaries(), [])
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(self.drive(modal)[0], {"FINISHED"})
        self.assertEqual(len(self.temporaries()), 1)
        self.des_ops.project_changed(None)  # cambiar de proyecto
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.names(), files)

    def test_i_the_summary_and_the_progress_in_both_languages(self) -> None:
        """Principio 10, RF-013-31: el avance, el resumen del cálculo y su título salen en inglés con
        el idioma de Geoblender en inglés (los avisos que da el dominio, también)."""
        self.i18n.set_language("en")
        state, _calls, modal = self.calculate(name="Pit")
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(self.view.summary_title, "Envelope «Pit» in V01")
        lines = [item.name for item in self.view.summary]
        self.assertTrue(lines[0].startswith("Envelope «Pit»: "), lines)
        self.assertRegex(lines[0], r"^Envelope «Pit»: .+ cells \(.+ m²\)$")
        self.assertTrue(any(text.startswith("Elevations ") for text in lines), lines)
        self.assertEqual(modal._status_text(self.model.Progress("envelope", 2, 5, "…")),
                         "Computing the envelope… 40 % · Esc: cancel")
        self.des_ops.discard_calculation()
        self.assertEqual(self.temporaries(), [])

        # El resumen de una envolvente con superficie de partida lleva el desmonte y el terraplén
        # (las cifras que se registrarían), en los dos idiomas; los avisos van en alerta.
        figure = _module("core.provenance.figures").FigureSpec
        notice = _module("design.preview").Notice(
            "des.seeds_without_data", {"cells": 3, "area": 12.0, "surface": "Ladera"})
        opened = SimpleNamespace(
            op_type=ENVELOPE_TYPE, name="Corta", notices=(notice,),
            figures=(figure("des.env_cells", 4210.0, "-"), figure("des.env_area_m2", 4210.0, "m2"),
                     figure("des.env_min_m", 188.2, "m"), figure("des.env_max_m", 231.5, "m"),
                     figure("des.env_cut_m3", 412380.0, "m3"),
                     figure("des.env_fill_m3", 0.0, "m3")))
        for language, heads in (("en", ("Envelope «Corta»: {c} cells ({c} m²)", "Elevations {l} to {h} m",
                                        "Against the start surface: cut {v} m³ · fill 0 m³")),
                                ("es", ("Envolvente «Corta»: {c} celdas ({c} m²)", "Cotas {l} a {h} m",
                                        "Frente a la superficie de partida: desmonte {v} m³ · "
                                        "relleno 0 m³"))):
            with self.subTest(idioma=language):
                self.i18n.set_language(language)
                number = self.i18n.format_number
                wanted = [heads[0].format(c=number(4210, 0)),
                          heads[1].format(l=number(188.2, 1), h=number(231.5, 1)),
                          heads[2].format(v=number(412380, 0))]
                found = self.panels.summary_lines(opened)
                self.assertEqual([text for text, _alert in found[:3]], wanted)
                self.assertTrue(found[3][1])  # el aviso, en alerta
                self.assertEqual([alert for _text, alert in found[:3]], [False] * 3)

    def grid_uid(self, name: str) -> str:
        """El uid del dato vivo ``name`` de V01."""
        ((uid,),) = self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current' "
                              "AND version_uid = ?", name, self.v01.uid)
        return str(uid)

    def counts(self) -> list[tuple[Any, ...]]:
        """Las operaciones, los datos y los eventos del proyecto (exportar no escribe en él)."""
        return [self.rows(f"SELECT count(*) FROM {table}")[0]
                for table in ("gb_operation", "gb_dataset", "gb_event")]

    def test_j_export_a_grid_to_geotiff_by_steps_without_writing_in_the_project(self) -> None:
        """RF-013-34, RF-006-24 (D-29 de la 011, RNF-013-07; M7): «Exportar rejilla a GeoTIFF…» (una
        orden interna, no una operación) escribe por pasos la envolvente, la superficie de diseño y
        la rejilla de cotas de berma de V01 como GeoTIFF entregable —las cotas registradas en
        float32, el «sin dato» −9999 declarado y el CRS del proyecto—, con el avance y Esc (ninguna
        llamada de más de 0,2 s), sin cambiar ni una operación, un dato, un evento o un fichero del
        proyecto; desde un guion se rechaza sobre un fichero que ya existe si no se pide sustituirlo;
        Esc a mitad no deja el GeoTIFF ni su temporal; con el proyecto en solo lectura exporta fuera
        de él; lo que no es una rejilla viva del diseño, un destino que no es un GeoTIFF y uno dentro
        del proyecto se rechazan nombrando el valor. El diálogo propone ``exports/<dato>_V01.tif``
        y la barra N «Diseño» ofrece el botón con la rejilla del objeto activo."""
        cls = self.commands.registered_class(EXPORT)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertEqual(cls.bl_options, {"REGISTER"})
        self.assertIsNone(getattr(cls, "provenance_op_type", None))  # no es una operación
        command = self.commands.catalog().commands[EXPORT]
        self.assertEqual((command.label, command.label_es),
                         ("Export grid to GeoTIFF…", "Exportar rejilla a GeoTIFF…"))
        self.assertEqual(command.entry, "013")
        self.assertTrue(cls.poll(bpy.context))
        out = Path(tempfile.mkdtemp(prefix="gb-d28-"))
        self.addCleanup(remove_tree, out)
        reader = _module("gis.geotiff.reader")
        before, files = self.counts(), self.names()

        grids = {"des_env_hoyo": "Envolvente", "des_srf_hoyo": "Superficie de diseño",
                 "des_brm_hoyo": "Cota real de las bermas"}
        for name in grids:
            with self.subTest(grid=name):
                target = out / f"{name}.tif"
                self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                    "EXEC_DEFAULT", source=self.grid_uid(name), filepath=str(target),
                    in_steps=True), {"RUNNING_MODAL"})
                modal = self.running(EXPORT)
                self.assertEqual(modal._status_text(self.model.Progress("export", 400, 1000, "…")),
                                 f"Exportando «{name}.tif»… 40 % · Esc: cancelar")
                state, calls = self.drive(modal)
                self.assertEqual(state, {"FINISHED"})
                self.assertLess(max(calls), 0.2)  # RNF-013-07
                self.assertGreater(len(modal.progress_log), 2)
                self.assertEqual(modal.progress_log[-1][2:4], (1000, 1000))
                self.assertEqual(modal.report_log, [f"Rejilla del diseño exportada a «{name}.tif»"])
                record = self.rows("SELECT locator FROM gb_dataset WHERE uid = ?",
                                   self.grid_uid(name))[0][0]
                stored = reader.read_geotiff(Path(self.project.root, *record.split("/")),
                                             max_cells=10 ** 7)
                found = reader.read_geotiff(target, max_cells=10 ** 7)
                self.assertEqual(found.grid, stored.grid)
                self.assertEqual((found.declared_crs.epsg, found.source_dtype, found.nodata_value),
                                 (self.project.record.crs_epsg, "float32", -9999.0))
                self.assertTrue(np.isfinite(found.values).any(), name)
                np.testing.assert_array_equal(  # 0 m: lo registrado en float32 (NaN con NaN)
                    found.values, stored.values.astype(np.float32).astype(np.float64))
        self.assertEqual(sorted(path.name for path in out.iterdir()),
                         sorted(f"{name}.tif" for name in grids))
        self.assertEqual((self.counts(), self.names()), (before, files))  # nada escrito en el proyecto

        # Un fichero que ya existe: desde un guion se rechaza; con «overwrite», se sustituye igual.
        uid, target = self.grid_uid("des_srf_hoyo"), out / "des_srf_hoyo.tif"
        kept = target.read_bytes()
        with self.assertRaises(RuntimeError) as raised:
            bpy.ops.geoblender.des_export_design_grid("EXEC_DEFAULT", source=uid,
                                                      filepath=str(target))
        self.assertIn("Ya existe «des_srf_hoyo.tif»", str(raised.exception))
        self.assertEqual(target.read_bytes(), kept)
        self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
            "EXEC_DEFAULT", source=uid, filepath=str(target), overwrite=True), {"FINISHED"})
        self.assertEqual(target.read_bytes(), kept)
        # Con ventana, lo mismo pregunta antes de sustituir (la confirmación es la misma orden).
        with mock.patch.object(self.des_ops, "_confirm_later") as later:
            self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                "EXEC_DEFAULT", source=uid, filepath=str(target), in_steps=True), {"CANCELLED"})
        later.assert_called_once_with({"source": uid, "filepath": str(target)},
                                      idname=EXPORT)

        # Esc a mitad de la escritura: ni el GeoTIFF ni su temporal.
        half = out / "a_medias.tif"
        with mock.patch.object(_module("gis.geotiff.writer"), "TILE_SIZE", 16), \
                mock.patch.object(cls, "STEP_BUDGET_S", 1e-9):  # un paso por llamada
            self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                "EXEC_DEFAULT", source=uid, filepath=str(half), in_steps=True),
                {"RUNNING_MODAL"})
            modal = self.running(EXPORT)
            self.assertEqual(self.drive(modal, stop_after=3)[0], {"RUNNING_MODAL"})
            done = [entry[2] for entry in modal.progress_log]  # el avance crece, sin llegar al final
            self.assertEqual((len(done), done == sorted(done), 0 < done[-1] < 1000),
                             (3, True, True), done)
            self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIsNone(modal._steps)
        self.assertIn("Exportación cancelada: no se ha escrito nada", modal.report_log)
        self.assertFalse(half.exists())
        self.assertEqual([path.name for path in out.iterdir() if ".tmp" in path.name], [])

        # Los rechazos: nombran el valor y no escriben nada.
        for label, values, word in (
                ("una tabla", {"source": self.grid_uid("des_rpt_hoyo"), "filepath": "x.tif"},
                 "no es una rejilla viva del diseño"),
                ("la superficie de partida", {"source": self.ground, "filepath": "x.tif"},
                 "no es una rejilla viva del diseño"),
                ("sin rejilla", {"source": "", "filepath": str(out / "x.tif")},
                 "Elija la rejilla del diseño"),
                ("sin fichero", {"source": uid, "filepath": ""}, "Elija el fichero"),
                ("no es un GeoTIFF", {"source": uid, "filepath": str(out / "x.png")}, "x.png"),
                ("dentro del proyecto", {"source": uid, "filepath":
                                         str(Path(self.project.root) / "x.tif")}, "x.tif")):
            with self.subTest(rechazo=label):
                with self.assertRaises(RuntimeError) as raised:
                    bpy.ops.geoblender.des_export_design_grid("EXEC_DEFAULT", **values)
                self.assertIn(word, str(raised.exception))
        with mock.patch.dict(os.environ, {"GEOBLENDER_READ_ONLY_DIRS": str(out)}):  # RF-008-15
            with self.assertRaises(RuntimeError) as raised:
                bpy.ops.geoblender.des_export_design_grid(
                    "EXEC_DEFAULT", source=uid, filepath=str(out / "protegida.tif"))
        self.assertIn("solo lectura", str(raised.exception))
        self.assertEqual((self.counts(), self.names()), (before, files))
        self.assertEqual(sorted(path.name for path in out.iterdir()),
                         sorted(f"{name}.tif" for name in grids))
        with mock.patch.object(self.session.SESSION, "unavailable", return_value="Abra un proyecto"):
            self.assertFalse(cls.poll(bpy.context))  # sin proyecto, no está disponible

        # Con el proyecto en solo lectura exporta fuera de él, y dentro no.
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertTrue(cls.poll(bpy.context))
            self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                "EXEC_DEFAULT", source=uid, filepath=str(out / "solo_lectura.tif")),
                {"FINISHED"})
            with self.assertRaises(RuntimeError) as raised:
                bpy.ops.geoblender.des_export_design_grid(
                    "EXEC_DEFAULT", source=uid,
                    filepath=str(Path(project.root, "exports", "x.tif")))
            self.assertIn("solo lectura", str(raised.exception))
        self.assertTrue((out / "solo_lectura.tif").is_file())

        # El diálogo propone el fichero y pide el destino; sin rejilla elegida, lo dice.
        reports: list[str] = []
        manager = SimpleNamespace(fileselect_add=mock.Mock(),
                                  invoke_confirm=mock.Mock(return_value={"RUNNING_MODAL"}))
        context = SimpleNamespace(window=window(), window_manager=manager, active_object=None)
        fake = operator_self(cls, report=lambda kind, text: reports.append(text), source=uid,
                             filepath="", overwrite=False, confirm=False, in_steps=False)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        manager.fileselect_add.assert_called_once_with(fake)
        self.assertEqual(Path(fake.filepath),
                         Path(self.project.root, "exports", "des_srf_hoyo_V01.tif"))
        self.assertTrue(fake.in_steps)
        fake = operator_self(cls, report=lambda kind, text: reports.append(text), source="",
                             filepath="", overwrite=False, confirm=False, in_steps=False)
        self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(reports, ["Elija la rejilla del diseño: selecciónela en la vista"])
        fake = operator_self(cls, report=lambda kind, text: reports.append(text), source=uid,
                             filepath=str(target), overwrite=False, confirm=True, in_steps=True)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertTrue(fake.overwrite)  # la confirmación de sustituir
        self.assertEqual(manager.invoke_confirm.call_args.kwargs["title"], "Sustituir el fichero")

        # El objeto activo de la vista da la rejilla (source vacío) y la barra N ofrece el botón.
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
        (shown,) = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        self.addCleanup(bpy.data.objects.remove, shown, do_unlink=True)
        view_panels = _module("bl.ui.view_panels")
        for other in bpy.data.objects:
            other.select_set(False)
        shown.select_set(True)
        bpy.context.view_layer.objects.active = shown
        self.addCleanup(setattr, bpy.context.view_layer.objects, "active", None)
        view_panels.on_active_changed()
        buttons = [item for item in draw(getattr(bpy.types, PANEL), bpy.context).items
                   if item.kind == "operator" and item.target == EXPORT]
        self.assertEqual([item.text for item in buttons], ["Exportar rejilla a GeoTIFF…"])
        self.assertTrue(buttons[0].enabled)
        self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
            "EXEC_DEFAULT", filepath=str(out / "activa.tif")), {"FINISHED"})
        self.assertEqual((out / "activa.tif").read_bytes(), kept)
        self.assertEqual((self.counts(), self.names()), (before, files))
        self.i18n.set_language("en")
        buttons = [item.text for item in draw(getattr(bpy.types, PANEL), bpy.context).items
                   if item.kind == "operator" and item.target == EXPORT]
        self.assertEqual(buttons, ["Export grid to GeoTIFF…"])

    def stale(self) -> dict[str, Any]:
        """Las operaciones obsoletas sin sustituir con sus causas (``deduce`` de la 008)."""
        graph = _module("core.provenance.graph")
        with self.project.read() as conn:
            return dict(graph.deduce(graph.load_graph(conn)).operations)

    def test_k_recompute_what_is_stale_without_asking_and_with_its_progress(self) -> None:
        """RF-013-31, RF-013-17 (RF-008-26, D-19, RNF-013-07; M7): cambiar un valor del perfil EXPL
        solo para V01 deja obsoletas las operaciones de ``des`` que lo leyeron (el escalonado «Hoyo» y
        el «Monticulo», con su envolvente por sectores) y no la envolvente «Hoyo», que no lo lee;
        «Recalcular lo obsoleto» las rehace por la cola de ``des`` **sin pedir confirmación**, con su
        avance en la barra de estado («Recalculando «Hoyo»… 100 %»), cada una en la revisión abierta
        de V01 y sustituyendo a la obsoleta, con el valor nuevo entre sus entradas y sus cifras
        finitas; nada queda obsoleto ni en la cola, ni sin registrar, ni con temporales, y la barra
        N lee el dato nuevo «Al día»."""
        key = f"des.bench.{EXPL.lower()}.height_m"
        graph = _module("core.provenance.graph")
        self.assertEqual(self.stale(), {})
        pending = {kind: [row[0] for row in self.operations(kind, "done")]
                   for kind in (ENVELOPE_TYPE, STEPPED_TYPE)}
        self.assertEqual((len(pending[ENVELOPE_TYPE]), len(pending[STEPPED_TYPE])), (3, 2))
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=key, value="6", kind="ADOPTADO", source=SOURCE, source_kind="DOCUMENT",
            decided_by=PERSON, reason=REASON, scope="VERSION"), {"FINISHED"})
        ((own,),) = self.rows("SELECT uid FROM gb_parameter WHERE key = ? AND scope_uid = ?",
                              key, self.v01.uid)
        found = self.stale()
        self.assertTrue(found, "ninguna operación de des quedó obsoleta")
        for uid, causes in found.items():
            self.assertEqual(causes, {graph.Cause(graph.CauseKind.PARAMETER_CHANGED, own)})
        kinds = {self.rows("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for uid in found}
        self.assertEqual(kinds, {ENVELOPE_TYPE, STEPPED_TYPE})
        names = {json_name(self.rows("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0])
                 for uid in found}
        self.assertEqual(names, {"Hoyo", "Monticulo"})
        hoyo_envelope = next(uid for uid in pending[ENVELOPE_TYPE]
                             if json_name(self.rows("SELECT settings FROM gb_operation WHERE "
                                                    "uid = ?", uid)[0][0]) == "Hoyo")
        self.assertNotIn(hoyo_envelope, found)  # la envolvente del hoyo no lee el perfil
        old_stepped = {json_name(settings): uid for uid, settings in self.rows(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done'",
            STEPPED_TYPE)}
        old_figure = self.figures_of(old_stepped["Hoyo"])

        # Recalcular lo obsoleto: sin confirmar, sin diálogo, por la cola de des y con su avance.
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text") as status:
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"),
                             {"RUNNING_MODAL"})
            operator = self.running(RECOMPUTE)
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
            calls: list[float] = []
            for _ in range(MAX_EVENTS):
                started = time.process_time()
                state = operator.modal(bpy.context, TIMER)
                self.des_ops.des_tick()  # el temporizador de la cola (en blender -b, a mano)
                calls.append(time.process_time() - started)
                if state != {"RUNNING_MODAL"}:
                    break
            else:
                self.fail("el recálculo no acaba")
        ask.assert_not_called()
        self.assertEqual(state, {"FINISHED"})
        self.assertLess(max(calls), 0.4)  # una llamada del modal y un paso de la cola (RNF-013-07)
        self.assertEqual({str(result.status) for result in operator.result.results}, {"done"})
        self.assertTrue(operator.progress_log)
        shown = [call.args[0] for call in status.call_args_list]
        self.assertIn("Recalculando «Hoyo»… 100 %", shown)
        self.assertIn("Recalculando «Monticulo»… 100 %", shown)
        self.assertEqual(self.des_ops.pending_runs(), [])
        self.assertEqual(self.stale(), {})
        self.assertIsNone(self.des_ops.calculation())  # no deja un cálculo sin registrar
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.operations(ENVELOPE_TYPE, "running"), [])
        self.assertEqual(self.operations(STEPPED_TYPE, "running"), [])

        ((opened,),) = self.rows("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = "
                                 "'open'", self.v01.uid)
        for old in found:  # cada obsoleta tiene quien la sustituye, hecha, en la revisión abierta
            ((new,),) = self.rows("SELECT superseded_by FROM gb_operation WHERE uid = ?", old)
            self.assertTrue(new, f"{old}: nadie la sustituye")
            self.assertEqual(self.rows("SELECT status, supersedes_uid, revision_uid FROM "
                                       "gb_operation WHERE uid = ?", new),
                             [("done", old, opened)])
        ((value,),) = self.rows(
            "SELECT p.value FROM gb_operation_param AS p JOIN gb_operation AS o ON o.uid = "
            "p.operation_uid WHERE o.op_type = ? AND o.status = 'done' AND o.superseded_by IS "
            "NULL AND o.settings LIKE '%Hoyo%' AND p.key = ?", STEPPED_TYPE, key)
        self.assertEqual(json.loads(value), 6.0)  # el valor nuevo, entre sus entradas
        (new_hoyo,) = [uid for uid, settings in self.rows(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
            "superseded_by IS NULL", STEPPED_TYPE) if json_name(settings) == "Hoyo"]
        self.assertNotEqual(new_hoyo, old_stepped["Hoyo"])
        figures = self.figures_of(new_hoyo)
        self.assertEqual(sorted(figures), sorted(old_figure))
        self.assertTrue(all(np.isfinite(value) for value in figures.values()))
        self.assertNotEqual(figures["des.cut_m3"], old_figure["des.cut_m3"])  # con otro banco
        self.assertIn("des_srf_hoyo", self.datasets())  # un dato vivo por nombre, el nuevo

        # La barra N lee el dato nuevo «al día» (el estado sale de la procedencia).
        read = self.panels.item_lines(self.project, self.grid_uid("des_srf_hoyo"))
        self.assertIn("Al día", [line.text for line in read.lines])
        self.i18n.set_language("en")
        self.assertEqual(self.i18n.tr(self.des_ops.RECOMPUTING, name="Hoyo", percent=40),
                         "Recomputing «Hoyo»… 40 %")

    def test_l_closing_the_project_midway_says_so_in_its_own_words(self) -> None:
        """RF-013-33, D-14 (F-4 de la verificación única, T37): si el proyecto se cierra a mitad de
        un cálculo, el modal se para sin dejar nada y dice «Se cerró el proyecto mientras se
        calculaba «Cierre»: no ha quedado nada a medias» (en inglés, su propio *msgid*), no que se
        cubicaba; el texto de la cubicación (011), que usa ``res.py``, sigue siendo el suyo."""
        closed = ("The project was closed while the design «{name}» was being computed: nothing "
                  "has been left half-done")
        cubication = ("The project was closed while «{name}» was being computed: nothing has been "
                      "left half-done")
        files = self.names()
        for language, wanted in (
                ("es", "Se cerró el proyecto mientras se calculaba «Cierre»: no ha quedado nada a "
                       "medias"),
                ("en", closed.format(name="Cierre"))):
            with self.subTest(idioma=language):
                self.i18n.set_language(language)
                with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):
                    modal = self.start(name="Cierre")
                    self.drive(modal, stop_after=2)  # ya ha empezado y aún no ha acabado
                    with mock.patch.object(self.ps, "current", return_value=None):  # se cierra
                        self.assertEqual(modal.modal(bpy.context, TIMER), {"CANCELLED"})
                self.assertEqual(modal.report_log, [wanted])
                self.assertIsNone(modal._steps)
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.des_ops._NEXT, [])  # noqa: SLF001 - ni el escalonado pendiente
                self.assertEqual(self.operations(ENVELOPE_TYPE, "running"), [])
                self.assertEqual(self.temporaries(), [])
                self.assertEqual(self.names(), files)
        self.i18n.set_language("es")
        self.assertEqual(self.i18n.tr(closed, name="Hoyo"),
                         "Se cerró el proyecto mientras se calculaba «Hoyo»: no ha quedado nada a "
                         "medias")
        self.assertEqual(self.i18n.tr(cubication, name="Hoyo"),
                         "Se cerró el proyecto mientras se cubicaba «Hoyo»: no ha quedado nada a "
                         "medias")

    def test_z_disabling_geoblender_removes_the_command_and_drops_the_calculation(self) -> None:
        """Principio 8, D-14: con un cálculo abierto, desactivar Geoblender lo descarta (no queda
        ningún temporal) y quita la orden."""
        state, _calls, _modal = self.calculate(name="Al apagar")
        self.assertEqual(state, {"FINISHED"})
        self.assertTrue(self.temporaries())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_compute_envelope", None))
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())


if __name__ == "__main__":
    unittest.main()
