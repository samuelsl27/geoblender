# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista previa de semillas, dominios y restricciones (spec 013, T25; HU-013-1; RF-013-01,
RF-013-02, RF-013-03, RF-013-33; RNF-013-05; plan 013 §5.5, D-29; comprobación manual M1; principio 8).

La vista previa de la Vista 3D (``bl.draw.design``, ``geoblender.des_toggle_preview``) es un manejador
de dibujo sin objetos ni escritura: lo que dibuja se prueba en sus lotes (los puntos de las
semillas con su color por cota, las rayas del dominio, el borde de los sectores, los contornos de las
restricciones) y en sus textos en píxeles (el resumen, la leyenda y los nombres), no en píxeles de
pantalla (``docs/trampas.md`` §3: sin GPU en ``blender -b``). Un proyecto por clase (ventana de
60 × 60 m con celdas de 2 m, V01 y V02, un límite legal, un perímetro y una torre, dos sectores con la
búsqueda de intocables cerrada solo en el primero, y una ladera que sube 0,1 m por metro al este desde
100 m) y las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-013-33 (a): la orden es la real (no la provisional), con el ``poll`` de las órdenes de Diseño
  (dice por qué no está disponible), salvo para quitar la vista previa; la propiedad de la ventana la
  activa y la quita; su diálogo propone la primera superficie y dibuja lo que se previsualiza.
- RF-013-03 (b): sin las máscaras compiladas solo se ven los contornos de las restricciones y el
  resumen lo dice; no escribe nada en el proyecto (sus ficheros, bit a bit, y sus operaciones no
  cambian) y quitarla lo quita todo.
- RF-013-01, RF-013-02, RF-013-03 (c): con las máscaras compiladas, las semillas del sector 1 (una por
  celda, en su cota y coloreadas por ella), el dominio de trabajo en trama sobre la ladera, el borde de
  los dos sectores (el segundo, en ámbar, con su búsqueda pendiente) y el resumen son los de
  ``design`` en el idioma de Geoblender, con los avisos en alerta.
- RF-013-03, RNF-013-05 (d): «semillas en toda la ladera»: el aviso de las semillas fuera del dominio y
  su aclarado cuando pasan del tope de puntos.
- RF-013-03, RNF-013-05 (e): en píxeles, el resumen arriba a la izquierda (partido al ancho, los
  avisos en ámbar), la leyenda y los nombres; el dibujo de los puntos y de las líneas con ``gpu`` (un
  lote cada uno, creado una vez) deja su estado como estaba.
- RF-013-03 (f): cambiar de versión activa la rehace; conmutar a la interfaz de Blender o cerrar el
  proyecto la quita.
- RF-013-33 (g): el diálogo y la orden rechazan lo que falta (la cota fija, los sectores marcados) sin
  activarla y quitarla informa; una vista previa que el cálculo rechaza avisa con el motivo y se quita.
- RF-013-01, RF-013-02 (h; H3, hallazgo 1): el resumen empieza a la derecha de la barra de herramientas
  de la Vista 3D cuando se superpone a la región (a escala 1,0 y 1,25), y sin ella queda donde estaba.
- RF-014-04 (j; spec 014, T23 y T44; plan 014 §5.5; M1): el botón «Vista previa» del diálogo de
  «Cantera con dos superficies…» (la misma orden con ``preview``, con todo lo pedido en el diálogo)
  activa la vista previa con su diseño (``QuarryPlan``: su ``QuarryRequest`` con dos fondos, una zona
  a conservar y un corredor con rasante, en capas del proyecto), sin calcular ni escribir nada; lo que
  falta del diálogo se rechaza sin activarla, y pulsarlo otra vez la cambia por la nueva. La vista
  previa enseña además el recinto excavable (su borde), la coronación (puntos en el color de las
  semillas, por cota), las zonas a sostener, los fondos con su cota, las zonas a conservar que siembran
  los techos y los corredores, cada uno con su lote, sus nombres y su fila en la leyenda (en los dos
  idiomas), todo igual a lo que dice ``design.preview`` y con el borde de cada pieza, lado a lado,
  igual al de sus celdas; conmutar a la interfaz de Blender (``Ctrl+F10``) la quita con la de la
  cantera activa; el anillo, el del parámetro o el pedido por guion; sin máscaras al día, solo los
  contornos y el aviso; una capa que el cálculo rechaza avisa y la quita; y no escribe nada.
- Principio 8 (z): desactivar Geoblender con la vista previa activa quita el manejador, los avisos y
  el temporizador y deja la huella de Blender como al principio de la sesión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import unittest
import uuid
from collections.abc import Generator
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

TOGGLE = "geoblender.des_toggle_preview"
WM_PROPERTY = "geoblender_design_preview"
VIEW_PROPERTY = "geoblender_design"
REASON = "Prueba de la vista previa del diseño"
PERSON = "Samuel (IMGA)"
CLOSED_AT = "2026-11-03T10:00:00Z"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
TOWER = (20.0, 20.0, 26.0, 26.0)
SECTORS = {"Sector 1": (2.0, 2.0, 30.0, 56.0), "Sector 2": (30.0, 2.0, 56.0, 56.0)}
SEEDS_IN_SECTOR_1 = 14 * 27  # centros de celda (x = 3, 5 … 29; y = 3, 5 … 55) dentro del sector 1
SIZE = (1920, 1001)  # la región, en píxeles (la ventana de la 019: RF-019-19)
HALF = 60.0  # la vista desde arriba: 120 m de ancho
MAX_PUMPS = 20_000

# La cantera con dos superficies (spec 014, T23): capas del proyecto, en coordenadas de la prueba.
LAYERS_TYPE = "gis.test_preview_layers"
FLOORS_LAYER = "gis_fea_fondos"
FLOOR_BOXES = ((8.0, 30.0, 16.0, 46.0), (24.0, 36.0, 34.0, 46.0))
FLOOR_LEVELS = (95.0, 96.0)
FLOOR_CELLS = (4 * 8, 5 * 5)  # centros x = 9 … 15, y = 31 … 45; x = 25 … 33, y = 37 … 45
CONSERVE_LAYER = "gis_fea_conservar"
CONSERVE_BOX = (8.0, 8.0, 16.0, 16.0)
CORRIDORS_LAYER = "gis_fea_corredores"
CORRIDOR_AXIS = ((40.0, 8.0), (40.0, 30.0))
CORRIDOR_FIELDS = {"ancho": 4.0, "cota_inicial": 97.0, "pendiente": 5.0}
CORRIDOR_CELLS = 2 * 11  # x = 39 y 41; y = 9 … 29 (σ = 1 … 21 m: 97,05 a 98,05 m)
AREA_CELLS = 22 * 22 - 5 * 5  # x, y = 7 … 49 menos la torre con su resguardo (x, y = 19 … 27)
CROWN_CELLS = 28 * 28 - 22 * 22 + 5 * 5  # el anillo de 3 celdas y el agujero de la torre
QUARRY = "geoblender.des_design_quarry"
PROFILE = "REST_5_35_6"  # el perfil de banco de las dos superficies de la cantera (T44)
QUARRY_FIELDS = {  # los campos del diálogo de la cantera, con lo que pone por defecto (T44)
    "name": "", "start": "none", "order": "FINAL_FIRST", "final_seeds": "CROWN",
    "final_surface": "none", "final_zone": "none", "final_elevation": "", "final_profile": "",
    "final_anchor": "FIXED", "final_anchor_grid": "none", "final_metric": "CHAMFER5",
    "exploitation_seeds": "CROWN", "exploitation_surface": "none", "exploitation_zone": "none",
    "exploitation_elevation": "", "exploitation_profile": "", "exploitation_anchor": "FIXED",
    "exploitation_anchor_grid": "none", "exploitation_metric": "CHAMFER5", "floors_layer": "none",
    "floors_field": "cota", "conserve": "none", "corridors_layer": "none",
    "corridors_width_field": "ancho", "corridors_level": "FIXED", "corridors_level_field": "cota",
    "corridors_start_field": "cota_inicial", "corridors_gradient_field": "pendiente",
    "fill_layer": "none", "water_layer": "none", "water_field": "cota", "to_final": "NONE",
    "to_final_layer": "none"}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def top_view(centre: tuple[float, float]) -> np.ndarray:
    """La matriz de una vista desde arriba (ortográfica) de 2·:data:`HALF` m de ancho y el alto
    de la región, centrada en ``centre`` (locales)."""
    width, height = SIZE
    sx, sy = 1.0 / HALF, width / (height * HALF)
    return np.array([[sx, 0.0, 0.0, -centre[0] * sx],
                     [0.0, sy, 0.0, -centre[1] * sy],
                     [0.0, 0.0, -0.001, 0.0],
                     [0.0, 0.0, 0.0, 1.0]])


