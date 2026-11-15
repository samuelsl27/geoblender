# SPDX-License-Identifier: GPL-3.0-or-later
"""La plataforma: huella y rasante, su aplicación sobre la superficie de partida y su borde (spec 015,
T06, T07 y T08; RF-015-19, los rechazos de geometría de RF-015-08, RF-015-20, RF-015-21, RF-015-22,
RF-015-06 y RF-015-13; plan 015 §5.1 y §5.4, A0, A1, A2 y A3; CE-015-02, CE-015-03 y CE-015-07) y su
contrapendiente, sus cifras y sus avisos (T09; RF-015-23, RF-015-24, RF-015-14 y RF-015-13; A4 y A5).
Dominio puro: sin proyecto y sin ``bpy``.

Lo que entrega:

- :class:`PlatformJob` (el homólogo de ``quarry.QuarryJob``): todo lo que el cálculo necesita **ya
  leído** y nada del proyecto —la petición, el código de la entidad, la rejilla, la superficie de
  partida, la geometría de origen (:class:`PlatformGeometry`: una línea con su ancho o un polígono con
  su eje enlazado o sin él), los parámetros resueltos (por último segmento de su clave, los de
  :class:`~.params.PlatformParam`) y las máscaras ``cut_allowed`` y ``fill_allowed`` como arrays— para
  probarlo sin proyecto y reproducirlo.
- :func:`platform_footprint` (A0 y A1): la :class:`Footprint` de la plataforma —su huella, la abscisa
  σ de cada celda, la rasante, el eje usado con su sentido, la longitud medida de la huella y los
  avisos— en su **ventana de trabajo** (:func:`work_window`: la huella ampliada por el alcance y dos
  celdas, recortada a la rejilla).
- :func:`axis_of_polygon` (A1): el eje principal de las celdas de un polígono.
- :func:`apply_platform` y :func:`apply_platform_steps` (A2): la superficie que deja la plataforma
  sobre la de partida (:class:`Applied`), con lo que no se mueve y por qué (:class:`OffLevel`).
- :func:`platform_edge` y :func:`platform_edge_steps` (A3): el borde que une la huella con la
  superficie de partida (:class:`Edge`), con su volumen, la altura de su pared, la pared más
  empinada que el ángulo de borde con su causa (:class:`EdgeWall`) y sus avisos.
- :func:`magnitude_notices`: el aviso de magnitud de RF-013-30 del desmonte y el terraplén de la
  entidad frente a la revisión congelada anterior.
- :func:`platform_profile` (A4): el perfil longitudinal de la superficie resultante
  (:class:`LongProfile`) y su contrapendiente.
- :func:`order_check` (RF-015-14): el orden ``final ≤ explotación ≤ terreno`` de una cantera de la 014
  frente a la otra de sus dos superficies (:class:`QuarryOrder`, :class:`OrderBreach`).
- :func:`platform_outcome` (A5): el :class:`PlatformOutcome` que junta la huella, lo aplicado y el borde
  con el perfil, lo que las máscaras no dejan mover (:class:`HeldGroup`), las cifras de RF-015-24
  (``provenance.platform_figures``) y la lista de avisos, en orden estable.

**Con eje y ancho** la huella es la del corredor de extremos planos de RF-014-09
(:func:`~.quarry.axis_abscissa`, que mide lo que su eje ± 1 celda: error 20) y la abscisa σ, la del
punto más próximo de todo el eje (a igual distancia de dos tramos, la menor; la abscisa 0 está en el
primer vértice). **Con polígono**, las celdas son las de su centro (D-16 de la 013) y el eje, la parte
dentro del polígono de la línea enlazada —que lo cruza de lado a lado— o, sin enlace, el eje principal
de las celdas (con el aviso ``des.platform_axis_principal``); σ es la del punto más próximo del eje,
fijada en sus extremos. En los dos casos la sección es horizontal: la rasante de una celda es ``cota
inicial + σ · pendiente / 100``.

Rechaza (``DesignError``, nombrando la capa, la entidad, el campo y el valor, y sin elegir ninguno por
la persona; RF-015-08), en este orden: una capa de puntos (``des.platform_layer_kind``); un ancho, una
cota inicial, una pendiente o un alcance que falta o sale de rango y una métrica que no es de su lista
(``des.entity_param_*``); una línea
de varias partes, sin longitud, cerrada o que se corta a sí misma (``des.platform_axis_parts``,
``_axis_length_zero``, ``_axis_closed`` y ``_self_intersects``); un polígono sin área, que se corta o
sin celdas (``des.platform_area_zero``, ``_self_intersects`` y ``_no_cells``); un eje enlazado que no
cruza su polígono de lado a lado (``des.platform_axis_not_crossing``); una cota inicial o final de la
rasante fuera de las del terreno ± 1.000 m (``des.platform_level_range``); y una línea fuera de la
rejilla (``des.platform_no_cells``).

**Aplicar** (A2): en el modo «en corte» (el de por defecto, D-5) la superficie es ``z' = mín(z,
rasante)`` en las celdas de la huella donde el corte se admite (``cut_allowed``) y **ninguna celda
sube**: la plataforma es el fondo de su corredor, no una cota mínima (B7). En «en corte y relleno»,
además ``z' = rasante`` donde ``z < rasante`` y el relleno se admite (``fill_allowed``). Las celdas de
la huella que las máscaras no dejan mover quedan como en la partida; las que no quedan en la rasante
(a 10⁻⁹ m) se agrupan (4-conexas) con su área, su diferencia máxima, su lugar absoluto y su causa
(:class:`OffLevelCause`: ``cut_allowed`` falso, ``fill_allowed`` falso o, por debajo en «en corte», el
modo), y las máscaras de lo que se impide quedan en :class:`Applied` para que la zona se mire contra
las restricciones de otras entidades (el resumen es de la T12). Las celdas que quedan en la rasante
(:attr:`Applied.at_level`) son las semillas del borde (T08). Sin dato en la huella lo rechaza la
preparación (RF-015-09, T11): aquí es un error del programa, no se oculta con un valor.

**El borde** (A3, RF-015-22): las semillas son las celdas de la huella que quedaron en la rasante
(:attr:`Applied.at_level`). Con ``t = tan(ángulo de borde) · factor de malla`` y la métrica de la
entidad (la euclídea exacta, por defecto, o el *chamfer* 5×5 de la 013), la envolvente ascendente
``ENV↑`` y, en «en corte y relleno», la descendente ``ENV↓`` de esas semillas
(:func:`~.edges.seed_envelope_steps`) dan, **fuera de la huella** y hasta el **alcance** (obligatorio,
D-20: la distancia a la semilla más próxima con la misma métrica; lo que pasa de él no se toca),
``z' = mín(z, ENV↑)`` donde el corte se admite y ``z' = máx(z, ENV↓)`` donde se admite el relleno. El
volumen del borde (corte y relleno por separado, m³) es la suma celda a celda de ``|z − z'|`` por el
área de la celda; la **altura máxima de su pared** es ``máx(|z − z'|)`` en las celdas que el borde
mueve (interpretación del plan, [I]). Una celda que el borde mueve queda **más empinada que el ángulo
de borde más la tolerancia de cara** de la 013 si su mayor inclinación a sus 8 vecinas con dato (la de
D-13) la pasa **y** pasa de la que el terreno ya tenía en esa celda (lo que el terreno ya tenía no
cuenta, como en el salto creado de la 014, error 48): solo se admite en el límite del alcance y en el
borde de lo que admiten las máscaras (:class:`WallCause`); lo demás es de la propia plataforma (su
pendiente, o lo que no queda en su rasante). Lo que el borde deja sin
mover por las máscaras (``held``), lo que llega al borde de la rejilla o a celdas sin dato fuera de la
huella (``outside``) y el salto creado de la 014 (A11, :class:`~.edges.EdgeReport`) son los datos de
RF-015-13; sus avisos ya vienen armados (:attr:`Edge.notices`). La ventana de trabajo (A0) cubre lo
que el alcance puede tocar con la métrica de la entidad (con el *chamfer*, que mide 0,98644 de la
distancia exacta a lo largo de un eje, una ventana algo mayor).

**La contrapendiente** (A4, RF-015-23, D-8, D-16): el perfil longitudinal de la plataforma **en la
superficie resultante** (huella y borde) es, por cada tramo de una celda de abscisa (``⌊σ/h⌋``), la
cota más alta de su sección. En el sentido en que **baja** la rasante (pendiente < 0: hacia las
abscisas grandes; > 0: hacia las pequeñas) la contrapendiente de un tramo es lo que sube el perfil
sobre el mínimo de los tramos aguas arriba; pasa si es mayor que la tolerancia de la entidad
(``counter_tol_m``, 0,1 m por defecto, D-8). Con pendiente 0 %, es el máximo menos el mínimo del
perfil (D-16: admitida). El aviso lleva la abscisa, la cuantía y el lugar de la celda más alta del
peor tramo y **hay que confirmarlo expresamente para crear la plataforma**
(:attr:`PlatformOutcome.needs_confirmation`, :meth:`PlatformOutcome.ensure_creatable`).

**Las cifras y los avisos** (A5, RF-015-24, RF-015-13, RF-015-14): el área, las longitudes del eje y de
la huella, las cotas de la rasante en los extremos, el corte y el relleno de la huella y del borde por
separado y, de lo que no queda en la rasante (por debajo y por encima), su área y la diferencia
máxima; «la plataforma no corta» si ninguna celda baja; y el orden de las dos superficies de una
cantera de la 014 contra la otra (un aviso: no impide crear). Los avisos de lo que no se mueve por
la restricción de **otra entidad**, con su nombre, son de quien lee las restricciones (T12): aquí
quedan los datos (:attr:`PlatformOutcome.held`, :attr:`PlatformOutcome.held_groups`).

**Leer solo la ventana** (spec 015, T37; RNF-015-03, plan 015 §5.4 A0): el cálculo solo toca la ventana de
trabajo de la huella, así que :class:`PlatformJob` puede llevar la superficie de partida y las máscaras **de una
ventana** de la rejilla (``region``) y no de toda ella; :func:`reading_window` da la ventana que basta leer (la caja
de la geometría ampliada por el ancho, el alcance y dos celdas: **nunca menos** de lo que el cálculo toca) y
:meth:`PlatformJob.start_in`, ``cut_in`` y ``fill_in`` dan una parte de lo leído en coordenadas de la rejilla. Lo que
la ventana no basta para decidir (el rango de cotas de RF-015-08 es el de la superficie entera) es
:class:`NeedsWholeSurface`: quien prepara lee la rejilla entera y repite, con el mismo resultado y el mismo rechazo.

Las coordenadas absolutas son float64 y se pasan a locales respecto a la esquina de la rejilla solo
dentro del cálculo (principio 6, ADR-0005). Ninguna entrada se modifica.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import format_value
from .edges import EdgeReport, created_steps, edge_notices, seed_envelope_steps
from .edges import summary_notices as _stretch_notices
from .edges import transition_domain
from .envelopes import CHAMFER_SCALE, SlopeField, reach_steps
from .grids import _label_units, dilate_square
from .messages import DesignError
from .model import Axis, Direction, Metric, PlatformMode, PlatformRequest, Surface
from .params import (
    EDGE_MAX_STEP,
    EDGE_MIN_SHARE,
    PLATFORM_PARAMS,
    TOLERANCE_FACE,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    PlatformParam,
    check_entity_param,
    check_quarry_param,
    entity_key,
    entity_segment,
)
from .preview import Notice
from .provenance import platform_figures
from .quarry import (
    FLOOR_LEVEL_MARGIN_M,
    ORDER_TOLERANCE_M,
    _EMPTY_TILES,
    _UNIT_WORK,
    _axis_segments,
    _centre_distance,
    _run_units,
    _segment_frame,
    _slack,
    _tile_box,
    _tiles,
    axis_abscissa_units,
    axis_paths,
    corridor_window,
)
from .report import REPORT_CELLS_PER_UNIT, Previous, _max_tangents, _padded, _thickness
from .seeds import pace_progress
from .zones import _paint, _polygon_spans

__all__ = [
    "Applied",
    "Edge",
    "EdgeWall",
    "Footprint",
    "HeldGroup",
    "LongProfile",
    "NeedsWholeSurface",
    "OffLevel",
    "OffLevelCause",
    "OrderBreach",
    "PlatformGeometry",
    "PlatformJob",
    "PlatformOutcome",
    "QuarryOrder",
    "WallCause",
    "apply_platform",
    "apply_platform_steps",
    "axis_of_polygon",
    "magnitude_notices",
    "order_check",
    "platform_edge",
    "platform_edge_steps",
    "platform_footprint",
    "platform_footprint_units",
    "platform_outcome",
    "platform_profile",
    "reading_window",
    "summary_notices",
    "window_part",
    "work_window",
]

_GEOMETRY = "geometría"
_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_LINK_FIELD = "eje"
_TOL_M = 1e-9
"""Lo que separa dos puntos distintos (m): la resolución de un float64 a 4,4 Mm de norte."""
_REL = 1e-12
"""La tolerancia relativa de un paralelismo y de un parámetro dentro de un tramo."""

_Parts = tuple[tuple[np.ndarray, ...], ...]


# --- Lo leído ----------------------------------------------------------------------------------


def _xy(points: object) -> np.ndarray:
    """``points`` como array float64 ``(k, 2)`` de vértices finitos (la Z, si la trae, no cuenta);
    ``ValueError`` si no son puntos o no son finitos."""
    array = np.asarray(points, dtype=np.float64)
    if array.ndim == 2 and array.shape[1] in (2, 3):
        array = array[:, :2]
    elif array.size % 2 == 0:
        array = array.reshape(-1, 2)
    else:
        raise ValueError(f"unos vértices son un array (k, 2), no de forma {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError("una geometría tiene coordenadas no finitas")
    return array


def _parts(parts: object) -> _Parts:
    """Las partes de una geometría (por parte, sus caminos o sus anillos) con cada uno como array
    float64 ``(k, 2)``, sin copiar los que ya lo son."""
    return tuple(tuple(_xy(path) for path in part) for part in parts)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True, eq=False)
class PlatformGeometry:
    """La geometría de origen de una plataforma, ya leída de su capa: su ``kind`` (``point``,
    ``line`` o ``polygon``, el de la capa; un punto se rechaza al calcular) y sus ``parts`` (por
    parte, su camino o sus anillos —el primero, el exterior—, X e Y ABSOLUTAS en float64, como las da
    ``gis.vector.FeatureLayer``). Un polígono lleva, si tiene eje enlazado, las partes de esa línea
    (``axis_parts``) y su nombre (``axis_name``, para decirlo en un rechazo); sin ellas, el eje es el
    principal de sus celdas. Una línea no lleva eje enlazado (``ValueError``, como un tipo que no es
    de una capa de entidades: errores del programa)."""

    kind: str
    parts: _Parts
    axis_parts: _Parts | None = None
    axis_name: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _KINDS_ES:
            raise ValueError(f"la geometría de una plataforma es de puntos, líneas o polígonos, "
                             f"no «{self.kind}»")
        if self.axis_parts is not None and self.kind != "polygon":
            raise ValueError("solo un polígono lleva un eje enlazado (RF-015-19)")
        object.__setattr__(self, "parts", _parts(self.parts))
        if self.axis_parts is not None:
            object.__setattr__(self, "axis_parts", _parts(self.axis_parts))


Window = tuple[slice, slice]
"""Una ventana de la rejilla: sus filas y sus columnas (``slice`` de enteros, sin paso)."""


class NeedsWholeSurface(Exception):
    """El cálculo de una plataforma preparada con **una ventana** de la rejilla (:attr:`PlatformJob.region`) necesita
    saber algo de la rejilla entera que la ventana no basta para decidir (el rango de cotas de RF-015-08, que la
    superficie tenga algún dato): no es un rechazo de la persona, es la señal de que quien prepara ha de leer la
    rejilla entera y repetir, con el mismo resultado y el mismo rechazo que si la hubiera leído entera (spec 015,
    T37)."""


def _whole(grid: Grid) -> Window:
    return slice(0, grid.nrows), slice(0, grid.ncols)


def _ends(part: slice) -> tuple[int, int]:
    """Los extremos enteros de ``part`` (``ValueError`` si no los tiene o lleva paso)."""
    start, stop = part.start, part.stop
    if part.step not in (None, 1) or not isinstance(start, int) or not isinstance(stop, int):
        raise ValueError(f"una ventana se indica con filas y columnas enteras sin paso, no {part!r}")
    return start, stop


def _window_of(window: Window, grid: Grid) -> Window:
    """``window`` comprobada contra ``grid`` (``ValueError`` si no es de enteros, está vacía o se sale de ella)."""
    found: list[slice] = []
    for part, size in zip(window, grid.shape, strict=True):
        start, stop = _ends(part)
        if not 0 <= start < stop <= size:
            raise ValueError(f"la ventana {window!r} no está dentro de la rejilla de {grid.nrows} × {grid.ncols}")
        found.append(slice(start, stop))
    return found[0], found[1]


def window_part(array: np.ndarray, region: Window, window: Window) -> np.ndarray:
    """La parte de ``array`` —que es de la ventana ``region`` de la rejilla— que cae en ``window`` (también de la
    rejilla): una vista. ``ValueError`` (un error del programa: se pidió algo que no se leyó) si ``window`` no está
    dentro de ``region`` o está vacía."""
    (r0, r1), (c0, c1) = _ends(region[0]), _ends(region[1])
    (top, bottom), (left, right) = _ends(window[0]), _ends(window[1])
    if not (r0 <= top < bottom <= r1 and c0 <= left < right <= c1):
        raise ValueError(f"la ventana {window!r} no está dentro de lo leído ({region!r})")
    return array[top - r0 : bottom - r0, left - c0 : right - c0]


def _shaped_array(values: object, shape: tuple[int, int], dtype: type, what: str, where: str) -> np.ndarray:
    """``values`` como array de forma ``shape`` (``ValueError`` si no lo es); ``where``, de qué es la forma."""
    array = np.asarray(values, dtype=dtype)
    if array.shape != shape:
        raise ValueError(f"{what} es de la forma {where} {shape}, no {array.shape}")
    return array


@dataclass(frozen=True, slots=True, eq=False)
class PlatformJob:
    """Lo que necesita calcular una plataforma, ya leído y sin proyecto (plan 015 §5.3.1; lo que
    ``quarry.QuarryJob`` a la 014): la ``request`` (su nombre y la capa con sus campos), el ``code``
    de la entidad (``PLT-001``, para nombrar la clave de un parámetro en un rechazo), la rejilla
    (``grid``), la superficie de partida ``start`` (m, float64; ``NaN``, sin dato), la ``geometry`` de
    origen, los parámetros resueltos (``values``: por último segmento de su clave, los de
    :class:`~.params.PlatformParam`: ``width_m`` —solo con una línea—,
    ``start_level_m``, ``gradient_pct``, ``reach_m``…) y las máscaras de la versión como arrays
    booleanos (``cut_allowed`` y ``fill_allowed``: las usan la aplicación y el borde, T07 y T08).

    Los tres arrays son de la **rejilla entera** o, con ``region`` (spec 015, T37; RNF-015-03), **de esa ventana** de
    la rejilla (filas y columnas): es lo que basta leer para calcular la plataforma (:func:`reading_window`: el
    cálculo solo toca la ventana de trabajo de su huella). Se piden por coordenadas de la rejilla con
    :meth:`start_in`, :meth:`cut_in` y :meth:`fill_in`. ``ValueError`` (errores del programa) si el código no es el
    de una entidad, una clave no es de una plataforma, la ventana no está dentro de la rejilla o un array no es de la
    forma de la rejilla (o de la ventana)."""

    request: PlatformRequest
    code: str
    grid: Grid
    start: np.ndarray
    geometry: PlatformGeometry
    values: Mapping[str, object]
    cut_allowed: np.ndarray
    fill_allowed: np.ndarray
    region: Window | None = None

    def __post_init__(self) -> None:
        entity_segment(self.code)
        if self.region is not None:
            object.__setattr__(self, "region", _window_of(self.region, self.grid))
        window = self.window
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        where = "de la rejilla" if self.region is None else "de su ventana"
        object.__setattr__(self, "start",
                           _shaped_array(self.start, shape, np.float64, "la superficie de partida", where))
        for name in ("cut_allowed", "fill_allowed"):
            object.__setattr__(self, name, _shaped_array(getattr(self, name), shape, np.bool_,
                                                         f"la máscara «{name}»", where))
        known = {param.value for param in PlatformParam}
        unknown = sorted(set(self.values) - known)
        if unknown:
            raise ValueError(f"los valores de una plataforma son de {', '.join(sorted(known))}, "
                             f"no «{unknown[0]}»")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def window(self) -> Window:
        """La ventana de la rejilla que cubren ``start``, ``cut_allowed`` y ``fill_allowed``: ``region`` o, sin
        ella, la rejilla entera."""
        return _whole(self.grid) if self.region is None else self.region

    @property
    def whole(self) -> bool:
        """Si lo leído es la rejilla entera (sin ``region`` o con una que la cubre)."""
        return self.region is None or all(
            (part.start, part.stop) == (0, size) for part, size in zip(self.region, self.grid.shape, strict=True))

    def _in(self, array: np.ndarray, window: Window) -> np.ndarray:
        return array[window] if self.region is None else window_part(array, self.region, window)

    def start_in(self, window: Window) -> np.ndarray:
        """La superficie de partida en ``window`` (filas y columnas de la rejilla): una vista; ``ValueError`` si
        ``window`` no está dentro de lo leído."""
        return self._in(self.start, window)

    def cut_in(self, window: Window) -> np.ndarray:
        """La máscara de corte admitido en ``window`` (como :meth:`start_in`)."""
        return self._in(self.cut_allowed, window)

    def fill_in(self, window: Window) -> np.ndarray:
        """La máscara de relleno admitido en ``window`` (como :meth:`start_in`)."""
        return self._in(self.fill_allowed, window)


@dataclass(frozen=True, slots=True, eq=False)
class Footprint:
    """La huella y la rasante de una plataforma (A0 y A1), en su ventana de trabajo (``window``:
    filas y columnas de la rejilla, :func:`work_window`; todas las rejillas de abajo son de su
    forma): ``cells`` (la huella; booleana), ``sigma`` (la abscisa σ, m, a lo largo del eje desde su
    primer vértice, de la celda: la de su punto más próximo; ``NaN`` fuera de la huella) y ``levels``
    (la rasante, m: ``cota inicial + σ · pendiente / 100``; ``NaN`` fuera). ``axis`` es el eje usado
    (:class:`~.model.Axis`, con su sentido, su longitud y si es el principal), ``length_m`` la
    longitud medida de la huella (m; el máximo menos el mínimo de la abscisa sin recortar de sus
    celdas: error 20, no los 220 m de un *buffer*), ``start_level_m`` y ``gradient_pct`` los de la
    rasante, ``cell_area_m2`` el área de una celda y ``notices`` los avisos (el eje principal)."""

    window: tuple[slice, slice]
    cells: np.ndarray
    sigma: np.ndarray
    levels: np.ndarray
    axis: Axis
    length_m: float
    start_level_m: float
    gradient_pct: float
    cell_area_m2: float
    notices: tuple[Notice, ...] = ()

    @property
    def cell_count(self) -> int:
        """Las celdas de la huella."""
        return int(np.count_nonzero(self.cells))

    @property
    def area_m2(self) -> float:
        """El área de la huella (m²): sus celdas por el área de una."""
        return self.cell_count * self.cell_area_m2

    @property
    def end_level_m(self) -> float:
        """La cota de la rasante en el último vértice del eje (m)."""
        return self.start_level_m + self.axis.length_m * self.gradient_pct / 100.0


def work_window(rows: slice, cols: slice, reach_m: float, grid: Grid,
                metric: Metric | str = Metric.EXACT) -> tuple[slice, slice]:
    """**A0** (plan 015 §5.4): la ventana de trabajo de una entidad, la caja de su huella (``rows``
    y ``cols``: filas y columnas de ``grid``) ampliada por el alcance ``reach_m`` (m) y dos celdas,
    recortada a la rejilla: ``⌈alcance / paso⌉ + 2`` celdas por cada lado (el paso de cada eje). Así
    veinte plataformas de una hectárea no cuestan veinte envolventes de la rejilla entera.

    Con la métrica *chamfer* 5×5 (``metric``), que a lo largo de un eje mide
    :data:`~.envelopes.CHAMFER_SCALE` (0,98644) de la distancia exacta, lo que el alcance llega a
    tocar es ``alcance / 0,98644``: la ampliación es ``⌈alcance / (0,98644 · paso)⌉ + 2`` (con la
    exacta, la de siempre, bit a bit). ``ValueError`` si el alcance no es un número mayor o igual que
    0 o la métrica no es de la 013."""
    if not reach_m >= 0.0:
        raise ValueError(f"el alcance es un número mayor o igual que 0, no {reach_m!r}")
    scale = CHAMFER_SCALE if Metric(metric) is Metric.CHAMFER5 else 1.0
    across_rows = math.ceil(reach_m / (scale * grid.dy)) + 2
    across_cols = math.ceil(reach_m / (scale * grid.dx)) + 2
    return (slice(max(rows.start - across_rows, 0), min(rows.stop + across_rows, grid.nrows)),
            slice(max(cols.start - across_cols, 0), min(cols.stop + across_cols, grid.ncols)))


def reading_window(geometry: PlatformGeometry, values: Mapping[str, object], grid: Grid) -> Window | None:
    """**A0**, antes de leer nada (spec 015, T37; RNF-015-03): la ventana de la rejilla que basta leer para calcular
    la plataforma de ``geometry`` con los parámetros ``values`` (los resueltos: ``width_m``, ``reach_m``,
    ``metric``): la caja de toda su geometría —los vértices de sus partes y, en un polígono, de su eje enlazado—
    ampliada por la mitad del ancho (la del corredor de una línea; un polígono, sin ancho) y, como en
    :func:`work_window`, por el alcance y dos celdas, recortada a la rejilla. **Contiene siempre la ventana de trabajo
    de la huella** (la huella cabe en la caja de la geometría y :func:`work_window` es monótona), así que leer solo
    ella no cambia ni un bit del cálculo. ``None`` si no se puede juzgar —una geometría que no es de líneas ni de
    polígonos, sin vértices o fuera de la rejilla, un alcance o un ancho que faltan o no son un número no negativo,
    una métrica que no es de la lista—: se lee la rejilla entera y la preparación da los rechazos de siempre."""
    if geometry.kind not in ("line", "polygon"):
        return None
    try:
        reach = float(values[PlatformParam.REACH.value])  # type: ignore[arg-type]
        half = (float(values[PlatformParam.WIDTH.value]) / 2.0  # type: ignore[arg-type]
                if geometry.kind == "line" else 0.0)
        found = values.get(PlatformParam.METRIC.value)
        metric = Metric(PLATFORM_PARAMS[PlatformParam.METRIC.value].default if found is None else found)
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(reach) and reach >= 0.0 and math.isfinite(half) and half >= 0.0):
        return None
    paths = [path for part in (*geometry.parts, *(geometry.axis_parts or ())) for path in part if path.shape[0]]
    if not paths:
        return None
    box = corridor_window([np.concatenate(paths)], half, grid)
    if box[0].stop <= box[0].start or box[1].stop <= box[1].start:
        return None
    return work_window(box[0], box[1], reach, grid, metric)


# --- Rechazos ----------------------------------------------------------------------------------


def _reject(code: str, request: PlatformRequest, field: str, value: object,
            **values: object) -> DesignError:
    """El rechazo ``code`` de la plataforma de ``request``: nombra la capa, la entidad, el campo y
    el valor."""
    return DesignError(code, obj=f"Plataforma «{request.name}» de la capa «{request.layer}»",
                       field=field, value=value, layer=request.layer, entity=request.name, **values)


def _resolved(job: PlatformJob, *, line: bool) -> tuple[float, float, float, float | None]:
    """Los valores que calcula la huella, ya comprobados (``des.entity_param_missing`` o
    ``des.entity_param_range`` con la capa y la clave de su campo): ``(cota inicial, pendiente, alcance,
    ancho)``, y el ancho solo con una línea (un polígono no lo tiene: ``None``)."""
    name, code, found, layer = job.request.name, job.code, job.values, job.request.layer

    def one(param: PlatformParam) -> float:
        value = check_entity_param(name, code, param, found.get(param.value), layer=layer)
        assert isinstance(value, float)
        return value

    width = one(PlatformParam.WIDTH) if line else None
    return (one(PlatformParam.START_LEVEL), one(PlatformParam.GRADIENT), one(PlatformParam.REACH),
            width)


def _metric(job: PlatformJob) -> Metric:
    """La métrica de la envolvente de la plataforma de ``job`` (``des.entity_param_choice`` si no es
    de su lista); sin el valor, la de la familia de parámetros (la exacta, D-22)."""
    found = job.values.get(PlatformParam.METRIC.value)
    if found is None:
        found = PLATFORM_PARAMS[PlatformParam.METRIC.value].default
    return Metric(check_entity_param(job.request.name, job.code, PlatformParam.METRIC, found,
                                     layer=job.request.layer))


def _check_levels(job: PlatformJob, axis_m: float, start_level: float, gradient: float) -> None:
    """**RF-015-08**: la cota inicial de la rasante y la del final del eje (de ``axis_m`` m) dentro
    de ``[mín(z) − 1.000, máx(z) + 1.000]`` m con las celdas con dato de la superficie de partida;
    si no, ``des.platform_level_range`` con la capa, la entidad, el campo (el de la cota inicial o,
    para la final, «<cota inicial> + <pendiente>»), el valor y el rango. ``ValueError`` si la
    superficie de partida no tiene ninguna celda con dato (lo rechaza antes la preparación)."""
    finite = np.isfinite(job.start)
    if not finite.any():
        if not job.whole:  # una ventana sin dato: la rejilla entera lo decide
            raise NeedsWholeSurface("la ventana leída de la superficie de partida no tiene ninguna celda con dato")
        raise ValueError("la superficie de partida no tiene ninguna celda con dato")
    low = float(np.min(job.start, where=finite, initial=np.inf)) - FLOOR_LEVEL_MARGIN_M
    high = float(np.max(job.start, where=finite, initial=-np.inf)) + FLOOR_LEVEL_MARGIN_M
    fields = job.request.fields
    end_level = start_level + axis_m * gradient / 100.0
    for field, level in ((fields.start_level_field, start_level),
                         (f"{fields.start_level_field} + {fields.gradient_field}", end_level)):
        if not low <= level <= high:
            if not job.whole:  # el rango de la ventana está dentro del de la rejilla entera: ella decide
                raise NeedsWholeSurface(f"la cota {level} no cabe en el rango de la ventana leída")
            raise _reject("des.platform_level_range", job.request, field, level, low=low,
                          high=high)


# --- Geometría: cruces y puntos ----------------------------------------------------------------


def _hits(p: np.ndarray, r: np.ndarray, a: np.ndarray, s: np.ndarray
          ) -> tuple[np.ndarray, np.ndarray]:
    """El tramo ``p + t·r`` (``t`` en [0, 1]) frente a los tramos ``a + u·s`` (``a`` y ``s``,
    ``(n, 2)``): para cada uno, si se tocan (un cruce, un contacto o un solape sobre la misma
    recta) y el ``t`` del primer punto común. En locales (float64)."""
    ap = a - p
    denom = r[0] * s[:, 1] - r[1] * s[:, 0]
    cross_s = ap[:, 0] * s[:, 1] - ap[:, 1] * s[:, 0]
    cross_r = ap[:, 0] * r[1] - ap[:, 1] * r[0]
    length_r = math.hypot(r[0], r[1])
    length_s = np.hypot(s[:, 0], s[:, 1])
    parallel = np.abs(denom) <= _REL * length_r * length_s
    safe = np.where(parallel, 1.0, denom)
    t = cross_s / safe
    u = cross_r / safe
    crossing = (~parallel & (t >= -_REL) & (t <= 1.0 + _REL) & (u >= -_REL) & (u <= 1.0 + _REL))
    on_line = parallel & (np.abs(cross_r) <= _TOL_M * length_r)
    along_a = (ap @ r) / (length_r * length_r)
    along_b = along_a + (s @ r) / (length_r * length_r)
    first = np.maximum(np.minimum(along_a, along_b), 0.0)
    last = np.minimum(np.maximum(along_a, along_b), 1.0)
    overlap = on_line & (first <= last + _REL)
    return crossing | overlap, np.where(overlap, first, t)


def _first_crossing_units(rings: Sequence[np.ndarray], *, closed: bool
                          ) -> Generator[None, None, tuple[float, float] | None]:
    """El primer punto (locales) en que una polilínea, o los anillos de un polígono, se tocan a sí
    mismos: un cruce, un contacto o un solape de dos tramos que no son vecinos, o un tramo que
    vuelve sobre el anterior por la misma recta; ``None`` si no (en ``StopIteration.value``). ``rings``:
    cada camino (``closed`` falso) o anillo (``closed`` verdadero, **sin** repetir el primer vértice al
    final) en locales, sin vértices repetidos seguidos. Un anillo con otro (un hueco con su exterior)
    cuenta. **Por unidades** (T44; D-2 y A-3; RNF-015-03): una por tramo, que se mide con todos los
    siguientes (O(n²) en total: 0,3 s de una sola llamada con 3.000 vértices), en el orden de siempre y con el
    mismo primer punto."""
    first_edges, last_edges, identity, position, size = [], [], [], [], []
    for index, ring in enumerate(rings):
        if ring.shape[0] < 2:
            continue
        begin = ring if closed else ring[:-1]
        end = np.roll(ring, -1, axis=0) if closed else ring[1:]
        count = begin.shape[0]
        first_edges.append(begin)
        last_edges.append(end)
        identity.append(np.full(count, index))
        position.append(np.arange(count))
        size.append(np.full(count, count))
    if not first_edges:
        return None
    a, b = np.concatenate(first_edges), np.concatenate(last_edges)
    ids, pos, count = np.concatenate(identity), np.concatenate(position), np.concatenate(size)
    r = b - a
    for i in range(a.shape[0] - 1):
        yield
        j = np.arange(i + 1, a.shape[0])
        gap = pos[j] - pos[i]
        neighbours = (ids[j] == ids[i]) & ((gap == 1) | ((gap == count[i] - 1) & closed))
        j = j[~neighbours]
        if j.size == 0:
            continue
        hit, t = _hits(a[i], r[i], a[j], r[j])
        if hit.any():
            point = a[i] + t[int(np.flatnonzero(hit)[0])] * r[i]
            return float(point[0]), float(point[1])
    for index in range(len(rings)):
        own = ids == index
        if not own.any():
            continue
        steps, ends = r[own], b[own]
        now, then = (steps, np.roll(steps, -1, axis=0)) if closed else (steps[:-1], steps[1:])
        cross = now[:, 0] * then[:, 1] - now[:, 1] * then[:, 0]
        scale = np.hypot(now[:, 0], now[:, 1]) * np.hypot(then[:, 0], then[:, 1])
        back = (np.abs(cross) <= _REL * scale) & ((now * then).sum(axis=1) < 0.0)
        if back.any():
            vertex = ends[int(np.flatnonzero(back)[0])]
            return float(vertex[0]), float(vertex[1])
    return None


def _inside(points: np.ndarray, parts: Sequence[Sequence[np.ndarray]]) -> np.ndarray:
    """Si cada punto de ``points`` (``(m, 2)``, locales) está dentro de alguna de las partes de un
    polígono (``parts``: por parte, sus anillos cerrados sin repetir el primer vértice; el
    par-impar de sus anillos, un hueco incluido)."""
    found = np.zeros(points.shape[0], dtype=bool)
    px, py = points[:, 0][:, None], points[:, 1][:, None]
    for rings in parts:
        parity = np.zeros(points.shape[0], dtype=bool)
        for ring in rings:
            a, b = ring, np.roll(ring, -1, axis=0)
            straddles = (a[:, 1][None, :] > py) != (b[:, 1][None, :] > py)
            rise = np.where(b[:, 1] == a[:, 1], 1.0, b[:, 1] - a[:, 1])
            at = a[:, 0] + (py - a[:, 1]) * (b[:, 0] - a[:, 0]) / rise
            parity ^= ((straddles & (px < at)).sum(axis=1) % 2) == 1
        found |= parity
    return found


_INSIDE_WORK = 400_000
"""Los pares «punto × vértice» de una unidad de :func:`_inside_units` (≈ 20 ms)."""


def _inside_units(points: np.ndarray, parts: Sequence[Sequence[np.ndarray]]
                  ) -> Generator[None, None, np.ndarray]:
    """:func:`_inside` **por unidades** (T44; A-3; RNF-015-03): los puntos de ``points`` en bloques, uno por
    unidad (cada punto es independiente de los demás: el mismo resultado bit a bit). Con 2.000 pasos del eje
    y un contorno de 3.000 vértices, :func:`_inside` es una sola llamada con una matriz de 6 M de pares."""
    found = np.zeros(points.shape[0], dtype=bool)
    block = max(1, _INSIDE_WORK // max(1, sum(ring.shape[0] for rings in parts for ring in rings)))
    for first in range(0, points.shape[0], block):
        found[first:first + block] = _inside(points[first:first + block], parts)
        yield
    return found


def _on_boundary(point: np.ndarray, begin: np.ndarray, end: np.ndarray) -> bool:
    """Si ``point`` (local) está a ≤ :data:`_TOL_M` de algún tramo ``begin → end``."""
    step = end - begin
    length2 = (step * step).sum(axis=1)
    along = np.where(length2 > 0.0, ((point - begin) * step).sum(axis=1)
                     / np.where(length2 > 0.0, length2, 1.0), 0.0)
    near = begin + np.clip(along, 0.0, 1.0)[:, None] * step
    return bool((np.hypot(near[:, 0] - point[0], near[:, 1] - point[1]) <= _TOL_M).any())


def _dedupe(points: np.ndarray) -> np.ndarray:
    """``points`` sin los vértices que repiten al anterior (a ≤ :data:`_TOL_M`)."""
    if points.shape[0] < 2:
        return points
    step = np.hypot(*np.diff(points, axis=0).T)
    return points[np.concatenate(([True], step > _TOL_M))]


def _ring(points: np.ndarray) -> np.ndarray:
    """Un anillo (locales) sin vértices repetidos y sin el que repite el primero al final."""
    ring = _dedupe(points)
    if ring.shape[0] > 1 and math.hypot(*(ring[-1] - ring[0])) <= _TOL_M:
        ring = ring[:-1]
    return ring


def _degenerate(ring: np.ndarray) -> bool:
    """Si todos los vértices de ``ring`` están alineados (a ≤ :data:`_TOL_M` de la recta del primero
    al más lejano): no tiene área."""
    if ring.shape[0] < 3:
        return True
    offset = ring - ring[0]
    far = offset[int(np.argmax(np.hypot(offset[:, 0], offset[:, 1])))]
    norm = math.hypot(far[0], far[1])
    if norm <= _TOL_M:
        return True
    return bool((np.abs(offset[:, 0] * far[1] - offset[:, 1] * far[0]) / norm).max() <= _TOL_M)


def _shoelace(ring: np.ndarray) -> float:
    """El área (m²) de un anillo en locales, sin signo."""
    nxt = np.roll(ring, -1, axis=0)
    return abs(0.5 * float((ring[:, 0] * nxt[:, 1] - nxt[:, 0] * ring[:, 1]).sum()))


def _origin(grid: Grid) -> np.ndarray:
    """La esquina noroeste de la rejilla: el origen de las coordenadas locales de un cálculo."""
    return np.array([grid.west, grid.north], dtype=np.float64)


# --- A1: el eje de una línea -------------------------------------------------------------------


def _line_path_units(job: PlatformJob) -> Generator[None, None, np.ndarray]:
    """El camino (absoluto, ``(k, 2)``) de la línea de la plataforma, comprobado (RF-015-08): una
    sola parte (``des.platform_axis_parts``), con longitud (``des.platform_axis_length_zero``), abierta
    (``des.platform_axis_closed``) y que no se corta a sí misma (``des.platform_self_intersects``,
    con el punto, absoluto). Por unidades (T44): la comprobación de los cruces cede el hilo tramo a tramo
    (:func:`_first_crossing_units`)."""
    request = job.request
    paths = [path for path in axis_paths(job.geometry.parts) if path.shape[0] > 0]
    if len(paths) > 1:
        raise _reject("des.platform_axis_parts", request, _GEOMETRY, len(paths))
    path = paths[0] if paths else np.empty((0, 2))
    length = (math.fsum(np.hypot(*np.diff(path, axis=0).T).tolist())
              if path.shape[0] > 1 else 0.0)
    if not length > 0.0:
        raise _reject("des.platform_axis_length_zero", request, _GEOMETRY, 0.0)
    if path.shape[0] >= 3 and math.hypot(*(path[-1] - path[0])) <= _TOL_M:
        raise _reject("des.platform_axis_closed", request, _GEOMETRY, length)
    origin = _origin(job.grid)
    hit = yield from _first_crossing_units([_dedupe(path - origin)], closed=False)
    if hit is not None:
        x, y = hit[0] + float(origin[0]), hit[1] + float(origin[1])
        raise _reject("des.platform_self_intersects", request, _GEOMETRY, f"{x:.3f}, {y:.3f}",
                      x=x, y=y)
    return path


def _trim(cells: np.ndarray, rows: slice, cols: slice) -> tuple[slice, slice, np.ndarray] | None:
    """La caja de las celdas ``True`` de ``cells`` (la ventana ``rows`` × ``cols`` de la rejilla):
    ``(filas, columnas, celdas dentro de la caja)``; ``None`` si no hay ninguna."""
    found_rows = np.flatnonzero(cells.any(axis=1))
    if found_rows.size == 0:
        return None
    found_cols = np.flatnonzero(cells.any(axis=0))
    r0, r1 = int(found_rows[0]), int(found_rows[-1]) + 1
    c0, c1 = int(found_cols[0]), int(found_cols[-1]) + 1
    return (slice(rows.start + r0, rows.start + r1), slice(cols.start + c0, cols.start + c1),
            cells[r0:r1, c0:c1])


# --- A1: el eje de un polígono -----------------------------------------------------------------


def axis_of_polygon(cells: np.ndarray, grid: Grid, *, offset: tuple[int, int] = (0, 0)) -> Axis:
    """**A1** (RF-015-19): el **eje principal** de las celdas ``cells`` (booleana: toda la rejilla
    ``grid`` o una ventana suya cuya primera celda es la ``offset`` = (fila, columna)): la dirección
    propia mayor de la matriz de covarianza de los centros de celda (con la misma varianza en las dos
    direcciones, la este-oeste), por el centro de las celdas y de extremo a extremo de la huella (de
    los centros extremos, ampliados media celda en cada extremo). Su sentido, el de la abscisa 0: el
    extremo más al oeste y, a igual abscisa x (a ≤ :data:`_TOL_M`), el del sur. Devuelve un
    :class:`~.model.Axis` ``principal`` de coordenadas absolutas float64 (los cálculos van en locales
    desde la esquina de la rejilla). ``ValueError`` si no hay ninguna celda (lo rechaza antes
    :func:`platform_footprint`). Ninguna entrada se modifica."""
    rows, cols = np.nonzero(cells)
    if rows.size == 0:
        raise ValueError("el eje principal de un polígono pide al menos una celda")
    x = (cols + offset[1] + 0.5) * grid.dx
    y = -(rows + offset[0] + 0.5) * grid.dy  # locales desde la esquina noroeste, Y hacia el norte
    ex, ey = x - x.mean(), y - y.mean()
    var_x, var_y, covariance = float((ex * ex).mean()), float((ey * ey).mean()), float(
        (ex * ey).mean())
    if covariance == 0.0:
        ux, uy = (1.0, 0.0) if var_x >= var_y else (0.0, 1.0)
    else:
        angle = 0.5 * math.atan2(2.0 * covariance, var_x - var_y)
        ux, uy = math.cos(angle), math.sin(angle)
    along = ex * ux + ey * uy
    half_cell = 0.5 * (abs(ux) * grid.dx + abs(uy) * grid.dy)
    ends = [(float(x.mean()) + (t * ux), float(y.mean()) + (t * uy))
            for t in (float(along.min()) - half_cell, float(along.max()) + half_cell)]
    (xa, ya), (xb, yb) = ends
    if xb - xa < -_TOL_M or (abs(xb - xa) <= _TOL_M and yb < ya):
        (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
    return Axis(((grid.west + xa, grid.north + ya), (grid.west + xb, grid.north + yb)),
                principal=True)


def _polygon_rings_units(job: PlatformJob) -> Generator[None, None, list[list[np.ndarray]]]:
    """Los anillos (locales, cerrados sin repetir el primer vértice) de cada parte con área del
    polígono, comprobados (RF-015-08): sin área (``des.platform_area_zero``: todas las partes
    degeneradas o un área neta de 0) o que se corta a sí misma o a un hueco
    (``des.platform_self_intersects``, con el punto, absoluto). Por unidades (T44): los cruces ceden el hilo
    tramo a tramo."""
    request, origin = job.request, _origin(job.grid)
    live: list[list[np.ndarray]] = []
    for part in job.geometry.parts:
        rings = [_ring(points - origin) for points in part]
        if not rings or _degenerate(rings[0]):
            continue
        live.append([rings[0], *(ring for ring in rings[1:] if not _degenerate(ring))])
    if not live:
        raise _reject("des.platform_area_zero", request, _GEOMETRY, 0.0)
    for rings in live:
        hit = yield from _first_crossing_units(rings, closed=True)
        if hit is not None:
            x, y = hit[0] + float(origin[0]), hit[1] + float(origin[1])
            raise _reject("des.platform_self_intersects", request, _GEOMETRY,
                          f"{x:.3f}, {y:.3f}", x=x, y=y)
    area = math.fsum(_shoelace(rings[0]) - math.fsum(_shoelace(hole) for hole in rings[1:])
                     for rings in live)
    if not area > 0.0:
        raise _reject("des.platform_area_zero", request, _GEOMETRY, area)
    return live


def _linked_axis_units(job: PlatformJob, parts: list[list[np.ndarray]]) -> Generator[None, None, Axis]:
    """El eje de un polígono con su línea enlazada: **la parte de la línea que está dentro del
    polígono** (de su entrada a su salida, con los vértices de la línea que haya dentro), que ha de
    cruzarlo de lado a lado: una sola parte dentro, con sus dos extremos en el contorno y con
    longitud. Si no (la línea empieza o acaba dentro, no lo toca, lo cruza varias veces o roza el
    contorno), ``des.platform_axis_not_crossing`` con el campo del enlace y el nombre del eje; una línea de
    varias partes, ``des.platform_axis_parts``. ``parts``: los anillos de :func:`_polygon_rings_units`. Por
    unidades (T44): cada tramo de la línea frente al contorno y los puntos medios dentro del polígono, por
    bloques."""
    request, geometry, grid = job.request, job.geometry, job.grid
    assert geometry.axis_parts is not None
    paths = [path for path in axis_paths(geometry.axis_parts) if path.shape[0] > 0]
    if len(paths) > 1:
        raise _reject("des.platform_axis_parts", request, _GEOMETRY, len(paths))

    def not_crossing() -> DesignError:
        return _reject("des.platform_axis_not_crossing", request,
                       request.fields.axis_field or _LINK_FIELD, geometry.axis_name)

    if not paths or paths[0].shape[0] < 2:
        raise not_crossing()
    path, origin = paths[0], _origin(grid)
    line = path - origin
    begin = np.concatenate([ring for rings in parts for ring in rings])
    end = np.concatenate([np.roll(ring, -1, axis=0) for rings in parts for ring in rings])
    pieces: list[tuple[int, float, float]] = []
    edges = end - begin
    for k in range(line.shape[0] - 1):
        yield
        step = line[k + 1] - line[k]
        length = math.hypot(step[0], step[1])
        if not length > 0.0:
            continue
        hit, t = _hits(line[k], step, begin, edges)
        cuts = np.unique(np.concatenate(([0.0, 1.0], np.clip(t[hit], 0.0, 1.0))))
        pieces.extend((k, float(t0), float(t1)) for t0, t1 in zip(cuts[:-1], cuts[1:], strict=True)
                      if (t1 - t0) * length > _TOL_M)
    if not pieces:
        raise not_crossing()
    k_of = np.array([piece[0] for piece in pieces])
    mid_t = np.array([0.5 * (piece[1] + piece[2]) for piece in pieces])
    middles = line[k_of] + mid_t[:, None] * (line[k_of + 1] - line[k_of])
    runs: list[list[int]] = []
    current: list[int] | None = None
    for index, inside in enumerate((yield from _inside_units(middles, parts))):
        if not inside:
            current = None
            continue
        if current is None:
            current = []
            runs.append(current)
        current.append(index)
    if len(runs) != 1:
        raise not_crossing()
    first, last = pieces[runs[0][0]], pieces[runs[0][-1]]
    starts_in = first[0] == 0 and first[1] == 0.0 and not _on_boundary(line[0], begin, end)
    ends_in = (last[0] == line.shape[0] - 2 and last[2] == 1.0
               and not _on_boundary(line[-1], begin, end))
    if starts_in or ends_in:
        raise not_crossing()

    def point(k: int, t: float) -> tuple[float, float]:
        if t == 0.0:
            return float(path[k][0]), float(path[k][1])
        if t == 1.0:
            return float(path[k + 1][0]), float(path[k + 1][1])
        found = line[k] + t * (line[k + 1] - line[k])
        return float(found[0] + origin[0]), float(found[1] + origin[1])

    points: list[tuple[float, float]] = []
    for position, index in enumerate(runs[0]):
        k, t0, t1 = pieces[index]
        for t in ((t0, t1) if position == 0 else (t1,)):
            found = point(k, t)
            if not points or math.hypot(found[0] - points[-1][0],
                                        found[1] - points[-1][1]) > _TOL_M:
                points.append(found)
    if len(points) < 2:
        raise not_crossing()
    return Axis(tuple(points))


_NEAR_TILE_CELLS = 32
"""El lado (celdas) de la tesela con que se mide el eje de un polígono (:func:`_nearest_abscissa_units`): menor
que la de un corredor porque cada celda toma el tramo más próximo de todo el eje, y las de una tesela pequeña
tienen pocos candidatos."""


def _nearest_abscissa_units(path: np.ndarray, grid: Grid, rows: slice, cols: slice,
                            needed: np.ndarray | None = None
                            ) -> Generator[None, None, tuple[np.ndarray, np.ndarray]]:
    """La abscisa σ (m desde el primer vértice de ``path``, absoluto) del punto del camino más
    próximo al centro de cada celda de las filas ``rows`` y columnas ``cols`` (fijada en los
    extremos del camino: es la de su vértice; a igual distancia de dos tramos, la menor) y la
    abscisa **sin recortar** (la de la proyección sobre la recta de ese tramo), dos rejillas de la
    forma de la ventana (en ``StopIteration.value``). Todas las celdas, a diferencia de
    :func:`~.quarry.axis_abscissa`, que mide un corredor: con ``needed`` (la forma de la ventana), solo las
    de esa máscara (las demás, ``NaN``), que es lo que usa la huella (las celdas del polígono).

    **Por unidades** (T44; D-2 y A-3; RNF-015-03, RF-015-29): la ventana, por teselas de 32 × 32 celdas, y
    cada una con los tramos que pueden ser el más próximo de alguna de sus celdas —los que quedan, de su centro,
    a no más de la distancia del tramo más próximo más una diagonal—, en el orden del eje, no con todos: lo que
    era O(tramos × celdas de la caja) es ahora O(celdas × tramos cercanos), con **el mismo resultado bit a
    bit** (el tramo más próximo y su desempate, el anterior, son los de siempre: los que se dejan fuera quedan
    más lejos que el que gana)."""
    shape = (max(rows.stop - rows.start, 0), max(cols.stop - cols.start, 0))
    sigma = np.full(shape, np.nan)
    reach = np.full(shape, np.nan)
    segments = _axis_segments([np.asarray(path, dtype=np.float64)])
    if segments is None or sigma.size == 0:
        return sigma, reach
    yield
    slack = _slack(grid)
    skipped = 0
    for tile in _tiles((rows, cols), _NEAR_TILE_CELLS):
        r0, r1, c0, c1 = tile
        at = (slice(r0 - rows.start, r1 - rows.start), slice(c0 - cols.start, c1 - cols.start))
        if needed is not None and not needed[at].any():
            skipped += 1
            if skipped >= _EMPTY_TILES:
                skipped = 0
                yield
            continue
        centre, diagonal = _tile_box(grid, tile)[4:]
        distance = _centre_distance(segments, centre)
        found = np.flatnonzero(distance <= float(distance.min()) + 2.0 * (diagonal + slack))
        row_index = np.arange(r0, r1, dtype=np.float64)
        col_index = np.arange(c0, c1, dtype=np.float64)
        best = np.full((row_index.size, col_index.size), np.inf)
        here = np.full(best.shape, np.nan)
        beyond = np.full(best.shape, np.nan)
        per_unit = max(1, _UNIT_WORK // best.size)
        for count, k in enumerate(found.tolist(), start=1):
            length, walked = segments.length[k], segments.walked[k]
            along, across = _segment_frame(segments.start[k], segments.end[k], length, grid,
                                           row_index, col_index)
            clamped = np.clip(along, 0.0, length)
            distance2 = across * across + (along - clamped) ** 2
            better = distance2 < best
            best[better] = distance2[better]
            here[better] = (walked + clamped)[better]
            beyond[better] = (walked + along)[better]
            if count % per_unit == 0:
                yield
        sigma[at] = here
        reach[at] = beyond
        yield
    return sigma, reach


# --- A0 y A1: la huella y la rasante -----------------------------------------------------------


def platform_footprint_units(job: PlatformJob) -> Generator[None, None, Footprint]:
    """**A0 y A1** (RF-015-19, RF-015-08; plan 015 §5.4): la huella y la rasante de la plataforma de
    ``job`` en su ventana de trabajo, **por unidades** (cada ``yield``, una; para componerlas con
    ``pace_units``; T44 de la 015, hallazgos D-2 y A-3; RNF-015-03, RNF-015-05, RF-015-29): lo mismo que
    :func:`platform_footprint` —que es esta llevada hasta el final—, con la :class:`Footprint` en
    ``StopIteration.value`` y **el mismo resultado bit a bit**. Una huella no es una sola llamada: un eje
    digitalizado de 400 vértices sobre 2,81 M celdas tardaba 9 s sin ceder el hilo de Blender ni dejarse
    cancelar. Ahora ceden el hilo, en unidades de pocos milisegundos, la comprobación de que el eje no se
    corta (un tramo con los siguientes), la del contorno del polígono, la de su eje enlazado, la abscisa de
    cada celda (:func:`~.quarry.axis_abscissa_units` y :func:`_nearest_abscissa_units`: por teselas y con los
    tramos que llegan a cada una) y el armado de las rejillas de la ventana de trabajo; los rechazos son los
    mismos y salen en el mismo orden al avanzar. Cerrar el generador a mitad (Esc) no deja nada: no escribe
    nada y no modifica la entrada."""
    request, geometry, grid = job.request, job.geometry, job.grid
    if geometry.kind not in ("line", "polygon"):
        raise _reject("des.platform_layer_kind", request, _GEOMETRY, _KINDS_ES[geometry.kind])
    line = geometry.kind == "line"
    start_level, gradient, reach_m, width = _resolved(job, line=line)
    metric = _metric(job)
    notices: list[Notice] = []
    if line:
        assert width is not None
        path = yield from _line_path_units(job)
        axis = Axis(tuple((float(x), float(y)) for x, y in path))
        _check_levels(job, axis.length_m, start_level, gradient)
        yield
        window = corridor_window([path], width / 2.0, grid)
        sigma, reach = yield from axis_abscissa_units([path], width / 2.0, grid, window)
        cells = np.isfinite(sigma)
        box = _trim(cells, *window)
        if box is None:
            raise _reject("des.platform_no_cells", request, _GEOMETRY, 0)
        rows, cols, _ = box
        inner = (slice(rows.start - window[0].start, rows.stop - window[0].start),
                 slice(cols.start - window[1].start, cols.stop - window[1].start))
        cells, sigma, reach = cells[inner], sigma[inner], reach[inner]
    else:
        parts = yield from _polygon_rings_units(job)
        top, left, block = _paint(_polygon_spans(geometry.parts, grid), grid.nrows, grid.ncols)
        yield
        box = _trim(block, slice(top, top + block.shape[0]), slice(left, left + block.shape[1]))
        if box is None:
            raise _reject("des.platform_no_cells", request, _GEOMETRY, 0)
        rows, cols, cells = box
        if geometry.axis_parts is None:
            axis = axis_of_polygon(cells, grid, offset=(rows.start, cols.start))
            (xa, ya), (xb, yb) = axis.vertices
            notices.append(Notice("des.platform_axis_principal", {
                "entity": request.name, "x": xa, "y": ya, "x_end": xb, "y_end": yb}))
        else:
            axis = yield from _linked_axis_units(job, parts)
        _check_levels(job, axis.length_m, start_level, gradient)
        yield
        sigma, reach = yield from _nearest_abscissa_units(np.array(axis.vertices), grid, rows, cols, cells)
        sigma, reach = np.where(cells, sigma, np.nan), np.where(cells, reach, np.nan)
    yield
    window = work_window(rows, cols, reach_m, grid, metric)
    shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
    at = (slice(rows.start - window[0].start, rows.stop - window[0].start),
          slice(cols.start - window[1].start, cols.stop - window[1].start))
    footprint = np.zeros(shape, dtype=bool)
    footprint[at] = cells
    abscissa = np.full(shape, np.nan)
    abscissa[at] = sigma
    yield
    levels = np.full(shape, np.nan)
    levels[footprint] = start_level + abscissa[footprint] * gradient / 100.0
    found = reach[cells]
    return Footprint(window, footprint, abscissa, levels, axis, float(found.max() - found.min()),
                     start_level, gradient, grid.cell_area, tuple(notices))


def platform_footprint(job: PlatformJob) -> Footprint:
    """**A0 y A1** (RF-015-19, RF-015-08; plan 015 §5.4): la huella y la rasante de la plataforma de
    ``job`` en su ventana de trabajo. Con una **línea** (su eje, con el ancho ``width_m``), la huella
    es la del corredor de extremos planos de RF-014-09 y σ, la abscisa del punto más próximo de todo
    el eje; con un **polígono**, las celdas por su centro y σ la del punto más próximo de su eje
    (fijada en los extremos): el enlazado —su parte de dentro, de lado a lado— o, sin enlace, el
    principal (:func:`axis_of_polygon`), con el aviso ``des.platform_axis_principal``. La rasante de
    cada celda es ``cota inicial + σ · pendiente / 100`` (sección horizontal), a ≤ 10⁻⁹ m del
    cálculo a mano. Los rechazos, en el orden de la documentación del módulo; no modifica la
    entrada. Es :func:`platform_footprint_units` llevada hasta el final, sin ceder el hilo: quien
    calcula en Blender usa las unidades."""
    return _run_units(platform_footprint_units(job))


# --- A2: aplicar la plataforma -----------------------------------------------------------------


class OffLevelCause(StrEnum):
    """Por qué una celda de la huella no queda en la rasante (RF-015-13, RF-015-24): ``CUT_DENIED``
    (``cut_allowed`` falso: está por encima y las máscaras no dejan cortar), ``FILL_DENIED``
    (``fill_allowed`` falso: en «en corte y relleno» está por debajo y las máscaras no dejan
    rellenar) y ``NOT_FILLED`` (está por debajo en el modo «en corte», que no rellena: no es lo que
    una máscara impide). El valor es el nombre de la máscara o del modo."""

    CUT_DENIED = "cut_allowed"
    FILL_DENIED = "fill_allowed"
    NOT_FILLED = "cut_mode"


@dataclass(frozen=True, slots=True)
class OffLevel:
    """Un grupo 4-conexo de celdas de la huella que no quedan en la rasante (A2, RF-015-24): su
    número ``group`` (desde 1, en el orden de su primera celda recorriendo la rejilla fila a fila
    desde el norte), su ``cause``, sus ``cells``, su ``area_m2``, su diferencia máxima con la rasante
    ``max_m`` (m, positiva) y su centro ``x``, ``y`` (m, absolutos en float64: la media de los
    centros de sus celdas)."""

    group: int
    cause: OffLevelCause
    cells: int
    area_m2: float
    max_m: float
    x: float
    y: float


@dataclass(frozen=True, slots=True, eq=False)
class Applied:
    """La plataforma aplicada sobre su superficie de partida (A2; RF-015-20, RF-015-21), en la
    ventana de trabajo de su huella (``window``; todas las rejillas son de su forma) y en el
    ``mode`` pedido: ``surface`` (m, float64, **nueva**: la superficie de partida con la huella
    aplicada; el resto, igual) y ``at_level`` (la huella que queda en la rasante a 10⁻⁹ m: las
    semillas del borde).

    ``cut_m3`` y ``fill_m3`` son el corte y el relleno **de la huella** (m³; el del borde, :class:`Edge`) y
    ``cut_cells`` y ``fill_cells``, las celdas que bajan y que suben. Lo que no queda en la rasante:
    ``above`` (por encima, que son las celdas que las máscaras no dejan cortar) y ``below`` (por
    debajo: lo que el modo «en corte» no rellena o, en «en corte y relleno», lo que las máscaras no
    dejan rellenar), cada uno en grupos (:class:`OffLevel`); y las máscaras de lo que **las máscaras**
    impiden, ``cut_denied`` y ``fill_denied`` (esta, solo en «en corte y relleno»), para mirar de qué
    restricción es esa zona (RF-015-13)."""

    window: tuple[slice, slice]
    mode: PlatformMode
    surface: np.ndarray
    at_level: np.ndarray
    cut_cells: int
    fill_cells: int
    cut_m3: float
    fill_m3: float
    cut_denied: np.ndarray
    fill_denied: np.ndarray
    above: tuple[OffLevel, ...]
    below: tuple[OffLevel, ...]
    cell_area_m2: float

    @property
    def blocked_cells(self) -> int:
        """Las celdas de la huella que las máscaras no dejan mover (cortar o rellenar)."""
        return int(np.count_nonzero(self.cut_denied)) + int(np.count_nonzero(self.fill_denied))

    @property
    def blocked_area_m2(self) -> float:
        """El área (m²) que las máscaras no dejan mover: la de ``blocked_cells``."""
        return self.blocked_cells * self.cell_area_m2


def _mode(job: PlatformJob) -> PlatformMode:
    """El modo de la plataforma de ``job`` (``des.entity_param_choice`` si no es de su lista); sin el
    valor, el de la familia de parámetros («en corte», D-5)."""
    found = job.values.get(PlatformParam.MODE.value)
    if found is None:
        found = PLATFORM_PARAMS[PlatformParam.MODE.value].default
    return PlatformMode(check_entity_param(job.request.name, job.code, PlatformParam.MODE, found,
                                           layer=job.request.layer))


def _check_footprint(job: PlatformJob, footprint: Footprint) -> None:
    """``ValueError`` (error del programa) si la ventana de ``footprint`` no cabe en la rejilla de
    ``job`` o sus rejillas no son de su forma."""
    rows, cols = footprint.window
    grid = job.grid
    if not (0 <= rows.start < rows.stop <= grid.nrows and 0 <= cols.start < cols.stop <= grid.ncols
            and rows.step in (None, 1) and cols.step in (None, 1)):
        raise ValueError(f"la ventana de la huella ({rows}, {cols}) no cabe en la rejilla del "
                         f"trabajo de {grid.nrows} filas y {grid.ncols} columnas")
    shape = (rows.stop - rows.start, cols.stop - cols.start)
    for name in ("cells", "levels"):
        found = getattr(footprint, name).shape
        if found != shape:
            raise ValueError(f"«{name}» de la huella es de la forma {found}, no de la de su "
                             f"ventana {shape}")


def _group_units(chosen: np.ndarray, rows: np.ndarray, cols: np.ndarray, depth: np.ndarray,
                 cause: OffLevelCause, grid: Grid, window: tuple[slice, slice],
                 box: tuple[slice, slice]) -> Generator[None, None, tuple[OffLevel, ...]]:
    """Los grupos 4-conexos (:class:`OffLevel`) de las celdas de la huella ``chosen`` (de las
    celdas de la huella, en su orden): ``rows`` y ``cols`` son su posición en la ventana, ``depth``
    su diferencia con la rasante y ``box`` la caja de la huella en la ventana (el etiquetado solo
    recorre esa caja). Las unidades del etiquetado son las de ``grids._label_units``."""
    if not chosen.any():
        return ()
    picked_rows, picked_cols = rows[chosen], cols[chosen]
    mask = np.zeros((box[0].stop - box[0].start, box[1].stop - box[1].start), dtype=bool)
    mask[picked_rows - box[0].start, picked_cols - box[1].start] = True
    labels = yield from _label_units(mask)
    tags = labels.grid[picked_rows - box[0].start, picked_cols - box[1].start]
    count = labels.count + 1
    row_sum = np.bincount(tags, weights=picked_rows + window[0].start, minlength=count)
    col_sum = np.bincount(tags, weights=picked_cols + window[1].start, minlength=count)
    top = np.zeros(count)
    np.maximum.at(top, tags, depth[chosen])
    found = []
    for index in range(1, count):
        cells = int(labels.sizes[index - 1])
        x = grid.west + (col_sum[index] / cells + 0.5) * grid.dx
        y = grid.north - (row_sum[index] / cells + 0.5) * grid.dy
        found.append(OffLevel(index, cause, cells, cells * grid.cell_area, float(top[index]),
                              float(x), float(y)))
    return tuple(found)


def _apply_units(job: PlatformJob, footprint: Footprint, mode: PlatformMode
                 ) -> Generator[None, None, Applied]:
    """Las unidades de :func:`apply_platform_steps`: las celdas de la huella (sin bucle por celda,
    sobre las de la huella y no sobre la ventana), la superficie y los grupos."""
    window, cells, grid = footprint.window, footprint.cells, job.grid
    start = job.start_in(window)
    z = start[cells]
    level = footprint.levels[cells]
    missing = int(np.count_nonzero(~np.isfinite(z)))
    if missing or not np.isfinite(level).all():
        raise ValueError(
            f"la plataforma «{job.request.name}» ({job.code}) tiene {missing} celdas sin dato en "
            "su huella (o una rasante sin cota): la preparación lo rechaza antes de calcular "
            "(RF-015-09)")
    yield None
    new = np.where(job.cut_in(window)[cells], np.minimum(z, level), z)
    if mode is PlatformMode.CUT_FILL:
        new = np.where(job.fill_in(window)[cells] & (z < level), level, new)
    drop = z - new
    gap = new - level
    near = np.abs(gap) <= _TOL_M
    above = gap > _TOL_M
    below = gap < -_TOL_M
    cut_m3 = float(np.sum(np.maximum(drop, 0.0))) * grid.cell_area
    fill_m3 = float(np.sum(np.maximum(-drop, 0.0))) * grid.cell_area
    yield None
    surface = np.array(start, dtype=np.float64, copy=True)
    surface[cells] = new
    at_level = np.zeros(cells.shape, dtype=bool)
    at_level[cells] = near
    cut_denied = np.zeros(cells.shape, dtype=bool)
    cut_denied[cells] = above
    fill_denied = np.zeros(cells.shape, dtype=bool)
    if mode is PlatformMode.CUT_FILL:
        fill_denied[cells] = below
    yield None
    rows, cols = np.nonzero(cells)
    box = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    over = yield from _group_units(above, rows, cols, gap, OffLevelCause.CUT_DENIED, grid, window,
                                   box)
    why = OffLevelCause.FILL_DENIED if mode is PlatformMode.CUT_FILL else OffLevelCause.NOT_FILLED
    under = yield from _group_units(below, rows, cols, -gap, why, grid, window, box)
    return Applied(window, mode, surface, at_level, int(np.count_nonzero(drop > 0.0)),
                   int(np.count_nonzero(drop < 0.0)), cut_m3, fill_m3, cut_denied, fill_denied,
                   over, under, grid.cell_area)


def apply_platform_steps(job: PlatformJob, footprint: Footprint, *,
                         budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A2** (RF-015-20, RF-015-21, RF-015-06, RF-015-13; plan 015 §5.4): aplica la plataforma de
    ``job`` con su ``footprint`` (:func:`platform_footprint`) sobre su superficie de partida, por
    pasos de ``budget_s`` como mucho: el último ``Progress`` (fase ``platform_apply``) lleva el
    :class:`Applied`.

    En el modo «en corte» (el de por defecto) ``z' = mín(z, rasante)`` en las celdas de la huella con
    ``cut_allowed``: **ninguna celda sube** (el lomo de B7: la plataforma es el fondo de su corredor,
    no una cota mínima). En «en corte y relleno», además ``z' = rasante`` donde ``z < rasante`` y
    ``fill_allowed``. Fuera de la huella y donde las máscaras no dejan mover, ``z' = z`` bit a bit.
    El corte y el relleno son los de la huella (m³); los del borde, de :func:`platform_edge`. Lo que no queda en la
    rasante se agrupa con su área, su diferencia máxima, su lugar y su causa (:class:`Applied`).

    Rechazos al llamar: un modo que no es de la lista (``des.entity_param_choice``, con la entidad, el
    campo y el valor; sin el valor ``mode``, el de por defecto) y ``ValueError`` (errores del
    programa) si la ventana de la huella no es de la rejilla del trabajo; al avanzar, ``ValueError``
    si falta dato en la huella (lo rechaza antes la preparación, RF-015-09, T11: no se oculta con un
    valor). Ninguna entrada se modifica y no se escribe nada; cerrar el generador a mitad no deja
    nada."""
    mode = _mode(job)
    _check_footprint(job, footprint)
    work = _apply_units(job, footprint, mode)
    return pace_progress(work, budget_s, phase="platform_apply",
                         running="Aplicando la plataforma…", finished="Plataforma aplicada")


