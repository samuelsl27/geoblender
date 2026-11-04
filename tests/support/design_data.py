# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de las envolventes y el escalonado que no necesitan el paquete (spec 013, T30 y
T31; plan 013 §2.2; RNF-013-01 a RNF-013-07).

Solo numpy y la biblioteca estándar: los usan a la vez las pruebas de rendimiento con el Python de
Blender (``tests/support/design_perf.py``, que los convierte a las clases de su copia del paquete,
``import_geoblender``) y las de dentro de Blender (``tests/rendimiento/blender/perf_design.py``, que los
convierte a las clases de la extensión habilitada: allí no se puede cargar otra copia del paquete,
``docs/trampas.md`` §4). No se versionan datos: se generan con la semilla :data:`SEED`, sin ningún
dato de cliente.

- **La rejilla** (spec 013 §5): :data:`COLS` × :data:`ROWS` celdas de :data:`STEP_M` m (2,81 M), la
  de las restricciones de la 012 (``constraints_data``), con :func:`terrain` (un terreno ondulado de
  145 a 215 m con colinas, un ondulado de metros y ruido de 5 cm).
- **Las semillas** (plan §2.2): :func:`ring_seeds` (un anillo de radio :data:`RING_RADIUS_M`; con
  :data:`RING_HALF_WIDTH_M`, unas 5.300 celdas, y con :data:`THICK_HALF_WIDTH_M`, unas 9.800, bajo
  el tope de 10.000 de RNF-013-01), :func:`disc_seeds` (un disco rugoso de unas 159.900 celdas, con un
  ondulado de ±2 m y ruido de 0,3 m sobre el terreno: la zona maciza de RNF-013-01) y
  :func:`preview_seeds` (un disco de unas 100.000 celdas sobre el terreno con un ondulado de ±2 m: las
  semillas de la vista previa de RNF-013-05). Cada una es una rejilla de cotas con NaN donde no hay
  semilla.
- **Los sectores** (:data:`SECTORS` franjas): :func:`strip_labels` (las etiquetas de la rejilla),
  :func:`sector_boxes` (la caja de cada franja del perímetro), :func:`profile_of` y :func:`assigned` (el
  perfil de cada sector) y los diez :data:`PROFILES` con los dos taludes impuestos de :data:`IMPOSED`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from tests.support import constraints_data as cdata

__all__ = [
    "CELLS", "COLS", "CONTOUR_MAX_SEEDS", "DISC_RADIUS_M", "GENERAL_DEG", "IMPOSED", "MARGIN_M",
    "PERSON", "PREVIEW_RADIUS_M", "PROFILES", "RING_HALF_WIDTH_M", "RING_RADIUS_M", "ROWS", "SECTORS",
    "SEED", "SOLID_MAX_SEEDS", "STEP_M", "THICK_HALF_WIDTH_M", "PerfProfile", "assigned",
    "disc_seeds", "preview_seeds", "profile_of", "ring_seeds", "sector_boxes", "sector_code",
    "strip_labels", "terrain",
]

COLS, ROWS = cdata.COLS, cdata.ROWS
STEP_M = cdata.STEP_M
CELLS = COLS * ROWS
SEED = 20_261_104
GENERAL_DEG = 35.0
"""La pendiente de las envolventes de pendiente constante (``k = tan 35°``, plan §2.2)."""
CONTOUR_MAX_SEEDS = 10_000
SOLID_MAX_SEEDS = 160_000
RING_RADIUS_M = 600.0
RING_HALF_WIDTH_M = 0.7
"""El anillo de §2.2: unas 5.300 celdas."""
THICK_HALF_WIDTH_M = 1.3
"""El anillo más grueso: unas 9.800 celdas, bajo el tope de RNF-013-01."""
DISC_RADIUS_M = 225.6
PREVIEW_RADIUS_M = 178.4
"""El radio del disco de la vista previa de RNF-013-05: unas 100.000 celdas."""
SECTORS = 20
PERSON = "Samuel (IMGA)"
MARGIN_M = 10.0
"""Lo que el perímetro queda dentro de la ventana (y el límite legal, la mitad)."""

_CACHE: dict[str, np.ndarray] = {}


# --- El terreno y las semillas -------------------------------------------------------------------


def _east() -> np.ndarray:
    """Las coordenadas locales (m desde el oeste) de los centros de cada columna, (1, COLS)."""
    return (np.arange(COLS, dtype=np.float64) + 0.5)[None, :] * STEP_M


def _north() -> np.ndarray:
    """Las coordenadas locales (m desde el sur) de los centros de cada fila (la 0 al norte),
    (ROWS, 1)."""
    return (np.arange(ROWS, dtype=np.float64)[::-1] + 0.5)[:, None] * STEP_M


def terrain() -> np.ndarray:
    """El terreno (m, float64, fila 0 al norte): de 145 a 215 m, con colinas de cientos de
    metros, un ondulado de metros y ruido de 5 cm. Es el mismo array en cada llamada: no se
    modifica."""
    if "terrain" not in _CACHE:
        east, north = _east(), _north()
        values = (180.0 + 30.0 * np.sin(east / 150.0) * np.cos(north / 120.0)
                  + 5.0 * np.sin(east / 7.3) * np.sin(north / 5.1))
        values += np.random.default_rng(SEED).normal(0.0, 0.05, values.shape)
        _CACHE["terrain"] = values
    return _CACHE["terrain"]


