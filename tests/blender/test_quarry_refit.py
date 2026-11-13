# SPDX-License-Identifier: GPL-3.0-or-later
"""«Ajustar el diseño a un límite nuevo…» y la exportación de las rejillas de la 014 en Blender
(spec 014, T33; HU-014-7; RF-014-27 a RF-014-29, RF-014-32; plan 014 §5.3.3, §5.5, P-1, P-3;
comprobación manual M6).

:class:`GEOBLENDER_OT_des_refit_to_limit` (``geoblender.des_refit_to_limit``, en Diseño ▸ Cantera)
calcula con ``design.steps.refit_run`` la operación ``des.refit`` de la versión activa: cada
superficie de diseño elegida, ajustada al límite vigente con la cara de **su propio perfil** (el
ángulo no se pide, P-3). Su diálogo pide el nombre, la superficie de partida y las superficies que se
ajustan: las de diseño de la versión (las de una cantera, de un escalonado de la 013…), con **las que
quedan fuera del límite vigente marcadas** y lo que deja fuera cada una; si las máscaras no están al
día, lo dice. Calcular, Crear, Cancelar y Esc son los de las demás órdenes de la 014: nada se
registra hasta Crear. El cargador de ``des_adj_`` lleva cada superficie ajustada a la vista y la
barra N enseña su ficha; «Exportar rejilla a GeoTIFF…» la exporta, y también la clasificación de la
cantera, con su código por clase y su leyenda en los metadatos (RF-014-32). El resumen de un ajuste
de un diseño obsoleto dice que recalcularlo sustituye el ajuste (T54, RF-014-31, hallazgo F-16), y
cerrar el proyecto mientras la orden comprueba antes de abrir su ventana no la vuelve a abrir (T54,
punto 2 de la T48).

Un proyecto pequeño por clase (ventana de 60 × 40 m con celdas de 2 m, V01, el límite legal de
(4, 4) a (56, 36) con 2 m hacia dentro, el perímetro de (2, 2) a (58, 38), un sector con la búsqueda
cerrada, la ladera ``100 + 0,25·y + 0,0625·x`` y los perfiles ``REST_5_35_6`` y ``EXPL_10_60_6``) con
la cantera «Corta» de V01 (la final con ``REST_5_35_6`` y la explotación con ``EXPL_10_60_6``) y el
escalonado de la 013 «Escalonado» (de una envolvente a 98 m), creados por el dominio; después, el
límite legal **30 m más corto por el este** (de x = 56 a x = 26), sin recompilar las máscaras. Las
pruebas, en el orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
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

from tests.support import blender_ext, step_modals
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

REFIT = "geoblender.des_refit_to_limit"
REFIT_CLASS = "GEOBLENDER_OT_des_refit_to_limit"
REFIT_TYPE = "des.refit"
DESIGN_MENU = "GEOBLENDER_MT_ui_design"
KIND = "DESIGN"
REASON = "Prueba del ajuste a un límite nuevo"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de restauración"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M, HEIGHT_M = 60.0, 40.0
STEP_M = 2.0
LEGAL = (4.0, 4.0, 56.0, 36.0)
INWARD_M = 2.0
PERIMETER = (2.0, 2.0, 58.0, 38.0)
CUT_BACK_M = 30.0
NEW_LEGAL = (LEGAL[0], LEGAL[1], LEGAL[2] - CUT_BACK_M, LEGAL[3])
SECTOR = ("Sector único", (0.0, 0.0, WIDTH_M, HEIGHT_M))
CLOSED_AT = "2026-11-13T10:00:00Z"
REST, REST_CODE, REST_FACE_DEG = "REST_5_35_6", "rest_5_35_6", 35.0
EXPL, EXPL_CODE, EXPL_FACE_DEG = "EXPL_10_60_6", "expl_10_60_6", 60.0
QUARRY_NAME = "Corta"
ENVELOPE_NAME = "Hueco"
STEPPED_NAME = "Escalonado"
ENVELOPE_M = 98.0
"""La cota fija de las semillas de la envolvente del escalonado (un dato de la prueba)."""
NAME = "Ajuste E6"
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 por defecto (el proyecto no declara otro)."""
NODATA = -9999.0
PROPERTIES = {
    "name": ("Name", "Name of the refit, unique in the active version"),
    "surfaces": ("Design surfaces", "Design surfaces of the active version that are refitted "
                                    "(marked: the ones the current limit leaves outside)"),
    "start": ("Start surface", "Surface the design starts from: outside the limit the refitted "
                               "surfaces go back to it"),
}
"""Las propiedades del diálogo con el ``msgid`` de su nombre y de su descripción."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
CLOSED_TEXT = "Se cerró el proyecto mientras se calculaba «Cierre»: no ha quedado nada a medias"
"""Lo que dice la orden si el proyecto se cierra mientras calcula «Cierre» (T48)."""


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
    columns = STEP_M * np.arange(int(WIDTH_M / STEP_M), dtype=np.float64) + STEP_M / 2
    rows = HEIGHT_M - (STEP_M * np.arange(int(HEIGHT_M / STEP_M), dtype=np.float64) + STEP_M / 2)
    x, y = np.meshgrid(columns, rows)
    return 100.0 + 0.25 * y + 0.0625 * x


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class _Rows(list):  # type: ignore[type-arg]
    """La colección de filas de la orden, de mentira (``add`` y ``clear``)."""

    def add(self) -> SimpleNamespace:
        row = SimpleNamespace(name="", label="", outside=False, selected=False)
        self.append(row)
        return row


class RefitToLimitTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera, para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t33-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.out = folder / "salida"
        cls.out.mkdir()
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
        cls.dstore = _module("design.store")
        cls.refit = _module("design.refit")
        cls.surfaces = _module("design.surfaces")
        cls.access = _module("gis.masks.access")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + WIDTH_M, SOUTH + HEIGHT_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = _module("core.versions.store").create_version(
                conn, cls.project, feature="cantera", title="Cantera", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        for name, height, face in ((REST, "5", "35"), (EXPL, "10", "60")):
            assert bpy.ops.geoblender.des_save_bench_profile(
                name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
                scope="PROJECT", height=height, face=face, berm="6",
                anchor="125") == {"FINISHED"}
        steps, dmodel = _module("design.steps"), cls.dmodel
        request = dmodel.QuarryRequest(QUARRY_NAME, cls.ground, dmodel.QuarrySide(REST_CODE),
                                       dmodel.QuarrySide(EXPL_CODE))
        envelope = dmodel.EnvelopeRequest(
            ENVELOPE_NAME, "down", dmodel.SeedSource(
                "fixed", zone=dmodel.Zone("sector", "sector_1"), elevation_m=ENVELOPE_M),
            slope_deg=REST_FACE_DEG)
        stepped = dmodel.DesignRequest(name=STEPPED_NAME, envelope=ENVELOPE_NAME, sense="cut",
                                       base_profile=REST_CODE, sector_profiles={},
                                       anchor_grid=None)
        for work in (lambda: steps.quarry_run(cls.project, request, version=cls.v01.uid),
                     lambda: steps.envelope_run(cls.project, envelope, version=cls.v01.uid),
                     lambda: steps.design_run(cls.project, stepped, cls.ground,
                                              version=cls.v01.uid)):
            found = None
            for found in work():
                pass
            found.result.create()
        cls.final = cls.dprov.dataset_name("fin", QUARRY_NAME)
        cls.exploitation = cls.dprov.dataset_name("exp", QUARRY_NAME)
        cls.stepped = cls.dprov.dataset_name("srf", STEPPED_NAME)
        cls.adjusted = {surface: cls.dprov.refit_output(NAME, surface)
                        for surface in (cls.exploitation, cls.final)}
        (legal,) = [item for item in cls.stored() if item.name == "Concesión"]
        cls.cprov.edit_constraints(cls.project, [dataclasses.replace(
            legal, parts=((ring(NEW_LEGAL),),))], srs_id=cls.project.record.crs_epsg)
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
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
            values={m.ConstraintParam.BUFFER_IN: INWARD_M, m.ConstraintParam.BUFFER_OUT: 0.0,
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
    def stored(cls) -> tuple[Any, ...]:
        """Las restricciones guardadas en el proyecto."""
        with cls.project.read() as conn:
            return cls.cstore.read_constraints(conn)

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
        return self.commands.registered_class(REFIT)

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

    def uid_of(self, name: str) -> str:
        (uid,) = [row[0] for row in self.rows(
            "SELECT uid FROM gb_dataset WHERE name = ? AND status IN ('current', 'stale')", name)]
        return str(uid)

    def compiled(self) -> None:
        """Las máscaras de V01 al día con el límite nuevo (las compila si no lo están)."""
        state, _pending = self.access.mask_state(self.project, self.v01.uid)
        if state is not self.access.MaskState.CURRENT:
            self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})

    @staticmethod
    def row(name: str, selected: bool) -> dict[str, Any]:
        """Una fila de las superficies del diálogo desde un guion (Blender pide todos sus campos)."""
        return {"name": name, "label": "", "outside": False, "selected": selected}

    def form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: el ajuste «Ajuste E6» de las dos superficies de la cantera."""
        return {"name": NAME, "start": self.ground, "in_steps": False,
                "surfaces": [self.row(self.exploitation, True), self.row(self.final, True),
                             self.row(self.stepped, False)], **values}

    def fake_dialog(self, **values: Any) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira y el contexto con que se abre el diálogo (sin ventana)."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {
            "name": "", "surfaces": _Rows(), "start": "", "note": "", "confirm": False,
            "in_steps": False, "properties": SimpleNamespace(is_property_set=lambda name: False),
            **values}
        return operator_self(self.cls, report=lambda kind, text: None, **fields), context, dialog

    def loaded(self, name: str) -> Any:
        """El objeto de la vista del dato vivo ``name`` (lo carga si no está)."""
        uid = self.uid_of(name)
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        if not found:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
            found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]
        self.assertEqual(len(found), 1)
        return found[0]

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{REFIT} no está en marcha")
        return found[0]

    def expected(self, surface: str, face_deg: float) -> Any:
        """El ajuste de ``surface`` (su dato de V01) al límite vigente con una cara de ``face_deg``
        (factor de malla 1), con ``design.refit.refit_steps``."""
        values = self.surfaces.read_surface(self.project, surface,
                                            version_uid=self.v01.uid).values
        masks = self.access.load_masks(self.project, self.v01.uid)
        face = self.refit.ProfileFace("cara", "Cara", face_deg, 1.0)
        slope = self.refit.face_slope(np.zeros(values.shape, dtype=np.int64), face, ())
        found = None
        for found in self.refit.refit_steps(values, ground(), masks, slope, THICKNESS_M,
                                            name=surface, version=self.v01.code):
            pass
        return found.result

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_its_dialog_and_the_marked_surfaces(self) -> None:
        """RF-014-27, RF-014-29 (plan §5.3.3, §5.5): «Ajustar el diseño a un límite nuevo…» es una
        orden real de ``des.refit`` en Diseño, con la puerta de la procedencia y los pasos con Esc;
        sus propiedades tienen nombre y descripción en español. Su diálogo ofrece las superficies de
        diseño de la versión que se pueden ajustar (las dos de la cantera y la del escalonado de la
        013; no las envolventes ni la clasificación): con las máscaras sin recompilar, ninguna
        marcada y la nota que lo dice; recompiladas, **las que quedan fuera del límite vigente,
        marcadas** y en alerta, con su volumen y su área fuera (los de la comprobación de la T31);
        propone «Ajuste» y, de partida, la de la ficha de la primera; lo dado no cambia; dibuja el
        nombre, la partida y una fila por superficie."""
        cls = self.cls
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), (REFIT_TYPE, {"REGISTER"}))
        self.assertEqual(cls.STEP_BUDGET_S, 0.05)
        command = self.commands.catalog().commands[REFIT]
        self.assertEqual((command.label_es, command.home),
                         ("Ajustar el diseño a un límite nuevo…", DESIGN_MENU))
        self.assertEqual(self.dprov.OPERATION_TYPES_BY_NAME[REFIT_TYPE].commands, (REFIT,))
        for prop, (label, about) in PROPERTIES.items():  # registradas ya en español
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertEqual((keywords["name"], keywords["description"]),
                                 (self.i18n.translate("es", label),
                                  self.i18n.translate("es", about)))
                self.assertEqual(self.i18n.untranslated([label, about]), [])
        listed = sorted([self.exploitation, self.final, self.stepped])

        fake, context, dialog = self.fake_dialog()  # las máscaras, obsoletas por el límite nuevo
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Ajustar el diseño a un límite nuevo…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertTrue(fake.in_steps)
        self.assertEqual((fake.name, fake.start), ("Ajuste", self.ground))
        self.assertEqual([(row.name, row.label, row.outside, row.selected)
                          for row in fake.surfaces],
                         [(name, f"«{name}»", False, False) for name in listed])
        self.assertEqual(fake.note, "Las máscaras de V01 no están al día: compílelas para ver qué "
                                    "superficies deja fuera el límite vigente")

        self.compiled()
        fake, context, _dialog = self.fake_dialog()
        cls.invoke(fake, context, None)
        self.assertEqual(fake.note, "")
        self.assertEqual([row.name for row in fake.surfaces], listed)
        checks = {check.surface: check for check in self.dstore.limit_checks(
            self.project, self.v01.uid, types=self.dstore.REFIT_SOURCES)}
        self.assertEqual(sorted(checks), listed)
        # Sin ``types``, la comprobación de la T31 sigue sin mirar el escalonado de la 013.
        self.assertEqual(sorted(check.surface for check in self.dstore.limit_checks(
            self.project, self.v01.uid)), sorted([self.exploitation, self.final]))
        for row in fake.surfaces:
            with self.subTest(superficie=row.name):
                check = checks[row.name]
                self.assertTrue(check.outside)
                self.assertEqual((row.outside, row.selected), (True, True))
                self.assertEqual(row.label, "«{surface}» · {volume} m³ en {area} m² fuera del "
                                            "límite vigente".format(
                                                surface=row.name,
                                                volume=self.i18n.format_number(check.volume_m3, 0),
                                                area=self.i18n.format_number(check.area_m2, 0)))
        given, context, _dialog = self.fake_dialog(
            name="Mío", start=self.ground, surfaces=_Rows(),
            properties=SimpleNamespace(is_property_set=lambda name: name in ("surfaces", "start")))
        cls.invoke(given, context, None)
        self.assertEqual((given.name, list(given.surfaces)), ("Mío", []))
        shown = draw(cls, bpy.context, name=NAME, start=self.ground, surfaces=fake.surfaces,
                     note="", confirm=False)
        texts = shown.texts()
        for heading in ("Nombre", "Superficie de partida", "Superficies de diseño que se ajustan"):
            self.assertIn(heading, texts)
        boxes = [item for item in shown.of_kind("prop") if item.target == "selected"]
        self.assertEqual([(item.text, item.alert) for item in boxes],
                         [(row.label, True) for row in fake.surfaces])

    def test_b_calculate_then_create_the_refit(self) -> None:
        """RF-014-27 a RF-014-29 (M6; P-3; error 46): Calcular desde un guion las dos superficies de
        la cantera deja el cálculo abierto con su resumen (una línea por superficie, en los dos
        idiomas) y solo sus dos temporales; cada superficie, ajustada con la cara de **su propio
        perfil** (la explotación con 60°, la final con 35°: con 35°, la explotación saldría
        distinta) y las dos atadas después por la regla de orden de la cantera («final primero»,
        con su nota en el resumen; T53, RF-014-14) y, al final del resumen, en alerta y en los dos
        idiomas, el aviso de que la cantera de la que salen está obsoleta (el límite nuevo) y
        recalcularla sustituye el ajuste (T54, RF-014-31, hallazgo F-16); Crear registra
        ``des.refit`` hecha en V01 con una ``des_adj_`` por superficie
        (releídas, las calculadas) y la cifra ``des.refit_m3`` de cada una, y lo ajustado ya no deja
        nada fuera del límite vigente."""
        self.compiled()
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_refit_to_limit("EXEC_DEFAULT", **self.form()),
                         {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        self.assertEqual((held.op_type, held.name, held.version), (REFIT_TYPE, NAME, "V01"))
        after = self.state()
        self.assertEqual(after[:3], before[:3], "calcular no registra nada")
        temporaries = sorted(set(after[3]) - set(before[3]))
        self.assertEqual(len(temporaries), 2, temporaries)
        self.assertTrue(all(".tmp" in name for name in temporaries))
        self.assertEqual(self.view.summary_title, f"Ajuste «{NAME}» en V01")
        summary = [line.name for line in self.view.summary]
        outcome = held.outcome
        self.assertEqual([item.surface for item in outcome.refits],
                         [self.exploitation, self.final])
        for line, surface in zip(summary, (self.exploitation, self.final), strict=False):
            self.assertTrue(line.startswith(f"«{surface}» ajustada con la cara de su perfil: "),
                            summary)
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertTrue([line.name for line in self.view.summary][0].startswith(
            f"«{self.exploitation}» refitted with the face of its profile: "))
        self.i18n.set_language("es")
        expected = {surface: self.expected(surface, face) for surface, face in (
            (self.exploitation, EXPL_FACE_DEG), (self.final, REST_FACE_DEG))}
        tied = _module("design.quarry").order_surfaces(  # «final primero», T53 (RF-014-14)
            "final_first", expected[self.final].grid, expected[self.exploitation].grid, ground())
        for surface, grid in ((self.exploitation, tied.exploitation), (self.final, tied.final)):
            with self.subTest(superficie=surface):
                found = outcome.refit(surface)
                np.testing.assert_array_equal(found.grid, grid)
                self.assertEqual((found.volume_m3, found.cells),
                                 (expected[surface].volume_m3, expected[surface].cells))
                self.assertGreater(found.volume_m3, 0.0)
        self.assertIn(f"Regla de orden de la cantera «{QUARRY_NAME}» con sus dos superficies "
                      f"ajustadas: «{self.exploitation}» cambia en {tied.adjusted} celdas",
                      summary[-2])
        stale = _module("core.provenance.stale")  # la cantera, obsoleta por el límite nuevo
        ((quarry_uid,),) = self.rows("SELECT uid FROM gb_operation WHERE op_type = ?",
                                     "des.quarry")
        with self.project.read() as conn:
            self.assertTrue(stale.item_causes(conn, "operation", quarry_uid))
        surfaces = f"«{self.exploitation}», «{self.final}»"
        self.assertEqual(summary[-1], (  # T54: recalcular la cantera sustituye el ajuste
            f"El diseño «{QUARRY_NAME}» está obsoleto: Proyecto ▸ Recalcular lo obsoleto lo "
            "vuelve a calcular con el límite vigente y después rehace sobre él este ajuste de "
            f"{surfaces}, que sustituye al que se cree ahora."))
        self.assertTrue(self.view.summary[-1].alert)
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary[-1].name, (
            f"The design «{QUARRY_NAME}» is stale: Project ▸ Recompute the stale results "
            f"computes it again with the current limit and then redoes this refit of {surfaces} "
            "on it, which replaces the one created now."))
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        wrong = self.expected(self.exploitation, REST_FACE_DEG)  # el error 46
        self.assertGreater(wrong.volume_m3, outcome.refit(self.exploitation).volume_m3)
        self.assertEqual(held.warnings()[-1], summary[-1])  # «Crear con N avisos» lo cuenta

        self.assertEqual(bpy.ops.geoblender.des_refit_to_limit(
            "EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?",
                                     REFIT_TYPE)
        self.assertEqual(status, "done")
        for surface, adjusted in self.adjusted.items():
            with self.subTest(superficie=surface):
                written = self.surfaces.read_surface(self.project, adjusted,
                                                     version_uid=self.v01.uid).values
                np.testing.assert_array_equal(written, outcome.refit(surface).grid)
        figures = sorted(value for _key, value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual(figures, sorted(item.volume_m3 for item in outcome.refits))
        self.assertEqual({key for key, _value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}, {"des.refit_m3"})
        checks = self.dstore.limit_checks(self.project, self.v01.uid,
                                          names=tuple(self.adjusted.values()))
        self.assertEqual(len(checks), 2)
        self.assertFalse(any(check.outside for check in checks))

    def test_b_the_refit_of_a_stale_stepped_design_names_it(self) -> None:
        """RF-014-27, RF-014-31 (T54, hallazgo F-16): lo mismo con una superficie que no sale de
        una cantera: el escalonado de la 013 «Escalonado» está obsoleto (su envolvente lee las
        máscaras del límite nuevo), y el resumen del ajuste de su superficie lo dice, en alerta y
        al final, nombrándolo. Calcular no registra nada."""
        self.compiled()
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_refit_to_limit("EXEC_DEFAULT", **self.form(
            name="Del escalonado", surfaces=[self.row(self.stepped, True)])), {"FINISHED"})
        self.assertEqual(self.state()[:3], before[:3])
        last = self.view.summary[-1]
        self.assertEqual(last.name, (
            f"El diseño «{STEPPED_NAME}» está obsoleto: Proyecto ▸ Recalcular lo obsoleto lo "
            "vuelve a calcular con el límite vigente y después rehace sobre él este ajuste de "
            f"«{self.stepped}», que sustituye al que se cree ahora."))
        self.assertTrue(last.alert)

    def test_c_the_refitted_surface_in_the_view_its_card_and_the_exports(self) -> None:
        """RF-014-27, RF-014-32 (M6): «Cargar en la vista» de una superficie ajustada da un objeto
        ``DESIGN`` «Superficie ajustada a un límite nuevo …»; la barra N enseña su ficha (la
        superficie de la que sale, la de partida y sus cifras, sin envolvente ni semillas).
        «Exportar rejilla a GeoTIFF…» la escribe como las cotas de la 013 (cada cota, la registrada
        en float32) y escribe la clasificación de la cantera con el código de cada clase y su
        leyenda en los metadatos; las dos rejillas de la 014 que la barra N rechazaba."""
        loader = self.views.loader_for(self.adjusted[self.exploitation])
        self.assertEqual((loader.prefix, loader.kind, loader.label),
                         ("des_adj_", KIND, "Surface refitted to a new limit"))
        obj = self.loaded(self.adjusted[self.exploitation])
        self.assertTrue(obj.name.startswith("Superficie ajustada a un límite nuevo "), obj.name)
        found = self.panels.item_lines(self.project, str(obj.geoblender.dataset_uid))
        texts = [line.text for line in found.lines]
        self.assertEqual(found.title, f"Superficie ajustada a un límite nuevo · {NAME}")
        self.assertIn(f"Superficie ajustada: «{self.exploitation}»", texts)
        self.assertIn(f"Superficie de partida: «{self.ground}»", texts)
        self.assertNotIn("Semillas y dominios", texts)
        self.assertFalse(any(text.startswith("Envolvente") for text in texts), texts)
        self.assertFalse(any("fuera del límite vigente" in text for text in texts), texts)
        self.assertEqual(len(found.figures), 3, found.figures)  # el encabezado y las dos

        reader = _module("gis.geotiff.reader")
        tiff, geokeys = _module("gis.geotiff.tiff"), _module("gis.geotiff.geokeys")
        before = self.state()
        classes = self.dprov.dataset_name("cls", QUARRY_NAME)
        for name in (self.adjusted[self.exploitation], classes):
            with self.subTest(dato=name):
                target = self.out / f"{name}.tif"
                self.assertEqual(bpy.ops.geoblender.des_export_design_grid(
                    "EXEC_DEFAULT", source=self.uid_of(name), filepath=str(target)),
                    {"FINISHED"})
                stored = self.surfaces.read_surface(self.project, name,
                                                    version_uid=self.v01.uid).values
                written = reader.read_geotiff(target, max_cells=10**7)
                self.assertEqual((written.source_dtype, written.nodata_value),
                                 ("float32", NODATA))
                finite = np.isfinite(stored)
                np.testing.assert_array_equal(written.values, np.where(
                    finite, stored.astype(np.float32).astype(np.float64), np.nan))
                with target.open("rb") as stream:
                    ifd = tiff.read_first_ifd(stream, target.stat().st_size)
                items = geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")
                self.assertEqual(items["DATO"], name)
                if name == classes:
                    self.assertTrue(set(np.unique(written.values[finite]).tolist())
                                    <= {0.0, 1.0, 2.0})
                    self.assertEqual({key: value for key, value in items.items()
                                      if key.startswith("CODIGO_") or key == "UNIDAD"},
                                     {"UNIDAD": "código", "CODIGO_0": "sin diferencia",
                                      "CODIGO_1": "desdoblado",
                                      "CODIGO_2": "relleno de restauración"})
                else:
                    self.assertEqual((items["UNIDAD"], items["TIPO"]),
                                     ("m", "Superficie ajustada a un límite nuevo"))
        self.assertEqual(self.state(), before)  # exportar no escribe en el proyecto

    def test_d_esc_cancel_and_what_is_missing_leave_nothing(self) -> None:
        """RF-014-29 (RNF-014-05): Esc con el cálculo en marcha, Cancelar la confirmación, ninguna
        superficie marcada y un nombre vacío no dejan nada (ni operación, ni dato, ni cifra, ni
        temporal); Esc deja el aviso de que no queda nada a medias."""
        self.compiled()
        before = self.state()
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_refit_to_limit(
                "EXEC_DEFAULT", **self.form(name="Esc", in_steps=True)), {"RUNNING_MODAL"})
        modal = self.running()
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"CANCELLED"})
        self.assertIn("Cálculo cancelado: no queda nada a medias", modal.report_log)
        self.assertEqual(self.state(), before)
        self.assertEqual(bpy.ops.geoblender.des_refit_to_limit(
            "EXEC_DEFAULT", **self.form(name="Cancelado")), {"FINISHED"})
        self.cls.cancel(operator_self(self.cls, confirm=True, in_steps=False), bpy.context)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_refit_to_limit("EXEC_DEFAULT", **self.form(
                name="Ninguna", surfaces=[self.row(self.final, False)]))
        self.assertIn("Elija las superficies de diseño que se ajustan", str(caught.exception))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_refit_to_limit("EXEC_DEFAULT", **self.form(name=" "))
        self.assertIn("Escriba el nombre del ajuste", str(caught.exception))
        self.assertEqual(self.state(), before)

    def test_e_closing_the_project_at_the_last_step_leaves_nothing(self) -> None:
        """RNF-014-05, RF-014-29 (T48, hallazgo F-9): si el proyecto se cierra justo antes del
        último evento —el ajuste, calculado; su resultado llega con el proyecto ya cerrado—, el
        modal se para sin dejar nada (ni cálculo abierto ni ventana de «Crear», ni operación, ni
        dato, ni cifra, ni temporal) y lo dice."""
        self.compiled()
        before = self.state()

        def start() -> Any:
            with mock.patch.object(self.des_ops, "_ask_confirmation"):
                self.assertEqual(bpy.ops.geoblender.des_refit_to_limit(
                    "EXEC_DEFAULT", **self.form(name="Cierre", in_steps=True)), {"RUNNING_MODAL"})
            return self.running()

        closed = step_modals.close_at_the_last_event(self.cls, start, bpy.context, session=self.ps,
                                                     des_ops=self.des_ops)
        self.assertEqual(closed.state, {"CANCELLED"})
        self.assertEqual(closed.modal.report_log, [CLOSED_TEXT])
        self.assertIsNone(closed.modal._steps)
        self.assertEqual(closed.asked, 0)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

    def test_e_closing_the_project_while_checking_opens_nothing(self) -> None:
        """RNF-014-05 (T54, punto 2 de la T48; la comprobación previa de la T35, RNF-014-02): sin
        acierto en la caché, la orden comprueba las superficies antes de abrir su ventana; si el
        proyecto se cierra justo antes del último evento —las filas, calculadas; llegan con el
        proyecto ya cerrado—, el modal se para sin volver a abrir la orden, lo dice y no deja
        nada (ni cálculo abierto, ni operación, ni dato, ni cifra, ni temporal). (En
        ``blender -b`` Blender no llama a ``invoke``: se llama a mano con un ``self`` y un
        contexto de mentira, como en la prueba f de ``test_quarry_limit``.)"""
        self.compiled()
        later = self.enterContext(mock.patch.object(self.des_ops, "_invoke_later"))
        before = self.state()
        fakes: list[Any] = []

        def start() -> Any:
            self.panels.forget_limit_checks()  # sin acierto: comprueba antes
            manager = SimpleNamespace(**{name: mock.Mock() for name in (
                "event_timer_add", "event_timer_remove", "modal_handler_add", "progress_begin",
                "progress_update", "progress_end", "invoke_props_dialog")})
            context = SimpleNamespace(window=window(), window_manager=manager, workspace=None,
                                      selected_objects=())
            fake = operator_self(self.cls, name="", surfaces=_Rows(), start="", note="",
                                 confirm=False, in_steps=False, report=lambda kind, text: None,
                                 properties=SimpleNamespace(is_property_set=lambda name: False))
            self.assertEqual(self.cls.invoke(fake, context, None), {"RUNNING_MODAL"})
            manager.invoke_props_dialog.assert_not_called()
            fakes.append(fake)
            return SimpleNamespace(modal=lambda _context, event: self.core_ops._StepsModal.modal(
                fake, context, event))

        closed = step_modals.close_at_the_last_event(self.cls, start, bpy.context, session=self.ps,
                                                     des_ops=self.des_ops)
        self.assertEqual(later.call_count, 1, "solo la primera vez, la que llega al final")
        self.assertEqual(closed.state, {"CANCELLED"})
        checking = fakes[-1]
        self.assertEqual(checking.report_log,
                         ["Comprobación cancelada: no se ha abierto la ventana"])
        self.assertIsNone(checking._steps)
        self.assertEqual(closed.asked, 0)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)

    def test_z_disabling_geoblender_removes_the_command_and_the_loader(self) -> None:
        """Principio 8, D-14 de la 013: con un cálculo abierto, desactivar Geoblender lo descarta
        (no queda ningún temporal) y quita la orden y el cargador de la superficie ajustada."""
        self.compiled()
        self.assertEqual(bpy.ops.geoblender.des_refit_to_limit(
            "EXEC_DEFAULT", **self.form(name="Al apagar")), {"FINISHED"})
        self.assertTrue(any(".tmp" in name for name in self.names()))
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, REFIT_CLASS, None))
        self.assertIsNone(self.views.loader_for(self.adjusted[self.exploitation]))
        self.assertFalse(any(".tmp" in name for name in self.names()))


if __name__ == "__main__":
    unittest.main()