def apply_platform(job: PlatformJob, footprint: Footprint) -> Applied:
    """**A2**: :func:`apply_platform_steps` hasta el final, sin pasos: el :class:`Applied` de la
    plataforma de ``job`` con su ``footprint``. Los mismos rechazos."""
    mode = _mode(job)
    _check_footprint(job, footprint)
    work = _apply_units(job, footprint, mode)
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


# --- A3: el borde ------------------------------------------------------------------------------

_EDGE_PHASE = "platform_edge"


class WallCause(StrEnum):
    """Por qué una celda del borde queda más empinada que el ángulo de borde más la tolerancia de cara
    y que el terreno (RF-015-22, RF-015-13): ``REACH`` (junto a una celda que el alcance deja sin tocar: la
    envolvente llegó a su límite sin encontrar el terreno y la pared queda ahí), ``MASKS`` (junto a lo
    que las máscaras no dejan mover: una celda del borde que no se corta ni se rellena, o una de la
    huella que no se mueve) y ``OTHER`` (ninguna de las dos: la pared viene de la propia plataforma
    —su pendiente, más empinada que el ángulo de borde, o lo que no queda en su rasante—, no del
    borde). Las dos primeras son las únicas que RF-015-22 admite y avisa; ``OTHER`` es lo que no
    debería haber. El valor es el nombre de la causa."""

    REACH = "reach"
    MASKS = "masks"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class EdgeWall:
    """Las celdas del borde más empinadas que el ángulo de borde más la tolerancia de cara (y que lo
    que el terreno ya tenía) por una misma ``cause`` (RF-015-22): cuántas (``cells``), su ``area_m2``, la mayor inclinación
    ``max_deg`` (°: la de la celda a la más distinta de sus 8 vecinas con dato, D-13) y el lugar de
    la primera celda con ella (``x``, ``y``: absolutos en float64; a igual inclinación, la primera
    de norte a sur y de oeste a este)."""

    cause: WallCause
    cells: int
    area_m2: float
    max_deg: float
    x: float
    y: float


