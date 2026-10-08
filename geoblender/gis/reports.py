# SPDX-License-Identifier: GPL-3.0-or-later
"""Informes de topografía (spec 006; plan 006 §5.1; RF-006-09, RF-006-11, RF-006-12,
RF-006-14, RF-006-16, RF-006-23).

Lo que una importación, un remuestreo, un TIN o una validación cuentan al usuario: recuentos,
áreas (m²), porcentajes (%) y longitudes (m), con la unidad en el nombre del campo. Son cifras
diagnósticas, de tipo :data:`KIND` (CALCULADO), que no van a ``gb_figure`` hasta que un
informe las cite (spec 006 §11). Inmutables, con tuplas en lugar de listas, y serializables a
JSON con ``dataclasses.asdict`` (los ``report.json`` de los trabajos de la 004).

- :class:`TopoReport` y :class:`Rejection`: puntos y líneas importados (RF-006-12).
- :class:`Conflict` y :class:`ConflictKind`: un conflicto al crear un TIN (RF-006-14).
- :class:`ResampleReport`: la rejilla del proyecto desde un MDT (RF-006-05, RF-006-11).
- :class:`TinReport`: un TIN creado (RF-006-13 a RF-006-16).
- :class:`SurfaceReport`: la validación de una superficie (RF-006-23).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ports import TransformInfo

KIND = "CALCULADO"
"""El tipo de las cifras de estos informes (principio 2): diagnósticas, calculadas."""


@dataclass(frozen=True, slots=True)
class Rejection:
    """Una fila (o entidad) rechazada: su número en la fuente (1 = la primera), el motivo
    en español (el texto de ``gis.messages``) y su código ``gis.*``."""

    row: int
    reason: str
    code: str = ""


@dataclass(frozen=True, slots=True)
class TopoReport:
    """Importación de puntos y líneas de un fichero de texto o de una capa (RF-006-12):
    filas o entidades leídas (``read``), puntos y líneas aceptados, duplicados y
    rechazadas con su número y motivo; ``warnings``, los avisos en español."""

    source: str
    read: int
    points: int = 0
    lines: int = 0
    duplicates: int = 0
    rejected: tuple[Rejection, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def rejected_count(self) -> int:
        """Cuántas filas o entidades se rechazaron."""
        return len(self.rejected)


class ConflictKind(StrEnum):
    """Qué choca al crear un TIN (RF-006-14; plan A7 y A8)."""

    DUPLICATE_POINTS = "duplicate_points"
    CROSSING_LINES = "crossing_lines"
    POINT_ON_LINE = "point_on_line"
    COLLINEAR_OVERLAP = "collinear_overlap"


@dataclass(frozen=True, slots=True)
class Conflict:
    """Un conflicto (RF-006-14): sus dos identificadores (punto o línea), la posición X, Y
    ABSOLUTA (m) y la cota de cada uno allí (m)."""

    kind: ConflictKind
    ids: tuple[str, str]
    x: float
    y: float
    z: tuple[float, float]

    @property
    def dz(self) -> float:
        """La diferencia de cota (m), en valor absoluto."""
        return abs(self.z[0] - self.z[1])


@dataclass(frozen=True, slots=True)
class ResampleReport:
    """La rejilla del proyecto desde un MDT (RF-006-11; RF-006-05 si reproyecta).

    ``method``: ``area_mean``, ``bilinear`` o ``mode`` (el de ``gis.resample``);
    ``cells`` de la rejilla destino, ``valid_cells`` con dato y su ``cell_area_m2``;
    ``transform`` y ``supersample``, los de la reproyección (si la hubo); ``notes``, en
    español.
    """

    method: str
    min_valid_fraction: float
    cells: int
    valid_cells: int
    cell_area_m2: float
    transform: TransformInfo | None = None
    supersample: int | None = None
    notes: tuple[str, ...] = ()

    @property
    def nodata_cells(self) -> int:
        """Celdas sin dato: cobertura por debajo de la fracción mínima o sin vecinos."""
        return self.cells - self.valid_cells

    @property
    def valid_area_m2(self) -> float:
        """Área con dato (m²), con el área exacta de la celda (RF-006-02)."""
        return self.valid_cells * self.cell_area_m2


@dataclass(frozen=True, slots=True)
class TinReport:
    """Un TIN creado (RF-006-13 a RF-006-16): el triangulador (con su versión), puntos de
    entrada, vértices, triángulos y aristas obligatorias; duplicados fundidos; triángulos
    quitados por el contorno o los huecos y por el lado máximo; % de triángulos planos
    antes (TIN desde curvas) y después, puntos añadidos y cimas o fondos sin acotar que
    quedan planos (número y área, D-6); lado máximo (m) y triángulos degenerados."""

    triangulator: str
    input_points: int
    vertices: int
    triangles: int
    constraint_edges: int
    duplicates_merged: int = 0
    removed_outside: int = 0
    removed_long_edges: int = 0
    flat_pct_before: float | None = None
    flat_pct: float = 0.0
    points_added: int = 0
    unresolved_flat_regions: int = 0
    unresolved_flat_area_m2: float = 0.0
    max_edge_m: float = 0.0
    degenerate: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    """Validación de una superficie (RF-006-23): ``surface_type`` (``grid`` o ``tin``),
    área total y sin dato (m²), el área de cada hueco interior, celdas con dato fuera de
    la ventana de trabajo, cotas fuera del rango plausible ``z_range_m`` y, en un TIN, el
    % de triángulos planos, el lado máximo (m) y los degenerados."""

    surface_type: str
    area_m2: float
    nodata_area_m2: float
    hole_areas_m2: tuple[float, ...]
    cells_outside_window: int
    out_of_range: int
    z_range_m: tuple[float, float]
    flat_pct: float | None = None
    max_edge_m: float | None = None
    degenerate: int | None = None

    @property
    def nodata_pct(self) -> float:
        """El porcentaje del área sin dato (0 si el área es 0)."""
        if self.area_m2 <= 0.0:
            return 0.0
        return self.nodata_area_m2 / self.area_m2 * 100.0
