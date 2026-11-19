# SPDX-License-Identifier: GPL-3.0-or-later
"""La regla del espesor y el cuerpo apoyado (spec 016, T23; HU-016-4; RF-016-01, RF-016-20, RF-016-21, RF-016-22;
RNF-016-02, RNF-016-03; plan 016 §5.4 A0 y A11, §5.7 P-7; D-8, D-9; errores 26 y B9). Dominio puro: sin proyecto y sin ``bpy``.

Lo que entrega:

- :func:`derive` (RF-016-01): **la regla del espesor, una sola función** para toda entidad apoyada. Del apoyo (o el techo) y el
  **espesor** da la base y el techo, y comprueba en **todas** las celdas que el espesor no es negativo y que la base no queda por
  encima del techo. «Sobre una base»: base = apoyo, techo = apoyo + espesor. «Bajo un techo» (el escombro existente de los errores
  26 y B9): techo = la superficie conocida, base = techo − espesor. **Nunca recibe ni devuelve la cota de una base como dato que
  interpolar**: lo que se interpola es el espesor, que es ≥ 0 por construcción, y la base y el techo salen de él (interpolar la
  cota de la base dio espesores negativos en una ladera con vaguada).
- :class:`BodyJob` (el homólogo de ``removal.RemovalJob``): todo lo que el cálculo necesita **ya leído** y nada del proyecto —la
  petición, el código (``BDY-001``), la rejilla, el CRS y la referencia vertical (solo los lleva el ráster intermedio del TIN),
  la superficie conocida, la huella, los datos de espesor (:class:`ThicknessData`: puntos y polígonos), los valores resueltos
  (``max_distance_m``, sin valor por defecto: D-9, y ``zero_at_edge``) y, «sobre una base», la partida y el relleno admitido—
  para probar el cálculo sin proyecto y reproducirlo (``reproduce.py``).
- :func:`body_steps` y :func:`compute_body` (A11): el :class:`BodyOutcome` con el espesor, la base, el techo, la superficie que
  deja el cuerpo «sobre una base», lo lejano y las cifras de RF-016-20 a RF-016-22.
- :func:`body_window` (A0): la ventana de trabajo de una huella (su caja y una celda más), que es lo que basta leer del apoyo y
  la partida; el resultado es el mismo, bit a bit, que con la rejilla entera.

**A11, paso a paso** (``body_steps``):

1. **Los datos, a su celda.** Cada punto va al centro de **su** celda (la que lo contiene; el borde oeste y el norte de una celda
   son de ella); cada polígono da un dato, con su valor, en cada celda cuyo centro contiene (par-impar; decisión de la sesión
   principal, 18/11/2026); en una celda con varios datos, **su media** (los de puntos y polígonos juntos). Los datos fuera de la
   huella —también fuera de la rejilla, y los polígonos sin ninguna celda dentro— se **ignoran con aviso**
   (``des.body_data_outside``, ``des.bdy_ignored``). Con ``zero_at_edge``, cada celda del borde de la huella (con una vecina de
   fuera por uno de sus cuatro lados; los huecos de la huella cuentan; el borde del array, no) **suma un dato de valor 0**: si ya
   tenía datos, el 0 entra en su media (la regla de «varios en una celda»). Sin ningún dato real en la huella se rechaza
   (RF-016-22: ``des.body_no_data``, nombrando la huella y la capa de los datos); los ceros del borde no son datos.
2. **TIN lineal.** Las celdas con dato son los vértices de un TIN de Delaunay (``gis.cdt.PureTriangulator``) que se rasteriza
   con ``gis.tin.tin_to_raster`` (coordenadas baricéntricas: **reproduce el dato en su celda a 0,0 m**, queda entre el menor y el
   mayor y no es negativo donde los datos no lo son). Se descartan los triángulos con un lado en planta **mayor que
   ``2·max_distance_m``** (que no se interpolan a través de un vacío) y, sin ningún triángulo (menos de tres datos o todos
   alineados), no hay TIN. El TIN se construye en **unidades de celda** —vértices en ``(columna + ½, −(fila + ½))``, la rejilla
   ``(0, 0, 1, 1)`` de la ventana—: las coordenadas son enteros y medios exactos, el resultado no depende del origen absoluto ni de
   la ventana, y la triangulación es exacta.
3. **El dato más próximo** (``design.grids``, la transformada de distancia exacta: la celda con dato más próxima y su distancia;
   a igual distancia, el menor valor) da el espesor donde el TIN no llega (fuera de su envolvente convexa o en un triángulo
   descartado) y **la distancia de cada celda a los datos**.
4. **Lo lejano** (RF-016-21): las celdas del cuerpo a **más de** ``max_distance_m`` de su dato más próximo. Se avisan con su área
   (m²), su volumen (m³) y su lugar —el centro de la más lejana— (``des.body_far``) **sin impedir calcular** (B9). Si **ninguna**
   celda del cuerpo queda a ``max_distance_m`` o menos de un dato se rechaza (RF-016-22: ``des.body_all_far``).
5. **El cuerpo y su regla.** El cuerpo existe donde la huella tiene la superficie conocida (con dato); ahí, ``derive`` da la base
   y el techo y comprueba la regla de RF-016-01. «Sobre una base», la superficie de la cadena es ``compose(partida, techo, huella
   ∩ relleno admitido, FILL)``: ``máx(partida, techo)`` donde se admite relleno y la partida, **bit a bit**, en las demás.
   «Bajo un techo» no cambia la superficie (``surface`` es ``None``).

**Cómo está partido para los pasos** (RNF-016-03, T24): cada ``yield`` de las unidades es una unidad de trabajo y
:func:`~.seeds.pace_progress` las agrupa en pasos de ``budget_s``. Los datos a celdas ceden cada punto-bloque y cada polígono; el
más próximo, por bandas; la triangulación y la rasterización del TIN son **hoy una unidad cada una** (:func:`_triangulate_units` y
:func:`_rasterize_units`: sus contratos —puntos en unidades de celda → triángulos; TIN y ventana → espesor o NaN— no cambian
cuando la T24 las parta en pasos de 256 puntos y bandas de filas).

**Lo que no hace** (la T25): leer la capa de datos (puntos, líneas con su Z o su M, polígonos), preparar, crear, recalcular y
reproducir la operación, rechazar un espesor negativo de la capa con capa, entidad, campo y valor, y avisar de más de 100 ha con
secciones.

Las coordenadas absolutas se pasan a celdas **con la esquina de la rejilla restada antes de dividir** (principio 6, ADR-0005) y
ninguna entrada se modifica.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.cdt import PureTriangulator
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.tin import Tin, tin_to_raster
from .compose import compose
from .envelopes import CELLS_PER_UNIT
from .grids import _nearest_units
from .messages import DesignError
from .model import BenchSense, BodyRequest, BodySense
from .params import BodyParam, check_entity_param, entity_params, entity_params_of
from .platform import Window, _shaped_array, _whole, _window_of
from .preview import Notice
from .provenance import body_figures
from .seeds import pace_progress
from .zones import _paint, _polygon_spans

__all__ = [
    "BodyJob",
    "BodyOutcome",
    "BodySense",
    "ThicknessData",
    "all_far_error",
    "body_steps",
    "body_window",
    "compute_body",
    "derive",
    "edge_cells",
    "no_data_error",
]

_PHASE = "body"
_OUTSIDE = "des.body_data_outside"
_FAR = "des.body_far"
_NO_DATA = "des.body_no_data"
_ALL_FAR = "des.body_all_far"
_OBJ = "Cuerpo apoyado «{}»"


# --- La regla del espesor (RF-016-01) ------------------------------------------------------------------------------------


def derive(support: np.ndarray, thickness: np.ndarray, sense: BodySense | str) -> tuple[np.ndarray, np.ndarray]:
    """**RF-016-01**: ``(base, techo)`` de un cuerpo de ``thickness`` (m, ≥ 0; ``NaN``, sin dato) sobre la superficie conocida
    ``support`` (m, de su forma; ``NaN``, sin dato). «Sobre una base» (``sense`` = :attr:`BodySense.ON_BASE`) la superficie es
    el apoyo: **base = apoyo** y **techo = apoyo + espesor**; «bajo un techo» (:attr:`BodySense.UNDER_ROOF`) es el techo:
    **techo = la superficie** y **base = techo − espesor**. Donde falta el apoyo o el espesor, sin dato (``NaN``) en las dos.

    Comprueba en **todas** las celdas con dato que el espesor no es negativo y que la base no está por encima del techo
    (``ValueError`` con la primera celda, fila y columna, y su valor: es un error del programa, el espesor llega de un TIN
    convexo de datos ≥ 0 y la orden rechaza antes un dato negativo); un valor infinito, una forma que no casa o un sentido
    desconocido son también errores del programa. Nunca se interpola ni se guarda la cota de la base: es lo que se deriva del
    espesor. Dos arrays nuevos; ninguna entrada se modifica."""
    way = BodySense(sense)
    floor = np.asarray(support, dtype=np.float64)
    depth = np.asarray(thickness, dtype=np.float64)
    if floor.shape != depth.shape:
        raise ValueError(f"el apoyo {floor.shape} y el espesor {depth.shape} deben ser de la misma forma")
    if np.isinf(floor).any() or np.isinf(depth).any():
        raise ValueError("el apoyo y el espesor no pueden ser infinitos (sin dato es NaN)")
    with np.errstate(invalid="ignore"):
        negative = depth < 0.0
    if negative.any():
        cell = tuple(int(index) for index in np.argwhere(negative)[0])
        raise ValueError(f"el espesor de la celda {cell} es {float(depth[cell])!r}: un espesor no es negativo (RF-016-01)")
    valid = np.isfinite(floor) & np.isfinite(depth)
    if way is BodySense.ON_BASE:
        base = np.where(valid, floor, np.nan)
        top = np.where(valid, floor + depth, np.nan)
    else:
        top = np.where(valid, floor, np.nan)
        base = np.where(valid, floor - depth, np.nan)
    with np.errstate(invalid="ignore"):
        above = valid & ~(base <= top)
    if above.any():
        cell = tuple(int(index) for index in np.argwhere(above)[0])
        raise ValueError(f"la base de la celda {cell} queda por encima del techo (RF-016-01): {float(base[cell])!r} > "
                         f"{float(top[cell])!r}")
    return base, top


# --- Los datos y el trabajo -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class ThicknessData:
    """Los datos de espesor de un cuerpo, ya leídos de su capa (RF-016-20): ``points`` (``(n, 3)``, float64: X e Y ABSOLUTAS
    y el espesor, m ≥ 0; un punto, un vértice de una línea con su Z o su M, **declarado**: lo lee la orden) y ``polygons`` (por
    polígono, ``(anillos, espesor)``: los anillos ABSOLUTOS, el exterior primero y luego los huecos, y el espesor constante en
    él, m ≥ 0). Copia lo que recibe. ``ValueError`` (errores del programa: la orden rechaza antes un dato así con capa, entidad,
    campo y valor) si una forma no es la de arriba o un valor no es finito o es negativo."""

    points: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.float64))
    polygons: tuple[tuple[Sequence[np.ndarray], float], ...] = ()

    def __post_init__(self) -> None:
        points = np.array(self.points, dtype=np.float64)
        if points.size == 0:
            points = points.reshape(0, 3)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(f"los datos de espesor son un array (n, 3) con X, Y y el espesor, no de forma {points.shape}")
        if not np.isfinite(points).all():
            raise ValueError("un dato de espesor tiene una coordenada o un valor que no es finito")
        self._check_values(points[:, 2], "un dato de espesor")
        object.__setattr__(self, "points", points)
        found = []
        for rings, value in self.polygons:
            number = float(value)
            self._check_values(np.array([number]), "un polígono de espesor")
            group = tuple(np.array(ring, dtype=np.float64) for ring in rings)
            if not group or any(part.ndim != 2 or part.shape[1] not in (2, 3) or not np.isfinite(part).all() for part in group):
                raise ValueError("un polígono de espesor son anillos (k, 2) o (k, 3) de vértices finitos, el exterior primero")
            found.append((group, number))
        object.__setattr__(self, "polygons", tuple(found))

    @staticmethod
    def _check_values(values: np.ndarray, what: str) -> None:
        if not np.isfinite(values).all() or (values < 0.0).any():
            worst = float(values[~np.isfinite(values) | (values < 0.0)][0])
            raise ValueError(f"el espesor de {what} es un número finito y no negativo, no {worst!r} (RF-016-01, RF-015-08)")

    @property
    def count(self) -> int:
        """Los datos: los puntos y los polígonos."""
        return int(self.points.shape[0]) + len(self.polygons)


@dataclass(frozen=True, slots=True, eq=False)
class BodyJob:
    """Lo que necesita calcular un cuerpo apoyado, ya leído y sin proyecto (plan 016 §5.3.1): la ``request`` (su nombre, el
    sentido, la huella y la capa de los datos, para nombrarlos en un rechazo), el ``code`` de la entidad (``BDY-001``), la
    rejilla ``grid`` (del proyecto, de celdas cuadradas), el ``crs`` y la ``vertical`` (solo para el ráster intermedio del TIN),
    la superficie conocida ``support`` (m, float64; ``NaN``, sin dato: «sobre una base» es el apoyo y «bajo un techo», el techo),
    la ``footprint`` (máscara booleana de las celdas de la huella: el centro dentro del polígono), los ``data``
    (:class:`ThicknessData`) y los valores resueltos (``values``: por último segmento de su clave, los de
    :class:`~.params.BodyParam`: ``max_distance_m`` —sin valor por defecto: D-9— y ``zero_at_edge``, que sin valor es falso).

    **«Sobre una base»** lleva además la partida de la cadena (``start``: m, float64, ``NaN``, sin dato) y el relleno admitido
    (``fill_allowed``: máscara booleana; el de las máscaras de la 012, ``design.compose.admitted``); **«bajo un techo» no** (no
    cambia la superficie, RF-016-20).

    ``support``, ``footprint``, ``start`` y ``fill_allowed`` son de la **rejilla entera** o, con ``region``, de **esa ventana** de
    la rejilla (A0: la de :func:`body_window` basta y da el mismo resultado, bit a bit). Una ventana ha de contener la huella
    con una celda de margen por cada lado que no sea el borde de la rejilla (el borde de la huella se mira dentro de ella).
    ``ValueError`` (errores del programa) si el código no es el de un cuerpo, una clave de ``values`` no es de un cuerpo, un array
    no es de su forma, las celdas no son cuadradas, «sobre una base» no trae partida o relleno o «bajo un techo» sí, o la ventana
    corta la huella."""

    request: BodyRequest
    code: str
    grid: Grid
    crs: CrsRef
    vertical: VerticalRef
    support: np.ndarray
    footprint: np.ndarray
    data: ThicknessData
    values: Mapping[str, object]
    start: np.ndarray | None = None
    fill_allowed: np.ndarray | None = None
    region: Window | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, BodyRequest):
            raise TypeError(f"la petición de un cuerpo es una BodyRequest, no {type(self.request).__name__}")
        kind = entity_params_of(self.code).kind
        if kind != "body":
            raise ValueError(f"el código {self.code!r} no es el de un cuerpo apoyado (es de {kind})")
        if not isinstance(self.grid, Grid):
            raise TypeError(f"la rejilla es una Grid, no {type(self.grid).__name__}")
        if self.grid.dx != self.grid.dy:
            raise ValueError(f"la rejilla de un cuerpo es la del proyecto, de celdas cuadradas, no {self.grid.dx} × {self.grid.dy}")
        if not isinstance(self.crs, CrsRef) or not isinstance(self.vertical, VerticalRef):
            raise TypeError("el CRS es un CrsRef y la referencia vertical, un VerticalRef")
        if not isinstance(self.data, ThicknessData):
            raise TypeError(f"los datos de espesor son un ThicknessData, no {type(self.data).__name__}")
        if self.region is not None:
            object.__setattr__(self, "region", _window_of(self.region, self.grid))
        window = self.window
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        where = "de la rejilla" if self.region is None else "de su ventana"
        object.__setattr__(self, "support", _shaped_array(self.support, shape, np.float64, "la superficie conocida", where))
        object.__setattr__(self, "footprint", _shaped_array(self.footprint, shape, np.bool_, "la huella", where))
        on_base = self.request.sense is BodySense.ON_BASE
        for name, dtype, what in (("start", np.float64, "la partida"), ("fill_allowed", np.bool_, "el relleno admitido")):
            given = getattr(self, name)
            if on_base and given is None:
                raise ValueError(f"un cuerpo «sobre una base» necesita {what} ({name}) (RF-016-20)")
            if not on_base and given is not None:
                raise ValueError(f"un cuerpo «bajo un techo» no cambia la superficie y no lleva {what} ({name}) (RF-016-20)")
            if given is not None:
                object.__setattr__(self, name, _shaped_array(given, shape, dtype, what, where))
        known = {param.value for param in BodyParam}
        unknown = sorted(set(self.values) - known)
        if unknown:
            raise ValueError(f"los valores de un cuerpo son de {', '.join(sorted(known))}, no «{unknown[0]}»")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        if self.region is not None:
            self._check_margin(window)

    def _check_margin(self, window: Window) -> None:
        """Una ventana interior no puede tocar la huella por un lado que no sea el de la rejilla (el borde de la huella se mira
        con las celdas de fuera)."""
        rows, cols = window
        sides = (("norte", rows.start > 0, self.footprint[0, :]), ("sur", rows.stop < self.grid.nrows, self.footprint[-1, :]),
                 ("oeste", cols.start > 0, self.footprint[:, 0]), ("este", cols.stop < self.grid.ncols, self.footprint[:, -1]))
        for name, inside, line in sides:
            if inside and line.any():
                raise ValueError(f"la ventana {window!r} corta la huella por el {name}: ha de contenerla con una celda de margen "
                                 "(body_window)")

    @property
    def window(self) -> Window:
        """La ventana de la rejilla que cubren los arrays: ``region`` o, sin ella, la rejilla entera."""
        return _whole(self.grid) if self.region is None else self.region


def body_window(footprint: np.ndarray, grid: Grid) -> Window | None:
    """**A0**: la ventana de trabajo de un cuerpo: la caja de las celdas de ``footprint`` (máscara de la rejilla entera) y una
    celda más por cada lado, recortada a la rejilla; ``None`` si la huella no tiene ninguna celda (nada que calcular: la orden
    rechaza con :func:`no_data_error`). Es lo que basta leer del apoyo y de la partida. ``ValueError`` si la máscara no es de la
    forma de la rejilla."""
    found = np.asarray(footprint, dtype=np.bool_)
    if found.shape != grid.shape:
        raise ValueError(f"la huella es una máscara de la rejilla {grid.shape}, no de forma {found.shape}")
    rows = np.flatnonzero(found.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(found.any(axis=0))
    return (slice(max(int(rows[0]) - 1, 0), min(int(rows[-1]) + 2, grid.nrows)),
            slice(max(int(cols[0]) - 1, 0), min(int(cols[-1]) + 2, grid.ncols)))


def edge_cells(footprint: np.ndarray) -> np.ndarray:
    """Las celdas del **borde** de la huella ``footprint`` (máscara 2D): las de la huella con alguna de sus cuatro vecinas fuera
    de ella. Los huecos de la huella tienen su borde; **el borde del array no cuenta** (la huella sigue más allá: la rejilla solo
    la recorta). Una máscara nueva."""
    found = np.asarray(footprint, dtype=np.bool_)
    if found.ndim != 2:
        raise ValueError(f"la huella es una máscara 2D, no de forma {found.shape}")
    padded = np.pad(found, 1, constant_values=True)
    inner = (found & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return found & ~inner


@dataclass(frozen=True, slots=True)
class _Settings:
    """Lo que lee A11 de los valores del cuerpo, ya comprobado."""

    max_distance_m: float
    zero_at_edge: bool
    sense: BodySense


def _settings(job: BodyJob) -> _Settings:
    """La distancia máxima (obligatoria: D-9) y el «cero en el borde» (falso si no se da) de ``job``, comprobados
    (``des.entity_param_missing`` o ``_range``, nombrando la capa, la entidad, la clave y el valor: RF-015-08)."""
    name, code, found, layer = job.request.name, job.code, job.values, job.request.layer
    distance = check_entity_param(name, code, BodyParam.MAX_DISTANCE, found.get(BodyParam.MAX_DISTANCE.value), layer=layer)
    zero = found.get(BodyParam.ZERO_AT_EDGE.value)
    if zero is None:
        zero = entity_params("body").template(BodyParam.ZERO_AT_EDGE.value).default
    zero = check_entity_param(name, code, BodyParam.ZERO_AT_EDGE, zero, layer=layer)
    assert isinstance(distance, float) and isinstance(zero, bool)
    return _Settings(distance, zero, job.request.sense)


# --- Los rechazos (RF-016-22) ---------------------------------------------------------------------------------------------


def no_data_error(request: BodyRequest) -> DesignError:
    """**RF-016-22**: ``des.body_no_data``, el rechazo de un cuerpo cuya huella no tiene ningún dato de espesor, nombrando la
    huella (``request.feature``) y la capa de los datos (``request.data_layer``). No se registra nada."""
    return DesignError(_NO_DATA, obj=_OBJ.format(request.name), field="datos de espesor", value=request.data_layer,
                       entity=request.name, layer=request.data_layer, footprint=request.feature)


def all_far_error(request: BodyRequest, distance_m: float) -> DesignError:
    """**RF-016-22**: ``des.body_all_far``, el rechazo de un cuerpo con ninguna celda a ``distance_m`` o menos de un dato,
    nombrando la huella y la distancia máxima."""
    return DesignError(_ALL_FAR, obj=_OBJ.format(request.name), field="distancia máxima", value=distance_m,
                       entity=request.name, footprint=request.feature, distance=distance_m)


# --- Lo que da -------------------------------------------------------------------------------------------------------------


def _decimal(value: float, places: int = 2) -> str:
    """``value`` con coma decimal y sin ceros de más (para el mensaje de la operación)."""
    return f"{value:.{places}f}".rstrip("0").rstrip(".").replace(".", ",")


@dataclass(frozen=True, slots=True, eq=False)
class BodyOutcome:
    """El cuerpo apoyado (A11; RF-016-01, RF-016-20 a RF-016-22), en su ventana de trabajo (``window``: filas y columnas de la
    rejilla; todas las rejillas de abajo son de su forma): la ``footprint``; ``body`` (las celdas de la huella con la superficie
    conocida con dato: donde existe el cuerpo), el ``thickness`` (m, ≥ 0), la ``base`` y el ``top`` (m; ``NaN`` fuera de
    ``body``), la ``surface`` que deja el cuerpo «sobre una base» (``máx(partida, techo)`` en la huella admitida y la partida bit
    a bit en las demás; ``None`` «bajo un techo») y ``far`` (las celdas de ``body`` a más de la distancia máxima de su dato más
    próximo).

    Las cifras: ``volume_m3`` (la suma de los espesores de ``body`` por el área de la celda), ``thickness_max_m`` y su lugar
    (``thickness_max_x``, ``thickness_max_y``: el centro de la primera celda de arriba abajo y de oeste a este que lo tiene),
    ``far_m2``, ``far_m3`` y su lugar (``far_x``, ``far_y``: el centro de la celda más lejana; ``None`` sin lo lejano),
    ``farthest_m`` (la mayor distancia de una celda de ``body`` a su dato más próximo), ``ignored`` (los datos fuera de la
    huella), ``data_cells`` (las celdas con algún dato real), ``zero_cells`` (las del borde que solo llevan el 0),
    ``tin_cells`` y ``nearest_cells`` (las de ``body`` con el espesor del TIN o del dato más próximo) y ``unsupported_cells``
    (las de la huella sin superficie conocida: sin cuerpo). ``max_distance_m``, ``zero_at_edge`` y ``sense`` son los del cuerpo
    y ``notices`` los avisos (``des.body_data_outside`` y ``des.body_far``)."""

    name: str
    code: str
    sense: BodySense
    window: Window
    footprint: np.ndarray
    body: np.ndarray
    thickness: np.ndarray
    base: np.ndarray
    top: np.ndarray
    surface: np.ndarray | None
    far: np.ndarray
    volume_m3: float
    thickness_max_m: float
    thickness_max_x: float
    thickness_max_y: float
    far_m2: float
    far_m3: float
    far_x: float | None
    far_y: float | None
    farthest_m: float
    ignored: int
    data_cells: int
    zero_cells: int
    tin_cells: int
    nearest_cells: int
    unsupported_cells: int
    cell_area_m2: float
    max_distance_m: float
    zero_at_edge: bool
    notices: tuple[Notice, ...] = ()

    @property
    def figures(self) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO de la operación (:func:`~.provenance.body_figures`, con el ámbito de la entidad y en el orden de
        ``BODY_FIGURES``): ``des.bdy_volume_m3``, ``_thickness_max_m``, ``_far_m2``, ``_far_m3`` y ``des.bdy_ignored``."""
        return body_figures(self.name, self.code, {
            "des.bdy_volume_m3": self.volume_m3, "des.bdy_thickness_max_m": self.thickness_max_m,
            "des.bdy_far_m2": self.far_m2, "des.bdy_far_m3": self.far_m3, "des.bdy_ignored": self.ignored})

    @property
    def message(self) -> str:
        """El mensaje de la operación (como el de una retirada): lo que dice el resumen de lo calculado, con el volumen (al metro
        cúbico) y el espesor máximo."""
        return (f"Cuerpo apoyado «{self.name}»: {round(self.volume_m3)} m³ y {_decimal(self.thickness_max_m)} m de espesor "
                "máximo")

    def compose(self, start: np.ndarray) -> np.ndarray:
        """La superficie entera que deja el cuerpo «sobre una base»: una rejilla **nueva** igual a ``start`` (la superficie de
        partida, de la rejilla entera) con la ventana de trabajo sustituida por :attr:`surface`. ``ValueError`` si el cuerpo es
        «bajo un techo» (no cambia la superficie) o ``start`` no es una rejilla que contenga la ventana."""
        if self.surface is None:
            raise ValueError("un cuerpo «bajo un techo» no cambia la superficie (RF-016-20)")
        whole = np.array(start, dtype=np.float64, copy=True)
        rows, cols = self.window
        if whole.ndim != 2 or rows.stop > whole.shape[0] or cols.stop > whole.shape[1]:
            raise ValueError(f"la superficie de partida {whole.shape} no contiene la ventana del cuerpo ({rows}, {cols})")
        whole[self.window] = self.surface
        return whole


