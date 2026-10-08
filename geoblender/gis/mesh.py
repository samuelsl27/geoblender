# SPDX-License-Identifier: GPL-3.0-or-later
"""Mallas de una superficie para la vista, su comprobación y sus niveles de detalle (spec 006;
RF-006-21, RF-006-22; plan 006 §5.3.2 y §5.4 A15).

Todas las coordenadas de este módulo son **absolutas** (CRS y datum del proyecto, m,
float64): la vista (``bl``) las pasa a locales respecto al GeoOrigin con
``core.georef.world_to_local`` antes de crear la malla, y las devuelve a absolutas con
``core.georef.local_to_world`` para comprobarla (ADR-0005).

- :class:`MeshArrays`: los vértices y los triángulos de una malla de superficie, con la normal
  hacia arriba (+Z): antihorarios vistos desde arriba.
- :func:`surface_mesh_from_raster`: la malla de una rejilla, la triangulación de A13 (la de
  ``gis.tin.raster_to_tin``: los centros de las celdas con dato, dos triángulos por cuadro de
  2 × 2 con la diagonal fija, uno si tiene tres esquinas con dato).
- :func:`surface_mesh_from_tin`: la malla de un TIN, sus vértices y sus caras (las horarias,
  vueltas hacia arriba).
- :func:`check_surface_mesh` y :class:`MeshReport` (RF-006-21): una malla no es válida, y no
  se muestra como superficie del proyecto, si tiene caras con la normal hacia abajo (área en
  planta con signo negativo) o degeneradas (área en planta nula, con signo exacto: un vértice
  repetido o tres alineados en planta; o un vértice no finito), o si su volumen sobre la cota
  mínima de la superficie difiere del de la rejilla o el TIN en más que su área en planta por
  :data:`VOLUME_TOLERANCE_M` (0,5 mm). El volumen es V = Σ A(t)·(z̄ₜ − z_min) con A(t) el
  área en planta con signo de cada triángulo (positiva si es antihorario): la malla invertida
  da V ≈ −V_ref (ΔV ≈ −2V), la que pierde caras, menos. El informe dice cuántas caras fallan,
  cuántas tiene la malla y la superficie y la diferencia en m³.
- :func:`lod_rasters` (RF-006-22): de una rejilla de paso menor que el primero de
  ``gis.view.lod_steps_m`` (2 y 5 m), sus versiones para la vista general, por media de área
  (``gis.resample``, A6) en la rejilla alineada de cada paso (``gis.grid.aligned_grid``). La
  rejilla de cálculo no se modifica.

Las cifras de :class:`MeshReport` son diagnósticas (CALCULADO), como las de
``gis.reports``. Las entradas no se modifican.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from . import params
from .grid import aligned_grid, validate_step
from .messages import GisError, format_value, render
from .ports import Cancelled, Progress
from .raster import Raster
from .resample import ResampleMethod, resample_to_grid
from .tin import Tin, _orientation, _oriented, raster_to_tin

__all__ = [
    "LOD_STEPS_KEY",
    "VOLUME_TOLERANCE_M",
    "MeshArrays",
    "MeshReport",
    "check_surface_mesh",
    "lod_rasters",
    "surface_mesh_from_raster",
    "surface_mesh_from_tin",
]

VOLUME_TOLERANCE_M = 0.0005
"""La diferencia de volumen admitida, por m² de área en planta de la malla: 0,5 mm
(RF-006-21)."""

LOD_STEPS_KEY = "gis.view.lod_steps_m"
MESSAGE_DECIMALS = 3
"""Cota base, diferencia y tolerancia en el mensaje: al milímetro y al litro."""


@dataclass(frozen=True, slots=True, eq=False)
class MeshArrays:
    """Una malla de superficie: ``vertices`` float64 ``(n, 3)`` ABSOLUTOS y finitos y
    ``faces`` int32 ``(m, 3)``, triángulos con índices de ``vertices``, antihorarios vistos
    desde arriba (normal +Z). No copia los arrays. ``TypeError`` o ``ValueError`` si no
    cumplen tipos, formas e índices (errores del programa)."""

    vertices: np.ndarray
    faces: np.ndarray

    def __post_init__(self) -> None:
        vertices = _vertex_array(self.vertices, "MeshArrays.vertices")
        if not np.isfinite(vertices).all():
            raise ValueError("MeshArrays.vertices tiene coordenadas que no son finitas")
        if not isinstance(self.faces, np.ndarray) or self.faces.dtype != np.int32:
            found = (self.faces.dtype if isinstance(self.faces, np.ndarray)
                     else type(self.faces).__name__)
            raise TypeError(f"MeshArrays.faces es un ndarray int32, no {found}")
        _face_array(self.faces, len(vertices), "MeshArrays.faces")


def _vertex_array(vertices: object, what: str) -> np.ndarray:
    """``vertices`` si es un ndarray float64 ``(n, 3)`` (absolutas: en float32 ya habrían
    perdido precisión, ADR-0005)."""
    if not isinstance(vertices, np.ndarray) or vertices.dtype != np.float64:
        found = vertices.dtype if isinstance(vertices, np.ndarray) else type(vertices).__name__
        raise TypeError(f"{what}: los vértices son coordenadas ABSOLUTAS en un ndarray "
                        f"float64, no {found}")
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError(f"{what}: los vértices son (n, 3) y llegan {vertices.shape}")
    return vertices


def _face_array(faces: object, count: int, what: str) -> np.ndarray:
    """``faces`` si es un ndarray de enteros ``(m, 3)`` con índices de ``count`` vértices."""
    if not isinstance(faces, np.ndarray) or faces.dtype.kind not in "iu":
        found = faces.dtype if isinstance(faces, np.ndarray) else type(faces).__name__
        raise TypeError(f"{what}: las caras son un ndarray de enteros, no {found}")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError(f"{what}: las caras son triángulos (m, 3) y llegan {faces.shape}")
    if faces.size and (int(faces.min()) < 0 or int(faces.max()) >= count):
        raise ValueError(f"{what}: las caras usan vértices que no existen (hay {count})")
    return faces


# Mallas (A15) ----------------------------------------------------------------------------


def surface_mesh_from_raster(
    raster: Raster,
    *,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> MeshArrays:
    """La malla de ``raster`` (RF-006-21; A15): la triangulación de A13, la de
    ``gis.tin.raster_to_tin`` (vértices en los centros de las celdas con dato, bit a bit,
    triángulos antihorarios). Sin ningún triángulo → ``GisError`` ``gis.grid_tin_empty`` con
    ``name``. Avance y cancelación como ``raster_to_tin``. La entrada no se modifica."""
    if not isinstance(raster, Raster):
        raise TypeError(f"raster debe ser un Raster, no {type(raster).__name__}")
    tin = raster_to_tin(raster, name=name, progress=progress, cancelled=cancelled)
    return MeshArrays(tin.vertices, tin.faces)


def surface_mesh_from_tin(tin: Tin) -> MeshArrays:
    """La malla de ``tin`` (RF-006-21; A15): sus vértices y sus caras, las horarias (un TIN
    leído de otro sitio) vueltas hacia arriba con el signo exacto. Los arrays del TIN no se
    copian ni se modifican: las caras son un array nuevo solo si hay que dar la vuelta a
    alguna."""
    if not isinstance(tin, Tin):
        raise TypeError(f"tin debe ser un Tin, no {type(tin).__name__}")
    faces = _oriented(tin.vertices[:, :2], tin.faces)
    return MeshArrays(tin.vertices, np.ascontiguousarray(faces, dtype=np.int32))


# Comprobación (RF-006-21) ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeshReport:
    """La comprobación de la malla de una superficie (RF-006-21): ``surface``, su nombre;
    ``faces`` de la malla y ``reference_faces`` de la superficie (rejilla triangulada o
    TIN); caras con la normal hacia abajo (``faces_down``) y degeneradas
    (``faces_degenerate``); ``base_m``, la cota mínima de la superficie; el volumen sobre ella
    de la malla y de la superficie (m³); el área en planta de la malla y de la superficie
    (m²); y ``tolerance_m3``, el área en planta de la malla por :data:`VOLUME_TOLERANCE_M`."""

    surface: str
    faces: int
    reference_faces: int
    faces_down: int
    faces_degenerate: int
    base_m: float
    volume_m3: float
    reference_volume_m3: float
    plan_area_m2: float
    reference_area_m2: float
    tolerance_m3: float

    @property
    def failed_faces(self) -> int:
        """Las caras que fallan: hacia abajo o degeneradas."""
        return self.faces_down + self.faces_degenerate

    @property
    def difference_m3(self) -> float:
        """Volumen de la malla − volumen de la superficie (m³)."""
        return self.volume_m3 - self.reference_volume_m3

    @property
    def valid(self) -> bool:
        """Ninguna cara falla y |diferencia| ≤ tolerancia (RF-006-21)."""
        return self.failed_faces == 0 and abs(self.difference_m3) <= self.tolerance_m3

    def _values(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "faces": self.faces,
            "reference_faces": self.reference_faces,
            "base": _rounded(self.base_m),
            "difference": _rounded(self.difference_m3),
            "tolerance": _rounded(self.tolerance_m3),
        }

    def message(self, language: str = "es") -> str | None:
        """El texto de ``gis.mesh_invalid`` (caras que fallan, caras de la malla y de la
        superficie, cota base, diferencia y tolerancia en m³), o ``None`` si es válida."""
        if self.valid:
            return None
        return render("gis.mesh_invalid", language=language, value=self.failed_faces,
                      **self._values())

    def error(self) -> GisError | None:
        """El error ``gis.mesh_invalid`` (sin lanzar; objeto, la malla; campo, «caras»;
        valor, las que fallan), o ``None`` si es válida."""
        if self.valid:
            return None
        obj = f"Malla de «{self.surface}»" if self.surface else "Malla"
        return GisError("gis.mesh_invalid", obj=obj, field="caras", value=self.failed_faces,
                        **self._values())


def _rounded(value: float) -> float:
    return round(value, MESSAGE_DECIMALS) + 0.0  # + 0,0: sin «-0»


def _reference(reference: object, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Vértices y caras de la superficie de referencia: la triangulación de A13 de una
    rejilla o las caras de un TIN."""
    if isinstance(reference, Raster):
        tin = raster_to_tin(reference, name=name)
    elif isinstance(reference, Tin):
        tin = reference
    else:
        raise TypeError(f"la referencia es un Raster o un Tin, no {type(reference).__name__}")
    return tin.vertices, tin.faces.astype(np.int64)


