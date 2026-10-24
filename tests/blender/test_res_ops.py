# SPDX-License-Identifier: GPL-3.0-or-later
"""Las órdenes de la cubicación (spec 011; plan 011 §5.3.4, §5.5, A10, A11, D-19, D-25, D-30,
D-31, D-36).

**Entre dos superficies… (Mayús+Alt+M)** (T21; HU-011-1; RF-011-01, RF-011-02, RF-011-03,
RF-011-04, RF-011-06, RF-011-20, RF-011-25, RF-011-26):

- RF-011-06 (D-31): con dos superficies seleccionadas en la vista, el diálogo las propone (de
  partida, la de mayor cota media en sus celdas comunes, sea cual sea el orden de la selección)
  con el nombre «<final> − <partida>»; «Invertir» las cambia; Intro cubica. La orden es la real
  de la entrada «011» (no la provisional de R-38) con su atajo de la Vista 3D.
- RF-011-01, RF-011-04, RF-011-20, RF-011-25: desde la interfaz, ``res.volume`` por pasos en el
  modal de la orden (un evento cada vez, ninguna llamada de más de 0,2 s) con su avance en la
  barra de estado; Esc a mitad no deja ni cifra, ni tabla, ni rejilla (la operación,
  cancelada); terminada, el desmonte, el terraplén, el neto y las áreas (con dato, sin dato y
  sin movimiento) celda a celda, de la revisión abierta de la versión activa, la rejilla de
  diferencias cargada en la vista y la ventana de la cubicación.
- RF-011-02, RF-011-03: una cota constante como final; dos superficies que no casan, el rechazo
  de A1 con las dos y la orden que lo resuelve, sin escribir nada.
- D-30: repetir el nombre de una cubicación de la versión pregunta si se sustituye; la nueva
  sustituye a la anterior.
- RF-011-20, RF-011-26: sin versión activa, la ventana de elegir o crear una; con la activa
  SUPERADO o el proyecto en solo lectura, desactivada con su motivo.

**Por unidad, fase y banco…** (T23; HU-011-2, HU-011-3; RF-011-07 a RF-011-10, RF-011-12 a
RF-011-18; plan §5.3.4, D-16, D-35, D-37):

- el diálogo ofrece las capas de dominios con sus campos, los bancos, «Por unidades» y la rejilla
  (no) y, sin columna de materiales, el aviso que lleva a definirla (desde un guion, el rechazo);
- con la capa «Fases», bancos anclados y la columna, ``res.volume`` y, encadenada, ``res.tonnage``:
  la tabla fase × banco × unidad (m³; m³ esponjados y t) y sus cifras; sin una densidad, su aviso
  y ningún total de toneladas;
- una capa con solapes o sin valor, el rechazo con la lista de sus polígonos (RF-011-08).

**Por momentos de extracción… y Ratios…** (T24; HU-011-4, HU-011-3; RF-011-19, RF-011-18; plan
A13, D-33, D-35):

- el diálogo ofrece las cubicaciones de la versión activa como momentos y como directa; dos
  momentos que parten la directa suman lo mismo (diferencia 0) y uno que deja un hueco da la
  diferencia en m³ y en % y el aviso de la tolerancia (``res.stages``, por pasos); los momentos
  mal elegidos, rechazados;
- «Ratios…» deja elegida la tabla de la cubicación con el filtro de relaciones y la abre; sin
  unidades, lo dice.

**Versión no editable, solo lectura y recalcular** (T26; HU-011-5; RF-011-20, RF-011-21,
RF-011-26; E5; plan A12, D-16, D-19):

- las seis órdenes de Cubicación, activas con el proyecto en escritura y la versión activa
  editable o sin ninguna; con la activa SUPERADO o en solo lectura, desactivadas con su motivo;
- E5: congelada V01.r1, un K cambiado solo en V01 deja obsoletas las toneladas de la cubicación de
  la revisión abierta (no sus m³ ni lo congelado en V01.r1); «Recalcular lo obsoleto» las rehace
  en V01.r2 por la cola de ``res``, con su avance, y las cifras de V01.r1 siguen iguales.

Un proyecto para toda la clase (V01 activa y V02), rejillas de 8 × 8 celdas de 1 m y la extensión
sin importar otra vez (``blender_ext.release``; RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import importlib
import json
import re
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.trees import remove_tree

ENTRY = "011"
BETWEEN = "geoblender.res_compute_volume_between_surfaces"
PANEL = "GEOBLENDER_PT_res_volumetrics"
CELLS = 8
OTHER_CELLS = 4
REASON = "Prueba de las órdenes de la cubicación"
START, FINAL, OTHER = "gis_dtm_septiembre", "gis_dtm_octubre", "gis_dtm_otra"
ELEVATION = "ELEVATION"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
MAX_EVENTS = 400
CALL_LIMIT_S = 0.2
"""Lo más que dura una llamada del modal (RNF-011-04)."""
CANCELLED = "Cubicación cancelada: no ha quedado nada a medias"
DIALOG = {"name": "", "start": START, "final": FINAL, "start_elevation": "",
          "final_elevation": "", "invert": False, "scope_layer": "NONE",
          "difference_grid": True, "replace": False, "confirm": False, "in_steps": False}
"""Los valores por defecto del diálogo abierto a mano."""
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo que cambia al registrar una operación sin resultados: la base, su diario y la cabecera."""
SCOPE_RING = np.array([(vf.WEST + 1.5, vf.SOUTH - 1.0), (vf.WEST + 6.0, vf.SOUTH - 1.0),
                       (vf.WEST + 6.0, vf.SOUTH + CELLS + 1.0),
                       (vf.WEST + 1.5, vf.SOUTH + CELLS + 1.0), (vf.WEST + 1.5, vf.SOUTH - 1.0)],
                      dtype=np.float64)
"""El ámbito de la prueba: de la mitad de la columna 1 al final de la 5, de norte a sur."""
SCOPE_WEIGHTS = np.array([0.0, 0.5, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0])
"""La fracción de cada columna dentro de :data:`SCOPE_RING`."""
BREAKDOWN = "geoblender.res_compute_volume_breakdown"
BREAKDOWN_DIALOG = {**DIALOG, "difference_grid": False, "domains_layer": "NONE",
                    "domains_field": "NONE", "bench_height": "", "bench_anchor": "",
                    "bench_levels": "", "by_units": False}
"""Los valores por defecto del diálogo de «Por unidad, fase y banco…» abierto a mano."""
PHASES = (("Fase 1", vf.WEST - 1.0, vf.WEST + 4.0), ("Fase 2", vf.WEST + 4.0, vf.WEST + 6.5))
"""La capa «Fases» (campo «Fase»): dos franjas de norte a sur; la segunda acaba a mitad de la
columna 6 (lo de su este, «Fuera de los dominios»)."""
OVERLAPS = ((1, "A", vf.WEST - 1.0, vf.WEST + 5.0), (2, "B", vf.WEST + 4.0, vf.WEST + 9.0),
            (3, "", vf.WEST + 10.0, vf.WEST + 12.0))
"""La capa «Solapes» (campo «zona»): A y B se solapan en una franja de 1 m × 10 m; la 3, sin
valor."""
BASE_M = 101.0
"""La base (cota constante) de la montera, sobre la capa útil."""
BENCH_M, ANCHOR_M = 1.0, 100.5
"""Los bancos: 1 m anclados a 100,5 m (la escala de las rejillas de la prueba)."""
DENSITY = {"montera": 1.8, "capa_util": 2.0}
SWELL = 1.5
"""La densidad (t/m³) y el K de la capa útil (valores sintéticos de prueba, HIPÓTESIS)."""
MISSING_DENSITY = "«Montera» tiene volumen y le falta el parámetro «res.unit.montera.density»"
STAGES = "geoblender.res_compute_extraction_stages"
RATIOS = "geoblender.res_compute_ratios"
STAGES_DIALOG = {"name": "", "direct": "", "replace": False, "confirm": False,
                 "in_steps": False}
"""Los valores por defecto del diálogo de «Por momentos de extracción…» abierto a mano."""
REST = ((vf.WEST - 1.0, vf.WEST + 1.5), (vf.WEST + 6.0, vf.WEST + 9.0))
"""La capa de contornos «Resto»: lo que queda fuera de :data:`SCOPE_RING`, en dos franjas."""
DIRECT = "Directa"
STAGE_CUBICATIONS = {DIRECT: None, "Explotación": "scope", "Resto": "rest"}
"""Las cubicaciones por unidades de los momentos (septiembre − octubre; su ámbito): la
directa, sin ámbito, y dos momentos que la parten (el ámbito y lo que queda fuera)."""
WITHOUT_UNITS = "Sin unidades"
"""Una cubicación sin unidades (el ámbito): un momento que deja un hueco."""
SHOW = "geoblender.res_show_volumetrics"
EXPORT_CSV = "geoblender.res_export_csv"
UNCONFIRMED = "depende de un valor sin confirmar"
HYPOTHESIS = "depende de una hipótesis"
BENCHES = "Fases y bancos"
"""Una cubicación sin unidades por la capa «Fases» y bancos de 1 m anclados a 100,5 m."""
DIFFERENCE = "geoblender.res_compute_surface_difference"
MATERIALS = "geoblender.res_edit_materials"
SIX = (BETWEEN, DIFFERENCE, BREAKDOWN, STAGES, MATERIALS, RATIOS)
"""Las seis órdenes de Cubicación (RF-011-26; BS §8.9)."""
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
RECOMPUTE = "geoblender.core_recompute_stale"
SWELL_KEY = "res.unit.capa_util.swell"
SWELL_V01 = 1.6
"""El K de la capa útil solo en V01 (el del proyecto, :data:`SWELL`)."""


class _Collection(list):
    """Una ``CollectionProperty`` simulada para el ``self`` de un diálogo abierto a mano."""

    def add(self) -> SimpleNamespace:
        item = SimpleNamespace(name="", chosen=False)
        self.append(item)
        return item


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _start_values() -> np.ndarray:
    """Septiembre: 100 m en el oeste y 0,25 m más por columna."""
    return 100.0 + 0.25 * np.mgrid[0:CELLS, 0:CELLS][1].astype(np.float64)


def _final_values() -> np.ndarray:
    """Octubre: 100,75 m (la columna 3 de septiembre, sin movimiento) con un hueco en la esquina
    noroeste."""
    values = np.full((CELLS, CELLS), 100.75, dtype=np.float64)
    values[0, 0] = np.nan
    return values