# --- A11 ---------------------------------------------------------------------------------------------------------------


type _Carried = tuple[np.ndarray, np.ndarray, int]


def _carry_units(job: BodyJob) -> Generator[None, None, _Carried]:
    """Las unidades de llevar los datos a sus celdas: la suma y el número de datos de cada celda de la ventana (puntos y
    polígonos juntos) y cuántos datos caen fuera de la huella. Los puntos van de una vez y cada polígono es una unidad."""
    grid, rows, cols = job.grid, *job.window
    height, width = rows.stop - rows.start, cols.stop - cols.start
    footprint = job.footprint
    sums = np.zeros((height, width), dtype=np.float64)
    counts = np.zeros((height, width), dtype=np.int64)
    ignored = 0
    points = job.data.points
    if len(points):
        col = np.floor((points[:, 0] - grid.west) / grid.dx)
        row = np.floor((grid.north - points[:, 1]) / grid.dy)
        inside = (row >= rows.start) & (row < rows.stop) & (col >= cols.start) & (col < cols.stop)
        local_row = row[inside].astype(np.int64) - rows.start
        local_col = col[inside].astype(np.int64) - cols.start
        kept = footprint[local_row, local_col]
        ignored += len(points) - int(np.count_nonzero(kept))
        flat = local_row[kept] * width + local_col[kept]
        sums += np.bincount(flat, weights=points[inside, 2][kept], minlength=height * width).reshape(height, width)
        counts += np.bincount(flat, minlength=height * width).reshape(height, width)
    yield
    for rings, value in job.data.polygons:
        spans = _polygon_spans([rings], grid, box=job.window)
        top, left, block = _paint(spans, height, width)
        if block.size == 0:
            ignored += 1
            continue
        part = (slice(top - rows.start, top - rows.start + block.shape[0]),
                slice(left - cols.start, left - cols.start + block.shape[1]))
        take = block & footprint[part]
        if not take.any():
            ignored += 1
            continue
        sums[part][take] += value
        counts[part][take] += 1
        yield
    return sums, counts, ignored


