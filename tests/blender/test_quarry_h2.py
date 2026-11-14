# SPDX-License-Identifier: GPL-3.0-or-later
"""La historia del hito H2 en Blender: E3 y E4 con las órdenes reales (spec 014, T24; HU-014-3,
HU-014-4; RF-014-12 a RF-014-18, RF-014-29; CE-014-04, CE-014-05; plan 014 §7.1, §7.5; comprobación
manual M3 y M4).

«Cantera con dos superficies…» (``geoblender.des_design_quarry``) desde un guion, como la deja el
diálogo: «Calcular» (``in_steps`` falso) da el resumen y el cálculo abierto, y la misma orden con
``confirm=True`` lo crea. Las superficies, la clasificación y las cifras se releen del proyecto.

Un proyecto por clase (ventana de 100 × 100 m con celdas de 2 m, V01 y V02; el límite legal de
(6, 6) a (94, 94) con 2 m hacia dentro, el perímetro de (4, 10) a (96, 96), una zona sin corte de
(30, 30) a (40, 40) sin resguardo, dos sectores con la búsqueda cerrada —el oeste hasta x = 50—; la
ladera ``100 + 0,25·y + 0,0625·x``; los perfiles ``EXPL_10_60_6`` y ``REST_5_35_6`` con ancla 125 m;
la capa de fondos con un polígono de (20, 50) a (44, 80) a 105 m y la de zonas de restauración por
relleno, de (26, 36) a (46, 46)). El recinto, a mano: los centros con ``9 ≤ x ≤ 91`` e
``11 ≤ y ≤ 91`` menos los 5 × 5 de la zona sin corte, 1.697 celdas. Los parámetros de D-5, **los de
por defecto** (1 m y 0,2 ha: el proyecto no los da). Las pruebas, en el orden de sus letras sobre el
mismo estado:

- **E3** (a; RF-014-12 a RF-014-14, RF-014-29; M3): la cantera «Corta» con la final ``REST_5_35_6``
  primero y la explotación ``EXPL_10_60_6`` anclada al fondo de cada muro, y «Corta B» con
  «explotación primero», calculadas y creadas con la orden; releídas: ``final ≤ explotación ≤
  terreno`` en todas las celdas, la ladera fuera del recinto y la regla de RF-014-13 entre las dos,
  bit a bit.
- **E3** (b; RF-014-15, RF-014-16; CE-014-04): la clasificación registrada de las dos, cuadrada con
  la cubicación de la 011 (``reserves.volumes.volume_steps`` sobre las rejillas registradas, con la
  zona de relleno y los sectores como dominios): sus cifras CALCULADO a ≤ 10⁻⁶ relativo, en total y
  por sector, y su rejilla de clases, la regla a mano.
- **E4** (c; RF-014-17; M4): con la explotación sembrada en toda la ladera (queda sin explotar y la
  final, por debajo), el resumen avisa en ámbar de la zona de desdoblado sobre terreno sin explotar
  de más de 0,2 ha, con su nota, y ofrece «Explotación hasta la final»; se crea «Sin el modo».
- **E4** (d; RF-014-18; CE-014-05; M4): con «todas las zonas avisadas», «Hasta la final» baja la
  explotación en esas zonas a la cota de ancla de su perfil inmediatamente por encima de la final
  (sin quedar nunca por debajo de ella ni pasar del terreno) y lo que pasa a la explotación
  (``des.to_final_m3``, en total y por sector) es lo que cubica la 011 entre la explotación «Sin el
  modo» y la de «Hasta la final», y la diferencia de las celdas a mano; su clasificación, cuadrada
  con la 011.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import math
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.trees import remove_tree

VIEW_PROPERTY = "geoblender_design"
QUARRY_TYPE = "des.quarry"
REASON = "Prueba del hito H2 de la cantera"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de explotación"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 100.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
LEGAL = (6.0, 6.0, 94.0, 94.0)
PERIMETER = (4.0, 10.0, 96.0, 96.0)
NO_CUT = (30.0, 30.0, 40.0, 40.0)
SECTORS = {"Sector oeste": (0.0, 0.0, 50.0, 100.0), "Sector este": (50.0, 0.0, 100.0, 100.0)}
SECTOR_CODES = ("sector_1", "sector_2")
CLOSED_AT = "2026-11-12T10:00:00Z"
LAYERS_TYPE = "gis.test_quarry_h2"
FLOORS_LAYER = "gis_fea_fondos"
FLOOR_BOX = (20.0, 50.0, 44.0, 80.0)
FLOOR_M = 105.0
FILL_LAYER = "gis_fea_relleno"
FILL_BOX = (26.0, 36.0, 46.0, 46.0)
EXPL, REST = "EXPL_10_60_6", "REST_5_35_6"
ANCHOR_M, EXPL_HEIGHT_M, EXPL_FACE_DEG = 125.0, 10.0, 60.0
FIRST, SECOND = "Corta", "Corta B"
WITHOUT, DOWN = "Sin el modo", "Hasta la final"
RELATIVE = 1e-6
"""La tolerancia frente a la cubicación de la 011 (RF-014-15, CE-014-04)."""


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
    return np.meshgrid(STEP_M * index + STEP_M / 2, SIZE_M - (STEP_M * index + STEP_M / 2))


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda (exacta en binario)."""
    x, y = centers()
    return 100.0 + 0.25 * y + 0.0625 * x