def finish(steps: Generator[None, None, Any]) -> Any:
    """Los pasos de un generador hasta el final: su ``StopIteration.value``."""
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def path(points: tuple[tuple[float, float], ...]) -> np.ndarray:
    """El camino absoluto de los puntos ``points`` (coordenadas de la prueba)."""
    return np.array([(WEST + x, SOUTH + y) for x, y in points], dtype=np.float64)


def unit_edges(values: np.ndarray) -> set[tuple[str, int, int]]:
    """Los lados de celda del borde de ``values`` por fuerza bruta: ``("h", i, j)`` es el lado de
    arriba de la fila ``i`` (``i`` = filas: el de abajo de la última) en la columna ``j``, y ``("v",
    i, j)`` el lado izquierdo de la columna ``j`` en la fila ``i``, cuando las dos celdas que separa
    (fuera de la rejilla, 0) tienen valores distintos."""
    rows, cols = values.shape

    def at(i: int, j: int) -> Any:
        return values[i, j] if 0 <= i < rows and 0 <= j < cols else 0

    found = {("h", i, j) for i in range(rows + 1) for j in range(cols) if at(i - 1, j) != at(i, j)}
    found |= {("v", i, j) for i in range(rows) for j in range(cols + 1) if at(i, j - 1) != at(i, j)}
    return found


def covered_edges(segments: np.ndarray, grid: Any) -> set[tuple[str, int, int]]:
    """Los lados de celda de ``grid`` que cubren unos segmentos ``(k, 2, 2)`` absolutos que van por
    los lados de celda (los del borde, partidos o no): los de su línea con el punto medio dentro."""
    found: set[tuple[str, int, int]] = set()
    for (x0, y0), (x1, y1) in np.asarray(segments, dtype=np.float64).tolist():
        if abs(y0 - y1) < 1e-6:
            i = int(round((grid.north - y0) / grid.dy))
            low, high = sorted(((x0 - grid.west) / grid.dx, (x1 - grid.west) / grid.dx))
            found |= {("h", i, j) for j in range(grid.ncols) if low - 1e-6 <= j + 0.5 <= high + 1e-6}
        else:
            j = int(round((x0 - grid.west) / grid.dx))
            low, high = sorted(((grid.north - y0) / grid.dy, (grid.north - y1) / grid.dy))
            found |= {("v", i, j) for i in range(grid.nrows) if low - 1e-6 <= i + 0.5 <= high + 1e-6}
    return found


class DesignPreviewTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, dos sectores
    (el segundo con la búsqueda pendiente) y una ladera para toda la clase (las pruebas, en el orden
    de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d25-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.switcher = _module("bl.ui.switcher")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.masks_store = _module("gis.masks.store")
        cls.dmodel = _module("design.model")
        cls.dsteps = _module("design.steps")
        cls.i18n = _module("core.i18n")
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
        cls.declare()
        cls.declare_sectors()
        cls.close_search("sector_1", 1)
        cls.ground = cls.write_slope("Ladera")
        cls.flat = cls.write_slope("Plana", base=50.0, rise=0.0)  # la más reciente, no la de las semillas
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        cls.panels.fill_sectors(cls.project)  # las zonas «sector:…» del diálogo salen de aquí
        cls.panels.refresh_choices(cls.project)
        cls.design = _module("bl.draw.design")
        cls.constraints = _module("bl.draw.constraints")

    @classmethod
    def declare(cls) -> None:
        """El límite legal, el perímetro de actuación y una torre intocable (como las dejará la
        orden de la 012)."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 3), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.UNTOUCHABLE, "Torre", TOWER)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 2.0,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                   srs_id=cls.project.record.crs_epsg)

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
        """Cierra la búsqueda de intocables de un sector (con su huella): queda sin la marca de
        pendiente."""
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
    def write_slope(cls, name: str, *, base: float = 100.0, rise: float = 0.1) -> str:
        """Una rejilla del proyecto de la ventana que sube ``rise`` m por metro al este desde
        ``base`` m (como la deja «Rejilla del proyecto desde un MDT»); el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        x, _y = grid.centers()
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, base + rise * (x - WEST), crs,
                                                          vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

    @classmethod
    def write_layer(cls, name: str, kind: str, entities: tuple[Any, ...],
                    numbers: dict[str, tuple[float, ...]]) -> None:
        """Una capa ``gis_fea_…`` con las entidades ``entities`` (cada una, sus partes con sus anillos
        o su camino, absolutos), el campo ``nombre`` y los campos numéricos ``numbers`` (``DOUBLE``,
        un valor por entidad), como la deja la importación de la 006."""
        gis_store, vector = _module("gis.store"), _module("gis.vector")
        datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
                   *(vector.FieldColumn(field, field, "DOUBLE") for field in numbers))
        fids = tuple(range(1, len(entities) + 1))
        values = {"nombre": tuple(f"Entidad {fid}" for fid in fids),
                  **{field: tuple(found) for field, found in numbers.items()}}
        layer = vector.FeatureLayer(kind, fids, tuple(entities), columns, values)
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
                immutable=False),), message="Capa de prueba de la vista previa de la cantera")

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
        if self.design.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.design.disable()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas de la prueba (desde el SO de la ventana) respecto al GeoOrigin."""
        return (WEST + x - self.origin.x0, SOUTH + y - self.origin.y0)

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que la vista previa no cambia)."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        with self.project.read() as conn:
            return int(conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0])

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no
        corren) hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.design.tick() is None:
                built = self.design.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def show(self, **values: Any) -> set[str]:
        """Lanza la orden (sin diálogo) sobre la ladera con lo pedido en ``values``."""
        form = {"seeds_from": "SURFACE", "surface": self.ground, "zone": "none", **values}
        return bpy.ops.geoblender.des_toggle_preview("EXEC_DEFAULT", **form)

    def compile_masks(self, version: Any) -> None:
        """La compilación de ``version`` como la lanzará la orden (``begin_compile`` y sus pasos
        hasta el final)."""
        handle = self.masks_store.begin_compile(self.project, version=version.uid)
        for _step in self.masks_store.compile_run(self.project, handle):
            pass
        self.project.refresh_header()

    def truth(self, plan: Any, version: Any | None = None) -> Any:
        """Lo que dice ``design`` de ``plan`` (``design.steps.preview_steps``), sin pasar por el
        dibujo."""
        found = None
        for step in self.dsteps.preview_steps(self.project, plan, (version or self.v01).uid):
            found = step.result if step.result is not None else found
        return found

    def sector_1_plan(self) -> Any:
        return self.design.Plan(self.dmodel.SeedSource(self.dmodel.SeedKind.SURFACE,
                                                       surface=self.ground,
                                                       zone=self.dmodel.Zone(
                                                           self.dmodel.ZoneKind.SECTOR,
                                                           "sector_1")))

    def legend_texts(self, built: Any) -> list[str]:
        return [row.text for row in built.lines.legend]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_real_and_available_as_the_design_commands(self) -> None:
        """RF-013-33, D-29: «Vista previa de semillas, dominios y restricciones» es una orden real (no
        la provisional) con el ``poll`` de las de Diseño: dice por qué no está disponible (sin
        proyecto, en solo lectura o con la versión activa no editable), pero con la vista previa
        activa siempre se puede quitar; la propiedad de la ventana la activa (sobre la primera
        rejilla) y la quita; su diálogo propone la primera superficie y dibuja lo que se
        previsualiza."""
        cls = self.commands.registered_class(TOGGLE)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), ("des.envelope", {"REGISTER"}))
        command = self.commands.catalog().commands[TOGGLE]
        self.assertEqual((command.entry, command.action), ("013", "T"))
        self.assertEqual(command.label_es, "Vista previa de semillas, dominios y restricciones")
        self.assertTrue(cls.poll(bpy.context))
        for reason in ("Abra un proyecto", "Proyecto en solo lectura: prueba",
                       "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"):
            with mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                self.assertFalse(cls.poll(bpy.context), reason)
        self.assertFalse(self.design.enabled())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), False)

        setattr(bpy.context.window_manager, WM_PROPERTY, True)  # la primera rejilla, entera
        self.assertTrue(self.design.enabled() and self.design.drawing())
        first = self.panels.surface_items(None, None)[0][0]
        self.assertIn(first, (self.ground, self.flat))
        self.assertEqual((self.design.plan().seeds.surface, self.design.plan().seeds.zone,
                          self.design.plan().domain), (first, None, self.dmodel.WorkDomain()))
        with mock.patch.object(self.des_ops, "design_unavailable", return_value="solo lectura"):
            self.assertTrue(cls.poll(bpy.context))  # quitarla, siempre
        setattr(bpy.context.window_manager, WM_PROPERTY, False)
        self.assertFalse(self.design.enabled() or self.design.drawing() or self.design.building())
        self.assertFalse(bpy.app.timers.is_registered(self.design.tick))

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        values = {"seeds_from": "SURFACE", "surface": "", "zone": "none", "elevation": "",
                  "bound": "ALL", "bound_layer": "none",
                  "properties": SimpleNamespace(is_property_set=lambda name: False)}
        fake = operator_self(cls, report=lambda kind, text: None, **values)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"],
                         "Vista previa de semillas, dominios y restricciones")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Mostrar")
        self.assertEqual(fake.surface, self.ground)
        self.assertFalse(any(item.use for item in self.view.sectors))
        shown = draw(cls, bpy.context, **values).texts()
        for heading in ("Semillas", "Origen de las semillas", "Zona de las semillas", "Acotar a"):
            self.assertIn(heading, shown)
        marked = draw(cls, bpy.context, **{**values, "bound": "SECTORS"})
        self.assertEqual(len([item for item in marked.of_kind("prop") if item.target == "use"]), 2)

    def test_b_without_masks_only_the_constraints_are_shown_and_nothing_is_written(self) -> None:
        """RF-013-03 (M1): con las máscaras de V01 sin compilar la vista previa construye, por pasos,
        los contornos de las restricciones con su leyenda y el resumen dice que no puede mostrar el
        dominio ni las semillas; no escribe nada en el proyecto (los mismos ficheros bit a bit, ninguna
        operación) y deja el resumen en la vista; volver a pulsar el control lo quita todo."""
        design = self.design
        files, operations = self.files(), self.operations()
        self.assertEqual(self.show(), {"FINISHED"})
        self.assertTrue(design.enabled() and design.drawing() and design.building())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), True)
        built = self.pump()
        self.assertFalse(design.building())
        self.assertEqual((built.lines.version_code, built.lines.masks), ("V01", "missing"))
        self.assertIsNone(built.seeds)
        self.assertEqual(built.sectors, ())
        self.assertEqual([batch.role for batch in built.lines.batches],
                         [self.constraints.OUTLINE] * 3)
        legend = self.legend_texts(built)
        self.assertEqual(legend[0], "Vista previa · V01")
        self.assertIn("Máscaras sin compilar: solo contornos", legend)
        (text, alert), = built.summary
        self.assertTrue(alert)
        self.assertTrue(text.startswith("Las máscaras de V01 no se han compilado"), text)
        self.assertEqual([(line.name, line.alert) for line in self.view.preview],
                         [(text, True)])
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)
        self.assertEqual(self.show(), {"FINISHED"})  # el mismo control la quita
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertEqual(len(self.view.preview), 0)
        self.assertFalse(bpy.app.timers.is_registered(design.tick))
        self.assertEqual(self.files(), files)

    def test_c_seeds_domain_sectors_and_summary_come_from_design(self) -> None:
        """RF-013-01, RF-013-02, RF-013-03 (M1): con las máscaras de V01 compiladas y las semillas
        de la ladera en el sector 1: un punto por celda de semilla en su cota (la de la ladera) y
        coloreado por ella (azul la más baja, rojo la más alta), el dominio de trabajo en trama
        sobre la ladera y solo en sus celdas, el borde de cada sector (azul con la búsqueda vigente,
        ámbar el 2, pendiente) con su nombre y su estado, las restricciones y la leyenda; y el resumen
        es el de ``design.preview`` en español y en inglés, con la torre y el sector 2 como avisos. Compilar con la vista
        previa activa la rehace, y no escribe nada por ella."""
        design, constraints = self.design, self.constraints
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertEqual(self.pump().lines.masks, "missing")
        self.compile_masks(self.v01)
        files, operations = self.files(), self.operations()
        design.on_project_read(self.project)
        self.assertTrue(design.building())
        built = self.pump()
        self.assertEqual(built.lines.masks, "current")
        self.assertEqual(built.lines.surface, self.ground)

        seeds = built.seeds
        self.assertEqual((seeds.count, seeds.total, seeds.stride), (SEEDS_IN_SECTOR_1,) * 2 + (1,))
        self.assertEqual((seeds.positions.shape, seeds.positions.dtype, seeds.colors.dtype),
                         ((SEEDS_IN_SECTOR_1, 3), np.float32, np.float32))
        east = np.arange(1, 15) * STEP_M + 1.0
        north = np.arange(1, 28) * STEP_M + 1.0
        expected = np.array([(self.local(x, y)[0], self.local(x, y)[1],
                              100.0 + 0.1 * x - self.origin.z0) for x in east for y in north])
        order = np.lexsort((seeds.positions[:, 1], seeds.positions[:, 0]))
        self.assertTrue(np.allclose(seeds.positions[order], expected, atol=1e-4))
        low, high = np.argmin(seeds.positions[:, 2]), np.argmax(seeds.positions[:, 2])
        self.assertTrue(np.allclose(seeds.colors[low], (*design.RAMP[0][1], 1.0), atol=1e-6))
        self.assertTrue(np.allclose(seeds.colors[high], (*design.RAMP[-1][1], 1.0), atol=1e-6))
        self.assertEqual(seeds.size_px, design.SEED_PX)
        self.assertEqual((round(seeds.low, 6), round(seeds.high, 6)), (100.3, 102.9))

        found = self.truth(self.sector_1_plan())  # lo que dice design, sin pasar por el dibujo
        mask = found.domain.mask
        domain = built.lines.batch(constraints.DOMAIN, constraints.DOMAIN)
        self.assertGreater(domain.segments, 0)
        grid = found.seeds.geometry
        xyz = domain.positions.astype(np.float64)
        self.assertTrue(np.all(xyz[0::2, 1] == xyz[1::2, 1]))  # rayas horizontales
        for start, end in zip(xyz[0::2], xyz[1::2], strict=True):  # cada raya cae en el dominio
            row = int(round((grid.north - (start[1] + self.origin.y0)) / grid.dy - 0.5))
            first = int(round((start[0] + self.origin.x0 - grid.west) / grid.dx))
            last = int(round((end[0] + self.origin.x0 - grid.west) / grid.dx))
            self.assertTrue(mask[row, first:last].all(), (row, first, last))
        self.assertTrue(np.allclose(
            xyz[:, 2], 100.0 + 0.1 * (xyz[:, 0] + self.origin.x0 - WEST) - self.origin.z0,
            atol=2e-3))  # sobre la ladera
        self.assertIsNone(built.lines.batch(constraints.STRIP, constraints.STRIP))
        self.assertEqual(sorted(built.sectors), [("Sector 1", False), ("Sector 2", True)])
        plain = built.lines.batch(design.SECTOR, design.SECTOR)
        late = built.lines.batch(design.SECTOR_PENDING, design.SECTOR_PENDING)
        for batch, name in ((plain, "Sector 1"), (late, "Sector 2")):  # su borde, sobre la ladera
            left, bottom, right, top = SECTORS[name]
            xy = batch.positions[:, :2]
            self.assertEqual((xy.min(axis=0).tolist(), xy.max(axis=0).tolist()),
                             ([self.local(left, bottom)[0], self.local(left, bottom)[1]],
                              [self.local(right, top)[0], self.local(right, top)[1]]), name)
            self.assertTrue(np.allclose(
                batch.positions[:, 2],
                100.0 + 0.1 * (batch.positions[:, 0].astype(np.float64) + self.origin.x0 - WEST)
                - self.origin.z0, atol=2e-3))
        self.assertEqual((plain.color, late.color), (design.SECTOR_COLOR, design.PENDING_COLOR))
        self.assertGreater(late.width_px, plain.width_px)
        self.assertEqual(sorted(label.text for label in built.lines.labels
                                if label.text.startswith("Sector")),
                         ["Sector 1 · Búsqueda vigente", "Sector 2 · Búsqueda pendiente"])
        for ctype in ("legal_limit", "action_perimeter", "untouchable"):
            self.assertIsNotNone(built.lines.batch(ctype, constraints.OUTLINE), ctype)
        self.assertIsNotNone(built.lines.batch("untouchable", constraints.ZONE))
        legend = self.legend_texts(built)
        self.assertEqual(legend[:3], ["Vista previa · V01", "Semillas a 100,3 m", "Semillas a 102,9 m"])
        for row in ("Dominio de trabajo", "Sector con la búsqueda vigente",
                    "Sector con la búsqueda pendiente"):
            self.assertIn(row, legend)
        self.assertNotIn("Dominio por defecto", legend)
        self.assertNotIn("Franja de solo relleno", legend)

        self.assertEqual(built.summary, tuple(
            (notice.text("es"), notice.severity == "warning") for notice in found.notices))
        thin = self.i18n.THIN_SPACE
        text = " ".join(line for line, _alert in built.summary)
        self.assertIn(f"Semillas: 378 celdas (1{thin}512 m²), cotas 100,3 a 102,9 m", text)
        self.assertIn("Sector «Sector 2»: búsqueda de intocables pendiente", text)
        self.assertEqual([line.name for line in self.view.preview],
                         [line for line, _alert in built.summary])
        self.assertTrue(any(alert for _line, alert in built.summary))
        self.i18n.set_language("en")
        design.rebuild()
        english = self.pump().summary
        self.assertEqual(english, tuple((notice.text("en"), notice.severity == "warning")
                                        for notice in found.notices))
        self.assertTrue(english[0][0].startswith("Seeds: 378 cells (1,512 m²), elevations 100.3 to "
                                                 "102.9 m"), english[0][0])
        self.assertIn("Seeds at 100.3 m", self.legend_texts(self.design.built()))
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)

    def test_d_seeds_on_the_whole_slope_warn_and_are_thinned(self) -> None:
        """RF-013-03, RNF-013-05 (M1: «semillas en toda la ladera»): con las semillas en toda la
        superficie, el resumen avisa en alerta de las semillas fuera del dominio de trabajo (se
        conservan, con su número y su área) y, con más puntos que el tope, se dibuja uno de cada
        ``stride`` (el primero de cada grupo, en el orden de la rejilla) y la leyenda lo dice."""
        design = self.design
        self.assertEqual(self.show(), {"FINISHED"})
        full = self.pump()
        found = self.truth(design.plan())
        self.assertEqual(full.seeds.count, 900)  # 30 × 30 celdas con cota
        outside = found.seeds.outside_domain
        self.assertGreater(outside, 0)
        warned = [line for line, alert in full.summary if alert and "fuera del dominio" in line]
        (warning,) = warned
        self.assertTrue(warning.startswith(f"{outside} celdas de semilla ("), warning)
        self.assertIn(f"{outside} celdas de semilla fuera del dominio.", full.summary[0][0])
        self.assertNotIn("Semillas aclaradas", " ".join(self.legend_texts(full)))
        design.disable()
        with mock.patch.object(design, "MAX_SEED_POINTS", 128), mock.patch.object(
                design, "SEED_ROWS_PER_STEP", 7):  # 900 / 128 = 7,03: de 8 en 8, en 5 trozos
            self.assertEqual(self.show(), {"FINISHED"})
            thin = self.pump()
        self.assertEqual((thin.seeds.count, thin.seeds.total, thin.seeds.stride), (113, 900, 8))
        self.assertEqual(thin.seeds.positions.shape, (113, 3))
        self.assertIn("Semillas aclaradas: se dibuja 1 de cada 8", self.legend_texts(thin))
        first = thin.seeds.positions[0]  # la primera celda de la rejilla: fila 0, columna 0
        self.assertTrue(np.allclose(first[:2], self.local(1.0, SIZE_M - 1.0), atol=1e-4))
        again = [(line, alert) for line, alert in thin.summary]
        self.assertEqual(again, list(full.summary))  # el resumen cuenta todas, no las dibujadas

    def test_e_what_is_drawn_in_pixels_and_with_gpu(self) -> None:
        """RF-013-03, RNF-013-05: en píxeles de la región, el resumen arriba a la izquierda (cada línea
        partida al ancho, los avisos en ámbar y las demás en blanco), los nombres que caben y la
        leyenda abajo a la derecha; con ``gpu``, los puntos de las semillas en un solo lote con su
        color por vértice (creado una vez, con el tamaño de su punto y el de la pantalla) y los
        lotes de líneas de la 012 (uno por lote), sin que cambie el estado de ``gpu``."""
        design, constraints = self.design, self.constraints
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        built = self.pump()
        pixels = _module("bl.draw.dh_overlay")
        matrix = top_view(self.local(30.0, 30.0))
        measure = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        items = design.screen_items(built, matrix, SIZE, measure=measure, scale=1.0)
        texts = [item for item in items if isinstance(item, pixels.Text)]
        summary = design.summary_items(built.summary, measure, 1.0, SIZE)
        self.assertEqual(items[-len(summary):], summary)  # el resumen, lo último que se pinta
        box, *lines = summary
        limit = SIZE[0] * design.SUMMARY_WIDTH_FRACTION - 2 * pixels.MARGIN_PX
        self.assertTrue(all(isinstance(item, pixels.Text) and item.x == pixels.MARGIN_PX
                            for item in lines))
        self.assertTrue(all(measure(item.text) <= limit for item in lines))
        self.assertEqual(" ".join(item.text for item in lines).split(),
                         " ".join(line for line, _alert in built.summary).split())
        amber = sum(len(design.wrap_text(line, measure, limit))
                    for line, alert in built.summary if alert)
        self.assertGreater(amber, 0)
        self.assertEqual([item.color for item in lines].count(pixels.STALE_COLOR), amber)
        tops = [item.y for item in lines]
        self.assertEqual(tops, sorted(tops, reverse=True))  # de arriba abajo
        self.assertGreater(box.y1, SIZE[1] / 2)  # arriba a la izquierda
        self.assertTrue(box.x0 < pixels.MARGIN_PX and box.y1 < SIZE[1] and box.y1 > tops[0])
        self.assertEqual(design.wrap_text("una dos tres", len, 6), ["una", "dos", "tres"])
        self.assertEqual(design.wrap_text("una dos tres", len, 7), ["una dos", "tres"])
        self.assertEqual(design.wrap_text("una dos tres", len, 12), ["una dos tres"])
        self.assertEqual(design.wrap_text("anticonstitucionalmente", len, 5),
                         ["anticonstitucionalmente"])
        names = {item.text for item in texts}
        self.assertIn("Sector 2 · Búsqueda pendiente", names)
        self.assertIn("Torre", names)
        panel = next(item for item in items if isinstance(item, pixels.Box)
                     and item.x1 == SIZE[0] - pixels.MARGIN_PX + pixels.PAD_PX)  # la leyenda
        self.assertEqual(panel.y0, pixels.MARGIN_PX - pixels.PAD_PX)
        self.assertEqual(design.summary_items((), len, 1.0, SIZE), [])

        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        gpu.state.depth_mask_get.return_value = True
        gpu.state.blend_get.return_value = "NONE"
        with mock.patch.object(design, "gpu", gpu), mock.patch.object(
                design, "batch_for_shader") as make:
            view = dict(view_matrix=Matrix.Identity(4), projection_matrix=Matrix.Identity(4),
                        perspective=True, view_distance=100.0)
            self.assertEqual(design.draw_points(built, pixel_size=1.0, **view), built.seeds.count)
            gpu.shader.from_builtin.assert_called_with("POINT_FLAT_COLOR")
            self.assertEqual(make.call_count, 1)
            self.assertEqual(make.call_args.args[1], "POINTS")
            data = make.call_args.args[2]
            self.assertEqual(sorted(data), ["color", "pos"])
            self.assertEqual((data["pos"].shape, data["color"].shape),
                             ((built.seeds.count, 3), (built.seeds.count, 4)))
            self.assertEqual(design.draw_points(built, pixel_size=2.0, **view), built.seeds.count)
            self.assertEqual(make.call_count, 1)  # el lote de gpu ya estaba
        sizes = [call.args[0] for call in gpu.state.point_size_set.call_args_list]
        self.assertEqual(sizes, [design.SEED_PX, 1.0, 2 * design.SEED_PX, 1.0])
        gpu.state.depth_test_set.assert_called_with("NONE")
        gpu.state.depth_mask_set.assert_called_with(True)
        gpu.state.blend_set.assert_called_with("NONE")
        nothing = design.Built(built.lines, None, (), ())
        self.assertEqual(design.draw_points(nothing, pixel_size=1.0, **view), 0)

        lines_gpu = mock.MagicMock()
        lines_gpu.state.depth_test_get.return_value = "NONE"
        with mock.patch.object(constraints, "gpu", lines_gpu), mock.patch.object(
                constraints, "batch_for_shader") as lots:
            drawn = constraints.draw_lines(built.lines, viewport_size=(400.0, 300.0),
                                           pixel_size=1.0, **view)
        self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        self.assertGreater(len(built.lines.batches), 6)  # dominio, tres contornos, la torre y 2 sectores

    def test_f_changing_the_version_or_leaving_removes_or_rebuilds_it(self) -> None:
        """RF-013-03: cambiar de versión activa rehace la vista previa con la de la nueva (V02 no
        tiene máscaras: solo contornos y el aviso); volver a V01 devuelve las semillas; un aviso del
        proyecto sin nada nuevo no rehace nada; conmutar a la interfaz de Blender la quita (y
        volver a Geoblender no la pone sola); cerrar el proyecto también."""
        design, switcher = self.design, self.switcher
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertEqual(self.pump().seeds.count, SEEDS_IN_SECTOR_1)
        design.on_project_read(self.project)  # sin nada nuevo
        self.assertFalse(design.building())
        self.set_active(self.v02)
        self.assertTrue(design.building())
        other = self.pump()
        self.assertEqual((other.lines.version_code, other.lines.masks), ("V02", "missing"))
        self.assertIsNone(other.seeds)
        self.assertEqual(self.legend_texts(other)[0], "Vista previa · V02")
        self.assertTrue(other.summary[0][0].startswith("Las máscaras de V02 no se han compilado"))
        self.set_active(self.v01)
        self.assertEqual(self.pump().seeds.count, SEEDS_IN_SECTOR_1)

        self.assertIn(design.disable, switcher.blender_hooks())
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), False)
        # Lo que queda apuntado es lo de la cola de avisos (spec 019, T22), que no se quita al conmutar.
        self.assertEqual([hook for hook in switcher.blender_hooks()
                          if not hook.__module__.endswith("bl.ui.notices")], [])
        other_space = next(space.name for space in bpy.data.workspaces
                           if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
        self.assertFalse(design.enabled())

        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        self.assertIn(design.on_project_changed, self.ps.listeners())
        self.ps.listeners()[self.ps.listeners().index(design.on_project_changed)](None)
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertNotIn(design.on_project_changed, self.ps.listeners())
        self.assertEqual(len(self.view.preview), 0)

    def test_g_the_dialog_refuses_what_is_missing_and_a_rejected_preview_warns(self) -> None:
        """RF-013-33, RF-013-03: una cota fija sin escribir, unos sectores sin marcar y una cota que no
        es un número se rechazan sin activar nada y diciéndolo; una vista previa que el cálculo
        rechaza (aquí, una superficie que ya no existe) avisa con el motivo y se quita sola; con
        la versión activa no editable la orden se niega con su motivo y con la vista previa activa
        la quita."""
        design = self.design
        for values, wanted in (
                ({"seeds_from": "FIXED", "elevation": ""}, "Escriba la cota fija de las semillas"),
                ({"seeds_from": "FIXED", "elevation": "alta"}, "«alta» no es un número"),
                ({"bound": "SECTORS"}, "Marque los sectores a los que se acota el dominio")):
            with self.subTest(pedido=wanted), self.assertRaises(RuntimeError) as caught:
                self.show(**values)
            self.assertIn(wanted, str(caught.exception))
            self.assertFalse(design.enabled())
        self.assertEqual(self.show(seeds_from="FIXED", elevation="101,5",
                                   zone="sector:sector_1"), {"FINISHED"})
        fixed = self.pump()
        self.assertEqual(fixed.seeds.count, SEEDS_IN_SECTOR_1)
        self.assertTrue(np.all(fixed.seeds.positions[:, 2] == np.float32(101.5 - self.origin.z0)))
        self.assertEqual({tuple(color) for color in fixed.seeds.colors.tolist()},
                         {tuple(np.float32(value) for value in (*self.design.RAMP[2][1], 1.0))})
        design.disable()

        self.view.sectors[1].use = True
        self.assertEqual(self.show(bound="SECTORS"), {"FINISHED"})
        self.assertEqual(design.plan().domain, self.dmodel.WorkDomain(sectors=("sector_2",)))
        design.disable()
        self.panels.clear_sector_marks()

        self.ps.take_notices()
        missing = design.Plan(self.dmodel.SeedSource(self.dmodel.SeedKind.SURFACE,
                                                     surface="Ladera inexistente"))
        design.enable(missing)
        self.assertIsNone(self.run_to_end())
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        (notice,) = self.ps.take_notices()
        self.assertTrue(notice.startswith("No se pudo preparar la vista previa de semillas, "
                                          "dominios y restricciones: "), notice)
        self.assertIn("Ladera inexistente", notice)

        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        with mock.patch.object(self.des_ops, "design_unavailable",
                               return_value="V02 está en estado SUPERADO"):
            self.assertEqual(bpy.ops.geoblender.des_toggle_preview(), {"FINISHED"})
        self.assertFalse(design.enabled())
        with mock.patch.object(self.des_ops, "design_unavailable",
                               return_value="V02 está en estado SUPERADO"):
            self.assertFalse(bpy.ops.geoblender.des_toggle_preview.poll())

    def run_to_end(self) -> Any:
        """Los pasos hasta que acaban o fallan (``None`` si la vista previa se quitó)."""
        for _ in range(MAX_PUMPS):
            if self.design.tick() is None:
                return self.design.built()
        self.fail("la vista previa no acaba")

    def test_h_the_summary_starts_after_the_toolbar_that_covers_the_region(self) -> None:
        """RF-013-01, RF-013-02 (H3, hallazgo 1; M1): la barra de herramientas de la Vista 3D se
        superpone a la región (preferencia «Region Overlap») y tapa lo que se dibuja desde su borde
        izquierdo, así que el resumen empieza donde ella acaba (``covered_px``: su anchura si está a la
        vista, a la izquierda y superpuesta; 0 si no), a escala 1,0 y 1,25: ninguna caja ni línea
        queda antes de ella, el ancho al que se parten las líneas sale de lo que queda a su derecha
        (sin pasarse del borde derecho) y con 0 es el reparto de siempre; ``_draw_pixels`` se lo pasa
        leyendo la región ``TOOLS`` del área."""
        design = self.design
        pixels = _module("bl.draw.dh_overlay")
        measure = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        summary = (
            ("Semillas: 25 600 celdas (102 400 m²), cotas 650,0 a 650,0 m; dominio: 3,4 ha; "
             "17 060 celdas de semilla fuera del dominio.", False),
            ("Máscaras de V01: al día.", False),
            ("17 060 celdas de semilla (68 240 m²) están fuera del dominio de trabajo: la envolvente "
             "las usa, pero allí no se entrega nada. Revise la zona de las semillas antes de "
             "calcular.", True),
        )
        words = " ".join(line for line, _alert in summary).split()

        for scale in (1.0, 1.25):  # sin zona tapada: el reparto de siempre
            with self.subTest(scale=scale, covered=0.0):
                margin, pad = pixels.MARGIN_PX * scale, pixels.PAD_PX * scale
                today = design.summary_items(summary, measure, scale, SIZE)
                self.assertEqual(design.summary_items(summary, measure, scale, SIZE, covered_px=0.0),
                                 today)
                box, *lines = today
                limit = SIZE[0] * design.SUMMARY_WIDTH_FRACTION - 2.0 * margin
                self.assertEqual({item.x for item in lines}, {margin})
                self.assertEqual((box.x0, box.x1 - pad - margin),
                                 (margin - pad, max(measure(item.text) for item in lines)))
                self.assertEqual([item.text for item in lines],
                                 [part for line, _alert in summary
                                  for part in design.wrap_text(line, measure, limit)])

        for scale, covered in ((1.0, 56.0), (1.25, 70.0), (1.0, 300.0)):
            with self.subTest(scale=scale, covered=covered):
                margin, pad = pixels.MARGIN_PX * scale, pixels.PAD_PX * scale
                box, *lines = design.summary_items(summary, measure, scale, SIZE, covered_px=covered)
                self.assertGreaterEqual(box.x0, covered)  # la caja, a la derecha de la barra
                self.assertTrue(all(isinstance(item, pixels.Text) and item.x >= covered
                                    for item in lines))
                self.assertEqual({item.x for item in lines}, {covered + margin})  # una vez, no dos
                self.assertEqual(box.x0, covered + margin - pad)
                limit = (SIZE[0] - covered) * design.SUMMARY_WIDTH_FRACTION - 2.0 * margin
                self.assertTrue(all(measure(item.text) <= limit for item in lines))
                self.assertLessEqual(box.x1, SIZE[0])  # sin pasarse del borde derecho
                self.assertGreater(len(lines), len(summary))  # las líneas largas se parten
                self.assertEqual(" ".join(item.text for item in lines).split(), words)
                self.assertEqual([item.color for item in lines].count(pixels.STALE_COLOR),
                                 len(design.wrap_text(summary[2][0], measure, limit)))

        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        built = self.pump()
        matrix = top_view(self.local(30.0, 30.0))
        plain = design.summary_items(built.summary, measure, 1.0, SIZE)
        moved = design.summary_items(built.summary, measure, 1.0, SIZE, covered_px=56.0)
        shown = design.screen_items(built, matrix, SIZE, measure=measure, scale=1.0, covered_px=56.0)
        rest = design.screen_items(built, matrix, SIZE, measure=measure, scale=1.0)
        self.assertEqual(shown[-len(moved):], moved)  # el resumen, a la derecha de la barra
        self.assertEqual(shown[:-len(moved)], rest[:-len(plain)])  # los nombres y la leyenda, donde estaban

        def regions(tools_width: int, alignment: str = "LEFT") -> SimpleNamespace:
            return SimpleNamespace(regions=[
                SimpleNamespace(type="HEADER", width=SIZE[0], alignment="TOP"),
                SimpleNamespace(type="TOOLS", width=tools_width, alignment=alignment),
                SimpleNamespace(type="WINDOW", width=SIZE[0], alignment="NONE")])

        shown_bar, hidden_bar = (SimpleNamespace(show_region_toolbar=value) for value in (True, False))
        covered = design.toolbar_covered_px
        self.assertEqual(covered(shown_bar, regions(56), True), 56.0)
        self.assertEqual(covered(shown_bar, regions(56), False), 0.0)  # sin «Region Overlap»
        self.assertEqual(covered(shown_bar, regions(1), True), 0.0)  # una región oculta mide 1
        self.assertEqual(covered(shown_bar, regions(0), True), 0.0)
        self.assertEqual(covered(hidden_bar, regions(56), True), 0.0)
        self.assertEqual(covered(shown_bar, regions(56, "RIGHT"), True), 0.0)  # tapa el otro lado
        self.assertEqual(covered(shown_bar, SimpleNamespace(regions=[]), True), 0.0)

        fake_blf = SimpleNamespace(size=lambda *args: None,
                                   dimensions=lambda font, text: (measure(text), 12.0))
        for scale, tools_width in ((1.0, 56), (1.25, 70), (1.0, 1)):
            with self.subTest(scale=scale, tools=tools_width):
                context = SimpleNamespace(
                    space_data=SimpleNamespace(overlay=SimpleNamespace(show_overlays=True),
                                               show_region_toolbar=True),
                    region=SimpleNamespace(width=SIZE[0], height=SIZE[1]),
                    region_data=SimpleNamespace(perspective_matrix=matrix),
                    area=regions(tools_width),
                    preferences=SimpleNamespace(system=SimpleNamespace(
                        ui_scale=scale, use_region_overlap=True)))
                with mock.patch.object(design, "bpy", SimpleNamespace(context=context)), \
                        mock.patch.object(design, "blf", fake_blf), \
                        mock.patch.object(design.dh_overlay, "paint") as paint:
                    design._draw_pixels()
                self.assertFalse(design._STATE.failed)
                paint.assert_called_once()
                items = paint.call_args.args[0]
                left = float(tools_width) if tools_width > 1 else 0.0
                expected = design.summary_items(built.summary, measure, scale, SIZE, covered_px=left)
                self.assertEqual(items[-len(expected):], expected)

    def test_i_the_seeds_legend_has_one_row_for_one_elevation_and_the_color_that_is_seen(self) -> None:
        """RF-013-02 (H3, hallazgo 2; M1): con todas las semillas a la misma cota (la superficie
        plana: ``low == high``) ``elevation_colors`` las pinta del color del medio de la rampa, y la
        leyenda enseña **una** fila «Semillas a 50,0 m» con ese color (el de todos los puntos, ni el
        del primer extremo ni el del último); con varias cotas, las dos filas de siempre, la baja con
        el primer color de la rampa y la alta con el último, que son los de las semillas más baja y más
        alta. Solo cambia la leyenda: los puntos y sus colores son los mismos."""
        design = self.design
        ends = (design._hex(design.RAMP[0][1]), design._hex(design.RAMP[-1][1]))

        def seed_rows(built: Any) -> list[tuple[str, str | None]]:
            return [(row.text, row.color) for row in built.lines.legend
                    if row.text.startswith("Semillas a ")]  # no «Semillas aclaradas»

        self.assertEqual(self.show(surface=self.flat), {"FINISHED"})
        flat = self.pump()
        self.assertEqual((flat.seeds.low, flat.seeds.high), (50.0, 50.0))
        self.assertEqual(flat.seeds.count, 900)
        self.assertTrue(np.all(flat.seeds.colors == flat.seeds.colors[0]))  # los puntos, de un color
        seen = design._hex(flat.seeds.colors[0])
        self.assertEqual(seen, design._hex(design.elevation_colors([50.0], 50.0, 50.0)[0]))
        self.assertNotIn(seen, ends)
        self.assertEqual(seed_rows(flat), [("Semillas a 50,0 m", seen)])

        design.disable()
        self.i18n.set_language("en")
        self.assertEqual(self.show(surface=self.flat), {"FINISHED"})
        english = [(row.text, row.color) for row in self.pump().lines.legend
                   if row.text.startswith("Seeds at ")]
        self.assertEqual(english, [("Seeds at 50.0 m", seen)])
        self.i18n.set_language("es")

        design.disable()
        self.assertEqual(self.show(), {"FINISHED"})  # la ladera: varias cotas
        sloped = self.pump()
        low, high = sloped.seeds.low, sloped.seeds.high
        self.assertLess(low, high)
        number = self.i18n.format_number
        self.assertEqual(seed_rows(sloped), [(f"Semillas a {number(low, 1)} m", ends[0]),
                                             (f"Semillas a {number(high, 1)} m", ends[1])])
        height = sloped.seeds.positions[:, 2]  # los puntos son float32: el color, con su redondeo
        for place, stop in ((int(np.argmin(height)), design.RAMP[0][1]),
                            (int(np.argmax(height)), design.RAMP[-1][1])):
            self.assertTrue(np.allclose(sloped.seeds.colors[place][:3], stop, atol=1e-6), place)

    def quarry_truth(self, request: Any, ring: int, version: Any | None = None) -> Any:
        """Lo que dice ``design`` de la cantera ``request`` con el anillo ``ring``
        (``design.preview.quarry_summarize_steps``), sin pasar por el dibujo."""
        found = None
        for step in _module("design.preview").quarry_summarize_steps(
                self.project, request, (version or self.v01).uid, ring_cells=ring):
            found = step.result if step.result is not None else found
        return found

    def absolute(self, batch: Any) -> tuple[np.ndarray, np.ndarray]:
        """Los segmentos ``(k, 2, 2)`` absolutos de un lote y la cota local de sus vértices."""
        xyz = batch.positions.astype(np.float64)
        xy = xyz[:, :2] + np.array([self.origin.x0, self.origin.y0], dtype=np.float64)
        return xy.reshape(-1, 2, 2), xyz[:, 2]

    def on_slope(self, x_local: np.ndarray, z_local: np.ndarray) -> bool:
        """Si las cotas locales ``z_local`` son las de la ladera en las abscisas locales."""
        return bool(np.allclose(z_local, 100.0 + 0.1 * (x_local + self.origin.x0 - WEST)
                                - self.origin.z0, atol=2e-3))

    def quarry_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo de la cantera: «Corta» sobre la ladera, las dos superficies con
        el perfil :data:`PROFILE` (por su nombre), los fondos, la zona a conservar y los corredores
        con rasante (sus campos, los propuestos); cambiado por ``values``."""
        return {"name": "Corta", "start": self.ground, "final_profile": PROFILE,
                "exploitation_profile": PROFILE, "floors_layer": FLOORS_LAYER,
                "conserve": f"layer:{CONSERVE_LAYER}", "corridors_layer": CORRIDORS_LAYER,
                "corridors_level": "GRADIENT", **values}

    def preview_button(self, form: dict[str, Any]) -> Any:
        """El botón de la orden de la cantera en su diálogo, dibujado con lo pedido en ``form``
        (los demás campos, los de :data:`QUARRY_FIELDS`)."""
        cls = self.des_ops.GEOBLENDER_OT_des_design_quarry
        shown = draw(cls, bpy.context, confirm=False, outside="", **{**QUARRY_FIELDS, **form})
        (button,) = [item for item in shown.of_kind("operator") if item.target == QUARRY]
        return button

    def test_j_a_quarry_design_adds_its_pieces_with_their_legend(self) -> None:
        """RF-014-04 (spec 014, T23 y T44; plan 014 §5.5; M1): el botón «Vista previa» del diálogo de
        «Cantera con dos superficies…» es la misma orden con ``preview`` y todo lo pedido en él; la
        orden comprueba lo pedido (lo que falta, rechazado sin activar nada) y activa la vista previa
        con su diseño (``QuarryPlan``), sin calcular ni escribir nada; pulsarlo otra vez la cambia
        por la nueva. La vista previa enseña, sobre la superficie de partida y sin
        escribir nada, además de las restricciones y los sectores: el borde del recinto excavable, la
        coronación (un punto por celda en su cota, coloreado por ella como las semillas), el borde de
        las zonas a sostener, el de cada fondo con su cota, el de las zonas a conservar (y su trama)
        con su nombre y el de cada corredor con sus cotas; cada borde, lado a lado, igual al de sus
        celdas en ``design.preview`` (y las celdas, a mano); la leyenda con una fila por pieza y el
        resumen de ``design``, en español y en inglés. Conmutar a la interfaz de Blender
        (``Ctrl+F10``, los ganchos del conmutador) la quita con la de la cantera activa. El anillo es
        el del parámetro (3 celdas por defecto) o el pedido por guion; sin las máscaras de la versión,
        solo los contornos y el aviso; una capa que el cálculo rechaza avisa con el motivo y la
        quita."""
        design, constraints = self.design, self.constraints
        grid_module = _module("gis.grid")
        rng = np.random.default_rng(14)
        for case in range(24):  # el borde de una rejilla de valores, frente a la fuerza bruta
            rows, cols = (int(value) for value in rng.integers(1, 12, size=2))
            values = rng.integers(0, 3, size=(rows, cols))
            if case % 2:
                values = values > 0
            small = grid_module.Grid(10.0, 20.0 + STEP_M * rows, STEP_M, STEP_M, cols, rows)
            with mock.patch.object(design, "EDGE_ROWS_PER_STEP", 1 + case % 4):
                segments = finish(design.edges_steps(values, small))
            self.assertEqual(covered_edges(segments, small), unit_edges(values), case)
        empty = grid_module.Grid(0.0, 4.0, 2.0, 2.0, 2, 2)
        self.assertEqual(finish(design.edges_steps(np.zeros((2, 2), dtype=bool), empty)).shape,
                         (0, 2, 2))

        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                          "Layers of the tests", False))
        self.addCleanup(contract.unregister_operation, LAYERS_TYPE)
        self.write_layer(FLOORS_LAYER, "polygon", tuple(((ring(box),),) for box in FLOOR_BOXES),
                         {"cota": FLOOR_LEVELS})
        self.write_layer(CONSERVE_LAYER, "polygon", (((ring(CONSERVE_BOX),),),), {})
        self.write_layer(CORRIDORS_LAYER, "line", (((path(CORRIDOR_AXIS),),),),
                         {field: (value,) for field, value in CORRIDOR_FIELDS.items()})
        access = _module("gis.masks.access")
        if access.mask_state(self.project, self.v01.uid)[0] is not access.MaskState.CURRENT:
            self.compile_masks(self.v01)
        self.set_active(self.v01)
        self.assertEqual(bpy.ops.geoblender.des_save_bench_profile(  # el que piden los dos lados
            name=PROFILE, kind="ADOPTADO", source=REASON, decided_by=PERSON, reason=REASON,
            scope="PROJECT", height="5", face="35", berm="6", anchor="100"), {"FINISHED"})
        self.panels.fill_profiles(self.project)
        code = self.panels.profile_codes()[PROFILE]
        m = self.dmodel
        request = m.QuarryRequest(
            "Corta", self.ground, m.QuarrySide(code), m.QuarrySide(code),
            floors=m.LayerField(FLOORS_LAYER, "cota"),
            conserve=(m.Zone(m.ZoneKind.LAYER, CONSERVE_LAYER),),
            corridors=m.CorridorFields(CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                       gradient_field="pendiente"))
        files, operations = self.files(), self.operations()

        self.panels.refresh_choices(self.project)  # las capas nuevas, en las listas del diálogo
        form = self.quarry_form()
        button = self.preview_button(form)  # «Vista previa»: la orden de la cantera, con lo pedido
        self.assertEqual((button.text, button.icon, button.operator_context),
                         ("Vista previa", "HIDE_OFF", "EXEC_DEFAULT"))
        self.assertEqual(vars(button.properties), {**QUARRY_FIELDS, **form, "preview": True})
        with self.assertRaises(RuntimeError) as caught:  # lo que falta: nada activado
            bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", preview=True,
                                                 **self.quarry_form(final_profile=""))
        self.assertIn("Elija el perfil base de «Superficie final»", str(caught.exception))
        self.assertFalse(design.enabled())
        self.assertEqual(bpy.ops.geoblender.des_design_quarry(
            "EXEC_DEFAULT", preview=True, **self.quarry_form(corridors_layer="none")),
            {"FINISHED"})
        self.assertEqual(design.plan(), design.QuarryPlan(replace(request, corridors=None)))
        self.assertEqual(bpy.ops.geoblender.des_design_quarry("EXEC_DEFAULT", preview=True, **form),
                         {"FINISHED"})  # pulsarlo otra vez: la nueva en lugar de la otra
        self.assertTrue(design.enabled() and design.drawing() and design.building())
        self.assertEqual(design.plan(), design.QuarryPlan(request))
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), True)
        self.assertIsNone(self.des_ops.calculation())  # ni un cálculo abierto
        built = self.pump()
        truth = self.quarry_truth(request, 3)  # el anillo del parámetro: 3 celdas por defecto
        grid = truth.masks.grid
        self.assertEqual((built.lines.masks, built.lines.surface), ("current", self.ground))
        self.assertEqual((int(truth.area.sum()), int(truth.crown.sum()), int(truth.hold.sum())),
                         (AREA_CELLS, CROWN_CELLS, 25))
        self.assertEqual((truth.floors.cells, truth.corridors.floors.cells,
                          int(truth.conserve[0].mask.sum())), (FLOOR_CELLS, (CORRIDOR_CELLS,), 16))

        pieces = ((design.AREA, truth.area, design.AREA_COLOR),
                  (design.HOLD, truth.hold, design.HOLD_COLOR),
                  (design.FLOORS, truth.floors.owner, design.FLOOR_COLOR),
                  (design.CEILINGS, truth.conserve[0].mask, design.CEILING_COLOR),
                  (design.CORRIDORS, truth.corridors.floors.owner, design.CORRIDOR_COLOR))
        for key, cells, color in pieces:  # el borde de cada pieza, lado a lado, sobre la ladera
            with self.subTest(pieza=key):
                batch = built.lines.batch(key, constraints.OUTLINE)
                self.assertIsNotNone(batch)
                self.assertEqual(batch.color, color)
                segments, height = self.absolute(batch)
                self.assertEqual(covered_edges(segments, grid), unit_edges(cells))
                self.assertTrue(self.on_slope(batch.positions[:, 0].astype(np.float64), height))
        self.assertGreater(built.lines.batch(design.AREA, constraints.OUTLINE).width_px,
                           built.lines.batch(design.HOLD, constraints.OUTLINE).width_px)
        hatch = built.lines.batch(design.CEILINGS, constraints.ZONE)  # la zona a conservar, en trama
        segments, _height = self.absolute(hatch)
        zone = truth.conserve[0].mask
        for (x0, y0), (x1, _y1) in segments.tolist():
            row = int(round((grid.north - y0) / grid.dy - 0.5))
            first, last = sorted((int(round((x0 - grid.west) / grid.dx)),
                                  int(round((x1 - grid.west) / grid.dx))))
            self.assertTrue(zone[row, first:last].all(), (row, first, last))
        roles = {batch.role for batch in built.lines.batches}
        self.assertFalse(roles & {constraints.DOMAIN, constraints.STRIP})
        self.assertIsNotNone(built.lines.batch(design.SECTOR_PENDING, design.SECTOR_PENDING))
        self.assertIsNotNone(built.lines.batch("untouchable", constraints.OUTLINE))

        crown = built.seeds  # la coronación, en el color de las semillas
        self.assertEqual((crown.count, crown.total, crown.stride), (CROWN_CELLS, CROWN_CELLS, 1))
        rows, cols = np.nonzero(truth.crown)
        expected = np.column_stack([grid.west + (cols + 0.5) * grid.dx - self.origin.x0,
                                    grid.north - (rows + 0.5) * grid.dy - self.origin.y0,
                                    truth.start[rows, cols] - self.origin.z0])
        self.assertTrue(np.allclose(crown.positions.astype(np.float64), expected, atol=1e-4))
        self.assertEqual((round(crown.low, 6), round(crown.high, 6)), (100.1, 105.5))
        low, high = np.argmin(crown.positions[:, 2]), np.argmax(crown.positions[:, 2])
        self.assertTrue(np.allclose(crown.colors[low], (*design.RAMP[0][1], 1.0), atol=1e-6))
        self.assertTrue(np.allclose(crown.colors[high], (*design.RAMP[-1][1], 1.0), atol=1e-6))

        labels = {label.text: label for label in built.lines.labels}
        for text, (x, y), color in (("Fondo a 95,00 m", (12.0, 38.0), design.FLOOR_COLOR),
                                    ("Fondo a 96,00 m", (29.0, 41.0), design.FLOOR_COLOR),
                                    ("Corredor 1: 97,05 a 98,05 m", (40.0, 19.0),
                                     design.CORRIDOR_COLOR),
                                    (f"Zona a conservar «{CONSERVE_LAYER}»", (12.0, 12.0),
                                     design.CEILING_COLOR)):
            with self.subTest(nombre=text):
                self.assertIn(text, labels)
                lx, ly = self.local(x, y)
                place = labels[text].xyz
                self.assertTrue(np.allclose(place[:2], (lx, ly), atol=1e-3), place)
                self.assertTrue(self.on_slope(np.array([place[0]]), np.array([place[2]])))
                self.assertEqual(labels[text].color, color)
        self.assertIn("Sector 2 · Búsqueda pendiente", labels)
        self.assertIn("Torre", labels)

        hexed = design._hex
        legend = [(row.text, row.color) for row in built.lines.legend]
        self.assertEqual(legend[:10], [
            ("Vista previa · V01", None),
            ("Coronación a 100,1 m", hexed(design.RAMP[0][1])),
            ("Coronación a 105,5 m", hexed(design.RAMP[-1][1])),
            ("Recinto excavable", hexed(design.AREA_COLOR)),
            ("Zonas a sostener", hexed(design.HOLD_COLOR)),
            (f"Fondos de «{FLOORS_LAYER}» (2)", hexed(design.FLOOR_COLOR)),
            ("Zonas a conservar: techos de conservación (1)", hexed(design.CEILING_COLOR)),
            (f"Corredores de «{CORRIDORS_LAYER}» (1)", hexed(design.CORRIDOR_COLOR)),
            ("Sector con la búsqueda vigente", hexed(design.SECTOR_COLOR)),
            ("Sector con la búsqueda pendiente", hexed(design.PENDING_COLOR))])
        texts = [text for text, _color in legend]
        self.assertIn(f"Sobre la superficie «{self.ground}»", texts)
        for absent in ("Dominio de trabajo", "Dominio por defecto", "Franja de solo relleno"):
            self.assertNotIn(absent, texts)
        self.assertEqual(built.summary, tuple((notice.text("es"), notice.severity == "warning")
                                              for notice in truth.notices))
        thin = self.i18n.THIN_SPACE
        said = " ".join(line for line, _alert in built.summary)
        self.assertIn(f"Recinto excavable: {AREA_CELLS} celdas (1{thin}836 m²", said)
        self.assertIn(f"Coronación: anillo de 3 celdas fuera del recinto, {CROWN_CELLS} celdas", said)
        self.assertEqual([line.name for line in self.view.preview],
                         [line for line, _alert in built.summary])

        measure = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        shown = {item.text for item in design.screen_items(built, top_view(self.local(30.0, 30.0)),
                                                            SIZE, measure=measure)
                 if hasattr(item, "text")}
        self.assertTrue({"Fondo a 95,00 m", "Recinto excavable", "Zonas a sostener"} <= shown)
        gpu = mock.MagicMock()
        with mock.patch.object(design, "gpu", gpu), mock.patch.object(design, "batch_for_shader"):
            self.assertEqual(design.draw_points(built, view_matrix=Matrix.Identity(4),
                                                projection_matrix=Matrix.Identity(4),
                                                perspective=True, view_distance=100.0,
                                                pixel_size=1.0), CROWN_CELLS)

        self.i18n.set_language("en")
        design.rebuild()
        english = self.pump()
        self.assertEqual(english.summary, tuple((notice.text("en"), notice.severity == "warning")
                                                for notice in truth.notices))
        rows_en = [row.text for row in english.lines.legend]
        self.assertEqual(rows_en[1:8], ["Crown at 100.1 m", "Crown at 105.5 m",
                                        "Excavation boundary", "Zones to hold",
                                        f"Floors of «{FLOORS_LAYER}» (2)",
                                        "Zones to conserve: conservation ceilings (1)",
                                        f"Corridors of «{CORRIDORS_LAYER}» (1)"])
        names = {label.text for label in english.lines.labels}
        self.assertTrue({"Floor at 95.00 m", "Corridor 1: 97.05 to 98.05 m",
                         f"Zone to conserve «{CONSERVE_LAYER}»"} <= names)
        self.i18n.set_language("es")

        switcher = self.switcher  # conmutar a la interfaz de Blender la quita
        self.assertIn(design.disable, switcher.blender_hooks())
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.plan())
        self.assertIsNone(design.built())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), False)
        self.assertEqual(len(self.view.preview), 0)
        other_space = next(space.name for space in bpy.data.workspaces
                           if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
        self.assertFalse(design.enabled())

        design.enable(design.QuarryPlan(request, ring_cells=1))  # el anillo pedido por guion
        narrow = self.pump()
        self.assertEqual(narrow.seeds.total, 24 * 24 - 22 * 22 + 16)  # y el borde del agujero
        self.assertEqual(narrow.seeds.total, int(self.quarry_truth(request, 1).crown.sum()))

        self.set_active(self.v02)  # sin máscaras: solo los contornos y el aviso
        self.assertTrue(design.building())
        bare = self.pump()
        self.assertEqual((bare.lines.version_code, bare.lines.masks), ("V02", "missing"))
        self.assertIsNone(bare.seeds)
        self.assertIsNone(bare.lines.batch(design.AREA, constraints.OUTLINE))
        self.assertTrue(bare.summary[0][0].startswith("Las máscaras de V02 no se han compilado"))
        self.set_active(self.v01)
        self.assertEqual(self.pump().seeds.total, 24 * 24 - 22 * 22 + 16)
        design.disable()

        self.ps.take_notices()
        self.assertEqual(bpy.ops.geoblender.des_design_quarry(
            "EXEC_DEFAULT", preview=True, **self.quarry_form(floors_field="nada")), {"FINISHED"})
        self.assertEqual(design.plan(), design.QuarryPlan(
            replace(request, floors=m.LayerField(FLOORS_LAYER, "nada"))))
        self.assertIsNone(self.run_to_end())
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        (notice,) = self.ps.take_notices()
        self.assertTrue(notice.startswith("No se pudo preparar la vista previa de semillas, "
                                          "dominios y restricciones: "), notice)
        self.assertIn(f"La capa «{FLOORS_LAYER}» no tiene el campo numérico «nada»", notice)
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)

    def test_z_disabling_geoblender_with_the_preview_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa activa, desactivar Geoblender quita los manejadores de
        dibujo, los avisos, el temporizador y los lotes, y la huella de Blender vuelve a la del
        principio de la sesión."""
        design = self.design
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertTrue(design.drawing())
        self.assertTrue(bpy.app.timers.is_registered(design.tick))  # la construcción, sin acabar
        blender_ext.release()
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