def _collinear(rows: np.ndarray, cols: np.ndarray) -> bool:
    """Si las celdas ``(rows, cols)`` (enteros, distintas) están todas en una recta: el producto cruzado, exacto con enteros."""
    d_row, d_col = rows - rows[0], cols - cols[0]
    moved = np.flatnonzero((d_row != 0) | (d_col != 0))
    if moved.size == 0:
        return True
    first = int(moved[0])
    return not bool(np.any(d_col[first] * d_row - d_row[first] * d_col))


def _triangulate_units(xy: np.ndarray) -> Generator[None, None, np.ndarray]:
    """La triangulación de Delaunay de ``xy`` (float64 ``(n ≥ 3, 2)``, no alineados: unidades de celda) por
    ``gis.cdt.PureTriangulator.triangulate``, **tal como está**: int32 ``(m, 3)``. Hoy una sola unidad; la T24 la parte en pasos
    de 256 puntos (``triangulate_steps``, la misma salida bit a bit) sin cambiar este contrato."""
    triangles = PureTriangulator().triangulate(xy, np.empty((0, 2), dtype=np.int32))
    yield
    return triangles


def _rasterize_units(tin: Tin, shape: tuple[int, int], job: BodyJob) -> Generator[None, None, np.ndarray]:
    """El TIN (en unidades de celda) en la rejilla ``(0, 0, 1, 1)`` de la ventana de ``shape``: el espesor interpolado
    linealmente en el centro de cada celda y ``NaN`` donde no llega (``gis.tin.tin_to_raster``). Hoy una sola unidad; la T24 la
    parte por bandas de filas sin cambiar este contrato."""
    unit = Grid(0.0, 0.0, 1.0, 1.0, shape[1], shape[0])
    raster = tin_to_raster(tin, unit, crs=job.crs, vertical=job.vertical)
    yield
    return np.asarray(raster.values, dtype=np.float64)