@dataclass(frozen=True, slots=True, eq=False)
class Edge:
    """El borde de una plataforma (A3; RF-015-22, RF-015-13), en la ventana de trabajo de su huella
    (``window``; todas las rejillas son de su forma): ``surface`` (m, float64, **nueva**: la
    superficie de partida con la huella aplicada y el borde, ``z'``), ``in_reach`` (las celdas a
    ≤ ``reach_m`` de las semillas con la métrica ``metric``: lo que el alcance deja tocar), ``changed``
    (las celdas que el borde mueve, fuera de la huella), ``held`` (las que su envolvente movería y las
    máscaras no admiten: quedan como en la partida, y de ellas sale el área que no se mueve de
    RF-015-13), ``steep`` (las celdas movidas más empinadas que ``limit_deg`` y que lo que el terreno
    ya tenía en ellas) y ``outside`` (las
    movidas que llegan al borde de la rejilla o a celdas sin dato fuera de la huella).

    ``angle_deg``, ``mesh_factor`` y ``reach_m`` son los de la entidad y ``tolerance_deg`` la
    tolerancia de cara de la 013 (:attr:`limit_deg` = ángulo + tolerancia). ``cut_m3`` y ``fill_m3``
    son el corte y el relleno **del borde** (m³, por separado; ``Σ |z − z'|`` por el área de la
    celda) y ``cut_cells`` y ``fill_cells``, las celdas que bajan y que suben. ``wall_max_m`` es la
    **altura máxima de su pared**, ``máx(|z − z'|)`` sobre las celdas que el borde mueve (m; 0 sin
    ninguna: interpretación del plan, [I], que CE-015-07 comprueba a mano), con su lugar
    (``wall_x``, ``wall_y``: absolutos, la primera de norte a sur y de oeste a este; ``None`` sin
    borde). ``walls`` son las celdas de ``steep`` por causa (:class:`EdgeWall`, las que tienen
    alguna, en el orden de :class:`WallCause`) y ``created`` el salto creado de la 014 (A11,
    :class:`~.edges.EdgeReport`) de la superficie entera (huella y borde) frente a la de partida.
    ``notices`` son los avisos ya armados (``preview.Notice``, en este orden): la pared del borde
    (``des.platform_edge_steep``), lo que llega al borde de la rejilla o a celdas sin dato
    (``des.entity_edge_outside``) y el salto creado y sus tramos (``des.edge_surface_step`` y
    ``des.edge_stretch``, con el nombre de la entidad). Los de lo que no se mueve por la restricción
    de otra entidad y el de magnitud son de la tarea que los junta con el resto del resumen (T12;
    :func:`magnitude_notices`)."""

    window: tuple[slice, slice]
    surface: np.ndarray
    in_reach: np.ndarray
    changed: np.ndarray
    held: np.ndarray
    steep: np.ndarray
    outside: np.ndarray
    metric: Metric
    angle_deg: float
    mesh_factor: float
    reach_m: float
    tolerance_deg: float
    cut_cells: int
    fill_cells: int
    cut_m3: float
    fill_m3: float
    wall_max_m: float
    wall_x: float | None
    wall_y: float | None
    walls: tuple[EdgeWall, ...]
    created: EdgeReport
    cell_area_m2: float
    notices: tuple[Notice, ...]

    @property
    def limit_deg(self) -> float:
        """La inclinación que una celda del borde puede pasar sin avisar (°): el ángulo de borde más
        la tolerancia de cara."""
        return self.angle_deg + self.tolerance_deg

    @property
    def changed_cells(self) -> int:
        """Las celdas que el borde mueve."""
        return int(np.count_nonzero(self.changed))

    @property
    def held_cells(self) -> int:
        """Las celdas del borde que las máscaras no dejan mover."""
        return int(np.count_nonzero(self.held))

    @property
    def held_area_m2(self) -> float:
        """El área del borde que las máscaras no dejan mover (m²)."""
        return self.held_cells * self.cell_area_m2

    @property
    def steep_cells(self) -> int:
        """Las celdas del borde más empinadas que el ángulo más la tolerancia."""
        return int(np.count_nonzero(self.steep))

    @property
    def outside_cells(self) -> int:
        """Las celdas que el borde mueve y llegan al borde de la rejilla o a celdas sin dato."""
        return int(np.count_nonzero(self.outside))

    @property
    def outside_area_m2(self) -> float:
        """Su área (m²)."""
        return self.outside_cells * self.cell_area_m2