def _distance_from_center() -> np.ndarray:
    """La distancia (m) de cada centro de celda al centro de la rejilla."""
    return np.hypot(_east() - COLS * STEP_M / 2.0, _north() - ROWS * STEP_M / 2.0)


def ring_seeds(half_width_m: float) -> np.ndarray:
    """Las semillas de un anillo de radio :data:`RING_RADIUS_M` y ``half_width_m`` de semiancho,
    con la cota del terreno (NaN fuera): array nuevo."""
    seeds = np.full((ROWS, COLS), np.nan)
    ring = np.abs(_distance_from_center() - RING_RADIUS_M) <= half_width_m
    seeds[ring] = terrain()[ring]
    return seeds


def disc_seeds() -> np.ndarray:
    """La zona maciza: las celdas de un disco de :data:`DISC_RADIUS_M` con el terreno más un
    ondulado de ±2 m y ruido de 0,3 m (rugosa, el peor caso de la búsqueda exacta; NaN fuera):
    array nuevo."""
    seeds = np.full((ROWS, COLS), np.nan)
    disc = _distance_from_center() <= DISC_RADIUS_M
    rough = (2.0 * np.sin(_east() / 3.1) * np.sin(_north() / 2.3)
             + np.random.default_rng(SEED + 1).normal(0.0, 0.3, (ROWS, COLS)))
    seeds[disc] = (terrain() + rough)[disc]
    return seeds


def preview_seeds() -> np.ndarray:
    """Las semillas de la vista previa de RNF-013-05: las celdas de un disco de
    :data:`PREVIEW_RADIUS_M` (unas 100.000) con el terreno más un ondulado de ±2 m (NaN fuera):
    array nuevo."""
    seeds = np.full((ROWS, COLS), np.nan)
    disc = _distance_from_center() <= PREVIEW_RADIUS_M
    wave = 2.0 * np.sin(_east() / 3.1) * np.sin(_north() / 2.3)
    seeds[disc] = (terrain() + wave)[disc]
    return seeds


# --- Los perfiles y los sectores -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerfProfile:
    """Un perfil de banco de §2.2: su ``code`` y la altura, la cara, la berma y el ancla (m y °)."""

    code: str
    height_m: float
    face_deg: float
    berm_m: float
    anchor_m: float = 125.0

    @property
    def general_tan(self) -> float:
        """El talud general ``h / (h/tan α + B)``."""
        return self.height_m / (self.height_m / math.tan(math.radians(self.face_deg))
                                + self.berm_m)


PROFILES = tuple(PerfProfile(f"perf_{h}_{face}_{berm}", float(h), float(face), float(berm))
                 for h, face, berm in ((10, 60, 6), (10, 70, 8), (10, 55, 8), (10, 65, 6),
                                       (10, 50, 8), (5, 35, 6), (5, 45, 6), (5, 40, 8),
                                       (5, 60, 6), (5, 50, 8)))
"""Los diez perfiles (h 5 o 10 m; cara de 35° a 70°; berma de 6 u 8 m; ancla de 125 m)."""
IMPOSED: dict[int, float] = {5: 10.6, 13: 18.0}
"""El talud general impuesto (°) de los sectores 5 y 13 (plan §2.2)."""


def sector_code(index: int) -> str:
    """El código del sector ``index`` (1 a :data:`SECTORS`)."""
    return f"sector_{index:02d}"


def profile_of(index: int) -> PerfProfile:
    """El perfil que se asigna al sector ``index`` (1 a :data:`SECTORS`): los diez, en rotación."""
    return PROFILES[(index - 1) % len(PROFILES)]


def assigned() -> dict[str, str]:
    """El código del perfil de cada sector (código del sector → código del perfil)."""
    return {sector_code(index): profile_of(index).code for index in range(1, SECTORS + 1)}


def strip_labels() -> np.ndarray:
    """Las etiquetas (int16) de :data:`SECTORS` franjas verticales de igual ancho que cubren toda
    la rejilla: el sector ``k`` es la etiqueta ``k``."""
    columns = (np.arange(COLS) * SECTORS // COLS + 1).astype(np.int16)
    return np.broadcast_to(columns, (ROWS, COLS)).copy()


def sector_boxes() -> tuple[tuple[int, str, str, float, float, float, float], ...]:
    """Las :data:`SECTORS` franjas verticales del perímetro de actuación (a :data:`MARGIN_M` de la
    ventana): ``(índice, código, nombre, oeste, sur, este, norte)`` en coordenadas absolutas."""
    west, south, east, north = cdata.window()
    left, right = west + MARGIN_M, east - MARGIN_M
    width = (right - left) / SECTORS
    found = []
    for index in range(1, SECTORS + 1):
        lo = left + (index - 1) * width
        hi = right if index == SECTORS else left + index * width
        found.append((index, sector_code(index), f"Sector {index:02d}", lo, south + MARGIN_M, hi,
                      north - MARGIN_M))
    return tuple(found)