def _volume(vertices: np.ndarray, faces: np.ndarray, det: np.ndarray,
            base: float) -> float:
    """Σ A(t)·(z̄ₜ − base) con A(t) = ``det``/2, el área en planta con signo."""
    z = vertices[:, 2][faces] - base
    height = (z[:, 0] + z[:, 1] + z[:, 2]) / 3.0
    return float(np.sum(0.5 * det * height))


def check_surface_mesh(
    vertices_abs: np.ndarray,
    faces: np.ndarray,
    reference: Raster | Tin,
    *,
    name: str = "",
) -> MeshReport:
    """Comprueba la malla ``vertices_abs`` (float64 ``(n, 3)``, ABSOLUTOS: los de la vista,
    vueltos con ``core.georef.local_to_world``) y ``faces`` (enteros ``(m, 3)``) frente a la
    superficie ``reference``, una rejilla (con la triangulación de A13) o un TIN (con sus
    caras): RF-006-21, A15.

    Cada cara con un vértice no finito es degenerada y no cuenta en el volumen ni en el área;
    las demás, por el signo exacto de su área en planta, van hacia arriba, hacia abajo o son
    degeneradas (área nula). Volumen sobre ``base_m``, la cota mínima de los vértices de la
    superficie: el de la malla con el área con signo y el de la superficie con el área sin
    signo (no depende de cómo estén orientados sus triángulos). ``name`` es el de la
    superficie en el informe y en los errores. Una rejilla sin triángulos →
    ``gis.grid_tin_empty``; tipos o formas que no son → ``TypeError`` o ``ValueError``. Las
    entradas no se modifican."""
    vertices = _vertex_array(vertices_abs, "check_surface_mesh")
    mesh_faces = _face_array(faces, len(vertices), "check_surface_mesh").astype(np.int64)
    reference_vertices, reference_faces = _reference(reference, name)
    base = float(reference_vertices[:, 2][reference_faces].min())
    reference_det, _sign = _orientation(reference_vertices[:, :2], reference_faces)
    reference_det = np.abs(reference_det)

    finite = np.isfinite(vertices).all(axis=1)[mesh_faces].all(axis=1)
    usable = mesh_faces[finite]
    det, sign = _orientation(vertices[:, :2], usable)
    plan_area = float(np.sum(0.5 * np.abs(det)))
    return MeshReport(
        surface=name,
        faces=len(mesh_faces),
        reference_faces=len(reference_faces),
        faces_down=int(np.count_nonzero(sign < 0)),
        faces_degenerate=int(np.count_nonzero(sign == 0)) + len(mesh_faces) - len(usable),
        base_m=base,
        volume_m3=_volume(vertices, usable, det, base),
        reference_volume_m3=_volume(reference_vertices, reference_faces, reference_det, base),
        plan_area_m2=plan_area,
        reference_area_m2=float(np.sum(0.5 * reference_det)),
        tolerance_m3=plan_area * VOLUME_TOLERANCE_M,
    )


