# SPDX-License-Identifier: GPL-3.0-or-later
"""HITO H2 de la corta por bancos: E1 a E5 en ``blender -b`` con CE-018-01 a CE-018-11 (spec 018, T26; HU-018-1 a HU-018-5; RF-018-01 a RF-018-06,
RF-018-08 a RF-018-13, RF-018-16 a RF-018-31; RF-015-15 a RF-015-17; plan 018 §7.1 y §7.5).

Sin pantalla y **sin las órdenes de la interfaz** (que son la fase H): la corta se crea, se recalcula y se encadena con las funciones del dominio
(``design.steps.pit_run``, ``design.entity_store``, ``core.provenance.recompute``…) **tal como las deja registradas la extensión habilitada** (las de
``bl.ops.des``, con su cola de recálculo, que en ``blender -b`` se mueve a mano con ``des_tick``), sobre un proyecto de verdad creado con
``core.project``: si la corta no se crea, recalcula y encadena bien aquí, un fallo de la interfaz ya no se confundiría con uno del dominio.

El proyecto: la ventana de 400 × 400 m con celdas de 2 m (200 × 200); V01 y V02; los perfiles ``EXPL_10_60_6``, ``EXPL_10_45_6`` (ancla 125 m) y
``DESD_10_45_6`` y ``DESD_10_60_6`` (ancla 100 m) con los valores de prueba de la 013; los perfiles de pista ``PISTA_PRINCIPAL`` (Rmín 12 m),
``PISTA_SIETE`` (7 m) y ``PISTA_OCHO`` (8 m); la roseta de CE-018-02; una espiral y un zig-zag; el límite legal, el perímetro de actuación y un
intocable; tres sectores (oeste, este y la franja sur, esta con la búsqueda de intocables sin hacer al principio). Las cuentas, **a mano**, como las de
los hitos H1 (``tests/unit/design/milestone_pit_h1.py``) y de la 015 a la 017 sin Blender, que este no sustituye: aquí se repite lo que no cabe sin
la extensión registrada. Los datos puros no se importan de ``tests/support`` (cargan una segunda copia del paquete: ``docs/trampas.md`` §4).

Una sola historia, en el orden de las letras (el proyecto es de la clase; cada prueba parte de lo que dejó la anterior). **V01**:

- **a** (CE-018-08, RF-018-05): un sector sin búsqueda de intocables rechaza la corta y nombra la orden; no deja nada.
- **b** (E1; CE-018-01, 03, 11; RF-018-10, 11, 28, 31): la corta circular sin rampa (cinco bancos, volumen a ≤ 0,1 % del analítico, cada banco su
  tronco de cono, el reparto igual al de la cubicación de la 011 a ≤ 10⁻⁹), creada: la operación, sus ocho datos y sus cifras.
- **c** (CE-018-01): el cuadrado de 100 m: la cresta a 5,7735 m del pie, el pie siguiente a 11,7735 m y el área de la cresta.
- **d** (E1; CE-018-05, 11): la ascendente con la espiral de ``PISTA_SIETE``: el eje, la pendiente de la rampa y la cota de cada banco.
- **e** (E2; CE-018-04): la descendente desde el límite cuadrado: lados 180, 148, 116, 84 y 52 m y se detiene por el ancho; con la cota de fondo, 3
  bancos; el límite que queda vacío se rechaza.
- **f** (E2; CE-018-06, RF-018-19): la descendente con el zig-zag de ``PISTA_OCHO``; la zona sin rampa que cruza el eje se rechaza con el banco y lo que falta.
- **g** (E3; CE-018-02): la roseta con n = 2 y los sectores con perfiles distintos, sin huecos.
- **h** (CE-018-07): sobre el terreno inclinado, la línea de cielo tiene la cota del terreno y la distancia al límite legal es la de la cuenta a mano.
- **i** (E4, parte; CE-018-08, 09): el perímetro y el intocable; el banco 2 fijado con una capa (hash igual, capa editada = obsoleta); la lista de hallazgos.
- **j** (E5; CE-018-11, RF-018-27): la verificación por recinto de la 012 cumple; el contraste con la 013.
- **ia** (E4, parte; RF-018-22, P-12): «Expandir banco…» sobre el pie del banco 1 de la corta circular (la capa ``des_pbl_``): da la cresta del banco 1, y crearla deja la capa
  ``des_pxb_`` editable con la operación ``des.pit_expand`` y su cifra, sin entidad ni superficie.
- **k** (CE-018-10, RF-018-25, RF-009-11): congelar V01, reproducir sin escribir y traer una corta a otra versión.
- **kb** (RF-018-22, RF-009-11): la expansión de **ia**, reproducida de lo congelado, da la misma capa (hash) y la misma cifra.

**V02**: **l** y **m** (E5; CE-018-10): la corta, la plataforma, la pista y otra corta que declara su apoyo; la cascada en «Recalcular lo obsoleto» (con la
cola real) y descartar la corta («apoyo retirado»). **n** (E4, la capa editada en QGIS; P-12): la capa de la expansión de **ia** editada fuera de Geoblender no
se bloquea, deja obsoleta la expansión que parte de ella y repetir la primera no la sobrescribe. El ensayo con el ratón, la vista previa, el TIN y la orden
de «Expandir banco…» son de las fases G y H (T29 a T35) y del H3.

Se ejecuta con ``tools/run_blender_tests.py`` (paso «hito» de ``tools/check.py --completo``).
"""

import importlib
import json
import math
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
from tests.support.trees import remove_tree

PERSON = "Samuel (IMGA)"
REASON = "Prueba del hito H2 de la corta"
SOURCE = "Estudio de la prueba"
CLOSED_AT = "2026-11-23T10:00:00Z"
LAYERS_TYPE = "gis.test_pit_h2"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 400.0
STEP_M = 2.0
CELLS = int(SIZE_M / STEP_M)
CENTER = (200.0, 200.0)
FLOOR_Z, TOP_Z, LIMIT_Z, BOTTOM_Z = 125.0, 175.0, 100.0, 70.0
HEIGHT, FACE, BERM = 10.0, 60.0, 6.0
ARC_M, SIMPLIFY_M = 0.05, 0.05
EXPL, EXPL45, DESD, DESD60 = "EXPL_10_60_6", "EXPL_10_45_6", "DESD_10_45_6", "DESD_10_60_6"
FLOORS, FLOORS_SOUTH, FLOORS_SQUARE, FLOORS_CORNER = "gis_fea_h2_fondos", "gis_fea_h2_fondo_sur", "gis_fea_h2_fondo_cuadrado", "gis_fea_h2_fondo_esquina"
LIMITS, LIMITS_RECT, LIMITS_SMALL, NO_RAMP = "gis_fea_h2_limite", "gis_fea_h2_limite_rect", "gis_fea_h2_limite_chico", "gis_fea_h2_sin_rampa"
FIXED_LAYER = "gis_brk_h2_banco_2"
PLATFORM_LAYER, AXIS_LAYER = "gis_fea_h2_plataformas", "gis_fea_h2_ejes"
ROAD_PROFILE_VALUES = {"vehicle_width_m": 3.5, "lane_factor": 3.0, "shoulder_m": 0.0, "berm_m": 1.0, "max_gradient_pct": 10.0, "station_step_m": 1.0,
                       "max_mean_gradient_pct": 10.0, "curve_radius_m": 20.0, "min_radius_m": 12.0, "cut_angle_deg": 60.0, "fill_angle_deg": 35.0,
                       "reach_m": 60.0, "class": "Pista de acceso"}
"""El perfil de pista de referencia de IMGA (``spec.md`` de la 017 §11, solo para pruebas)."""
VOLUME_TOL = 1e-3
"""D-11: ≤ 0,1 % (HIPÓTESIS) con celdas de ≤ 2 m."""
REPORT: list[str] = []
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def absolute(points: Any) -> np.ndarray:
    """Los puntos locales (m desde la esquina suroeste) como absolutos, float64 ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) + np.array([WEST, SOUTH])


def local(points: np.ndarray) -> np.ndarray:
    """Los puntos absolutos ``(k, ≥ 2)`` como locales ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64)[:, :2] - np.array([WEST, SOUTH])


def circle(radius: float, center: tuple[float, float] = CENTER, vertices: int = 720) -> np.ndarray:
    """El anillo circular antihorario local de ``vertices`` vértices (sin repetir el primero)."""
    angle = 2.0 * math.pi * np.arange(vertices) / vertices
    return np.column_stack([center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle)])


def rectangle(length: float, width: float, center: tuple[float, float] = CENTER) -> np.ndarray:
    """El rectángulo antihorario local de cuatro vértices, desde el suroeste."""
    hx, hy = length / 2.0, width / 2.0
    return np.array([[center[0] - hx, center[1] - hy], [center[0] + hx, center[1] - hy], [center[0] + hx, center[1] + hy], [center[0] - hx, center[1] + hy]])


