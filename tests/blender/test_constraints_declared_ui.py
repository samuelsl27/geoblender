# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista de la 012 con las restricciones declaradas por las entidades (spec 015, T21; HU-015-1;
RF-012-18, RF-012-19, RF-012-29, RF-012-02, RF-015-11; plan 015 §5.1 y §5.5; comprobación manual M2).

Una restricción declarada por una entidad de diseño (RF-012-29) es de su versión: la tabla
``des_decl_<vNN>`` que escribe ``des.declare_constraints``, con el contorno de la huella de la entidad,
su resguardo y su «activa» como columnas, y no se edita a mano (RF-008-56). La vista de la 012 la
enseña como las demás, pero con **su entidad**, y no deja cambiarla fuera de la entidad. Un proyecto
por clase (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, las seis restricciones de seis tipos de
las pruebas de la 012 y, **solo en V01**, la que declara la plataforma «P1» —«sin relleno», con 4 m de
resguardo—, con las máscaras compiladas con ella) y las pruebas, en el orden de sus letras sobre el
mismo estado:

- RF-012-18 (a): «Ver restricciones y límites» enseña la declarada con su contorno y su zona, el color
  de su tipo (el de «sin relleno», como cualquier otra), su entidad en la etiqueta y en la leyenda
  («Plataforma P1 (declarada)», nunca ``dec__plt_001``); V02, que no la tiene, no la enseña.
- RF-012-19, RF-012-02 (b): la ventana Restricciones… y la barra N dicen de la declarada su origen (la
  entidad), su estado «Activa», su resguardo («la da la entidad»), y **no ofrecen** «Cambiar…» ni
  «Editar…», sino que se cambia en la entidad; una restricción del proyecto, sí; con la declaración que
  difiere de la de las entidades, lo avisa.
- RF-012-02, RF-012-29 (c): las órdenes de cambiar sobre una declarada fallan con un mensaje claro y sin
  traza, sin escribir nada.
- RF-012-18 (d, e): los desplegables de zonas del diseño y los nombres de las verificaciones y de las
  fichas incluyen la declarada por su entidad, sin su código.
- RF-015-11, RF-012-19 (f, g): editar su tabla en QGIS la deja **bloqueada**: la barra N y la lista
  dicen «Bloqueada por una edición fuera de Geoblender» y qué hacer, la leyenda de la superposición lo
  avisa, y compilar se niega; aceptar la edición con un motivo la desbloquea.
- Principio 8 (z): desactivar Geoblender con la superposición activa deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import sqlite3
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
from tests.support.fake_layout import draw
from tests.support.trees import remove_tree

TOGGLE = "geoblender.core_toggle_constraints_overlay"
PANEL = "GEOBLENDER_PT_core_constraint"
WINDOW = "GEOBLENDER_PT_core_constraints"
COMPLETE = "geoblender.core_complete_constraint"
SET_PARAMETER = "geoblender.core_set_parameter"
VIEW_PROPERTY = "geoblender_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
REASON = "Prueba de las restricciones declaradas por las entidades"
PERSON = "Samuel (IMGA)"
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
TOWER = (20.0, 20.0, 26.0, 26.0)
POND = (34.0, 10.0, 44.0, 18.0)
TRACK = ((6.0, 40.0), (52.0, 40.0))
TREE = (12.0, 12.0)
BUFFER_M = 4.0
NAMES = {"legal_limit": "Concesión", "action_perimeter": "Perímetro", "untouchable": "Torre 132 kV",
         "no_cut": "Balsa", "requires_access": "Camino", "avoid": "Árbol"}
ENTITY = "PLT-001"
ENTITY_NAME = "P1"
CODE = "dec__plt_001"
SHOWN = "Plataforma P1 (declarada)"
ORIGIN = "Plataforma P1 (PLT-001)"
BOX = (30.0, 26.0, 40.0, 32.0)
"""La huella de la entidad (local: izquierda, abajo, derecha, arriba): 5 × 3 celdas de 2 m."""
GUARD_M = 4.0
TABLE = "des_decl_v01"
MAX_PUMPS = 20_000


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


class DeclaredViewTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, seis restricciones y la declarada de
    una entidad en V01, para toda la clase (las pruebas, en el orden de sus letras: cada una parte de lo
    que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t21-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.versions = _module("bl.scene.versions")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.des_panels = _module("bl.ui.des_panels")
        cls.views = _module("bl.scene.constraint_views")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.styles = _module("core.constraints.styles")
        cls.declared = _module("core.constraints.declared")
        cls.dprov = _module("design.provenance")
        cls.entities = _module("design.entities")
        cls.masks_store = _module("gis.masks.store")
        cls.access = _module("gis.masks.access")
        cls.operations = _module("core.provenance.operations")
        cls.i18n = _module("core.i18n")
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
        cls.declare_project_constraints()
        cls.declared_uid = cls.declare_entity_constraint()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        cls.compile_masks(cls.v01)
        cls.ov = _module("bl.draw.constraints")

    @classmethod
    def declare_project_constraints(cls) -> None:
        """Las seis restricciones del proyecto como las dejará la orden (``core.edit_constraints``)."""
        m, kinds = cls.cmodel, cls.cmodel.GeometryKind

        def row(ctype: Any, kind: Any, parts: Any) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=NAMES[ctype.value], ctype=ctype, kind=kind,
                parts=parts, priority=0, reason=REASON, decided_by=PERSON,
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
        cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                   srs_id=cls.project.record.crs_epsg)

    @classmethod
    def declare_entity_constraint(cls) -> str:
        """La restricción que declara la plataforma «P1» en V01 (``des.declare_constraints``, como la deja
        la orden de la entidad: la tabla ``des_decl_v01`` con el contorno de su huella, 4 m de resguardo y
        «activa»); el ``uid`` de la restricción."""
        declared, dprov = cls.declared, cls.dprov
        row = declared.DeclaredConstraint(
            uid=declared.declared_uid(cls.v01.uid, ENTITY), code=declared.declared_code(ENTITY),
            ctype=cls.cmodel.ConstraintType.NO_FILL, name=ENTITY_NAME,
            reason=cls.entities.declared_reason(cls.entities.EntityKind.PLATFORM, ENTITY_NAME),
            decided_by=PERSON, decided_on=date(2026, 11, 14), entity_code=ENTITY,
            entity_name=ENTITY_NAME, parts=((ring(BOX),),), buffer_out_m=GUARD_M, active=True)
        srs = cls.project.record.crs_epsg
        table = dprov.dataset_locator(dprov.DECLARED_TABLE, "", cls.v01.code)
        handle = cls.operations.begin_operation(
            cls.project, dprov.DECLARE_CONSTRAINTS, executor="blender", version=cls.v01.uid,
            settings=dprov.declare_settings([(ENTITY, ENTITY_NAME)]))
        with cls.project.write_transaction() as conn:
            declared.write_declared(conn, table, [row], srs_id=srs)
            handle.complete(conn, outputs=(dprov.dataset_spec(
                dprov.DECLARED_TABLE, "", cls.v01.code, crs_epsg=srs),),
                figures=dprov.declare_figures(1), message="Restricción declarada de prueba")
        cls.project.refresh_header()
        return str(row.uid)

    @classmethod
    def compile_masks(cls, version: Any) -> None:
        """La compilación de ``version`` como la lanzará la orden (``begin_compile`` y sus pasos)."""
        handle = cls.masks_store.begin_compile(cls.project, version=version.uid)
        for _step in cls.masks_store.compile_run(cls.project, handle):
            pass
        cls.project.refresh_header()

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
    def origin(self) -> Any:
        return self.project.origin

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas locales de la prueba (desde el SO de la ventana) respecto al GeoOrigin."""
        return (WEST + x - self.origin.x0, SOUTH + y - self.origin.y0)

    def pump(self) -> Any:
        """Los pasos de la construcción de la superposición, hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.ov.tick() is None:
                built = self.ov.built()
                self.assertIsNotNone(built, "la superposición no construyó nada")
                return built
        self.fail("la superposición no acaba de construirse")

    def chosen(self, code: str) -> Any:
        """Lee la lista de Restricciones… y elige la restricción de código ``code`` (la barra N la
        sigue): su fila."""
        self.panels.fill_constraints(self.project)
        view = self.view
        index = next(n for n, item in enumerate(view.constraints) if item.code == code)
        view.item_index = index
        self.panels.read_selected(bpy.context)
        return view.constraints[index]

    def selected_layout(self) -> Any:
        return draw(getattr(bpy.types, PANEL), bpy.context)

    def window_layout(self) -> Any:
        return draw(getattr(bpy.types, WINDOW), bpy.context)

    def buttons(self, layout: Any) -> set[str]:
        """Las órdenes que dibujó ``layout`` para cambiar o editar una restricción."""
        return {item.target for item in layout.of_kind("operator")
                if item.target in (COMPLETE, SET_PARAMETER)}

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def state(self) -> tuple[Any, ...]:
        """Lo que una orden de cambiar podría dejar: operaciones, parámetros y datos."""
        return (self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
                self.rows("SELECT key, scope, value FROM gb_parameter ORDER BY fid"),
                self.rows("SELECT name, status, content_sha256 FROM gb_dataset ORDER BY name"))

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_overlay_shows_the_declared_one_with_its_entity(self) -> None:
        """RF-012-18, RF-012-29: con las máscaras de V01 compiladas con la declarada, «Ver restricciones y
        límites» enseña su contorno (el rectángulo de su huella) y su zona rayada con el color de su tipo
        (el de «sin relleno», como las demás), su entidad en la etiqueta y en la leyenda («Plataforma P1
        (declarada)») y nunca su código; V02, que no la tiene, no la enseña; no escribe nada en el
        proyecto."""
        ov = self.ov
        self.assertEqual(self.access.mask_state(self.project, self.v01.uid)[0].value, "current")
        operations = self.rows("SELECT count(*) FROM gb_operation")
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        built = self.pump()
        self.assertEqual((built.version_code, built.masks), ("V01", "current"))
        no_fill = self.styles.COLORS[self.cmodel.ConstraintType.NO_FILL]
        outline = built.batch("no_fill", ov.OUTLINE)
        self.assertIsNotNone(outline, "el contorno de la declarada")
        self.assertEqual(outline.segments, 4)
        self.assertEqual(tuple(round(c * 255) for c in outline.color[:3]), no_fill)
        xy = outline.positions[:, :2]
        left, bottom = self.local(BOX[0], BOX[1])
        right, top = self.local(BOX[2], BOX[3])
        self.assertEqual((xy.min(axis=0).tolist(), xy.max(axis=0).tolist()),
                         ([left, bottom], [right, top]))
        zone = built.batch("no_fill", ov.ZONE)
        self.assertIsNotNone(zone, "la zona de la declarada, aunque su código no sea el de ninguna de "
                                   "las capas del proyecto")
        self.assertGreater(zone.segments, 0)
        self.assertEqual(tuple(round(c * 255) for c in zone.color[:3]), no_fill)
        reach = GUARD_M + STEP_M  # la celda que la toca, hasta una celda más
        x0, y0 = self.local(BOX[0] - reach, BOX[1] - reach)
        x1, y1 = self.local(BOX[2] + reach, BOX[3] + reach)
        zxy = zone.positions[:, :2]
        self.assertTrue(np.all((zxy[:, 0] >= x0 - 1e-3) & (zxy[:, 0] <= x1 + 1e-3)))
        self.assertTrue(np.all((zxy[:, 1] >= y0 - 1e-3) & (zxy[:, 1] <= y1 + 1e-3)))
        names = {label.text for label in built.labels}
        self.assertIn(SHOWN, names)
        self.assertTrue(names >= set(NAMES.values()))
        self.assertNotIn(CODE, names)
        self.assertNotIn(ENTITY_NAME, names, "la etiqueta es la de la entidad, no solo su nombre")
        label = next(label for label in built.labels if label.text == SHOWN)
        self.assertEqual(tuple(round(c * 255) for c in label.color[:3]), no_fill)
        legend = [row.text for row in built.legend]
        self.assertIn(SHOWN, legend)
        self.assertIn("Sin relleno (1)", legend)
        row = next(row for row in built.legend if row.text == SHOWN)
        self.assertEqual(row.color, "#%02x%02x%02x" % no_fill)
        self.assertFalse([text for text in legend if CODE in text])
        self.assertNotIn("Restricciones declaradas bloqueadas", " ".join(legend))
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation"), operations)
        self.set_active(self.v02)  # la de V01 no es de V02
        other = self.pump()
        self.assertEqual(other.version_code, "V02")
        self.assertIsNone(other.batch("no_fill", ov.OUTLINE))
        self.assertNotIn(SHOWN, {label.text for label in other.labels})
        self.assertNotIn(SHOWN, [row.text for row in other.legend])
        self.set_active(self.v01)
        self.assertIn(SHOWN, [row.text for row in self.pump().legend])
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        self.assertFalse(ov.enabled())

    def test_b_the_side_bar_says_origin_and_state_and_offers_no_change(self) -> None:
        """RF-012-19, RF-012-02, RF-012-29: la barra N de la declarada (elegida en la lista de
        Restricciones…) dice su origen —la entidad, con su tipo y su código—, su estado «Activa», su motivo
        y su decisor, y su resguardo, que **da la entidad**; no ofrece «Cambiar…» ni «Editar…», sino que se
        cambia en la entidad; la de una restricción del proyecto, sí. La ventana Restricciones… igual. Si
        la declaración difiere de la de las entidades, lo avisa."""
        item = self.chosen(CODE)
        self.assertEqual((item.declared, item.origin, item.state, item.ctype, item.name),
                         (True, ORIGIN, "active", "no_fill", SHOWN))
        self.assertEqual(item.uid, self.declared_uid)
        self.assertEqual((item.reason, item.decided_by, item.decided_on, item.priority),
                         ("declarada por la plataforma P1", PERSON, "14/11/2026", 0))
        (line,) = item.parameters
        self.assertEqual(line.name, "Resguardo hacia fuera")
        self.assertRegex(line.text, r"^4 m · la da la entidad$")
        self.assertFalse(line.registered, "no es un parámetro del almacén: no hay nada que «Cambiar…»")
        panel = getattr(bpy.types, PANEL)
        self.assertTrue(panel.poll(bpy.context))
        selected = self.view.selected
        self.assertEqual((selected.uid, selected.declared, selected.origin, selected.state),
                         (self.declared_uid, True, ORIGIN, "active"))
        with mock.patch.object(_module("design.entity_store"), "declaration_diverges",
                               return_value=False):
            self.panels.read_selected(bpy.context)
        self.assertFalse(self.view.selected.diverges)
        layout = self.selected_layout()
        texts = layout.texts()
        joined = " ".join(texts)
        self.assertTrue(any("Sin relleno" in text and SHOWN in text for text in texts), texts)
        self.assertIn("Activa", texts)
        self.assertIn(f"Origen: {ORIGIN}", joined)
        self.assertIn("Motivo: declarada por la plataforma P1", joined)
        self.assertIn("Resguardo hacia fuera:", joined)
        self.assertIn("4 m · la da la entidad", joined)
        self.assertIn("La declara una entidad: su resguardo, su motivo y si está activa se cambian en la "
                      "entidad", joined)
        self.assertNotIn(CODE, joined)
        self.assertNotIn("La declaración difiere", joined)
        self.assertNotIn("Cambiar…", texts)
        self.assertNotIn("Editar…", texts)
        self.assertEqual(self.buttons(layout), set(), "ni «Cambiar…» ni «Editar…»")
        window = self.window_layout()
        self.assertEqual(self.buttons(window), set())
        self.assertIn(f"Origen: {ORIGIN}", " ".join(window.texts()))
        self.assertIn(SHOWN, " ".join(window.texts()))
        # Si la declaración vigente difiere de la que darían las entidades, lo avisa.
        with mock.patch.object(_module("design.entity_store"), "declaration_diverges",
                               return_value=True):
            self.panels.read_selected(bpy.context)
            self.assertTrue(self.view.selected.diverges)
            self.assertIn("La declaración difiere de la de las entidades",
                          " ".join(self.selected_layout().texts()))
            self.chosen(CODE)  # la lista lo lleva igual (la ventana)
            self.assertTrue(self.view.constraints[self.view.item_index].diverges)
            self.assertIn("La declaración difiere de la de las entidades",
                          " ".join(self.window_layout().texts()))
            tower = self.chosen(next(item.code for item in self.view.constraints
                                     if item.ctype == "untouchable"))
            self.assertFalse(tower.diverges, "solo la de la tabla de las entidades")
        # Una restricción del proyecto: con su origen vacío y sus botones.
        tower = self.chosen(next(item.code for item in self.view.constraints
                                 if item.ctype == "untouchable"))
        self.assertEqual((tower.declared, tower.origin, tower.name), (False, "", "Torre 132 kV"))
        layout = self.selected_layout()
        self.assertEqual(self.buttons(layout), {COMPLETE, SET_PARAMETER})
        self.assertNotIn("Origen:", " ".join(layout.texts()))
        self.assertEqual([item.name for item in self.view.constraints][:6],
                         [NAMES[name] for name in NAMES], "las del proyecto, como siempre")
        self.assertEqual(self.view.constraints[6].code, CODE, "la declarada, tras ellas")
        self.chosen(CODE)

    def test_c_changing_a_declared_one_fails_with_a_clear_message(self) -> None:
        """RF-012-02, RF-012-29: las órdenes de cambiar una restricción (``core_complete_constraint``, la
        de «Editar…», y ``core_set_parameter``, la de «Cambiar…» con la clave de su resguardo) sobre una
        declarada fallan con un mensaje claro —la de editar, que la declara la entidad y se cambia allí; la
        de cambiar, que no es un parámetro registrado— y sin traza, y no escriben nada."""
        before = self.state()
        with self.assertRaises(RuntimeError) as refused:
            bpy.ops.geoblender.core_complete_constraint("EXEC_DEFAULT", uid=self.declared_uid,
                                                        reason="Lo cambio a mano")
        message = str(refused.exception)
        self.assertIn("Esta restricción la declara Plataforma P1", message)
        self.assertIn("se cambian en la entidad", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("ya no está en el proyecto", message)
        with self.assertRaises(RuntimeError) as asked:
            bpy.ops.geoblender.core_set_parameter(
                "EXEC_DEFAULT", key=f"core.constraint.{CODE}.buffer_out_m", value="9",
                reason="Lo cambio a mano")
        self.assertNotIn("Traceback", str(asked.exception))
        self.assertIn(f"core.constraint.{CODE}.buffer_out_m", str(asked.exception))
        self.assertEqual(self.state(), before, "ninguna escribió nada")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_parameter WHERE key LIKE ?", "%dec__%"),
                         [(0,)])
        # La guardia es solo de las declaradas: la fila de una restricción del proyecto se lee como siempre.
        tower = next(item for item in self.view.constraints if item.ctype == "untouchable")
        cls = _module("bl.ops.core_constraints").GEOBLENDER_OT_core_complete_constraint
        found = cls._row(SimpleNamespace(uid=tower.uid, _declared_by=lambda project: None), self.project)
        self.assertEqual((found.code, found.name), (tower.code, "Torre 132 kV"))

    def test_d_the_zone_lists_and_the_names_carry_the_entity_not_the_code(self) -> None:
        """RF-012-18, RF-012-02: los desplegables de zonas del diseño (semillas y zonas a conservar) ofrecen
        la zona de la declarada de la versión activa con su entidad («Plataforma P1 (declarada)») y no su
        código; sin versión activa, o en otra, no; los nombres de la tabla de una verificación y de las
        fichas de los datos de la versión (``shown_names``) también; ``zone_name`` no cae al código."""
        panels, des_panels = self.panels, self.des_panels
        des_panels.refresh_choices(self.project)
        zones = {identifier: (label, about) for identifier, label, about in
                 des_panels.zone_items(None, None)}
        key = des_panels.CONSTRAINT_ZONE + CODE
        self.assertIn(key, zones)
        self.assertEqual(zones[key], (SHOWN, "Zona de una restricción declarada por una entidad"))
        tower = self.rows("SELECT code FROM core_constraint_polygon WHERE name = ?",
                          "Torre 132 kV")[0][0]
        self.assertEqual(zones[des_panels.CONSTRAINT_ZONE + tower][0], "Torre 132 kV")
        self.assertFalse([label for label, _about in zones.values() if CODE in label])
        self.assertIn(key, [item[0] for item in des_panels._CHOICES.conserve],
                      "también las zonas a conservar")
        with self.project.read() as conn:
            names = self.views.shown_names(conn, self.v01.uid)
            plain = self.views.shown_names(conn, self.v02.uid)
            none = self.views.shown_names(conn, None)
        self.assertEqual(names[CODE], (SHOWN, self.cmodel.ConstraintType.NO_FILL))
        self.assertNotIn(CODE, plain)
        self.assertEqual(plain, none)
        self.assertEqual(panels.zone_name(CODE, names), SHOWN)
        self.assertEqual(panels.zone_name(CODE, plain), CODE, "sin la declarada, cae a su código")
        self.set_active(self.v02)
        des_panels.refresh_choices(self.project)
        self.assertNotIn(key, [item[0] for item in des_panels.zone_items(None, None)])
        self.set_active(self.v01)
        des_panels.refresh_choices(self.project)

    def test_e_the_card_of_a_design_names_the_applied_declared_one(self) -> None:
        """RF-012-18: la lista «Restricciones aplicadas» de la ficha de un dato de la versión nombra la
        declarada por su entidad (``constraint_text``), y su tipo, como las demás."""
        listed = self.masks_store.listed_constraints(self.project, version=self.v01.uid)
        lines = [line.text for line in self.des_panels._constraint_lines(listed, "V01")]
        self.assertIn(f"Sin relleno · {SHOWN}", lines)
        self.assertIn("Intocable · Torre 132 kV", lines)
        self.assertFalse([text for text in lines if CODE in text])
        entry = next(item for item in listed if item.declared)
        self.assertEqual(self.views.constraint_text(entry.constraint), SHOWN)
        self.assertEqual(self.views.constraint_text(listed[0].constraint), "Concesión")
        self.i18n.set_language("en")
        self.assertEqual(self.views.constraint_text(entry.constraint), "Platform P1 (declared)")
        self.assertEqual(self.views.entity_text("PLT-001", "P1"), "Platform P1")
        self.assertEqual(self.views.entity_text("XXX-001", "Otra"), "Otra")  # tipo desconocido

    def test_f_editing_the_table_in_qgis_blocks_it_and_the_view_says_so(self) -> None:
        """RF-015-11, RF-012-19, RF-008-56: editar la tabla de la declarada en QGIS la deja bloqueada
        (compilar se niega, con la puerta de la 008); la barra N y la lista dicen «Bloqueada por una edición
        fuera de Geoblender», en alerta y con qué hacer; la superposición sigue enseñando su contorno y su
        entidad, avisa en su leyenda de lo bloqueado y de que las máscaras no están al día; y siguen sin
        ofrecer cambiarla."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)  # QGIS, su conexión
        try:
            conn.execute(f'UPDATE "{TABLE}" SET reason = ?', ("Retocada en QGIS",))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         ("2031-01-01T00:00:00.000Z", TABLE))
        finally:
            conn.close()
        with self.assertRaises(RuntimeError) as refused:  # la puerta bloquea la tabla y se niega
            bpy.ops.geoblender.gis_compile_constraints()
        self.assertIn("se editó fuera de Geoblender", str(refused.exception))
        self.assertEqual(self.rows("SELECT status FROM gb_dataset WHERE name = 'des_decl'"),
                         [("blocked",)])
        self.project.refresh_header()
        item = self.chosen(CODE)
        self.assertEqual((item.state, item.declared, item.origin), ("blocked", True, ORIGIN))
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertEqual(self.view.selected.state, "blocked")
        layout = self.selected_layout()
        texts = layout.texts()
        self.assertIn("Bloqueada por una edición fuera de Geoblender", texts)
        alerts = [entry.text for entry in layout.items if entry.alert and entry.kind == "label"]
        self.assertIn("Bloqueada por una edición fuera de Geoblender", alerts)
        self.assertIn("Acepte la edición con un motivo o recalcule la declaración: la entidad la vuelve "
                      "a poner", " ".join(texts))
        self.assertIn(f"Origen: {ORIGIN}", " ".join(texts))
        self.assertEqual(self.buttons(layout), set())
        self.assertEqual(self.buttons(self.window_layout()), set())
        self.assertIn("Bloqueada por una edición fuera de Geoblender", self.window_layout().texts())
        self.assertFalse(self.view.selected.diverges, "bloqueada: aún no se aceptó lo editado")
        self.assertEqual([entry.state for entry in self.view.constraints][:6], ["active"] * 6,
                         "las del proyecto no se bloquean (RF-012-03)")
        # La superposición: sigue enseñando su contorno y su entidad, y avisa.
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        built = self.pump()
        self.assertIsNotNone(built.batch("no_fill", self.ov.OUTLINE))
        self.assertIn(SHOWN, {label.text for label in built.labels})
        legend = [row.text for row in built.legend]
        self.assertIn(SHOWN, legend)
        self.assertIn("Restricciones declaradas bloqueadas por una edición fuera de Geoblender (1)",
                      legend)
        self.assertEqual(built.masks, "stale")
        self.assertIsNone(built.batch("no_fill", self.ov.ZONE), "sin máscaras al día no hay zonas")
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})

    def test_g_accepting_the_edit_unblocks_it_and_the_declaration_differs(self) -> None:
        """RF-015-11, RF-012-19: aceptar la edición con un motivo (``core_resolve_dataset``) desbloquea la
        tabla: la barra N vuelve a «Activa» y, como lo vigente es lo aceptado y las entidades no declaran
        lo mismo (aquí ninguna entidad respalda la fila de la prueba), avisa de que la declaración difiere
        de la de las entidades; compilar vuelve a poder y la superposición ya no avisa de nada bloqueado."""
        uid = self.rows("SELECT uid FROM gb_dataset WHERE name = 'des_decl'")[0][0]
        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset(
            "EXEC_DEFAULT", dataset_uid=uid, decision="ACCEPT", reason="La propiedad lo pide"),
            {"FINISHED"})
        self.project.refresh_header()
        item = self.chosen(CODE)
        self.assertEqual(item.state, "active")
        self.assertEqual(item.reason, "Retocada en QGIS", "lo aceptado es lo vigente")
        self.assertTrue(item.diverges, "ninguna entidad declara lo que hay: difiere")
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertEqual((self.view.selected.state, self.view.selected.diverges), ("active", True))
        texts = self.selected_layout().texts()
        self.assertNotIn("Bloqueada por una edición fuera de Geoblender", texts)
        self.assertIn("La declaración difiere de la de las entidades", " ".join(texts))
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        built = self.pump()
        self.assertEqual(built.masks, "current")
        self.assertNotIn("Restricciones declaradas bloqueadas", " ".join(row.text for row in built.legend))
        self.assertIsNotNone(built.batch("no_fill", self.ov.ZONE))
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        self.assertFalse(self.ov.enabled())

    def test_h_an_unreadable_table_does_not_break_the_lists(self) -> None:
        """RF-015-11 (T21): una fila de la tabla que ya no es una declarada (la edición de QGIS la dejó
        con un tipo que no existe) no tumba la lista de Restricciones…, la barra N ni la superposición:
        la declarada no se enseña (compilar sí se niega, con su mensaje) y las del proyecto, como siempre."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(f'UPDATE "{TABLE}" SET ctype = ?', ("no_existe",))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         ("2031-01-01T00:00:01.000Z", TABLE))
        finally:
            conn.close()
        self.assertEqual(self.panels.fill_constraints(self.project), 6)
        self.assertEqual([item.declared for item in self.view.constraints], [False] * 6)
        self.assertFalse(self.panels.read_selected(bpy.context) and self.view.selected.declared)
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        built = self.pump()
        self.assertNotIn(SHOWN, [row.text for row in built.legend])
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        des_panels = self.des_panels
        des_panels.refresh_choices(self.project)
        self.assertNotIn(des_panels.CONSTRAINT_ZONE + CODE, [item[0] for item in
                                                           des_panels.zone_items(None, None)])

    def test_z_disabling_geoblender_with_the_overlay_on_leaves_nothing(self) -> None:
        """Principio 8: con la superposición activa (y la declarada en pantalla), desactivar Geoblender
        quita el manejador, los avisos y el temporizador y deja la huella de Blender como al principio de
        la sesión."""
        ov = self.ov
        self.assertEqual(bpy.ops.geoblender.core_toggle_constraints_overlay(), {"FINISHED"})
        self.assertTrue(ov.drawing())
        blender_ext.release()
        self.assertFalse(ov.enabled() or ov.drawing() or ov.building())
        self.assertIsNone(ov.built())
        self.assertFalse(hasattr(bpy.types, PANEL))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