def inside(box: tuple[float, float, float, float]) -> np.ndarray:
    """Las celdas con el centro dentro del rectángulo local ``box``."""
    x, y = centers()
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def hand_area() -> np.ndarray:
    """El recinto a mano (véase el módulo)."""
    return inside((8.0, 10.0, 92.0, 92.0)) & ~inside(NO_CUT)


class QuarryH2Test(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera, para toda la clase (las pruebas,
    en el orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.thickness: dict[str, float] = {}  # el espesor mínimo de cada cantera creada
        cls.kept: dict[str, np.ndarray] = {}  # lo que una prueba deja a la siguiente
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t24-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.surfaces = _module("design.surfaces")
        cls.i18n = _module("core.i18n")
        cls.volumes = _module("reserves.volumes")
        cls.rsurfaces = _module("reserves.surfaces")
        cls.polygons = _module("reserves.polygons")
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
        cls.declare_sectors()
        for code in SECTOR_CODES:
            cls.close_search(code)
        cls.ground = cls.write_grid("Ladera", ground())
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.write_layer(FLOORS_LAYER, ((ring(FLOOR_BOX),),), {"cota": FLOOR_M})
        cls.write_layer(FILL_LAYER, ((ring(FILL_BOX),),), {})
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        for name, (height, face, berm) in ((EXPL, ("10", "60", "6")), (REST, ("5", "35", "6"))):
            assert bpy.ops.geoblender.des_save_bench_profile(
                name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
                scope="PROJECT", height=height, face=face, berm=berm, anchor="125") == {"FINISHED"}
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y una zona sin corte."""
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
    def declare_sectors(cls) -> None:
        """Los dos sectores de búsqueda (``core_sector``)."""
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
    def close_search(cls, code: str) -> None:
        """Cierra la búsqueda de intocables del sector ``code``, como la orden de la 012."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, code,
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_layer(cls, name: str, entity: tuple[tuple[np.ndarray, ...], ...],
                    numbers: dict[str, float]) -> None:
        """Una capa de polígonos ``gis_fea_…`` de una entidad con el campo ``nombre`` y los campos
        numéricos ``numbers`` (``DOUBLE``), como la deja la importación de la 006."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
                   *(vector.FieldColumn(field, field, "DOUBLE") for field in numbers))
        values = {"nombre": ("Entidad 1",), **{field: (value,) for field, value in numbers.items()}}
        layer = vector.FeatureLayer("polygon", (1,), (entity,), columns, values)
        rows = gis_store.feature_rows(layer, srs)
        names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f"geom {layer.geometry_type}, {names})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de prueba de la cantera")

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
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def name(self, family: str, quarry: str) -> str:
        return str(self.dprov.dataset_name(family, quarry))

    def read(self, family: str, quarry: str) -> np.ndarray:
        """Las cotas (o los códigos) de la rejilla ``family`` de la cantera ``quarry``, releídas."""
        return self.surfaces.read_surface(self.project, self.name(family, quarry),
                                          version_uid=self.v01.uid).values

    def e3_form(self, **values: Any) -> dict[str, Any]:
        """E3: la final con ``REST_5_35_6`` y la explotación con ``EXPL_10_60_6`` anclada al fondo
        de cada muro, las dos en la coronación y las zonas a sostener; los fondos y las zonas de
        relleno."""
        return {"name": FIRST, "start": self.ground, "final_profile": REST,
                "exploitation_profile": EXPL, "exploitation_anchor": "NEAREST_FLOOR",
                "floors_layer": FLOORS_LAYER, "fill_layer": FILL_LAYER, "in_steps": False,
                **values}

    def e4_form(self, **values: Any) -> dict[str, Any]:
        """E4: la final de E3; la explotación con ``EXPL_10_60_6`` sembrada en toda la ladera del
        dominio (no excava: queda sobre terreno sin explotar), con la confirmación de esas
        semillas, que caen fuera de la coronación (``confirm_outside``, T43)."""
        return {"name": WITHOUT, "start": self.ground, "final_profile": REST,
                "exploitation_profile": EXPL, "exploitation_seeds": "SURFACE",
                "exploitation_surface": self.ground, "exploitation_zone": "domain",
                "floors_layer": FLOORS_LAYER, "fill_layer": FILL_LAYER, "in_steps": False,
                "confirm_outside": True, **values}

    def calculate(self, form: dict[str, Any]) -> Any:
        """«Calcular» desde un guion: el cálculo abierto, con su resumen en la vista."""
        self.assertEqual(bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", **form),
                         {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        self.assertEqual(self.view.summary_title, f"Cantera «{form['name']}» en V01")
        self.thickness[form["name"]] = held.outcome.classes.min_thickness_m
        return held

    def create(self) -> None:
        """«Crear» el cálculo abierto: la misma orden con ``confirm=True``."""
        self.assertEqual(bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", confirm=True),
                         {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.view.summary_title, "")

    def summary(self) -> list[tuple[str, bool]]:
        return [(line.name, bool(line.alert)) for line in self.view.summary]

    def figures(self, quarry: str) -> dict[tuple[str, str | None, str | None], float]:
        """Las cifras registradas de la cantera ``quarry``: (clave, sector, superficie) → valor,
        todas CALCULADO."""
        (operation,) = self.rows("SELECT operation_uid FROM gb_dataset WHERE name = ? AND "
                                 "status = 'current'", self.name("exp", quarry))
        found = {}
        for key, value, kind, scope in self.rows(
                "SELECT key, value, kind, scope FROM gb_figure WHERE operation_uid = ?",
                operation[0]):
            self.assertEqual(kind, "CALCULADO")
            where = json.loads(scope)
            found[(key, where.get("sector"), where.get("surface"))] = float(value)
        return found

    def source(self, family: str, quarry: str) -> Any:
        """La rejilla registrada como superficie de la cubicación de la 011."""
        dataset = self.ground if family == "ground" else self.name(family, quarry)
        return self.rsurfaces.surface_source(
            self.project, self.rsurfaces.SurfaceRef(dataset=dataset), version_uid=self.v01.uid)

    def domains(self, name: str, boxes: dict[str, tuple[float, float, float, float]]) -> Any:
        return self.volumes.DomainLayer(name, "nombre", tuple(
            self.polygons.Polygon(fid, value, (ring(box),))
            for fid, (value, box) in enumerate(boxes.items(), start=1)))

    def cubicate(self, upper: Any, lower: Any, thickness: float, layer: Any = None) -> Any:
        """La cubicación de la 011 de ``upper`` frente a ``lower`` (fuentes de la 011) con el
        espesor mínimo y, si se da, la capa de dominios: su ``KernelResult``."""
        refs = self.rsurfaces.SurfaceRef
        request = self.volumes.VolumeRequest("Comprobación", refs(dataset="arriba"),
                                             refs(dataset="abajo"), domains=layer,
                                             min_thickness_m=thickness)
        found = None
        for found in self.volumes.volume_steps(request, {"start": upper, "final": lower}):
            pass
        return found.result.kernel

    def close(self, found: float, expected: float, what: str) -> None:
        self.assertLessEqual(abs(found - expected), RELATIVE * abs(expected),
                             f"{what}: {found!r} frente a {expected!r}")

    def check_with_the_011(self, quarry: str) -> dict[str, float]:
        """La clasificación registrada de ``quarry`` frente a la cubicación de la 011 de sus
        rejillas registradas: las cifras de volumen y de área del total y de cada sector, y la
        rejilla de clases con la regla a mano. Devuelve las cifras del total (una ayuda: las
        pruebas que la usan citan sus requisitos)."""
        e = self.thickness[quarry]
        found = self.figures(quarry)
        start, upper, lower = (self.source("ground", quarry), self.source("exp", quarry),
                               self.source("fin", quarry))
        by_fill = self.cubicate(upper, lower, e, self.domains("Relleno", {"relleno": FILL_BOX}))
        by_sector = self.cubicate(upper, lower, e, self.domains("Sectores", dict(
            zip(SECTOR_CODES, SECTORS.values(), strict=True))))
        dug = self.cubicate(start, upper, e, self.domains("Sectores", dict(
            zip(SECTOR_CODES, SECTORS.values(), strict=True))))
        self.assertEqual((float(by_fill.fill_m3[0]), float(dug.fill_m3[0])), (0.0, 0.0))

        def moved(result: Any, row: int) -> float:
            return float(result.area_m2[row] - result.still_area_m2[row]) / 10_000.0

        fill = found[("des.restoration_fill_m3", None, None)]
        unsplit = found[("des.unsplit_m3", None, None)]
        self.close(fill, float(by_fill.cut_m3[1]), "relleno")
        self.close(unsplit, float(by_fill.cut_m3[by_fill.outside]), "desdoblado")
        self.close(found[("des.restoration_fill_area_ha", None, None)], moved(by_fill, 1),
                   "área del relleno")
        self.close(found[("des.unsplit_area_ha", None, None)], moved(by_fill, by_fill.outside),
                   "área del desdoblado")
        self.close(found[("des.exp_cut_m3", None, None)], float(dug.cut_m3[0]), "excavación")
        self.close(found[("des.exp_cut_area_ha", None, None)], moved(dug, 0),
                   "área de la excavación")
        for row, code in enumerate(SECTOR_CODES, start=1):
            self.close(found[("des.unsplit_m3", code, None)]
                       + found[("des.restoration_fill_m3", code, None)],
                       float(by_sector.cut_m3[row]), f"Δ de {code}")
            self.close(found[("des.exp_cut_m3", code, None)], float(dug.cut_m3[row]),
                       f"excavación de {code}")
        z, final, exploitation = ground(), self.read("fin", quarry), self.read("exp", quarry)
        area = hand_area()
        delta = exploitation - final
        hand = np.where(delta > e, np.where(inside(FILL_BOX), 2.0, 1.0), 0.0)
        classes = self.read("cls", quarry)
        self.assertTrue(np.array_equal(classes[area], hand[area]))
        self.assertTrue(bool(np.all(np.isnan(classes[~area]))))
        self.assertTrue(bool(np.all(z[area] - exploitation[area] >= 0.0)))
        return {"unsplit": unsplit, "fill": fill,
                "cut": found[("des.exp_cut_m3", None, None)]}

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_e3_the_two_surfaces_with_both_orders(self) -> None:
        """E3, RF-014-12 a RF-014-14, RF-014-29 (M3): «Corta» («final primero») y «Corta B»
        («explotación primero») se calculan con la orden real (el resumen dice su orden) y se crean
        con su confirmación; releídas del proyecto: ``final ≤ explotación ≤ terreno`` en todas las
        celdas, sin tolerancia; fuera del recinto, la ladera; la regla de RF-014-13 entre las dos,
        bit a bit (``explotación(final primero) = máx(explotación(explotación primero),
        final(final primero))`` y ``final(explotación primero) = mín(final(final primero),
        explotación(explotación primero))``), con celdas que la regla cambió."""
        first = self.calculate(self.e3_form()).outcome
        self.assertTrue(self.summary()[0][0].startswith(
            "Orden del diseño: Primero la superficie final · la regla de orden cambió "))
        self.create()
        second = self.calculate(self.e3_form(name=SECOND, order="EXPLOITATION_FIRST")).outcome
        self.assertTrue(self.summary()[0][0].startswith(
            "Orden del diseño: Primero la superficie de explotación"))
        self.create()
        self.assertGreater(first.adjusted, 0)
        self.assertEqual(first.adjusted, second.adjusted)
        z, area = ground(), hand_area()
        self.assertEqual(int(np.count_nonzero(area)), 42 * 41 - 5 * 5)
        final_a, exploitation_a = self.read("fin", FIRST), self.read("exp", FIRST)
        final_b, exploitation_b = self.read("fin", SECOND), self.read("exp", SECOND)
        for final, exploitation in ((final_a, exploitation_a), (final_b, exploitation_b)):
            self.assertTrue(bool(np.all(final <= exploitation)))  # RF-014-14, sin tolerancia
            self.assertTrue(bool(np.all(exploitation <= z)))
            self.assertTrue(np.array_equal(final[~area], z[~area]))  # fuera, la ladera
            self.assertTrue(np.array_equal(exploitation[~area], z[~area]))
        self.assertTrue(np.array_equal(exploitation_a, np.maximum(exploitation_b, final_a)))
        self.assertTrue(np.array_equal(final_b, np.minimum(final_a, exploitation_b)))
        self.assertTrue(bool(np.any(exploitation_a != exploitation_b)))
        self.assertTrue(bool(np.any(final_a != final_b)))
        self.assertTrue(np.array_equal(exploitation_a, first.exploitation_grid))  # lo creado
        self.assertTrue(np.array_equal(final_b, second.final_grid))

    def test_b_e3_the_classification_squares_with_the_011(self) -> None:
        """E3, RF-014-15, RF-014-16, CE-014-04 (M3): la clasificación registrada de las dos canteras
        es la de la cubicación de la 011 sobre sus rejillas registradas (el desdoblado, el relleno
        de restauración en su zona, la excavación de la explotación y sus áreas, en total y por
        sector, a ≤ 10⁻⁶ relativo), y su rejilla de clases, la regla a mano; hay desdoblado y
        relleno, los dos órdenes dan la misma diferencia y «explotación primero» excava más."""
        first = self.check_with_the_011(FIRST)
        second = self.check_with_the_011(SECOND)
        self.assertGreater(first["unsplit"], 0.0)
        self.assertGreater(first["fill"], 0.0)
        self.assertEqual((first["unsplit"], first["fill"]), (second["unsplit"], second["fill"]))
        self.assertGreater(second["cut"], first["cut"])

    def test_c_e4_the_warning_of_unsplit_on_unexploited_ground(self) -> None:
        """E4, RF-014-17 (error 60; M4): con la explotación en toda la ladera, el resumen avisa en
        ámbar de las zonas de desdoblado sobre terreno sin explotar de más de 0,2 ha (los valores
        de D-5 por defecto, 1 m y 0,2 ha), con una nota por zona, y ofrece «Explotación hasta la
        final»; dice «Explotación hasta la final: no». Se crea «Sin el modo»: su explotación es la
        ladera."""
        held = self.calculate(self.e4_form())
        unsplit = held.outcome.unsplit
        self.assertEqual((unsplit.threshold_m, unsplit.min_area_ha), (1.0, 0.2))
        self.assertGreaterEqual(len(unsplit.zones), 1)
        self.assertTrue(all(zone.area_ha >= 0.2 for zone in unsplit.zones))
        shown = self.summary()
        warning = [text for text, alert in shown
                   if alert and text.startswith("La explotación no llega a la final en ")]
        self.assertEqual(len(warning), 1, shown)
        self.assertIn("«Explotación hasta la final»", warning[0])
        self.assertEqual(len([text for text, _alert in shown if text.startswith("Zona ")]),
                         len(unsplit.zones))
        self.assertIn(("Explotación hasta la final: no", False), shown)
        self.kept["warned"] = unsplit.warned.copy()
        self.create()
        self.assertTrue(np.array_equal(self.read("exp", WITHOUT), ground()))  # sin explotar

    def test_d_e4_down_to_the_final_in_the_warned_zones(self) -> None:
        """E4, RF-014-18, CE-014-05 (M4): «Hasta la final», con «todas las zonas avisadas», dice en
        el resumen lo que pasa a la explotación y baja la explotación en esas zonas hasta la cota
        de ancla de ``EXPL_10_60_6`` inmediatamente por encima de la final (``125 + 10·⌈(final −
        125)/10⌉``: alguna celda justo en ella), sin quedar por debajo de ella en ninguna celda
        (T62: la cara baja desde la cota de arriba), con la transición a la cara de su perfil (A9
        a mano con la descendente y la ascendente *chamfer* de la 013, a ≤ 10⁻⁹ m), nunca por
        debajo de la final ni por encima del terreno; la final no cambia; lo que pasa a la
        explotación, ``des.to_final_m3`` en total y por sector, es la diferencia de las celdas a
        mano y lo que cubica la 011 entre la explotación «Sin el modo» y esta, sin terraplén; y la
        clasificación de las dos canteras cuadra con la 011. Tras el modo, ninguna línea del
        resumen lo vuelve a recomendar (T57, hallazgo F-19; HU-014-4, RF-014-17): lo que queda en
        las zonas tratadas (aquí, menos de un banco en zonas que no pasan del área mínima) solo
        tendría su propio aviso, sin ofrecerlo."""
        held = self.calculate(self.e4_form(name=DOWN, to_final="WARNED"))
        self.assertIsNotNone(held.outcome.to_final)
        shown = self.summary()
        moved = [text for text, _alert in shown
                 if text.startswith("«Explotación hasta la final» en ")]
        self.assertEqual(len(moved), 1, shown)
        unsplit = held.outcome.unsplit
        self.assertEqual(unsplit.zones, ())  # todas las avisadas se trataron
        left = [text for text, alert in shown
                if alert and text.startswith("Tras «Explotación hasta la final», la explotación "
                                             "sigue sin llegar a la final en ")]
        self.assertEqual(len(left), 1 if unsplit.remaining else 0, shown)
        self.assertFalse(any("Use «Explotación hasta la final»" in text for text, _alert in shown),
                         shown)
        self.assertFalse(any(text.startswith("La explotación no llega a la final")
                             for text, _alert in shown), shown)
        self.assertTrue(bool(np.all(self.kept["warned"][unsplit.warned])))
        self.create()
        z, warned = ground(), self.kept["warned"]
        before, after = self.read("exp", WITHOUT), self.read("exp", DOWN)
        final = self.read("fin", DOWN)
        self.assertTrue(np.array_equal(final, self.read("fin", WITHOUT)))
        self.assertTrue(bool(np.all(final <= after)))
        self.assertTrue(bool(np.all(after <= before)))
        self.assertTrue(bool(np.all(after <= z)))
        level = ANCHOR_M + EXPL_HEIGHT_M * np.ceil((final - ANCHOR_M - 1e-9) / EXPL_HEIGHT_M)
        floor = np.minimum(level, before)
        self.assertGreaterEqual(float(np.min(after[warned] - floor[warned])), -1e-3)  # T62
        self.assertTrue(bool(np.any(after[warned] == level[warned])))
        self.assertTrue(bool(np.any(after[warned] > final[warned] + 1.0)))  # menos de un banco
        self.assertTrue(np.array_equal(after[~hand_area()], z[~hand_area()]))
        # A9 a mano (T62): la descendente de la 013 de las cotas de ancla del recinto con la cara de
        # EXPL_10_60_6 (60°, malla 1,0); en las zonas, máx(final, mín(explotación, z, ENV↓)); la
        # ascendente de lo que queda en ellas y, en el resto del recinto, máx(final,
        # mín(explotación, ENV↑)); ≤ z.
        envelopes = _module("design.envelopes")
        grid = _module("gis.grid").project_grid(self.project.record.window, STEP_M)
        slope = envelopes.SlopeField(math.tan(math.radians(EXPL_FACE_DEG)))
        area = hand_area()
        zone = warned & area
        falling = rising = None
        for falling in envelopes.chamfer_steps(np.where(area & np.isfinite(final), level, np.inf),
                                               grid, slope, "down", name="A9"):
            pass
        kept = np.minimum(np.maximum(final, np.minimum(before, falling.result.grid)), z)
        for rising in envelopes.chamfer_steps(np.where(zone, kept, np.inf), grid, slope, "up",
                                              name="A9"):
            pass
        expected = np.where(zone, kept, np.where(
            area, np.maximum(final, np.minimum(before, rising.result.grid)), before))
        np.testing.assert_allclose(after, np.minimum(expected, z), rtol=0.0, atol=1e-9)
        found = self.figures(DOWN)
        passed = found[("des.to_final_m3", None, None)]
        self.assertGreater(passed, 0.0)
        cell = STEP_M * STEP_M
        self.close(passed, float(np.sum(before - after)) * cell, "lo que pasa, a mano")
        x, _y = centers()
        layer = self.domains("Sectores", dict(zip(SECTOR_CODES, SECTORS.values(), strict=True)))
        cubication = self.cubicate(self.source("exp", WITHOUT), self.source("exp", DOWN), 0.0,
                                   layer)
        self.assertEqual(float(cubication.fill_m3[0]), 0.0)
        self.close(passed, float(cubication.cut_m3[0]), "lo que pasa (011)")
        for row, (code, mine) in enumerate(zip(SECTOR_CODES, (x < 50.0, x > 50.0), strict=True),
                                           start=1):
            by_hand = float(np.sum((before - after)[mine])) * cell
            value = found.get(("des.to_final_m3", code, None), 0.0)
            self.close(value, by_hand, f"lo que pasa en {code}, a mano")
            self.close(value, float(cubication.cut_m3[row]), f"lo que pasa en {code} (011)")
        self.assertTrue(math.isclose(passed, held.outcome.to_final.volume_m3, rel_tol=1e-12))
        self.check_with_the_011(WITHOUT)
        self.check_with_the_011(DOWN)


if __name__ == "__main__":
    unittest.main()
