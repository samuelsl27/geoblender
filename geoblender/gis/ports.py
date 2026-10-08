# SPDX-License-Identifier: GPL-3.0-or-later
"""Puertos de ``gis`` (spec 006; plan 006 §5.3.1; ADR-0004, ADR-0020, ADR-0021).

Las interfaces que ``gis`` define y que implementan otros: el dominio no sabe de Blender ni
de pyproj (principios 3 y 4). Este módulo es el **dueño** del puerto de CRS, que usa también
la 005 (convergencia de cuadrícula para el azimut de los sondeos).

- :class:`RasterIO`: lectura y escritura de rásteres; la implementa ``gis.geotiff.GeoTiffIO``
  (biblioteca estándar y numpy, ADR-0020), con los perfiles de :class:`WriteProfile`.
- :class:`Triangulator`: triangulación de Delaunay restringida (ADR-0021); en Blender,
  ``bl.scene.triangulator.BlenderTriangulator`` (``delaunay_2d_cdt``), y sin Blender,
  ``gis.cdt.PureTriangulator``. Si no cumple el contrato, :class:`TriangulationError`.
- :class:`Transform` y :class:`TransformInfo`: una transformación entre CRS con su
  descripción, su precisión (``None`` = desconocida; RF-006-05 no la admite) y sus rejillas.
- :class:`CrsService`: identificar un WKT, dar transformaciones, el factor de escala y la
  convergencia de cuadrícula; lo implementa ``adapters.pyproj_crs.PyprojCrsService``
  (PROJ aislado y sin red), resuelto por ``adapters.registry``.
- ``Progress`` y ``Cancelled``: el avance (fracción de 0 a 1 y texto) y la consulta de
  cancelación que reciben las operaciones largas (RF-006-28).

Coordenadas: ``Transform.apply``, ``CrsService.scale_factor`` y ``grid_convergence`` reciben
coordenadas **absolutas** en float64; ``Triangulator.triangulate``, **relativas al GeoOrigin**
(locales, en float64), para que la CDT de Blender, en float32, no pierda precisión (ADR-0005).

Un ``ports.py`` solo importa la biblioteca estándar, numpy y ``core`` (ARQ-10): ``Raster`` y
``RasterSource`` son de ``gis.raster`` y aquí solo se nombran en las anotaciones, que con
``from __future__ import annotations`` quedan como texto y no se evalúan.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from numpy import ndarray

from ..core.errors import GeoblenderError
from ..core.georef import CrsRef, VerticalRef

type Progress = Callable[[float, str], None]
"""Avance de una operación: fracción hecha (de 0 a 1) y texto para la barra de estado."""

type Cancelled = Callable[[], bool]
"""Verdadero si el usuario pidió cancelar: la operación para sin dejar resultados."""

__all__ = [
    "Cancelled",
    "CrsService",
    "Progress",
    "RasterIO",
    "Transform",
    "TransformInfo",
    "TriangulationError",
    "Triangulator",
    "WriteProfile",
]


class WriteProfile(StrEnum):
    """Perfil de escritura de un ráster (plan 006 §5.2.1).

    - ``PROJECT``: el del proyecto (``rasters/gis_*.tif``): Float64 y sin dato NaN.
    - ``DELIVERABLE``: el entregable (``exports/…``): Float32 y sin dato −9999 (RF-006-24).
    """

    PROJECT = "project"
    DELIVERABLE = "deliverable"


@dataclass(frozen=True, slots=True)
class TransformInfo:
    """Qué transformación es: ``description`` (la de PROJ, para el informe),
    ``accuracy_m`` (precisión en m; ``None`` si es desconocida, y entonces no se usa:
    RF-006-05) y ``grids`` (las rejillas que usa, p. ej. ``es_ign_SPED2ETV2.tif``)."""

    description: str
    accuracy_m: float | None
    grids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        accuracy = self.accuracy_m
        if accuracy is not None and not (math.isfinite(accuracy) and accuracy >= 0.0):
            raise ValueError(
                f"la precisión de una transformación es un número de metros ≥ 0 o None "
                f"(desconocida), no {accuracy!r}"
            )


class TriangulationError(GeoblenderError):
    """Un triangulador no cumplió el contrato de :class:`Triangulator` (p. ej. creó
    vértices nuevos o perdió una arista obligatoria). Se construye como cualquier
    ``GeoblenderError``, con el código y el texto de ``gis.messages``
    (``gis.triangulation_contract``)."""


@runtime_checkable
class RasterIO(Protocol):
    """Lectura y escritura de un ráster de una banda (RF-006-08, RF-006-24)."""

    def read(
        self,
        path: Path,
        *,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> RasterSource:
        """El ráster de ``path`` en float64 (sin dato = NaN) con lo que declara la fuente
        (``gis.raster.RasterSource``). La fuente no se modifica ni se crea nada junto a
        ella (RF-006-10); lo no admitido se rechaza con un código ``gis.*`` (RF-006-09)."""
        ...

    def write(self, raster: Raster, path: Path, *, profile: WriteProfile) -> None:
        """Escribe ``raster`` (``gis.raster.Raster``) en ``path`` con ``profile``, con
        temporal y renombrado: nunca un fichero a medias."""
        ...


@runtime_checkable
class Triangulator(Protocol):
    """Triangulación de Delaunay restringida (RF-006-13; ADR-0021).

    ``name``: ``"blender-cdt@<versión>"`` o ``"pure@<versión>"``, que se guarda en la
    procedencia de la operación (RF-006-26).
    """

    name: str

    def triangulate(self, xy_local: ndarray, edges: ndarray) -> ndarray:
        """Triángulos de ``xy_local`` (float64 (n, 2), RELATIVAS al GeoOrigin) con las
        aristas obligatorias ``edges`` (int32 (k, 2), sin cruces: los prepara
        ``gis.breaklines``).

        Devuelve int32 (m, 3): índices de la entrada, antihorarios vistos desde arriba,
        sin vértices nuevos, cubriendo la envolvente convexa y con cada arista de
        ``edges`` como arista de algún triángulo. Si no puede cumplirlo,
        :class:`TriangulationError`.
        """
        ...


@runtime_checkable
class Transform(Protocol):
    """Una transformación entre dos CRS (con sus datums verticales) de precisión conocida
    (RF-006-05)."""

    info: TransformInfo

    def apply(self, xyz: ndarray) -> ndarray:
        """``xyz`` float64 (n, 3) ABSOLUTAS en el CRS de origen (orden x, y: Este, Norte)
        → float64 (n, 3) ABSOLUTAS en el de destino. No modifica ``xyz``."""
        ...


@runtime_checkable
class CrsService(Protocol):
    """Servicio de CRS (RF-006-04, RF-006-05, RF-006-07, RF-006-31; D-2)."""

    def identify_wkt(self, wkt: str) -> CrsRef | None:
        """El CRS del catálogo que es ``wkt`` (de un ``.prj`` o de un GeoPackage), o
        ``None`` si no es ninguno (se pide al usuario: RF-006-04)."""
        ...

    def transformer(
        self, src: CrsRef, src_v: VerticalRef, dst: CrsRef, dst_v: VerticalRef
    ) -> Transform:
        """La transformación de ``src`` + ``src_v`` a ``dst`` + ``dst_v`` de mejor
        precisión con todas sus rejillas presentes; su ``info`` dice cuál es."""
        ...

    def scale_factor(self, crs: CrsRef, xy: ndarray) -> ndarray:
        """Factor de escala de ``crs`` en ``xy`` (float64 (n, 2) ABSOLUTAS) → (n,)."""
        ...

    def grid_convergence(self, crs: CrsRef, xy: ndarray) -> ndarray:
        """Convergencia de cuadrícula γ en grados (n,) en ``xy`` (ABSOLUTAS): el ángulo
        horario del norte geográfico al de cuadrícula, positivo al este del meridiano
        central; azimut de cuadrícula = azimut geográfico − γ (contrato de la 005)."""
        ...
