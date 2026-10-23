# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproducir lo congelado de la cubicación (spec 011, T15; RF-011-20; CE-011-04; plan 011 A12,
D-16, D-38).

Las funciones de reproducir de los tipos de ``res`` que se repiten (``OperationDef.reproduce``,
:data:`REPRODUCE`). ``core.versions.reproduce`` da a cada una, por cada operación congelada de
una revisión, su ``ReproduceRequest``: sus ajustes, sus entradas congeladas (``FrozenInput``: el
GeoTIFF de la instantánea de cada superficie, la tabla de su GeoPackage o de ``entradas.gpkg``),
sus parámetros congelados (el valor y la unidad de la fila del historial que usó), una carpeta de
trabajo vacía y el registro del proyecto (su CRS y su referencia vertical). Cada una hace **lo
mismo que la orden** sin recibir el proyecto ni escribir en él:

- ``res.volume`` y ``res.difference`` (:func:`reproduce_volume`): la cubicación de sus ajustes
  (``reserves.provenance.volume_request``) con la columna, el espesor mínimo y el umbral de
  presencia congelados y las superficies congeladas (cada papel, su GeoTIFF; una cota constante,
  en el CRS y el datum del proyecto), por los mismos pasos (``reserves.volumes.volume_steps``,
  con las bandas por defecto); en su carpeta de trabajo, la tabla ``res_vol_`` (en un GeoPackage
  propio, con sus títulos) y la rejilla de diferencias, cada una con el papel con que la anotó la
  operación, y sus cifras (las de ``res.difference``, con el ámbito de la diferencia);
- ``res.tonnage`` (:func:`reproduce_tonnage`): de la tabla de volúmenes y la columna congeladas,
  con los parámetros congelados (D-16), la tabla ``res_ton_`` y sus cifras;
- ``res.stages`` (:func:`reproduce_stages`): de las tablas de volúmenes congeladas de sus
  momentos y de la directa, con la tolerancia congelada (A13), la tabla ``res_stg_`` y sus
  cifras (sus avisos no son salidas: no se reproducen).

Con el mismo Geoblender y el mismo numpy, las salidas y las cifras salen **bit a bit**; con
otros, ``core.versions.reproduce`` compara las cifras con ``figure_tolerance`` (10⁻⁹, D-38).
Cerrar los pasos antes del final o un fallo dejan lo escrito en la carpeta de trabajo, que borra
quien la creó. Python puro con numpy (nivel 9).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar

from ..core.content.builtin import GPKG_LAYER
from ..core.georef.crs import CrsRef, VerticalRef
from ..core.gpkg.base import create_attribute_table, create_base, set_column_titles
from ..core.gpkg.connection import GpkgConnection
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.contract import ReproduceFunction
from ..core.units import convert
from ..core.versions.reproduce import (
    FrozenInput,
    ReproducedOutput,
    ReproducedResult,
    ReproduceRequest,
)
from ..gis.content import GEOTIFF
from ..gis.store import insert_rows
from . import provenance as declared
from .materials import MaterialColumn, read_column
from .messages import ResError
from .params import ANTHROPIC_PRESENCE, MIN_THICKNESS, STAGES_TOLERANCE
from .stages import StageTable, stages
from .store import STAGE_TABLE_COLUMNS, TABLE_COLUMNS, difference_figures
from .surfaces import BAND_ROWS, SurfaceRef, SurfaceSource, constant_source, grid_source
from .table import (
    COLUMN_NAMES,
    STAGE_COLUMN_NAMES,
    STAGE_TITLES,
    TITLES,
    Row,
    StageRow,
    read_rows,
)
from .volumes import (
    FINAL,
    START,
    STEP_BUDGET_S,
    VolumeRequest,
    VolumeResult,
    base_role,
    thickness_role,
    tonnage_outputs,
    volume_steps,
)

__all__ = [
    "GRID_FILE",
    "REPRODUCE",
    "reproduce_stages",
    "reproduce_tonnage",
    "reproduce_volume",
]

GRID_FILE = "rejilla_diferencias.tif"
"""La rejilla de diferencias reproducida, en la carpeta de trabajo."""

_OBJ = "Reproducción de la cubicación"
_T = TypeVar("_T")


def _check(request: object, op_types: Sequence[str]) -> ReproduceRequest:
    if not isinstance(request, ReproduceRequest):
        raise TypeError(f"se reproduce una ReproduceRequest, no {request!r}")
    if request.op_type not in op_types:
        raise ValueError(f"esta función reproduce {', '.join(op_types)}, no "
                         f"«{request.op_type}»")
    return request


def _name(request: ReproduceRequest) -> str:
    name = request.settings.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"los ajustes de «{request.op_type}» llevan el nombre de su cubicación")
    return name


