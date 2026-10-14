# SPDX-License-Identifier: GPL-3.0-or-later
"""Arrays de la vista 3D de los sondeos (spec 005, T17; RF-005-23, RF-005-24, RF-005-25;
plan 005 §5.3.2 y §5.4, «Vista»; D9 y D10 del plan).

``bl/scene`` crea con ellos las curvas ``POLY`` (los tubos de Geometry Nodes) y la malla de
las barras, y ``bl/draw`` las etiquetas y las leyendas: aquí se calcula todo y allí solo se
crean objetos y se dibuja (constitución, principio 3). Las coordenadas son **absolutas** y en
float64, en el CRS y la referencia vertical del conjunto de sondeos; ``bl/scene`` resta el
GeoOrigin con ``core.georef.world_to_local`` antes de pasar a float32 (ADR-0005). Las
profundidades y los puntos salen de :mod:`.desurvey` (``polyline_md`` y ``md_to_xyz``): están
sobre la misma curva que la traza (RF-005-21).

**Curvas de litología** (:func:`lithology_curves`; RF-005-23): de cada sondeo con traza, una
curva por tramo del esquema de logueo elegido y una por hueco sin dato (de la boca al primer
tramo, entre tramos y del último al fondo de la traza), con sus dos límites y los puntos de la
traza cada ≤ ``max_step_m`` (``dh.desurvey.trace_step_m``) entre ellos. Una curva por tramo, y
no una por sondeo, deja el color nítido en los contactos (D9). El hueco se mide desde el hasta
más hondo de los tramos anteriores: dos tramos solapados se dibujan los dos (el solape es
DH-E10 de la validación). Un tramo imposible (sin desde o sin hasta, desde < 0 o desde ≥ hasta)
no se dibuja: queda en el hueco. Color de cada punto: el de su litología en el catálogo del
esquema (``#RRGGBB``, sRGB) pasado a **lineal** (:func:`srgb_to_linear`: los atributos
``FLOAT_COLOR`` de Blender son lineales); los huecos y los códigos sin catálogo (DH-E11), gris
(:data:`NO_DATA_COLOR`, el de una litología sin color).

**Barras de leyes** (:func:`grade_bars`; RF-005-24): junto a cada tramo analizado del elemento,
un cuadrilátero en la horizontal perpendicular a la traza, a su **derecha** según se baja
(azimut + 90°; al **este** en un tramo vertical), de ``offset_m`` a ``offset_m + width_m`` del
eje. Sin ``max_step_m``, una cara por tramo, entre sus dos límites; con él, una por cada parte
de ≤ ``max_step_m`` de la traza (la barra sigue un sondeo curvo). Cada cara es plana (sus dos
lados largos, paralelos a su cuerda) y lleva el color de la clase de su valor en la leyenda.
Se dibujan los valores primarios del elemento (sin distinguir mayúsculas) con tramo posible y
sondeo con traza: con valor (también «>x», por su valor) o bajo el límite de detección («< x»,
clase «< LD»); no, los vacíos, los no analizados, los duplicados ni los de otra unidad que la
de la leyenda (sin convertir, DH-W07: se cuentan en ``skipped_units``).

**Leyenda de clases** (:class:`GradeLegend`, :func:`default_grade_legend`; RF-005-24):
editable, en la unidad del elemento: cortes crecientes y un color por clase; un valor justo en
un corte es de la clase de arriba. Más la clase «< LD» (:data:`BELOW_DL_COLOR`). Por defecto,
5 clases por quintiles (``numpy.quantile``, interpolación lineal) de :func:`grade_values`,
redondeados a 2 cifras significativas (cortes repetidos, una vez), con los colores de
:data:`DEFAULT_RAMP`. La leyenda de la litología, :func:`lithology_legend`.

**Etiquetas** (:func:`labels`; RF-005-25): en la boca de cada sondeo con X, Y, Z, su nombre y
su profundidad total con dos decimales en el formato del idioma («S-12 (160,00 m)»; sin
profundidad, solo el nombre) y, si se pide, la profundidad en el fondo de su traza
(«160,00 m»).

**Lo que excluye la validación** (RF-005-17; ``validate.Exclusions``, opcional): un sondeo con
un error de alcance S no se dibuja; la tabla de un esquema o de un elemento con un error de
alcance T no se pinta en ese sondeo (su traza queda en gris; sus barras no salen), y un
registro con un error de alcance R tampoco.

Nada modifica la entrada. Python puro y numpy (ADR-0004); vectorial salvo los textos.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..core.i18n import format_number, tr
from .desurvey import Traces, md_to_xyz, polyline_md
from .model import (
    DEFAULT_COLOR,
    AssayColumns,
    DetectionFlag,
    DrillholeSet,
    name_key,
)
from .validate import TABLE_NAMES, Exclusions

__all__ = [
    "BELOW_DL_COLOR",
    "DEFAULT_RAMP",
    "LABEL_DECIMALS",
    "NO_DATA_COLOR",
    "TEXT_UNIT",
    "VERTICAL_TOLERANCE",
    "BarArrays",
    "CurveArrays",
    "GradeLegend",
    "Label",
    "LegendEntry",
    "default_grade_legend",
    "grade_bars",
    "grade_values",
    "labels",
    "lithology_curves",
    "lithology_legend",
    "srgb_to_linear",
]

NO_DATA_COLOR = DEFAULT_COLOR
"""El gris de los huecos sin dato y de los códigos sin catálogo (sRGB)."""
BELOW_DL_COLOR = "#C8C8C8"
"""El color por defecto de la clase «< LD» (sRGB): un gris claro, distinto del de sin dato."""
DEFAULT_RAMP: tuple[str, ...] = ("#2C7BB6", "#3FA34D", "#F2D43D", "#F28C28", "#D7263D")
"""Los colores por defecto de las clases de leyes, de la más baja a la más alta (sRGB); con
otro número de clases, se interpolan."""
TEXT_UNIT = "text"
"""La unidad de un elemento de texto: no tiene leyenda de clases."""
LABEL_DECIMALS = 2
"""Los decimales de la profundidad en las etiquetas («S-12 (160,00 m)»)."""
VERTICAL_TOLERANCE = 1e-9
"""Una cuerda es vertical (barra al este) si su parte horizontal no pasa de esta fracción de
su longitud."""

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_NUMBERS = (int, float, np.integer, np.floating)
_SIGNIFICANT = 2  # cifras significativas de los cortes de la leyenda por defecto
_RGBA = 4
_LITHOLOGY = TABLE_NAMES["lithology"]
_ASSAY = TABLE_NAMES["assays"]
_FLAGS = AssayColumns.code_values("detection_flag")
_OK = _FLAGS.index(DetectionFlag.OK)
_BELOW_DL = _FLAGS.index(DetectionFlag.BELOW_DL)
_ABOVE_UL = _FLAGS.index(DetectionFlag.ABOVE_UL)


# --- Colores ---------------------------------------------------------------------------------


def _color(value: object, what: str) -> str:
    """Un color «#RRGGBB» en mayúsculas; ``TypeError``/``ValueError`` si no lo es."""
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto «#RRGGBB», no {value!r}")
    if not _COLOR.fullmatch(value):
        raise ValueError(f"{what} es un color «#RRGGBB» (sRGB), no {value!r}")
    return value.upper()