def _tin_units(job: BodyJob, mask: np.ndarray, data: np.ndarray, settings: _Settings, cell: float
               ) -> Generator[None, None, np.ndarray]:
    """El espesor del TIN lineal de las celdas con dato (``mask``, con su valor en ``data``) en la ventana, ``NaN`` donde no
    llega: sin triángulos (menos de tres datos, alineados o todos con un lado mayor que ``2·max_distance_m``), todo ``NaN``."""
    shape = mask.shape
    nothing = np.full(shape, np.nan)
    rows, cols = np.nonzero(mask)
    if rows.size < 3 or _collinear(rows, cols):
        return nothing
    xy = np.column_stack([cols + 0.5, -(rows + 0.5)])
    faces = yield from _triangulate_units(xy)
    corner = xy[faces]
    sides = corner - np.roll(corner, 1, axis=1)
    longest2 = (sides ** 2).sum(axis=2).max(axis=1)  # celdas²: cada vértice es un entero y medio, exacto
    faces = faces[longest2 * (cell * cell) <= 4.0 * settings.max_distance_m * settings.max_distance_m]
    if not len(faces):
        return nothing
    vertices = np.column_stack([xy, data[rows, cols]])
    tin = Tin(vertices, faces, np.empty((0, 2), dtype=np.int32), np.full(len(vertices), 5, dtype=np.uint8),
              triangulator=PureTriangulator.name)
    values = yield from _rasterize_units(tin, shape, job)
    return values


