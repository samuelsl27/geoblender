# SPDX-License-Identifier: GPL-3.0-or-later
"""«Accesibilidad de las pistas…» en Blender (spec 017, T30; HU-017-3; RF-017-29, RF-017-24, RF-017-25, RF-017-04, RF-017-30, RF-015-28, RF-015-29; plan 017 §5.3.3 y §5.5; comprobación manual M3).

:class:`GEOBLENDER_OT_des_road_access` (``geoblender.des_road_access``) calcula con ``design.steps.access_run`` la operación ``des.road_access`` de la versión activa: de una **superficie del proyecto o de
la versión** y de los puntos de entrada de una capa, qué celdas se alcanzan a pie (la pendiente y el ancho transitables), las cotas mínima y máxima alcanzables —también sobre la final de una cantera—
y qué tramos de berma, plataformas y zonas «requiere acceso» quedan comunicados. Su diálogo pide el nombre, la superficie (la última de la cadena, por defecto), la capa de los puntos de entrada y los
tres umbrales, **cada uno con su tipo** (HIPÓTESIS sin valor por defecto: D-17); tras Calcular, la ventana de Crear enseña el resumen y **las listas** de bermas, plataformas y zonas, comunicadas o no, cada
una con su lugar y su «Ir a». Calcular, Crear, Cancelar y Esc son los de las demás órdenes (``_CalculateAndCreate``): nada se registra hasta Crear. Es el modelo de ``milestone_road_ops.py`` (T29b): aprovecha el
proyecto de ``test_platform_ops.py`` (60 × 60 m con celdas de 2 m, V01 y V02, el límite legal, el perímetro y un sector con la búsqueda cerrada) y le añade lo que mira la accesibilidad: dos terrenos
(``Suave``, de ``100 + 0,02·(x + y)``, y ``Muro``, que sube 30 m desde y = 36 m: una pared que separa el sur del norte), una capa con el punto de entrada **en el norte**, otra con un punto fuera de la
rejilla, las rejillas de cotas de berma de V01 (una banda al sur y otra al norte, escritas por una operación de prueba), la plataforma «Carga» (al sur, creada con la orden real) y dos zonas «requiere acceso»
(una al sur y otra al norte, de la 012). Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-017-29, RF-015-28 (a): la orden es real, del catálogo (entrada 017, entregada); sus propiedades tienen nombre y descripción; el diálogo propone el nombre, la capa y la superficie (la última de la cadena) y
  dibuja sus campos, con el tipo de cada umbral.
- RF-017-24, RF-017-04 (b): la petición del diálogo es la que arma ``AccessRequest``, con coma decimal y los umbrales vacíos sin cifra.
- RF-017-24, RF-017-25, RF-015-03, RF-015-02 (c): Calcular sobre ``Suave`` (todo se alcanza) deja el cálculo abierto, con su resumen y las tres listas, y nada en el proyecto; Crear registra ``des.road_access``,
  sus cifras, la entidad y los parámetros de la persona y encadena la capa de entidades.
- RF-017-25, RF-017-24 (d): sobre ``Muro`` desde el norte, la lista dice cada tramo de berma, la plataforma y cada zona **comunicados o no**, con su lugar y su «Ir a», las que no, primero y en alerta.
- RF-015-29, RF-017-30, RF-017-04, RF-015-08 (e): Esc a mitad, Cancelar la confirmación y lo que se rechaza no dejan nada (0 transacciones). **Esc no depende del reloj** (T39, E-2 de la verificación
  única): con un paso de una unidad por evento y un reloj de mentira en los dos módulos que miden el presupuesto, los eventos del cálculo son los mismos con cualquier ritmo (e, segunda prueba).
- RF-017-29, RF-015-28, RF-009-05, RF-009-21 (f): la orden sale desactivada con su motivo con el proyecto en solo lectura, con la versión activa no editable y sin versión activa.
- Principio 8 (z): desactivar Geoblender quita la orden y no deja nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
import uuid
from datetime import date
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

ACCESS = "geoblender.des_road_access"
ACCESS_CLASS = "GEOBLENDER_OT_des_road_access"
ACCESS_TYPE = "des.road_access"
PERSON = platform_ops.PERSON
REASON = "Prueba de la orden «Accesibilidad de las pistas…»"
ENTRIES = "gis_fea_accesos"
OUTSIDE = "gis_fea_accesos_fuera"
ENTRY_ROWS = (("Entrada norte", (10.0, 52.0)),)
OUTSIDE_ROWS = (("Entrada fuera", (-20.0, 30.0)),)
WALL_M = 36.0
"""La y local desde la que sube el terreno ``Muro``."""
WALL_RISE_M = 30.0
PROBE = "des.probe_access_ops"
"""El tipo de operación de prueba que escribe los datos de una cantera de la 014 y sus bermas en V01 (solo desde esta prueba)."""
QUARRY = "Cantera"
EXPLOITATION, FINAL, BERMS_DATASET = "des_exp_cantera", "des_fin_cantera", "des_brm_cantera"
FINAL_RISE_M = 20.0
"""Lo que la superficie final de la cantera está más alta que la de explotación."""
SOUTH_BERM_M, NORTH_BERM_M = 100.3, 130.3
SOUTH_BAND, NORTH_BAND = (10.0, 10.0, 50.0, 20.0), (10.0, 40.0, 50.0, 50.0)
"""Las dos bandas de berma (local: izquierda, abajo, derecha, arriba): 20 × 5 celdas de 2 m = 400 m² cada una."""
SOUTH_ZONE, NORTH_ZONE = ("Zona del camino", (40.0, 10.0, 50.0, 20.0)), ("Zona de la balsa", (40.0, 40.0, 50.0, 50.0))
"""Las zonas «requiere acceso» (local): 5 × 5 celdas = 100 m² cada una."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
FAST_TICK_S, SLOW_TICK_S = 1e-7, 1.0
"""Los dos relojes de mentira de la prueba del reloj: lo que avanza cada lectura (muy rápido: 0,1 µs; muy lento: 1 s)."""
HIDDEN = ("confirm", "in_steps")
PROPERTIES = {  # la propiedad → su nombre y su descripción (msgid en inglés; en español al registrarse)
    "name": ("Name", "Name of the accessibility, unique in the active version"),
    "surface": ("Surface", "Surface the accessibility is calculated on: a grid of the project or of the active version; by default, the last of the chain of entities of the version"),
    "layer": ("Layer of the entry points", "Layer of points of the project with the entry points: where people or machines get onto the surface"),
    "name_field": ("Name field", "Field of the layer with the name of each entry point (empty: its number (fid))"),
    "walk_slope": ("Maximum walkable gradient (%)", "Local gradient above which a cell cannot be walked, in per cent; a hypothesis without default value"),
    "walk_width": ("Minimum walkable width (m)", "Narrowest passage that can be walked, in metres, between cell centres; a hypothesis without default value"),
    "min_berm_area": ("Minimum area of a berm stretch (m²)", "Smallest berm stretch that is listed, in square metres; a hypothesis without default value"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción (las ocultas, que pone quien lanza la orden, no los llevan)."""
THRESHOLDS = {"walk_slope": "12", "walk_width": "4", "min_berm_area": "100"}
"""Los umbrales tecleados como los teclea una persona (**solo de la prueba**: la orden no propone ninguno)."""
DEFAULTS: dict[str, Any] = {  # lo que dibuja el diálogo con un valor de cada propiedad (para los ``draw`` simulados)
    "name": "Accesibilidad abierta", "surface": "", "layer": ENTRIES, "name_field": "", "walk_slope": "", "walk_width": "", "min_berm_area": "", "confirm": False, "in_steps": False}


def smooth() -> np.ndarray:
    """El terreno ``Suave``: ``100 + 0,02·(x + y)`` en los centros de celda (el 2,8 % de pendiente: se anda por todo él)."""
    x, y = platform_ops.centers()
    return 100.0 + 0.02 * (x + y)


def wall() -> np.ndarray:
    """El terreno ``Muro``: el suave con 30 m más desde ``y = 36``: una pared de 30 m en una celda de 2 que ninguna pendiente transitable pasa."""
    _x, y = platform_ops.centers()
    return smooth() + np.where(y > WALL_M, WALL_RISE_M, 0.0)


def never(request: Any) -> Any:  # solo declara que se repite sola
    raise AssertionError("esta prueba no recalcula")


class RoadAccessOpsTest(platform_ops.CreatePlatformTest):
    """El proyecto de la prueba de la plataforma, con lo que necesita la accesibilidad (los terrenos, las capas, las bermas, una plataforma y dos zonas). Las pruebas de la plataforma no se repiten."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smooth_surface = cls.write_grid("Suave", smooth())
        cls.wall_surface = cls.write_grid("Muro", wall())
        for name, rows in ((ENTRIES, ENTRY_ROWS), (OUTSIDE, OUTSIDE_ROWS)):
            cls.write_points(name, rows)
        cls.layers_before = {name: cls.table_state(name) for name in (ENTRIES, OUTSIDE)}
        cls.write_quarry()
        cls.write_zones()
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01 con las zonas «requiere acceso»
        for _step in platform_ops._module("design.entity_store").after_entity_change(cls.project, cls.v01.uid):  # la declaración (vacía) ya consumida por las máscaras: crear la plataforma no las recompila
            pass
        cls.refresh()
        platform = {"name": platform_ops.LOADING, "layer": platform_ops.LAYER, "feature": platform_ops.LOADING, "start": cls.ground, "edge_angle": "35", "reach": "10", "in_steps": False}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **platform) == {"FINISHED"}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False) == {"FINISHED"}  # «Carga», al sur: PLT-001, la única de la cadena
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_access_choices(cls.project)

    @classmethod
    def write_points(cls, name: str, rows: tuple[Any, ...]) -> None:
        """La capa de puntos ``name`` con su campo ``nombre``, como la deja la importación de la 006."""
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),)
        parts = tuple(((platform_ops.path((point,)),),) for _name, point in rows)
        layer = vector.FeatureLayer("point", tuple(range(1, len(rows) + 1)), parts, columns, {"nombre": tuple(row[0] for row in rows)})
        records = gis_store.feature_rows(layer, srs)
        handle = platform_ops._module("core.provenance.operations").begin_operation(cls.project, platform_ops.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, "nombre" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES (?, ?, ?)', records)
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                                                                input_uid=None, immutable=False),), message="Capa de puntos de entrada de la prueba")

    @classmethod
    def table_state(cls, name: str) -> tuple[Any, ...]:
        """Una capa como está: su registro y todo el contenido de su tabla."""
        with cls.project.read() as conn:
            record = conn.execute("SELECT uid, status, content_sha256 FROM gb_dataset WHERE name = ?", (name,)).fetchall()
            table = conn.execute(f'SELECT * FROM "{name}" ORDER BY fid').fetchall()
        return record, table

    @classmethod
    def write_quarry(cls) -> None:
        """Lo que una cantera de la 014 deja en V01, escrito por una operación de prueba de ``des``: las rejillas de cotas de berma (``des_brm_cantera``: la banda del sur a 100,3 m y la del norte a
        130,3 m; ``NaN`` fuera) y sus dos superficies, la de explotación (``des_exp_cantera``: la de ``Suave``) y la final (``des_fin_cantera``: 20 m más alta)."""
        dprov, store = platform_ops._module("design.provenance"), platform_ops._module("design.store")
        contract, gis = platform_ops._module("core.provenance.contract"), platform_ops._module("gis")
        probe = dprov.OperationType(PROBE, "Quarry of the tests", (dprov.BERMS_GRID, dprov.EXPLOITATION_GRID, dprov.FINAL_GRID), ())
        cls.enterClassContext(mock.patch.object(dprov, "OPERATION_TYPES_BY_NAME", MappingProxyType({**dprov.OPERATION_TYPES_BY_NAME, PROBE: probe})))
        contract.register_operation(probe.definition(never))
        cls.addClassCleanup(contract.unregister_operation, PROBE)
        x, y = platform_ops.centers()
        levels = np.full(x.shape, np.nan)
        for box, level in ((SOUTH_BAND, SOUTH_BERM_M), (NORTH_BAND, NORTH_BERM_M)):
            left, bottom, right, top = box
            levels[(x > left) & (x < right) & (y > bottom) & (y < top)] = level
        grid = platform_ops._module("gis.grid").project_grid(cls.project.record.window, float(cls.project.record.grid_step_m))
        crs, vertical = platform_ops._module("gis.store").project_references(cls.project)
        begun = store._start(cls.project, PROBE, QUARRY, cls.v01, None, {"name": QUARRY}, (), (), None)
        with store.design_writer(cls.project, PROBE, QUARRY, version=cls.v01.uid) as writer:
            for family, values in ((dprov.BERMS_GRID, levels), (dprov.EXPLOITATION_GRID, smooth()), (dprov.FINAL_GRID, smooth() + FINAL_RISE_M)):
                for _unit in writer.grid_steps(family, gis.Raster(grid, values, crs, vertical)):
                    pass
            writer.commit(begun, message="Cantera de la prueba de la accesibilidad")

    @classmethod
    def write_zones(cls) -> None:
        """Las dos zonas «requiere acceso» de la 012 (una al sur y otra al norte), como las deja «Restricciones…»."""
        m, kinds = cls.cmodel, cls.cmodel.GeometryKind

        def row(name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(uid=uuid.uuid4().hex, code="", name=name, ctype=m.ConstraintType.REQUIRES_ACCESS, kind=kinds.POLYGON, parts=((platform_ops.ring(box),),), priority=0,
                                reason=f"{REASON}: {name}", decided_by=PERSON, decided_on=date(2026, 11, 21), decision_uid=None, intention_uid=None, source_input=None,
                                source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        declaration = cls.cprov.ParamDeclaration(values={m.ConstraintParam.BUFFER_OUT: 0.0, m.ConstraintParam.ACTIVE: True}, source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, [row(*SOUTH_ZONE), row(*NORTH_ZONE)], params=declaration, srs_id=cls.project.record.crs_epsg)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def access(self) -> Any:
        return self.commands.registered_class(ACCESS)

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo: la accesibilidad de la capa de entradas (en el norte) sobre ``Suave``, con los umbrales de la prueba."""
        return {"name": "Accesibilidad abierta", "surface": self.smooth_surface, "layer": ENTRIES, **THRESHOLDS, "in_steps": False, **values}

    def calculate_access(self, form: dict[str, Any]) -> Any:
        """«Calcular» desde un guion: el cálculo abierto de la sesión."""
        self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **form), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def create_access(self, **values: Any) -> set[str]:
        """«Crear» el cálculo abierto desde un guion (la confirmación)."""
        return bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", confirm=True, in_steps=False, **values)

    def fake(self, **values: Any) -> Any:
        """El operador de mentira con todas las propiedades del diálogo (los de ``DEFAULTS`` y lo que se dé)."""
        properties = values.pop("properties", SimpleNamespace(is_property_set=lambda name: False))
        shown = {**DEFAULTS, "surface": self.smooth_surface, **values}
        return operator_self(self.access, report=lambda kind, text: None, properties=properties, **shown)

    def running_access(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.access) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{ACCESS} no está en marcha")
        return found[0]

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    def sections(self) -> dict[str, Any]:
        """Las listas de la ventana de crear por su título."""
        return {section.title: section for section in self.panels.access_sections()}

    def place(self, local: tuple[float, float], area_m2: float) -> tuple[str, str, str]:
        """El lugar de «Ir a» del punto local ``local`` y un área, como lo escribe la interfaz (texto sin pérdida)."""
        return self.panels.constraint_panels.place_of(platform_ops.WEST + local[0], platform_ops.SOUTH + local[1], area_m2)

    def parameter_row(self, code: str, param: str) -> tuple[Any, ...]:
        """La fila de la versión del parámetro ``param`` de la accesibilidad ``code``: valor, origen, tipo del origen y decisor."""
        ((value, source, kind, decider),) = self.rows(
            "SELECT value, source, source_kind, decided_by FROM gb_parameter WHERE key = ? AND scope = 'version' AND scope_uid = ?",
            f"des.access.{code.lower().replace('-', '_')}.{param}", self.v01.uid)
        return json.loads(value), source, kind, decider

    # --- a: la orden, el diálogo y la propuesta --------------------------------------------------

    def test_a_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-017-29, RF-015-28, RF-017-24, RF-017-25 (plan §5.3.3, §5.5; M3): «Accesibilidad de las pistas…» es una orden real de ``des.road_access`` con la puerta de la procedencia y los pasos con Esc;
        es de la entrada 017 (entregada por la T33b) y del catálogo, con su casa en Diseño ▸ Pistas y entidades; sus propiedades tienen nombre y descripción en español y los decimales son texto; su diálogo propone el nombre, la capa
        de entradas y **la superficie: la última de la cadena** (``des_psf_carga``); dibuja sus campos y **el tipo de cada umbral** (HIPÓTESIS: sin valor por defecto)."""
        cls = self.access
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertTrue(issubclass(cls, self.des_ops._ChainsEntityLayer))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options), (ACCESS, ACCESS_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        self.assertEqual(self.dprov.ACCESS_COMMAND, ACCESS)
        self.assertIn(ACCESS, self.dprov.OPERATION_TYPES_BY_NAME[ACCESS_TYPE].commands)
        command = self.commands.catalog().commands[ACCESS]
        self.assertEqual((command.label_es, command.entry, command.module, command.kind), ("Accesibilidad de las pistas…", "017", "des", "operator"))
        self.assertTrue(self.commands.is_available(ACCESS), "la entrada 017 está entregada (T33b): la orden se dibuja en su menú sin la nota «Disponible en …»")
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, set(PROPERTIES))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]), (self.i18n.translate("es", label), self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        for prop in HIDDEN:  # las pone quien la lanza: sin nombre ni descripción
            self.assertNotIn("name", cls.__annotations__[prop].keywords)
        for prop in ("walk_slope", "walk_width", "min_berm_area"):  # los decimales, en texto (regla 4: nada de float32)
            self.assertIs(cls.__annotations__[prop].function, bpy.props.StringProperty, prop)

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        proposal = self.fake(name="", layer="", surface="")
        self.assertEqual(cls.invoke(proposal, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Accesibilidad de las pistas…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(proposal.in_steps)
        self.assertEqual((proposal.name, proposal.layer), ("Accesibilidad 1", ENTRIES))
        carga_surface = self.dprov.dataset_name("psf", platform_ops.LOADING)
        self.assertEqual(self.panels.access_default_surface(), carga_surface, "la última de la cadena: la superficie que deja «Carga»")
        self.assertEqual(proposal.surface, carga_surface)
        self.assertIn(carga_surface, [item[0] for item in self.panels.surface_items(None, None)], "la superficie propuesta es de las que ofrece el diálogo")
        self.assertEqual([proposal.walk_slope, proposal.walk_width, proposal.min_berm_area], ["", "", ""], "ningún umbral se propone: no tienen valor por defecto (D-17)")
        given = self.fake(name="Mía", layer=ENTRIES, surface=self.wall_surface, properties=SimpleNamespace(is_property_set=lambda name: name in ("layer", "surface")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, given.layer, given.surface), ("Mía", ENTRIES, self.wall_surface), "lo dado no cambia")
        self.assertEqual([item[0] for item in self.panels.access_layer_items(None, None)], [ENTRIES, OUTSIDE], "las capas de puntos del proyecto")

        texts = draw(cls, bpy.context, **{**DEFAULTS, "surface": self.smooth_surface}).texts()
        for heading in ("Nombre", "Superficie", "Puntos de entrada", "Capa de los puntos de entrada", "Campo del nombre", "Pendiente máxima transitable (%)", "Ancho mínimo transitable (m)",
                        "Área mínima de un tramo de berma (m²)"):
            self.assertIn(heading, texts)
        self.assertEqual(len([text for text in texts if text == "HIPÓTESIS: sin valor por defecto, lo elige usted"]), 3, "los tres umbrales son hipótesis sin valor por defecto")
        self.assertEqual(self.dprov.ACCESS_COMMAND, cls.COMMAND)

    # --- b: la petición ----------------------------------------------------------------------------

    def test_b_the_request_of_the_dialog_and_what_it_cannot_arm(self) -> None:
        """RF-017-24, RF-017-04, RF-015-08 (plan §5.2.2, §5.3.3): lo pedido en el diálogo arma ``AccessRequest`` —la capa y su campo, la superficie y los umbrales con coma decimal— y los umbrales
        vacíos quedan sin cifra (los rechaza el cálculo, con su nombre: ninguno se elige por la persona); lo que el diálogo no puede armar se dice sin tocar nada."""
        asked = self.access._request(self.fake(name_field="nombre", walk_slope="12,5", walk_width=" 3 ", min_berm_area="150"))
        self.assertEqual((asked.name, asked.layer, asked.entries.name_field, asked.surface, asked.berms), ("Accesibilidad abierta", ENTRIES, "nombre", self.smooth_surface, None))
        self.assertEqual((asked.walk_slope_pct, asked.walk_width_m, asked.min_berm_area_m2), (12.5, 3.0, 150.0))
        empty = self.access._request(self.fake())
        self.assertEqual((empty.entries.name_field, empty.walk_slope_pct, empty.walk_width_m, empty.min_berm_area_m2), (None, None, None, None), "ningún valor se elige por la persona")
        for changes, text in (({"name": " "}, "Escriba el nombre de la accesibilidad"), ({"layer": "none"}, "Elija la capa de los puntos de entrada"), ({"layer": ""}, "Elija la capa de los puntos de entrada"),
                              ({"surface": "none"}, "Elija la superficie sobre la que se calcula la accesibilidad"), ({"surface": ""}, "Elija la superficie sobre la que se calcula la accesibilidad"),
                              ({"walk_slope": "abc"}, "«abc» no es un número (campo «Pendiente máxima transitable (%)»)"),
                              ({"walk_width": "1 m"}, "«1 m» no es un número"), ({"min_berm_area": "x"}, "«x» no es un número")):
            with self.subTest(cambios=changes):
                with self.assertRaises(ValueError) as caught:
                    self.access._request(self.fake(**changes))
                self.assertIn(text, str(caught.exception))

    # --- c: calcular y crear -----------------------------------------------------------------------

    def test_c_calculate_writes_nothing_and_create_registers_the_accessibility(self) -> None:
        """RF-017-24, RF-017-25, RF-015-03, RF-015-02 (M3): Calcular desde un guion sobre ``Suave`` (se anda por todo el terreno: se comunica todo) deja el cálculo abierto con su resumen —la
        cabecera con cuántos tramos de berma, plataformas y zonas se comunican, las cotas mínima y máxima alcanzables y el área— y **las tres listas con su lugar y su «Ir a»**, y nada en el proyecto. Crear
        registra ``des.road_access`` en V01 con su rejilla de lo alcanzable, sus tablas y sus cifras, la entidad ``ACC-001`` y los parámetros: los umbrales que escribió la persona quedan como suyos; **encadena
        la capa de entidades**; las capas de entrada no se tocan y la ventana de las listas se vacía."""
        self.refresh()
        before = self.state()
        held = self.calculate_access(self.form(name_field="nombre"))
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), (ACCESS_TYPE, "Accesibilidad abierta", "V01", "ACC-001"))
        self.assertEqual(self.state(), before, "calcular no registra nada ni deja un temporal")
        self.assertEqual(self.view.summary_title, "Accesibilidad «Accesibilidad abierta» en V01")
        summary, found = self.summary(), held.summary
        self.assertEqual(summary[0][0], found.notices[0].text("es"))
        self.assertEqual(summary[1][0], found.notices[1].text("es"))
        self.assertEqual(found.notices[0].values["berms_reached"], 2)
        self.assertEqual((found.notices[0].values["platforms_reached"], found.notices[0].values["zones_reached"]), (1, 2))
        self.assertEqual((len(found.berms), len(found.platforms), len(found.zones)), (2, 1, 2))
        self.assertTrue(summary[0][0].startswith("Accesibilidad «Accesibilidad abierta» (ACC-001): quedan comunicados 2 de 2 tramos de berma, 1 de 1 plataformas y 2 de 2 zonas"), summary[0])
        self.assertTrue(summary[1][0].startswith("Cotas alcanzables de "), summary[1])
        self.assertFalse(any(alert for _text, alert in summary), "todo se comunica: ningún aviso")
        self.assertAlmostEqual(found.z_min_m, 100.0 + 0.02 * (2.0 + 2.0), delta=0.5)  # las cotas del plano más baja y más alta que se alcanzan
        self.assertGreater(found.z_max_m, found.z_min_m)

        lists = self.sections()
        self.assertEqual(list(lists), ["Tramos de berma", "Plataformas", "Zonas «requiere acceso»"])
        berms, platforms, zones = lists.values()
        self.assertEqual((len(berms.rows), len(platforms.rows), len(zones.rows)), (2, 1, 2))
        self.assertEqual([berms.more, platforms.more, zones.more], [0, 0, 0])
        for section in lists.values():
            for row in section.rows:
                self.assertFalse(row.alert, row.text)
                self.assertIsNotNone(row.place, f"«Ir a»: {row.text}")
        self.assertTrue(all(row.text.endswith("comunicado") for row in berms.rows), [row.text for row in berms.rows])
        self.assertEqual(sorted((row.place for row in berms.rows)), sorted([self.place((30.0, 45.0), 400.0), self.place((30.0, 15.0), 400.0)]), "el centro de cada banda de berma, con su área")
        self.assertIn("Tramo de berma ", berms.rows[0].text)
        self.assertIn(f"«{BERMS_DATASET}»", berms.rows[0].text)
        self.assertEqual(sorted(row.text.rsplit("cota ", 1)[1].split(" m,")[0] for row in berms.rows), [self.i18n.format_number(level, 2) for level in (SOUTH_BERM_M, NORTH_BERM_M)])
        self.assertEqual(platforms.rows[0].text.split(": ", 1)[0], "Plataforma «Carga» (PLT-001)")
        self.assertIn("comunicada, se llega a la cota ", platforms.rows[0].text)
        self.assertEqual(platforms.rows[0].place, self.place((30.0, 30.0), float(platform_ops.LOADING_CELLS * platform_ops.CELL_M2)), "el centro de la huella de «Carga» (40 celdas)")
        self.assertEqual(sorted(row.place for row in zones.rows), sorted([self.place((45.0, 15.0), 100.0), self.place((45.0, 45.0), 100.0)]), "el centro de cada zona, con su área")
        self.assertTrue(all(row.text.endswith("comunicada") for row in zones.rows), [row.text for row in zones.rows])

        layers_before = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.entity_layer' AND status = 'done'")[0][0]
        self.assertEqual(self.create_access(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.panels.access_sections(), [], "creada la accesibilidad, la ventana de las listas se vacía")
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?", ACCESS_TYPE)
        self.assertEqual(status, "done")
        for family in ("acc", "acb", "acp", "acz", "prp"):
            self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'current' AND name = ?", self.dprov.dataset_name(family, "Accesibilidad abierta")), [(1,)], family)
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual((figures["des.acc_z_min_m"], figures["des.acc_z_max_m"]), (found.z_min_m, found.z_max_m))
        self.assertEqual((figures["des.acc_berms_reached"], figures["des.acc_zones_reached"], figures["des.acc_zones_missing"]), (2, 2, 0))
        entry = self.entities.registry(self.project, self.v01.uid).get("ACC-001")
        self.assertEqual((entry.record.name, str(entry.record.state)), ("Accesibilidad abierta", "current"))
        value, source, kind, decider = self.parameter_row("ACC-001", "walk_slope_pct")
        self.assertEqual((value, kind, decider), (12.0, "person", self.project.session.user_host))
        self.assertEqual(source, "diálogo de «Accesibilidad de las pistas…», entidad «Accesibilidad abierta»")
        self.assertEqual((self.parameter_row("ACC-001", "walk_width_m")[0], self.parameter_row("ACC-001", "min_berm_area_m2")[0]), (4.0, 100.0))
        self.assertEqual(self.parameter_row("ACC-001", "surface")[0], self.smooth_surface)
        self.assertEqual(self.parameter_row("ACC-001", "entries_layer")[0], ENTRIES)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.entity_layer' AND status = 'done'")[0][0], layers_before + 1, "tras crear, encadena la capa de entidades")
        self.assertNotIn("ACC-001", repr(self.rows('SELECT * FROM "des_enl_v01"')), "sin huella no hay fila en la capa de entidades")
        self.assertEqual(self.table_state(ENTRIES), self.layers_before[ENTRIES], "la capa de entradas no se toca")

    # --- d: las listas con lo que no se comunica ---------------------------------------------------

    def test_d_the_lists_say_what_is_communicated_or_not_with_its_place_and_go_to(self) -> None:
        """RF-017-25, RF-017-24, RF-015-03 (M3): sobre ``Muro`` desde el norte (la pared separa el sur del norte) quedan comunicados la berma y la zona del norte y **no** la berma del sur, la plataforma
        «Carga» ni la zona del camino: **las tres listas** dicen de cada uno si está comunicado, con su cota y su área y su lugar; **las que no, primero y en alerta**, con la distancia y la diferencia de
        cota a lo alcanzable más próximo de la zona; cada fila lleva su «Ir a» (``core_go_to_place`` con el lugar y el radio que da su área) y la ventana de crear los dibuja; el resumen
        no repite cada uno, y el botón dice «Crear con 3 avisos»."""
        self.refresh()
        before = self.state()
        held = self.calculate_access(self.form(name="Accesibilidad con pared", surface=self.wall_surface))
        self.assertEqual(self.state(), before)
        found = held.summary
        self.assertEqual((found.notices[0].values["berms_reached"], found.notices[0].values["platforms_reached"], found.notices[0].values["zones_reached"]), (1, 0, 1))
        self.assertAlmostEqual(found.z_max_m, wall().max(), delta=3.0)
        self.assertGreater(found.z_min_m, 125.0, "solo se alcanza el norte (a partir de ≈ 130 m)")
        summary = self.summary()
        self.assertEqual(len(summary), 2, "el resumen: la cabecera y las cotas; lo que no se comunica va en las listas, con su lugar")
        self.assertFalse(any(alert for _text, alert in summary))
        for text, _alert in summary:
            self.assertNotIn("no queda comunicad", text)

        lists = self.sections()
        berms, platforms, zones = lists.values()
        self.assertEqual([row.alert for row in berms.rows], [True, False], "la que no se comunica, primero y en alerta")
        self.assertTrue(berms.rows[0].text.endswith("no comunicado"), berms.rows[0].text)
        self.assertIn(f"cota {self.i18n.format_number(SOUTH_BERM_M, 2)} m", berms.rows[0].text)
        self.assertEqual(berms.rows[0].place, self.place((30.0, 15.0), 400.0))
        self.assertTrue(berms.rows[1].text.endswith("· comunicado"), berms.rows[1].text)
        self.assertEqual(berms.rows[1].place, self.place((30.0, 45.0), 400.0))
        (platform,) = platforms.rows
        self.assertEqual((platform.text, platform.alert), ("Plataforma «Carga» (PLT-001): no comunicada", True))
        self.assertEqual(platform.place, self.place((30.0, 30.0), 160.0))
        self.assertEqual([row.alert for row in zones.rows], [True, False])
        missing = next(item for item in found.zones if not item.connected)
        self.assertTrue(zones.rows[0].text.startswith("Zona «zona_del_camino» que requiere acceso: no comunicada; lo alcanzable más próximo está a "), zones.rows[0].text)
        self.assertIn(f"a {self.i18n.format_number(missing.distance_m, 2)} m (diferencia de cota {self.i18n.format_number(missing.level_difference_m, 2)} m)", zones.rows[0].text)
        self.assertEqual(zones.rows[0].place, self.panels.constraint_panels.place_of(missing.x, missing.y, 100.0), "el lugar que dice el resumen: su celda más próxima a lo alcanzable")
        self.assertEqual(zones.rows[1].text, "Zona «zona_de_la_balsa» que requiere acceso: comunicada")
        self.assertEqual(self.panels.access_report_lines(), [(row.text, True) for section in (berms, platforms, zones) for row in section.rows if row.alert],
                         "en el informe de la orden, cada cosa que no se comunica")

        window = draw(self.access, bpy.context, **{**DEFAULTS, "confirm": True})
        buttons = window.of_kind("operator")
        self.assertEqual([item.target for item in buttons], [self.panels.constraint_panels.GO_TO_PLACE] * 5, "una fila, un «Ir a»")
        self.assertEqual([item.text for item in buttons], ["Ir a"] * 5)
        self.assertEqual([(item.properties.x, item.properties.y, item.properties.radius) for item in buttons],
                         [row.place for section in (berms, platforms, zones) for row in section.rows])
        shown = window.texts()
        for title in ("Tramos de berma", "Plataformas", "Zonas «requiere acceso»"):
            self.assertIn(title, shown)
        self.assertTrue(any("no comunicada" in text for text in shown))
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.assertEqual(self.access.invoke(self.fake(confirm=True), context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Crear con 3 avisos")
        self.assertEqual(dialog.call_args.kwargs["title"], "Accesibilidad «Accesibilidad con pared» en V01")

        self.i18n.set_language("en")
        self.panels.show_summary(held)
        english = self.sections()
        self.assertEqual(list(english), ["Berm stretches", "Platforms", "Zones that require access"])
        self.assertEqual(english["Platforms"].rows[0].text, "Platform «Carga» (PLT-001): not communicated")
        self.assertTrue(english["Zones that require access"].rows[1].text.endswith("that requires access: communicated"))
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.access.cancel(operator_self(self.access, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.panels.access_sections(), [], "al cancelar, las listas se vacían")
        self.assertEqual(self.state(), before)

    def test_d_b_a_long_list_is_cut_with_a_note(self) -> None:
        """RF-017-25 (M3): una lista de más filas de las que caben en la ventana enseña las primeras —**las que no se comunican, antes**— y una nota con las que faltan; el resultado entero sigue en el
        cálculo (y se registra al crear)."""
        model = platform_ops._module("design.road_model")
        many = tuple(model.BermReach(number, 100.0 + number, 500.0, number % 2 == 0, 10.0 * number, 20.0 * number, "des_brm_x") for number in range(1, 31))
        outcome = model.AccessOutcome(name="Larga", code="ACC-009", reachable=np.zeros((2, 2), dtype=bool), z_min_m=None, z_max_m=None, area_m2=0.0, berms=many)
        job = SimpleNamespace(platforms=(), zones=(), grid=None)
        held = SimpleNamespace(op_type=ACCESS_TYPE, outcome=outcome, entity=SimpleNamespace(job=job), name="Larga", version="V01", notices=(), summary=SimpleNamespace(notices=()))
        self.panels.show_access(held)
        self.addCleanup(self.panels.show_access, None)
        lists = self.sections()
        berms, platforms, zones = lists.values()
        self.assertEqual(len(berms.rows), 10)
        self.assertEqual(berms.more, 20)
        self.assertEqual([row.alert for row in berms.rows], [True] * 10, "las 15 que no se comunican van antes: caben las diez primeras")
        self.assertEqual([row.text.split(" ")[3] for row in berms.rows], [str(number) for number in range(1, 20, 2)][:10])
        self.assertEqual((platforms.rows, zones.rows), ((), ()))
        shown = draw(self.access, bpy.context, **{**DEFAULTS, "confirm": True}).texts()
        self.assertIn("… y 20 más (la lista entera se registra al crear la accesibilidad)", shown)
        self.assertIn("Nada que enseñar", shown)

    def test_d_c_on_the_exploitation_of_a_quarry_the_lowest_level_on_its_final_surface_comes_too(self) -> None:
        """RF-017-24, error 23 (M3): sobre la superficie de **explotación** de una cantera de dos superficies, el resumen da además **la cota mínima alcanzable sobre su final** con los mismos umbrales
        (aquí, la final está 20 m más alta: 20 m más que la mínima de la explotación) y la superficie final es una entrada de la operación; sobre otra superficie, no hay final ni esa línea."""
        self.refresh()
        before = self.state()
        held = self.calculate_access(self.form(name="Accesibilidad de la cantera", surface=EXPLOITATION))
        self.assertEqual((held.entity.final, held.summary.final), (FINAL, FINAL))
        self.assertAlmostEqual(held.summary.z_min_final_m, held.summary.z_min_m + FINAL_RISE_M, delta=1e-9)
        line = [text for text, _alert in self.summary() if text.startswith("Sobre la superficie final")]
        self.assertEqual(line, [f"Sobre la superficie final «{FINAL}» de la cantera la cota mínima alcanzable es {self.i18n.format_number(held.summary.z_min_final_m, 1)} m."])
        self.assertIn(FINAL, [use.item for use in held.entity.start.inputs])
        self.assertEqual((held.summary.notices[0].values["berms"], held.summary.notices[0].values["berms_reached"]), (2, 2))
        self.access.cancel(operator_self(self.access, confirm=True, in_steps=False), bpy.context)
        self.assertEqual(self.state(), before)
        other = self.calculate_access(self.form(name="Accesibilidad del terreno"))
        self.assertIsNone(other.entity.final)
        self.assertFalse([text for text, _alert in self.summary() if text.startswith("Sobre la superficie final")])
        self.access.cancel(operator_self(self.access, confirm=True, in_steps=False), bpy.context)

    # --- e: Esc, cancelar y lo que se rechaza ---------------------------------------------------

    def paced(self, tick_s: float) -> Any:
        """Cada evento del modal, **un paso de una unidad, vaya como vaya el reloj** (E-2 de la verificación única; :func:`~tests.support.step_modals.one_unit_per_event`): el presupuesto de la orden se
        fija **antes de lanzarla** —sus generadores lo leen al crearse— y el reloj de los dos módulos que lo miden (el del modal y el que agrupa las unidades en pasos) avanza ``tick_s`` s por lectura."""
        return step_modals.one_unit_per_event((self.access,), (self.core_ops, platform_ops._module("gis.masks.compile")), tick_s=tick_s)

    def start_esc_calculation(self) -> Any:
        """«Calcular» la accesibilidad «Esc» sobre ``Muro`` desde la interfaz (por pasos, sin abrir la ventana de «Crear») y el modal en marcha."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **self.form(name="Esc", surface=self.wall_surface, in_steps=True)), {"RUNNING_MODAL"})
        return self.running_access()

    def count_esc_events(self, before: tuple[Any, ...], tick_s: float) -> int:
        """Los eventos del cálculo de «Esc» **entero** con un reloj de ``tick_s`` s por lectura (lo que deja, descartado: el proyecto, como estaba)."""
        with self.paced(tick_s):
            whole = self.start_esc_calculation()
            with mock.patch.object(self.des_ops, "_ask_confirmation"):
                state, events = step_modals.drive(whole, bpy.context)
        self.assertEqual(state, {"FINISHED"})
        for text in ("Plataforma «Carga» (PLT-001): no comunicada", "Zona «zona_del_camino» que requiere acceso: no comunicada; lo alcanzable más próximo está a "):
            self.assertTrue(any(line.startswith(text) for line in whole.report_log), f"el informe de la orden dice lo que no se comunica: {text}")
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before)
        return events

    def esc_in_the_middle(self, before: tuple[Any, ...], *, counting_tick_s: float, cutting_tick_s: float) -> int:
        """Esc **a mitad** del cálculo de «Esc»: cuenta sus eventos con un reloj de ``counting_tick_s`` s por lectura y corta con otro de ``cutting_tick_s`` s, **tras uno, a la mitad y antes de los
        dos últimos** (``events // 2`` y ``events - 2``: ninguno se pasa del total; con un paso por evento, los eventos no dependen del reloj, así que siempre caen dentro). Cada Esc responde
        ``CANCELLED``, dice que no queda nada a medias y deja el proyecto como estaba, sin cálculo ni listas. Devuelve los eventos del cálculo entero."""
        events = self.count_esc_events(before, counting_tick_s)
        self.assertGreaterEqual(events, 3, "el cálculo tiene varios pasos: Esc cae a mitad")
        for cut in sorted({1, max(1, events // 2), events - 2}):
            with self.subTest(eventos_antes_de_Esc=cut, reloj_al_contar=counting_tick_s, reloj_al_cortar=cutting_tick_s):
                with self.paced(cutting_tick_s):
                    modal = self.start_esc_calculation()
                    self.assertEqual(step_modals.drive(modal, bpy.context, stop_after=cut)[0], {"RUNNING_MODAL"}, f"el cálculo tiene {events} eventos")
                    self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
                self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
                self.assertIsNone(modal._steps)
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.panels.access_sections(), [])
                self.assertEqual(self.state(), before)
        return events

    def test_e_esc_cancel_and_what_is_refused_leave_nothing(self) -> None:
        """RF-015-29, RF-017-30, RF-017-04, RF-015-08 (M3, M9): Esc **a mitad** del cálculo, Cancelar la confirmación y lo que se rechaza —el nombre vacío o repetido, un umbral sin valor, fuera de rango o que
        no es un número, un punto de entrada fuera de la rejilla— no dejan nada: ni operación, ni dato, ni parámetro, ni cifra, ni temporal (0 transacciones); cada rechazo dice **la capa, la
        accesibilidad, el campo y el valor**; Esc dice que no queda nada a medias."""
        self.refresh()
        before = self.state()
        self.esc_in_the_middle(before, counting_tick_s=step_modals.TICK_S, cutting_tick_s=step_modals.TICK_S)

        self.calculate_access(self.form(name="Cancelada"))
        self.access.cancel(operator_self(self.access, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

        for changes, texts in (
                ({"name": " "}, ("Escriba el nombre de la accesibilidad",)),
                ({"name": "Accesibilidad abierta"}, ("El nombre «Accesibilidad abierta» ya lo tiene la entidad «Accesibilidad abierta» en V01",)),
                ({"walk_slope": ""}, (f"Capa «{ENTRIES}»", "entidad «Rechazada»", ".walk_slope_pct»", "no tiene valor ni lleva ninguno por defecto")),
                ({"walk_width": ""}, (f"Capa «{ENTRIES}»", "entidad «Rechazada»", ".walk_width_m»", "no tiene valor ni lleva ninguno por defecto")),
                ({"min_berm_area": ""}, (f"Capa «{ENTRIES}»", "entidad «Rechazada»", ".min_berm_area_m2»", "no tiene valor ni lleva ninguno por defecto")),
                ({"walk_slope": "-1"}, (f"Capa «{ENTRIES}»", "entidad «Rechazada»", ".walk_slope_pct» = -1", "está fuera de su rango")),
                ({"walk_width": "0"}, (f"Capa «{ENTRIES}»", "entidad «Rechazada»", ".walk_width_m» = 0", "está fuera de su rango")),
                ({"walk_slope": "abc"}, ("«abc» no es un número",)),
                ({"layer": OUTSIDE}, (f"Capa «{OUTSIDE}»", "accesibilidad «Rechazada»", "el punto de entrada «1» no tiene dato en la superficie", self.smooth_surface))):
            with self.subTest(cambios=changes):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **self.form(**{"name": "Rechazada", **changes}))
                for text in texts:
                    self.assertIn(text, str(caught.exception))
                self.assertIsNone(self.des_ops.calculation())
                self.assertEqual(self.state(), before)

    def test_e_b_the_events_of_the_calculation_and_the_cut_of_esc_do_not_depend_on_the_clock(self) -> None:
        """RF-015-29, RF-017-30, RNF-017-06 (E-2 de la verificación única de la 017): el número de eventos de «Calcular» **no depende del reloj** y Esc a mitad cae siempre dentro. Con un reloj de
        mentira que va **muy rápido** (0,1 µs por lectura: el paso agrupa casi todas las unidades) y otro **muy lento** (1 s por lectura: una unidad por paso), el cálculo entero da **los mismos
        eventos**, y contarlos con uno y cortar con el otro —en los dos sentidos, también el que antes fallaba: contar lento y cortar rápido— deja el proyecto como estaba. La versión de antes
        (el presupuesto del modal fijado cuando la orden ya había creado sus generadores, con el de verdad, 0,05 s) daba muchos más eventos con el reloj lento: ``FINISHED`` donde se esperaba
        ``RUNNING_MODAL``."""
        self.refresh()
        before = self.state()
        counted = {tick: self.count_esc_events(before, tick) for tick in (FAST_TICK_S, SLOW_TICK_S, step_modals.TICK_S)}
        self.assertEqual(len(set(counted.values())), 1, f"los eventos del cálculo no dependen del reloj: {counted}")
        for counting, cutting in ((SLOW_TICK_S, FAST_TICK_S), (FAST_TICK_S, SLOW_TICK_S)):
            self.assertEqual(self.esc_in_the_middle(before, counting_tick_s=counting, cutting_tick_s=cutting), counted[counting])

    # --- f: desactivada con su motivo ---------------------------------------------------------------

    def test_f_the_command_is_disabled_with_its_reason(self) -> None:
        """RF-017-29, RF-015-28, RF-009-05, RF-009-21 (M3): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable (V02 SUPERADO: «V02 está en estado
        SUPERADO: …», que dice también su descripción) la orden sale desactivada con su motivo y no se puede lanzar; **sin versión activa**, el diálogo no abre: dice que hace falta una y la ventana que la
        pide (RF-009-05); con V01 en escritura, activa. Ninguna deja nada."""
        messages: list[str] = []
        cls = self.access
        self.assertTrue(cls.poll(bpy.context))
        self.assertTrue(bpy.ops.geoblender.des_road_access.poll())

        def poll() -> bool:
            messages.clear()
            with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                return bool(cls.poll(bpy.context))

        self.assertTrue(poll())
        self.assertEqual(messages, [])
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertFalse(poll())
            (reason,) = messages
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(bpy.ops.geoblender.des_road_access.poll())
            with self.assertRaises(RuntimeError):
                bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **self.form(name="No debe"))
            self.assertEqual(self.state(), before)
        self.assertTrue(poll())
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        not_editable = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
        self.assertFalse(poll())
        self.assertEqual(messages, [not_editable])
        self.assertFalse(bpy.ops.geoblender.des_road_access.poll())
        self.assertIn(not_editable, cls.description(bpy.context, SimpleNamespace()))
        reported: list[str] = []
        refused = operator_self(cls, report=lambda kind, text: reported.append(text), confirm=False, in_steps=False)
        self.assertEqual(cls.invoke(refused, SimpleNamespace(window=None), None), {"CANCELLED"})
        self.assertEqual(reported, [not_editable])
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertTrue(poll())

        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=""), {"FINISHED"})  # sin versión activa
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertTrue(poll(), "sin versión activa la orden está activa: la pide al lanzarla (RF-009-05)")
        with mock.patch.object(self.session, "open_version_dialog") as asked:
            reported.clear()
            nobody = operator_self(cls, report=lambda kind, text: reported.append(text), confirm=False, in_steps=False)
            self.assertEqual(cls.invoke(nobody, SimpleNamespace(window=None), None), {"CANCELLED"})
            asked.assert_called_once()
            self.assertEqual(reported, [], "la ventana que pide la versión es lo que dice")
            asked.reset_mock()
            with self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", name="Sin versión")
            self.assertIn(self.session.version_required_text(), str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})

    # --- z: desactivar ---------------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_command_and_the_open_calculation(self) -> None:
        """Principio 8, D-14 de la 013, RF-015-26: con un cálculo abierto desactivar Geoblender lo descarta (no queda ningún temporal ni lista) y quita la orden y sus listas."""
        self.refresh()
        self.calculate_access(self.form(name="Al apagar", surface=self.wall_surface))
        self.assertTrue(self.panels.access_sections())
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, ACCESS_CLASS, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))
        self.assertEqual(self.panels.access_sections(), [])
        self.assertEqual(self.panels.access_default_surface(), None)


# Las pruebas de la plataforma son de ``test_platform_ops.py``: aquí solo se aprovecha su proyecto.
for _name in dir(platform_ops.CreatePlatformTest):
    if _name.startswith("test_") and not hasattr(RoadAccessOpsTest.__dict__.get(_name, None), "__call__"):
        setattr(RoadAccessOpsTest, _name, None)


if __name__ == "__main__":
    unittest.main()