@dataclass(frozen=True, slots=True)
class _EdgeSettings:
    """Lo que lee el borde, ya comprobado: los valores de la entidad (el ángulo de borde y su
    factor de malla, el alcance y la métrica) y los parámetros del proyecto (la tolerancia de cara,
    el espesor mínimo, el salto creado admitido y el porcentaje de parejas dentro de él)."""

    angle_deg: float
    mesh_factor: float
    reach_m: float
    metric: Metric
    tolerance_deg: float
    thickness_m: float
    threshold_m: float
    share_pct: float

    @property
    def tan(self) -> float:
        """La tangente efectiva de la envolvente: ``tan(ángulo de borde) · factor de malla``."""
        return math.tan(math.radians(self.angle_deg)) * self.mesh_factor


def _project_number(project: Mapping[str, object], key: str) -> float:
    """El parámetro del proyecto ``key`` de ``project`` como número finito; ``ValueError`` (error del
    programa: quien llama los lee del proyecto, ``PLATFORM_COMMON_PARAMS``) si no lo tiene."""
    value = project.get(key)
    if isinstance(value, bool) or not isinstance(value, numbers.Real) \
            or not math.isfinite(float(value)):
        raise ValueError(f"los parámetros del proyecto no dan un valor numérico de «{key}»: "
                         f"{value!r}")
    return float(value)