def srgb_to_linear(colors: Iterable[str]) -> np.ndarray:
    """Los colores «#RRGGBB» (sRGB, como los del catálogo) en lineal con alfa 1: float32
    (n, 4), como los atributos ``FLOAT_COLOR`` de Blender. Cada canal c = valor/255 pasa por
    la curva de IEC 61966-2-1: c/12,92 hasta 0,04045 y ((c + 0,055)/1,055)^2,4 por encima."""
    if isinstance(colors, str):
        raise TypeError(f"srgb_to_linear recibe una lista de colores, no un texto: {colors!r}")
    found = [_color(value, "un color") for value in colors]
    channels = np.array([[int(c[k:k + 2], 16) for k in (1, 3, 5)] for c in found],
                        dtype=np.float64).reshape(-1, 3) / 255.0
    linear = np.where(channels <= 0.04045, channels / 12.92,
                      ((channels + 0.055) / 1.055) ** 2.4)
    result = np.ones((len(found), _RGBA), dtype=np.float32)
    result[:, :3] = linear
    return result


def _linear_of(colors: np.ndarray) -> np.ndarray:
    """:func:`srgb_to_linear` de un array de colores (object), cada color distinto una vez."""
    unique, inverse = np.unique(colors.astype(str), return_inverse=True)
    return srgb_to_linear(unique.tolist())[inverse.reshape(-1)]


@dataclass(frozen=True, slots=True)
class LegendEntry:
    """Una entrada de una leyenda: su texto, su color «#RRGGBB» (sRGB) y, en la litología, la
    descripción del código."""

    label: str
    color: str
    description: str | None = None

    @property
    def linear(self) -> tuple[float, float, float, float]:
        """El color en lineal con alfa 1 (:func:`srgb_to_linear`)."""
        r, g, b, a = srgb_to_linear([self.color])[0].tolist()
        return r, g, b, a


# --- Comprobaciones ---------------------------------------------------------------------------


