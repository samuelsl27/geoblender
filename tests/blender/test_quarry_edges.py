# SPDX-License-Identifier: GPL-3.0-or-later
"""«Transiciones con el terreno no afectado» en Blender (spec 014, T28; HU-014-5; RF-014-19 a
RF-014-21, RF-014-29; plan 014 §5.3.3, §5.5; comprobación manual M7).

:class:`GEOBLENDER_OT_des_create_transitions` (``geoblender.des_create_transitions``, en
Restauración ▸ Superficie final) calcula con ``design.steps.edge_transition_run`` la operación
``des.edge_transition`` de la versión activa: la transición de una **superficie de diseño** con el
terreno no afectado del borde de lo que mueve y el salto creado que deja. Su diálogo pide el
nombre, la superficie de diseño (solo las de la versión: las de un escalonado, una cantera o una
transición) y la superficie de partida; propone **la superficie de diseño seleccionada** en la
vista (o, sin ella, la primera de la lista) y, de partida, la de su ficha. Calcular, Crear,
Cancelar y Esc son los de las demás órdenes de la 014 (``_CalculateAndCreate``): nada se registra
hasta Crear. El cargador de ``des_trn_`` la lleva a la vista como objeto ``DESIGN`` y la barra N
enseña su ficha.

Un proyecto pequeño por clase (ventana de 40 × 40 m con celdas de 2 m, V01, el límite legal de
(4, 4) a (36, 36) con 2 m hacia dentro, el perímetro de (2, 2) a (38, 38), un sector con la
búsqueda cerrada, la ladera ``100 + 0,25·y + 0,0625·x``, el perfil ``REST_5_35_6`` y un ángulo de
transición de 15° declarado: un dato de la prueba, más tendido que el talud general del perfil
(20,8°), para que la transición cambie la pared) con la cantera «Corta» de V01 creada por el
dominio (las dos superficies con ``REST_5_35_6`` y semillas en la coronación). Las pruebas, en el
orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import tempfile
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

TRANSITIONS = "geoblender.des_create_transitions"
TRANSITIONS_CLASS = "GEOBLENDER_OT_des_create_transitions"
TRANSITION_TYPE = "des.edge_transition"
RECLAMATION = "GEOBLENDER_MT_ui_reclamation"
KIND = "DESIGN"
REASON = "Prueba de las transiciones con el terreno no afectado"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de restauración"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 40.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (4.0, 4.0, 36.0, 36.0)
PERIMETER = (2.0, 2.0, 38.0, 38.0)
SECTOR = ("Sector único", (0.0, 0.0, 40.0, 40.0))
CLOSED_AT = "2026-11-13T10:00:00Z"
REST, REST_CODE = "REST_5_35_6", "rest_5_35_6"
QUARRY_NAME = "Corta"
NAME = "Borde"
ANGLE_KEY = "des.edge.transition_deg"
ANGLE_DEG = 15.0
PROPERTIES = {
    "name": ("Name", "Name of the transition, unique in the active version"),
    "surface": ("Design surface", "Design surface of the active version that is joined with the "
                                  "untouched terrain at the edge of what it moves"),
    "start": ("Start surface", "Surface the design starts from: the untouched terrain is the one "
                               "the design does not move"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (fila 0 al norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    x, y = np.meshgrid(STEP_M * index + STEP_M / 2, SIZE_M - (STEP_M * index + STEP_M / 2))
    return 100.0 + 0.25 * y + 0.0625 * x


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class CreateTransitionsTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera, para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t28-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.views = _module("bl.scene.views")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.dmodel = _module("design.model")
        cls.edges = _module("design.edges")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        cls.model = _module("core.project.model")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = _module("core.versions.store").create_version(
                conn, cls.project, feature="cantera", title="Cantera", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        with cls.project.write_transaction() as conn:
            _module("core.params").ParameterStore(cls.project).create(
                conn, ANGLE_KEY, ANGLE_DEG, kind="ADOPTADO", source="Criterio de la prueba",
                source_kind="person", decided_by=PERSON, reason=REASON)
        cls.project.refresh_header()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=REST, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
            scope="PROJECT", height="5", face="35", berm="6", anchor="125") == {"FINISHED"}
        side = cls.dmodel.QuarrySide(REST_CODE)
        request = cls.dmodel.QuarryRequest(QUARRY_NAME, cls.ground, side, side)
        found = None
        for found in _module("design.steps").quarry_run(cls.project, request,
                                                        version=cls.v01.uid):
            pass
        found.result.create()
        cls.final = cls.dprov.dataset_name("fin", QUARRY_NAME)
        cls.exploitation = cls.dprov.dataset_name("exp", QUARRY_NAME)
        cls.dataset = cls.dprov.dataset_name("trn", NAME)
        cls.panels.refresh_choices(cls.project)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y el sector de búsqueda,
        con su búsqueda cerrada, como los dejan las órdenes de la 012."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 13), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                                                 row(types.ACTION_PERIMETER, "Perímetro",
                                                     PERIMETER)],
                                   params=declaration, srs_id=cls.project.record.crs_epsg)
        operations = _module("core.provenance.operations")
        sector = cls.cmodel.Sector(f"sector1{'0' * 26}", "sector_1", SECTOR[0], (ring(SECTOR[1]),))
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, (sector,), srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sector de prueba")
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, "sector_1",
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto de la ventana con ``values``; el nombre de su dato."""
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
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no sigue

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> Any:
        return self.commands.registered_class(TRANSITIONS)

    @property
    def view(self) -> Any:
        return bpy.context.window_manager.geoblender_design

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def names(self) -> list[str]:
        """Los ficheros de la carpeta del proyecto (sin el diario de la base)."""
        root = Path(self.project.root)
        return sorted(str(item.relative_to(root)) for item in root.rglob("*")
                      if item.is_file() and item.suffix != ".gpkg-journal")

    def state(self) -> tuple[Any, ...]:
        """Lo que la orden podría dejar: operaciones, datos, cifras y ficheros."""
        return (self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
                self.rows("SELECT name, status FROM gb_dataset ORDER BY name"),
                self.rows("SELECT count(*) FROM gb_figure"), self.names())

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: la transición «Borde» de la superficie final de la cantera."""
        return {"name": NAME, "surface": self.final, "start": self.ground, "in_steps": False,
                **values}

    def fake_dialog(self, selected: tuple[Any, ...] = (), **values: Any
                    ) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana), con los
        objetos ``selected`` seleccionados en la vista."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=selected,
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "surface": "", "start": "", "confirm": False, "in_steps": False,
            "properties": SimpleNamespace(is_property_set=lambda name: False), **values}
        return operator_self(self.cls, report=lambda kind, text: None, **fields), context, dialog

    def loaded(self, name: str) -> Any:
        """El objeto de la vista del dato vivo ``name`` (lo carga si no está)."""
        (uid,) = [row[0] for row in self.rows(
            "SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", name)]
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        if not found:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
            found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        self.assertEqual(len(found), 1)
        return found[0]

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{TRANSITIONS} no está en marcha")
        return found[0]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-014-19, RF-014-29 (plan §5.3.3, §5.5): «Transiciones con el terreno no afectado» es
        una orden real de ``des.edge_transition`` en Restauración, con la puerta de la procedencia y
        los pasos con Esc; sus propiedades tienen nombre y descripción en español; su lista de
        superficies de diseño tiene solo las de la versión (las dos de la cantera, no la ladera ni
        las envolventes ni la clasificación); su diálogo propone «Transición», **la superficie de
        diseño seleccionada** en la vista (sin selección, la primera de la lista) y, de partida, la
        de su ficha; lo dado no cambia; dibuja el nombre y las dos superficies."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (TRANSITION_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        command = self.commands.catalog().commands[TRANSITIONS]
        self.assertEqual((command.label_es, command.home),
                         ("Transiciones con el terreno no afectado", RECLAMATION))
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[TRANSITION_TYPE].commands,
                         (TRANSITIONS,))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        listed = [item[0] for item in self.panels.design_surface_items(None, None)]
        self.assertEqual(sorted(listed), sorted([self.exploitation, self.final]))

        fake, context, dialog = self.fake_dialog()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"],
                         "Transiciones con el terreno no afectado")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.surface, fake.start),
                         ("Transición", listed[0], self.ground))
        chosen = self.loaded(self.final)
        fake, context, _dialog = self.fake_dialog(selected=(chosen,))
        cls.invoke(fake, context, None)
        self.assertEqual((fake.surface, fake.start), (self.final, self.ground))
        given, context, _dialog = self.fake_dialog(
            selected=(chosen,), name="Mía", surface=self.exploitation, start=self.ground,
            properties=SimpleNamespace(is_property_set=lambda name: name in ("surface", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.surface), ("Mía", self.exploitation))
        shown = draw(cls, bpy.context, name=NAME, surface=self.final, start=self.ground,
                     confirm=False).texts()
        for heading in ("Nombre", "Superficie de diseño", "Superficie de partida"):
            self.assertIn(heading, shown)

    def test_b_calculate_then_create_the_transition(self) -> None:
        """RF-014-19 a RF-014-21, RF-014-29 (M7): Calcular desde un guion deja el cálculo abierto
        con su resumen (la transición en m³ y el salto creado del borde, en los dos idiomas) y solo
        el temporal; Crear registra ``des.edge_transition`` hecha en V01 con ``des_trn_`` (la
        transición de A10 en lo que mueve la superficie final, releída, que solo la acerca al
        terreno: ninguna celda fuera de ``[mín(final, ladera), máx(final, ladera)]``, T40) y
        ``des_erp_`` y sus tres cifras CALCULADO."""
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_create_transitions(
            "EXEC_DEFAULT", **self.form()), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        self.assertEqual((held.op_type, held.name, held.version), (TRANSITION_TYPE, NAME, "V01"))
        after = self.state()
        self.assertEqual(after[:3], before[:3], "calcular no registra nada")
        (temporary,) = sorted(set(after[3]) - set(before[3]))
        self.assertIn(".tmp", temporary)
        self.assertEqual(self.view.summary_title, f"Transición «{NAME}» en V01")
        summary = [line.name for line in self.view.summary]
        outcome = held.outcome
        self.assertTrue(summary[0].startswith(f"Transición de «{self.final}» a 15°"), summary)
        self.assertIn("parejas", summary[1])
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertTrue([line.name for line in self.view.summary][0].startswith(
            f"Transition of «{self.final}» at 15°"))
        self.i18n.set_language("es")
        final = self.surfaces.read_surface(self.project, self.final,
                                           version_uid=self.v01.uid).values
        masks = _module("gis.masks.access").load_masks(self.project, self.v01.uid)
        thickness = _module("core.params").definition("res.verify.min_thickness_m").default
        with np.errstate(invalid="ignore"):
            domain = ((masks.cut_allowed() | masks.fill_allowed()) & np.isfinite(final)
                      & (np.abs(final - ground()) > thickness))
        np.testing.assert_array_equal(outcome.domain, domain)
        expected = None
        for expected in self.edges.transition_steps(final, ground(), domain, masks.grid,
                                                    ANGLE_DEG):
            pass
        np.testing.assert_array_equal(outcome.grid, expected.result.grid)
        with np.errstate(invalid="ignore"):
            low, high = np.fmin(final, ground()), np.fmax(final, ground())
            away = domain & ((outcome.grid < low) | (outcome.grid > high))
        self.assertFalse(bool(away.any()), "la transición aleja celdas del terreno")
        self.assertGreater(outcome.transition.volume_m3, 0.0)

        self.assertEqual(bpy.ops.geoblender.des_create_transitions(
            "EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                     TRANSITION_TYPE)
        self.assertEqual(status, "done")
        written = self.surfaces.read_surface(self.project, self.dataset,
                                             version_uid=self.v01.uid).values
        np.testing.assert_array_equal(written, outcome.grid)
        np.testing.assert_array_equal(written[~outcome.domain], final[~outcome.domain])
        self.assertTrue(outcome.domain.any())
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual(figures, {"des.transition_m3": outcome.transition.volume_m3,
                                   "des.created_step_max_m": max(0.0, outcome.report.maximum_m),
                                   "des.created_step_share_pct": outcome.report.within_pct})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name IN (?, ?) AND "
                                   "status = 'current'", self.dataset,
                                   self.dprov.dataset_name("erp", NAME)), [(2,)])

    def test_c_the_transition_in_the_view_and_its_card(self) -> None:
        """RF-014-19 (M7): «Cargar en la vista» de la transición da un objeto ``DESIGN``
        «Transición con el terreno no afectado …» a sus cotas; la barra N enseña su ficha: la
        superficie de diseño y la de partida y sus cifras, sin envolvente ni semillas; seleccionada
        no se propone como superficie de partida de otra transición."""
        loader = self.views.loader_for(self.dataset)
        self.assertEqual((loader.prefix, loader.kind, loader.label),
                         ("des_trn_", KIND, "Transition with the untouched terrain"))
        obj = self.loaded(self.dataset)
        self.assertTrue(obj.name.startswith("Transición con el terreno no afectado "), obj.name)
        found = self.panels.item_lines(self.project, str(obj.geoblender.dataset_uid))
        texts = [line.text for line in found.lines]
        self.assertEqual(found.title, f"Transición con el terreno no afectado · {NAME}")
        self.assertIn(f"Superficie de diseño: «{self.final}»", texts)
        self.assertIn(f"Superficie de partida: «{self.ground}»", texts)
        self.assertNotIn("Semillas y dominios", texts)
        self.assertFalse(any(text.startswith("Envolvente") for text in texts), texts)
        self.assertEqual(len(found.figures), 4, found.figures)  # el encabezado y las tres
        self.panels.refresh_choices(self.project)
        listed = [item[0] for item in self.panels.design_surface_items(None, None)]
        self.assertIn(self.dataset, listed)  # una transición también es una superficie de diseño
        fake, context, _dialog = self.fake_dialog(selected=(obj,))
        self.cls.invoke(fake, context, None)
        self.assertEqual((fake.surface, fake.start), (self.dataset, self.ground))

    def test_d_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-014-29 (RNF-014-05): Esc con el cálculo en marcha, Cancelar la confirmación y un
        nombre vacío no dejan nada (ni operación, ni dato, ni cifra, ni temporal); Esc deja el
        aviso de que no queda nada a medias."""
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_transitions(
                "EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.des_create_transitions(
            "EXEC_DEFAULT", **self.form(name="Cancelada")), {"FINISHED"})
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_create_transitions("EXEC_DEFAULT", **self.form(name=" "))
        self.assertIn("Escriba el nombre de la transición", str(caught.exception))
        self.assertEqual(self.state(), before)

    def test_z_disabling_geoblender_removes_the_command_and_the_loader(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta
        (no queda ningún temporal) y quita la orden y el cargador de la transición."""
        self.assertEqual(bpy.ops.geoblender.des_create_transitions(
            "EXEC_DEFAULT", **self.form(name="Al apagar")), {"FINISHED"})
        self.assertTrue(any(".tmp" in name for name in self.names()))
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, TRANSITIONS_CLASS, None))
        self.assertIsNone(self.views.loader_for(self.dataset))
        self.assertFalse(any(".tmp" in name for name in self.names()))


if __name__ == "__main__":
    unittest.main()
