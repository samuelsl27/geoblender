# SPDX-License-Identifier: GPL-3.0-or-later
"""Aviso de alturas elipsoidales (spec 006, T13; RF-006-06; plan 006 §5.3.2 y §5.4 A16; D-8).

Una red de seguridad: el datum vertical ya es obligatorio (RF-006-04), pero unas cotas de
GNSS o de dron declaradas como ortométricas y que son elipsoidales quedan unos 50 m por
encima del terreno. :func:`check_vertical_offset` compara las cotas que se importan con un
MDT del proyecto (bilineal del MDT en sus posiciones, A16) y avisa si la **mediana** de
(nueva − MDT) está, en valor absoluto, dentro de la banda de ``gis.vertical.ellipsoidal_band_m``
(40–60 m, extremos incluidos; D-8), con al menos :data:`MIN_SAMPLES` posiciones comunes. Quien
importa (``bl``) pide la confirmación del usuario con :meth:`VerticalCheck.message`
antes de terminar.

La banda es la de la península y Baleares. En Canarias (DP-46) no hay banda ni aviso hasta que
IMGA fije la suya: :func:`ellipsoidal_band` reconoce Canarias porque el centro del MDT cae en
el ámbito geográfico de REGCAN95 (EPSG:4082 y 4083) del catálogo de la 002, sea cual sea el
CRS del proyecto.

Coordenadas ABSOLUTAS en float64, las del MDT de referencia (las cotas nuevas ya
transformadas a su CRS y a su referencia vertical). Las entradas no se modifican.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..core.georef import CrsCatalog, load_catalog, tm_inverse
from . import params
from .messages import render
from .raster import Raster
from .resample import _sample

__all__ = [
    "BAND_KEY",
    "CANARY_CRS_EPSG",
    "MAX_SAMPLES",
    "MIN_SAMPLES",
    "VerticalCheck",
    "check_vertical_offset",
    "ellipsoidal_band",
]

BAND_KEY = "gis.vertical.ellipsoidal_band_m"
MIN_SAMPLES = 100
"""Posiciones comunes (con cota nueva y del MDT) necesarias para avisar (RF-006-06)."""
MAX_SAMPLES = 100_000
"""Posiciones que se comparan como mucho (plan §5.4 A16): si hay más, se toman siempre las
mismas, repartidas por toda la lista."""
CANARY_CRS_EPSG = (4082, 4083)
"""REGCAN95 / UTM 27N y 28N: su ámbito EPSG (``bbox_lonlat``) es el de Canarias (DP-46)."""
MESSAGE_DECIMALS = 1
"""La mediana en el aviso, al decímetro (plan §5.5: «es de 51,3 m»)."""


@dataclass(frozen=True, slots=True)
class VerticalCheck:
    """Resultado de :func:`check_vertical_offset`.

    - ``warn``: hay que avisar y pedir confirmación (RF-006-06).
    - ``median_m``: mediana de (cota nueva − MDT) en m, o ``None`` con menos de
      ``min_samples`` posiciones comunes.
    - ``samples``: posiciones comunes comparadas (≤ :data:`MAX_SAMPLES`).
    - ``positions``: posiciones recibidas con X, Y y Z finitas.
    - ``band_m``: la banda de aviso (|mediana|, m), o ``None`` sin banda (Canarias, DP-46).
    - ``min_samples``: las posiciones comunes exigidas.
    - ``reference``: el nombre del MDT de referencia, para el aviso.
    """

    warn: bool
    median_m: float | None
    samples: int
    positions: int
    band_m: tuple[float, float] | None
    min_samples: int
    reference: str

    def message(self, language: str = "es") -> str | None:
        """El aviso ``gis.ellipsoidal_suspected`` con la mediana al decímetro, o ``None`` si
        no hay que avisar."""
        if not self.warn or self.median_m is None:
            return None
        median = round(self.median_m, MESSAGE_DECIMALS) + 0.0  # sin «-0»
        return render("gis.ellipsoidal_suspected", language=language,
                      dtm=self.reference, median=median)


def ellipsoidal_band(reference: Raster, *,
                     catalog: CrsCatalog | None = None) -> tuple[float, float] | None:
    """La banda de aviso para ``reference``: ``None`` si su centro cae en Canarias (el ámbito
    geográfico de :data:`CANARY_CRS_EPSG` en ``catalog``, por defecto el de la extensión);
    si no, ``gis.vertical.ellipsoidal_band_m`` (península y Baleares, D-8)."""
    if not isinstance(reference, Raster):
        raise TypeError(f"reference debe ser un Raster, no {type(reference).__name__}")
    catalog = load_catalog() if catalog is None else catalog
    grid = reference.grid
    x = grid.west + 0.5 * grid.ncols * grid.dx
    y = grid.north - 0.5 * grid.nrows * grid.dy
    try:
        lon, lat = tm_inverse(x, y, reference.crs.projection)
    except ValueError:  # fuera del alcance de su proyección: no es Canarias ni nada
        lon = lat = float("nan")
    for epsg in CANARY_CRS_EPSG:
        west, south, east, north = catalog.horizontal(epsg).bbox_lonlat
        if west <= lon <= east and south <= lat <= north:
            return None
    band = params.default(BAND_KEY)
    return (float(band[0]), float(band[1]))  # type: ignore[index]


def _positions(xyz: object) -> np.ndarray:
    if not isinstance(xyz, np.ndarray):
        raise TypeError(f"xyz debe ser un array de numpy, no {type(xyz).__name__}")
    if xyz.dtype.kind != "f":
        raise TypeError(f"xyz debe ser de coma flotante, no {xyz.dtype}")
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz debe tener la forma (n, 3), no {xyz.shape}")
    return xyz


def _min_samples(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"min_samples debe ser un entero, no {value!r}")
    if value < 1:
        raise ValueError(f"min_samples debe ser ≥ 1, no {value}")
    return value


def _band(band_m: Sequence[float] | None, reference: Raster,
          catalog: CrsCatalog | None) -> tuple[float, float] | None:
    if band_m is None:
        return ellipsoidal_band(reference, catalog=catalog)
    low, high = params.param(BAND_KEY).check(band_m)  # type: ignore[misc]
    return (low, high)


def check_vertical_offset(
    xyz: np.ndarray,
    reference: Raster,
    *,
    band_m: Sequence[float] | None = None,
    min_samples: int = MIN_SAMPLES,
    name: str = "MDT",
    catalog: CrsCatalog | None = None,
) -> VerticalCheck:
    """Compara las cotas nuevas ``xyz`` ((n, 3), ABSOLUTAS en el CRS y la referencia vertical
    de ``reference``) con el MDT ``reference`` (RF-006-06, A16).

    Se toman las posiciones con X, Y y Z finitas dentro de la extensión del MDT (como mucho
    :data:`MAX_SAMPLES`, siempre las mismas), la bilineal del MDT en ellas (sin dato si le
    falta un vecino) y la mediana de (nueva − MDT) en las comunes. Se avisa si hay al menos
    ``min_samples`` comunes y |mediana| está en ``band_m`` (extremos incluidos). ``band_m``
    ``None`` es la de :func:`ellipsoidal_band` (ninguna en Canarias); una explícita se
    comprueba como el parámetro (``gis.param_*``). ``name`` es el MDT en el aviso.
    Entradas mal formadas: ``TypeError`` o ``ValueError`` (error del programa).
    """
    if not isinstance(reference, Raster):
        raise TypeError(f"reference debe ser un Raster, no {type(reference).__name__}")
    xyz = _positions(xyz)
    minimum = _min_samples(min_samples)
    band = _band(band_m, reference, catalog)
    finite = np.isfinite(xyz).all(axis=1)
    grid = reference.grid
    x, y = xyz[:, 0], xyz[:, 1]
    with np.errstate(invalid="ignore"):
        inside = ((x >= grid.west) & (x <= grid.west + grid.ncols * grid.dx)
                  & (y <= grid.north) & (y >= grid.north - grid.nrows * grid.dy))
    chosen = np.flatnonzero(finite & inside)
    if chosen.size > MAX_SAMPLES:
        chosen = chosen[(np.arange(MAX_SAMPLES, dtype=np.int64) * chosen.size) // MAX_SAMPLES]
    difference = xyz[chosen, 2] - _sample(reference, x[chosen], y[chosen])
    difference = difference[np.isfinite(difference)]
    samples = int(difference.size)
    median = float(np.median(difference)) if samples >= minimum else None
    warn = (median is not None and band is not None
            and band[0] <= abs(median) <= band[1])
    return VerticalCheck(warn=warn, median_m=median, samples=samples,
                         positions=int(np.count_nonzero(finite)), band_m=band,
                         min_samples=minimum, reference=name)