def _param(request: ReproduceRequest, key: str, unit: str) -> float:
    """El parámetro congelado ``key`` (en ``unit``), como lo usó la operación."""
    value, frozen_unit = request.params.get(key, (None, ""))
    if value is None:
        raise ValueError(f"«{request.op_type}» no tiene «{key}» entre sus parámetros congelados")
    return convert(float(value), frozen_unit, unit)  # type: ignore[arg-type]


def _param_m(request: ReproduceRequest, key: str) -> float:
    """El parámetro congelado ``key`` (m), como lo usó la operación."""
    return _param(request, key, "m")


def _read(item: FrozenInput, read: Callable[[Any, str], _T]) -> _T:
    """Lo que da ``read(conexión, tabla)`` de la tabla congelada ``item`` (de solo lectura)."""
    layer = item.settings.get("layer")
    if not isinstance(layer, str) or not layer:
        raise ValueError(f"la entrada congelada «{item.name}» no dice su tabla (layer)")
    with GpkgConnection.open_read(Path(item.files["main"])) as gpkg:
        return read(gpkg.connection, layer)


def _column(request: ReproduceRequest) -> MaterialColumn:
    """La columna de materiales congelada que consumió la operación."""
    column = _read(request.input(declared.MATERIALS_ROLE), read_column)
    if column is None:
        raise ResError("res.materials_missing", obj="Columna de materiales", field="units",
                       value=0)
    return column


def _source(request: ReproduceRequest, role: str, ref: SurfaceRef, crs: CrsRef,
            vertical: VerticalRef) -> SurfaceSource:
    """La superficie congelada del papel ``role``: su GeoTIFF o la cota constante de ``ref``."""
    if ref.elevation is not None:
        return constant_source(ref.elevation, name=ref.shown, crs=crs, vertical=vertical)
    item = request.input(role)
    return grid_source(item.files["main"], name=item.name or ref.shown, crs=crs,
                       vertical=vertical)


def _sources(request: ReproduceRequest, volume: VolumeRequest, crs: CrsRef,
             vertical: VerticalRef) -> dict[str, SurfaceSource]:
    """Las superficies congeladas de ``volume`` por papel (las que lee ``volume_steps``)."""
    found = {START: _source(request, START, volume.start, crs, vertical),
             FINAL: _source(request, FINAL, volume.final, crs, vertical)}
    for unit in () if volume.column is None else volume.column.units:
        for ref, role in ((unit.base, base_role(unit.code)),
                          (unit.thickness, thickness_role(unit.code))):
            if ref is not None:
                found[role] = _source(request, role, ref, crs, vertical)
    return found


def _table(request: ReproduceRequest, family: str, name: str,
           rows: Sequence[Row] | Sequence[StageRow], crs: CrsRef) -> ReproducedOutput:
    """La tabla ``family`` de la cubicación ``name`` con ``rows`` en un GeoPackage propio de la
    carpeta de trabajo, como salida reproducida con el papel de su familia (la de los momentos,
    con su columna ``stage``)."""
    found = declared.FAMILIES_BY_CODE[family]
    table = declared.dataset_name(family, name)
    columns, names, titles = ((STAGE_TABLE_COLUMNS, STAGE_COLUMN_NAMES, STAGE_TITLES)
                              if family == declared.STAGE_TABLE
                              else (TABLE_COLUMNS, COLUMN_NAMES, TITLES))
    path = Path(request.workdir) / f"{found.role}.gpkg"
    check_path_length(path, obj=_OBJ)
    with GpkgConnection.open_write(path, create=True) as gpkg, gpkg.transaction() as conn:
        create_base(conn, crs)
        create_attribute_table(conn, table, columns, f"{found.label} «{name}»",
                               f"{found.label} «{name}», reproducida por Geoblender")
        set_column_titles(conn, table, titles)
        insert_rows(conn, table, names, [row.values() for row in rows])
    return ReproducedOutput(found.role, GPKG_LAYER.id, {"main": path}, {"layer": table})


def reproduce_volume(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S,
                     band_rows: int = BAND_ROWS) -> Iterator[Progress]:
    """Reproduce ``res.volume`` o ``res.difference`` (véase el módulo): los pasos de la
    cubicación (``Progress`` de ``volume_steps``) y, el último, con su ``ReproducedResult``.
    ``TypeError`` o ``ValueError`` al llamar si ``request`` no es de uno de esos tipos; al
    avanzar, los mismos rechazos que la orden y ``ValueError`` si falta lo congelado que usó
    (una entrada o un parámetro)."""
    return _volume_steps(_check(request, (declared.VOLUME, declared.DIFFERENCE)), budget_s,
                         band_rows)


