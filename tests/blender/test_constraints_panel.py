# SPDX-License-Identifier: GPL-3.0-or-later
"""La restricción seleccionada (spec 012, T27; HU-012-2; RF-012-19; plan 012 §5.3.3, §5.3.4, D-30;
comprobación manual M4).

«Cargar en la vista» de las restricciones (``bl.scene.constraint_views``: un objeto ``CONSTRAINT``
por restricción, con el color de su tipo, en la colección de su dato) y lo que enseña la barra N
«Restricción» (``GEOBLENDER_PT_core_constraint``) del objeto seleccionado o, sin él, de la
restricción elegida en la ventana Restricciones…: su tipo, sus resguardos y su peso con su
insignia de tipo y su ámbito, la prioridad, el motivo, el decisor, la fecha, la decisión, su estado
en la versión activa y las cifras de su última verificación. Un proyecto por clase (ventana de
60 × 60 m con celdas de 2 m, V01 y V02, seis restricciones de seis tipos) y las pruebas, en el
orden de sus letras sobre el mismo estado:

- RF-012-19 (a): el tipo ``CONSTRAINT`` está en ``Object.geoblender.kind`` y en la rama
  «Constraints»; el cargador de ``core_constraint`` es el de la 012 y el menú contextual
  «Restricción ▾» (``GEOBLENDER_MT_core_context_constraint``) está disponible, con las órdenes que
  existen y la que aún no, desactivada.
- RF-012-19 (b): cargar en la vista las tres capas da un objeto por restricción en la colección de
  su dato, con el color de su tipo (los once distintos y ninguno el violeta de las intenciones), sus
  vértices en las coordenadas absolutas de la restricción y su uid; la vista no escribe nada en el
  proyecto ni cambia las máscaras; cerrar los pasos a mitad no deja nada.
- RF-012-19 (c, d): seleccionar un objeto lee su ficha del proyecto (nada se lee al dibujar) y la
  barra N enseña el tipo, los resguardos y el peso con su insignia y su ámbito, la prioridad, el
  motivo, el decisor, la fecha y su estado en la versión activa; otra versión activa o un
  resguardo cambiado la ponen al día; una restricción desactivada en la versión lo dice.
- RF-012-19, RF-010-06, RF-010-08 (e): con una verificación hecha, la barra N enseña sus cifras
  (las de la última verificación vigente de la versión, por final, con el veredicto), y «Elemento
  activo» y «Cifras de la selección» de la 010 las enseñan también.
- RF-012-19 (f): sin objeto de restricción activo, la barra N es de la elegida en la ventana
  Restricciones…; «Editar la restricción…» abre la ventana en la restricción activa.
- Principio 8 (z): desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw
from tests.support.trees import remove_tree

ENTRY = "012"
KIND = "CONSTRAINT"
PREFIX = "core_constraint"
PANEL = "GEOBLENDER_PT_core_constraint"
CONTEXT_MENU = "GEOBLENDER_MT_core_context_constraint"
LOAD = "geoblender.core_load_into_view"
EDIT = "geoblender.core_edit_constraints"
VIEW_PROPERTY = "geoblender_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
REASON = "Prueba de la restricción seleccionada"
PERSON = "Samuel (IMGA)"
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
LAYER_OF = {"legal_limit": "polygon", "action_perimeter": "polygon", "untouchable": "polygon",
            "no_cut": "polygon", "requires_access": "line", "avoid": "point"}
VIOLET = (0.7, 0.25, 0.9)  # el de las intenciones del cliente: ningún tipo lo repite
CHECK_NAME = "Diseño de la prueba"
START_M, FINAL_M = 100.0, 96.0  # la verificación: toda la ventana rebajada 4 m


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


class ConstraintPanelTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 y seis restricciones, para
    toda la clase (las pruebas, en el orden de sus letras: cada una parte de lo que dejó la
    anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r27-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.views = _module("bl.scene.views")
        cls.versions = _module("bl.scene.versions")
        cls.constraint_views = _module("bl.scene.constraint_views")
        cls.panels = _module("bl.ui.constraint_panels")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.core_props = _module("bl.props.core")
        cls.mesh = _module("bl.scene.mesh")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.cparams = _module("core.constraints.params")
        cls.styles = _module("core.constraints.styles")
        cls.masks_store = _module("gis.masks.store")
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
    def write_start(cls) -> str:
        """La superficie de partida: una rejilla del proyecto llana a :data:`START_M` m, como la
        deja «Rejilla del proyecto desde un MDT» (``gis.resample``); el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Partida"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster("Partida", _module("gis.raster").Raster(
                grid, np.full((grid.nrows, grid.ncols), START_M, dtype=np.float64), crs, vertical))
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

    @property
    def origin(self) -> Any:
        return self.project.origin

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que ver no cambia)."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def stored(self) -> dict[str, Any]:
        """Las restricciones del proyecto por su tipo."""
        with self.project.read() as conn:
            return {item.ctype.value: item for item in self.cstore.read_constraints(conn)}

    def loaded(self) -> dict[str, Any]:
        """Los objetos ``CONSTRAINT`` de la escena por el uid de su restricción."""
        prop = self.constraint_views.CONSTRAINT_PROPERTY
        return {obj[prop]: obj for obj in bpy.data.objects
                if obj.geoblender.kind == KIND and prop in obj.keys()}

    def load_all(self) -> None:
        for layer in ("polygon", "line", "point"):
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=f"{PREFIX}_{layer}"),
                             {"FINISHED"})

    def choose(self, ctype: str) -> Any:
        """Selecciona y activa el objeto de la restricción de tipo ``ctype`` y lee su ficha como
        lo hace Blender al cambiar el objeto activo."""
        obj = self.loaded()[self.stored()[ctype].uid]
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        return obj

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def panel_texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    def parameters(self) -> dict[str, str]:
        """Los parámetros de la restricción de la barra N: nombre → su texto."""
        return {line.name: line.text for line in self.view.selected.parameters}

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_kind_the_loader_and_the_context_menu(self) -> None:
        """RF-012-19, D-30, D-38: ``CONSTRAINT`` es un tipo de ``Object.geoblender`` con su rama
        «Constraints»; el cargador de ``core_constraint`` (las tres capas) es el de la 012; la
        barra N «Restricción» es un panel real de la Vista 3D y el menú contextual
        «Restricción ▾» de la entrada «012» está disponible con las órdenes que existen
        (Restricciones…, Ver restricciones, Buscar intocables, Decisión de la propiedad) y
        «Abrir en QGIS», que aún no, desactivada."""
        self.assertIn(KIND, [item[0] for item in self.core_props.OBJECT_KINDS])
        self.assertEqual(self.views.BRANCHES[KIND], (("constraints", "Constraints"),))
        for layer in ("polygon", "line", "point"):
            loader = self.views.loader_for(f"{PREFIX}_{layer}")
            self.assertEqual((loader.prefix, loader.kind), (PREFIX, KIND))
        self.assertEqual(self.views.loader_for("core_intention").kind, "CLIENT_INTENTION")
        cat = self.commands.catalog()
        self.assertEqual(cat.contexts[KIND].id, CONTEXT_MENU)
        self.assertEqual(cat.commands[CONTEXT_MENU].entry, ENTRY)
        self.assertEqual(len(cat.contexts[KIND].icons), 2)
        self.assertTrue(self.commands.is_available(CONTEXT_MENU))
        menu = getattr(bpy.types, CONTEXT_MENU)
        self.assertEqual(menu.bl_label, "Restricción")
        layout = draw(menu, bpy.context)
        shown = {item.target: item for item in layout.items if item.kind == "operator"}
        for idname in (EDIT, "geoblender.core_toggle_constraints_overlay",
                       "geoblender.core_find_untouchables", "geoblender.core_show_decisions"):
            with self.subTest(orden=idname):
                self.assertTrue(shown[idname].enabled, idname)
        self.assertFalse(shown["geoblender.gis_open_in_qgis"].enabled)
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_category),
                         ("VIEW_3D", "UI", "Restricción"))
        self.assertIn(panel, self.panels.classes)

    def test_b_load_one_object_per_constraint_with_the_colour_of_its_type(self) -> None:
        """RF-012-19, RF-012-18: «Cargar en la vista» de las tres capas da un objeto ``CONSTRAINT``
        por restricción en la colección de su dato, con el color de su tipo (el de QGIS y el de la
        superposición), alambre, sus vértices en las coordenadas absolutas de la restricción (el
        punto, con su cruz) y su uid; la vista no escribe nada en el proyecto ni cambia el
        estado de las máscaras; el color de los once tipos es distinto y ninguno es el violeta de
        las intenciones; cerrar los pasos a mitad no deja nada y descargar quita los objetos."""
        views, cv = self.views, self.constraint_views
        saved = self.stored()
        files, operations = self.files(), self.operations()
        colours = {tuple(cv.constraint_color(ctype)) for ctype in self.cmodel.ConstraintType}
        self.assertEqual(len(colours), len(self.cmodel.ConstraintType))
        for colour in colours:
            self.assertGreater(sum((a - b) ** 2 for a, b in zip(colour[:3], VIOLET)), 0.05)
        meshes = len(bpy.data.meshes)
        steps = views.load_steps(bpy.context, self.project, [f"{PREFIX}_polygon"])
        for _ in range(3):
            next(steps)
        self.assertGreater(len(bpy.data.meshes), meshes)
        steps.close()
        self.assertEqual(len(bpy.data.meshes), meshes)
        self.assertEqual(self.loaded(), {})
        self.load_all()
        self.assertEqual((self.files(), self.operations()), (files, operations))
        loaded = self.loaded()
        self.assertEqual(set(loaded), {item.uid for item in saved.values()})
        for ctype, item in saved.items():
            with self.subTest(tipo=ctype):
                obj = loaded[item.uid]
                (dataset_uid,) = self.rows("SELECT uid FROM gb_dataset WHERE name = ?",
                                           f"{PREFIX}_{LAYER_OF[ctype]}")[0]
                self.assertEqual(obj.geoblender.dataset_uid, dataset_uid)
                self.assertEqual(obj.geoblender.kind, KIND)
                self.assertEqual(obj.display_type, "WIRE")
                self.assertEqual(tuple(round(value, 5) for value in obj.color[:3]),
                                 tuple(round(value, 5) for value in cv.constraint_color(
                                     item.ctype)[:3]))
                self.assertIn(item.name, obj.name)
                self.assertIn(item.ctype.label("es"), obj.name)
                self.assertEqual(obj.users_collection[0].get("geoblender_key"),
                                 f"dataset:{dataset_uid}")
                world = self.mesh.mesh_vertices_world(obj.data, self.origin)
                self.assertTrue(np.all(world[:, 2] == float(self.origin.z0)))
                wanted = np.vstack([ring_ for part in item.parts for ring_ in part])
                if item.kind.value == "point":  # el punto, primer vértice; la cruz, las aristas
                    self.assertEqual((len(world), len(obj.data.edges)), (5, 4))
                    np.testing.assert_allclose(world[:1, :2], wanted, atol=1e-4)
                else:
                    drawn = {tuple(np.round(row, 3)) for row in world[:, :2]}
                    for point in wanted:
                        self.assertIn(tuple(np.round(point, 3)), drawn)
        self.assertEqual(len({obj.users_collection[0].name for obj in loaded.values()}), 3)
        # Cargar de nuevo no duplica y descargar una capa quita solo sus objetos.
        before = len(self.loaded())
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=f"{PREFIX}_point"),
                         {"FINISHED"})
        self.assertEqual(len(self.loaded()), before)

    def test_c_selecting_one_shows_its_type_buffers_reason_and_state(self) -> None:
        """RF-012-19: seleccionar el objeto de la torre lee su ficha del proyecto (al cambiar el
        objeto activo, no al dibujar) y la barra N enseña su tipo, sus resguardos y su peso con
        su insignia de tipo y su ámbito («V01: — · proyecto: 4 m [HIP]»), la prioridad, el
        motivo, el decisor, la fecha, su estado en la versión activa y el botón de editarla; sin
        decisión enlazada no dibuja la línea; con un objeto de otro tipo, su ficha; sin ningún
        objeto de restricción activo, la barra N no se ofrece."""
        panel = getattr(bpy.types, PANEL)
        self.assertFalse(panel.poll(bpy.context))
        self.assertNotIn(self.panels.on_version_changed, self.versions.listeners())
        obj = self.choose("untouchable")
        self.assertTrue(panel.poll(bpy.context))
        self.assertIn(self.panels.on_version_changed, self.versions.listeners())  # solo ahora
        selected = self.view.selected
        tower = self.stored()["untouchable"]
        self.assertEqual((selected.uid, selected.code, selected.ctype, selected.kind,
                          selected.state, selected.priority, selected.name),
                         (tower.uid, tower.code, "untouchable", "polygon", "active", 3,
                          "Torre 132 kV"))
        self.assertEqual((selected.reason, selected.decided_by, selected.decided_on),
                         (f"{REASON}: Torre 132 kV", PERSON, "01/11/2026"))
        parameters = self.parameters()
        self.assertIn("Resguardo hacia fuera", parameters)
        self.assertRegex(parameters["Resguardo hacia fuera"],
                         r"^V01: .* · proyecto: .*4.* m \[HIP\]")
        self.assertTrue(all(line.registered for line in selected.parameters))
        layout = draw(panel, bpy.context)
        texts = layout.texts()
        self.assertTrue(any("Intocable" in text and "Torre 132 kV" in text for text in texts),
                        texts)
        self.assertIn("Activa", texts)
        self.assertTrue(any(text.startswith("Motivo: ") and "Torre 132 kV" in text
                            for text in texts))
        self.assertIn(f"Decidida por: {PERSON}", texts)
        self.assertIn("Fecha de la decisión: 01/11/2026", texts)
        self.assertIn("Prioridad: 3", texts)
        self.assertFalse(any(text.startswith("Decisión enlazada") for text in texts))
        self.assertTrue(any(text.startswith("Resguardo hacia fuera: V01:") for text in texts))
        edit = [item for item in layout.items if item.target == self.panels.COMPLETE_CONSTRAINT]
        self.assertEqual(len(edit), 1)
        self.assertEqual(edit[0].properties.uid, tower.uid)
        # Otro objeto, otra ficha; un objeto que no es de restricción, ninguna.
        self.choose("avoid")
        self.assertEqual((self.view.selected.ctype, self.view.selected.kind),
                         ("avoid", "point"))
        self.assertIn("Peso de la zona preferible no afectar", self.parameters())
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()
        self.assertFalse(panel.poll(bpy.context))
        self.assertEqual(self.view.selected.uid, "")
        self.assertIsNotNone(obj)

    def test_d_the_state_follows_the_active_version_and_the_parameters(self) -> None:
        """RF-012-19, RF-009-29: desactivarla en V01 la deja «Inactiva en V01» (en V02 sigue
        activa: otra versión activa pone al día la barra N); un resguardo cambiado en la versión
        sale en la barra N con su valor propio; sin versión activa, el estado es el del proyecto;
        la restricción que se borró de la capa deja la barra N vacía."""
        self.choose("no_cut")
        self.assertEqual(self.view.selected.state, "active")
        store = _module("core.params").ParameterStore(self.project)
        code = self.codes["no_cut"]
        with self.project.write_transaction() as conn:
            store.change(conn, self.cparams.active_key(code), value=False, kind="ADOPTADO",
                         source="Criterio de la prueba", source_kind="person",
                         decided_by=PERSON, reason=REASON, version=self.v01.uid)
            store.change(conn, self.cparams.buffer_out_key(code), value=BUFFER_M + 3.0,
                         kind="HIPÓTESIS", source="Criterio de la prueba", source_kind="person",
                         decided_by=PERSON, reason=REASON, version=self.v01.uid)
        self.project.refresh_header()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertEqual(self.view.selected.state, "inactive")
        self.assertIn("Inactiva en V01", self.panel_texts())
        self.assertRegex(self.parameters()["Resguardo hacia fuera"], r"^V01: .*7.* m")
        self.set_active(self.v02)
        self.assertEqual(self.view.selected.state, "active")
        self.assertIn("Activa", self.panel_texts())
        self.assertRegex(self.parameters()["Resguardo hacia fuera"],
                         r"^V02: .* · proyecto: .*4.* m")
        self.set_active(self.v01)
        self.assertEqual(self.view.selected.state, "inactive")
        self.set_active(None)
        self.assertEqual(self.view.selected.state, "active")
        self.assertIn("Activa", self.panel_texts())
        self.set_active(self.v01)

    def test_e_the_figures_of_the_last_verification(self) -> None:
        """RF-012-19, RF-010-06, RF-010-08: sin verificación, la barra N lo dice; con una hecha
        en V01 (toda la ventana rebajada 4 m: la torre no cumple), enseña su nombre, de cada final
        su superficie y su veredicto y las cifras registradas de la torre con su insignia de tipo
        ([CAL]) y su unidad, las mismas del proyecto; la de otra versión no cuenta; «Elemento
        activo» y «Cifras de la selección» de la 010 las enseñan también; un límite legal suma
        las de su banda hacia dentro."""
        self.choose("untouchable")
        texts = self.panel_texts()
        self.assertIn("Sin verificación en V01", texts)
        self.assertEqual([line.text for line in self.view.selected_lines], [
            "Sin verificación en V01"])
        steps = self.verify.verify_project_steps(
            self.project, version=self.v01.uid, name=CHECK_NAME,
            start=self.surfaces.SurfaceRef(dataset=self.write_start(), label="Partida"),
            finals=[self.surfaces.SurfaceRef(elevation=FINAL_M, label="Rebajada")],
            budget_s=0.05)
        for _ in steps:
            pass
        self.project.refresh_header()
        self.assertTrue(self.panels.read_selected(bpy.context))
        tower = self.stored()["untouchable"]
        table = self.verify.dataset_locator(self.verify.TABLE, CHECK_NAME, "V01")
        rows = self.rows(f'SELECT "final", quantity, value, note FROM "{table}" WHERE zone = ? '
                         "ORDER BY fid", tower.code)
        self.assertTrue(rows, "la verificación no escribió la torre")
        by_quantity = {quantity: (value, note) for _final, quantity, value, note in rows}
        self.assertEqual(by_quantity["verdict"][1], "fails")
        self.assertEqual(by_quantity["counted_m3"][1], "any")
        counted_m3 = by_quantity["counted_m3"][0]
        self.assertGreater(counted_m3, 0.0)
        figures_mod = _module("core.provenance.figures")
        stored = [figures_mod.FigureRecord.from_row(row) for row in self.rows(
            f"SELECT {figures_mod.RECORD_COLUMNS} FROM gb_figure AS f WHERE operation_uid IN "
            "(SELECT uid FROM gb_operation WHERE op_type = 'res.verify_constraints') AND "
            "json_extract(scope, '$.zone') = ? ORDER BY fid", tower.code)]
        self.assertEqual({figure.key for figure in stored}, {
            "res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2",
            "res.check_nodata_area_m2"})
        wanted = [f"[CAL] {figure.text(language='es')}" for figure in stored]
        formatted = _module("core.i18n").format_number(counted_m3, 0)
        lines = [(line.text, line.alert) for line in self.view.selected_lines]
        texts = [text for text, _alert in lines]
        self.assertEqual(texts[0], f"Última verificación en V01: {CHECK_NAME}")
        self.assertEqual(texts[1], f"«Rebajada»: No cumple · {formatted} m³ de movimiento")
        self.assertTrue(lines[1][1])  # no cumple, en alerta
        self.assertEqual(texts[2:], wanted)
        self.assertTrue(any("m³" in text and "= " in text for text in wanted), wanted)
        joined = " ".join(self.panel_texts())
        for text in texts:
            self.assertIn(text, joined)
        # «Elemento activo» y «Cifras de la selección» (010): las mismas líneas.
        view_panels = self.view_panels
        manager = bpy.context.window_manager
        self.assertTrue(view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(manager, view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(texts) - 1:],
                         [f"Intocable · Torre 132 kV", *texts])
        self.assertEqual(view_panels.fill_selection_figures(bpy.context), 1)
        selection = [row.text for row in getattr(
            manager, view_panels.WINDOW_MANAGER_PROPERTY).selection]
        self.assertEqual(selection[-len(texts) - 1:], [f"Intocable · Torre 132 kV", *texts])
        # El límite legal: su zona y su banda hacia dentro.
        self.choose("legal_limit")
        legal = [line.text for line in self.view.selected_lines]
        self.assertGreater(len([text for text in legal if text.startswith("[CAL]")]), 4)
        self.assertTrue(all(text.startswith("[CAL]") or "«Rebajada»" in text or "Última" in text
                            for text in legal), legal)
        # Una verificación de otra versión no cuenta.
        self.set_active(self.v02)
        self.assertEqual([line.text for line in self.view.selected_lines],
                         ["Sin verificación en V02"])
        self.set_active(self.v01)

    def test_f_the_window_choice_without_an_object_and_edit_opens_on_the_active(self) -> None:
        """RF-012-19, D-30, PC §3.7: sin objeto de restricción activo, la barra N es de la
        restricción elegida en la ventana Restricciones… (con las cifras de su última
        verificación); «Editar la restricción…» abre la ventana en la restricción del objeto
        activo."""
        panel = getattr(bpy.types, PANEL)
        bpy.context.view_layer.objects.active = None
        self.view_panels.on_active_changed()
        self.assertFalse(panel.poll(bpy.context))
        with mock.patch.object(_module("bl.ops.core_constraints"), "_call_panel",
                               return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.core_edit_constraints(), {"FINISHED"})
        view = self.view
        order = [item.ctype for item in view.constraints]
        self.assertEqual(order[:4], ["legal_limit", "action_perimeter", "untouchable", "no_cut"])
        view.item_index = order.index("avoid")
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((view.selected.ctype, view.selected.name), ("avoid", "Árbol"))
        self.assertTrue(any(line.text.startswith("Última verificación en V01")
                            for line in view.selected_lines))
        self.choose("untouchable")
        view.item_index = 0
        with mock.patch.object(_module("bl.ops.core_constraints"), "_call_panel",
                               return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.core_edit_constraints(), {"FINISHED"})
        self.assertEqual(view.constraints[view.item_index].ctype, "untouchable")
        self.assertEqual(view.selected.ctype, "untouchable")

    def test_g_unloading_the_objects_leaves_the_choice_of_the_window(self) -> None:
        """RF-012-19, D-30: descargar de la vista las tres capas quita los objetos y no escribe
        nada en el proyecto; sin objeto, la barra N vuelve a ser de la restricción elegida en la
        ventana y, sin la ventana leída, de nadie."""
        files, operations = self.files(), self.operations()
        self.choose("untouchable")
        view = self.view
        view.item_index = [item.ctype for item in view.constraints].index("no_cut")
        self.assertEqual(view.selected.ctype, "untouchable")  # el objeto manda sobre la ventana
        uids = [row[0] for row in self.rows(
            "SELECT uid FROM gb_dataset WHERE name IN ('core_constraint_polygon', "
            "'core_constraint_line', 'core_constraint_point')")]
        self.assertEqual(self.views.unload_datasets(uids), 6)
        self.assertEqual(self.loaded(), {})
        self.view_panels.on_active_changed()
        panel = getattr(bpy.types, PANEL)
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((view.selected.ctype, view.selected.uid),
                         ("no_cut", view.constraints[view.item_index].uid))
        view.constraints.clear()
        self.view_panels.on_active_changed()
        self.assertFalse(panel.poll(bpy.context))
        self.assertEqual((view.selected.uid, len(view.selected_lines)), ("", 0))
        self.assertNotIn(self.panels.on_version_changed, self.versions.listeners())
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_z_disabling_geoblender_leaves_nothing(self) -> None:
        """Principio 8: desactivar Geoblender quita la barra N, la escucha de la ficha y los
        cargadores, y la huella de Blender vuelve a la del principio de la sesión."""
        blender_ext.release()
        self.assertFalse(hasattr(bpy.types, PANEL))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