# Niveles de detalle (RF-006-22) ----------------------------------------------------------


def _lod_steps(steps_m: Sequence[float] | None) -> tuple[float, ...]:
    """Los pasos de los niveles: los de ``gis.view.lod_steps_m`` si es ``None``; si no,
    comprobados como el parámetro (``gis.param_*``). Cada uno, paso de rejilla del proyecto
    (``gis.step_invalid``)."""
    definition = params.param(LOD_STEPS_KEY)
    steps = definition.default if steps_m is None else definition.check(steps_m)
    for step in steps:  # type: ignore[union-attr]
        validate_step(step)
    return tuple(float(step) for step in steps)  # type: ignore[union-attr]


def _level_progress(progress: Progress | None, index: int, count: int,
                    step: float) -> Progress | None:
    """El avance del remuestreo de un nivel, dentro del de todos."""
    if progress is None:
        return None

    def report(fraction: float, text: str) -> None:
        progress((index + fraction) / count,
                 f"Nivel de detalle de {format_value(step)} m: {text}")

    return report


def lod_rasters(
    raster: Raster,
    steps_m: Sequence[float] | None = None,
    *,
    min_valid_fraction: float | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> dict[float, Raster]:
    """Las versiones de ``raster`` para la vista general (RF-006-22; A15): si su paso (en X y
    en Y) es menor que el primero de ``steps_m`` (``None``: ``gis.view.lod_steps_m``, 2 y
    5 m), una por paso, la media por área (``gis.resample``, A6, con ``min_valid_fraction``;
    ``None``: ``gis.resample.min_valid_fraction``) en la rejilla alineada que cubre la suya
    (``aligned_grid``), con su CRS y su referencia vertical; si no, ninguna (``{}``). Por
    paso, en orden creciente. Pasos que no son el parámetro → ``gis.param_*``; que no son
    pasos de rejilla del proyecto → ``gis.step_invalid``. Avance y cancelación
    (``JobCancelled``) del remuestreo. La rejilla de cálculo no se modifica."""
    if not isinstance(raster, Raster):
        raise TypeError(f"raster debe ser un Raster, no {type(raster).__name__}")
    steps = _lod_steps(steps_m)
    grid = raster.grid
    if max(grid.dx, grid.dy) >= steps[0]:
        return {}
    levels: dict[float, Raster] = {}
    for index, step in enumerate(steps):
        level, _report = resample_to_grid(
            raster, aligned_grid(grid.extent, step), method=ResampleMethod.AREA_MEAN,
            min_valid_fraction=min_valid_fraction,
            progress=_level_progress(progress, index, len(steps), step), cancelled=cancelled)
        levels[step] = level
    return levels