def _volume_steps(request: ReproduceRequest, budget_s: float,
                  band_rows: int) -> Iterator[Progress]:
    crs, vertical = request.references()
    column = _column(request) if request.settings.get("units") else None
    volume = declared.volume_request(request.settings, column=column)
    presence = volume.presence_m if column is None else _param_m(request, ANTHROPIC_PRESENCE)
    volume = replace(volume, min_thickness_m=_param_m(request, MIN_THICKNESS),
                     presence_m=presence)
    sources = _sources(request, volume, crs, vertical)
    grid = temporary = None
    if volume.difference_grid:
        grid = Path(request.workdir) / GRID_FILE
        temporary = grid.with_name(grid.name + ".tmp")
        check_path_length(temporary, obj=_OBJ)
    steps = volume_steps(volume, sources, budget_s=budget_s, difference_path=grid,
                         difference_temporary=temporary, band_rows=band_rows)
    last: Progress | None = None
    with closing(steps):
        for step in steps:
            last = step
            if isinstance(step.result, VolumeResult):
                break
            yield step
    assert last is not None and isinstance(last.result, VolumeResult)
    result: VolumeResult = last.result
    outputs: list[ReproducedOutput] = []
    if result.difference is not None and grid is not None:
        os.replace(result.difference.path, grid)
        outputs.append(ReproducedOutput(
            declared.FAMILIES_BY_CODE[declared.DIFFERENCE_GRID].role, GEOTIFF.id,
            {"main": grid}))
    if request.op_type == declared.VOLUME:
        outputs.append(_table(request, declared.VOLUMES, volume.name, result.rows, crs))
        figures = result.figures
    else:
        figures = difference_figures(result)
    yield Progress(last.phase, last.total, last.total, f"«{volume.name}» reproducida",
                   result=ReproducedResult(tuple(outputs), tuple(figures)))


def reproduce_tonnage(request: ReproduceRequest) -> Iterator[Progress]:
    """Reproduce ``res.tonnage`` (véase el módulo): un paso al leer lo congelado y el último,
    con su ``ReproducedResult``. ``TypeError`` o ``ValueError`` al llamar si ``request`` no es
    de ese tipo."""
    return _tonnage_steps(_check(request, (declared.TONNAGE,)))


def _tonnage_steps(request: ReproduceRequest) -> Iterator[Progress]:
    total = 2
    name = _name(request)
    crs, _vertical = request.references()
    rows = _read(request.input(declared.VOLUMES_ROLE), read_rows)
    column = _column(request)
    yield Progress("read", 1, total, f"Pesando «{name}»: la tabla de volúmenes leída…")
    values = {key: value for key, (value, _unit) in request.params.items()}
    outputs = tonnage_outputs(rows, column, values, name=name)
    table = _table(request, declared.TONNES, name, outputs.rows, crs)
    yield Progress("result", total, total, f"Toneladas de «{name}» reproducidas",
                   result=ReproducedResult((table,), outputs.figures))


def reproduce_stages(request: ReproduceRequest) -> Iterator[Progress]:
    """Reproduce ``res.stages`` (véase el módulo): un paso al leer las tablas congeladas y el
    último, con su ``ReproducedResult``. ``TypeError`` o ``ValueError`` al llamar si ``request``
    no es de ese tipo."""
    return _stages_steps(_check(request, (declared.STAGES,)))


def _stages_steps(request: ReproduceRequest) -> Iterator[Progress]:
    total = 2
    name = _name(request)
    moments, direct = request.settings.get("moments"), request.settings.get("direct")
    if not isinstance(moments, Sequence) or isinstance(moments, str) \
            or not isinstance(direct, str):
        raise ValueError(f"los ajustes de «{request.op_type}» llevan sus momentos y su directa")
    crs, _vertical = request.references()
    roles = [(declared.stage_role(position), moment)
             for position, moment in enumerate(moments, start=1)]
    tables = [StageTable(cubication, _read(request.input(role), read_rows))
              for role, cubication in (*roles, (declared.DIRECT_ROLE, direct))]
    yield Progress("read", 1, total, f"Comparando «{name}»: las tablas de volúmenes leídas…")
    result = stages(tables[:-1], tables[-1], name=name,
                    tolerance_pct=_param(request, STAGES_TOLERANCE, "%"))
    table = _table(request, declared.STAGE_TABLE, name, result.rows, crs)
    yield Progress("result", total, total, f"«{name}» reproducida",
                   result=ReproducedResult((table,), result.figures))


REPRODUCE: Mapping[str, ReproduceFunction] = MappingProxyType({
    declared.VOLUME: reproduce_volume,
    declared.TONNAGE: reproduce_tonnage,
    declared.DIFFERENCE: reproduce_volume,
    declared.STAGES: reproduce_stages,
})
"""La función de reproducir de cada tipo de ``res`` que se repite: las que registra
``bl/ops/res.py`` con ``reserves.provenance.operation_defs``."""