def _expected(start: np.ndarray, final: np.ndarray | float,
              weights: np.ndarray | float = 1.0) -> dict[str, float]:
    """Las seis cifras de los totales con espesor mínimo 0 y celdas de 1 m², sumadas aquí; con
    ``weights``, la fracción de cada celda dentro del ámbito (por columnas)."""
    moved = np.broadcast_to(np.asarray(final, dtype=np.float64), start.shape) - start
    weight = np.broadcast_to(np.asarray(weights, dtype=np.float64), start.shape)
    known = np.isfinite(moved)
    cut = float((weight * np.where(known & (moved < 0), -moved, 0.0)).sum())
    fill = float((weight * np.where(known & (moved > 0), moved, 0.0)).sum())
    return {"res.cut_m3": cut, "res.fill_m3": fill, "res.net_m3": cut - fill,
            "res.area_m2": float((weight * known).sum()),
            "res.nodata_area_m2": float((weight * ~known).sum()),
            "res.still_area_m2": float((weight * (known & (moved == 0))).sum())}


def _strip(west: float, east: float) -> np.ndarray:
    """La fracción de cada columna de la rejilla entre las x ``west`` y ``east``."""
    columns = vf.WEST + np.arange(CELLS, dtype=np.float64)
    return np.clip(np.minimum(columns + 1.0, east) - np.maximum(columns, west), 0.0, 1.0)


def _breakdown_expected() -> dict[tuple[str, float, str], float]:
    """El desmonte de cada fase (``''``: fuera de ellas; ``'*'``: todas), banco (su cota de
    abajo) y unidad (la montera sobre :data:`BASE_M`; la capa útil, debajo), sumado aquí celda a
    celda: lo que de ``[final, partida]`` cae en el banco y en la unidad, por la fracción de la
    columna dentro de la fase."""
    start, final = _start_values(), _final_values()
    weights = {name: _strip(west, east) for name, west, east in PHASES}
    weights[""] = 1.0 - sum(weights.values())
    weights["*"] = np.ones(CELLS)
    units = {"montera": (BASE_M, np.inf), "capa_util": (-np.inf, BASE_M)}
    found: dict[tuple[str, float, str], float] = {}
    for domain, weight in weights.items():
        for low in (ANCHOR_M - BENCH_M, ANCHOR_M, ANCHOR_M + BENCH_M):
            for code, (base, roof) in units.items():
                total = 0.0
                for (row, column), top in np.ndenumerate(start):
                    bottom = final[row, column]
                    if np.isfinite(bottom) and top > bottom:
                        thick = min(top, roof, low + BENCH_M) - max(bottom, base, low)
                        total += float(weight[column]) * max(0.0, thick)
                found[(domain, low, code)] = total
    return found