def box_ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``(izquierda, abajo, derecha, arriba)``."""
    left, bottom, right, top = box
    return absolute([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)])


def centers() -> tuple[np.ndarray, np.ndarray]:
    """Los centros de celda locales ``(x, y)`` de la ventana (la fila 0 es el norte)."""
    index = np.arange(CELLS, dtype=np.float64)
    return np.meshgrid(STEP_M * index + STEP_M / 2, SIZE_M - (STEP_M * index + STEP_M / 2))


def flat(z: float) -> np.ndarray:
    return np.full((CELLS, CELLS), z, dtype=np.float64)


def inclined() -> np.ndarray:
    """CE-018-07: el terreno que sube un 10 % hacia el este, de 130 m en x = 0 (150 m en el centro de la corta)."""
    x, _y = centers()
    return 130.0 + 0.10 * x


def inside(box: tuple[float, float, float, float]) -> np.ndarray:
    x, y = centers()
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def circle_radii(radius: float = 50.0, benches: int = 5) -> list[tuple[float, float]]:
    """Los radios ``(pie_k, cresta_k)`` de la corta circular a mano (``h/tan α`` de cara y ``B`` de berma)."""
    run = HEIGHT / math.tan(math.radians(FACE))
    found, foot = [], radius
    for _ in range(benches):
        found.append((foot, foot + run))
        foot = foot + run + BERM
    return found


def circle_volume(radius: float = 50.0, benches: int = 5) -> float:
    """El volumen analítico de la corta circular sobre un terreno llano a la cresta del último banco (CE-018-03): 961.661,57 m³."""
    return math.fsum(math.pi * HEIGHT / 3.0 * (r * r + r * big + big * big) for r, big in circle_radii(radius, benches))


def shoelace(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


class PitH2Test(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de las cortas, para toda la clase (las pruebas, en el orden de sus letras)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.made: dict[str, Any] = {}  # lo que una prueba deja a la siguiente
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t26-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.des_ops = _module("bl.ops.des")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.core_params = _module("core.params")
        cls.access = _module("gis.masks.access")
        cls.gis_store = _module("gis.store")
        cls.entities = _module("design.entities")
        cls.entity_store = _module("design.entity_store")
        cls.messages = _module("design.messages")
        cls.dmodel = _module("design.model")
        cls.pit_model = _module("design.pit_model")
        cls.pit_lines = _module("design.pit_lines")
        cls.pit_store = _module("design.pit_store")
        cls.pit_expand = _module("design.pit_expand")
        cls.external = _module("core.datasets.external")
        cls.pit_rose = _module("design.pit_rose")
        cls.pit_ramp_def = _module("design.pit_ramp_def")
        cls.road_model = _module("design.road_model")
        cls.road_profiles = _module("design.road_profiles")
        cls.dprov = _module("design.provenance")
        cls.steps = _module("design.steps")
        cls.surfaces = _module("design.surfaces")
        cls.dstore = _module("design.store")
        cls.recompute = _module("core.provenance.recompute")
        cls.freeze = _module("core.versions.freeze")
        cls.reproduce = _module("core.versions.reproduce")
        cls.volumes = _module("reserves.volumes")
        cls.rsurfaces = _module("reserves.surfaces")
        cls.kernel = _module("reserves.kernel")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="corta", title="Corta", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="cadena", title="Cadena", reason=REASON)
            cls.v03, _revision = store.create_version(conn, cls.project, feature="traida", title="Traída", reason=REASON)
        cls.project.refresh_header()
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False))
        cls.addClassCleanup(contract.unregister_operation, LAYERS_TYPE)
        cls.declare_constraints()
        cls.declare_sectors()
        for code in ("sector_1", "sector_2"):
            cls.close_search(code)  # el tercero queda sin búsqueda: CE-018-08
        cls.write_terrains()
        cls.write_layers()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        for name, face, anchor in ((EXPL, "60", "125"), (EXPL45, "45", "125"), (DESD, "45", "100"), (DESD60, "60", "100")):
            assert bpy.ops.geoblender.des_save_bench_profile(name=name, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON, scope="PROJECT",
                                                              height="10", face=face, berm="6", anchor=anchor) == {"FINISHED"}
        cls.write_road_profiles_roses_and_ramps()
        cls.compile_masks()

    # --- El proyecto -----------------------------------------------------------------------------------------------

    @classmethod
    def compile_masks(cls) -> None:
        """Compila y carga las máscaras de las tres versiones (cualquier cambio de un sector, una búsqueda o un parámetro las deja obsoletas)."""
        cls.masks = {}
        for version in (cls.v01, cls.v02, cls.v03):
            assert bpy.ops.geoblender.core_set_active_version(version_uid=version.uid) == {"FINISHED"}
            assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}
            cls.masks[version.uid] = cls.access.load_masks(cls.project, version.uid)
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}

    @classmethod
    def declare_constraints(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y un intocable (en el hueco de la corta de la esquina)."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON, parts=((box_ring(box),),), priority=0,
                                reason=f"{REASON}: {name}", decided_by=PERSON, decided_on=date(2026, 11, 23), decision_uid=None, intention_uid=None,
                                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", (8.0, 8.0, 392.0, 392.0)), row(types.ACTION_PERIMETER, "Perímetro", (20.0, 20.0, 380.0, 340.0)),
                row(types.UNTOUCHABLE, "Elemento intocable", (318.0, 318.0, 326.0, 326.0))]
        declaration = cls.cprov.ParamDeclaration(values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 0.0, m.ConstraintParam.ACTIVE: True},
                                                 source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, rows, params=declaration, srs_id=cls.project.record.crs_epsg)

    SECTOR_BOXES = {"Sector oeste": (0.0, 60.0, 200.0, 400.0), "Sector este": (200.0, 60.0, 400.0, 400.0), "Sector sur": (0.0, 0.0, 400.0, 60.0)}

    @classmethod
    def declare_sectors(cls) -> None:
        sectors = tuple(cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name, (box_ring(box),))
                        for index, (name, box) in enumerate(cls.SECTOR_BOXES.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str) -> None:
        """Cierra la búsqueda de intocables del sector ``code``, como la orden de la 012."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, code, cls.cstore.sector_sha256(sector), 25.0, PERSON, CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto con ``values``; el nombre de su dato."""
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = cls.gis_store.project_references(cls.project)
        handle = _module("core.provenance.operations").begin_operation(cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
                                                                       executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with cls.gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

    @classmethod
    def write_terrains(cls) -> None:
        """Los terrenos de partida: de cada superficie parte **una sola** entidad, así que cada corta tiene el suyo."""
        cls.terrain: dict[str, str] = {}
        for label, values in (("llano", flat(TOP_Z)), ("cuadrado", flat(TOP_Z)), ("rampa", flat(TOP_Z)), ("roseta", flat(TOP_Z)), ("fijado", flat(TOP_Z)),
                              ("esquina", flat(TOP_Z)), ("inclinado", inclined()), ("limite", flat(LIMIT_Z)), ("limite_b", flat(LIMIT_Z)),
                              ("limite_c", flat(LIMIT_Z)), ("limite_d", flat(LIMIT_Z)), ("zigzag", flat(LIMIT_Z)), ("zigzag_b", flat(LIMIT_Z)),
                              ("sur", flat(TOP_Z)), ("cadena", flat(TOP_Z)), ("cadena_b", flat(TOP_Z)), ("cadena_c", flat(TOP_Z))):
            cls.terrain[label] = cls.write_grid(f"h2 {label}", values)

    @classmethod
    def write_layer(cls, name: str, kind: str, entities: tuple[Any, ...], names: tuple[str, ...], fields: dict[str, tuple[Any, ...]]) -> None:
        """Una capa ``gis_fea_…`` con el campo ``nombre`` y los campos ``fields`` (``TEXT`` si alguno es un texto y ``DOUBLE`` si no), como la deja la 006."""
        vector, datasets, builtin = _module("gis.vector"), _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        kinds = {field: "TEXT" if any(isinstance(item, str) for item in values) else "DOUBLE" for field, values in fields.items()}
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), *(vector.FieldColumn(field, field, sql) for field, sql in kinds.items()))
        values = {"nombre": names, **{field: tuple(found) for field, found in fields.items()}}
        layer = vector.FeatureLayer(kind, tuple(range(1, len(entities) + 1)), entities, columns, values)
        rows = cls.gis_store.feature_rows(layer, srs)
        column_names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        handle = _module("core.provenance.operations").begin_operation(cls.project, LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, {column_names})')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (name, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features",
                                                                crs_epsg=srs, input_uid=None, immutable=False),), message="Capa de prueba de la corta")

    @classmethod
    def write_polygons(cls, name: str, rings: list[np.ndarray], names: list[str], **fields: list[float]) -> None:
        cls.write_layer(name, "polygon", tuple(((absolute(item),),) for item in rings), tuple(names), {key: tuple(value) for key, value in fields.items()})

    @classmethod
    def write_breaklines(cls, name: str, lines: list[np.ndarray]) -> None:
        """Las líneas con Z (absolutas, ``(n, 3)``) como la tabla de líneas de rotura ``name`` (``gis_brk_…``), como la deja la importación de la 006."""
        breaklines, datasets, builtin = _module("gis.breaklines"), _module("core.datasets"), _module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        rows = cls.gis_store.breakline_rows([breaklines.Breakline(f"S{number}", np.ascontiguousarray(line, dtype=np.float64)) for number, line in enumerate(lines, 1)], srs)
        handle = _module("core.provenance.operations").begin_operation(cls.project, LAYERS_TYPE, settings={"name": name}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, line_id TEXT NOT NULL DEFAULT \'\', hard BOOLEAN NOT NULL, '
                         "code TEXT NOT NULL DEFAULT '')")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', 'LINESTRING', ?, 1, 0)",
                         (name, srs))
            conn.executemany(f'INSERT INTO "{name}" (geom, line_id, hard, code) VALUES (?, ?, ?, ?)', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features",
                                                                crs_epsg=srs, input_uid=None, immutable=False),), message="Líneas 3D de prueba de la corta")

    @classmethod
    def write_layers(cls) -> None:
        cls.write_polygons(FLOORS, [circle(50.0)], ["Fondo circular"], cota_m=[FLOOR_Z])
        cls.write_polygons(FLOORS_SQUARE, [rectangle(100.0, 100.0)], ["Fondo cuadrado"], cota_m=[FLOOR_Z])
        cls.write_polygons(FLOORS_SOUTH, [circle(20.0, (200.0, 50.0))], ["Fondo del sur"], cota_m=[165.0])
        cls.write_polygons(FLOORS_CORNER, [circle(25.0, (330.0, 325.0))], ["Fondo de la esquina"], cota_m=[165.0])
        cls.write_polygons(LIMITS, [rectangle(200.0, 200.0)], ["Límite cuadrado"])
        cls.write_polygons(LIMITS_RECT, [rectangle(300.0, 200.0)], ["Límite rectangular"])
        cls.write_polygons(LIMITS_SMALL, [rectangle(40.0, 40.0)], ["Límite pequeño"])
        cls.write_polygons(NO_RAMP, [rectangle(30.0, 30.0, (100.0, 120.0))], ["Zona sin rampa"])
        line = ((absolute([(160.0, 200.0), (240.0, 200.0)]),),)
        axis = ((absolute([(165.0, 210.0), (235.0, 210.0)]),),)
        cls.write_layer(PLATFORM_LAYER, "line", (line,), ("Plataforma sobre la corta",), {"ancho": (10.0,), "cota_inicial": (FLOOR_Z + 1.0,), "pendiente": (0.0,)})
        cls.write_layer(AXIS_LAYER, "line", (axis,), ("Pista sobre la plataforma",), {})

    @classmethod
    def write_road_profiles_roses_and_ramps(cls) -> None:
        """Los perfiles de pista, la roseta de CE-018-02 y las rampas de la prueba, con su origen (como las deja «Pistas…», «Rosetas…» y «Rampas…» de la 018)."""
        by_hand = {"source": SOURCE, "decided_by": PERSON, "reason": REASON}
        profiles = cls.road_profiles
        edits = [profiles.ProfileEdit(name=name, values={**ROAD_PROFILE_VALUES, "min_radius_m": radius})
                 for name, radius in (("PISTA PRINCIPAL", 12.0), ("PISTA SIETE", 7.0), ("PISTA OCHO", 8.0))]
        profiles.edit_road_profiles(cls.project, tuple(edits), profiles.ProfileDeclaration(**by_hand))
        cls.pit_rose.edit_pit_roses(cls.project, [cls.pit_rose.RoseEdit(name="Roseta del tajo", ranges=[cls.pit_rose.RoseRange(0.0, 180.0, 60.0, 6.0),
                                                                                                    cls.pit_rose.RoseRange(180.0, 360.0, 45.0, 6.0)])],
                                    cls.pit_rose.Declaration(**by_hand))
        cls.rose = "roseta_del_tajo"
        spiral = {"type": "spiral", "sense": "ccw", "start": "fondo", "gradient_pct": 8.0, "road_profile": "pista_siete", "transition_m": 0.0}
        zigzag = {"type": "zigzag", "sense": "ccw", "start": "fondo", "gradient_pct": 10.0, "road_profile": "pista_ocho", "transition_m": 0.0,
                  "turn_radius_m": 12.0, "min_platform_m": 40.0}
        cls.ramps = {}
        for name, values in (("Espiral", spiral), ("Zig-zag", zigzag)):
            cls.ramps[name] = cls.pit_ramp_def.edit_pit_ramps(cls.project, [cls.pit_ramp_def.RampEdit(name=name, values=values)],
                                                              cls.pit_rose.Declaration(**by_hand)).created[0]

    # --- Ayudas ----------------------------------------------------------------------------------------------------

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def request(self, name: str, *, mode: str = "up", source: str = FLOORS, start: str = "llano", **changes: Any) -> Any:
        base: dict[str, Any] = {"profile": EXPL.lower(), "arc_tol_m": ARC_M, "simplify_m": SIMPLIFY_M}
        if mode == "up":
            base["level_field"] = "cota_m"
        else:
            base["bottom_level_m"] = None
        return self.pit_model.PitRequest(name, self.road_model.LayerFields(source, "nombre"), mode, self.terrain[start], **{**base, **changes})

    def calculate(self, asked: Any, version: Any = None, **options: Any) -> Any:
        """«Calcula» ``asked``: la ``Calculation`` abierta (nada registrado); un rechazo sale al avanzar."""
        version = version or self.v01
        options.setdefault("masks", self.masks[version.uid])
        found = None
        for step in self.steps.pit_run(self.project, asked, version=version.uid, **options):
            found = step.result
        assert found is not None
        return found

    def create(self, asked: Any, version: Any = None, **options: Any) -> tuple[Any, str]:
        """Calcula y crea: el cálculo (ya cerrado) y el uid de la operación."""
        calculation = self.calculate(asked, version, **options)
        stored = calculation.create(decided_by=PERSON)
        return calculation, str(stored.handle.uid)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def counts(self) -> list[Any]:
        return [self.rows(f"SELECT count(*) FROM {table}")[0][0] for table in ("gb_operation", "gb_dataset", "gb_figure", "gb_parameter")]

    def figures_of(self, uid: str) -> dict[str, float]:
        return {key: float(value) for key, value in self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def surface_of(self, name: str) -> str:
        return str(self.dprov.dataset_name(self.dprov.ENTITY_SURFACE_GRID, name))

    def line(self, found: Any, kind: str, bench: int, part: int = 0) -> np.ndarray:
        """Los vértices locales ``(k, 2)`` de la polilínea ``kind`` del banco ``bench`` (la parte ``part``)."""
        item = next(poly for poly in found.polylines if poly.kind == kind and poly.bench == bench and poly.part == part)
        return local(item.vertices)

    def levels(self, found: Any, kind: str, bench: int) -> np.ndarray:
        return next(poly for poly in found.polylines if poly.kind == kind and poly.bench == bench).vertices[:, 2]

    def stale_causes(self, uid: str) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for cause, subject in self.rows("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid):
            named = self.rows("SELECT key FROM gb_parameter WHERE uid = ? UNION ALL SELECT name FROM gb_dataset WHERE uid = ?", subject, subject)
            found.add((cause, subject if not named else named[0][0]))
        return found

    def current(self, version: Any, code: str) -> str:
        entry = self.entities.registry(self.project, version.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def states(self, version: Any) -> dict[str, Any]:
        return {entry.record.code: entry.record.state for entry in self.entities.registry(self.project, version.uid)}

    def hashes(self, *names: str) -> dict[str, tuple[str, ...]]:
        return {name: tuple(self.rows("SELECT content_sha256, status FROM gb_dataset WHERE name = ? AND status = 'current'", name)[0]) for name in names}

    def run_recompute(self) -> Any:
        """«Recalcular lo obsoleto» con lo que registra la extensión (cada recálculo, en la cola de ``des``: en ``blender -b`` la mueve ``des_tick``)."""
        work = self.recompute.recompute_steps(self.project)
        outcome = None
        for _ in range(20_000):
            try:
                step = next(work)
            except StopIteration:
                break
            self.des_ops.des_tick()
            outcome = step.result if step.result is not None else outcome
        else:
            self.fail("el recálculo no acaba")
        self.assertEqual(self.des_ops.pending_runs(), [])
        return outcome

    def change(self, key: str, value: Any, version: Any) -> None:
        with self.project.write_transaction() as conn:
            self.core_params.ParameterStore(self.project).change(conn, key, value=value, source="prueba del hito H2", source_kind="person", decided_by=PERSON,
                                                                 reason="Se cambia un parámetro de la corta", version=version.uid)

    # --- a: un sector sin búsqueda ---------------------------------------------------------------------------------

    def test_a_a_sector_without_the_search_refuses_the_pit_and_names_the_order(self) -> None:
        """CE-018-08, RF-018-05, RF-015-07: la corta que toca un sector sin la búsqueda de intocables vigente se rechaza al avanzar, con
        ``des.sector_pending``, que nombra la orden «Buscar elementos intocables por sector…» y el sector; no escribe nada. Con la búsqueda hecha, se calcula."""
        asked = self.request("Corta del sur", source=FLOORS_SOUTH, start="sur")
        before = self.counts()
        with self.assertRaises(self.messages.DesignError) as caught:
            self.calculate(asked)
        self.assertEqual(caught.exception.code, "des.sector_pending")
        self.assertIn("Sector sur", str(caught.exception))
        self.assertIn("intocables", str(caught.exception))
        self.assertEqual(self.counts(), before, "el rechazo no deja nada")
        self.close_search("sector_3")
        self.compile_masks()
        calculation = self.calculate(asked)
        self.assertGreater(calculation.outcome.figures[0].value, 0.0)
        before = self.counts()
        calculation.discard()
        self.assertEqual(self.counts(), before)

    # --- b: la corta circular --------------------------------------------------------------------------------------

    def test_b_the_circular_pit_gives_the_analytic_volume_and_is_created_with_its_eight_data(self) -> None:
        """E1, CE-018-01, 03, 11; RF-018-10, 11, 28, 31, RF-015-01, RF-015-02: la corta circular de 50 m de radio con ``EXPL_10_60_6`` y cinco bancos sobre el
        terreno llano a 175 m da el volumen analítico a ≤ 0,1 % (celdas de 2 m), cada banco anclado a 125 + 10·k, el pie y la cresta con los radios a mano, cada
        banco su tronco de cono (≤ 0,1 %) y el reparto igual al de la cubicación de la 011 (≤ 10⁻⁹); «Crear» deja una operación con los ocho datos."""
        calculation, uid = self.create(self.request("Corta circular"))
        found = calculation.outcome
        self.assertEqual((found.code, str(found.stop)), ("PIT-001", "surface"))
        figures = {item.key: item.value for item in found.figures}
        exact = circle_volume()
        diff = figures["des.pit_cut_m3"] / exact - 1.0
        REPORT.append(f"CE-018-03: {figures['des.pit_cut_m3']:,.1f} m³ frente a {exact:,.2f} a mano ({diff * 100:+.4f} %)")
        self.assertLessEqual(abs(diff), VOLUME_TOL)
        self.assertEqual(figures["des.pit_benches"], 5.0)
        sagitta = 50.0 * (1.0 - math.cos(math.pi / 720))
        for bench, (foot, crest) in enumerate(circle_radii()):
            for kind, radius, level in (("foot", foot, FLOOR_Z + HEIGHT * bench), ("crest", crest, FLOOR_Z + HEIGHT * (bench + 1))):
                points = self.line(found, kind, bench) - np.array(CENTER)
                np.testing.assert_allclose(self.levels(found, kind, bench), level, rtol=0.0, atol=1e-9)
                self.assertAlmostEqual(float(np.hypot(points[:, 0], points[:, 1]).mean()), radius, delta=ARC_M + sagitta + 1e-3, msg=f"{kind} {bench}")
        by_bench = {item.bench: item.cut_m3 for item in found.benches}
        for bench, (foot, crest) in enumerate(circle_radii()):
            frustum = math.pi * HEIGHT / 3.0 * (foot * foot + foot * crest + crest * crest)
            self.assertLess(abs(by_bench[bench] / frustum - 1.0), VOLUME_TOL, f"banco {bench}")
        self.assertAlmostEqual(sum(by_bench.values()) / figures["des.pit_cut_m3"], 1.0, delta=1e-9)
        # la cubicación de la 011 entre la partida y la superficie de la corta (CE-018-11)
        start = self.terrain["llano"]
        result = self.cubicate(start, self.surface_of("Corta circular"))
        self.assertAlmostEqual(float(result.cut_m3[self.kernel.ALL]) / figures["des.pit_cut_m3"], 1.0, delta=1e-9)
        grid = _module("gis.grid").project_grid(self.project.record.window, float(self.project.record.grid_step_m))
        accumulators = self.kernel.Accumulators(grid, slices=_module("reserves.slices").Slices(HEIGHT, FLOOR_Z, None))
        self.kernel.band_step(accumulators, self.kernel.BandValues(0, flat(TOP_Z), found.compose(flat(TOP_Z))))
        sliced = accumulators.result()
        slack = len(sliced.slice_cut_m3[self.kernel.ALL]) - 5
        for item in found.benches:
            self.assertAlmostEqual(item.cut_m3 / float(sliced.slice_cut_m3[self.kernel.ALL][slack + item.bench]), 1.0, delta=1e-9, msg=f"banco {item.bench}")
        # lo creado
        self.assertEqual(self.rows("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [(self.dprov.PIT, "version", "done")])
        outputs = self.rows("SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND "
                            "io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)
        self.assertEqual(len(outputs), 8)
        registered = self.figures_of(uid)
        self.assertEqual(registered["des.pit_cut_m3"], figures["des.pit_cut_m3"])
        self.assertEqual(self.states(self.v01), {"PIT-001": self.entities.EntityState.CURRENT})
        type(self).made["circle"] = SimpleNamespace(uid=uid, found=found, name="Corta circular")
        # E5: el contraste con la 013 (CE-018-12 sintético)
        contrast = found.extra["contrast"]
        self.assertLess(abs(contrast.volume_diff_pct) / 100.0, 1e-2)
        self.assertLess(contrast.above_max_m, HEIGHT)
        REPORT.append(f"E5 contraste con la 013: {contrast.volume_diff_pct:+.3f} % en volumen; por encima, a lo sumo {contrast.above_max_m:.2f} m")

    def cubicate(self, start: str, final: str) -> Any:
        """La cubicación de la 011 de ``start`` frente a ``final`` (dos rejillas registradas): su ``KernelResult``."""
        refs = self.rsurfaces.SurfaceRef
        sources = {"start": self.rsurfaces.surface_source(self.project, refs(dataset=start), version_uid=self.v01.uid),
                   "final": self.rsurfaces.surface_source(self.project, refs(dataset=final), version_uid=self.v01.uid)}
        request = self.volumes.VolumeRequest("Comprobación", refs(dataset="arriba"), refs(dataset="abajo"), min_thickness_m=0.0)
        found = None
        for found in self.volumes.volume_steps(request, sources):
            pass
        return found.result.kernel

    # --- c: el cuadrado de 100 m -----------------------------------------------------------------------------------

    def test_c_the_square_floor_gives_the_reference_offset(self) -> None:
        """CE-018-01, RF-018-10: el fondo cuadrado de 100 m con ``EXPL_10_60_6`` da una cresta a 5,7735 m del pie (h/tan α) y el pie siguiente a 11,7735 m; el
        área de la cresta es L² + 4·L·d + π·d² = 12.414,12 m², dentro de la tolerancia de arco por el perímetro."""
        calculation = self.calculate(self.request("Corta cuadrada", source=FLOORS_SQUARE, start="cuadrado"))
        found = calculation.outcome
        d = HEIGHT / math.tan(math.radians(FACE))
        self.assertAlmostEqual(d, 5.7735, places=4)
        crest = self.line(found, "crest", 0)
        by_hand = 100.0 * 100.0 + 4.0 * 100.0 * d + math.pi * d * d
        self.assertAlmostEqual(by_hand, 12_414.12, delta=0.01)
        perimeter = float(np.hypot(*np.diff(np.vstack([crest, crest[:1]]), axis=0).T).sum())
        self.assertLessEqual(abs(shoelace(crest) - by_hand), perimeter * ARC_M, "el área de la cresta")
        for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
            self.assertAlmostEqual(sign * (crest[:, axis] - CENTER[axis]).max() if sign > 0 else -(crest[:, axis] - CENTER[axis]).min(), 50.0 + d, delta=ARC_M)
        foot = self.line(found, "foot", 1)
        self.assertAlmostEqual(float((foot[:, 0] - CENTER[0]).max()), 50.0 + d + BERM, delta=ARC_M)
        self.assertAlmostEqual(float((foot[:, 0] - CENTER[0]).max()), 50.0 + 11.7735, delta=ARC_M)
        self.assertFalse([item for item in found.notices if item.code == "des.pit_offset_unreliable"], "el resultado es simple")
        calculation.discard()
        REPORT.append(f"CE-018-01: área de la cresta {shoelace(crest):,.2f} m² frente a {by_hand:,.2f} a mano")

    # --- d: la espiral -----------------------------------------------------------------------------------------------

    def test_d_the_ascending_pit_with_a_spiral_ramp(self) -> None:
        """E1, CE-018-05, CE-018-11, RF-018-16 a 21: la corta circular con la espiral de 8 % del perfil ``PISTA_SIETE`` (Rmín 7 m) sube de 125 a 175 m con la
        cota de cada banco igual a su ancla, a una pendiente máxima de 8,04 %, media de 7,58 % (≤ pm) y un eje redondeado de 659 m; la superficie cubica
        con la 011 y el volumen por banco suma el total (≤ 10⁻⁹). La ventana de trabajo contiene el movimiento de la rampa (la banda ensancha cada banco)."""
        started = time.process_time()
        calculation, uid = self.create(self.request("Corta con espiral", source=FLOORS, start="rampa", ramps=(self.ramps["Espiral"],), simplify_m=1e-6))
        found = calculation.outcome
        REPORT.append(f"CE-018-05: la corta con la espiral se calcula y crea en {time.process_time() - started:.1f} s de CPU")
        (ramp,) = found.ramps
        self.assertEqual((float(ramp.axis[0, 2]), float(ramp.axis[-1, 2])), (FLOOR_Z, TOP_Z))
        self.assertEqual(set(np.unique(found.extra["checked_ramps"][0].benches)), {0, 1, 2, 3, 4})
        figures = self.figures_of(uid)
        self.assertAlmostEqual(figures["des.pit_ramp_gradient_max_pct"], 8.04, delta=0.01)
        self.assertAlmostEqual(figures["des.pit_ramp_gradient_mean_pct"], 7.58, delta=0.01)
        self.assertLessEqual(figures["des.pit_ramp_gradient_mean_pct"], 10.0)
        self.assertAlmostEqual(figures["des.pit_ramp_len_m"], 659.7, delta=0.5)
        self.assertFalse(found.extra["mean_pending"], "la media no pasa de pm: sin confirmar")
        by_bench = {item.bench: item.cut_m3 for item in found.benches}
        self.assertAlmostEqual(sum(by_bench.values()) / figures["des.pit_cut_m3"], 1.0, delta=1e-9)
        result = self.cubicate(self.terrain["rampa"], self.surface_of("Corta con espiral"))
        self.assertAlmostEqual(float(result.cut_m3[self.kernel.ALL]) / figures["des.pit_cut_m3"], 1.0, delta=1e-9)
        self.assertGreater(figures["des.pit_cut_m3"], circle_volume(), "la banda de la rampa añade corte")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ? AND status = 'done'", self.dprov.PIT)[0][0], 2)
        type(self).made["spiral"] = SimpleNamespace(uid=uid, found=found, name="Corta con espiral")

    # --- e: la descendente --------------------------------------------------------------------------------------------

    def test_e_the_descending_pit_from_the_square_limit(self) -> None:
        """E2, CE-018-04, RF-018-02, RF-018-13: el límite cuadrado de 200 m sobre el terreno llano a 100 m con ``DESD_10_45_6`` y un ancho mínimo de fondo de
        30 m da cinco bancos con los lados de pie de 180, 148, 116, 84 y 52 m y se detiene por el ancho; con la cota de fondo de 70 m, a los 3 bancos; un
        límite que queda vacío antes del primer banco se rechaza."""
        asked = self.request("Corta del límite", mode="down", source=LIMITS, start="limite", profile=DESD.lower(), min_floor_width_m=30.0)
        calculation, _uid = self.create(asked)
        found = calculation.outcome
        self.assertEqual((str(found.stop), len(found.benches)), ("floor_width", 5))
        for bench, side in enumerate((180.0, 148.0, 116.0, 84.0, 52.0)):
            foot = self.line(found, "foot", bench)
            self.assertAlmostEqual(float(foot[:, 0].max() - foot[:, 0].min()), side, delta=0.1, msg=f"el lado del pie del banco {bench}")
            np.testing.assert_allclose(self.levels(found, "foot", bench), LIMIT_Z - HEIGHT * (bench + 1), rtol=0.0, atol=1e-9)
        by_hand = LIMIT_Z - 5 * HEIGHT
        self.assertAlmostEqual(float(found.surface.min()), by_hand, delta=1e-9)
        shallow = self.calculate(self.request("Corta del límite hasta 70", mode="down", source=LIMITS, start="limite_b", profile=DESD.lower(),
                                              min_floor_width_m=30.0, bottom_level_m=BOTTOM_Z)).outcome
        self.assertEqual((str(shallow.stop), len(shallow.benches)), ("bottom_level", 3))
        before = self.counts()
        with self.assertRaises(self.messages.DesignError) as caught:
            self.calculate(self.request("Corta vacía", mode="down", source=LIMITS_SMALL, start="limite_c", profile=DESD.lower(), min_floor_width_m=30.0))
        self.assertEqual(caught.exception.code, "des.pit_empty")
        self.assertEqual(self.counts(), before, "el rechazo no deja nada")
        type(self).made["limit"] = SimpleNamespace(found=found)

    # --- f: el zig-zag -------------------------------------------------------------------------------------------------

    def test_f_the_descending_pit_with_a_zigzag_and_a_no_ramp_zone(self) -> None:
        """E2, CE-018-05, CE-018-06, RF-018-19, RF-018-21: la corta descendente desde el límite rectangular de 300 × 200 m con ``DESD_10_60_6`` y el zig-zag de
        ``PISTA_OCHO`` baja con la rampa pegada a su ancla; una zona sin rampa **fuera** del eje se respeta (ningún punto del eje cae dentro) y la que lo
        **cruza** se rechaza con el banco, lo que falta y el lugar (``des.pit_no_ramp_fit``), sin escribir nada."""
        common = {"mode": "down", "source": LIMITS_RECT, "profile": DESD60.lower(), "max_benches": 4, "simplify_m": 1e-6}
        free = self.calculate(self.request("Corta con zig-zag", start="zigzag", ramps=(self.ramps["Zig-zag"],), **common))
        found = free.outcome
        (ramp,) = found.ramps
        self.assertGreater(len(found.benches), 1)
        self.assertEqual(float(ramp.axis[0, 2]), LIMIT_Z)
        self.assertLessEqual(free.outcome.extra["checked_ramps"][0].max_gradient_pct, 10.0 + 1e-9)
        axis = local(ramp.axis)
        zone = np.array([[85.0, 105.0], [115.0, 135.0]])
        centre = axis[len(axis) // 2]
        crossing = rectangle(30.0, 30.0, (float(centre[0]), float(centre[1])))
        self.write_polygons("gis_fea_h2_cruza", [crossing], ["Cruza el eje"])
        before = self.counts()
        with self.assertRaises(self.messages.DesignError) as caught:
            self.calculate(self.request("Corta con zig-zag y zona", start="zigzag_b", ramps=(self.ramps["Zig-zag"],),
                                        noramp=self.road_model.LayerFields("gis_fea_h2_cruza", "nombre"), **common))
        error = caught.exception
        self.assertEqual(error.code, "des.pit_no_ramp_fit")
        self.assertEqual(error.values["reason"], "zona sin rampa")
        self.assertGreater(error.values["needed"], error.values["available"])
        self.assertIn("banco", str(error))
        self.assertEqual(self.counts()[0:1], before[0:1], "el rechazo no deja ninguna operación")
        # la zona que no cruza el eje se respeta
        far = rectangle(10.0, 10.0, (float(zone[0, 0]) - 60.0, float(zone[0, 1]) - 60.0))
        self.write_polygons("gis_fea_h2_lejos", [far], ["Lejos del eje"])
        kept = self.calculate(self.request("Corta con zig-zag y zona lejana", start="zigzag_b", ramps=(self.ramps["Zig-zag"],),
                                           noramp=self.road_model.LayerFields("gis_fea_h2_lejos", "nombre"), **common)).outcome
        inside_zone = [(x, y) for x, y in local(kept.ramps[0].axis) if abs(x - (zone[0, 0] - 60.0)) < 5.0 and abs(y - (zone[0, 1] - 60.0)) < 5.0]
        self.assertEqual(inside_zone, [])
        free.discard()

    # --- g: la roseta y los sectores ------------------------------------------------------------------------------------

    def test_g_the_rose_with_double_benches_and_two_sectors_without_gaps(self) -> None:
        """E3, CE-018-02, RF-018-06 a 09: con la roseta de dos rangos y n = 2, la berma aparece cada dos bancos y el avance es 2·h/tan α + B por azimut (la cara
        que baja a 90°, en el oeste: 11,547 + 6 m; a 270°, en el este: 20 + 6 m); con un sector de 45° y otro de 60° y n = 2, el resultado no
        tiene huecos en su borde: una polilínea por banco, cerrada, con los dos avances."""
        calculation, uid = self.create(self.request("Corta con roseta", start="roseta", rose=self.rose, n_berm=2))
        found = calculation.outcome
        self.assertEqual(str(found.stop), "surface")
        run_west, run_east = 2.0 * HEIGHT / math.tan(math.radians(60.0)), 2.0 * HEIGHT / math.tan(math.radians(45.0))
        west, east = 50.0, 50.0
        sagitta = 50.0 * (1.0 - math.cos(math.pi / 720))
        benches = len({poly.bench for poly in found.polylines})
        self.assertEqual(benches, 3)
        for bench in range(benches):
            for kind in ("foot", "crest"):
                xy = self.line(found, kind, bench)
                level = FLOOR_Z + 2.0 * HEIGHT * (bench + (1 if kind == "crest" else 0))
                np.testing.assert_allclose(self.levels(found, kind, bench), level, rtol=0.0, atol=1e-9)
                if kind == "crest":
                    west, east = west + run_west, east + run_east
                at_west = xy[np.argmin(np.abs(xy[:, 1] - CENTER[1]) + (xy[:, 0] > CENTER[0]) * 1e6)]
                at_east = xy[np.argmin(np.abs(xy[:, 1] - CENTER[1]) + (xy[:, 0] < CENTER[0]) * 1e6)]
                tolerance = (2 * bench + 3) * ARC_M + sagitta + 1e-3
                self.assertAlmostEqual(CENTER[0] - at_west[0], west, delta=tolerance, msg=f"{kind} {bench} oeste")
                self.assertAlmostEqual(at_east[0] - CENTER[0], east, delta=tolerance, msg=f"{kind} {bench} este")
                if kind == "crest":
                    west, east = west + BERM, east + BERM
        # dos sectores de perfil distinto y n = 2 en el oeste: sin huecos en su borde
        asked = self.request("Corta con sectores", start="fijado", sector_profiles={"sector_1": EXPL.lower(), "sector_2": EXPL45.lower()}, n_berm=2)
        sectors = self.calculate(asked).outcome
        for bench in {poly.bench for poly in sectors.polylines}:
            parts = [poly for poly in sectors.polylines if poly.bench == bench and poly.kind == "crest"]
            self.assertEqual(len(parts), 1, f"una sola polilínea de cresta en el banco {bench}")
            xy = local(parts[0].vertices)
            gaps = np.hypot(*np.diff(np.vstack([xy, xy[:1]]), axis=0).T)
            self.assertLess(float(gaps.max()), 25.0, f"sin huecos en la cresta del banco {bench}")
        crest_west = self.line(sectors, "crest", 0)
        self.assertGreater(len({round(float(item), 1) for item in np.hypot(*(crest_west - np.array(CENTER)).T)}), 2)
        REPORT.append("E3 roseta + sectores: " + f"avance {run_west:.3f} + 6 m (60°) y {run_east:.3f} + 6 m (45°) por banco doble; los sectores sin huecos")
        type(self).made["rose"] = SimpleNamespace(uid=uid)

    # --- h: la línea de cielo -------------------------------------------------------------------------------------------

    def test_h_the_skyline_on_the_inclined_terrain(self) -> None:
        """CE-018-07, RF-018-28, RF-018-29: sobre el terreno que sube un 10 % hacia el este, la línea de cielo tiene en cada punto la cota del terreno (≤ 10⁻⁶ m),
        la corta sale a superficie en bancos distintos por lado y la distancia mínima de la línea de cielo al límite legal (con su 2 m hacia dentro) es la de la
        cuenta a mano."""
        calculation, uid = self.create(self.request("Corta en ladera", start="inclinado"))
        self.made["slope_uid"] = uid
        found = calculation.outcome
        self.assertTrue(found.skyline)
        for line in found.skyline:
            xy = local(line)
            np.testing.assert_allclose(line[:, 2], 130.0 + 0.10 * xy[:, 0], rtol=0.0, atol=1e-6)
        points = np.vstack([local(line) for line in found.skyline])
        legal = float(np.minimum.reduce([points[:, 0] - 10.0, 390.0 - points[:, 0], points[:, 1] - 10.0, 390.0 - points[:, 1]]).min())
        self.assertAlmostEqual(self.figures_of(uid)["des.pit_sky_dist_legal_m"], legal, delta=2.0)
        top = max(poly.bench for poly in found.polylines)
        self.assertGreaterEqual(top, 3, "sale a superficie en el este, más arriba que en el oeste")
        west, east = float(points[:, 0].min()), float(points[:, 0].max())
        self.assertLess(west, 150.0)
        self.assertGreater(east, 250.0)
        REPORT.append(f"CE-018-07: línea de cielo de x = {west:.1f} a {east:.1f} m con la cota del terreno a ≤ 10⁻⁶ m; distancia al límite legal {legal:.2f} m")

    def test_ha_the_tin_and_the_solid_of_the_pit_in_the_view_with_the_project(self) -> None:
        """T30, RF-018-30, RNF-018-09, ADR-0005: con la corta en ladera ya creada, el TIN (``des_pbl_`` con su línea de cielo ``des_psk_``) y el sólido de excavación
        (``des_pbk_``: entre la partida y la superficie de la corta) se cargan como vistas regenerables **sin escribir nada** en el proyecto: el TIN tiene cada banco a su cota
        y coordenadas locales; el sólido es una malla de volumen positivo que ronda el de corte de la rejilla (la malla va por centros de celda); con un límite de triángulos
        pequeño salen ``des.pit_view_large`` y ninguna malla."""
        import bpy

        pit_views = _module("bl.scene.pit_views")
        views = _module("bl.scene.views")
        registry = _module("core.datasets.registry")
        mesh_module = _module("bl.scene.mesh")
        name = "Corta en ladera"
        before = self.counts()

        def request(family: str) -> Any:
            dataset = self.dprov.dataset_name(family, name)
            with self.project.read() as conn:
                record = registry.get(conn, dataset, version_uid=self.v01.uid)
            self.assertIsNotNone(record, dataset)
            return views.ViewRequest(self.project, record, f"Vista {dataset}", 0)

        def load(loader: Any, asked: Any) -> Any:
            steps = loader(asked)
            while True:
                try:
                    next(steps)
                except StopIteration as done:
                    return done.value

        meshes = len(bpy.data.meshes)
        tin = load(pit_views.load_pit_tin, request(self.dprov.PIT_POLYLINES_TABLE))
        (tin_obj,) = tin.objects
        triangles = len(tin_obj.data.polygons)
        local = mesh_module.mesh_vertices_local(tin_obj.data).astype(np.float64)
        self.assertGreater(triangles, 100)
        self.assertLess(float(np.abs(local[:, :2]).max()), 1000.0, "locales, no absolutas")
        table = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(self.dprov.PIT_POLYLINES_TABLE, name))[0][0]
        levels = {round(float(row[0]), 3) for row in self.rows(f'SELECT z_m FROM "{table}"')}
        self.assertTrue(levels, "la corta tiene polilíneas")
        found = {round(float(value) + float(self.project.origin.z0), 3) for value in local[:, 2]}
        for level in levels:
            self.assertIn(level, found, "cada banco tiene vértices a su cota")
        solid = load(pit_views.load_pit_solid, request(self.dprov.PIT_BENCHES_TABLE))
        (solid_obj,) = solid.objects
        faces = mesh_module.mesh_triangles(solid_obj.data)
        points = mesh_module.mesh_vertices_local(solid_obj.data).astype(np.float64)
        a, b, c = (points[faces[:, index]] for index in range(3))
        volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        cut = self.figures_of(self.made["slope_uid"])["des.pit_cut_m3"]
        self.assertGreater(volume, 0.0)
        self.assertLess(abs(volume / cut - 1.0), 0.1, "el volumen de la malla (centros de celda) ronda el de corte")
        self.assertEqual(self.counts(), before, "las vistas no escriben nada")
        for loader, family in ((pit_views.tin_loader(10), self.dprov.PIT_POLYLINES_TABLE), (pit_views.solid_loader(10), self.dprov.PIT_BENCHES_TABLE)):
            with self.assertRaises(self.messages.DesignError) as caught:
                load(loader, request(family))
            self.assertEqual(caught.exception.code, "des.pit_view_large")
        for obj in (tin_obj, solid_obj):
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        self.assertEqual(len(bpy.data.meshes), meshes)
        REPORT.append(f"T30: TIN de {triangles:,} triángulos y sólido de {volume:,.0f} m³ (malla) frente a {cut:,.0f} m³ de corte (rejilla)")

    # --- i: restricciones, banco fijado y hallazgos -------------------------------------------------------------------------

    def test_i_the_perimeter_the_untouchable_and_the_fixed_bench(self) -> None:
        """E4 (parte), CE-018-08, CE-018-09, RF-018-05, 23, 26: con un perímetro de actuación que corta la corta, la superficie no se mueve fuera de él y el
        hallazgo da la longitud de cresta fuera y su lugar; con un intocable dentro del hueco, la superficie no lo toca y el hallazgo da el área sin excavar. Con
        el banco 2 fijado como una polilínea de una capa del proyecto, el programa la usa tal cual (cota a ≤ 10⁻⁹ m, hash de la capa igual antes y después) y la
        capa **editada** deja la corta obsoleta con su causa."""
        calculation, uid = self.create(self.request("Corta de la esquina", source=FLOORS_CORNER, start="esquina"))
        found = calculation.outcome
        flat_terrain = flat(TOP_Z)
        final = found.compose(self.surface_start("esquina", flat_terrain))
        outside = ~inside((20.0, 20.0, 380.0, 340.0))
        touchable = inside((318.0, 318.0, 326.0, 326.0))
        self.assertTrue(outside.any() and touchable.any())
        self.assertEqual(float(np.abs(final - flat_terrain)[outside].sum()), 0.0, "0 m³ fuera del perímetro")
        self.assertEqual(float(np.abs(final - flat_terrain)[touchable].sum()), 0.0, "0 m³ en el intocable")
        kinds = {str(item.kind): item for item in found.findings}
        self.assertIn("outside_perimeter", kinds)
        self.assertGreater(kinds["outside_perimeter"].value, 0.0)
        self.assertTrue(math.isfinite(kinds["outside_perimeter"].place[0]))
        self.assertIn("unexcavated", kinds)
        self.assertGreater(kinds["unexcavated"].value, 0.0)
        type(self).made["corner"] = SimpleNamespace(uid=uid, found=found)
        # el banco 2 fijado con una capa del proyecto (la del pie del banco 2 de la corta circular)
        circle_found = self.made["circle"].found
        foot = next(poly for poly in circle_found.polylines if (poly.bench, str(poly.kind)) == (2, "foot")).vertices
        self.write_breaklines(FIXED_LAYER, [np.vstack([foot, foot[:1]])])
        layer_hash = self.hashes(FIXED_LAYER)
        fixed = self.request("Corta con banco fijado", start="fijado", fixed=self.road_model.LayerFields(FIXED_LAYER, "line_id"))
        fixed_calculation, fixed_uid = self.create(fixed)
        self.assertEqual(self.hashes(FIXED_LAYER), layer_hash, "el hash de la capa es el mismo antes y después")
        used = next(poly for poly in fixed_calculation.outcome.polylines if (poly.bench, str(poly.kind)) == (2, "foot")).vertices
        np.testing.assert_allclose(np.array(sorted(map(tuple, np.unique(used, axis=0)))), np.array(sorted(map(tuple, np.unique(foot, axis=0)))), rtol=0.0, atol=1e-9)
        inputs = self.rows("SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND "
                           "io.direction = 'in'", fixed_uid)
        self.assertIn((FIXED_LAYER, self.dprov.ENTITY_LAYER_ROLE), inputs)
        self.assertEqual(self.stale_causes(fixed_uid), set())
        REPORT.append(f"CE-018-08: la esquina, 0 m³ fuera del perímetro y en el intocable; hallazgos {sorted(set(kinds))}; CE-018-09: banco fijado con hash igual")
        type(self).made["fixed"] = SimpleNamespace(uid=uid)

    def surface_start(self, label: str, values: np.ndarray) -> np.ndarray:
        return values

    def test_ia_expanding_a_bench_from_the_calculated_pit_leaves_the_editable_layer(self) -> None:
        """E4 (parte), RF-018-22, P-12: «Expandir banco…» sobre el pie del banco 1 de la corta circular (sus polilíneas, ``des_pbl_``) da la **cresta del banco 1** de la
        corta, a la misma cota; crearlo deja **una** operación ``des.pit_expand`` con la capa ``des_pxb_`` **editable en QGIS** y su cifra (la longitud de la cresta), y no
        crea ninguna entidad ni superficie."""
        source = self.dprov.dataset_name(self.dprov.PIT_POLYLINES_TABLE, "Corta circular")
        asked = self.pit_expand.ExpandRequest("Cresta 1 expandida", self.road_model.LayerFields(source, None), "up", self.terrain["llano"], bench=1, kind="foot",
                                              profile=EXPL.lower(), arc_tol_m=ARC_M, simplify_m=SIMPLIFY_M)
        before = (self.counts(), [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid)])
        calculation = None
        for step in self.steps.pit_expand_run(self.project, asked, version=self.v01.uid, masks=self.masks[self.v01.uid]):
            calculation = step.result
        assert calculation is not None
        self.assertEqual((self.counts(), [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid)]), before, "«Calcular» no escribe")
        crest = next(poly for poly in self.made["circle"].found.polylines if (poly.bench, str(poly.kind)) == (1, "crest")).vertices
        (found,) = calculation.outcome.polylines
        self.assertAlmostEqual(found.z_m, float(crest[0, 2]), delta=1e-9)
        self.assertEqual(len(found.vertices), len(crest))
        self.assertTrue(calculation.summary.slope_ok)
        stored = calculation.create()
        uid = str(stored.handle.uid)
        self.assertEqual(self.rows("SELECT op_type, status FROM gb_operation WHERE uid = ?", uid), [(self.dprov.PIT_EXPAND, "done")])
        table = self.dprov.dataset_locator(self.dprov.PIT_EXPANDED_TABLE, "Cresta 1 expandida", "V01")
        dataset = self.dprov.dataset_name(self.dprov.PIT_EXPANDED_TABLE, "Cresta 1 expandida")
        self.assertEqual(self.rows("SELECT qgis_editable, status FROM gb_dataset WHERE name = ?", dataset), [(1, "current")])
        self.assertEqual(len(self.rows(f'SELECT fid FROM "{table}"')), 1)
        self.assertEqual([key for (key,) in self.rows("SELECT key FROM gb_figure WHERE operation_uid = ?", uid)], ["des.pit_len_crest_m"])
        self.assertEqual([entry.record.code for entry in self.entities.registry(self.project, self.v01.uid)], before[1])
        type(self).made["expand"] = SimpleNamespace(uid=uid, table=table, dataset=dataset)
        REPORT.append("RF-018-22: «Expandir banco…» da la cresta del banco 1 de la corta y deja la capa des_pxb_ editable")

    # --- j: la verificación por recinto -------------------------------------------------------------------------------------

    def test_j_the_verification_by_enclosure_complies(self) -> None:
        """E5, CE-018-11, RF-018-28: la verificación de la 012 de la superficie de la corta de la esquina (con el perímetro y el intocable) frente a su partida
        da «cumple», con 0 m³ en los intocables y fuera del perímetro."""
        name = self.surface_of("Corta de la esquina")
        store = _module("reserves.compliance_store")
        with mock.patch.object(_module("bl.ops.res"), "_call_panel", return_value={"FINISHED"}):
            self.assertEqual(bpy.ops.geoblender.res_verify_constraints("EXEC_DEFAULT", name="Revisión de la corta", start=self.terrain["esquina"], finals=name,
                                                                       in_steps=True), {"RUNNING_MODAL"})
            cls = _module("bl.ui.commands").registered_class("geoblender.res_verify_constraints")
            operator = [op for op in bpy.context.window.modal_operators if isinstance(op, cls) and getattr(op, "_steps", None) is not None][0]
            for _ in range(20_000):
                state = operator.modal(bpy.context, TIMER)
                if state != {"RUNNING_MODAL"}:
                    break
            else:
                self.fail("la verificación no acaba")
        self.assertEqual(state, {"FINISHED"})
        locator = store.dataset_locator(store.TABLE, "Revisión de la corta", self.v01.code)
        table = {(zone, final, quantity): (value, note) for zone, final, quantity, value, note in
                 self.rows(f'SELECT zone, "final", quantity, value, note FROM "{locator}"')}
        judged = sorted(zone for (zone, found, quantity), (_value, note) in table.items() if found == 1 and quantity == "counted_m3" and note in ("cut", "fill", "any"))
        self.assertTrue(judged)
        for zone in judged:
            self.assertEqual(table[(zone, 1, "counted_m3")][0], 0.0, zone)
            self.assertEqual(table[(zone, 1, "verdict")][1], "complies", zone)

    # --- k: congelar, reproducir y traer --------------------------------------------------------------------------------------

    def test_k_freezing_reproducing_and_bringing_the_pits(self) -> None:
        """E5, CE-018-10, RF-018-25, RF-009-11, RF-015-18: congelar V01 deja ``V01.r1``; reproducirla, **sin proyecto y sin escribir nada**, da de cada corta el
        mismo hash de sus ocho datos y las mismas cifras; traer una corta a otra versión la deja **sin calcular**, con sus valores, y se calcula con su código."""
        versions_ops = _module("bl.ops.versions")
        dialog = versions_ops.revision_dialog(self.project, self.v01.uid)
        work = self.freeze.freeze_steps(self.project, self.v01.uid, reason="Entrega de la prueba", accepted=versions_ops._acceptance(dialog.accepted))
        outcome = None
        for step in work:
            outcome = step.result if step.result is not None else outcome
        revision = str(outcome.frozen.uid)
        pits = {str(uid): name for uid, name in self.rows("SELECT uid, json_extract(settings, '$.name') FROM gb_operation WHERE op_type = ? AND status = 'done'",
                                                          self.dprov.PIT)}
        self.assertEqual(sorted(pits.values()), sorted(["Corta circular", "Corta con espiral", "Corta del límite", "Corta con roseta", "Corta en ladera", "Corta de la esquina", "Corta con banco fijado"]))
        before = self.counts()
        files_before = sorted(str(item.relative_to(self.project.root)) for item in Path(self.project.root).rglob("*") if item.is_file() and "cache" not in item.parts
                              and not item.name.endswith(("-journal", "-wal", "-shm")))
        report = None
        for step in self.reproduce.reproduce_steps(self.project, revision):
            report = step.result if step.result is not None else report
        self.assertEqual(self.counts(), before, "reproducir no escribe en el proyecto")
        files_after = sorted(str(item.relative_to(self.project.root)) for item in Path(self.project.root).rglob("*") if item.is_file() and "cache" not in item.parts
                             and not item.name.endswith(("-journal", "-wal", "-shm")))
        self.assertEqual(files_after, files_before)
        type(self).made["report"], type(self).made["pits"] = report, pits
        for uid in pits:
            if pits[uid] == "Corta con espiral":
                continue  # su prueba es la ka
            self.same_as_frozen(report, uid, pits[uid])
        # traer una corta a otra versión: queda sin calcular y se calcula con su código
        brought = self.entity_store.bring_entities(self.project, self.v01, self.v03, codes=["PIT-001"])
        (item,) = brought.entities
        self.assertEqual(item.code, "PIT-001")
        self.assertEqual(self.entities.registry(self.project, self.v03.uid).get("PIT-001").record.state, self.entities.EntityState.UNCALCULATED)
        asked = self.pit_store.entity_pit_request(self.project, self.v03, "PIT-001")
        self.assertEqual(asked.name, "Corta circular")
        calculation = self.calculate(asked, self.v03, code="PIT-001")
        stored = calculation.create(decided_by=PERSON)
        self.assertEqual(self.entities.registry(self.project, self.v03.uid).get("PIT-001").record.state, self.entities.EntityState.CURRENT)
        self.assertEqual(str(self.entities.registry(self.project, self.v03.uid).get("PIT-001").operation_uid), str(stored.handle.uid))

    def same_as_frozen(self, report: Any, uid: str, name: str) -> None:
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual(len(mine), 8, name)
        self.assertTrue(all(check.same for check in mine), [(check.name, check.role) for check in mine if not check.same])
        found = [check for check in report.figures if check.operation_uid == uid]
        self.assertTrue(found and all(check.same for check in found), [check for check in found if not check.same])
        self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])

    def test_ka_the_pit_with_a_ramp_reproduces_the_same(self) -> None:
        """RF-018-25, RF-009-11, CE-018-05: la corta con la espiral, reproducida desde lo congelado, da de sus ocho datos el mismo hash. **Hoy no lo cumple**: el
        nombre libre de la rampa (``Espiral``) sale en el detalle de los hallazgos y en el informe, y lo congelado solo tiene su código (``espiral``)."""
        uid = next(key for key, name in self.made["pits"].items() if name == "Corta con espiral")
        self.same_as_frozen(self.made["report"], uid, "Corta con espiral")

    def test_kb_the_expansion_reproduces_the_same_layer(self) -> None:
        """RF-018-22, RF-009-11: la expansión de ``ia``, reproducida de lo congelado en ``V01.r1`` (sin proyecto), da el mismo hash de su capa ``des_pxb_`` y la misma cifra."""
        uid = self.made["expand"].uid
        mine = [check for check in self.made["report"].outputs if check.operation_uid == uid]
        self.assertEqual([check.role for check in mine], ["pit_expanded"])
        self.assertTrue(all(check.same for check in mine), mine)
        found = [check for check in self.made["report"].figures if check.operation_uid == uid]
        self.assertTrue(found and all(check.same for check in found), found)

    # --- l y m: la cadena y la cascada (V02) -------------------------------------------------------------------------------------

    def test_l_the_chain_in_v02_and_the_cascade_in_recompute_what_is_stale(self) -> None:
        """E5, CE-018-10, RF-015-15, RF-015-16, RF-018-03: la corta, una plataforma que parte de su superficie, una pista que parte de la de la plataforma y
        otra corta que **declara** que se apoya en la primera; cambiar el ángulo de cara del perfil de la corta (solo en V02) las deja obsoletas en cascada
        **con su causa** y «Recalcular lo obsoleto» —con la cola real de la extensión— las repite en orden y todas quedan al día."""
        first, _uid = self.create(self.request("Corta madre", start="cadena"), self.v02)
        code = first.outcome.code
        asked = self.dmodel.PlatformRequest("Plataforma", self.dmodel.PlatformFields(layer=PLATFORM_LAYER, start_level_field="cota_inicial", gradient_field="pendiente",
                                                                                      width_field="ancho"), "Plataforma sobre la corta", f"entity:{code}",
                                            mode="cut_fill", edge_angle_deg=35.0, reach_m=10.0)
        work = self.steps.platform_run(self.project, asked, masks=self.masks[self.v02.uid], version=self.v02.uid)
        platform = None
        for step in work:
            platform = step.result
        platform.create(decided_by=PERSON)
        road = self.road_model.RoadRequest("Pista", self.road_model.LayerFields(AXIS_LAYER, "nombre"), "on_axis", "pista_principal", "entity:PLT-001",
                                           feature="Pista sobre la plataforma")
        found = None
        for step in self.steps.road_run(self.project, road, version=self.v02.uid, masks=self.masks[self.v02.uid]):
            found = step.result
        found.create(decided_by=PERSON)
        self.write_polygons("gis_fea_h2_fondos_2", [circle(30.0, (330.0, 330.0))], ["Fondo 2"], cota_m=[FLOOR_Z + 40.0])
        second, _uid2 = self.create(self.request("Corta que se apoya", source="gis_fea_h2_fondos_2", start="cadena_b"), self.v02)
        code2 = second.outcome.code
        key = f"des.pit.{code2.lower().replace('-', '_')}.supports"
        with self.project.write_transaction() as conn:
            self.entity_store.set_entity_params(self.project, (self.entity_store.EntityParamRow(key, "supports", code, "Declarado por la persona",
                                                                                                "person", "Se apoya en la primera"),),
                                                version=self.v02.uid, decided_by=PERSON, conn=conn)
        old2 = self.current(self.v02, code2)  # al recalcularla lee lo que declaró y anota la superficie de la primera
        ((op_type, settings),) = self.rows("SELECT op_type, settings FROM gb_operation WHERE uid = ?", old2)
        handle, work = self.dstore.recompute_run(self.recompute.RecomputeRequest(self.project, old2, op_type, json.loads(settings), (), (), version=self.v02.uid))
        for _step in work:
            pass
        self.assertEqual(set(self.states(self.v02)), {code, "PLT-001", "RDW-001", code2})
        self.assertTrue(all(state is self.entities.EntityState.CURRENT for state in self.states(self.v02).values()), self.states(self.v02))
        dependents = self.entities.dependents(self.project, self.v02.uid, code)
        self.assertEqual({row.entity for row in dependents}, {"PLT-001", code2})
        face = "des.bench.expl_10_60_6.face_deg"
        old = self.current(self.v02, code)
        self.change(face, 50.0, self.v02)
        self.assertIn(("parameter_changed", face), self.stale_causes(old))
        for entity in ("PLT-001", "RDW-001", code2):
            self.assertTrue(self.stale_causes(self.current(self.v02, entity)), f"{entity} queda obsoleta en cascada")
        self.assertEqual([self.stale_causes(self.current(self.v01, "PIT-001"))][0], set(), "lo de V01 no cambia: el valor es de V02")
        outcome = self.run_recompute()
        made = [str(uid) for result in outcome.results for uid in result.operations]
        types = [self.rows("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0] for uid in made[:3]]
        self.assertEqual(types, [self.dprov.PIT, self.dprov.PLATFORM, self.dprov.ROAD], "en el orden de la cadena")
        for _ in range(3):  # la pista cuenta la superficie de la segunda corta como otro diseño y se asienta en otra pasada
            if not self.stale_entities():
                break
            self.run_recompute()
        for entity in (code, "PLT-001", "RDW-001", code2):
            self.assertEqual(self.stale_causes(self.current(self.v02, entity)), set(), entity)
        self.assertTrue(all(state is self.entities.EntityState.CURRENT for state in self.states(self.v02).values()))
        type(self).made["chain"] = SimpleNamespace(code=code, code2=code2)
        REPORT.append("CE-018-10: la cascada (corta, plataforma, pista y corta que declara su apoyo) se rehace en orden con la cola real")

    def stale_entities(self) -> list[str]:
        return [code for code in self.states(self.v02) if self.stale_causes(self.current(self.v02, code))]

    def test_m_discarding_the_pit_leaves_the_support_removed(self) -> None:
        """E5, CE-018-10, RF-015-17: descartar la corta da **una sola lista** de lo que se apoyaba en ella, deja la plataforma y la segunda corta en «apoyo
        retirado» y fuera de «Recalcular lo obsoleto», que no las rehace; la segunda, que solo **declara** el apoyo, se puede dar por buena y la plataforma,
        que parte de su superficie, no."""
        code, code2 = self.made["chain"].code, self.made["chain"].code2
        plan = self.entity_store.discard_plan(self.project, self.v02.uid, code)
        self.assertEqual({row.entity for row in plan.dependents}, {"PLT-001", code2})
        self.assertEqual(plan.dependents, self.entities.dependents(self.project, self.v02.uid, code))
        found = self.entity_store.discard_entity(self.project, self.v02.uid, code, reason="La corta se descarta", decided_by=PERSON)
        self.assertEqual({row.entity for row in found.dependents}, {"PLT-001", code2})
        states = self.states(self.v02)
        removed = self.entities.EntityState.SUPPORT_REMOVED
        self.assertEqual((states[code], states["PLT-001"], states[code2]), (self.entities.EntityState.DISCARDED, removed, removed))
        before = self.rows("SELECT uid FROM gb_operation ORDER BY fid")
        outcome = self.run_recompute()
        self.assertEqual(sum(len(result.operations) for result in outcome.results if str(result.status) == "done"), 0, "no rehace lo que perdió su apoyo")
        self.assertEqual(self.rows("SELECT uid FROM gb_operation ORDER BY fid"), before)
        retired = {row.entity: row for row in self.entities.retired_supports(self.project, self.v02.uid)}
        self.assertEqual((retired["PLT-001"].releasable, retired[code2].releasable), (False, True))
        with self.assertRaises(self.messages.DesignError) as caught:
            self.entity_store.release_support(self.project, self.v02.uid, "PLT-001", code, reason="No debe poder", decided_by=PERSON)
        self.assertEqual(caught.exception.code, "des.entity_release_start")
        handle, work = self.entity_store.release_support(self.project, self.v02.uid, code2, code, reason="La segunda corta ya está hecha", decided_by=PERSON)
        for step in work:
            self.des_ops.des_tick()
        self.assertEqual(self.states(self.v02)[code2], self.entities.EntityState.CURRENT)
        REPORT.append("CE-018-10: descartar la corta deja «apoyo retirado» en la plataforma y en la corta declarada; la segunda se da por buena")

    def test_n_the_layer_edited_in_qgis_is_not_blocked_and_is_not_overwritten(self) -> None:
        """E4 (la capa editada en QGIS), RF-018-22, P-12, RF-008-21: una segunda expansión parte de la capa de ``ia``; **editar la capa fuera de Geoblender** no la bloquea
        (vigente, con el contenido nuevo, editable), **deja obsoleta** la segunda expansión con su causa y **repetir la primera no la sobrescribe**
        (``des.pit_expand_layer_edited``)."""
        import sqlite3

        first = self.made["expand"]
        asked = self.pit_expand.ExpandRequest("Pie 2 expandido", self.road_model.LayerFields(first.dataset, "name"), "up", self.terrain["llano"], bench=1, kind="crest",
                                              profile=EXPL.lower(), arc_tol_m=ARC_M, simplify_m=SIMPLIFY_M)
        calculation = None
        for step in self.steps.pit_expand_run(self.project, asked, version=self.v01.uid, masks=self.masks[self.v01.uid]):
            calculation = step.result
        assert calculation is not None
        second = str(calculation.create().handle.uid)
        self.assertEqual(self.stale_causes(second), set())
        before = self.hashes(first.dataset)
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(f'UPDATE "{first.table}" SET name = ? WHERE fid = 1', ("Cresta 1 (editada en QGIS)",))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", ("2031-01-01T00:00:01.000Z", first.table))
        finally:
            conn.close()
        for _step in self.external.external_check_steps(self.project):
            pass
        after = self.hashes(first.dataset)
        self.assertEqual(after[first.dataset][1], "current")
        self.assertNotEqual(after[first.dataset][0], before[first.dataset][0])
        self.assertTrue(self.stale_causes(second), "la expansión que parte de la capa queda obsoleta")
        settings = json.loads(self.rows("SELECT settings FROM gb_operation WHERE uid = ?", first.uid)[0][0])
        request_ = self.recompute.RecomputeRequest(self.project, first.uid, self.dprov.PIT_EXPAND, settings, (), (), version=self.v01.uid)
        with self.assertRaises(self.messages.DesignError) as caught:
            handle, work = self.dstore.recompute_run(request_)
            for _step in work:
                pass
        self.assertEqual(caught.exception.code, "des.pit_expand_layer_edited")
        REPORT.append("P-12: la capa des_pxb_ editada en QGIS no se bloquea, deja obsoleta la expansión que parte de ella y no se sobrescribe")


def tearDownModule() -> None:
    """El informe del H2 (a la salida de errores)."""
    import sys

    print("\nINFORME H2 (T26):\n  " + "\n  ".join(REPORT), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