def _check_set(dset: object, excluded: object = None) -> None:
    """``dset`` es un ``DrillholeSet`` y ``excluded``, ``None`` o sus exclusiones."""
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"la vista se calcula sobre un DrillholeSet, no {dset!r}")
    if excluded is not None:
        if not isinstance(excluded, Exclusions):
            raise TypeError(f"lo excluido es un Exclusions de la validación, no {excluded!r}")
        holes = len(dset.collars)
        if np.shape(excluded.holes) != (holes,):
            raise ValueError(f"lo excluido es de {np.size(excluded.holes)} bocas y el conjunto "
                             f"de sondeos tiene {holes}")


def _check_inputs(dset: object, traces: object, excluded: object) -> None:
    """:func:`_check_set` y ``traces``, las trazas de ``dset`` (una boca por boca)."""
    _check_set(dset, excluded)
    if not isinstance(traces, Traces):
        raise TypeError(f"la vista se calcula con unas Traces, no {traces!r}")
    holes = len(dset.collars)  # dset ya es un DrillholeSet
    if traces.hole_start.size != holes + 1:
        raise ValueError(f"las trazas son de {traces.hole_start.size - 1} bocas y el conjunto "
                         f"de sondeos tiene {holes}: no son sus trazas")


def _length(value: object, what: str, *, zero: bool) -> float:
    """Una distancia (m) finita, positiva (o ≥ 0 si ``zero``)."""
    if isinstance(value, bool) or not isinstance(value, _NUMBERS):
        raise TypeError(f"{what} es un número de metros, no {value!r}")
    found = float(value)
    if not math.isfinite(found) or found < 0.0 or (found == 0.0 and not zero):
        raise ValueError(f"{what} es un número de metros finito y {'≥ 0' if zero else '> 0'}, "
                         f"no {value!r}")
    return found


def _matches(texts: np.ndarray, key: str) -> np.ndarray:
    """Si cada texto (o ``None``) de ``texts`` es ``key`` sin mayúsculas ni espacios
    exteriores; cada texto distinto se compara una vez."""
    seen: dict[object, bool] = {}

    def check(text: object) -> bool:
        found = seen.get(text)
        if found is None:
            found = seen[text] = isinstance(text, str) and name_key(text) == key
        return found

    return np.fromiter(map(check, texts.tolist()), dtype=np.bool_, count=len(texts))


def _drawn_holes(dset: DrillholeSet, traces: Traces | None,
                 excluded: Exclusions | None) -> np.ndarray:
    """Los sondeos que se dibujan: con traza (si hay ``traces``) y sin un error S."""
    holes = (traces.computed.copy() if traces is not None
             else np.ones(len(dset.collars), dtype=np.bool_))
    if excluded is not None:
        holes &= ~np.asarray(excluded.holes, dtype=np.bool_)
    return holes


def _table_excluded(excluded: Exclusions | None, table: str, key: str, count: int
                    ) -> np.ndarray:
    """Los sondeos con la tabla ``table`` del esquema o del elemento ``key`` excluida (T)."""
    mask = np.zeros(count, dtype=np.bool_)
    if excluded is not None:
        for hole, name, which in excluded.tables:
            if name == table and which is not None and name_key(which) == key and hole >= 0:
                mask[hole] = True
    return mask


def _record_excluded(excluded: Exclusions | None, table: str, count: int) -> np.ndarray:
    """Las filas de ``table`` excluidas (R)."""
    mask = np.zeros(count, dtype=np.bool_)
    if excluded is not None:
        rows = [row for name, row in excluded.records if name == table and 0 <= row < count]
        mask[rows] = True
    return mask