def _files(root: Path) -> list[str]:
    """Los ficheros de la carpeta del proyecto (sin la base, su diario y la cabecera)."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*")
                  if path.is_file() and path.relative_to(root).as_posix() not in WRITTEN)


def _surface(uid: str) -> SimpleNamespace:
    """Un objeto de la vista que muestra la rejilla ``uid`` (lo que lee ``invoke``)."""
    return SimpleNamespace(geoblender=SimpleNamespace(kind="DTM", dataset_uid=uid))


class ResBetweenSurfacesTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 activa en la sesión, para toda la
    clase (cada prueba cubica con su propio nombre)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r21-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.ps = _module("bl.scene.project_session")
        cls.res_ops = _module("bl.ops.res")
        cls.panels = _module("bl.ui.res_panels")
        cls.session = _module("bl.ops.core_provenance")
        cls.views = _module("bl.scene.views")
        cls.commands = _module("bl.ui.commands")
        cls.provenance = _module("reserves.provenance")
        (folder / "proyectos").mkdir()
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=vf.WINDOW,
                                                                  grid_step_m=vf.STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva",
                                                      title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="sur",
                                                      title="Fase sur", reason=REASON)
        cls.project.refresh_header()
        cls.uids = cls.write_grids()
        sources = folder / "fuentes"
        sources.mkdir()
        cls.scope = cls.import_layer(sources, "ambito", "Ámbito", [(1, None, [SCOPE_RING])],
                                     role="boundary")
        cls.rest = cls.import_layer(
            sources, "resto", "Resto",
            [(fid, None, [cls.strip_ring(west, east)])
             for fid, (west, east) in enumerate(REST, start=1)], role="boundary")
        cls.cubicated: set[str] = set()
        cls.phases = cls.import_layer(
            sources, "fases", "Fases",
            [(fid, name, [cls.strip_ring(west, east)])
             for fid, (name, west, east) in enumerate(PHASES, start=1)],
            role="domains", field="Fase")
        cls.overlaps = cls.import_layer(
            sources, "solapes", "Solapes",
            [(fid, value, [cls.strip_ring(west, east)]) for fid, value, west, east in OVERLAPS],
            role="domains", field="zona")
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @classmethod
    def write_grids(cls) -> dict[str, str]:
        """Septiembre, octubre (8 × 8 celdas de 1 m) y «otra» (4 × 4 de 2 m, la misma
        ventana), como las deja «Rejilla del proyecto desde un MDT» (``gis.resample``); el uid
        de cada una por su nombre de dato."""
        gis_store = _module("gis.store")
        Grid, Raster = _module("gis.grid").Grid, _module("gis.raster").Raster
        crs, vertical = gis_store.project_references(cls.project)
        grid = Grid(vf.WEST, vf.SOUTH + CELLS, 1.0, 1.0, CELLS, CELLS)
        other = Grid(vf.WEST, vf.SOUTH + CELLS, 2.0, 2.0, OTHER_CELLS, OTHER_CELLS)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Meses"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        coarse = np.full((OTHER_CELLS, OTHER_CELLS), 99.0)
        with gis_store.ResultWriter(cls.project, handle) as out:
            for name, values, where in (("Septiembre", _start_values(), grid),
                                        ("Octubre", _final_values(), grid),
                                        ("Otra", coarse, other)):
                out.raster(name, Raster(where, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return {record.name: record.uid for record in records}

    @staticmethod
    def strip_ring(west: float, east: float) -> np.ndarray:
        """Una franja de norte a sur entre ``west`` y ``east`` que pasa 1 m de la rejilla."""
        south, north = vf.SOUTH - 1.0, vf.SOUTH + CELLS + 1.0
        return np.array([(west, south), (east, south), (east, north), (west, north),
                         (west, south)], dtype=np.float64)

    @classmethod
    def import_layer(cls, folder: Path, layer: str, name: str,
                     features: list[tuple[int, str | None, list[np.ndarray]]], *, role: str,
                     field: str | None = None) -> str:
        """«Capas vectoriales…» de la 006 sin su trabajo (como ``res_fixtures.import_layer``):
        la capa ``layer`` de un GeoPackage fuera del proyecto (cada entidad, ``(fid, valor del
        campo de texto field, anillos)``), importada con el papel ``role`` («boundary» o
        «domains»); el nombre de su dato (``gis_bnd_`` o ``gis_dom_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        path = folder / f"{layer}.gpkg"
        conn = sqlite3.connect(path)
        try:
            _module("core.gpkg.base").create_base(conn, crs)
            extra = "" if field is None else f', "{field}" TEXT'
            conn.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                         f"NULL, geom GEOMETRY{extra})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (layer, layer, crs.epsg))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POLYGON', ?, 0, "
                         "0)", (layer, crs.epsg))
            encode = _module("core.gpkg.wkb").encode_geometry
            for fid, value, rings in features:
                blob = encode("POLYGON", rings, crs.epsg, False)
                if field is None:
                    conn.execute(f'INSERT INTO "{layer}" VALUES (?, ?)', (fid, blob))
                else:
                    conn.execute(f'INSERT INTO "{layer}" VALUES (?, ?, ?)', (fid, blob, value))
            conn.commit()
        finally:
            conn.close()
        inputs, gis_store, vector = (_module("core.inputs"), _module("gis.store"),
                                     _module("gis.vector"))
        reader = _module("gis.content").GPKG_LAYER
        settings = {"layer": layer, "role": role}
        anchors = [inputs.locate_source(path, cls.project, cls.ps.userdata(), role="main")]
        prints = [_module("core.inputs.model").SourcePrint(
            _module("core.hashing").sha256_file(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns)]
        request = reader.request(
            reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
            dict(zip(inputs.reader_roles(anchors), [path], strict=True)), settings)
        spec = gis_store.source_input(
            reader.id, name, files=anchors, file_prints=prints,
            digest=_module("core.content.readers").read_content(reader, request), crs=crs,
            vertical=vertical, settings=settings)
        copies = folder / f"copia_{layer}"
        copies.mkdir()
        read = vector.read_layer(vector.copy_source(path, copies), layer)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": name},
            executor="blender")
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.declare_input(spec)
            if role == "domains":
                out.domains(name, vector.domains_from_features(read)[0])
            else:
                out.boundary(name, read.geometries)
            (record,) = out.commit(message=REASON)
        return record.name

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
        self.panel = self.enterContext(mock.patch.object(self.res_ops, "_call_panel",
                                                         return_value={"FINISHED"}))

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def cls(self) -> type:
        return self.commands.registered_class(BETWEEN)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def figures(self, op_uid: str, name: str, **scope: Any) -> dict[str, float]:
        """Las cifras de la operación ``op_uid`` con el ámbito de la cubicación ``name`` (y lo
        que añade ``scope``: ``domain``, ``unit``…)."""
        found = _module("core.provenance.figures").scope_json({"cubication": name, **scope})
        return dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ? AND "
                              "scope = ?", op_uid, found))

    def operations(self, name: str, op_type: str = "res.volume"
                   ) -> list[tuple[str, str, str | None, str | None]]:
        """Las ``op_type`` de la cubicación ``name``: uid, estado, lo que sustituye y quien la
        sustituye, por orden."""
        return [(uid, status, supersedes, superseded)
                for uid, status, supersedes, superseded, settings in self.rows(
                    "SELECT uid, status, supersedes_uid, superseded_by, settings FROM "
                    "gb_operation WHERE op_type = ? ORDER BY started_at, uid", op_type)
                if json.loads(settings)["name"] == name]

    def datasets(self, name: str) -> list[str]:
        slug = _module("gis.provenance").dataset_slug(name)
        return [found for (found,) in self.rows(
            "SELECT name FROM gb_dataset WHERE name IN (?, ?, ?) AND status = 'current'",
            f"res_vol_{slug}", f"res_dif_{slug}", f"res_ton_{slug}")]

    def table(self, name: str) -> list[Any]:
        """Las filas de la tabla viva ``name`` (``res_vol_…`` o ``res_ton_…``)."""
        ((locator,),) = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = "
                                  "'current'", name)
        with self.project.read() as conn:
            return list(_module("reserves.table").read_rows(conn, locator))

    def dialog(self, context: Any = None, *, command: str = BETWEEN,
               **given: Any) -> tuple[Any, Any, Any]:
        """Abre el diálogo de ``command`` a mano (``invoke`` con un ``window_manager``
        simulado) y lo dibuja: el ``self``, lo dibujado y el diálogo pedido."""
        names = frozenset(given)
        cls = self.commands.registered_class(command)
        defaults = {BREAKDOWN: BREAKDOWN_DIALOG, STAGES: STAGES_DIALOG}.get(command, DIALOG)
        if command == STAGES:
            given.setdefault("moments", _Collection())
            given.setdefault("choices", _Collection())
        fake = operator_self(cls, report=lambda kind, text: None,
                             properties=SimpleNamespace(is_property_set=names.__contains__),
                             **{**defaults, **given})
        manager = SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}),
                                  invoke_confirm=mock.Mock(return_value={"RUNNING_MODAL"}))
        if context is None:
            context = SimpleNamespace(window_manager=manager, window=None, selected_objects=[])
        else:
            context.window_manager = manager
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        cls.draw(fake, bpy.context)
        return fake, fake.layout, manager

    def running(self, command: str = BETWEEN) -> Any:
        """La orden ``command`` que está en marcha como modal (la que aún tiene pasos)."""
        cls = self.commands.registered_class(command)
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{command} no está en marcha")
        return found[0]

    def drive(self, operator: Any) -> tuple[set[str], list[float]]:
        """Un evento del temporizador cada vez hasta que el modal acaba: su final y lo que duró
        cada llamada (s)."""
        calls: list[float] = []
        for _ in range(MAX_EVENTS):
            started = time.perf_counter()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.perf_counter() - started)
            if state != {"RUNNING_MODAL"}:
                return state, calls
        self.fail("Entre dos superficies… no acaba")

    def refused(self, *, command: str = BETWEEN, **values: Any) -> str:
        """El error de la orden ``command`` desde un guion (``RuntimeError``) sin que cambie el
        proyecto."""
        counter = vf.change_counter(self.project)
        with self.assertRaises(RuntimeError) as caught:
            getattr(bpy.ops.geoblender, command.split(".")[1])(**values)
        self.assertEqual(vf.change_counter(self.project), counter)
        return str(caught.exception)

    def save_column(self) -> None:
        """La columna de la prueba en el proyecto (``res.edit_materials``): la montera (estéril,
        in situ, con su base a :data:`BASE_M`) sobre la capa útil (útil, in situ, sin base), y
        la densidad y el K de la capa útil (HIPÓTESIS); la montera, sin densidad ni K."""
        materials, store = _module("reserves.materials"), _module("reserves.store")
        surface = _module("reserves.surfaces").SurfaceRef
        column = materials.MaterialColumn((
            materials.Unit("montera", "Montera", "natural", "waste", "in_situ",
                           base=surface(elevation=BASE_M)),
            materials.Unit("capa_util", "Capa útil", "natural", "useful", "in_situ")))
        handle = _module("core.provenance.operations").begin_operation(
            self.project, self.provenance.EDIT_MATERIALS, settings={"units": 2},
            executor="blender")
        store.save_materials(self.project, handle, column)
        self.declare({"res.unit.capa_util.density": DENSITY["capa_util"],
                      "res.unit.capa_util.swell": SWELL})

    def stage_cubications(self) -> None:
        """Las cubicaciones de los momentos en V01, una vez por clase, desde un guion: las de
        :data:`STAGE_CUBICATIONS` por unidades (con la columna de la prueba y la densidad de la
        montera; ``res.volume`` y ``res.tonnage``) y :data:`WITHOUT_UNITS`, sin ellas."""
        materials = _module("reserves.materials")
        with self.project.read() as conn:
            saved = materials.read_column(conn) is not None
        if not saved:
            self.save_column()
        density = _module("core.params").ParameterStore(self.project).get(
            "res.unit.montera.density")
        if density is None or density.value != DENSITY["montera"]:
            self.declare({"res.unit.montera.density": DENSITY["montera"]})
        layers = {None: "NONE", "scope": self.scope, "rest": self.rest}
        for name, layer in STAGE_CUBICATIONS.items():
            if name not in self.cubicated:
                self.assertEqual(bpy.ops.geoblender.res_compute_volume_breakdown(
                    name=name, start=START, final=FINAL, scope_layer=layers[layer],
                    by_units=True), {"FINISHED"})
                self.cubicated.add(name)
        if WITHOUT_UNITS not in self.cubicated:
            self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
                name=WITHOUT_UNITS, start=START, final=FINAL, scope_layer=self.scope,
                difference_grid=False), {"FINISHED"})
            self.cubicated.add(WITHOUT_UNITS)

    def stage_figures(self, op_uid: str, name: str, **scope: Any) -> dict[str, float]:
        """Las cifras de la operación ``op_uid`` con el ámbito de la cubicación por momentos
        ``name`` (y ``volume``, ``unit``)."""
        found = _module("core.provenance.figures").scope_json({"stages": name, **scope})
        return dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ? AND "
                              "scope = ?", op_uid, found))

    def compare(self, name: str, moments: list[str]) -> tuple[Any, str]:
        """«Por momentos de extracción…» de ``name`` (los momentos ``moments`` frente a
        :data:`DIRECT`) por pasos, un evento cada vez (ninguna llamada de más de 0,2 s): la
        orden, ya terminada, y el uid de su operación."""
        self.assertEqual(bpy.ops.geoblender.res_compute_extraction_stages(
            "EXEC_DEFAULT", name=name, moments=[{"name": item} for item in moments],
            direct=DIRECT, in_steps=True), {"RUNNING_MODAL"})
        operator = self.running(STAGES)
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        ((uid, status, _old, _new),) = self.operations(name, "res.stages")
        self.assertEqual(status, "done")
        return operator, uid

    def declare(self, values: dict[str, float]) -> None:
        """Declara en el proyecto cada parámetro de ``values`` como HIPÓTESIS (lo da de alta o,
        si ya está, sin valor «sin confirmar», lo cambia)."""
        store = _module("core.params").ParameterStore(self.project)
        given = {"kind": "HIPÓTESIS", "source": "Valores sintéticos de prueba",
                 "source_kind": "document", "decided_by": "Samuel (IMGA)", "reason": REASON}
        with self.project.write_transaction() as conn:
            for key, value in values.items():
                if store.get(key, conn=conn) is None:
                    store.create(conn, key, value, **given)
                else:
                    store.change(conn, key, value=value, **given)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_command_of_011_with_its_shortcut(self) -> None:
        """D-36, RF-011-06, RF-003-18: «Cubicar entre dos superficies…» es la orden real de la
        entrada «011» (no la provisional de R-38), lanza ``res.volume`` con la puerta de la
        procedencia y los pasos con Esc, y conserva su atajo Mayús+Alt+M en la Vista 3D (que en
        modo Blender queda para Blender, con su motivo)."""
        command = self.commands.catalog().commands[BETWEEN]
        self.assertEqual(command.entry, ENTRY)
        cls = self.cls
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.VOLUME, {"REGISTER"}))
        items = [(keymap.name, item.type, item.shift, item.alt, item.ctrl)
                 for keymap, item in _module("bl.ui.keymap").registered_items()
                 if item.idname == BETWEEN]
        self.assertEqual(items, [("3D View", "M", True, True, False)])
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        self.assertFalse(window.workspace.geoblender_mode)
        with mock.patch.object(cls, "poll_message_set") as message:
            with bpy.context.temp_override(window=window, area=area, region=region):
                self.assertFalse(cls.poll(bpy.context))
        message.assert_called_once_with("Solo en modo Geoblender (Ctrl+F10) o desde "
                                        "Geoblender ▾")
        self.assertTrue(cls.poll(bpy.context))

    def test_dialog_proposes_the_selected_surfaces(self) -> None:
        """RF-011-06, RF-011-02, RF-011-04 (D-31): con las dos superficies seleccionadas en
        cualquier orden, el diálogo propone de partida la de mayor cota media (septiembre) y de
        final la otra, con el nombre «octubre − septiembre»; ofrece las rejillas del proyecto y
        la cota constante, el ámbito opcional y la rejilla de diferencias (sí), y dice el
        espesor mínimo con su valor y su tipo. «Invertir» las cambia, con su nombre."""
        for order in ((FINAL, START), (START, FINAL)):
            with self.subTest(selección=order):
                context = SimpleNamespace(window=None, selected_objects=[
                    _surface(self.uids[name]) for name in order])
                fake, layout, manager = self.dialog(context)
                self.assertEqual((fake.start, fake.final, fake.name),
                                 (START, FINAL, "octubre − septiembre"))
        self.assertEqual(manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Cubicar entre dos superficies…")
        self.assertEqual([item[0] for item in self.panels.surface_items(None, None)],
                         [FINAL, OTHER, START, ELEVATION])
        self.assertEqual([item[0] for item in self.panels.scope_items(None, None)],
                         ["NONE", self.scope, self.rest, self.phases, self.overlaps])
        self.assertEqual([item.target for item in layout.of_kind("prop")],
                         ["name", "start", "invert", "final", "scope_layer", "difference_grid"])
        labels = [item.text for item in layout.of_kind("label")]
        self.assertIn("Espesor mínimo: 0 m [ADO] sin confirmar (se cambia en Proyecto ▸ Control "
                      "▸ Parámetros del proyecto…)", labels)

        fake.invert = True
        self.res_ops.invert_surfaces(fake, None)
        self.assertEqual((fake.start, fake.final, fake.name, fake.invert),
                         (FINAL, START, "septiembre − octubre", False))
        fake.final, fake.final_elevation = ELEVATION, "100,5"
        fake.invert = True
        self.res_ops.invert_surfaces(fake, None)
        self.assertEqual((fake.start, fake.start_elevation, fake.final, fake.final_elevation),
                         (ELEVATION, "100,5", FINAL, ""))
        self.cls.draw(fake, bpy.context)
        self.assertIn("start_elevation", [item.target for item in fake.layout.of_kind("prop")])

    def test_cubicate_in_steps_esc_and_finish(self) -> None:
        """RF-011-01, RF-011-04, RF-011-20, RF-011-25 (A10, A11, D-25; RNF-011-04): por pasos,
        un evento cada vez; Esc antes del primer paso o a mitad (leyendo, con su avance en la
        barra de estado) deja la operación cancelada y ni cifra, ni tabla, ni rejilla, ni
        fichero. Otra vez hasta el final, con su avance en la barra de estado y
        ninguna llamada de más de 0,2 s: las seis cifras de los totales (las de la prueba), de
        la revisión abierta de V01, la tabla y la rejilla de diferencias, cargada en la vista, y
        la ventana de la cubicación."""
        name = "Mensual octubre"
        values = {"name": name, "start": START, "final": FINAL, "in_steps": True}
        before = _files(self.project.root)
        shown: list[str] = []
        status_text = self.cls._status_text

        def spy(op: Any, step: Any) -> str:
            shown.append(status_text(op, step))
            return shown[-1]

        self.enterContext(mock.patch.object(self.cls, "_status_text", spy))
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
        self.assertEqual(self.running().modal(bpy.context, ESC), {"CANCELLED"})  # sin empezar
        with mock.patch.object(self.cls, "STEP_BUDGET_S", 1e-9):  # un paso por evento
            self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
                "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
            operator = self.running()
            for _ in range(2):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            self.assertEqual(operator.progress_log[-1][1], "bands")  # a mitad
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], CANCELLED)
        self.assertEqual(shown[-1][:len(f"Cubicando «{name}»: leyendo… ")],
                         f"Cubicando «{name}»: leyendo… ")
        cancelled = self.operations(name)
        self.assertEqual([status for _uid, status, _old, _new in cancelled],
                         ["cancelled", "cancelled"])
        for uid, _status, _old, _new in cancelled:
            self.assertEqual(self.figures(uid, name), {})
        self.assertEqual(self.datasets(name), [])
        self.assertEqual(_files(self.project.root), before)

        shown.clear()
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            "EXEC_DEFAULT", **values), {"RUNNING_MODAL"})
        operator = self.running()
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        self.assertTrue(shown)
        for text in shown:
            self.assertTrue(text.startswith(f"Cubicando «{name}»: ")
                            and text.endswith(" % · Esc: cancelar")
                            or re.fullmatch(f"Cargando «{name}» en la vista… \\d+ %", text),
                            text)
        expected = _expected(_start_values(), _final_values())
        (*_cancelled, (uid, status, _old, _new)) = self.operations(name)
        self.assertEqual(status, "done")
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(expected["res.still_area_m2"], 8.0)  # RF-011-04: la columna 3
        ((revision, inputs),) = self.rows(
            "SELECT o.revision_uid, (SELECT group_concat(io.role) FROM gb_operation_io AS io "
            "WHERE io.operation_uid = o.uid AND io.direction = 'in') FROM gb_operation AS o "
            "WHERE o.uid = ?", uid)
        self.assertEqual(self.rows("SELECT version_uid FROM gb_revision WHERE uid = ?",
                                   revision), [(self.v01.uid,)])
        self.assertEqual(sorted(inputs.split(",")), ["final", "start"])
        self.assertEqual(sorted(self.datasets(name)),
                         ["res_dif_mensual_octubre", "res_vol_mensual_octubre"])
        number_text = _module("reserves.table").number_text  # sin decimales (RF-011-23, T34)
        self.assertIn(f"{name} (V01.r1, en curso): desmonte "
                      f"{number_text(expected['res.cut_m3'], 'm3')} m³, terraplén "
                      f"{number_text(expected['res.fill_m3'], 'm3')} m³, neto "
                      f"{number_text(expected['res.net_m3'], 'm3')} m³", operator.report_log)
        (grid_uid,) = [found for (found,) in self.rows(
            "SELECT uid FROM gb_dataset WHERE name = 'res_dif_mensual_octubre'")]
        self.assertEqual(len([obj for obj in bpy.data.objects
                              if obj.geoblender.dataset_uid == grid_uid]), 1)
        self.panel.assert_called_with(PANEL)

    def test_constant_final_and_refusals(self) -> None:
        """RF-011-02, RF-011-03: desde un guion, de una vez, una cota constante como final da
        sus cifras; dos superficies que no casan (otro paso), dos cotas constantes o una cota
        que no es un número se rechazan con las dos superficies, la diferencia y la orden que
        lo resuelve, sin escribir nada (ni la operación)."""
        name = "Contra cota"
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name=name, start=START, final=ELEVATION, final_elevation="100,5",
            difference_grid=False), {"FINISHED"})
        ((uid, status, _old, _new),) = self.operations(name)
        self.assertEqual(status, "done")
        expected = _expected(_start_values(), 100.5)
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(self.datasets(name), ["res_vol_contra_cota"])

        text = self.refused(name="Otra rejilla", start=START, final=OTHER)
        self.assertIn(f"No se pueden cubicar «{START}» y «{OTHER}»: ", text)
        self.assertIn("Topografía ▸ Rejilla de proyecto desde un MDT…", text)
        text = self.refused(name="Dos cotas", start=ELEVATION, start_elevation="101",
                            final=ELEVATION, final_elevation="100,5")
        self.assertIn("son las dos cotas constantes", text)
        text = self.refused(name="Sin cota", start=START, final=ELEVATION, final_elevation="x")
        self.assertIn("Cota final: «x» no es un número de metros", text)
        for refused in ("Otra rejilla", "Dos cotas", "Sin cota"):
            self.assertEqual(self.operations(refused), [])

    def assertSixUnavailable(self, reason: str) -> None:  # noqa: N802
        """Las seis órdenes de Cubicación, desactivadas: su ``poll`` dice ``reason`` (y, la
        versión no editable, también su descripción)."""
        for idname in SIX:
            cls = self.commands.registered_class(idname)
            with self.subTest(orden=idname), mock.patch.object(cls, "poll_message_set") as message:
                self.assertFalse(cls.poll(bpy.context))
                message.assert_called_once_with(reason)
                if reason == NOT_EDITABLE:
                    self.assertIn(reason, cls.description(bpy.context, None))

    def assertSixAvailable(self) -> None:  # noqa: N802
        for idname in SIX:
            with self.subTest(orden=idname):
                self.assertTrue(self.commands.registered_class(idname).poll(bpy.context))

    def test_needs_an_editable_version_and_writing(self) -> None:
        """RF-011-20, RF-011-26 (RF-009-05, RF-009-21; plan §5.3.4): las seis órdenes de
        Cubicación (las cuatro que cubican, Materiales y densidades… y Ratios…), activas con el
        proyecto en escritura y la versión activa editable o sin ninguna (sin ella, «Cubicar
        entre dos superficies…» lanzada desde la interfaz abre la ventana de elegir o crear una
        y no hace nada más); con la activa SUPERADO, desactivadas con «V02 está en estado
        SUPERADO: cree una versión nueva a partir de ella» (también en su descripción), y con el
        proyecto en solo lectura, con «Proyecto en solo lectura: …»."""
        cls = self.cls
        self.set_active(None)
        self.addCleanup(self.set_active, self.v01)
        self.assertSixAvailable()
        fake = operator_self(cls, report=lambda kind, text: None, **DIALOG)
        with mock.patch.object(self.session, "open_version_dialog") as opened:
            self.assertEqual(cls.invoke(fake, SimpleNamespace(window=None), None),
                             {"CANCELLED"})
        opened.assert_called_once_with()

        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.assertSixUnavailable(NOT_EDITABLE)
        self.set_active(self.v01)
        self.assertSixAvailable()

        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = self.session.write_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertSixUnavailable(reason)
        self.assertSixAvailable()

    def test_scope_layer_limits_the_cubication(self) -> None:
        """RF-011-01, RF-011-20 (D-32): con un ámbito (una capa de contornos importada), solo
        cuenta lo que queda dentro, con la fracción exacta de cada celda (media columna en su
        borde); la operación consume la capa con el papel «scope» y la nombra en sus
        ajustes."""
        name = "Con ámbito"
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name=name, start=START, final=FINAL, scope_layer=self.scope,
            difference_grid=False), {"FINISHED"})
        ((uid, status, _old, _new),) = self.operations(name)
        self.assertEqual(status, "done")
        expected = _expected(_start_values(), _final_values(), SCOPE_WEIGHTS)
        self.assertEqual({key: value for key, value in self.figures(uid, name).items()
                          if key in expected}, expected)
        self.assertEqual(expected["res.area_m2"], 36.0)
        (settings,) = [json.loads(found) for (found,) in self.rows(
            "SELECT settings FROM gb_operation WHERE uid = ?", uid)]
        self.assertEqual(settings["scope"], self.scope)
        self.assertIn(("scope",), self.rows("SELECT role FROM gb_operation_io WHERE "
                                            "operation_uid = ? AND direction = 'in'", uid))

    def test_repeated_name_asks_before_replacing(self) -> None:
        """D-30 (RF-011-20): repetir el nombre de una cubicación de la versión activa, desde un
        guion, se rechaza sin escribir nada; desde la interfaz, pregunta si se sustituye
        («Ya hay una cubicación «Repetida» en V01: ¿sustituirla?») y, aceptado, la nueva
        sustituye a la anterior."""
        name = "Repetida"
        values = {"name": name, "start": START, "final": FINAL, "difference_grid": False}
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(**values),
                         {"FINISHED"})
        ((first, _status, _old, _new),) = self.operations(name)
        text = self.refused(**values)
        self.assertIn("Ya hay una cubicación «Repetida» en V01", text)

        fake = operator_self(self.cls, report=lambda kind, text: None, provenance_dialog=True,
                             **{**DIALOG, **values})
        with mock.patch.object(self.res_ops, "_confirm_later") as later:
            self.assertEqual(self.cls.execute(fake, bpy.context), {"CANCELLED"})
        (asked,), _kw = later.call_args
        self.assertEqual({key: asked[key] for key in values}, values)
        self.assertEqual(len(self.operations(name)), 1)
        _fake, _layout, manager = self.dialog(confirm=True, **values)
        self.assertEqual(manager.invoke_confirm.call_args.kwargs["message"],
                         "Ya hay una cubicación «Repetida» en V01: ¿sustituirla?")
        self.assertTrue(_fake.replace)

        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            replace=True, **values), {"FINISHED"})
        ((old, _s1, _o1, replaced), (new, status, supersedes, _n2)) = self.operations(name)
        self.assertEqual((old, replaced, status, supersedes), (first, new, "done", first))

    # --- Por unidad, fase y banco… (T23) ------------------------------------------------------

    def test_breakdown_by_phase_bench_and_unit(self) -> None:
        """RF-011-07, RF-011-09, RF-011-10, RF-011-12, RF-011-16, RF-011-17, RF-011-18,
        RF-011-20, RF-011-25 (D-16, D-30, D-36; RNF-011-04): «Por unidad, fase y banco…» es la
        orden real de la entrada «011»; su diálogo ofrece las capas de dominios con sus campos,
        los bancos, «Por unidades» y la rejilla y, sin columna de materiales, el aviso que lleva
        a definirla (desde un guion, el rechazo, sin escribir nada). Con la columna (la montera
        sobre la capa útil), la capa «Fases» por su campo «Fase» y bancos de 1 m anclados a
        100,5 m, por pasos (ninguna llamada de más de 0,2 s): ``res.volume`` y, encadenada,
        ``res.tonnage`` en V01.r1; la tabla fase × banco × unidad (m³ in situ; m³ esponjados y
        t) igual a la sumada en la prueba y sus cifras; sin la densidad de la montera, su aviso
        y ningún total de toneladas. Repetida desde un guion con esa densidad (sustituir), las
        dos operaciones nuevas sustituyen a las anteriores y sale el total."""
        self.assertEqual(self.commands.catalog().commands[BREAKDOWN].entry, ENTRY)
        cls = self.commands.registered_class(BREAKDOWN)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.VOLUME, {"REGISTER"}))
        fake, layout, manager = self.dialog(command=BREAKDOWN, domains_layer=self.phases)
        self.assertEqual(manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Por unidad, fase y banco…")
        self.assertEqual([item[0] for item in self.panels.domain_items(None, None)],
                         ["NONE", self.phases, self.overlaps])
        self.assertEqual([item[:2] for item in self.panels.field_items(fake, None)],
                         [("fase", "Fase")])
        self.assertEqual([item.target for item in layout.of_kind("prop")],
                         ["name", "start", "invert", "final", "scope_layer", "domains_layer",
                          "domains_field", "bench_height", "bench_anchor", "bench_levels",
                          "by_units", "difference_grid"])
        labels = [item.text for item in layout.of_kind("label")]
        hint = "defina antes los materiales (Cubicación ▸ Materiales y densidades…)"
        self.assertTrue(any(hint in label for label in labels), labels)
        name = "Por fases"
        values = {"name": name, "start": START, "final": FINAL, "domains_layer": self.phases,
                  "domains_field": "fase", "bench_height": "1", "bench_anchor": "100,5",
                  "by_units": True}
        self.assertIn(hint, self.refused(command=BREAKDOWN, **values))

        self.save_column()
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_breakdown(
            "EXEC_DEFAULT", in_steps=True, **values), {"RUNNING_MODAL"})
        operator = self.running(BREAKDOWN)
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assertLessEqual(max(calls), CALL_LIMIT_S, calls)
        self.assertIn("read", {phase for _at, phase, *_rest in operator.progress_log})  # pesar
        ((volume, status, _old, _new),) = self.operations(name)
        ((tonnage, weighed, _o, _n),) = self.operations(name, "res.tonnage")
        self.assertEqual((status, weighed), ("done", "done"))
        roles = {uid: sorted(role for (role,) in self.rows(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid))
            for uid in (volume, tonnage)}
        self.assertEqual(roles, {volume: ["domains", "final", "materials", "start"],
                                 tonnage: ["materials", "volumes"]})
        ((revision,),) = self.rows("SELECT DISTINCT revision_uid FROM gb_operation WHERE uid IN "
                                   "(?, ?)", volume, tonnage)
        self.assertEqual(self.rows("SELECT version_uid FROM gb_revision WHERE uid = ?",
                                   revision), [(self.v01.uid,)])
        self.assertEqual(sorted(self.datasets(name)), ["res_ton_por_fases", "res_vol_por_fases"])

        expected = _breakdown_expected()
        found = {(row.domain, row.bench_z0, row.unit): row.value
                 for row in self.table("res_vol_por_fases")
                 if row.quantity == "volume_m3" and row.unit is not None
                 and row.bench_z0 is not None}
        self.assertEqual(sorted(found), sorted(expected))
        weighed_rows = self.table("res_ton_por_fases")
        by_key = {(row.quantity, row.domain, row.bench_z0, row.unit): row for row in weighed_rows
                  if row.bench_z0 is not None and row.component is None}
        for key, value in expected.items():
            with self.subTest(fase=key[0], banco=key[1], unidad=key[2]):
                self.assertAlmostEqual(found[key], value, delta=1e-9)
                mass = by_key[("mass_t", *key)]
                if key[2] == "capa_util":
                    self.assertAlmostEqual(mass.value, DENSITY["capa_util"] * value, delta=1e-9)
                    self.assertAlmostEqual(by_key[("swell_m3", *key)].value, SWELL * value,
                                           delta=1e-9)
                elif value > 0.0:  # RF-011-17: la montera, sin densidad
                    self.assertIsNone(mass.value)
                    self.assertIn("res.note_no_density", mass.note)
        (total,) = [row for row in weighed_rows if row.quantity == "total_t"
                    and row.domain == "*" and row.bench_z0 is None and row.bench_z1 is None]
        self.assertIsNone(total.value)
        self.assertAlmostEqual(self.figures(volume, name, domain="Fase 2")["res.cut_m3"],
                               sum(value for key, value in expected.items()
                                   if key[0] == "Fase 2"), delta=1e-9)
        useful = sum(value for key, value in expected.items()
                     if key[0] == "*" and key[2] == "capa_util")
        self.assertGreater(useful, 0.0)
        self.assertAlmostEqual(self.figures(tonnage, name, unit="capa_util")["res.unit_t"],
                               DENSITY["capa_util"] * useful, delta=1e-9)
        self.assertNotIn("res.total_t", self.figures(tonnage, name))
        self.assertTrue(any(MISSING_DENSITY in text for text in operator.report_log),
                        operator.report_log)
        self.assertIn(f"Toneladas de «{name}» (V01.r1, en curso): sin total de toneladas",
                      operator.report_log)
        self.panel.assert_called_with(PANEL)

        self.declare({"res.unit.montera.density": DENSITY["montera"]})
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_breakdown(replace=True, **values),
                         {"FINISHED"})
        for op_type, first in (("res.volume", volume), ("res.tonnage", tonnage)):
            ((old, _s1, _o1, replaced), (new, status, supersedes, _n2)) = self.operations(
                name, op_type)
            self.assertEqual((old, replaced, status, supersedes), (first, new, "done", first))
        self.assertAlmostEqual(self.figures(new, name)["res.total_t"],
                               sum(DENSITY[key[2]] * value for key, value in expected.items()
                                   if key[0] == "*"), delta=1e-9)

    def test_breakdown_refuses_an_invalid_domain_layer(self) -> None:
        """RF-011-08, RF-011-09, RF-011-25 (A6): con la capa «Solapes» (dos polígonos que se
        solapan en 10 m² y uno con el campo vacío), desde un guion, el rechazo lista cada
        polígono con su número y su valor, su problema y el área del solape; la operación queda
        fallida sin cifras, tablas ni rejillas. Unos bancos escritos de las dos maneras se
        rechazan con su texto sin escribir nada."""
        name = "Con solapes"
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.res_compute_volume_breakdown(
                name=name, start=START, final=FINAL, domains_layer=self.overlaps,
                domains_field="zona")
        text = str(caught.exception)
        self.assertIn(f"La capa de dominios «{self.overlaps}» no sirve para repartir por "
                      "«zona»", text)
        self.assertIn("los polígonos 1 («A») y 2 («B») se solapan en 10,00 m²", text)
        self.assertIn("el polígono 3 tiene vacío el campo «zona»", text)
        ((uid, status, _old, _new),) = self.operations(name)
        self.assertEqual(status, "failed")
        self.assertEqual(self.figures(uid, name), {})
        self.assertEqual(self.datasets(name), [])
        text = self.refused(command=BREAKDOWN, name="Dos maneras", start=START, final=FINAL,
                            bench_height="10", bench_anchor="0", bench_levels="100; 110")
        self.assertIn("no las dos cosas", text)

    # --- Por momentos de extracción… y Ratios… (T24) -------------------------------------------

    def test_extraction_stages_against_the_direct(self) -> None:
        """RF-011-19, RF-011-20, RF-011-22, RF-011-25 (A13, D-30, D-33, D-36; RNF-011-04): «Por
        momentos de extracción…» es la orden real de la entrada «011»; su diálogo ofrece las
        cubicaciones de V01 como momentos (ninguno elegido) y como directa, y dice la
        tolerancia con su tipo. Dos momentos que parten la directa (el ámbito y lo que queda
        fuera, por unidades), por pasos: ``res.stages`` en V01.r1 con sus tablas de volúmenes
        como entradas, la tabla por momento y unidad, la suma igual a la directa (diferencia 0
        m³ y 0 %) en el desmonte, el terraplén y cada unidad, y ningún aviso. Un momento que
        deja un hueco y no tiene unidades: la diferencia en m³ y en % y el aviso de cada
        comparación que pasa de la tolerancia y el de la columna; ninguna cifra se ajusta. Los
        momentos mal elegidos y el nombre repetido (desde un guion), rechazados sin escribir
        nada."""
        self.assertEqual(self.commands.catalog().commands[STAGES].entry, ENTRY)
        cls = self.commands.registered_class(STAGES)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, _module("bl.ops.core")._StepsModal))
        self.assertEqual((cls.provenance_op_type, cls.bl_options),
                         (self.provenance.STAGES, {"REGISTER"}))
        self.stage_cubications()
        fake, layout, manager = self.dialog(command=STAGES)
        self.assertEqual(manager.invoke_props_dialog.call_args.kwargs["title"],
                         "Por momentos de extracción…")
        names = [item.name for item in fake.choices]
        self.assertLessEqual({*STAGE_CUBICATIONS, WITHOUT_UNITS}, set(names))
        self.assertEqual(names, sorted(names, key=str.casefold))
        self.assertFalse(any(item.chosen for item in fake.choices))
        self.assertEqual(list(fake.moments), [])
        self.assertEqual([item.target for item in layout.of_kind("prop")],
                         ["name", *["chosen"] * len(names)])
        self.assertEqual([(item.options["property"], item.options["search_property"])
                          for item in layout.of_kind("prop_search")],
                         [("direct", "cubications")])
        self.assertEqual([item.name for item in self.panels.view().cubications], names)
        labels = [item.text for item in layout.of_kind("label")]
        self.assertIn("Tolerancia de los momentos: 1 % [ADO] sin confirmar (se cambia en "
                      "Proyecto ▸ Control ▸ Parámetros del proyecto…)", labels)

        name = "Por momentos"
        operator, uid = self.compare(name, ["Explotación", "Resto"])
        roles = dict(self.rows(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid))
        self.assertEqual(roles, {"stage_1": "res_vol_explotacion", "stage_2": "res_vol_resto",
                                 "direct": "res_vol_directa"})
        ((revision,),) = self.rows("SELECT revision_uid FROM gb_operation WHERE uid = ?", uid)
        self.assertEqual(self.rows("SELECT version_uid FROM gb_revision WHERE uid = ?",
                                   revision), [(self.v01.uid,)])
        for scope, total in (({"volume": "Desmonte"}, 20.0), ({"volume": "Terraplén"}, 11.25),
                             ({"volume": "Desmonte", "unit": "montera"}, 12.0),
                             ({"volume": "Desmonte", "unit": "capa_util"}, 8.0)):
            with self.subTest(**scope):
                self.assertEqual(self.stage_figures(uid, name, **scope),
                                 {"res.stages_sum_m3": total, "res.stages_diff_m3": 0.0,
                                  "res.stages_diff_pct": 0.0})
        ((locator,),) = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = "
                                  "'current'", "res_stg_por_momentos")
        with self.project.read() as conn:
            rows = _module("reserves.table").read_stage_rows(conn, locator)
        found = {(item.stage, item.row.quantity, item.row.unit): item.row.value for item in rows
                 if item.stage is not None}
        self.assertEqual(found, {
            ("Explotación", "cut_m3", None): 6.0, ("Explotación", "fill_m3", None): 4.0,
            ("Explotación", "volume_m3", "montera"): 2.0,
            ("Explotación", "volume_m3", "capa_util"): 4.0,
            ("Resto", "cut_m3", None): 14.0, ("Resto", "fill_m3", None): 7.25,
            ("Resto", "volume_m3", "montera"): 10.0, ("Resto", "volume_m3", "capa_util"): 4.0})
        self.assertIn(f"«{name}» (V01.r1, en curso): suma de los momentos 20 m³, directa "
                      "«Directa» 20 m³, diferencia 0 m³ (0,00 %)", operator.report_log)
        self.assertEqual(len(operator.report_log), 1, operator.report_log)  # ningún aviso

        operator, uid = self.compare("Con hueco", [WITHOUT_UNITS])
        self.assertEqual(self.stage_figures(uid, "Con hueco", volume="Desmonte"),
                         {"res.stages_sum_m3": 6.0, "res.stages_diff_m3": -14.0,
                          "res.stages_diff_pct": -70.0})
        warnings = operator.report_log[1:]
        self.assertEqual(len(warnings), 5, warnings)  # la columna, el desmonte, el terraplén y
        self.assertIn("«Sin unidades» no usa la misma columna de materiales que «Directa»: sus "
                      "unidades no son comparables.", warnings)  # las dos unidades
        self.assertTrue(any(text.startswith(
            "Desmonte: la suma de los momentos (6 m³) difiere de la cubicación directa "
            "«Directa» (20 m³) en -14 m³ (-70,00 %), más que la tolerancia de 1 %")
            for text in warnings), warnings)

        values = {"name": "Mal elegidos", "direct": DIRECT}
        for moments, expected in (
                ([], "Elija al menos un momento de extracción"),
                ([DIRECT], "La cubicación directa «Directa» no puede ser también un momento"),
                (["Resto", "Resto"], "«Resto» se ha elegido dos veces como momento"),
                (["Resto", "Ninguna"], "No hay ninguna cubicación «Ninguna» en V01"),
                ([f"M{index}" for index in range(11)], "como mucho 10 momentos")):
            with self.subTest(momentos=moments):
                text = self.refused(command=STAGES, moments=[{"name": item} for item in moments],
                                    **values)
                self.assertIn(expected, text)
        text = self.refused(command=STAGES, name="Sin directa", moments=[{"name": "Resto"}])
        self.assertIn("Elija la cubicación directa", text)
        text = self.refused(command=STAGES, name=name, direct=DIRECT,
                            moments=[{"name": "Explotación"}, {"name": "Resto"}])
        self.assertIn(f"Ya hay una cubicación por momentos «{name}» en V01", text)
        self.assertEqual(self.operations("Mal elegidos", "res.stages"), [])

    def test_ratios_open_the_table_of_the_cubication(self) -> None:
        """RF-011-18, RF-011-23 (D-35, D-36): «Ratios…» es la orden real de la entrada «011»:
        con una cubicación por unidades de V01, deja elegida su tabla en la ventana de la
        cubicación con el filtro de relaciones (las filas de relaciones de sus toneladas: la
        estéril/útil del total, 12 m³ de montera frente a 8 m³ de capa útil) y la abre, y dice
        su relación en m³/m³ y en t/t; sin decir cuál, la elegida en el panel. Con una sin
        unidades, lo dice y no abre nada."""
        self.assertEqual(self.commands.catalog().commands[RATIOS].entry, ENTRY)
        cls = self.commands.registered_class(RATIOS)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.res_ops.classes)
        self.assertEqual(cls.bl_options, {"REGISTER"})
        self.stage_cubications()
        view = self.panels.view()
        view.cubication, view.quantities = "", "ALL"
        reports: list[tuple[str, str]] = []
        fake = operator_self(cls, report=lambda kind, text: reports.append((min(kind), text)),
                             cubication=DIRECT)
        self.panel.reset_mock()
        self.assertEqual(cls.execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual((view.cubication, view.quantities), (DIRECT, "RATIOS"))
        self.panel.assert_called_once_with(PANEL)
        listed = {item.name: (item.units, item.tonnage) for item in view.cubications}
        self.assertEqual((listed[DIRECT], listed[WITHOUT_UNITS]), ((True, True), (False, False)))
        ratios = _module("reserves.store").cubication_ratios(self.project, DIRECT,
                                                             version=self.v01.uid)
        (total,) = [item for item in ratios if item.quantity == "waste_ratio_m3"
                    and item.domain == "*" and item.bench is None]
        self.assertEqual(total.value, 12.0 / 8.0)
        self.assertEqual(reports, [("INFO", "Relación estéril/útil de «Directa»: 1,50 m³/m³ · "
                                            "1,35 t/t")])

        view.cubication = "Explotación"
        fake.cubication, reports[:] = "", []
        self.assertEqual(cls.execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual((fake.cubication, view.cubication), ("Explotación", "Explotación"))

        self.panel.reset_mock()
        fake.cubication, reports[:] = WITHOUT_UNITS, []
        self.assertEqual(cls.execute(fake, bpy.context), {"CANCELLED"})
        ((kind, text),) = reports
        self.assertEqual(kind, "WARNING")
        self.assertIn("«Sin unidades» se cubicó sin unidades: no tiene relaciones estéril/útil",
                      text)
        self.assertEqual(view.cubication, "Explotación")
        self.panel.assert_not_called()

    # --- La ventana de la cubicación y Exportar CSV… (T25) -------------------------------------

    def filtered(self, **chosen: str) -> list[Any]:
        """Las filas presentadas tras elegir en los filtros del panel (``domain``, ``bench`` o
        ``unit``) el elemento con ese texto."""
        view = self.panels.view()
        for name, text in chosen.items():
            items = getattr(self.panels, f"{name}_filter_items")(view, None)
            (identifier,) = [item[0] for item in items if item[1] == text]
            setattr(view, f"{name}_filter", identifier)
        return list(view.rows)

    @staticmethod
    def by_scope(rows: list[Any]) -> dict[tuple[str, str], Any]:
        """Las filas presentadas por (ámbito, dato)."""
        return {(row.scope, row.quantity): row for row in rows}

    def choose(self, name: str) -> None:
        """Elige la cubicación ``name`` en la lista del panel (como al pulsarla)."""
        view = self.panels.view()
        view.cubication_index = [item.name for item in view.cubications].index(name)
        self.assertEqual(view.cubication, name)

    def test_volumetrics_panel_lists_filters_and_marks(self) -> None:
        """RF-011-23 (RF-008-31, RF-009-20; plan §5.5, D-16, D-26, D-27, D-37; RNF-011-05): N ▸
        Proyecto ▸ Cubicaciones (plegado al empezar) lista las cubicaciones de la versión activa
        con su revisión («V01.r1 en curso») y, si lo está, «obsoleta»; elegida una, su tabla: un
        valor por fila con su unidad, [CAL] y sus marcas («depende de un valor sin confirmar»
        en todas, por el espesor mínimo por defecto; «depende de una hipótesis» en las t y los
        m³ esponjados, por la densidad y el K, HIPÓTESIS, no en los m³ in situ, que no se
        repiten de la tabla de toneladas); filtrada por dominio, banco y unidad (por defecto,
        los totales) y por las relaciones, sin leer el proyecto; los parámetros que usó con su
        valor, su tipo y su ámbito, y el factor combinado. Dibujar no lee el proyecto: cuando
        cambia, el panel pide leerlo en un temporizador."""
        self.stage_cubications()
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_breakdown(
            name=BENCHES, start=START, final=FINAL, domains_layer=self.phases,
            domains_field="fase", bench_height="1", bench_anchor="100,5"), {"FINISHED"})
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_category,
                          panel.bl_label, panel.bl_options),
                         ("VIEW_3D", "UI", "Proyecto", "Cubicaciones", {"DEFAULT_CLOSED"}))
        view = self.panels.view()
        found = self.panels.fill_volumetrics(self.project, self.v01.uid)
        listed = {item.name: item for item in view.cubications}
        self.assertEqual(list(listed), [item.name for item in found])
        self.assertLessEqual({*STAGE_CUBICATIONS, WITHOUT_UNITS, BENCHES}, set(listed))
        self.assertEqual({(item.status, item.revision, item.stale) for item in listed.values()},
                         {("V01.r1 en curso", "V01.r1", False)})
        for state, revision, editable, expected in (  # con revisiones congeladas (RF-009-20)
                ("open", "V01.r2", True, "V01.r2 en curso · vigente: r1"),
                ("frozen", "V01.r1", True, "V01 vigente: r1"),
                ("frozen", "V01.r1", False, "V01 congelada: r1")):
            with self.subTest(estado=state, editable=editable):
                item = SimpleNamespace(revision=revision, revision_state=state, current="r1")
                self.assertEqual(self.panels.status_text(item, editable=editable), expected)
        self.panels.show_cubication("")  # ninguna elegida
        with mock.patch.object(self.project, "read", side_effect=AssertionError("al dibujar")):
            layout = draw(panel, bpy.context, is_popover=False)
        self.assertEqual([item.target for item in layout.of_kind("template_list")],
                         ["GEOBLENDER_UL_res_cubications"])

        self.choose(DIRECT)  # los totales: todos los dominios, todas las rodajas y unidades
        rows = self.by_scope(list(view.rows))
        cut = rows[("", "cut_m3")]
        self.assertEqual((cut.name, cut.value, cut.badge, cut.marks),
                         ("Desmonte", "20 m³", "[CAL]", UNCONFIRMED))
        self.assertEqual(rows[("", "waste_ratio_m3")].value, "1,50 m³/m³")  # dos decimales
        self.assertIn(HYPOTHESIS, rows[("", "total_t")].marks)
        self.assertIn(UNCONFIRMED, rows[("", "total_t")].marks)
        unit = self.by_scope(self.filtered(unit="Capa útil"))
        self.assertEqual((unit[("Capa útil", "volume_m3")].value,
                          unit[("Capa útil", "volume_m3")].marks), ("8 m³", UNCONFIRMED))
        self.assertEqual(sum(row.quantity in ("volume_m3", "in_situ_m3") for row in view.rows), 1)
        for quantity, value in (("mass_t", "16 t"), ("swell_m3", "12 m³")):
            with self.subTest(dato=quantity):
                self.assertEqual(unit[("Capa útil", quantity)].value, value)
                self.assertIn(HYPOTHESIS, unit[("Capa útil", quantity)].marks)
        self.assertGreater(len(self.filtered(unit="Cualquier unidad")), len(unit))
        lines = [line.name for line in view.lines]
        self.assertEqual(lines[0], f"{DIRECT} · V01.r1 en curso")
        self.assertIn(f"Cubicación entre superficies (V01.r1) · {UNCONFIRMED}", lines)
        self.assertTrue(any(line.startswith("Toneladas de una cubicación (V01.r1) · ")
                            and HYPOTHESIS in line for line in lines), lines)
        self.assertTrue(any(line.startswith("Factor combinado: ") for line in lines), lines)
        label = _module("core.params").parameter_label
        parameters = [line.name for line in view.parameters]
        self.assertIn("Espesor mínimo de desmonte y terraplén: 0 m [ADO] sin confirmar · "
                      "proyecto", parameters)
        self.assertIn(f"{label('res.unit.capa_util.swell', 'es')}: 1,5 [HIP] · proyecto",
                      parameters)
        self.panels.show_cubication(DIRECT, quantities="RATIOS")  # lo que deja «Ratios…»
        ratios = {row.quantity for row in view.rows}
        self.assertIn("waste_ratio_m3", ratios)
        self.assertLessEqual(ratios, set(_module("reserves.table").RATIO_QUANTITIES))

        self.choose(BENCHES)
        self.assertEqual([item[1] for item in self.panels.domain_filter_items(view, None)],
                         ["Cualquier dominio", "Todos los dominios (total)", "Fase 1", "Fase 2",
                          "Fuera de los dominios"])
        shown = self.filtered(domain="Fase 2", bench="[100,5; 101,5) m")
        self.assertTrue(shown)
        self.assertTrue(all(row.scope == "Fase 2 · [100,5; 101,5) m" for row in shown), shown)
        (stored,) = [row for row in self.table("res_vol_fases_y_bancos")
                     if (row.domain, row.bench_z0, row.unit, row.quantity)
                     == ("Fase 2", ANCHOR_M, None, "cut_m3")]
        self.assertAlmostEqual(stored.value, sum(
            value for (domain, low, _unit), value in _breakdown_expected().items()
            if (domain, low) == ("Fase 2", ANCHOR_M)), delta=1e-9)
        self.assertEqual(self.by_scope(shown)[("Fase 2 · [100,5; 101,5) m", "cut_m3")].value,
                         _module("reserves.table").quantity_text(stored.value, "m3"))
        with mock.patch.object(self.project, "read", side_effect=AssertionError("al filtrar")):
            self.assertTrue(self.filtered(domain="Cualquier dominio"))
            layout = draw(panel, bpy.context, is_popover=False)
        self.assertEqual([item.target for item in layout.of_kind("template_list")],
                         ["GEOBLENDER_UL_res_cubications", "GEOBLENDER_UL_res_rows"])
        self.assertIn(EXPORT_CSV, [item.target for item in layout.of_kind("operator")])

        self.addCleanup(self.declare, {"res.unit.montera.density": DENSITY["montera"]})
        self.declare({"res.unit.montera.density": 1.9})  # las toneladas, obsoletas
        self.panels.on_project_read(self.project)
        if bpy.app.timers.is_registered(self.panels.volumetrics_tick):  # sin correr, en -b
            bpy.app.timers.unregister(self.panels.volumetrics_tick)
        with mock.patch.object(bpy.app.timers, "register") as timer:
            draw(panel, bpy.context, is_popover=False)
        timer.assert_called_once_with(self.panels.volumetrics_tick, first_interval=0.0)
        self.assertIsNone(self.panels.volumetrics_tick())
        listed = {item.name: item for item in view.cubications}
        self.assertEqual((listed[DIRECT].stale, listed[WITHOUT_UNITS].stale), (True, False))
        layout = FakeLayout()
        _module("bl.ui.res_panels").GEOBLENDER_UL_res_cubications.draw_item(
            None, bpy.context, layout, view, listed[DIRECT], 0, view, "cubication_index")
        self.assertIn("obsoleta", [item.text for item in layout.of_kind("label") if item.alert])

    def test_volumetrics_csv_window_read_only_and_superseded(self) -> None:
        """RF-011-23, RF-011-24 (D-29; RF-008-15): «Exportar CSV…» propone
        ``exports/<cubicación>_<revisión>.csv``, deja allí el CSV de lo registrado (con su BOM,
        para Excel en español) y, si ya existe, desde un guion lo rechaza y desde la interfaz
        pregunta si se sustituye; la ventana de la cubicación (``res_show_volumetrics``) deja
        elegida la pedida. Con el proyecto en solo lectura se ve igual y se exporta fuera del
        proyecto (en él, no); con la versión activa SUPERADO, también (su revisión, «cerrada»)."""
        self.stage_cubications()
        view = self.panels.view()
        self.panel.reset_mock()
        self.assertEqual(bpy.ops.geoblender.res_show_volumetrics(cubication=DIRECT),
                         {"FINISHED"})
        self.panel.assert_called_once_with(PANEL)
        self.assertEqual(view.cubication, DIRECT)
        self.assertTrue(len(view.rows))
        cls = self.commands.registered_class(EXPORT_CSV)
        self.assertEqual((cls.bl_options, self.commands.catalog().commands[EXPORT_CSV].entry),
                         ({"REGISTER"}, ENTRY))
        fake = operator_self(cls, report=lambda kind, text: None, cubication=DIRECT,
                             filepath="", overwrite=False, confirm=False)
        manager = SimpleNamespace(fileselect_add=mock.Mock())
        self.assertEqual(cls.invoke(fake, SimpleNamespace(window_manager=manager, window=None),
                                    None), {"RUNNING_MODAL"})
        target = Path(fake.filepath)
        self.assertEqual(target, self.project.root / "exports" / "directa_V01.r1.csv")
        self.assertEqual(bpy.ops.geoblender.res_export_csv(cubication=DIRECT,
                                                           filepath=str(target)), {"FINISHED"})
        self.assertTrue(target.read_bytes().startswith("﻿Cubicación;Directa".encode()))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.res_export_csv(cubication=DIRECT, filepath=str(target))
        self.assertIn("Ya existe «directa_V01.r1.csv»", str(caught.exception))
        asking = operator_self(cls, report=lambda kind, text: None, cubication=DIRECT,
                               filepath=str(target), overwrite=False, confirm=False,
                               interactive=True)
        with mock.patch.object(self.res_ops, "_confirm_later") as later:
            self.assertEqual(cls.execute(asking, SimpleNamespace(window=object())),
                             {"CANCELLED"})
        later.assert_called_once_with({"cubication": DIRECT, "filepath": str(target)},
                                      idname=EXPORT_CSV)
        self.assertEqual(bpy.ops.geoblender.res_export_csv(
            cubication=DIRECT, filepath=str(target), overwrite=True), {"FINISHED"})

        outside = Path(tempfile.mkdtemp(prefix="gb-r25-"))
        self.addCleanup(remove_tree, outside)
        project = self.project
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            self.assertEqual([item.name for item in self.panels.fill_volumetrics(
                project, self.v01.uid)], [item.name for item in view.cubications])
            self.panels.show_cubication(DIRECT)
            self.assertTrue(len(view.rows))
            text = self.refused(command=EXPORT_CSV, cubication=DIRECT,
                                filepath=str(project.root / "exports" / "otra.csv"))
            self.assertIn("solo lectura", text)
            self.assertEqual(bpy.ops.geoblender.res_export_csv(
                cubication=DIRECT, filepath=str(outside / "directa.csv")), {"FINISHED"})
        self.assertTrue((outside / "directa.csv").is_file())

        store = _module("core.versions.store")
        with project.write_transaction() as conn:
            v03, _revision = store.create_version(conn, project, feature="norte",
                                                  title="Fase norte", reason=REASON)
        project.refresh_header()
        self.set_active(v03)
        self.addCleanup(self.set_active, self.v01)
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name="Norte", start=START, final=FINAL, difference_grid=False), {"FINISHED"})
        with project.write_transaction() as conn:  # SUPERADO, con su revisión cerrada
            conn.execute("UPDATE gb_revision SET state = 'closed', closed_at = ?, closed_by = ? "
                         "WHERE version_uid = ? AND state = 'open'",
                         ("2026-10-24T10:00:00Z", "prueba", v03.uid))
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (v03.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE "
                         "uid = ?", (REASON, v03.uid))
        self.set_active(v03)
        self.panels.fill_volumetrics(project, v03.uid)
        self.assertEqual([(item.name, item.status) for item in view.cubications],
                         [("Norte", "V03 cerrada (r1)")])
        self.assertEqual(bpy.ops.geoblender.res_show_volumetrics(cubication="Norte"),
                         {"FINISHED"})
        self.assertEqual(self.by_scope(list(view.rows))[("", "cut_m3")].value,
                         _module("reserves.table").quantity_text(
                             _expected(_start_values(), _final_values())["res.cut_m3"], "m3"))
        self.assertEqual(bpy.ops.geoblender.res_export_csv(
            cubication="Norte", filepath=str(outside / "norte.csv")), {"FINISHED"})

    def test_volumetrics_shown_rounded_and_the_csv_complete(self) -> None:
        """RF-011-23, RF-011-24 (T34; regresión del H2, donde el panel enseñaba «91
        450,50000000001 m³» y «1,5675253987838387 m³/m³»): la tabla del panel y sus líneas (el
        factor combinado) dan cada cifra con los decimales de su unidad (m³, m² y t, sin
        decimales; las relaciones y los %, dos; el factor, seis) y el espacio fino de miles; lo
        mismo lo que dicen al terminar «Entre dos superficies…» (desmonte, terraplén y neto),
        las toneladas encadenadas y «Por momentos de extracción…». El CSV de la misma tabla
        lleva el valor completo."""
        self.stage_cubications()
        res_export, res_table = _module("reserves.export"), _module("reserves.table")
        thin = _module("core.i18n").THIN_SPACE
        long_m3 = 91_450.50000000001
        long = {"cut_m3": long_m3, "net_m3": -0.4, "area_m2": 2_812_345.678,
                "total_t": 12_345.678, "waste_ratio_m3": 1.5675253987838387,
                "grid_scale_factor": 1.0001823456, "ground_effect_pct": 0.018234}
        real = res_export.cubication_export(self.project, DIRECT, version=self.v01.uid)
        total = (res_table.ALL_DOMAINS, None, None, None)

        def longer(item: Any) -> Any:
            row = item.row
            if row.quantity not in long or (row.domain, row.bench, row.unit,
                                            row.component) != total:
                return item
            return replace(item, row=replace(row, value=long[row.quantity], note=None))

        found = replace(real, rows=tuple(longer(item) for item in real.rows))
        self.assertEqual(sum(item is not other for item, other in zip(found.rows, real.rows,
                                                                       strict=True)), len(long))
        with mock.patch.object(res_export, "cubication_export", return_value=found):
            shown = self.panels.read_table(self.project, self.v01.uid, DIRECT)
        totals = {quantity: value for (_d, _b, _u, quantity, where, _l, value, _m, _n)
                  in shown.rows if not where}
        self.assertEqual({quantity: totals[quantity] for quantity in long}, {
            "cut_m3": f"91{thin}451 m³", "net_m3": "0 m³", "area_m2": f"2{thin}812{thin}346 m²",
            "total_t": f"12{thin}346 t", "waste_ratio_m3": "1,57 m³/m³",
            "grid_scale_factor": "1,000182", "ground_effect_pct": "0,02 %"})
        lines = [text for text, _alert in shown.lines]
        self.assertIn("Factor combinado: 1,000182", lines)
        self.assertTrue(any(text.endswith(": 0,02 %") for text in lines), lines)
        for (_d, _b, _u, quantity, where, _l, value, _m, _n) in shown.rows:
            decimals = re.search(r",(\d+)", value)
            with self.subTest(dato=quantity, ambito=where):
                self.assertLessEqual(0 if decimals is None else len(decimals.group(1)),
                                     res_table.DECIMALS[res_table.QUANTITIES[quantity].unit])
        csv_values = {row[7]: row[9] for row in res_export.csv_rows(found)[-len(found.rows):]
                      if row[1] == "Todos los dominios" and not any(row[2:6])}
        self.assertEqual((csv_values["cut_m3"], csv_values["waste_ratio_m3"]),
                         ("91450,50000000001", "1,5675253987838387"))  # RF-011-24, D-29

        reports: list[str] = []
        operator = SimpleNamespace(_report=lambda _level, text: reports.append(text),
                                   _name="Larga")
        between = self.commands.registered_class(BETWEEN)
        between._report_result(operator, SimpleNamespace(result=SimpleNamespace(
            name="Larga", cut_m3=long_m3, fill_m3=12.25, net_m3=long_m3 - 12.25, warnings=())))
        between._report_tonnage(operator, SimpleNamespace(outputs=SimpleNamespace(
            result=SimpleNamespace(groups=(SimpleNamespace(domain=res_table.ALL_DOMAINS,
                                                           bench=None, total_t=12_345.678),)),
            warnings=())))
        comparison = SimpleNamespace(sum_m3=long_m3, direct_m3=90_000.0,
                                     diff_m3=long_m3 - 90_000.0,
                                     diff_pct=100.0 * (long_m3 - 90_000.0) / 90_000.0)
        self.commands.registered_class(STAGES)._report_result(operator, SimpleNamespace(
            result=SimpleNamespace(name="Larga", direct=DIRECT, warnings=(),
                                   comparison=lambda: comparison)))
        self.assertEqual(reports, [
            f"Larga (V01.r1, en curso): desmonte 91{thin}451 m³, terraplén 12 m³, neto "
            f"91{thin}438 m³",
            f"Toneladas de «Larga» (V01.r1, en curso): 12{thin}346 t",
            f"«Larga» (V01.r1, en curso): suma de los momentos 91{thin}451 m³, directa "
            f"«{DIRECT}» 90{thin}000 m³, diferencia 1{thin}451 m³ (1,61 %)"])

    # --- E5: congelar, K solo en V01 y recalcular (T26) ---------------------------------------

    def stale(self) -> dict[str, frozenset[Any]]:
        """Las operaciones obsoletas sin sustituir con sus causas (``deduce`` de la 008)."""
        graph = _module("core.provenance.graph")
        with self.project.read() as conn:
            return dict(graph.deduce(graph.load_graph(conn)).operations)

    def revision_figures(self, revision_uid: str) -> dict[str, float]:
        """Las cifras congeladas en la revisión ``revision_uid``: uid → valor."""
        return dict(self.rows(
            "SELECT f.uid, f.value FROM gb_revision_item AS i JOIN gb_figure AS f ON f.uid = "
            "i.item_uid WHERE i.revision_uid = ? AND i.item_kind = 'figure'", revision_uid))

    def listed(self, name: str) -> tuple[str, bool]:
        """La revisión como se lee y si está obsoleta la cubicación ``name`` de V01 en la lista
        del panel, leída de nuevo."""
        self.panels.fill_volumetrics(self.project, self.v01.uid)
        (found,) = [item for item in self.panels.view().cubications if item.name == name]
        return found.status, found.stale

    def test_with_v01_r1_frozen_k_only_in_v01_is_recomputed(self) -> None:
        """E5, RF-011-20, RF-011-21 (RF-008-24, RF-008-26, RF-009-07, RF-009-24, RF-009-29; plan
        A12, D-16, D-19): congelada V01.r1 con «Directa» (por unidades), «Cambiar parámetro…»
        con el K de la capa útil solo para V01 deja obsoletas las toneladas de las cubicaciones
        de V01 (ningún ``res.volume``) y el panel la marca «obsoleta» («V01 vigente: r1»).
        «Recalcular lo obsoleto» las rehace por la cola de ``res``, con su avance en la barra de
        estado: la nueva de «Directa», en la revisión abierta V01.r2, sustituye a la de V01.r1,
        lee el K de V01 y cambia sus m³ esponjados; nada queda obsoleto ni en la cola, y las
        cifras congeladas en V01.r1 siguen iguales. Va la última (orden alfabético): congela
        V01.r1 del proyecto de la clase."""
        self.stage_cubications()
        ((volume, _s, _o, _n),) = [item for item in self.operations(DIRECT) if item[3] is None]
        ((first, _s, _o, _n),) = [item for item in self.operations(DIRECT, "res.tonnage")
                                  if item[3] is None]
        freeze = _module("core.versions.freeze")
        plan = freeze.freeze_plan(self.project, self.v01.uid)
        outcome = None
        for step in freeze.freeze_steps(self.project, self.v01.uid, reason=REASON,
                                        accepted=freeze.Acceptance.of(plan)):
            outcome = step.result or outcome
        self.assertFalse(outcome.cancelled)
        r1 = str(outcome.frozen.uid)
        self.set_active(self.v01)  # la sesión lee la revisión abierta, V01.r2
        ((r2,),) = self.rows("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = "
                             "'open'", self.v01.uid)
        frozen = self.revision_figures(r1)
        self.assertTrue({uid for (uid,) in self.rows(
            "SELECT uid FROM gb_figure WHERE operation_uid = ?", first)} <= set(frozen))
        self.assertNotIn(first, self.stale())
        self.assertEqual(self.listed(DIRECT), ("V01 vigente: r1", False))

        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=SWELL_KEY, value="1,6", scope="VERSION", reason=REASON), {"FINISHED"})
        found = self.stale()
        ((own,),) = self.rows("SELECT uid FROM gb_parameter WHERE key = ? AND scope_uid = ?",
                              SWELL_KEY, self.v01.uid)
        graph = _module("core.provenance.graph")
        self.assertEqual(found[first], {graph.Cause(graph.CauseKind.PARAMETER_CHANGED, own)})
        self.assertNotIn(volume, found)  # D-16: los m³ in situ no dependen del K
        ((kinds,),) = self.rows("SELECT group_concat(DISTINCT op_type) FROM gb_operation WHERE "
                                f"uid IN ({', '.join('?' for _ in found)})", *found)
        self.assertEqual(kinds, "res.tonnage")
        self.assertEqual(self.listed(DIRECT), ("V01 vigente: r1", True))

        self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"),
                         {"RUNNING_MODAL"})
        operator = self.running(RECOMPUTE)
        self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
        with mock.patch.object(_module("bl.ops.incorporation"), "status_text") as status:
            for _ in range(MAX_EVENTS):
                if operator.modal(bpy.context, TIMER) != {"RUNNING_MODAL"}:
                    break
                self.res_ops.res_tick()  # el temporizador de la cola (en blender -b, a mano)
        self.assertEqual({str(result.status) for result in operator.result.results}, {"done"})
        self.assertTrue(operator.progress_log)
        shown = [call.args[0] for call in status.call_args_list]
        self.assertIn(f"Recalculando «{DIRECT}»… 100 %", shown)
        self.assertEqual(self.res_ops.pending_runs(), [])
        self.assertEqual(self.stale(), {})

        weighed = self.operations(DIRECT, "res.tonnage")
        ((new, done, _o, _n),) = [item for item in weighed if item[2] == first]
        self.assertEqual((done, [item[3] for item in weighed if item[0] == first]),
                         ("done", [new]))
        self.assertEqual(self.rows("SELECT revision_uid FROM gb_operation WHERE uid = ?", new),
                         [(r2,)])
        ((scope, version_uid, value),) = self.rows(
            "SELECT p.scope, g.scope_uid, p.value FROM gb_operation_param AS p JOIN "
            "gb_parameter AS g ON g.uid = p.parameter_uid WHERE p.operation_uid = ? AND "
            "p.key = ?", new, SWELL_KEY)
        self.assertEqual((scope, version_uid, json.loads(value)),
                         ("version", self.v01.uid, SWELL_V01))
        unit = {"unit": "capa_util"}
        useful = self.figures(volume, DIRECT, **unit)["res.unit_volume_m3"]
        self.assertGreater(useful, 0.0)
        self.assertAlmostEqual(self.figures(first, DIRECT, **unit)["res.unit_swell_m3"],
                               useful * SWELL, delta=1e-9)
        self.assertAlmostEqual(self.figures(new, DIRECT, **unit)["res.unit_swell_m3"],
                               useful * SWELL_V01, delta=1e-9)
        self.assertEqual(self.revision_figures(r1), frozen)
        self.assertEqual(self.listed(DIRECT), ("V01 vigente: r1", False))
        self.panels.show_cubication(DIRECT)
        lines = [line.name for line in self.panels.view().lines]
        self.assertTrue(any(line.startswith("Toneladas de una cubicación (V01.r2)")
                            for line in lines), lines)
        self.assertTrue(any(line.startswith("Cubicación entre superficies (V01.r1)")
                            for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