def _edge_settings(job: PlatformJob, project: Mapping[str, object]) -> _EdgeSettings:
    """Los valores del borde de ``job`` y los parámetros del proyecto, comprobados: el ángulo de
    borde, el alcance (obligatorio, D-20), el factor de malla y la métrica (``des.entity_param_*``,
    nombrando la plataforma, la clave y el valor; el ángulo y el alcance no tienen valor por
    defecto) y, del proyecto, la tolerancia de cara, el espesor mínimo y el salto admitido y su
    porcentaje (``des.quarry_param_*`` si salen de rango). El factor de malla de la plataforma es de
    (0; 10] (plan 015 §5.2.2); la envolvente se construye con ``tan · factor`` sin más tope."""
    name, code, found, layer = job.request.name, job.code, job.values, job.request.layer
    angle = check_entity_param(name, code, PlatformParam.EDGE_ANGLE,
                               found.get(PlatformParam.EDGE_ANGLE.value), layer=layer)
    reach = check_entity_param(name, code, PlatformParam.REACH,
                               found.get(PlatformParam.REACH.value), layer=layer)
    mesh = found.get(PlatformParam.MESH_FACTOR.value)
    if mesh is None:
        mesh = PLATFORM_PARAMS[PlatformParam.MESH_FACTOR.value].default
    mesh = check_entity_param(name, code, PlatformParam.MESH_FACTOR, mesh, layer=layer)
    assert isinstance(angle, float) and isinstance(reach, float) and isinstance(mesh, float)
    tolerance = _project_number(project, TOLERANCE_FACE)
    if tolerance < 0.0:
        raise ValueError(f"la tolerancia de cara es un número finito ≥ 0, no {tolerance!r}")
    thickness = _thickness(_project_number(project, VERIFY_MIN_THICKNESS))
    threshold = float(check_quarry_param(EDGE_MAX_STEP, _project_number(project, EDGE_MAX_STEP)))
    share = float(check_quarry_param(EDGE_MIN_SHARE, _project_number(project, EDGE_MIN_SHARE)))
    return _EdgeSettings(angle, mesh, reach, _metric(job), tolerance, thickness, threshold, share)


