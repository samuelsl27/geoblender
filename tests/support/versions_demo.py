# SPDX-License-Identifier: GPL-3.0-or-later
"""Demostración de versiones, «demo» (spec 009, T08; plan 009 §5.3.3 y §7.1).

Amplía la demostración de la procedencia de la 008 (:class:`~tests.support.provenance_demo.Demo`,
que registra entera) con los tipos de **versión** del código ``demo``, declarados como lo hará un
módulo de Geoblender que trabaja por versiones (la cubicación, el diseño; plan §5.3.3):
``OperationDef(scope="version")``, el parámetro de versión ``ParamDef(scope="version")``, la
función de reproducir y la tolerancia de las cifras al reproducir. Sus operaciones se registran
en la revisión abierta de la versión que se les pasa (``core.provenance.operations``, A3) y sus
salidas son datos de esa versión, con el código de la versión en la ubicación
(``core.versions.model.version_locator``, D-34: ``rasters/demo_pit_grid_v01.tif``).

- ``demo.pit`` (:meth:`VersionsDemo.pit`; se repite sola y se reproduce): el hueco sobre el
  límite importado (un dato del proyecto, papel ``boundary``) con la altura de banco
  ``demo.bench_height`` (m, de versión: cada versión puede tener la suya; si no, la del
  proyecto). La rejilla del fondo cubre la extensión del límite con celdas de ``step_m``; la
  celda cuyo centro está a ``d`` m del borde baja ``min(benches, ⌊d / berm_m⌋)`` bancos desde
  ``top_z``. Escribe la rejilla (GeoTIFF del perfil ``project`` de la 006, ``rasters/``), su
  malla (npz de ``meshes/``: los centros con su cota y dos triángulos por cuadro) y la tabla de
  sus bancos (``demo_pit_benches``: banco, cota del fondo, área en m² y volumen en m³). Sobre
  ``Limites_v1`` (500 × 350 m) con las opciones por defecto: 1 750 celdas, 3 182 celdas·banco;
- ``demo.pit_volume`` (se repite y se reproduce): lee la rejilla del hueco y da la cifra
  ``demo.pit_volume`` (m³), lo excavado bajo su borde (la cota más alta), con
  ``figure_tolerance`` relativa :data:`FIGURE_TOLERANCE`. Con 12 m, 3 818 400 m³;
- ``demo.sketch`` (edición a mano: no se repite ni se reproduce; al reproducir se toma lo
  congelado): las rampas que dibuja una persona (líneas en el CRS del proyecto, ``ramp`` y
  ``bench``) en una capa **editable en QGIS** de su versión, sobre la tabla de bancos (papel
  ``pit``): si esta cambia, queda «revisar a mano» (RF-008-27);
- ``demo.design_from_parent`` (se repite y se reproduce): lee la tabla de bancos **congelada**
  en la revisión de la que parte su versión (``Use(…, frozen=<revisión>)``, D-27) y escribe
  ``demo_design``, los bancos con su área y su volumen por ``widening``. Lo congelado se lee del
  dato vivo si aún tiene el contenido congelado y, si no, de la copia de su instantánea
  (``gb_revision_item.snapshot_path`` y ``snapshot_layer``); si no está en ninguno, error;
- ``demo.pit_stockpiles`` (se repite y se reproduce; spec 009, T10): sitúa los acopios del
  **proyecto** (``demo_stockpiles``, lo derivado de la cadena de la 008: filtrar, detectar, los
  años por banco y lo dibujado a mano) en el fondo del primer banco del hueco de su versión
  (``demo_pit_benches``) y escribe ``demo_pit_stockpiles`` (marca, volumen esponjado en m³ y
  cota). Es lo que tiene, aguas arriba, datos derivados del proyecto (plan A5).

**Reproducir** (spec 009, T15; ``core.versions.reproduce``). La función de reproducir de los
tipos que se repiten (``OperationDef.reproduce``) hace lo mismo que su cuerpo, con las entradas
y los parámetros congelados que recibe (``ReproduceRequest``) y sin el proyecto: lee cada
entrada de su fichero (la rejilla de la instantánea, la tabla de su GeoPackage, lo importado
copiado a ``entradas.gpkg``), escribe en su carpeta de trabajo (la rejilla, la malla y cada
tabla en un GeoPackage propio) y da sus salidas, con su papel, y sus cifras
(``ReproducedResult``). ``demo.sketch`` no la tiene: se toma lo congelado.

**Lo que registra además.** El lector de GeoTIFF de ``gis`` (``gis.geotiff@1``, el de las
rejillas de ``rasters/``) si no está registrado (lo registra ``bl/ops/gis.py``), y lo quita al
irse; nada más de ``gis``. Como la de la 008, se registra y se quita sin dejar rastro, no se
empaqueta (vive en ``tests/support/``) y sus datos son sintéticos. Fuera de Blender, con el
paquete de las pruebas; dentro, con el nombre del paquete de la extensión instalada.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.provenance_demo import DEMO_CODE, LABELS_ES, STOCKPILES_TABLE, Demo

PIT = "demo.pit"
PIT_VOLUME = "demo.pit_volume"
SKETCH = "demo.sketch"
DESIGN_FROM_PARENT = "demo.design_from_parent"
PIT_STOCKPILES = "demo.pit_stockpiles"
VERSION_TYPES: tuple[str, ...] = (PIT, PIT_VOLUME, SKETCH, DESIGN_FROM_PARENT, PIT_STOCKPILES)
"""Los tipos de versión de la demostración, en su orden de registro."""

BENCH_HEIGHT = "demo.bench_height"
"""El parámetro de versión (D-19): la altura de banco del hueco (m)."""
PIT_VOLUME_FIGURE = "demo.pit_volume"
FIGURE_TOLERANCE = 1e-12
"""La tolerancia relativa de ``demo.pit_volume`` al reproducir (plan §7.1)."""

PIT_GRID = "demo_pit_grid"
PIT_MESH = "demo_pit_mesh"
PIT_BENCHES = "demo_pit_benches"
SKETCH_LAYER = "demo_sketch"
DESIGN_TABLE = "demo_design"
PIT_STOCKPILES_TABLE = "demo_pit_stockpiles"
GRID_LOCATOR = f"rasters/{PIT_GRID}.tif"
MESH_LOCATOR = f"meshes/{PIT_MESH}.npz"
"""Las ubicaciones sin versión: la de cada dato lleva el código de su versión (D-34)."""

BENCHES = 3
BERM_M = 25.0
STEP_M = 10.0
TOP_Z = 500.0
"""Las opciones por defecto de ``demo.pit``: bancos, berma (m), paso de la rejilla (m) y cota
del borde (m, en la referencia vertical del proyecto)."""
WIDENING = 1.1
"""Lo que ensancha ``demo.design_from_parent`` el área y el volumen de cada banco."""
DEFAULT_RAMPS: tuple[tuple[str, int, tuple[tuple[float, float], ...]], ...] = (
    ("R-1", 1, ((700_030.25, 4_400_030.5), (700_230.25, 4_400_030.5))),
    ("R-2", 2, ((700_470.25, 4_400_060.5), (700_470.25, 4_400_290.5))),
)
"""Las rampas que dibuja la persona por defecto: rampa, banco y vértices (m, EPSG:25830,
dentro de ``Limites_v1``)."""

MODULES: tuple[str, ...] = (
    "core.content.builtin",
    "core.content.readers",
    "core.datasets.model",
    "core.datasets.registry",
    "core.georef.crs",
    "core.gpkg",
    "core.gpkg.base",
    "core.gpkg.connection",
    "core.gpkg.wkb",
    "core.i18n",
    "core.params",
    "core.project.model",
    "core.provenance.contract",
    "core.provenance.figures",
    "core.provenance.operations",
    "core.units",
    "core.versions.model",
    "core.versions.read",
    "core.versions.reproduce",
    "gis.content",
    "gis.geotiff.reader",
    "gis.geotiff.writer",
    "gis.grid",
    "gis.raster",
    "gis.store",
)
"""Los módulos de Geoblender que usa la demostración de versiones (los importa quien quiera
tenerlos cargados antes de comparar el estado del proceso)."""

VERSION_LABELS_ES: Mapping[str, str] = {
    "Demo design pit": "Diseñar el hueco (demostración)",
    "Demo compute pit volume": "Calcular el volumen del hueco (demostración)",
    "Demo sketch ramps": "Dibujar las rampas (demostración)",
    "Demo design from parent": "Diseñar desde la versión padre (demostración)",
    "Demo place stockpiles in pit": "Situar los acopios en el hueco (demostración)",
    "Demo pit volume": "Volumen del hueco (demostración)",
    "Demo bench height": "Altura de banco (demostración)",
}
"""Las etiquetas de los tipos de versión (``msgid`` en inglés → español)."""

_BENCH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bench", "INTEGER"), ("floor_z", "DOUBLE"), ("area_m2", "DOUBLE"), ("volume_m3", "DOUBLE"))
_SKETCH_COLUMNS: tuple[tuple[str, str], ...] = (("ramp", "TEXT"), ("bench", "INTEGER"))
_STOCKPILE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("mark", "TEXT"), ("loose_m3", "DOUBLE"), ("floor_z", "DOUBLE"))
_TITLES: Mapping[str, str] = {
    PIT_BENCHES: "Bancos del hueco (demostración)",
    SKETCH_LAYER: "Rampas (demostración)",
    DESIGN_TABLE: "Diseño desde la padre (demostración)",
    PIT_STOCKPILES_TABLE: "Acopios en el hueco (demostración)",
}
"""El identificador de cada tabla en ``gpkg_contents`` (único: se le añade el código de la
versión)."""


def _count(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{what} es un entero mayor que cero, no {value!r}")
    return value


def _positive(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{what} es un número finito mayor que cero, no {value!r}")
    return number


def _finite(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(
            float(value)):
        raise ValueError(f"{what} es un número finito, no {value!r}")
    return float(value)


def pit_depths(extent: tuple[float, float, float, float], *, benches: int, berm_m: float,
               step_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """La rejilla del hueco sobre ``extent`` (xmin, ymin, xmax, ymax; m): los centros de celda
    ``(x, y)`` absolutos (float64, fila 0 al norte) y los bancos que baja cada celda (enteros):
    ``min(benches, ⌊d / berm_m⌋)``, con ``d`` la distancia de su centro al borde de la
    extensión."""
    west, south, east, north = extent
    ncols = math.ceil((east - west) / step_m)
    nrows = math.ceil((north - south) / step_m)
    x = west + (np.arange(ncols, dtype=np.float64) + 0.5) * step_m
    y = north - (np.arange(nrows, dtype=np.float64) + 0.5) * step_m
    xx, yy = np.meshgrid(x, y)
    edge = np.minimum(np.minimum(xx - west, east - xx), np.minimum(yy - south, north - yy))
    down = np.minimum(benches, np.floor(edge / berm_m)).astype(np.int64)
    return xx, yy, down


def mesh_arrays(xx: np.ndarray, yy: np.ndarray, z: np.ndarray) -> dict[str, np.ndarray]:
    """La malla de una rejilla: sus centros con su cota (``vertices``, float64 absolutos, fila
    a fila) y dos triángulos por cuadro de cuatro centros (``faces``, int32)."""
    nrows, ncols = z.shape
    vertices = np.column_stack((xx.ravel(), yy.ravel(), z.ravel())).astype(np.float64)
    index = np.arange(nrows * ncols, dtype=np.int64).reshape(nrows, ncols)
    a = index[:-1, :-1].ravel()
    b = index[1:, :-1].ravel()
    c = index[:-1, 1:].ravel()
    d = index[1:, 1:].ravel()
    faces = np.concatenate((np.column_stack((a, b, c)), np.column_stack((c, b, d))))
    return {"vertices": vertices, "faces": faces.astype(np.int32)}


class VersionsDemo(Demo):
    """La demostración de la 008 y los tipos de versión (véase el módulo) sobre el paquete
    ``package`` de Geoblender (``None``: el de las pruebas sin Blender). Las órdenes de versión
    reciben la versión (uid o código) en que se registran y devuelven su ``OperationHandle``."""

    def __init__(self, package: str | None = None) -> None:
        super().__init__(package)
        self._bodies = {
            **self._bodies,
            PIT: self._pit,
            PIT_VOLUME: self._pit_volume,
            SKETCH: self._sketch,
            DESIGN_FROM_PARENT: self._design,
            PIT_STOCKPILES: self._pit_stockpiles,
        }
        self._again: Mapping[str, Callable[[Any], Any]] = {
            PIT: self._pit_again,
            PIT_VOLUME: self._pit_volume_again,
            DESIGN_FROM_PARENT: self._design_again,
            PIT_STOCKPILES: self._pit_stockpiles_again,
        }

    def __repr__(self) -> str:
        return (f"<VersionsDemo {self.package} "
                f"{'registrada' if self.active else 'sin registrar'}>")

    # --- Registro ---------------------------------------------------------------------------

    def _register_core(self) -> None:
        super()._register_core()
        readers = self.module("core.content.readers")
        geotiff = self.module("gis.content").GEOTIFF
        if geotiff.id not in readers.READERS:
            readers.register_reader(geotiff)
            self._undo.append(self._unregister_if(readers.READERS, geotiff.id, geotiff,
                                                  readers.unregister_reader))

    def _parameters(self) -> tuple[Any, ...]:
        params = self.module("core.params")
        return (*super()._parameters(), params.ParamDef(
            BENCH_HEIGHT, "float", "m", 10.0, 0.0, 50.0, ("RF-009-24",),
            "Demostración: altura de banco del diseño", min_exclusive=True, kind="HIPÓTESIS",
            source_kind="document", scope="version", label_msgid="Demo bench height",
        ))

    def _operations(self) -> tuple[Any, ...]:
        contract = self.module("core.provenance.contract")
        redo = self._recompute
        again = self._reproduce
        return (
            *super()._operations(),
            contract.OperationDef(PIT, "1.0", DEMO_CODE, "Demo design pit", True,
                                  scope="version", recompute=redo, reproduce=again),
            contract.OperationDef(PIT_VOLUME, "1.0", DEMO_CODE, "Demo compute pit volume", True,
                                  scope="version", recompute=redo, reproduce=again,
                                  figure_tolerance=contract.Tolerance(
                                      relative=FIGURE_TOLERANCE)),
            contract.OperationDef(SKETCH, "1.0", DEMO_CODE, "Demo sketch ramps", False,
                                  scope="version"),
            contract.OperationDef(DESIGN_FROM_PARENT, "1.0", DEMO_CODE,
                                  "Demo design from parent", True, scope="version",
                                  recompute=redo, reproduce=again),
            contract.OperationDef(PIT_STOCKPILES, "1.0", DEMO_CODE,
                                  "Demo place stockpiles in pit", True, scope="version",
                                  recompute=redo, reproduce=again),
        )

    def _figures(self) -> tuple[Any, ...]:
        contract = self.module("core.provenance.contract")
        return (*super()._figures(),
                contract.FigureDef(PIT_VOLUME_FIGURE, "m3", "Demo pit volume"))

    def _install_labels(self) -> None:
        i18n = self.module("core.i18n")
        installed = i18n._STATE.installed  # sin API para quitar: se deja como estaba
        labels = {**LABELS_ES, **VERSION_LABELS_ES}
        previous = {msgid: installed.get(msgid) for msgid in labels}
        i18n.install(labels)

        def restore() -> None:
            for msgid, text in previous.items():
                if text is None:
                    installed.pop(msgid, None)
                else:
                    installed[msgid] = text

        self._undo.append(restore)

    def _reproduce(self, request: Any) -> Iterator[Any]:
        """La función de reproducir de los tipos de versión (véase el módulo): lo mismo que su
        cuerpo con lo congelado de ``request`` (``ReproduceRequest``); un paso, con el
        ``ReproducedResult``."""
        result = self._again[request.op_type](request)
        yield self.module("core.project.model").Progress(
            "reproducción", 1, 1, f"«{request.op_type}» vuelta a ejecutar", result)

    # --- Órdenes de versión -----------------------------------------------------------------

    def pit(self, project: Any, version: str | None, *, boundary: str | None = None,
            benches: int = BENCHES, berm_m: float = BERM_M, step_m: float = STEP_M,
            top_z: float = TOP_Z) -> Any:
        """``demo.pit`` en ``version`` sobre el límite ``boundary`` (nombre o uid de lo
        importado; por defecto, el último importado vivo)."""
        settings = {"benches": _count(benches, "el número de bancos"),
                    "berm_m": _positive(berm_m, "la berma"),
                    "step_m": _positive(step_m, "el paso de la rejilla"),
                    "top_z": _finite(top_z, "la cota del borde")}
        if boundary is None:
            boundary = self.boundary_name(project)
            if boundary is None:
                raise ValueError("no hay ningún límite importado: impórtelo antes "
                                 "(import_boundary)")
        return self._run_version(project, PIT, version, settings=settings,
                                 inputs=self.version_uses(PIT, boundary=boundary),
                                 params=(BENCH_HEIGHT,))

    def pit_volume(self, project: Any, version: str | None) -> Any:
        """``demo.pit_volume`` en ``version``: el volumen de su rejilla del hueco."""
        return self._run_version(project, PIT_VOLUME, version,
                                 inputs=self.version_uses(PIT_VOLUME))

    def sketch(self, project: Any, version: str | None, *,
               ramps: Sequence[tuple[str, int, Sequence[Sequence[float]]]] = DEFAULT_RAMPS
               ) -> Any:
        """``demo.sketch`` en ``version``: las rampas ``ramps`` (rampa, banco y vértices en el
        CRS del proyecto) que dibuja una persona sobre la tabla de bancos de su versión."""
        settings = {"ramps": [[str(ramp), _count(bench, f"el banco de «{ramp}»"),
                               [[_finite(x, "una coordenada"), _finite(y, "una coordenada")]
                                for x, y in line]] for ramp, bench, line in ramps]}
        return self._run_version(project, SKETCH, version, settings=settings,
                                 inputs=self.version_uses(SKETCH))

    def design_from_parent(self, project: Any, version: str | None, *, frozen: str,
                           widening: float = WIDENING) -> Any:
        """``demo.design_from_parent`` en ``version`` con la tabla de bancos congelada en la
        revisión ``frozen`` (la de la que parte ``version``)."""
        settings = {"widening": _positive(widening, "el ensanche")}
        return self._run_version(project, DESIGN_FROM_PARENT, version, settings=settings,
                                 inputs=self.version_uses(DESIGN_FROM_PARENT, frozen=frozen))

    def pit_stockpiles(self, project: Any, version: str | None) -> Any:
        """``demo.pit_stockpiles`` en ``version``: los acopios del proyecto en el fondo del
        primer banco de su hueco."""
        return self._run_version(project, PIT_STOCKPILES, version,
                                 inputs=self.version_uses(PIT_STOCKPILES))

    def version_uses(self, op_type: str, *, boundary: str | None = None,
                     frozen: str | None = None) -> tuple[Any, ...]:
        """Lo que consume un tipo de versión (``Use``): ``demo.pit``, el límite
        (``boundary``); ``demo.design_from_parent``, la revisión congelada (``frozen``);
        ``demo.pit_stockpiles``, los acopios del proyecto y los bancos de su versión."""
        use = self.module("core.provenance.operations").Use
        if op_type == PIT:
            if boundary is None:
                raise ValueError("el hueco necesita el límite: el nombre o el uid de lo "
                                 "importado")
            return (use(boundary, "boundary"),)
        if op_type == DESIGN_FROM_PARENT:
            if frozen is None:
                raise ValueError("el diseño desde la padre necesita la revisión congelada")
            return (use(PIT_BENCHES, "parent_pit", frozen=frozen),)
        return {PIT_VOLUME: (use(PIT_GRID, "pit_grid"),),
                SKETCH: (use(PIT_BENCHES, "pit"),),
                PIT_STOCKPILES: (use(STOCKPILES_TABLE, "stockpiles"),
                                 use(PIT_BENCHES, "pit"))}[op_type]

    # --- Ejecución --------------------------------------------------------------------------

    def run_body(self, handle: Any) -> None:
        """El cuerpo del tipo de ``handle`` sobre una operación ya empezada por otro (una orden
        de Blender que la empieza con ``ProvenanceAwareOperator.begin``; spec 009, T20): calcula,
        escribe sus salidas y la completa, como las órdenes de la demostración."""
        if not self.active:
            raise RuntimeError("la demostración no está registrada (register)")
        self._bodies[handle.op_type](handle)

    def _run_version(self, project: Any, op_type: str, version: str | None, *,
                     settings: Mapping[str, Any] | None = None, inputs: Sequence[Any] = (),
                     params: Sequence[str] = ()) -> Any:
        if not self.active:
            raise RuntimeError("la demostración no está registrada (register)")
        operations = self.module("core.provenance.operations")
        with operations.operation(project, op_type, settings=dict(settings or {}),
                                  inputs=list(inputs), params=list(params),
                                  version=version) as handle:
            self._bodies[op_type](handle)
        return handle

    def _code(self, conn: sqlite3.Connection, handle: Any) -> str:
        """El código de la versión de la operación ``handle`` (``V01``)."""
        found = self.module("core.versions.read").version(conn, handle.version_uid)
        if found is None:
            raise ValueError(f"la operación «{handle.op_type}» no es de una versión")
        return str(found.code)

    def _record(self, conn: sqlite3.Connection, handle: Any, role: str) -> Any:
        """El registro del dato que consume ``handle`` con el papel ``role``."""
        (item,) = [item for item in handle.inputs if item.role == role]
        found = self.module("core.datasets.registry").get(conn, item.uid)
        if found is None:
            raise ValueError(f"«{item.name}» no está en el proyecto")
        return found

    def _version_spec(self, name: str, kind: str, store: str, locator: str, role: str, *,
                      reader: str, crs_epsg: int | None = None, editable: bool = False) -> Any:
        return self.module("core.datasets.model").DatasetSpec(
            name, DEMO_CODE, kind, store, locator, reader=reader, role=role, crs_epsg=crs_epsg,
            qgis_editable=editable)

    def _table_spec(self, name: str, locator: str, role: str, *, kind: str = "table",
                    crs_epsg: int | None = None, editable: bool = False) -> Any:
        reader = self.module("core.content.builtin").GPKG_LAYER.id
        return self._version_spec(name, kind, "gpkg", locator, role, reader=reader,
                                  crs_epsg=crs_epsg, editable=editable)

    def _clear_or_create(self, conn: sqlite3.Connection, name: str, locator: str, code: str,
                         create: Callable[[str], None]) -> None:
        """Vacía la tabla ``locator`` o, si no existe, la crea con ``create(identificador)``."""
        exists = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                              (locator,)).fetchone()
        if exists is None:
            create(f"{_TITLES[name]} {code}")
        else:
            conn.execute(f'DELETE FROM "{locator}"')

    def _write_rows(self, conn: sqlite3.Connection, name: str, locator: str, code: str,
                    rows: Sequence[Sequence[Any]]) -> None:
        """La tabla de bancos ``locator`` (de ``name``) con exactamente ``rows``."""
        base = self.module("core.gpkg.base")
        self._clear_or_create(conn, name, locator, code, lambda title: base.create_attribute_table(
            conn, locator, [base.ColumnDef(column, kind) for column, kind in _BENCH_COLUMNS],
            title, "Tabla sintética de la demostración de versiones (spec 009)"))
        conn.executemany(f'INSERT INTO "{locator}" (bench, floor_z, area_m2, volume_m3) '
                         "VALUES (?, ?, ?, ?)", [tuple(row) for row in rows])

    def _extent(self, conn: sqlite3.Connection, record: Any,
                crs_epsg: int) -> tuple[float, float, float, float]:
        """La extensión (xmin, ymin, xmax, ymax) de los polígonos del límite ``record``, que
        tiene que estar en el CRS del proyecto (``crs_epsg``; nunca se supone)."""
        return self._extent_of(conn, record.locator, record.name, record.crs_epsg, crs_epsg)

    def _extent_of(self, conn: sqlite3.Connection, layer: str, name: str,
                   layer_epsg: int | None, crs_epsg: int) -> tuple[float, float, float, float]:
        """La extensión de los polígonos de la capa ``layer`` (del dato ``name``, en
        ``layer_epsg``) de la base ``conn``: la del proyecto o una copia congelada."""
        if layer_epsg != crs_epsg:
            raise ValueError(f"«{name}» está en EPSG:{layer_epsg}, no en el CRS del "
                             f"proyecto (EPSG:{crs_epsg}): el hueco se calcula en este")
        wkb = self.module("core.gpkg.wkb")
        row = conn.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
                           (layer,)).fetchone()
        if row is None:
            raise ValueError(f"«{name}» no es una capa de entidades")
        xs: list[float] = []
        ys: list[float] = []
        for (blob,) in conn.execute(f'SELECT "{row[0]}" FROM "{layer}" '
                                    f'WHERE "{row[0]}" IS NOT NULL'):
            geometry = wkb.decode_geometry(blob)
            if geometry.geometry_type == "POLYGON":
                polygons = [geometry.coords]
            elif geometry.geometry_type == "MULTIPOLYGON":
                polygons = list(geometry.coords)
            else:
                raise ValueError(f"«{name}» tiene una geometría "
                                 f"{geometry.geometry_type}: el límite es de polígonos")
            for exterior, *_holes in polygons:
                xs.extend(float(point[0]) for point in exterior)
                ys.extend(float(point[1]) for point in exterior)
        if not xs:
            raise ValueError(f"«{name}» no tiene ningún polígono")
        return min(xs), min(ys), max(xs), max(ys)

    def _place(self, handle: Any, locator: str) -> tuple[Path, Path]:
        """La ruta de ``locator`` y su temporal, reclamadas por la operación."""
        final = Path(handle.project.root, *locator.split("/"))
        temporary = final.with_name(final.name + ".tmp")
        handle.claim_paths(final, temporary)
        final.parent.mkdir(parents=True, exist_ok=True)
        return final, temporary

    def _pit(self, handle: Any) -> None:
        units = self.module("core.units")
        gis_store = self.module("gis.store")
        settings = handle.settings
        (param,) = [param for param in handle.params if param.key == BENCH_HEIGHT]
        bench_m = float(units.convert(param.value, param.unit, "m"))
        project = handle.project
        crs, vertical = gis_store.project_references(project)
        with project.read() as conn:
            code = self._code(conn, handle)
            extent = self._extent(conn, self._record(conn, handle, "boundary"), crs.epsg)
        locate = self.module("core.versions.model").version_locator
        grid_path, _ = self._place(handle, locate(GRID_LOCATOR, code))
        mesh_path, mesh_temporary = self._place(handle, locate(MESH_LOCATOR, code))
        rows = self._write_pit(extent, settings, bench_m, crs, vertical, grid_path, mesh_path,
                               mesh_temporary)
        reader = self.module("gis.content").GEOTIFF.id
        mesh_reader = self.module("core.content.builtin").NPZ_MESH.id
        table = locate(PIT_BENCHES, code)
        with project.write_transaction() as conn:
            self._write_rows(conn, PIT_BENCHES, table, code, rows)
            handle.complete(conn, outputs=[
                self._version_spec(PIT_GRID, "raster", "rasters", locate(GRID_LOCATOR, code),
                                   "pit_grid", reader=reader, crs_epsg=crs.epsg),
                self._version_spec(PIT_MESH, "mesh", "meshes", locate(MESH_LOCATOR, code),
                                   "pit_mesh", reader=mesh_reader, crs_epsg=crs.epsg),
                self._table_spec(PIT_BENCHES, table, "pit"),
            ])

    def _write_pit(self, extent: tuple[float, float, float, float], settings: Mapping[str, Any],
                   bench_m: float, crs: Any, vertical: Any, grid_path: Path, mesh_path: Path,
                   mesh_temporary: Path) -> list[tuple[int, float, float, float]]:
        """Escribe la rejilla y la malla del hueco sobre ``extent`` con los ajustes de
        ``demo.pit`` y bancos de ``bench_m`` m, y devuelve las filas de su tabla de bancos."""
        step = float(settings["step_m"])
        xx, yy, down = pit_depths(extent, benches=int(settings["benches"]),
                                  berm_m=float(settings["berm_m"]), step_m=step)
        top = float(settings["top_z"])
        z = top - bench_m * down.astype(np.float64)
        grid = self.module("gis.grid").Grid(extent[0], extent[3], step, step, z.shape[1],
                                            z.shape[0])
        raster = self.module("gis.raster").Raster(grid, z, crs, vertical)
        writer = self.module("gis.geotiff.writer")
        writer.write_geotiff(raster, grid_path, profile="project",
                             temporary=writer.temporary_path(grid_path))
        meta = {"schema": 1, "kind": "surface", "closed": False, "crs_epsg": crs.epsg}
        with mesh_temporary.open("wb") as stream:
            np.savez(stream, **mesh_arrays(xx, yy, z),
                     meta=np.array(json.dumps(meta, ensure_ascii=False)))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(mesh_temporary, mesh_path)
        cell = grid.cell_area
        rows = []
        for level in range(1, int(settings["benches"]) + 1):
            area = float(np.count_nonzero(down >= level)) * cell
            rows.append((level, top - level * bench_m, area, bench_m * area))
        return rows

    def _volume(self, path: Path) -> float:
        """El volumen (m³) excavado bajo el borde (la cota más alta) de la rejilla ``path``."""
        reader = self.module("gis.geotiff.reader")
        source = reader.read_geotiff(path, max_cells=source_cells(path, reader))
        values = source.values[np.isfinite(source.values)]
        rim = float(values.max())
        return math.fsum((rim - values).tolist()) * source.grid.cell_area

    def _pit_volume(self, handle: Any) -> None:
        figures = self.module("core.provenance.figures")
        project = handle.project
        with project.read() as conn:
            record = self._record(conn, handle, "pit_grid")
        volume = self._volume(Path(project.root, *record.locator.split("/")))
        with project.write_transaction() as conn:
            handle.complete(conn, figures=[figures.FigureSpec(PIT_VOLUME_FIGURE, volume, "m3")])

    def _sketch(self, handle: Any) -> None:
        base = self.module("core.gpkg.base")
        gpkg = self.module("core.gpkg")
        project = handle.project
        epsg = int(project.record.crs_epsg)
        ramps = handle.settings["ramps"]
        with project.write_transaction() as conn:
            code = self._code(conn, handle)
            self._record(conn, handle, "pit")  # lo que lee: tiene que estar
            layer = self.module("core.versions.model").version_locator(SKETCH_LAYER, code)
            self._clear_or_create(conn, SKETCH_LAYER, layer, code, lambda title: (
                base.create_feature_table(
                    conn, layer, "LINESTRING", epsg, False,
                    [base.ColumnDef(column, kind) for column, kind in _SKETCH_COLUMNS], title,
                    "Capa sintética de la demostración de versiones (spec 009)")))
            conn.executemany(
                f'INSERT INTO "{layer}" (geom, ramp, bench) VALUES (?, ?, ?)',
                [(gpkg.encode_geometry("LINESTRING", [[float(x), float(y)] for x, y in line],
                                       epsg, False), ramp, bench)
                 for ramp, bench, line in ramps])
            handle.complete(conn, outputs=[self._table_spec(
                SKETCH_LAYER, layer, "ramps", kind="vector", crs_epsg=epsg, editable=True)])

    def frozen_rows(self, project: Any, item: Any) -> list[tuple[Any, ...]]:
        """Las filas de la tabla de bancos ``item`` (un ``Consumed`` con ``frozen``) con el
        contenido congelado: del dato vivo si aún lo tiene; si no, de la copia de su
        instantánea. ``ValueError`` si no está en ninguno."""
        columns = ", ".join(column for column, _kind in _BENCH_COLUMNS)
        with project.read() as conn:
            record = self.module("core.datasets.registry").get(conn, item.uid)
            if record is not None and record.content_sha256 == item.content_sha256:
                return conn.execute(f'SELECT {columns} FROM "{record.locator}" '
                                    "ORDER BY fid").fetchall()
            found = conn.execute(
                "SELECT i.snapshot_path, i.snapshot_layer, r.number, v.code "
                "FROM gb_revision_item AS i JOIN gb_revision AS r ON r.uid = i.revision_uid "
                "JOIN gb_version AS v ON v.uid = r.version_uid WHERE i.revision_uid = ? "
                "AND i.item_kind = 'dataset' AND i.item_uid = ?",
                (item.frozen, item.uid)).fetchone()
        label = item.frozen if found is None else f"{found[3]}.r{found[2]}"
        if found is not None and found[0] and found[1]:
            path = Path(project.root, *str(found[0]).split("/"))
            if path.is_file():
                snapshot = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
                try:
                    return snapshot.execute(f'SELECT {columns} FROM "{found[1]}" '
                                            "ORDER BY fid").fetchall()
                finally:
                    snapshot.close()
        raise ValueError(f"«{item.name}» congelado en {label} no está ni en el dato vivo (cambió "
                         "después) ni en la copia de su instantánea")

    def _design(self, handle: Any) -> None:
        widening = float(handle.settings["widening"])
        (item,) = [item for item in handle.inputs if item.role == "parent_pit"]
        rows = [(bench, floor, area * widening, volume * widening)
                for bench, floor, area, volume in self.frozen_rows(handle.project, item)]
        with handle.project.write_transaction() as conn:
            code = self._code(conn, handle)
            table = self.module("core.versions.model").version_locator(DESIGN_TABLE, code)
            self._write_rows(conn, DESIGN_TABLE, table, code, rows)
            handle.complete(conn, outputs=[self._table_spec(DESIGN_TABLE, table, "design")])

    def _pit_stockpiles(self, handle: Any) -> None:
        base = self.module("core.gpkg.base")
        project = handle.project
        with project.write_transaction() as conn:
            code = self._code(conn, handle)
            piles = self._record(conn, handle, "stockpiles")
            benches = self._record(conn, handle, "pit")
            (floor,) = conn.execute(f'SELECT floor_z FROM "{benches.locator}" '
                                    "ORDER BY bench LIMIT 1").fetchone()
            rows = [(str(mark), float(loose), float(floor)) for mark, loose in conn.execute(
                f'SELECT mark, loose_m3 FROM "{piles.locator}" ORDER BY fid')]
            table = self.module("core.versions.model").version_locator(PIT_STOCKPILES_TABLE,
                                                                          code)
            self._clear_or_create(
                conn, PIT_STOCKPILES_TABLE, table, code, lambda title: base.create_attribute_table(
                    conn, table,
                    [base.ColumnDef(column, kind) for column, kind in _STOCKPILE_COLUMNS], title,
                    "Tabla sintética de la demostración de versiones (spec 009)"))
            conn.executemany(f'INSERT INTO "{table}" (mark, loose_m3, floor_z) VALUES (?, ?, ?)',
                             rows)
            handle.complete(conn, outputs=[self._table_spec(PIT_STOCKPILES_TABLE, table,
                                                            "pit_stockpiles")])

    # --- Reproducir (spec 009, T15) ---------------------------------------------------------

    @staticmethod
    @contextmanager
    def _frozen(item: Any) -> Iterator[sqlite3.Connection]:
        """Una conexión de solo lectura (no crea nada) al GeoPackage de la entrada congelada
        ``item`` (``FrozenInput``); se cierra al salir (si no, su carpeta no se podría borrar)."""
        conn = sqlite3.connect(f"{Path(item.files['main']).as_uri()}?mode=ro", uri=True)
        try:
            yield conn
        finally:
            conn.close()

    def _rows(self, item: Any, columns: Sequence[str]) -> list[tuple[Any, ...]]:
        """Las filas de ``columns`` de la tabla de la entrada congelada ``item``, por su
        ``fid``."""
        with self._frozen(item) as conn:
            return conn.execute(f'SELECT {", ".join(columns)} FROM "{item.settings["layer"]}" '
                                "ORDER BY fid").fetchall()

    def _reproduced_table(self, request: Any, name: str, role: str,
                          columns: Sequence[tuple[str, str]],
                          rows: Sequence[Sequence[Any]]) -> Any:
        """La tabla ``name`` con ``rows`` en un GeoPackage propio de la carpeta de trabajo de
        ``request``, como salida reproducida con el papel ``role``."""
        base = self.module("core.gpkg.base")
        connection = self.module("core.gpkg.connection")
        reproduce = self.module("core.versions.reproduce")
        crs, _vertical = request.references()
        path = Path(request.workdir) / f"{role}.gpkg"
        with connection.GpkgConnection.open_write(path, create=True) as gpkg:
            with gpkg.transaction() as conn:
                base.create_base(conn, crs)
                base.create_attribute_table(
                    conn, name, [base.ColumnDef(column, kind) for column, kind in columns],
                    _TITLES[name], "Tabla reproducida de la demostración de versiones (spec 009)")
                names = ", ".join(column for column, _kind in columns)
                marks = ", ".join("?" for _ in columns)
                conn.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({marks})',
                                 [tuple(row) for row in rows])
        return reproduce.ReproducedOutput(role, self.module("core.content.builtin").GPKG_LAYER.id,
                                          {"main": path}, {"layer": name})

    def _pit_again(self, request: Any) -> Any:
        """``demo.pit`` con el límite y la altura de banco congelados."""
        reproduce = self.module("core.versions.reproduce")
        units = self.module("core.units")
        crs, vertical = request.references()
        boundary = request.input("boundary")
        with self._frozen(boundary) as conn:
            extent = self._extent_of(conn, boundary.settings["layer"], boundary.name,
                                     boundary.crs_epsg, crs.epsg)
        value, unit = request.params[BENCH_HEIGHT]
        bench_m = float(units.convert(value, unit, "m"))
        work = Path(request.workdir)
        grid_path, mesh_path = work / "pit_grid.tif", work / "pit_mesh.npz"
        rows = self._write_pit(extent, request.settings, bench_m, crs, vertical, grid_path,
                               mesh_path, work / "pit_mesh.npz.tmp")
        return reproduce.ReproducedResult(outputs=(
            reproduce.ReproducedOutput("pit_grid", self.module("gis.content").GEOTIFF.id,
                                       {"main": grid_path}),
            reproduce.ReproducedOutput("pit_mesh",
                                       self.module("core.content.builtin").NPZ_MESH.id,
                                       {"main": mesh_path}),
            self._reproduced_table(request, PIT_BENCHES, "pit", _BENCH_COLUMNS, rows),
        ))

    def _pit_volume_again(self, request: Any) -> Any:
        """``demo.pit_volume`` con la rejilla congelada."""
        reproduce = self.module("core.versions.reproduce")
        figures = self.module("core.provenance.figures")
        volume = self._volume(Path(request.input("pit_grid").files["main"]))
        return reproduce.ReproducedResult(
            figures=(figures.FigureSpec(PIT_VOLUME_FIGURE, volume, "m3"),))

    def _design_again(self, request: Any) -> Any:
        """``demo.design_from_parent`` con la tabla de bancos congelada en la padre."""
        reproduce = self.module("core.versions.reproduce")
        widening = float(request.settings["widening"])
        rows = [(bench, floor, area * widening, volume * widening)
                for bench, floor, area, volume in self._rows(
                    request.input("parent_pit"), [column for column, _kind in _BENCH_COLUMNS])]
        return reproduce.ReproducedResult(outputs=(
            self._reproduced_table(request, DESIGN_TABLE, "design", _BENCH_COLUMNS, rows),))

    def _pit_stockpiles_again(self, request: Any) -> Any:
        """``demo.pit_stockpiles`` con los acopios y los bancos congelados."""
        reproduce = self.module("core.versions.reproduce")
        benches = request.input("pit")
        with self._frozen(benches) as conn:
            (floor,) = conn.execute(f'SELECT floor_z FROM "{benches.settings["layer"]}" '
                                    "ORDER BY bench LIMIT 1").fetchone()
        rows = [(str(mark), float(loose), float(floor))
                for mark, loose in self._rows(request.input("stockpiles"), ("mark", "loose_m3"))]
        return reproduce.ReproducedResult(outputs=(self._reproduced_table(
            request, PIT_STOCKPILES_TABLE, "pit_stockpiles", _STOCKPILE_COLUMNS, rows),))


def source_cells(path: Path, reader: Any) -> int:
    """Las celdas del GeoTIFF ``path`` (su cabecera): el límite de celdas con que se lee
    entero, sin depender del parámetro de importación de la 006."""
    with path.open("rb") as stream:
        header = reader.read_header(stream, os.fstat(stream.fileno()).st_size, path.name)
    return int(header.width * header.height)