def _possible(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """Los tramos con desde y hasta finitos, desde ≥ 0 y desde < hasta."""
    with np.errstate(invalid="ignore"):
        return np.isfinite(start) & np.isfinite(end) & (start >= 0.0) & (start < end)


# --- Puntos sobre la traza --------------------------------------------------------------------


def _vertex_at(vhole: np.ndarray, vmd: np.ndarray, hole: np.ndarray, md: np.ndarray
               ) -> np.ndarray:
    """El vértice (sus posiciones, ordenadas por sondeo y profundidad) de cada (``hole``,
    ``md``), que está entre ellos exactamente. Vértices y consultas se ordenan juntos por
    (sondeo, profundidad, vértice antes que consulta): exacto, sin claves sumadas."""
    count = vmd.size
    query = np.zeros(count + md.size, dtype=np.bool_)
    query[count:] = True
    order = np.lexsort((query, np.concatenate((vmd, md)), np.concatenate((vhole, hole))))
    upto = np.cumsum(~query[order])
    rank = np.empty_like(order)
    rank[order] = np.arange(order.size)
    found = upto[rank[count:]] - 1
    if found.size and not (np.array_equal(vmd[found], md) and np.array_equal(vhole[found], hole)):
        raise RuntimeError("un límite de tramo no está entre los vértices de la polilínea")
    return found


def _ranges(start: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """Las posiciones ``start[k]`` … ``start[k] + sizes[k] − 1`` de cada k, seguidas."""
    total = int(sizes.sum())
    first = np.repeat(np.cumsum(sizes) - sizes, sizes)
    return np.repeat(start, sizes) + (np.arange(total, dtype=np.int64) - first)


def _segments(traces: Traces, hole: np.ndarray, start: np.ndarray, end: np.ndarray,
              max_step_m: float | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los puntos de cada tramo (``hole``, ``start``, ``end``) sobre la traza: el número de
    cada uno (int64), su profundidad y su posición absoluta. Sin ``max_step_m``, sus dos
    límites; con él, los vértices de ``desurvey.polyline_md`` de ``start`` a ``end``."""
    if max_step_m is None:
        sizes = np.full(hole.size, 2, dtype=np.int64)
        md = np.column_stack((start, end)).reshape(-1)
        point_hole = np.repeat(hole, 2)
    else:
        extra: dict[int, np.ndarray] = {}
        if hole.size:
            order = np.argsort(hole, kind="stable")
            keys, first = np.unique(hole[order], return_index=True)
            limits = np.split(order, first[1:])
            extra = {int(k): np.concatenate((start[rows], end[rows]))
                     for k, rows in zip(keys.tolist(), limits, strict=True)}
        offsets, vmd = polyline_md(traces, extra, max_step_m)
        vhole = np.repeat(np.arange(offsets.size - 1, dtype=np.int64), np.diff(offsets))
        low = _vertex_at(vhole, vmd, hole, start)
        sizes = _vertex_at(vhole, vmd, hole, end) - low + 1
        index = _ranges(low, sizes)
        md, point_hole = vmd[index], vhole[index]
    if not md.size:
        return sizes, np.zeros(0), np.zeros((0, 3))
    return sizes, md, md_to_xyz(traces, point_hole, md)


# --- Curvas de litología ----------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CurveArrays:
    """Las curvas de la litología de un esquema (véase el módulo), en orden de sondeo y
    profundidad:

    - por curva: ``curve_sizes`` (int32, sus puntos), ``hole`` (int32, la posición de la boca),
      ``from_m`` y ``to_m`` (float64), ``code`` (object, el código tal como venía; ``None`` en
      un hueco) y ``row`` (int64, la fila de ``dset.lithology``; −1 en un hueco);
    - por punto: ``points_abs`` (float64, (n, 3), absolutos), ``md`` (float64, su profundidad)
      y ``color_linear`` (float32, (n, 4), lineal con alfa 1).
    """

    curve_sizes: np.ndarray
    hole: np.ndarray
    from_m: np.ndarray
    to_m: np.ndarray
    code: np.ndarray
    row: np.ndarray
    points_abs: np.ndarray
    md: np.ndarray
    color_linear: np.ndarray


def _gaps(hole: np.ndarray, start: np.ndarray, end: np.ndarray, drawn: np.ndarray,
          traces: Traces) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los huecos sin dato (sondeo, desde, hasta) de los sondeos ``drawn`` con los tramos
    ``hole``, ``start``, ``end`` (ordenados por sondeo y desde): entre el comienzo de la traza
    o el hasta más hondo anterior y el desde siguiente, y del más hondo al fondo de la traza."""
    # El primer y el último nodo de cada sondeo (los de uno sin traza no se usan).
    if traces.md.size:
        first_md = traces.md[np.minimum(traces.hole_start[:-1], traces.md.size - 1)]
        last_md = traces.md[np.maximum(traces.hole_start[1:] - 1, 0)]
    else:
        first_md = last_md = np.zeros(drawn.size)
    if hole.size:
        first = np.ones(hole.size, dtype=np.bool_)
        first[1:] = hole[1:] != hole[:-1]
        last = np.ones(hole.size, dtype=np.bool_)
        last[:-1] = first[1:]
        # El hasta más hondo hasta cada tramo, por sondeo: exacto, sobre el rango de cada
        # valor (como ``validate``), sin sumar desplazamientos a los números.
        unique, rank = np.unique(end, return_inverse=True)
        group = np.cumsum(first, dtype=np.int64) - 1
        key = group * unique.size + rank.reshape(-1)
        deepest = unique[np.maximum.accumulate(key) - group * unique.size]
        previous = np.empty(hole.size)
        previous[1:] = deepest[:-1]
        previous[first] = first_md[hole[first]]
        before = start > previous
        after = last & (deepest < last_md[hole])
    else:
        previous = deepest = np.zeros(0)
        before = after = np.zeros(0, dtype=np.bool_)
    empty = np.flatnonzero(drawn & (np.bincount(hole, minlength=drawn.size) == 0))
    gap_hole = np.concatenate((hole[before], hole[after], empty))
    gap_start = np.concatenate((previous[before], deepest[after], first_md[empty]))
    gap_end = np.concatenate((start[before], last_md[hole[after]], last_md[empty]))
    return gap_hole, gap_start, gap_end


def lithology_curves(dset: DrillholeSet, traces: Traces, log_set: str, max_step_m: float,
                     *, excluded: Exclusions | None = None) -> CurveArrays:
    """Las curvas de la litología del esquema ``log_set`` (sin distinguir mayúsculas) de los
    sondeos de ``dset`` con traza en ``traces`` (las suyas), con puntos cada ≤ ``max_step_m``
    (m) y sin lo que excluye ``excluded`` (RF-005-23, RF-005-17; véase el módulo).

    ``TypeError``/``ValueError`` con unas trazas o unas exclusiones de otro conjunto, un
    esquema que no es un texto o un paso que no es positivo y finito."""
    _check_inputs(dset, traces, excluded)
    if not isinstance(log_set, str):
        raise TypeError(f"el esquema de logueo es un texto, no {log_set!r}")
    step = _length(max_step_m, "el paso de la vista", zero=False)
    key = name_key(log_set)
    count = len(dset.collars)
    drawn = _drawn_holes(dset, traces, excluded)
    painted = drawn & ~_table_excluded(excluded, _LITHOLOGY, key, count)

    lithology = dset.lithology
    hole_all = lithology.hole
    linked = hole_all >= 0
    keep = linked.copy()
    keep[linked] = painted[hole_all[linked]]
    keep &= (_matches(lithology.log_set, key) & _possible(lithology.from_m, lithology.to_m)
             & ~_record_excluded(excluded, _LITHOLOGY, len(lithology)))
    rows = np.flatnonzero(keep)
    rows = rows[np.lexsort((rows, lithology.to_m[rows], lithology.from_m[rows],
                            hole_all[rows]))]
    hole, start, end = hole_all[rows], lithology.from_m[rows], lithology.to_m[rows]
    gap_hole, gap_start, gap_end = _gaps(hole, start, end, drawn, traces)

    # Tramos y huecos juntos, por sondeo, desde, hasta y fila (los huecos, −1).
    all_hole = np.concatenate((hole, gap_hole))
    all_start = np.concatenate((start, gap_start))
    all_end = np.concatenate((end, gap_end))
    all_row = np.concatenate((rows, np.full(gap_hole.size, -1, dtype=np.int64)))
    order = np.lexsort((all_row, all_end, all_start, all_hole))
    all_hole, all_start, all_end, all_row = (all_hole[order], all_start[order],
                                             all_end[order], all_row[order])
    is_row = all_row >= 0
    codes = np.full(all_row.size, None, dtype=object)
    codes[is_row] = lithology.code[all_row[is_row]]

    catalog = {name_key(entry.code): entry.color for entry in dset.catalogs.lithology
               if name_key(entry.log_set) == key}
    colors = np.array([NO_DATA_COLOR if code is None else
                       catalog.get(name_key(code), NO_DATA_COLOR) for code in codes.tolist()],
                      dtype=object)
    sizes, md, xyz = _segments(traces, all_hole, all_start, all_end, step)
    color = _linear_of(colors) if colors.size else np.zeros((0, _RGBA), np.float32)
    return CurveArrays(
        curve_sizes=sizes.astype(np.int32), hole=all_hole.astype(np.int32),
        from_m=all_start.astype(np.float64), to_m=all_end.astype(np.float64), code=codes,
        row=all_row.astype(np.int64), points_abs=xyz, md=md,
        color_linear=np.repeat(color, sizes, axis=0))


def lithology_legend(dset: DrillholeSet, log_set: str) -> tuple[LegendEntry, ...]:
    """La leyenda de la litología del esquema ``log_set`` (RF-005-23): los códigos de su
    catálogo que salen en la leyenda, por su orden y su código, con su color y su
    descripción, y al final «Sin dato» en gris (:data:`NO_DATA_COLOR`)."""
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"la leyenda se calcula sobre un DrillholeSet, no {dset!r}")
    if not isinstance(log_set, str):
        raise TypeError(f"el esquema de logueo es un texto, no {log_set!r}")
    key = name_key(log_set)
    codes = sorted((entry for entry in dset.catalogs.lithology
                    if name_key(entry.log_set) == key and entry.show_in_legend),
                   key=lambda entry: (entry.sort_order, name_key(entry.code)))
    return (*(LegendEntry(entry.code, entry.color, entry.description) for entry in codes),
            LegendEntry(tr("No data"), NO_DATA_COLOR))


# --- Leyenda de clases ------------------------------------------------------------------------


def _number_text(value: float) -> str:
    """Un corte de la leyenda con sus decimales (los de su decimal más corto), en el formato
    del idioma."""
    text = np.format_float_positional(value, unique=True, trim="-")
    decimals = len(text.partition(".")[2])
    return format_number(value, decimals)


@dataclass(frozen=True)
class GradeLegend:
    """Una leyenda de clases de un elemento (RF-005-24; véase el módulo), en ``unit``:
    ``breaks``, los cortes (crecientes y finitos); ``colors``, uno por clase («#RRGGBB», sRGB;
    uno más que cortes), y ``below_dl_color``, el de la clase «< LD». La clase k va de
    ``breaks[k − 1]`` (incluido) a ``breaks[k]``; la «< LD» es la :attr:`below_dl_class`."""

    unit: str
    breaks: tuple[float, ...]
    colors: tuple[str, ...]
    below_dl_color: str = BELOW_DL_COLOR

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError(f"la unidad de una leyenda de leyes es un texto, no {self.unit!r}")
        if name_key(self.unit) == TEXT_UNIT:
            raise ValueError("un elemento de texto no tiene leyenda de clases")
        if isinstance(self.breaks, str) or not isinstance(self.breaks, Sequence):
            raise TypeError(f"los cortes de una leyenda son una lista, no {self.breaks!r}")
        for value in self.breaks:
            if isinstance(value, bool) or not isinstance(value, _NUMBERS):
                raise TypeError(f"los cortes de una leyenda son números, no {value!r}")
        breaks = tuple(float(value) + 0.0 for value in self.breaks)
        if not all(math.isfinite(value) for value in breaks) or any(
                b <= a for a, b in zip(breaks, breaks[1:])):
            raise ValueError(f"los cortes de una leyenda son finitos y crecientes, no {breaks}")
        if isinstance(self.colors, str) or not isinstance(self.colors, Sequence):
            raise TypeError(f"los colores de una leyenda son una lista, no {self.colors!r}")
        colors = tuple(_color(value, "el color de una clase") for value in self.colors)
        if len(colors) != len(breaks) + 1:
            raise ValueError(f"una leyenda con {len(breaks)} cortes tiene {len(breaks) + 1} "
                             f"colores, no {len(colors)}")
        object.__setattr__(self, "breaks", breaks)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(self, "below_dl_color",
                           _color(self.below_dl_color, "el color de «< LD»"))

    @property
    def below_dl_class(self) -> int:
        """La clase de los valores bajo el límite de detección: la última de :meth:`entries`."""
        return len(self.colors)

    def classify(self, values: np.ndarray) -> np.ndarray:
        """La clase (int64) de cada valor; −1 si no es un número."""
        found = np.asarray(values, dtype=np.float64)
        classes = np.searchsorted(np.array(self.breaks, dtype=np.float64), found, side="right")
        return np.where(np.isnan(found), -1, classes).astype(np.int64)

    def entries(self) -> tuple[LegendEntry, ...]:
        """Las entradas de la leyenda: una por clase («< a», «a – b», «≥ b»; con una sola,
        «Todos los valores») y la «< LD»."""
        texts = [_number_text(value) for value in self.breaks]
        if not texts:
            labels = [tr("All values")]
        else:
            labels = [f"< {texts[0]}",
                      *(f"{a} – {b}" for a, b in zip(texts, texts[1:])),
                      f"≥ {texts[-1]}"]
        return (*(LegendEntry(label, color) for label, color in zip(labels, self.colors,
                                                                     strict=True)),
                LegendEntry(tr("< DL"), self.below_dl_color))


def _ramp(count: int) -> tuple[str, ...]:
    """``count`` colores de :data:`DEFAULT_RAMP`, interpolados en sRGB si no son 5."""
    if count == len(DEFAULT_RAMP):
        return DEFAULT_RAMP
    stops = np.array([[int(c[k:k + 2], 16) for k in (1, 3, 5)] for c in DEFAULT_RAMP],
                     dtype=np.float64)
    where = (np.linspace(0.0, 1.0, count) if count > 1 else np.array([0.5]))
    where = where * (len(DEFAULT_RAMP) - 1)
    low = np.minimum(np.floor(where).astype(np.int64), len(DEFAULT_RAMP) - 2)
    part = (where - low)[:, None]
    rgb = np.rint(stops[low] * (1.0 - part) + stops[low + 1] * part).astype(np.int64)
    return tuple("#" + "".join(f"{int(v):02X}" for v in color) for color in rgb.tolist())


def _significant(value: float) -> float:
    """``value`` redondeado a :data:`_SIGNIFICANT` cifras significativas (por su decimal)."""
    return float(f"{value:.{_SIGNIFICANT}g}") + 0.0


def default_grade_legend(values: np.ndarray, unit: str, n_classes: int = 5) -> GradeLegend:
    """La leyenda por defecto de unos valores (los de :func:`grade_values`) en ``unit``:
    ``n_classes`` clases por sus cuantiles (quintiles con 5) redondeados a 2 cifras
    significativas, cada corte una vez, más «< LD» (RF-005-24). Sin valores finitos, una sola
    clase. ``ValueError`` si ``n_classes`` < 1."""
    if isinstance(n_classes, bool) or not isinstance(n_classes, int) or n_classes < 1:
        raise ValueError(f"una leyenda tiene al menos una clase, no {n_classes!r}")
    found = np.asarray(values, dtype=np.float64).reshape(-1)
    found = found[np.isfinite(found)]
    breaks: list[float] = []
    if found.size and n_classes > 1:
        probabilities = np.arange(1, n_classes) / n_classes
        rounded = (_significant(q) for q in np.quantile(found, probabilities).tolist())
        breaks = sorted(set(rounded))
    return GradeLegend(unit, tuple(breaks), _ramp(len(breaks) + 1))


# --- Barras de leyes --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class BarArrays:
    """Las barras de un elemento (véase el módulo): ``vertices_abs`` (float64, (4·caras, 3),
    absolutos; cuatro por cara, sin compartir), ``faces`` (int32, (caras, 4): lado de dentro
    arriba y abajo, lado de fuera abajo y arriba) y, por cara, ``color_linear`` (float32,
    (caras, 4)), ``grade_class`` (int16, la entrada de ``GradeLegend.entries()``), ``hole``
    (int32) y ``row`` (int64, la fila de ``dset.assays``); ``skipped_units``, los valores que
    se habrían dibujado y no están en la unidad de la leyenda."""

    vertices_abs: np.ndarray
    faces: np.ndarray
    color_linear: np.ndarray
    grade_class: np.ndarray
    hole: np.ndarray
    row: np.ndarray
    skipped_units: int = field(default=0)


def _assay_rows(dset: DrillholeSet, element: str, unit: str, drawn: np.ndarray,
                excluded: Exclusions | None, *, below_dl: bool) -> tuple[np.ndarray, int]:
    """Las filas de los análisis que se dibujan del elemento ``element`` en ``unit`` (véase
    el módulo) en los sondeos ``drawn``, por sondeo, desde, hasta y fila, y cuántas no están
    en ``unit``. Con ``below_dl``, también las «< x»."""
    if not isinstance(element, str):
        raise TypeError(f"el elemento es un texto, no {element!r}")
    key = name_key(element)
    assays = dset.assays
    hole = assays.hole
    linked = hole >= 0
    keep = linked.copy()
    keep[linked] = drawn[hole[linked]] & ~_table_excluded(
        excluded, _ASSAY, key, len(dset.collars))[hole[linked]]
    flags = assays.detection_flag
    valued = (np.isfinite(assays.value) & ((flags == _OK) | (flags == _ABOVE_UL)))
    if below_dl:
        valued |= flags == _BELOW_DL
    keep &= (assays.is_primary & valued & _matches(assays.element, key)
             & _possible(assays.from_m, assays.to_m)
             & ~_record_excluded(excluded, _ASSAY, len(assays)))
    same_unit = np.array([text == unit for text in assays.unit.tolist()], dtype=np.bool_)
    skipped = int((keep & ~same_unit).sum())
    rows = np.flatnonzero(keep & same_unit)
    rows = rows[np.lexsort((rows, assays.to_m[rows], assays.from_m[rows], hole[rows]))]
    return rows, skipped


def grade_values(dset: DrillholeSet, element: str, unit: str, *,
                 excluded: Exclusions | None = None) -> np.ndarray:
    """Los valores del elemento ``element`` en ``unit`` que las barras clasifican por clases
    (los de :func:`grade_bars` sin «< x»), también de sondeos sin traza, en orden de sondeo,
    desde, hasta y fila: la entrada de :func:`default_grade_legend` (RF-005-24)."""
    _check_set(dset, excluded)
    if not isinstance(unit, str):
        raise TypeError(f"la unidad es un texto, no {unit!r}")
    rows, _ = _assay_rows(dset, element, unit, _drawn_holes(dset, None, excluded), excluded,
                          below_dl=False)
    return dset.assays.value[rows].copy()


def _side(chord: np.ndarray) -> np.ndarray:
    """La dirección horizontal unitaria a la derecha de cada cuerda según se baja
    ((Δy, −Δx, 0)/|Δxy|); al este si la cuerda es vertical (:data:`VERTICAL_TOLERANCE`)."""
    horizontal = np.hypot(chord[:, 0], chord[:, 1])
    vertical = horizontal <= VERTICAL_TOLERANCE * np.linalg.norm(chord, axis=1)
    safe = np.where(vertical, 1.0, horizontal)
    side = np.column_stack((chord[:, 1] / safe, -chord[:, 0] / safe, np.zeros(len(chord))))
    side[vertical] = (1.0, 0.0, 0.0)
    return side


def grade_bars(dset: DrillholeSet, traces: Traces, element: str, legend: GradeLegend,
               offset_m: float, width_m: float, *, max_step_m: float | None = None,
               excluded: Exclusions | None = None) -> BarArrays:
    """Las barras del elemento ``element`` (sin distinguir mayúsculas) junto a la traza de
    cada sondeo, a ``offset_m`` (≥ 0) de su eje y de ``width_m`` (> 0) de ancho, del color de
    su clase en ``legend`` (RF-005-24, RF-005-17; véase el módulo); con ``max_step_m``, en
    partes de la traza de ≤ ``max_step_m`` m.

    ``TypeError``/``ValueError`` con unas trazas o unas exclusiones de otro conjunto, una
    leyenda que no es un :class:`GradeLegend` o distancias no válidas."""
    _check_inputs(dset, traces, excluded)
    if not isinstance(legend, GradeLegend):
        raise TypeError(f"la leyenda de las barras es un GradeLegend, no {legend!r}")
    offset = _length(offset_m, "la separación de las barras", zero=True)
    width = _length(width_m, "el ancho de las barras", zero=False)
    step = None if max_step_m is None else _length(max_step_m, "el paso de las barras",
                                                   zero=False)
    rows, skipped = _assay_rows(dset, element, legend.unit,
                                _drawn_holes(dset, traces, excluded), excluded, below_dl=True)
    assays = dset.assays
    hole = assays.hole[rows]
    sizes, _, xyz = _segments(traces, hole, assays.from_m[rows], assays.to_m[rows], step)

    # Una cara por cada dos puntos seguidos del mismo tramo, a la derecha de su cuerda.
    faces_of = sizes - 1
    first = _ranges(np.cumsum(sizes) - sizes, faces_of)
    top, low = xyz[first], xyz[first + 1]
    side = _side(low - top)
    inner, outer = offset * side, (offset + width) * side
    corners = np.stack((top + inner, low + inner, low + outer, top + outer), axis=1)
    classes = legend.classify(assays.value[rows])
    classes[assays.detection_flag[rows] == _BELOW_DL] = legend.below_dl_class
    palette = srgb_to_linear([*legend.colors, legend.below_dl_color])
    face_class = np.repeat(classes, faces_of)
    count = first.size
    return BarArrays(
        vertices_abs=corners.reshape(-1, 3),
        faces=np.arange(4 * count, dtype=np.int32).reshape(count, 4),
        color_linear=palette[face_class], grade_class=face_class.astype(np.int16),
        hole=np.repeat(hole, faces_of).astype(np.int32),
        row=np.repeat(rows, faces_of).astype(np.int64), skipped_units=skipped)


# --- Etiquetas --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Label:
    """Una etiqueta de la vista: el sondeo (posición de la boca), su texto, su posición
    absoluta (E, N, Z; float64) y si es la del fondo."""

    hole: int
    text: str
    xyz: tuple[float, float, float]
    bottom: bool = False


def _depth_text(depth: float) -> str:
    return f"{format_number(depth, LABEL_DECIMALS)} m"


def labels(dset: DrillholeSet, traces: Traces, at_end: bool) -> list[Label]:
    """Las etiquetas de los sondeos (RF-005-25; véase el módulo): en la boca de cada sondeo
    con X, Y y Z, «nombre (profundidad m)» (sin profundidad, el nombre) y, con ``at_end``, la
    profundidad total en su posición sobre la traza (solo los sondeos con traza), en orden de
    las bocas."""
    _check_inputs(dset, traces, None)
    collars = dset.collars
    xyz = np.column_stack((collars.x, collars.y, collars.z))
    depth = collars.depth
    placed = np.isfinite(xyz).all(axis=1)
    ends = np.flatnonzero(placed & traces.computed & np.isfinite(depth)) if at_end else \
        np.zeros(0, dtype=np.int64)
    bottom = dict(zip(ends.tolist(), md_to_xyz(traces, ends, depth[ends]).tolist(),
                      strict=True)) if ends.size else {}
    found: list[Label] = []
    for k in np.flatnonzero(placed).tolist():
        name, value = str(collars.name[k]), float(depth[k])
        text = f"{name} ({_depth_text(value)})" if math.isfinite(value) else name
        x, y, z = xyz[k].tolist()
        found.append(Label(k, text, (x, y, z)))
        if k in bottom:
            bx, by, bz = bottom[k]
            found.append(Label(k, _depth_text(value), (bx, by, bz), bottom=True))
    return found