def _check_edge_inputs(job: PlatformJob, footprint: Footprint, applied: Applied,
                       settings: _EdgeSettings) -> None:
    """``ValueError`` (errores del programa) si ``footprint`` y ``applied`` no son de la misma
    ventana, de la forma de ``footprint`` o de ``job``, o si la ventana no cubre lo que el alcance
    de ``job`` puede tocar con su métrica (A0: el cálculo no sale de ella)."""
    _check_footprint(job, footprint)
    rows, cols = footprint.window
    if applied.window != footprint.window:
        raise ValueError("la plataforma aplicada es de otra ventana que la huella")
    shape = footprint.cells.shape
    for name in ("surface", "at_level", "cut_denied", "fill_denied"):
        found = getattr(applied, name).shape
        if found != shape:
            raise ValueError(f"«{name}» de la plataforma aplicada es de la forma {found}, no de la "
                             f"de la ventana {shape}")
    where_rows, where_cols = np.nonzero(footprint.cells)
    if not where_rows.size:
        raise ValueError("la huella no tiene ninguna celda")
    box = (slice(int(where_rows.min()) + rows.start, int(where_rows.max()) + 1 + rows.start),
           slice(int(where_cols.min()) + cols.start, int(where_cols.max()) + 1 + cols.start))
    needed = work_window(box[0], box[1], settings.reach_m, job.grid, settings.metric)
    if not (rows.start <= needed[0].start and needed[0].stop <= rows.stop
            and cols.start <= needed[1].start and needed[1].stop <= cols.stop):
        raise ValueError(
            f"la ventana de la huella ({rows}, {cols}) no cubre lo que un alcance de "
            f"{settings.reach_m} m puede tocar con la métrica {settings.metric.value} "
            f"({needed[0]}, {needed[1]}): se calculó con otro alcance u otra métrica")


def _window_grid(grid: Grid, window: tuple[slice, slice]) -> Grid:
    """La rejilla de la ventana ``window`` de ``grid`` (la esquina noroeste de su primera celda)."""
    rows, cols = window
    return Grid(grid.west + cols.start * grid.dx, grid.north - rows.start * grid.dy, grid.dx,
                grid.dy, cols.stop - cols.start, rows.stop - rows.start)


def _places(grid: Grid, window: tuple[slice, slice], rows: np.ndarray, cols: np.ndarray
            ) -> tuple[np.ndarray, np.ndarray]:
    """Los centros absolutos (float64) de las celdas ``rows``, ``cols`` de la ventana."""
    x = grid.west + (cols + window[1].start + 0.5) * grid.dx
    y = grid.north - (rows + window[0].start + 0.5) * grid.dy
    return x, y


def _drain[T](steps: Iterator[Progress]) -> Generator[None, None, T]:
    """Las unidades de un cálculo por pasos (``steps``: cada ``Progress`` es una unidad) y, al
    terminar, su resultado; cerrar el generador cierra ``steps``. Es lo que deja componer los pasos
    públicos de la 013 y la 014 (:func:`~.envelopes.reach_steps`, :func:`~.edges.created_steps`) con
    ``yield from`` dentro de las unidades del borde."""
    with closing(steps):  # type: ignore[type-var]
        for step in steps:
            if step.result is not None:
                return step.result  # type: ignore[return-value]
            yield None
    raise RuntimeError("los pasos terminaron sin dar resultado")


def _walls(grid: Grid, window: tuple[slice, slice], rows: np.ndarray, cols: np.ndarray,
           degrees: np.ndarray, far: np.ndarray, blocked: np.ndarray, area: float
           ) -> tuple[EdgeWall, ...]:
    """Las celdas empinadas (``rows``, ``cols`` de la ventana, con su inclinación ``degrees``) por
    causa: ``REACH`` si alguna de sus 8 vecinas es de ``far`` (con dato fuera de la huella y más allá
    del alcance), si no ``MASKS`` si alguna es de ``blocked`` (lo que las máscaras no dejan mover) y,
    si no, ``OTHER``. De cada causa, cuántas, su área y la peor con su lugar."""
    near_far = dilate_square(far, 1)[rows, cols]
    near_blocked = dilate_square(blocked, 1)[rows, cols]
    selectors = {WallCause.REACH: near_far, WallCause.MASKS: ~near_far & near_blocked,
                 WallCause.OTHER: ~near_far & ~near_blocked}
    found = []
    for cause in WallCause:
        picked = np.nonzero(selectors[cause])[0]
        if not picked.size:
            continue
        best = int(picked[int(np.argmax(degrees[picked]))])
        x, y = _places(grid, window, rows[best:best + 1], cols[best:best + 1])
        found.append(EdgeWall(cause, int(picked.size), float(picked.size) * area,
                              float(degrees[best]), float(x[0]), float(y[0])))
    return tuple(found)


def _edge_notices(name: str, settings: _EdgeSettings, walls: tuple[EdgeWall, ...],
                  outside: np.ndarray, created: EdgeReport, grid: Grid,
                  window: tuple[slice, slice]) -> tuple[Notice, ...]:
    """Los avisos del borde, en el orden de :class:`Edge`: la pared (una nota con las celdas de
    cada causa y la peor), lo que llega al borde de la rejilla o a celdas sin dato con su lugar (la
    primera celda) y el salto creado con sus tramos, con el nombre de la entidad."""
    found: list[Notice] = []
    if walls:
        by_cause = {wall.cause: wall.cells for wall in walls}
        worst = walls[0]
        for wall in walls[1:]:
            if wall.max_deg > worst.max_deg:
                worst = wall
        found.append(Notice("des.platform_edge_steep", {
            "entity": name, "cells": sum(by_cause.values()), "angle": settings.angle_deg,
            "tolerance": settings.tolerance_deg, "max": worst.max_deg,
            "limit": settings.angle_deg + settings.tolerance_deg, "x": worst.x, "y": worst.y,
            "at_reach": by_cause.get(WallCause.REACH, 0), "reach": settings.reach_m,
            "at_masks": by_cause.get(WallCause.MASKS, 0),
            "other": by_cause.get(WallCause.OTHER, 0)}))
    if outside.any():
        rows, cols = np.nonzero(outside)
        x, y = _places(grid, window, rows[:1], cols[:1])
        count = int(rows.size)
        found.append(Notice("des.entity_edge_outside", {
            "entity": name, "cells": count, "area": count * grid.cell_area, "x": float(x[0]),
            "y": float(y[0])}))
    found.extend(edge_notices(created, surface=name))
    return tuple(found)


