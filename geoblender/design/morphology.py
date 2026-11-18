# SPDX-License-Identifier: GPL-3.0-or-later
"""La morfología con un disco exacto (spec 016, T05; RF-016-02, RF-016-08; RNF-016-01, RNF-016-03,
RNF-016-04; plan 016 A1, §2.1, §7.3, P-6, D-13): erosión, dilatación, apertura y cierre en escala de
grises y binarias, y el relleno de huecos, en numpy puro, sin dependencia nueva.

- **El disco.** Un disco de radio ``r`` celdas (``radio_m / lado de celda``) es, por cada ``dy`` de
  ``−⌊r⌋`` a ``⌊r⌋``, una fila de semiancho ``w(dy) = ⌊√(r² − dy²)⌋``: las celdas ``(dy, dx)`` con
  ``dx² + dy² ≤ r²``. Es **exacto**, no una aproximación poligonal: la prueba lo compara con la
  fuerza bruta (cada celda contra cada desplazamiento del disco). El cociente ``radio_m / lado`` se
  toma con una tolerancia de 10⁻⁹ celdas (``0,3 / 0,1`` da 2,9999999999999996), que no cambia ningún
  disco de radio entero o de media celda.
- **Por qué descompuesto por anchos.** Con el disco de 31 m de diámetro sobre celdas de 1 m
  (``r = 15,5``) son unas 800 comparaciones por celda: un bucle por vecino son decenas de segundos
  sobre 2,81 M celdas. Aquí el filtro de mínimo (o de máximo) con una ventana de ``2w + 1`` filas se
  hace con van Herk–Gil–Werman (prefijo y sufijo por bloques de ``2w + 1`` filas, O(1) por celda; cada
  paso del prefijo o del sufijo es una operación de numpy sobre todos los bloques y todas las columnas
  a la vez, que con el numpy de Blender resulta más rápida que ``ufunc.accumulate`` por el eje del
  bloque), **una vez por cada ``w`` distinto** (10 para ``r = 15,5``); el resultado es el mínimo (o el
  máximo) de esas ventanas desplazadas en columnas, una por cada ``dx`` (las de igual ``w``, con la
  misma ventana). El disco es simétrico: el eje que lleva la ventana es indiferente.
- **Los bordes y los huecos.** Las celdas fuera de la rejilla no cuentan (el elemento neutro de cada
  operación: la rejilla es todo lo que hay), así que ``abrir(a) ≤ a ≤ cerrar(a)`` también junto al
  borde; una máscara que toca el borde no se erosiona desde él. En una rejilla de reales, ``NaN`` es
  «sin dato» y tampoco cuenta; una celda cuyo disco entero está sin dato sale ``NaN``. Un infinito sí
  es un error (``ValueError``): no es una cota. Las máscaras son de ``bool`` y se devuelven de
  ``bool``; el resto de los tipos devuelven su tipo.
- **Por bandas.** Cada banda de filas lee solo las de su disco (``⌊r⌋`` por arriba y por abajo; los
  cortes de la rejilla, como celdas ausentes) y da las suyas: el resultado es igual **bit a bit** que
  el de una pieza (mínimos y máximos son exactos). La **apertura** son dos fases: erosionar todas las
  bandas y dilatar lo erosionado (la dilatación de una banda necesita las filas vecinas ya erosionadas).
  :func:`opening_steps` y compañía las dan por pasos de ``budget_s`` como mucho (una banda de
  :data:`BAND_ROWS` filas, unos 10 ms sobre 1.700 columnas); cerrarlos a mitad no deja nada.
- :func:`fill_holes`: los huecos interiores de una máscara son las componentes (4-conexas,
  :func:`design.grids.label_components`) de su complementaria, rodeada de un marco, que no son la del
  marco, esto es, que no tocan el borde de la rejilla.

Ninguna entrada se modifica: cada llamada da arrays nuevos. Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from .grids import label_components
from .seeds import pace_progress

__all__ = [
    "BAND_ROWS",
    "closing",
    "closing_steps",
    "dilate",
    "dilate_steps",
    "erode",
    "erode_steps",
    "fill_holes",
    "opening",
    "opening_steps",
]

BAND_ROWS = 32
"""Las filas de cada unidad de trabajo de las variantes por pasos (plan 016 A1: 21 ms previstos sobre
1.699 columnas con el disco de 31 m de diámetro; medidos en la T05, 9 ms; con 16 filas, 5 ms; con 64, 18 ms)."""
_TOLERANCE = 1e-9
"""Lo que se suma al radio en celdas antes de tomar el suelo de cada semiancho (el cociente
``radio_m / lado`` puede quedarse una unidad en el último decimal por debajo de un entero)."""
_PHASE = "morphology"

_ERODE, _DILATE = "erode", "dilate"
_OPERATIONS: dict[str, Callable[..., np.ndarray]] = {_ERODE: np.minimum, _DILATE: np.maximum}


@dataclass(frozen=True, slots=True)
class _Disk:
    """Un disco en celdas: ``widths[d]`` es el semiancho ``w(d)`` de la fila a ``d`` filas del centro
    (``d`` de 0 a ``⌊r⌋``; no crece con ``d``)."""

    widths: tuple[int, ...]

    @property
    def reach(self) -> int:
        """El alcance en filas y en columnas (``⌊r⌋``)."""
        return len(self.widths) - 1


def _disk(radius_m: float, cell: float) -> _Disk:
    """El disco de ``radius_m`` m sobre celdas de ``cell`` m. ``ValueError`` si el radio no es un
    número finito ≥ 0 o el lado no es un número finito > 0."""
    for name, value in (("el radio", radius_m), ("el lado de la celda", cell)):
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)) \
                or not math.isfinite(float(value)):
            raise ValueError(f"{name} es un número finito, no {value!r}")
    if radius_m < 0:
        raise ValueError(f"el radio no es negativo: {radius_m!r}")
    if cell <= 0:
        raise ValueError(f"el lado de la celda es positivo: {cell!r}")
    r = float(radius_m) / float(cell) + _TOLERANCE
    reach = math.floor(r)
    square = r * r
    return _Disk(tuple(math.floor(math.sqrt(square - d * d)) for d in range(reach + 1)))


def _grid(a: object) -> np.ndarray:
    """``a`` como rejilla de 2 dimensiones de booleanos, enteros o reales (``ValueError`` si no)."""
    found = np.asarray(a)
    if found.ndim != 2:
        raise ValueError(f"la rejilla es de 2 dimensiones, no de {found.ndim}")
    if found.dtype.kind not in "biuf":
        raise ValueError(f"la rejilla es de booleanos, enteros o reales, no {found.dtype}")
    return found


def _has_nan(found: np.ndarray) -> bool:
    """Si una rejilla de reales tiene ``NaN`` («sin dato»); ``ValueError`` si tiene un infinito."""
    if found.dtype.kind != "f" or np.isfinite(found).all():
        return False
    if np.isinf(found).any():
        raise ValueError("la rejilla tiene celdas infinitas: solo puede tener NaN como «sin dato»")
    return True


def _neutral(dtype: np.dtype, operation: str) -> object:
    """El elemento neutro de ``operation`` en ``dtype``: lo que no cambia un mínimo (``erode``) o un
    máximo (``dilate``)."""
    high = operation == _ERODE
    if dtype.kind == "b":
        return high
    if dtype.kind == "f":
        return np.inf if high else -np.inf
    info = np.iinfo(dtype)
    return info.max if high else info.min


def _window_rows(band: np.ndarray, origin: int, start: int, stop: int, half: int,
                 operation: str, neutral: object) -> np.ndarray:
    """El filtro de ventana de ``2 · half + 1`` filas (van Herk–Gil–Werman) de las filas ``start`` a
    ``stop − 1`` de la rejilla de la que ``band`` son las filas desde ``origin``: para cada columna,
    el mínimo o el máximo de las filas ``y − half … y + half`` que haya en la rejilla (``band`` ya las
    lleva todas las que hacen falta). El resultado, de ``stop − start`` filas, puede ser una vista."""
    if half == 0:
        return band[start - origin:stop - origin]
    ufunc = _OPERATIONS[operation]
    size = 2 * half + 1
    height = stop - start
    blocks = -(-(height + 2 * half) // size)
    padded = np.full((blocks * size, band.shape[1]), neutral, dtype=band.dtype)
    low = max(origin, start - half)
    high = min(origin + band.shape[0], stop + half)
    padded[low - (start - half):high - (start - half)] = band[low - origin:high - origin]
    cut = padded.reshape(blocks, size, band.shape[1])
    prefix = np.empty_like(cut)  # el mínimo (o máximo) desde el principio de su bloque
    prefix[:, 0] = cut[:, 0]
    for j in range(1, size):
        ufunc(prefix[:, j - 1], cut[:, j], out=prefix[:, j])
    suffix = np.empty_like(cut)  # y hasta el final de su bloque
    suffix[:, size - 1] = cut[:, size - 1]
    for j in range(size - 2, -1, -1):
        ufunc(suffix[:, j + 1], cut[:, j], out=suffix[:, j])
    # La ventana de la fila t cubre las filas t … t + size − 1 de ``padded``: un bloque entero, o el
    # final del bloque de t y el principio del siguiente.
    return ufunc(suffix.reshape(-1, band.shape[1])[:height],
                 prefix.reshape(-1, band.shape[1])[size - 1:size - 1 + height])


def _fold_band(source: np.ndarray, target: np.ndarray, start: int, stop: int, disk: _Disk,
               operation: str, neutral: object, nan: bool) -> None:
    """Las filas ``start`` a ``stop − 1`` de ``target`` (nuevo, de la forma de ``source``): el mínimo
    (``erode``) o el máximo (``dilate``) de ``source`` en el disco, leyendo solo sus filas
    ``start − ⌊r⌋ … stop + ⌊r⌋ − 1`` (las que haya)."""
    rows, columns = source.shape
    ufunc = _OPERATIONS[operation]
    band_low, band_high = max(0, start - disk.reach), min(rows, stop + disk.reach)
    band = source[band_low:band_high]
    if nan:  # «sin dato» no cuenta: el neutro (el infinito que no es un dato)
        band = np.where(np.isnan(band), neutral, band)
    out = target[start:stop]
    out.fill(neutral)
    reach = min(disk.reach, columns - 1)  # más allá de la rejilla no hay columnas que mirar
    d = 0
    while d <= reach:
        width = disk.widths[d]
        last = d
        while last + 1 <= reach and disk.widths[last + 1] == width:
            last += 1
        # Las filas a ``d … last`` columnas del centro tienen el mismo semiancho: su ventana, una vez.
        window = _window_rows(band, band_low, start, stop, min(width, rows - 1), operation, neutral)
        for shift in range(d, last + 1):
            ufunc(out[:, :columns - shift], window[:, shift:], out=out[:, :columns - shift])
            if shift:
                ufunc(out[:, shift:], window[:, :columns - shift], out=out[:, shift:])
        d = last + 1
    if nan:  # lo que no tenía ningún dato en su disco
        out[out == neutral] = np.nan


def _units(source: np.ndarray, disk: _Disk, operations: tuple[str, ...], band_rows: int,
           nan: bool) -> Generator[None, None, np.ndarray]:
    """Las unidades (una banda cada una) de aplicar ``operations`` una tras otra a ``source``; da el
    resultado. Cada fase lee entera la anterior (la dilatación necesita las filas vecinas ya
    erosionadas) y escribe una rejilla nueva."""
    rows = source.shape[0]
    current = source
    for operation in operations:
        neutral = _neutral(source.dtype, operation)
        target = np.empty_like(source)
        for start in range(0, rows, band_rows):
            _fold_band(current, target, start, min(rows, start + band_rows), disk, operation,
                       neutral, nan)
            yield None
        current = target
    return current


def _prepare(a: object, radius_m: float, cell: float) -> tuple[np.ndarray, _Disk, bool]:
    """La rejilla, el disco y si la rejilla tiene ``NaN`` (los rechazos, antes de calcular)."""
    disk = _disk(radius_m, cell)
    found = _grid(a)
    return found, disk, _has_nan(found)


def _run(a: object, radius_m: float, cell: float, operations: tuple[str, ...],
         band_rows: int | None) -> np.ndarray:
    found, disk, nan = _prepare(a, radius_m, cell)
    if band_rows is not None and (isinstance(band_rows, bool)
                                  or not isinstance(band_rows, (int, np.integer)) or band_rows < 1):
        raise ValueError(f"las filas de cada banda son un entero ≥ 1, no {band_rows!r}")
    size = max(1, found.shape[0] if band_rows is None else int(band_rows))
    work = _units(found, disk, operations, size, nan)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: np.ndarray = done.value
            return result


def _steps(a: object, radius_m: float, cell: float, operations: tuple[str, ...], budget_s: float,
           running: str, finished: str) -> Iterator[Progress]:
    found, disk, nan = _prepare(a, radius_m, cell)
    return pace_progress(_units(found, disk, operations, BAND_ROWS, nan), budget_s, phase=_PHASE,
                         running=running, finished=finished)


def erode(a: np.ndarray, radius_m: float, cell: float, *, band_rows: int | None = None) -> np.ndarray:
    """La erosión de ``a`` con un disco exacto de ``radius_m`` m sobre celdas de ``cell`` m: el
    mínimo de ``a`` en el disco centrado en cada celda (en una máscara, ``True`` si todas las celdas
    de su disco lo son). Véase el módulo para los bordes, ``NaN`` y los tipos. ``band_rows``: las
    filas de cada banda (``None``: la rejilla de una pieza; el resultado es el mismo bit a bit).
    ``ValueError`` si ``a`` no es una rejilla de booleanos, enteros o reales, de 2 dimensiones y sin
    infinitos, o si el radio o el lado de la celda no son números válidos."""
    return _run(a, radius_m, cell, (_ERODE,), band_rows)


def dilate(a: np.ndarray, radius_m: float, cell: float, *, band_rows: int | None = None
           ) -> np.ndarray:
    """La dilatación de ``a`` con un disco exacto de ``radius_m`` m sobre celdas de ``cell`` m: el
    máximo de ``a`` en el disco centrado en cada celda (en una máscara, ``True`` si alguna celda de
    su disco lo es). Como :func:`erode` en todo lo demás."""
    return _run(a, radius_m, cell, (_DILATE,), band_rows)


def opening(a: np.ndarray, radius_m: float, cell: float, *, band_rows: int | None = None
            ) -> np.ndarray:
    """La apertura de ``a``: :func:`erode` y después :func:`dilate` con el mismo disco (lo que un
    disco de ese radio puede tocar por dentro; ``abrir(a) ≤ a``). Como :func:`erode` en todo lo
    demás; con ``band_rows``, las dos fases por bandas."""
    return _run(a, radius_m, cell, (_ERODE, _DILATE), band_rows)


def closing(a: np.ndarray, radius_m: float, cell: float, *, band_rows: int | None = None
            ) -> np.ndarray:
    """El cierre de ``a``: :func:`dilate` y después :func:`erode` con el mismo disco (``cerrar(a) ≥
    a``). Como :func:`opening` en todo lo demás."""
    return _run(a, radius_m, cell, (_DILATE, _ERODE), band_rows)


def erode_steps(a: np.ndarray, radius_m: float, cell: float, *, budget_s: float = STEP_BUDGET_S
                ) -> Iterator[Progress]:
    """:func:`erode` por pasos de ``budget_s`` como mucho (una o más bandas de :data:`BAND_ROWS`
    filas cada uno): el último ``Progress`` (fase ``morphology``) lleva la rejilla en ``result``. Los
    rechazos de :func:`erode`, en la llamada. Cerrar el generador a mitad no deja nada."""
    return _steps(a, radius_m, cell, (_ERODE,), budget_s, "Erosionando…", "Erosión hecha")


def dilate_steps(a: np.ndarray, radius_m: float, cell: float, *, budget_s: float = STEP_BUDGET_S
                 ) -> Iterator[Progress]:
    """:func:`dilate` por pasos, como :func:`erode_steps`."""
    return _steps(a, radius_m, cell, (_DILATE,), budget_s, "Dilatando…", "Dilatación hecha")


def opening_steps(a: np.ndarray, radius_m: float, cell: float, *, budget_s: float = STEP_BUDGET_S
                  ) -> Iterator[Progress]:
    """:func:`opening` por pasos, como :func:`erode_steps`: las dos fases (erosionar todas las
    bandas y dilatar lo erosionado) en una sola sucesión de pasos."""
    return _steps(a, radius_m, cell, (_ERODE, _DILATE), budget_s, "Abriendo la superficie…",
                  "Apertura hecha")


def closing_steps(a: np.ndarray, radius_m: float, cell: float, *, budget_s: float = STEP_BUDGET_S
                  ) -> Iterator[Progress]:
    """:func:`closing` por pasos, como :func:`opening_steps`."""
    return _steps(a, radius_m, cell, (_DILATE, _ERODE), budget_s, "Cerrando la superficie…",
                  "Cierre hecho")


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """``mask`` con sus **huecos interiores** rellenos (una máscara de ``bool`` nueva): las celdas
    que no son de ``mask`` y no se pueden alcanzar desde el borde de la rejilla pasando solo por
    celdas que tampoco lo son (4-conexión, como las zonas de :func:`design.grids.label_components`).
    Lo que toca el borde no es un hueco. ``ValueError`` si ``mask`` no es de 2 dimensiones."""
    found = np.asarray(mask)
    if found.ndim != 2:
        raise ValueError(f"la máscara es una rejilla de 2 dimensiones, no de {found.ndim}")
    inside = found.astype(bool, copy=False)
    if inside.size == 0:
        return inside.copy()
    framed = np.ones((inside.shape[0] + 2, inside.shape[1] + 2), dtype=bool)
    framed[1:-1, 1:-1] = ~inside
    labels = label_components(framed)
    outside = labels.grid[0, 0]  # el marco es una sola componente: lo que se le une es el exterior
    return inside | ((labels.grid != outside)[1:-1, 1:-1] & ~inside)