def _first_cell(found: np.ndarray, values: np.ndarray) -> tuple[int, int]:
    """La primera celda (de arriba abajo y de oeste a este) con el mayor de ``values`` entre las de ``found``."""
    index = int(np.argmax(np.where(found, values, -np.inf)))
    row, col = divmod(index, found.shape[1])
    return row, col


def _body_units(job: BodyJob, settings: _Settings) -> Generator[None, None, BodyOutcome]:
    """Las unidades de :func:`body_steps`: los datos a sus celdas, el TIN, el dato más próximo, la regla del espesor, la
    superficie y las cifras (por bandas de filas)."""
    grid, request = job.grid, job.request
    rows, cols = job.window
    height, width = rows.stop - rows.start, cols.stop - cols.start
    cell, area = grid.dx, grid.cell_area
    footprint = job.footprint
    sums, counts, ignored = yield from _carry_units(job)
    real = counts > 0
    if not real.any():
        raise no_data_error(request)
    zero_cells = 0
    if settings.zero_at_edge:
        edge = edge_cells(footprint)
        zero_cells = int(np.count_nonzero(edge & ~real))
        counts = counts + edge
    mask = counts > 0
    data = np.where(mask, sums / np.maximum(counts, 1), 0.0)
    del sums, counts
    yield
    support = job.support
    body = footprint & np.isfinite(support)
    nearest = yield from _nearest_units(mask, data, cell)
    d2 = nearest.cells2.astype(np.float64) * (cell * cell)
    far = body & (d2 > settings.max_distance_m * settings.max_distance_m)
    if not np.any(body & ~far):
        raise all_far_error(request, settings.max_distance_m)
    tin_values = yield from _tin_units(job, mask, data, settings, cell)
    covered = np.isfinite(tin_values)
    spread = np.where(covered, tin_values, nearest.value)
    np.clip(spread, float(data[mask].min()), float(data[mask].max()), out=spread)  # el redondeo no sale del intervalo
    thickness = np.where(body, spread, np.nan)
    del spread, tin_values
    yield
    base, top = derive(support, thickness, settings.sense)
    surface = None
    if settings.sense is BodySense.ON_BASE:
        assert job.start is not None and job.fill_allowed is not None
        surface = compose(job.start, top, footprint & job.fill_allowed, BenchSense.FILL)
    yield
    volume_parts: list[float] = []
    far_parts: list[float] = []
    step = max(1, CELLS_PER_UNIT // max(width, 1))
    for first in range(0, height, step):
        band = slice(first, first + step)
        volume_parts.append(float(thickness[band][body[band]].sum()))
        far_parts.append(float(thickness[band][far[band]].sum()))
        yield
    top_row, top_col = _first_cell(body, thickness)
    far_cells = int(np.count_nonzero(far))
    far_x = far_y = None
    if far_cells:
        far_row, far_col = _first_cell(far, d2)
        far_x = grid.west + (cols.start + far_col + 0.5) * grid.dx
        far_y = grid.north - (rows.start + far_row + 0.5) * grid.dy
    body_cells = int(np.count_nonzero(body))
    tin_cells = int(np.count_nonzero(body & covered))
    far_m2, far_m3 = far_cells * area, math.fsum(far_parts) * area
    notices: list[Notice] = []
    if ignored:
        notices.append(Notice(_OUTSIDE, {"entity": request.name, "ignored": ignored}))
    if far_cells:
        assert far_x is not None and far_y is not None
        notices.append(Notice(_FAR, {"entity": request.name, "area": round(far_m2, 2), "volume": round(far_m3, 2),
                                     "distance": settings.max_distance_m, "x": round(far_x, 2), "y": round(far_y, 2)}))
    return BodyOutcome(
        name=request.name, code=job.code, sense=settings.sense, window=job.window, footprint=footprint.copy(), body=body,
        thickness=thickness, base=base, top=top, surface=surface, far=far,
        volume_m3=math.fsum(volume_parts) * area, thickness_max_m=float(thickness[top_row, top_col]),
        thickness_max_x=grid.west + (cols.start + top_col + 0.5) * grid.dx,
        thickness_max_y=grid.north - (rows.start + top_row + 0.5) * grid.dy,
        far_m2=far_m2, far_m3=far_m3, far_x=far_x, far_y=far_y, farthest_m=math.sqrt(float(d2[body].max())),
        ignored=ignored, data_cells=int(np.count_nonzero(real)), zero_cells=zero_cells, tin_cells=tin_cells,
        nearest_cells=body_cells - tin_cells, unsupported_cells=int(np.count_nonzero(footprint & ~body)), cell_area_m2=area,
        max_distance_m=settings.max_distance_m, zero_at_edge=settings.zero_at_edge, notices=tuple(notices))


def body_steps(job: BodyJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A11** (RF-016-01, RF-016-20 a RF-016-22; plan 016 §5.4): el cuerpo de ``job`` por pasos de ``budget_s`` como mucho
    (RNF-016-03): el último ``Progress`` (fase ``body``) lleva el :class:`BodyOutcome`. Véase el módulo.

    Rechazos **al llamar**, nombrando la capa, la entidad, la clave del campo y el valor (RF-015-08): sin distancia máxima
    (``des.entity_param_missing``: D-9, no se elige una por la persona) o fuera de su rango (``des.entity_param_range``); y **al
    avanzar** (RF-016-22), sin ningún dato de espesor en la huella (``des.body_no_data``) o con ninguna celda del cuerpo a la
    distancia máxima de un dato (``des.body_all_far``). Lo lejano es un aviso (``des.body_far``), no un rechazo. Ninguna entrada
    se modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    settings = _settings(job)
    return pace_progress(_body_units(job, settings), budget_s, phase=_PHASE, running="Calculando el cuerpo apoyado…",
                         finished="Cuerpo apoyado calculado")


def compute_body(job: BodyJob) -> BodyOutcome:
    """**A11**: :func:`body_steps` hasta el final, sin pasos: el :class:`BodyOutcome` de ``job``. Los mismos rechazos."""
    work = _body_units(job, _settings(job))
    while True:
        try:
            next(work)
        except StopIteration as done:
            outcome: Any = done.value
            assert isinstance(outcome, BodyOutcome)
            return outcome