def _edge_units(job: PlatformJob, footprint: Footprint, applied: Applied, settings: _EdgeSettings,
                budget_s: float) -> Generator[None, None, Edge]:
    """Las unidades de :func:`platform_edge_steps`: el alcance, las envolventes, la superficie con
    el borde, sus volúmenes y su pared, las celdas empinadas por bandas de filas, lo que llega al
    borde de la rejilla y el salto creado."""
    window, fp, grid = footprint.window, footprint.cells, job.grid
    shape = fp.shape
    z = job.start_in(window)
    base = applied.surface
    cut_ok = job.cut_in(window)
    fill_ok = job.fill_in(window)
    sub = _window_grid(grid, window)
    area = grid.cell_area
    name = job.request.name
    label = f"{name} (borde de la plataforma)"
    seeds = applied.at_level & fp
    in_reach = np.zeros(shape, dtype=bool)
    held = np.zeros(shape, dtype=bool)
    changed = np.zeros(shape, dtype=bool)
    final = z
    yield None
    if seeds.any():
        origin = np.where(seeds, 0.0, np.nan)
        distance = yield from _drain(reach_steps(origin, sub, settings.reach_m, settings.metric,
                                                 name=label, budget_s=budget_s))
        in_reach = np.isfinite(distance)
        del distance, origin
        seed_z = np.where(seeds, base, np.nan)
        slope = SlopeField(settings.tan)
        with np.errstate(invalid="ignore"):
            reachable = in_reach & ~fp & np.isfinite(z)
        up = yield from seed_envelope_steps(seed_z, sub, slope, settings.metric, Direction.UP,
                                            label)
        final = np.array(z, dtype=np.float64, copy=True)
        with np.errstate(invalid="ignore"):
            want_cut = reachable & (z > up)
        changed = want_cut & cut_ok
        held = want_cut & ~cut_ok
        final[changed] = up[changed]
        del up, want_cut
        yield None
        if applied.mode is PlatformMode.CUT_FILL:
            down = yield from seed_envelope_steps(seed_z, sub, slope, settings.metric,
                                                  Direction.DOWN, label)
            with np.errstate(invalid="ignore"):
                want_fill = reachable & (z < down)
            filled = want_fill & fill_ok
            held |= want_fill & ~fill_ok
            final[filled] = down[filled]
            changed = changed | filled
            del down, want_fill, filled
        del seed_z, reachable
        yield None
    surface = np.where(changed, final, base)
    moved = z[changed] - surface[changed]
    cut_m3 = float(np.sum(np.maximum(moved, 0.0))) * area
    fill_m3 = float(np.sum(np.maximum(-moved, 0.0))) * area
    wall_max, wall_x, wall_y = 0.0, None, None
    if moved.size:
        size = np.abs(moved)
        where_rows, where_cols = np.nonzero(changed)
        top = int(np.argmax(size))
        wall_max = float(size[top])
        found_x, found_y = _places(grid, window, where_rows[top:top + 1], where_cols[top:top + 1])
        wall_x, wall_y = float(found_x[0]), float(found_y[0])
    yield None
    limit = settings.angle_deg + settings.tolerance_deg
    picked_rows: list[np.ndarray] = []
    picked_cols: list[np.ndarray] = []
    picked_deg: list[np.ndarray] = []
    per_unit = max(1, REPORT_CELLS_PER_UNIT // max(shape[1], 1))
    for first in range(0, shape[0], per_unit):
        last = min(shape[0], first + per_unit)
        band = changed[first:last]
        if band.any():
            low, high = max(first - 1, 0), min(last + 1, shape[0])
            start = 1 + first - low
            rows_of = slice(start, start + (last - first))
            tangents = _max_tangents(_padded(surface, low, high), grid.dx, grid.dy)[
                rows_of, 1:shape[1] + 1]
            own = _max_tangents(_padded(z, low, high), grid.dx, grid.dy)[rows_of, 1:shape[1] + 1]
            with np.errstate(invalid="ignore"):
                degrees = np.degrees(np.arctan(tangents))
                over = band & (degrees > limit) & (tangents > own)
            found_rows, found_cols = np.nonzero(over)
            if found_rows.size:
                picked_rows.append(found_rows + first)
                picked_cols.append(found_cols)
                picked_deg.append(degrees[over])
        yield None
    steep = np.zeros(shape, dtype=bool)
    walls: tuple[EdgeWall, ...] = ()
    if picked_rows:
        rows_f, cols_f = np.concatenate(picked_rows), np.concatenate(picked_cols)
        steep[rows_f, cols_f] = True
        far = ~in_reach & ~fp & np.isfinite(z)
        blocked = applied.cut_denied | applied.fill_denied | held
        walls = _walls(grid, window, rows_f, cols_f, np.concatenate(picked_deg), far, blocked, area)
    yield None
    border = np.zeros(shape, dtype=bool)
    if window[0].start == 0:
        border[0, :] = True
    if window[0].stop == grid.nrows:
        border[-1, :] = True
    if window[1].start == 0:
        border[:, 0] = True
    if window[1].stop == grid.ncols:
        border[:, -1] = True
    nodata = ~np.isfinite(z) & ~fp
    near_nodata = dilate_square(nodata, 1) if nodata.any() else np.zeros(shape, dtype=bool)
    outside = changed & (border | near_nodata)
    domain = transition_domain(surface, z, settings.thickness_m, cut_ok | fill_ok)
    created: EdgeReport = yield from _drain(created_steps(
        surface, z, domain, sub, settings.thickness_m, settings.threshold_m, settings.share_pct,
        budget_s=budget_s))
    notices = _edge_notices(name, settings, walls, outside, created, grid, window)
    return Edge(window, surface, in_reach, changed, held, steep, outside, settings.metric,
                settings.angle_deg, settings.mesh_factor, settings.reach_m, settings.tolerance_deg,
                int(np.count_nonzero(moved > 0.0)), int(np.count_nonzero(moved < 0.0)), cut_m3,
                fill_m3, wall_max, wall_x, wall_y, walls, created, area, notices)


def platform_edge_steps(job: PlatformJob, footprint: Footprint, applied: Applied,
                        project: Mapping[str, object], *, budget_s: float = STEP_BUDGET_S
                        ) -> Iterator[Progress]:
    """**A3** (RF-015-22, RF-015-13; plan 015 §5.4): el borde de la plataforma de ``job`` con su
    ``footprint`` (:func:`platform_footprint`) y ``applied`` (:func:`apply_platform`), por pasos de
    ``budget_s`` como mucho: el último ``Progress`` (fase ``platform_edge``) lleva el :class:`Edge`.

    Las semillas son las celdas de la huella que quedaron en la rasante (``applied.at_level``). Con
    ``t = tan(ángulo de borde) · factor de malla`` y la métrica de la entidad (exacta por defecto,
    D-22, o *chamfer* 5×5), ``ENV↑`` y, en «en corte y relleno», ``ENV↓`` de esas semillas con
    ``seed_envelope_steps``, y el alcance (``reach_m``, m, obligatorio: D-20) como la distancia a la
    semilla más próxima con la misma métrica y ``t = 1`` (``reach_steps``): **fuera de la huella** y
    solo donde el alcance llega, ``z' = mín(z, ENV↑)`` donde ``cut_allowed`` y, en «en corte y
    relleno», ``z' = máx(z, ENV↓)`` donde ``fill_allowed`` (si las dos se cruzan —semillas más
    empinadas que el ángulo de borde: la rasante es una rampa— gana la descendente). Las celdas con
    ``NaN`` en la partida siguen sin dato; las que las máscaras no dejan mover quedan como estaban
    (``Edge.held``); lo que pasa del alcance, ni un bit.

    Da el volumen del borde (corte y relleno por separado), la altura máxima de su pared (``máx(|z −
    z'|)`` en las celdas que mueve), las celdas movidas más empinadas que el ángulo de borde más la
    tolerancia de cara —y que la inclinación que el terreno ya tenía en ellas— por causa
    (:class:`WallCause`), lo que llega al borde de la rejilla o a celdas
    sin dato, el salto creado de la 014 de la superficie entera (A11) y sus avisos (:class:`Edge`).
    Sin ninguna semilla (la huella no baja ninguna celda a la rasante) no hay borde: la superficie es
    la de ``applied``.

    ``project`` son los parámetros del proyecto que lee el borde, por su clave
    (``provenance.PLATFORM_COMMON_PARAMS``): la tolerancia de cara (``des.tolerance.face_deg``), el
    espesor mínimo (``res.verify.min_thickness_m``) y el salto admitido y su porcentaje
    (``des.edge.max_created_step_m``, ``des.edge.min_share``): ninguno lleva valor por defecto en
    este módulo (``ValueError`` si falta alguno).

    Rechazos al llamar, nombrando la plataforma, el campo y el valor (RF-015-08): sin ``reach_m`` o
    sin ``edge_angle_deg``, ``des.entity_param_missing``; fuera de su rango, ``des.entity_param_range``
    (el alcance, de (0; 10.000] m, y el ángulo, de (0; 90)°); una métrica que no es de la lista,
    ``des.entity_param_choice``. ``ValueError`` (errores del programa) si ``footprint`` y ``applied``
    no casan con ``job``, si la ventana no cubre lo que el alcance puede tocar con la métrica (A0) o,
    al avanzar, si las celdas no son cuadradas (ADR-0014). Ninguna entrada se modifica y no se
    escribe nada; cerrar el generador a mitad no deja nada."""
    settings = _edge_settings(job, project)
    _check_edge_inputs(job, footprint, applied, settings)
    work = _edge_units(job, footprint, applied, settings, budget_s)
    return pace_progress(work, budget_s, phase=_EDGE_PHASE,
                         running="Calculando el borde de la plataforma…",
                         finished="Borde de la plataforma calculado")


def platform_edge(job: PlatformJob, footprint: Footprint, applied: Applied,
                  project: Mapping[str, object]) -> Edge:
    """**A3**: :func:`platform_edge_steps` hasta el final, sin pasos: el :class:`Edge` de la
    plataforma de ``job``. Los mismos rechazos."""
    settings = _edge_settings(job, project)
    _check_edge_inputs(job, footprint, applied, settings)
    work = _edge_units(job, footprint, applied, settings, STEP_BUDGET_S)
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


def magnitude_notices(cut_m3: float, fill_m3: float, previous: Previous | None,
                      warning_ratio: float, operation: str = "") -> tuple[Notice, ...]:
    """El aviso de magnitud de RF-013-30 para el desmonte ``cut_m3`` y el terraplén ``fill_m3`` (m³,
    los de la entidad: huella y borde juntos) frente a la operación del mismo tipo y nombre de la
    revisión congelada más reciente de la versión (``previous``, D-25 de la 013): si el desmonte (o
    el terraplén) pasa en más de ``warning_ratio`` veces (el parámetro ``des.warning.magnitude_ratio``,
    mayor que 1) a los de esa revisión, ``des.magnitude_cut`` (o ``des.magnitude_fill``) con las
    cifras redondeadas, las veces y el umbral; con exactamente el umbral, o con 0 m³ antes, no. Sin
    revisión anterior (``None``), la nota ``des.magnitude_no_reference``, que dice el nombre de la
    ``operation``. La misma regla que el informe de la 013 (RF-013-30, ``design.report``), con el
    umbral que lee quien llama. ``ValueError`` si el umbral no es un número finito mayor que 1."""
    ratio = float(warning_ratio)
    if not math.isfinite(ratio) or ratio <= 1.0:
        raise ValueError(f"el umbral de aviso debe ser un número finito mayor que 1, no "
                         f"{warning_ratio!r}")
    if previous is None:
        return (Notice("des.magnitude_no_reference", {"operation": operation or "—"}),)
    found = []
    for code, current, before in (("des.magnitude_cut", cut_m3, previous.cut_m3),
                                  ("des.magnitude_fill", fill_m3, previous.fill_m3)):
        if before > 0.0 and current > ratio * before:
            found.append(Notice(code, {
                "current": round(current), "previous": round(before), "ratio": current / before,
                "threshold": ratio, "operation": previous.operation or operation or "—",
                "revision": previous.revision}))
    return tuple(found)


# --- A4: la contrapendiente --------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class LongProfile:
    """El perfil longitudinal de una plataforma en la superficie resultante (A4; RF-015-23, D-8,
    D-16): por cada tramo con celdas de la huella, de una celda de abscisa (``⌊σ/h⌋``, con ``h`` el
    paso de la rejilla ``step_m``), en el orden de la abscisa creciente, su número (``section``), su
    abscisa (``chainage_m``: el centro del tramo, ``(k + 0,5) · h``, sin pasar de la longitud del
    eje), su cota (``level_m``: **la más alta de su sección**), el lugar de esa celda (``x``, ``y``:
    absolutos en float64; a igual cota, la primera de norte a sur y de oeste a este) y su
    contrapendiente (``rise_m``, m, nunca negativa).

    La contrapendiente de un tramo es lo que su cota sube sobre el **mínimo de los tramos aguas arriba**
    (los anteriores en el sentido en que baja la rasante: hacia las abscisas grandes si la pendiente
    ``gradient_pct`` es negativa y hacia las pequeñas si es positiva; 0 en el primero). Con pendiente 0 %
    (:attr:`flat`, D-16) no hay sentido: es lo que sube sobre el mínimo de todo el perfil. Pasa si es
    mayor que ``tolerance_m`` (:attr:`flagged`)."""

    step_m: float
    gradient_pct: float
    tolerance_m: float
    section: np.ndarray
    chainage_m: np.ndarray
    level_m: np.ndarray
    x: np.ndarray
    y: np.ndarray
    rise_m: np.ndarray

    @property
    def flat(self) -> bool:
        """Si la rasante tiene pendiente 0 % (la contrapendiente es el máximo menos el mínimo)."""
        return self.gradient_pct == 0.0

    @property
    def flagged(self) -> np.ndarray:
        """Los tramos cuya contrapendiente pasa de la tolerancia (booleana, de la forma del perfil)."""
        return self.rise_m > self.tolerance_m

    @property
    def counter_sections(self) -> int:
        """Cuántos tramos pasan de la tolerancia."""
        return int(np.count_nonzero(self.flagged))

    @property
    def worst(self) -> int | None:
        """El índice (en los arrays del perfil) del tramo de mayor contrapendiente, si alguno pasa de
        la tolerancia (a igual cuantía, el de menor abscisa); si no, ``None``."""
        if not self.flagged.any():
            return None
        return int(np.argmax(self.rise_m))

    @property
    def spread_m(self) -> float:
        """El máximo menos el mínimo del perfil (m)."""
        return float(self.level_m.max() - self.level_m.min())


def _counter_tolerance(job: PlatformJob) -> float:
    """La tolerancia de contrapendiente de la plataforma de ``job`` (``des.entity_param_range`` si
    sale de rango); sin el valor, la de la familia de parámetros (0,1 m, D-8)."""
    found = job.values.get(PlatformParam.COUNTER_TOL.value)
    if found is None:
        found = PLATFORM_PARAMS[PlatformParam.COUNTER_TOL.value].default
    value = check_entity_param(job.request.name, job.code, PlatformParam.COUNTER_TOL, found,
                               layer=job.request.layer)
    assert isinstance(value, float)
    return value


def platform_profile(job: PlatformJob, footprint: Footprint, surface: np.ndarray,
                     tolerance_m: float | None = None) -> LongProfile:
    """**A4** (RF-015-23; plan 015 §5.4): el perfil longitudinal y la contrapendiente de la plataforma
    de ``job`` con su ``footprint`` en la ``surface`` resultante (m, de la forma de la ventana de la
    huella: la de :class:`Edge`, con la huella y el borde ya aplicados) y la tolerancia
    ``tolerance_m`` (por defecto, ``counter_tol_m`` del trabajo o 0,1 m, D-8). Véase
    :class:`LongProfile`. Sin bucle por celda: la cota más alta de cada sección y la primera celda
    con ella salen de ``np.maximum.at`` y ``np.minimum.at``, y el mínimo aguas arriba, de
    ``np.minimum.accumulate``. Ninguna entrada se modifica.

    ``ValueError`` (errores del programa) si la ventana no cabe en la rejilla, la superficie o la
    abscisa no son de la forma de la huella, hay celdas de la huella sin dato, las celdas no son
    cuadradas (ADR-0014: el tramo es una celda de abscisa) o la tolerancia no es un número finito
    mayor o igual que 0."""
    _check_footprint(job, footprint)
    grid = job.grid
    if grid.dx != grid.dy:
        raise ValueError(f"el perfil por tramos de una celda de abscisa supone celdas cuadradas "
                         f"(ADR-0014), no de {grid.dx} × {grid.dy} m")
    cells = footprint.cells
    heights = np.asarray(surface, dtype=np.float64)
    if heights.shape != cells.shape or footprint.sigma.shape != cells.shape:
        raise ValueError(f"la superficie resultante ({heights.shape}) y la abscisa "
                         f"({footprint.sigma.shape}) son de la forma de la ventana de la huella "
                         f"{cells.shape}")
    if tolerance_m is None:
        tolerance = _counter_tolerance(job)
    else:
        tolerance = float(tolerance_m)
        if not (math.isfinite(tolerance) and tolerance >= 0.0):
            raise ValueError(f"la tolerancia de contrapendiente es un número finito mayor o igual "
                             f"que 0, no {tolerance_m!r}")
    if not cells.any():
        raise ValueError("la huella no tiene ninguna celda")
    levels = heights[cells]
    sigma = footprint.sigma[cells]
    if not (np.isfinite(levels).all() and np.isfinite(sigma).all()):
        raise ValueError(f"la plataforma «{job.request.name}» ({job.code}) tiene celdas sin dato en "
                         "su huella o sin abscisa: no hay perfil que medir")
    step = grid.dx
    index = np.floor(sigma / step).astype(np.int64)
    size = int(index.max()) + 1
    present = np.flatnonzero(np.bincount(index, minlength=size))
    top = np.full(size, -np.inf)
    np.maximum.at(top, index, levels)
    order = np.arange(levels.size, dtype=np.int64)
    at_top = levels == top[index]
    first = np.full(size, levels.size, dtype=np.int64)
    np.minimum.at(first, index[at_top], order[at_top])
    level = top[present]
    rows, cols = np.nonzero(cells)
    pick = first[present]
    x, y = _places(grid, footprint.window, rows[pick], cols[pick])
    gradient = footprint.gradient_pct
    if gradient == 0.0:
        rise = level - level.min()
    else:
        walk = level if gradient < 0.0 else level[::-1]
        before = np.minimum.accumulate(walk)
        found = np.zeros(walk.size)
        found[1:] = np.maximum(walk[1:] - before[:-1], 0.0)
        rise = found if gradient < 0.0 else found[::-1]
    chainage = np.minimum((present + 0.5) * step, footprint.axis.length_m)
    return LongProfile(step, gradient, tolerance, present.astype(np.int64), chainage, level, x, y,
                       np.ascontiguousarray(rise))


def _counter_notice(name: str, profile: LongProfile) -> tuple[Notice, ...]:
    """El aviso de la contrapendiente del peor tramo (``des.platform_counter_slope``, o
    ``des.platform_counter_flat`` con pendiente 0 %): la cuantía y la cota al mm, la abscisa y el
    lugar de su celda más alta al cm, la tolerancia y la entidad; ninguno si no pasa de ella."""
    index = profile.worst
    if index is None:
        return ()
    values: dict[str, object] = {
        "entity": name, "amount": round(float(profile.rise_m[index]), 3),
        "tolerance": profile.tolerance_m, "chainage": round(float(profile.chainage_m[index]), 3),
        "x": round(float(profile.x[index]), 2), "y": round(float(profile.y[index]), 2)}
    if profile.flat:
        values["low"] = round(float(profile.level_m.min()), 3)
        values["high"] = round(float(profile.level_m[index]), 3)
        return (Notice("des.platform_counter_flat", values),)
    return (Notice("des.platform_counter_slope", values),)


# --- RF-015-14: el orden de las dos superficies de una cantera ---------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class QuarryOrder:
    """La otra superficie de una cantera de la 014 cuando la plataforma parte de una de las dos
    (RF-015-14): el nombre de la cantera (``quarry``), el lado que cambia la plataforma (``side``, la
    superficie de partida: ``final`` o ``exploitation``) con el nombre de su dato (``surface``) y la
    **otra** (``other``, m, float64, de la forma de la rejilla entera) con el suyo (``other_name``).
    ``ValueError`` (error del programa) si el lado no es de la cantera o ``other`` no es una rejilla."""

    quarry: str
    side: Surface | str
    surface: str
    other_name: str
    other: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Surface(self.side))
        other = np.asarray(self.other, dtype=np.float64)
        if other.ndim != 2:
            raise ValueError(f"la otra superficie de la cantera es una rejilla, no de forma "
                             f"{other.shape}")
        object.__setattr__(self, "other", other)


@dataclass(frozen=True, slots=True)
class OrderBreach:
    """Lo que no cumple ``final ≤ explotación ≤ terreno`` frente a la otra superficie (RF-015-14): el
    ``side`` que cambió la plataforma, las ``cells`` que lo incumplen (más que la tolerancia), su
    ``area_m2``, el mayor exceso ``max_m`` (m) y el lugar de la primera celda de norte a sur y de oeste
    a este (``x``, ``y``: absolutos en float64)."""

    side: Surface
    cells: int
    area_m2: float
    max_m: float
    x: float
    y: float


def order_check(result: np.ndarray, other: np.ndarray, side: Surface | str, grid: Grid,
                window: tuple[slice, slice] | None = None,
                tolerance_m: float = ORDER_TOLERANCE_M) -> OrderBreach | None:
    """**RF-015-14**: lo que la ``result`` de una entidad aplicada al lado ``side`` de una cantera de
    la 014 no cumple de ``final ≤ explotación ≤ terreno`` frente a la ``other`` superficie
    (``other``, de la rejilla ``grid`` entera): con ``side`` ``final`` (la entidad cambia la final)
    ``result ≤ other + tolerancia`` y con ``exploitation``, ``other ≤ result + tolerancia``, con la
    tolerancia ``tolerance_m`` (por defecto 1 mm: RF-014-14). ``result`` es de la ventana ``window``
    de ``grid`` (por defecto, la rejilla entera). Una celda sin dato en una de las dos no se compara.
    ``None`` si se cumple; si no, el :class:`OrderBreach` con el área y el lugar. Solo lee;
    ``ValueError`` (errores del programa) si el lado no es de la cantera o las rejillas no son de la
    forma de ``grid`` o de ``window``."""
    side = Surface(side)
    full = (slice(0, grid.nrows), slice(0, grid.ncols)) if window is None else window
    shape = (full[0].stop - full[0].start, full[1].stop - full[1].start)
    other_full = np.asarray(other, dtype=np.float64)
    if other_full.shape != grid.shape:
        raise ValueError(f"la otra superficie es de la forma de la rejilla {grid.shape}, no "
                         f"{other_full.shape}")
    found = np.asarray(result, dtype=np.float64)
    if found.shape != shape:
        raise ValueError(f"el resultado es de la forma de su ventana {shape}, no {found.shape}")
    against = other_full[full]
    with np.errstate(invalid="ignore"):
        excess = found - against if side is Surface.FINAL else against - found
        broken = excess > tolerance_m
    if not broken.any():
        return None
    rows, cols = np.nonzero(broken)
    x, y = _places(grid, full, rows[:1], cols[:1])
    count = int(rows.size)
    return OrderBreach(side, count, count * grid.cell_area, float(excess[broken].max()),
                       float(x[0]), float(y[0]))


# --- Lo que las máscaras no dejan mover --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeldGroup:
    """Un grupo 4-conexo de celdas que las máscaras no dejan mover (RF-015-13), de la huella
    (``cut_denied`` y ``fill_denied`` de :class:`Applied`) y del borde (:attr:`Edge.held`) juntas: su
    número ``group`` (desde 1, en el orden de su primera celda de norte a sur), sus ``cells`` y de
    ellas las de la huella (``footprint_cells``) y las del borde (``edge_cells``), su ``area_m2`` y
    su centro ``x``, ``y`` (absolutos en float64: la media de los centros de sus celdas). La
    restricción de **otra entidad** que lo causa la nombra quien lee las restricciones (T12)."""

    group: int
    cells: int
    footprint_cells: int
    edge_cells: int
    area_m2: float
    x: float
    y: float


def _run[T](work: Generator[None, None, T]) -> T:
    """El resultado de las unidades ``work`` ejecutadas hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]


def _held_groups(held: np.ndarray, inside: np.ndarray, grid: Grid, window: tuple[slice, slice]
                 ) -> tuple[HeldGroup, ...]:
    """Los grupos 4-conexos de ``held`` (de la ventana ``window``), con cuántas de sus celdas son de
    la huella (``inside``), su área y su centro absoluto; etiquetados solo sobre su caja."""
    rows, cols = np.nonzero(held)
    if not rows.size:
        return ()
    top, left = int(rows.min()), int(cols.min())
    mask = np.zeros((int(rows.max()) - top + 1, int(cols.max()) - left + 1), dtype=bool)
    mask[rows - top, cols - left] = True
    labels = _run(_label_units(mask))
    tags = labels.grid[rows - top, cols - left]
    count = labels.count + 1
    row_sum = np.bincount(tags, weights=rows + window[0].start, minlength=count)
    col_sum = np.bincount(tags, weights=cols + window[1].start, minlength=count)
    in_footprint = np.bincount(tags, weights=inside[rows, cols].astype(np.float64), minlength=count)
    found = []
    for index in range(1, count):
        cells = int(labels.sizes[index - 1])
        mine = int(round(in_footprint[index]))
        found.append(HeldGroup(
            index, cells, mine, cells - mine, cells * grid.cell_area,
            float(grid.west + (col_sum[index] / cells + 0.5) * grid.dx),
            float(grid.north - (row_sum[index] / cells + 0.5) * grid.dy)))
    return tuple(found)


# --- A5: el resultado, las cifras y los avisos -------------------------------------------------


def _off_level_notices(name: str, footprint_area_m2: float, applied: Applied) -> tuple[Notice, ...]:
    """Lo que no queda en la rasante, como avisos (RF-015-24, RF-015-13), en este orden: «la plataforma
    no corta» con el área de su huella si ninguna celda baja; lo que queda **por encima** (el corte que
    las máscaras no admiten) y lo que queda **por debajo** (el modo «en corte» no rellena o las máscaras
    no dejan rellenar), cada uno con su resumen (el área, la diferencia máxima y los grupos) y una nota por
    grupo con su área, su diferencia máxima y su lugar (al cm)."""
    found: list[Notice] = []
    if applied.cut_cells == 0:
        found.append(Notice("des.platform_no_cut", {"entity": name, "area": footprint_area_m2}))
    over = ("des.platform_above", "des.platform_above_group")
    under = (("des.platform_below_masks" if applied.below
              and applied.below[0].cause is OffLevelCause.FILL_DENIED else "des.platform_below"),
             "des.platform_below_group")
    for groups, (summary, note) in ((applied.above, over), (applied.below, under)):
        if not groups:
            continue
        found.append(Notice(summary, {
            "entity": name, "area": math.fsum(item.area_m2 for item in groups),
            "maximum": round(max(item.max_m for item in groups), 3), "groups": len(groups)}))
        found.extend(Notice(note, {
            "group": item.group, "cells": item.cells, "area": item.area_m2,
            "maximum": round(item.max_m, 3), "x": round(item.x, 2), "y": round(item.y, 2)})
            for item in groups)
    return tuple(found)


@dataclass(frozen=True, slots=True, eq=False)
class PlatformOutcome:
    """El cálculo de una plataforma (A0 a A5; RF-015-23, RF-015-24, RF-015-14, RF-015-13): su
    ``footprint``, lo ``applied`` y el ``edge`` (la superficie resultante es :attr:`result`), el
    ``profile`` longitudinal con su contrapendiente, lo que las máscaras no dejan mover (``held``: la
    máscara de la ventana, y ``held_groups``), el incumplimiento del orden de la cantera (``order``,
    ``None`` si se cumple o la plataforma no parte de una cantera), las ``figures`` de RF-015-24
    (``provenance.platform_figures``: CALCULADO, con su unidad y su ámbito) y los ``notices`` en orden
    estable: los de la huella (el eje principal), la contrapendiente, lo que no corta o no queda en la
    rasante, los del borde (:attr:`Edge.notices`: su pared, lo que llega al borde de la rejilla y el
    salto creado), el orden de la cantera y la magnitud.

    ``confirmed`` es la confirmación expresa de la contrapendiente (``confirm_counterslope`` de
    :func:`platform_outcome`): sin ella, una contrapendiente que pasa de la tolerancia impide crear
    (:attr:`needs_confirmation`, :meth:`ensure_creatable`). El incumplimiento del orden de la cantera
    **no** lo impide (RF-015-14)."""

    name: str
    code: str
    footprint: Footprint
    applied: Applied
    edge: Edge
    profile: LongProfile
    held: np.ndarray
    held_groups: tuple[HeldGroup, ...]
    order: OrderBreach | None
    figures: tuple[FigureSpec, ...]
    notices: tuple[Notice, ...]
    confirmed: bool = False

    @property
    def result(self) -> np.ndarray:
        """La superficie resultante en la ventana de trabajo (m, float64): la de partida con la
        huella aplicada y el borde."""
        return self.edge.surface

    @property
    def message(self) -> str:
        """El mensaje de la operación (spec 015, T12): lo que dice el resumen de lo calculado, en
        español: la plataforma, su código, su área y el desmonte y el terraplén de la huella y el
        borde juntos. Es lo que recibe ``DesignWriter.commit`` al crearla."""
        return (f"Plataforma «{self.name}» ({self.code}) calculada: "
                f"{format_value(round(self.area_m2, 2))} m², desmonte "
                f"{format_value(round(self.total_cut_m3, 2))} m³ y terraplén "
                f"{format_value(round(self.total_fill_m3, 2))} m³ (huella y borde)")

    @property
    def area_m2(self) -> float:
        """El área de la huella (m²)."""
        return self.footprint.area_m2

    @property
    def total_cut_m3(self) -> float:
        """El corte de la huella y del borde juntos (m³): el de la magnitud de RF-013-30."""
        return self.applied.cut_m3 + self.edge.cut_m3

    @property
    def total_fill_m3(self) -> float:
        """El relleno de la huella y del borde juntos (m³)."""
        return self.applied.fill_m3 + self.edge.fill_m3

    @property
    def no_cut(self) -> bool:
        """Si ninguna celda de la huella baja (RF-015-24: «la plataforma no corta»)."""
        return self.applied.cut_cells == 0

    @property
    def off_level_area_m2(self) -> float:
        """El área de las celdas de la huella que no quedan en la rasante, por encima y por debajo
        (m²)."""
        return math.fsum(item.area_m2 for item in (*self.applied.above, *self.applied.below))

    @property
    def off_level_max_m(self) -> float:
        """La mayor diferencia de esas celdas con la rasante (m); 0 si no hay ninguna."""
        return max((item.max_m for item in (*self.applied.above, *self.applied.below)),
                   default=0.0)

    @property
    def held_cells(self) -> int:
        """Las celdas de la huella y del borde que las máscaras no dejan mover."""
        return int(np.count_nonzero(self.held))

    @property
    def held_area_m2(self) -> float:
        """Su área (m²)."""
        return self.held_cells * self.applied.cell_area_m2

    @property
    def counter_slope(self) -> bool:
        """Si el perfil tiene una contrapendiente que pasa de la tolerancia."""
        return self.profile.worst is not None

    @property
    def needs_confirmation(self) -> bool:
        """Si hay una contrapendiente y el usuario no la ha confirmado: no se puede crear
        (RF-015-23)."""
        return self.counter_slope and not self.confirmed

    def confirm(self) -> PlatformOutcome:
        """El mismo resultado con la contrapendiente confirmada expresamente por el usuario."""
        return replace(self, confirmed=True)

    def ensure_creatable(self) -> None:
        """Rechaza crear la plataforma si tiene una contrapendiente sin confirmar: ``DesignError``
        ``des.platform_counter_unconfirmed`` con la entidad, la cuantía del peor tramo y la
        tolerancia (RF-015-23). No hace nada si no la hay o está confirmada; el orden de la cantera no
        lo impide."""
        index = self.profile.worst
        if index is None or self.confirmed:
            return
        raise DesignError(
            "des.platform_counter_unconfirmed", obj=f"Plataforma «{self.name}»",
            field=entity_key(self.code, PlatformParam.COUNTER_TOL), value=self.profile.tolerance_m,
            entity=self.name, amount=round(float(self.profile.rise_m[index]), 3),
            tolerance=self.profile.tolerance_m)


SUMMARY_GROUPS = 10
"""Los grupos de celdas fuera de la rasante (por encima o por debajo) que enseña el resumen de un
cálculo, y los tramos de cada aviso del salto creado; el resto, una nota con cuántos faltan (la lista
entera queda en el resultado y en el informe). No es una cifra minera: es lo que cabe en la
ventana."""
_GROUP_NOTES = {"des.platform_above": "des.platform_above_group",
                "des.platform_below": "des.platform_below_group",
                "des.platform_below_masks": "des.platform_below_group"}


def summary_notices(notices: Iterable[Notice], *, limit: int = SUMMARY_GROUPS
                    ) -> tuple[Notice, ...]:
    """Los avisos y notas ``notices`` de un :class:`PlatformOutcome` como los enseña el resumen de
    «Calcular» (spec 015, T12; RF-015-03, RF-015-24; la regla de ``edges.summary_notices``): de cada
    aviso del salto creado, sus ``limit`` primeros tramos (``des.edge_more_stretches`` con los que
    faltan) y, de lo que queda por encima o por debajo de la rasante, sus ``limit`` primeros grupos y
    una nota ``des.platform_more_groups`` con los que faltan. Lo demás, tal cual y en su orden;
    ``ValueError`` si ``limit`` es negativo."""
    found: list[Notice] = []
    note: str | None = None  # el código de las notas de grupo del último aviso de grupos
    shown = hidden = 0
    for notice in _stretch_notices(notices, limit=limit):
        if note is not None and notice.code == note:
            if shown < limit:
                found.append(notice)
                shown += 1
            else:
                hidden += 1
            continue
        if hidden:
            found.append(Notice("des.platform_more_groups", {"groups": hidden}))
        note, shown, hidden = _GROUP_NOTES.get(notice.code), 0, 0
        found.append(notice)
    if hidden:
        found.append(Notice("des.platform_more_groups", {"groups": hidden}))
    return tuple(found)


def _figures(name: str, code: str, footprint: Footprint, applied: Applied, edge: Edge
             ) -> tuple[FigureSpec, ...]:
    """Las cifras de RF-015-24 (las doce de ``provenance.PLATFORM_FIGURES``, CALCULADO): lo que no
    existe (sin celdas fuera de la rasante no hay diferencia máxima; sin borde no hay pared) se da como
    ``None``, que no se registra."""
    off = (*applied.above, *applied.below)
    return platform_figures(name, code, {
        "des.plat_area_m2": footprint.area_m2,
        "des.plat_axis_m": footprint.axis.length_m,
        "des.plat_footprint_m": footprint.length_m,
        "des.plat_start_level_m": footprint.start_level_m,
        "des.plat_end_level_m": footprint.end_level_m,
        "des.plat_cut_m3": applied.cut_m3,
        "des.plat_fill_m3": applied.fill_m3,
        "des.edge_cut_m3": edge.cut_m3,
        "des.edge_fill_m3": edge.fill_m3,
        "des.edge_wall_max_m": None if edge.wall_x is None else edge.wall_max_m,
        "des.plat_below_m2": math.fsum(item.area_m2 for item in off),
        "des.plat_below_max_m": max((item.max_m for item in off), default=None)})


def platform_outcome(job: PlatformJob, footprint: Footprint, applied: Applied, edge: Edge,
                     project: Mapping[str, object], *, confirm_counterslope: bool = False,
                     previous: Previous | None = None, operation: str = "",
                     quarry: QuarryOrder | None = None) -> PlatformOutcome:
    """**A4 y A5** (RF-015-23, RF-015-24, RF-015-14, RF-015-13; plan 015 §5.4): junta la ``footprint``
    de ``job``, lo ``applied`` y el ``edge`` en el :class:`PlatformOutcome`: el perfil longitudinal de
    la superficie resultante (:func:`platform_profile`, con la tolerancia ``counter_tol_m`` de la
    entidad o 0,1 m), las cifras, lo que las máscaras no dejan mover con su lugar y la lista de avisos
    en orden estable (:class:`PlatformOutcome`).

    ``confirm_counterslope`` es la confirmación expresa del usuario de una contrapendiente (RF-015-23;
    sin ella no se puede crear). ``previous`` y ``operation`` son los de la magnitud
    (:func:`magnitude_notices`: la operación del mismo nombre de la revisión congelada anterior y el
    nombre de la operación; sin ``previous``, la nota de que no hay con qué comparar) con el desmonte
    y el relleno de la huella y del borde juntos y el umbral ``des.warning.magnitude_ratio`` de
    ``project``, el mismo mapa de parámetros del proyecto que lee :func:`platform_edge` (``ValueError``
    si no lo tiene o no es un número finito mayor que 1). ``quarry`` es la otra
    superficie de la cantera de la 014 si la plataforma parte de una de las dos (RF-015-14): el
    incumplimiento de ``final ≤ explotación ≤ terreno`` con 1 mm avisa, sin impedir crearla.

    Solo lee; ``ValueError`` (errores del programa) si ``applied`` o ``edge`` no son de la ventana de
    ``footprint`` o de su forma, o ``quarry.other`` no es de la forma de la rejilla."""
    _check_footprint(job, footprint)
    if applied.window != footprint.window or edge.window != footprint.window:
        raise ValueError("la plataforma aplicada y el borde son de la misma ventana que la huella")
    shape = footprint.cells.shape
    for owner, names in ((applied, ("surface", "at_level", "cut_denied", "fill_denied")),
                         (edge, ("surface", "held"))):
        for attribute in names:
            found = getattr(owner, attribute).shape
            if found != shape:
                raise ValueError(f"«{attribute}» es de la forma {found}, no de la de la ventana "
                                 f"{shape}")
    ratio = _project_number(project, WARNING_RATIO)
    name = job.request.name
    profile = platform_profile(job, footprint, edge.surface)
    held = applied.cut_denied | applied.fill_denied | edge.held
    groups = _held_groups(held, footprint.cells, job.grid, footprint.window)
    breach: OrderBreach | None = None
    if quarry is not None:
        breach = order_check(edge.surface, quarry.other, quarry.side, job.grid, footprint.window)
    notices = [*footprint.notices, *_counter_notice(name, profile),
               *_off_level_notices(name, footprint.area_m2, applied), *edge.notices]
    if breach is not None and quarry is not None:
        notices.append(Notice("des.entity_quarry_order", {
            "entity": name, "surface": quarry.surface, "quarry": quarry.quarry,
            "other": quarry.other_name, "cells": breach.cells, "area": breach.area_m2,
            "above": round(breach.max_m, 3), "x": round(breach.x, 2), "y": round(breach.y, 2)}))
    notices.extend(magnitude_notices(applied.cut_m3 + edge.cut_m3, applied.fill_m3 + edge.fill_m3,
                                     previous, ratio, operation))
    return PlatformOutcome(name, job.code, footprint, applied, edge, profile, held, groups, breach,
                           _figures(name, job.code, footprint, applied, edge), tuple(notices),
                           bool(confirm_counterslope))
