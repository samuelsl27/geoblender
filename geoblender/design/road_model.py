# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la pista y de la accesibilidad (spec 017, T05; HU-017-1 a 3; RF-017-01, 02, 04, 10, 24; plan 017 §5.1,
§5.2.1, §5.2.2 y §5.3.1).

Lo que entrega, todo inmutable (``frozen``, ``slots``) y sin ninguna cifra minera por defecto (lo que no se pide es
``None``: el valor por defecto del parámetro o, si no lo tiene, el rechazo de RF-015-08, que es de la preparación):

- **La pista.** :class:`RoadMode` (``trace``, ``on_axis`` y ``axis_3d``: RF-017-02), :class:`RouteParams` (los nueve
  parámetros de la ruta, ya resueltos: RF-017-10), :class:`RoadRequest` (lo que pide el diálogo, con la capa y su campo,
  :class:`LayerFields`), :class:`RoadJob` (todo lo leído y **nada del proyecto**, para calcular sin proyecto y
  reproducir: la rejilla, la superficie de partida, las máscaras como arrays, la geometría —:class:`RoadGeometry` y
  :class:`LevelDestination`—, el perfil y los parámetros resueltos) y :class:`RoadOutcome` (el resultado).
- **La accesibilidad** (RF-017-24, RF-017-25). :class:`AccessRequest` (**sin** ``start``: no parte de ninguna
  superficie), :class:`AccessJob` (con :class:`EntryPoint`, :class:`BermGrid` y :class:`AccessCells`: lo que se lee una
  vez de la superficie, la final de una cantera, las bermas, las plataformas y las zonas «requiere acceso») y
  :class:`AccessOutcome` (con la comunicación de cada tramo de berma, plataforma y zona: :class:`BermReach`,
  :class:`PlatformReach` y :class:`ZoneReach`).
- **Los códigos de error** de lo que el cálculo no puede dar (RF-017-12): :class:`NoRouteCause` (las tres causas de «sin
  ruta») y :class:`LimitCause` (las cinco restricciones del tramo limitante). Su valor **es** el código de
  :mod:`design.messages`; el texto, en español y en inglés, y la gravedad son de ahí.

La validación al construir es de tipos y de forma (``TypeError`` si un valor no es de su tipo, ``ValueError`` si no es de
su forma o sale de su rango): son errores del programa. **Los rechazos de la persona**, con su capa, su pista (o su
perfil), el campo y el valor (RF-017-04), son de la preparación (T19 y T23, T17 para la accesibilidad), que los hace antes
de registrar nada y arma estos datos solo con lo que ya está comprobado. Los arrays que llevan los trabajos y los
resultados son **vistas de solo lectura** (float64 y booleanos): los del que los entregó siguen siendo suyos. Las
coordenadas absolutas van en float64 (regla 4 de AGENTS.md, ADR-0005); las celdas, por índice de la rejilla en filas.

**Lo define esta tarea y, en serie, una posterior puede añadirle un campo que su algoritmo necesite** (compatible hacia
atrás y anotado en su verificación): :class:`RoadOutcome` nace con lo que no depende de los algoritmos (la ventana, la
superficie, la huella, las cifras y los avisos) y el de la accesibilidad con la parte de A10 antes de las listas de A11.

**Perezoso** (RNF-001-03): este módulo y las peticiones ``@dataclass(frozen=True, slots=True)`` (≈ 0,5–1 ms cada una al
importar) no los carga ``design.model`` ni nada que habilitar Geoblender importe; las pide quien calcula. Y **no importa**
:mod:`design.road_profiles` (la tabla de los perfiles y su edición) al importarse: solo lo usa, dentro de
:class:`RoadJob`, al construir un trabajo. Python puro (nivel 8: ``core``, ``gis``).
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.messages import format_value
from .model import _name_or_none, _real_or_none, _text
from .params import (
    ACCESS_RANGES,
    ROAD_RANGES,
    AccessParam,
    RoadParam,
    ValueRange,
    entity_params,
    entity_params_of,
)
from .preview import Notice
from .supported_requests import _int_or_none, _named

if TYPE_CHECKING:
    from .road_axis import Axis
    from .road_engrave import Engraved
    from .road_profiles import RoadProfile
    from .road_route import Arrival

__all__ = [
    "BUDGET_NOTICE_STATES",
    "DEFAULT_SEARCH_BUDGET",
    "MAX_LEVELS",
    "ROUTE_STATE_BYTES",
    "AccessCells",
    "AccessJob",
    "AccessOutcome",
    "AccessRequest",
    "BermGrid",
    "BermReach",
    "EntryPoint",
    "LayerFields",
    "LevelDestination",
    "LimitCause",
    "NoRouteCause",
    "PlatformReach",
    "ProposalOutcome",
    "RoadGeometry",
    "RoadJob",
    "RoadMode",
    "RoadOutcome",
    "RoadRequest",
    "RouteParams",
    "RouteReport",
    "ZoneReach",
    "budget_memory_gib",
    "level_count",
    "min_level_step_m",
]

DEFAULT_SEARCH_BUDGET: int = int(entity_params("road").template(RoadParam.SEARCH_BUDGET.value).default)  # type: ignore[arg-type]
"""El presupuesto de estados expandidos de la ruta 3D cuando nadie lo pide (RF-017-10, P-3): el valor por defecto de la
familia ``des.road.{e}.search_budget`` (5.000.000, ADOPTADO «sin confirmar»), **leído de** :mod:`design.params` y no escrito
aquí."""

MAX_LEVELS: int = 2000
"""El tope del número de niveles a cada lado de un nodo, ``M = ⌊H/Δz⌋`` (la altura máxima de desmonte y terraplén entre el paso de cota; RF-017-10, RF-017-04; B-5 de la verificación única, T41): 2.000, 40 veces
los 50 de la referencia (14 m / 0,28 m). **Un límite de validez de la búsqueda, no una cifra minera**: sus tablas de saltos de nivel y de costes crecen con ``M`` (con H = 14 m y un paso de 0,0001 m, 140.000 niveles,
la preparación de una malla de 10 × 10 nodos tardaba 108 s en una sola llamada y 424 MiB, medido por el verificador B; con 0,001 m, 10 s y 43 MiB), de modo que un error de tecleo rompía RNF-017-06. Procedencia:
HIPÓTESIS de la sesión principal (21/11/2026, revisable); la preparación lo rechaza con el campo, el valor y el paso mínimo (``des.road_level_step_small``)."""
ROUTE_STATE_BYTES: int = 140
"""Los bytes que ocupa cada estado visto de la ruta 3D (un entero de la etiqueta y otro de la cola): ≈ 135 a 140 medidos por la T07 y la T34 (965 MiB de pico del proceso con 5,98 M estados vistos y 167 MiB de base)."""
BUDGET_NOTICE_STATES: int = 2 * DEFAULT_SEARCH_BUDGET
"""El presupuesto de estados por encima del cual la preparación avisa de la memoria que puede ocupar la búsqueda (``des.road_budget_memory``; B-5, T41): **más del doble del que viene por defecto** (5 M estados ≈ 1 GiB
medido); el parámetro admite hasta 10⁹ (``ROAD_RANGES``) y no se le pone un tope, que cambiaría el rango aprobado. Un umbral de aviso (HIPÓTESIS de la sesión principal, revisable), no una cifra minera."""
_LEVEL_TOLERANCE = 1e-9
"""El margen (en niveles) con que ``H/Δz`` da el número de niveles ``M``: ``14/0,28`` es 49,999… o 50,000… según el último bit."""
_STEP_DIGITS = 6
"""Los decimales (m: el micrómetro) a que :func:`min_level_step_m` redondea hacia arriba el paso de cota mínimo."""


def level_count(height_m: float, step_m: float) -> int:
    """El número de niveles a cada lado de un nodo de la ruta, ``M = ⌊H/Δz⌋`` (con ``H`` la altura máxima de desmonte y terraplén y ``Δz`` el paso de cota, m): la cota de un nodo es el terreno más ``m·Δz`` con ``m``
    de ``−M`` a ``M``. La cuenta de la búsqueda (:func:`~design.road_route.route_steps`) y la del tope :data:`MAX_LEVELS` son esta."""
    return math.floor(height_m / step_m + _LEVEL_TOLERANCE)


def min_level_step_m(height_m: float) -> float:
    """El paso de cota **menor** (m, redondeado hacia arriba al micrómetro) con que la altura máxima ``height_m`` (> 0) da como mucho :data:`MAX_LEVELS` niveles a cada lado: el que dice el rechazo de un paso de cota
    demasiado pequeño (``des.road_level_step_small``)."""
    return math.ceil(round(height_m / MAX_LEVELS * 10**_STEP_DIGITS, 3)) / 10**_STEP_DIGITS


def budget_memory_gib(budget: int) -> float | None:
    """La memoria (GiB de 2³⁰ bytes, :data:`ROUTE_STATE_BYTES` por estado) que puede ocupar una búsqueda con ``budget`` estados expandidos, **si** el presupuesto pasa de :data:`BUDGET_NOTICE_STATES` (más del doble
    del de por defecto); si no, ``None``: no hay nada que avisar (``des.road_budget_memory``)."""
    if budget <= BUDGET_NOTICE_STATES:
        return None
    return budget * ROUTE_STATE_BYTES / 1024**3

Point = tuple[float, float]
"""Un punto absoluto ``(x, y)`` (m, float64)."""
Window = tuple[slice, slice]
"""Una ventana de la rejilla: sus filas y sus columnas (``slice`` de enteros, sin paso)."""
Parts = tuple[tuple[np.ndarray, ...], ...]
"""Un polígono: por parte, sus anillos (el primero, el exterior), cada uno un array float64 ``(k, 2)`` absoluto."""

_ROUTE_REALS = ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
                "arrival_tol_m")
"""Los ocho parámetros de la ruta sin valor por defecto (HIPÓTESIS, D-10 y D-11): el noveno, el presupuesto, lo tiene."""


# --- Los enumerados y los códigos de error ------------------------------------------------------------------------------


class RoadMode(StrEnum):
    """El modo de una pista (RF-017-02): ``TRACE`` («trazar», de un origen a un destino: sale el eje y la rasante),
    ``ON_AXIS`` («sobre un eje»: una línea en planta a la que se ajustan las curvas y se da la rasante) y ``AXIS_3D`` («eje
    3D»: una línea con su Z, que **es** la rasante: solo se comprueba y se graba). Es el texto del parámetro ``mode``
    (:data:`~design.provenance.ROAD_MODES`)."""

    TRACE = "trace"
    ON_AXIS = "on_axis"
    AXIS_3D = "axis_3d"


class NoRouteCause(StrEnum):
    """Por qué no hay ruta (RF-017-12): ``NETWORK`` (la red 2D no alcanza el origen), ``CORRIDOR`` (lo alcanza y el pasillo
    no contiene ninguna ruta 3D) o ``BUDGET`` (la búsqueda agotó su presupuesto de estados: una tercera causa, **no** «no
    hay ruta»). Su valor es el código del rechazo de :mod:`design.messages`."""

    NETWORK = "des.road_no_route_network"
    CORRIDOR = "des.road_no_route_corridor"
    BUDGET = "des.road_budget"


class LimitCause(StrEnum):
    """La restricción del tramo limitante de un «sin ruta» (RF-017-12): ``SLOPE`` (la pendiente máxima de diseño), ``MASK``
    (una zona que las máscaras prohíben pisar), ``HEIGHT`` (la altura máxima de desmonte y terraplén), ``GRID_EDGE`` (el
    borde de la rejilla) o ``NO_DATA`` (celdas sin dato en la superficie de partida). Su valor es el código de la nota de
    :mod:`design.messages` que va detrás del error."""

    SLOPE = "des.road_limit_slope"
    MASK = "des.road_limit_mask"
    HEIGHT = "des.road_limit_height"
    GRID_EDGE = "des.road_limit_grid_edge"
    NO_DATA = "des.road_limit_no_data"


# --- Ayudantes de validación ---------------------------------------------------------------------------------------------


def _real(value: object, what: str) -> float:
    """``value`` como ``float`` finito; :class:`TypeError` si no es un número real (un texto o un booleano no lo son);
    :class:`ValueError` si no es finito."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} no es finito: {value!r}")
    return number


def _real_if_given(value: object, what: str) -> float | None:
    """:func:`_real`, o ``None`` si ``value`` es ``None``."""
    return None if value is None else _real(value, what)


def _ranged(value: object, key: str, ranges: Mapping[str, ValueRange], what: str) -> float:
    """``value`` como ``float`` finito dentro del rango ``ranges[key]`` (la fuente única de los rangos, :mod:`design.params`);
    :class:`ValueError` si sale de él."""
    number = _real(value, f"«{key}» de {what}")
    span = ranges[key]
    if not span.contains(number):
        raise ValueError(f"«{key}» de {what} = {number!r} está fuera de su rango {span.text()}")
    return number


def _flag(value: object, what: str) -> bool:
    """``value`` si es un sí/no; :class:`TypeError` si no lo es."""
    if not isinstance(value, bool):
        raise TypeError(f"{what} es un sí/no, no {value!r}")
    return value


def _label(value: object, what: str) -> str:
    """El texto ``value`` sin los espacios de los extremos; :class:`TypeError` si no es un texto y :class:`ValueError` si
    está en blanco."""
    text = _text(value, what)
    if not text:
        raise ValueError(f"{what} no puede estar en blanco")
    return text


def _readonly(values: object, shape: tuple[int, ...], dtype: type, what: str) -> np.ndarray:
    """``values`` como una **vista de solo lectura** del ``dtype`` pedido y de la forma ``shape`` (:class:`ValueError` si no es
    de ella): la vista no cambia las banderas del array de quien lo entrega."""
    array = np.asarray(values, dtype=dtype)
    if array.shape != shape:
        raise ValueError(f"{what} es de la forma de la rejilla {shape}, no {array.shape}")
    view = array.view()
    view.flags.writeable = False
    return view


def _kind_code(code: object, kind: str, what: str) -> str:
    """``code`` si es el código de una entidad de tipo ``kind`` (``RDW-001``, ``ACC-001``); :class:`TypeError` si no es un
    texto y :class:`ValueError` si no es un código de entidad, no es de un tipo registrado o es de otro tipo."""
    found = entity_params_of(code)  # type: ignore[arg-type]
    if found.kind != kind:
        raise ValueError(f"el código {code!r} no es el de {what} ({found.code_prefix}-… es de {found.kind})")
    return str(code)


def _point(value: object, what: str) -> Point:
    """``value`` como un punto absoluto ``(x, y)`` de ``float`` finitos: :class:`TypeError` si no son dos números reales y
    :class:`ValueError` si alguno no es finito."""
    try:
        x, y = value  # type: ignore[misc]
    except (TypeError, ValueError):
        raise TypeError(f"{what} es un punto (x, y), no {value!r}") from None
    return (_real(x, f"la x de {what}"), _real(y, f"la y de {what}"))


def _line(value: object) -> np.ndarray:
    """La línea ``value`` como un array float64 ``(k, 2)`` o ``(k, 3)`` (con su Z) de solo lectura, de al menos dos vértices
    y con la X y la Y finitas (la Z, de un «eje 3D», la comprueba :class:`RoadJob`)."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] not in (2, 3) or array.shape[0] < 2:
        raise ValueError(f"una línea es un array (k, 2) o (k, 3) con al menos dos vértices, no de forma {array.shape}")
    if not np.isfinite(array[:, :2]).all():
        raise ValueError("una línea tiene coordenadas X o Y no finitas")
    view = array.view()
    view.flags.writeable = False
    return view


def _ring(value: object) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] < 3:
        raise ValueError(f"un anillo es un array (k, 2) con al menos tres vértices, no de forma {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("un anillo tiene coordenadas no finitas")
    view = array.view()
    view.flags.writeable = False
    return view


def _parts(value: object, what: str) -> Parts:
    """Las partes de un polígono (por parte, sus anillos) con cada uno como un array float64 ``(k, 2)`` de solo lectura:
    :class:`ValueError` si no tiene ninguna parte, una parte no tiene ningún anillo o un anillo no es válido."""
    try:
        parts = tuple(value)  # type: ignore[call-overload]
    except TypeError:
        raise TypeError(f"{what} son partes de un polígono (por parte, sus anillos), no {value!r}") from None
    if not parts:
        raise ValueError(f"{what} tiene al menos una parte")
    found: list[tuple[np.ndarray, ...]] = []
    for part in parts:
        rings = tuple(part)
        if not rings:
            raise ValueError(f"{what} tiene una parte sin anillos")
        found.append(tuple(_ring(ring) for ring in rings))
    return tuple(found)


def _window(window: object) -> Window:
    """La ventana ``(filas, columnas)`` con sus extremos enteros y sin paso: :class:`TypeError` si no son dos ``slice`` y
    :class:`ValueError` si un extremo no es un entero, no es positivo o la ventana está vacía."""
    if not isinstance(window, tuple) or len(window) != 2 or not all(isinstance(part, slice) for part in window):
        raise TypeError(f"una ventana son dos slice (filas y columnas), no {window!r}")
    found: list[slice] = []
    for part in window:
        start, stop = part.start, part.stop
        if (part.step not in (None, 1) or isinstance(start, bool) or isinstance(stop, bool)
                or not isinstance(start, int) or not isinstance(stop, int) or not 0 <= start < stop):
            raise ValueError(f"una ventana se indica con filas y columnas enteras de 0 a su fin, sin paso: {part!r}")
        found.append(slice(start, stop))
    return found[0], found[1]


def _tuple_of[T](items: Iterable[object], kind: type[T], what: str) -> tuple[T, ...]:
    """``items`` como una tupla de instancias de ``kind`` (:class:`TypeError` si no es una colección o alguno es de otro tipo)."""
    if isinstance(items, str | bytes):
        raise TypeError(f"{what} es una lista de {kind.__name__}, no {items!r}")
    try:
        found = tuple(items)
    except TypeError:
        raise TypeError(f"{what} es una lista de {kind.__name__}, no {items!r}") from None
    for item in found:
        if not isinstance(item, kind):
            raise TypeError(f"{what} son {kind.__name__}, no {item!r}")
    return tuple(item for item in found if isinstance(item, kind))


# --- La pista: lo que se pide ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerFields:
    """Una capa del proyecto y el campo con el nombre de sus geometrías (plan 017 §5.2.1; RF-017-02): su ``layer`` y,
    si la capa lo tiene, el campo del nombre (``name_field``: su clave; sin él se usa el ``fid``). Los nombres de campo se
    eligen en el diálogo, como en la 014, la 015 y la 016; solo la capa es obligatoria. Es la capa de la pista (sus puntos o
    su línea) y la de los puntos de entrada de una accesibilidad."""

    layer: str
    name_field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", _label(self.layer, "la capa"))
        object.__setattr__(self, "name_field", _name_or_none(self.name_field, "«name_field» de los campos de una capa"))


@dataclass(frozen=True, slots=True)
class RoadRequest:
    """Lo que pide el usuario de «Pista…» (RF-017-01, RF-017-02, RF-017-10; plan 017 §5.2.2 y §5.3.3; el homólogo de
    ``PlatformRequest``): su ``name`` (único en la versión), la capa con su campo (``fields``), el ``mode`` (RF-017-02), el
    código del perfil de pista (``profile``: ``pista_principal``, el de ``des_road_profile``) y la superficie de la que parte
    (``start``: el nombre de su dato; la que el diálogo propone por defecto es la de explotación de una cantera de la 014 y,
    si no, la última de la cadena: D-3, T19).

    Lo demás es opcional y, si no se pide, es ``None``: el valor por defecto del parámetro (solo el presupuesto de estados
    lo tiene) o, si no lo tiene, el rechazo de RF-015-08 de la preparación, que decide también qué pide cada modo (P-14:
    «trazar» pide el origen, el destino y los nueve de la ruta; «sobre un eje» y «eje 3D», la geometría de su capa,
    ``feature``). ``feature`` es la geometría de la capa en los modos con línea (su nombre o su ``fid``, como texto);
    ``support``, la superficie de apoyo; ``origin`` y ``destination``, **la referencia** del origen y del destino como texto
    (un punto de la capa por su ``fid`` o su nombre, ``RDW-001@s`` —el eje de otra pista a la abscisa ``s``— o una
    entidad: la preparación la resuelve, T19); ``dest_level_m``, ``dest_tol_m`` y ``dest_zone``, el destino por cota (la
    rampa, D-4: la cota, su tolerancia de llegada y la capa de la zona), que **no** se da junto a un ``destination``
    (:class:`ValueError`: es un punto, una entidad **o** una cota); ``start_level_m`` y ``end_level_m``, las cotas de inicio y
    de fin (D-13: si no se dan, las de la superficie de partida en esos puntos, anotadas con su origen) y los parámetros de
    la ruta (``mesh_m``…``search_budget``: :class:`RouteParams`, HIPÓTESIS sin valor por defecto, D-10 y D-11).

    **No tiene** ``protect`` ni ``guard_m`` (la pista no declara restricción alguna: D-15) ni lo declarado después
    (``supports``) ni el descarte (``discarded`` y ``reason``): no son del diálogo de crearla. Lo leído (rejilla, partida,
    máscaras, geometrías y perfil) no es parte de la petición: lo recoge el cálculo (:class:`RoadJob`)."""

    name: str
    fields: LayerFields
    mode: RoadMode | str
    profile: str
    start: str
    feature: str | None = None
    support: str | None = None
    origin: str | None = None
    destination: str | None = None
    dest_level_m: float | None = None
    dest_tol_m: float | None = None
    dest_zone: str | None = None
    start_level_m: float | None = None
    end_level_m: float | None = None
    mesh_m: float | None = None
    level_step_m: float | None = None
    max_cut_fill_m: float | None = None
    lambda_per_m: float | None = None
    turn_m: float | None = None
    margin_m: float | None = None
    simplify_m: float | None = None
    arrival_tol_m: float | None = None
    search_budget: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de una pista", "Pista"))
        if not isinstance(self.fields, LayerFields):
            raise TypeError(f"la capa de una pista es LayerFields, no {self.fields!r}")
        object.__setattr__(self, "mode", RoadMode(self.mode))
        for attr in ("profile", "start"):
            object.__setattr__(self, attr, _text(getattr(self, attr), f"«{attr}» de una pista"))
        for attr in ("feature", "support", "origin", "destination", "dest_zone"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de una pista"))
        for attr in ("dest_level_m", "dest_tol_m", "start_level_m", "end_level_m", *_ROUTE_REALS):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de una pista"))
        object.__setattr__(self, "search_budget", _int_or_none(self.search_budget, "«search_budget» de una pista"))
        by_level = [attr for attr in ("dest_level_m", "dest_tol_m", "dest_zone") if getattr(self, attr) is not None]
        if self.destination is not None and by_level:
            raise ValueError("el destino de una pista es un punto, una entidad o una cota con su zona y su tolerancia "
                             f"(RF-017-02): se pidió el destino {self.destination!r} y {', '.join(by_level)}")

    @property
    def layer(self) -> str:
        """La capa de la pista."""
        return self.fields.layer


@dataclass(frozen=True, slots=True)
class RouteParams:
    """Los parámetros de la ruta, **ya resueltos** (RF-017-10, RF-017-09, RF-017-13; plan 017 §5.2.2; los nueve valores de
    ``des.road.{e}.*`` que solo lee «trazar»: P-14): la malla (``mesh_m``, un múltiplo entero del paso del proyecto, D-10), el
    paso de cota (``level_step_m``), la altura máxima de desmonte y terraplén (``max_cut_fill_m``), el peso del movimiento
    de tierras (``lambda_per_m``, 1/m), la penalización de giro (``turn_m``), la holgura del pasillo (``margin_m``: la
    holgura, no el ancho), la tolerancia de simplificación (``simplify_m``), la de llegada (``arrival_tol_m``) y el
    presupuesto de estados expandidos (``search_budget``).

    Los ocho primeros son HIPÓTESIS sin valor por defecto (D-10 y D-11; los de la referencia de IMGA son de las pruebas):
    se piden todos. El presupuesto sí lo tiene (:data:`DEFAULT_SEARCH_BUDGET`, ADOPTADO «sin confirmar»). Cada uno ha de
    estar en el rango de su familia (:data:`~design.params.ROAD_RANGES`, la fuente única: ``ValueError`` si no, y
    ``TypeError`` si no es un número real, o un entero el presupuesto); que la malla sea un múltiplo del paso del proyecto es
    de la red 2D (T06), que conoce la rejilla."""

    mesh_m: float
    level_step_m: float
    max_cut_fill_m: float
    lambda_per_m: float
    turn_m: float
    margin_m: float
    simplify_m: float
    arrival_tol_m: float
    search_budget: int = DEFAULT_SEARCH_BUDGET

    def __post_init__(self) -> None:
        for attr in _ROUTE_REALS:
            object.__setattr__(self, attr, _ranged(getattr(self, attr), attr, ROAD_RANGES, "los parámetros de la ruta"))
        budget = self.search_budget
        if isinstance(budget, bool) or not isinstance(budget, numbers.Integral):
            raise TypeError(f"«search_budget» de los parámetros de la ruta es un número entero, no {budget!r}")
        object.__setattr__(self, "search_budget",
                           int(_ranged(int(budget), "search_budget", ROAD_RANGES, "los parámetros de la ruta")))
        levels = level_count(self.max_cut_fill_m, self.level_step_m)
        if levels > MAX_LEVELS:  # B-5: la preparación lo rechaza antes con el campo (``des.road_level_step_small``); aquí, un error del programa
            raise ValueError(f"«level_step_m» de los parámetros de la ruta = {self.level_step_m!r} da {levels} niveles a cada lado con la altura máxima de {self.max_cut_fill_m!r} m: el tope es {MAX_LEVELS}; "
                             f"el paso de cota mínimo para esa altura es {min_level_step_m(self.max_cut_fill_m):g} m")

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> RouteParams:
        """Los parámetros de la ruta de ``values``: los valores resueltos de la pista por su último segmento (``mesh_m``…:
        ``RoadParam``; los demás —la capa, el modo, el perfil…— no son suyos y se ignoran). Sin presupuesto toma el valor
        por defecto del parámetro (:data:`DEFAULT_SEARCH_BUDGET`). :class:`ValueError` si falta uno de los ocho sin valor por
        defecto: es un error del programa, porque la preparación ya lo rechazó (RF-015-08) sin elegir uno por la persona."""
        missing = [attr for attr in _ROUTE_REALS if values.get(attr) is None]
        if missing:
            raise ValueError(f"faltan parámetros de la ruta ({', '.join(missing)}): la preparación los rechaza antes "
                             "(RF-015-08) y no se elige ninguno por la persona")
        budget = values.get("search_budget")
        return cls(**{attr: values[attr] for attr in _ROUTE_REALS},  # type: ignore[arg-type]
                   search_budget=DEFAULT_SEARCH_BUDGET if budget is None else budget)  # type: ignore[arg-type]


# --- La pista: lo que se lee --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class LevelDestination:
    """El destino por cota (la rampa, D-4; RF-017-02, RF-017-10): la cota pedida (``level_m``, m), la tolerancia de llegada
    (``tolerance_m``, m: de (0; 1.000]) y la ``zone`` donde ha de alcanzarse (los anillos de un polígono de una capa del
    proyecto, por parte: absolutos float64, de solo lectura). La ruta termina en el primer nodo de la zona cuya cota de
    partida difiere de la pedida en menos de la tolerancia."""

    level_m: float
    tolerance_m: float
    zone: Parts

    def __post_init__(self) -> None:
        object.__setattr__(self, "level_m", _real(self.level_m, "la cota del destino"))
        object.__setattr__(self, "tolerance_m",
                           _ranged(self.tolerance_m, RoadParam.DEST_TOL.value, ROAD_RANGES, "el destino por cota"))
        object.__setattr__(self, "zone", _parts(self.zone, "la zona del destino por cota"))


@dataclass(frozen=True, slots=True, eq=False)
class RoadGeometry:
    """La geometría de origen de una pista, ya leída de su capa (RF-017-01, RF-017-02; absolutas, float64, como las da
    ``gis.vector.FeatureLayer``): en «trazar», el ``origin`` y el ``destination`` (un punto ``(x, y)`` o un
    :class:`LevelDestination`: el destino de la rampa); en «sobre un eje» y «eje 3D», la ``line`` (un array ``(k, 2)`` o
    ``(k, 3)`` con su Z, el de «eje 3D»; de solo lectura). Cuál lleva cada modo lo comprueba :class:`RoadJob`."""

    origin: Point | None = None
    destination: Point | LevelDestination | None = None
    line: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.origin is not None:
            object.__setattr__(self, "origin", _point(self.origin, "el origen de la pista"))
        if self.destination is not None and not isinstance(self.destination, LevelDestination):
            object.__setattr__(self, "destination", _point(self.destination, "el destino de la pista"))
        if self.line is not None:
            object.__setattr__(self, "line", _line(self.line))


@dataclass(frozen=True, slots=True, eq=False)
class RoadJob:
    """Lo que necesita calcular una pista, ya leído y **sin nada del proyecto** (plan 017 §5.3.1; lo que ``PlatformJob`` a la
    015): la ``request`` (su nombre y su capa), el ``code`` de la entidad (``RDW-001``, para nombrar la clave de un parámetro
    en un rechazo), el perfil de pista (``profile``: un :class:`~design.road_profiles.RoadProfile` ya comprobado), la rejilla
    (``grid``), la superficie de partida ``start`` (m, float64; ``NaN``, sin dato), las máscaras de la versión como arrays
    booleanos de la rejilla —el corte y el relleno admitidos (``cut_allowed`` y ``fill_allowed``) y las celdas que la ruta y
    la sección no pisan (``untouchable``: intocables y exclusiones; RF-017-06)—, el peso de las zonas «preferible no
    afectar» (``avoid_weight``: ≥ 1 en cada celda; ``None`` si no hay ninguna, todo pesa 1), la ``geometry`` de origen
    (:class:`RoadGeometry`), los parámetros de la ruta (``route``: solo «trazar») y las cotas de inicio y de fin resueltas
    (``start_level_m`` y ``end_level_m``, D-13; ``None`` si las da la geometría —«eje 3D»— o la ruta —un destino por cota—).

    **No lleva** ruta de fichero, conexión, proyecto ni versión: se calcula sin proyecto y se reproduce con el mismo
    resultado. Los arrays son de la **rejilla entera** y vistas de solo lectura. :class:`TypeError` o :class:`ValueError`
    (errores del programa: la preparación rechazó antes, con su capa, su pista, su campo y su valor) si un tipo no es el
    suyo, el código no es el de una pista, un array no es de la forma de la rejilla, un peso baja de 1, o la geometría y la
    ruta no son las del modo (P-14): «trazar» lleva el origen, el destino y la ruta y no la línea; los otros dos, la línea y
    ni origen, ni destino ni ruta, y la de «eje 3D» con una Z finita en cada vértice."""

    request: RoadRequest
    code: str
    profile: RoadProfile
    grid: Grid
    start: np.ndarray
    cut_allowed: np.ndarray
    fill_allowed: np.ndarray
    untouchable: np.ndarray
    geometry: RoadGeometry
    route: RouteParams | None = None
    start_level_m: float | None = None
    end_level_m: float | None = None
    avoid_weight: np.ndarray | None = None

    def __post_init__(self) -> None:
        from . import road_profiles  # solo al usarlo: la tabla de los perfiles no se carga al importar este módulo

        if not isinstance(self.request, RoadRequest):
            raise TypeError(f"la petición de una pista es RoadRequest, no {self.request!r}")
        _kind_code(self.code, "road", "una pista")
        if not isinstance(self.profile, road_profiles.RoadProfile):
            raise TypeError(f"el perfil de una pista es RoadProfile, no {self.profile!r}")
        if not isinstance(self.grid, Grid):
            raise TypeError(f"la rejilla de una pista es Grid, no {self.grid!r}")
        shape = self.grid.shape
        object.__setattr__(self, "start", _readonly(self.start, shape, np.float64, "la superficie de partida"))
        for attr in ("cut_allowed", "fill_allowed", "untouchable"):
            object.__setattr__(self, attr, _readonly(getattr(self, attr), shape, np.bool_, f"la máscara «{attr}»"))
        if self.avoid_weight is not None:
            weight = _readonly(self.avoid_weight, shape, np.float64, "el peso de «preferible no afectar»")
            if not bool((weight >= 1.0).all()):
                raise ValueError("el peso de una celda «preferible no afectar» es un número de 1 o más (RF-017-06)")
            object.__setattr__(self, "avoid_weight", weight)
        if not isinstance(self.geometry, RoadGeometry):
            raise TypeError(f"la geometría de una pista es RoadGeometry, no {self.geometry!r}")
        if self.route is not None and not isinstance(self.route, RouteParams):
            raise TypeError(f"los parámetros de la ruta son RouteParams, no {self.route!r}")
        self._check_mode()
        for attr in ("start_level_m", "end_level_m"):
            object.__setattr__(self, attr, _real_if_given(getattr(self, attr), f"«{attr}» de una pista"))

    def _check_mode(self) -> None:
        geometry, mode = self.geometry, self.request.mode
        if mode is RoadMode.TRACE:
            if geometry.origin is None or geometry.destination is None or geometry.line is not None:
                raise ValueError("«trazar» lleva el origen y el destino y no la línea (RF-017-02)")
            if self.route is None:
                raise ValueError("«trazar» busca una ruta y lleva los parámetros de la ruta (RF-017-10)")
            return
        if geometry.line is None or geometry.origin is not None or geometry.destination is not None:
            raise ValueError(f"«{mode.value}» lleva la línea de su capa y ni origen ni destino (RF-017-02)")
        if self.route is not None:
            raise ValueError(f"«{mode.value}» no busca ninguna ruta y no lleva sus parámetros (P-14)")
        if mode is RoadMode.AXIS_3D and (geometry.line.shape[1] != 3 or not bool(np.isfinite(geometry.line[:, 2]).all())):
            raise ValueError("la línea de «eje 3D» lleva su Z, finita, en cada vértice (RF-017-02, RF-017-18)")

    @property
    def mode(self) -> RoadMode:
        """El modo de la pista."""
        return self.request.mode


# --- La pista: el resultado -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class RouteReport:
    """La ruta 3D de una pista «trazar» como la dice el resumen (spec 017, T20; RF-017-10, RF-017-12; plan 017 §5.8 H-10): la malla (``mesh_m``, m), **la holgura del pasillo** (``margin_m``, m: la
    ruta cambia con ella, H-10) y los nodos que tiene el pasillo (``corridor_nodes``), la cota inferior de la longitud de la red 2D (``lower_bound_m``, m: de la malla, no una cifra de la pista), los
    nodos de la ruta (``nodes``), los estados expandidos y vistos de la búsqueda (``expanded`` y ``seen``) con su presupuesto (``budget``), el coste de la búsqueda (``cost``: una cifra de búsqueda, no una
    longitud: RF-017-09), los rumbos cambiados (``turns``) y el destino alcanzado (``arrival``: lugar y cota, y si cabe en la tolerancia de llegada: ``road_route.Arrival``)."""

    mesh_m: float
    margin_m: float
    corridor_nodes: int
    lower_bound_m: float | None
    nodes: int
    expanded: int
    seen: int
    budget: int
    cost: float
    turns: int
    arrival: Arrival


@dataclass(frozen=True, slots=True, eq=False)
class RoadOutcome:
    """El cálculo de una pista (RF-017-01, RF-017-23; plan 017 §5.3.1): su ``name``, el ``code`` de la entidad, el ``mode``,
    la ventana de trabajo de la rejilla (``window``: filas y columnas), la superficie resultante (``surface``, m, float64) y
    la huella de la sección (``footprint``: booleana) en esa ventana, las ``figures`` de RF-017-23 (CALCULADO, con su unidad
    y su ámbito: ``provenance.road_figures``) y los ``notices`` en orden estable. Los arrays son de la forma de la ventana y
    de solo lectura. Lo demás que necesiten quienes calculan el eje, la rasante, la sección y el grabado (T10 a T13) y la
    orden (T20) lo añaden ellas, compatible hacia atrás.

    **Lo que añade ``road_store.road_compute_steps``** (T20; todo opcional): el eje con curvas (``axis``: ``road_axis.Axis``), el terreno de partida bajo sus estaciones (``terrain``, m, una cota por
    estación) y la rasante en ellas (``levels``, m), el grabado entero (``engraved``: ``road_engrave.Engraved``, con las celdas que las máscaras no dejan mover y los grupos de la calzada que no
    queda en su rasante, de los que la T20b arma la confirmación de RF-017-22 y los avisos con la restricción que lo impide), la ruta con la holgura del pasillo (``route``; ``None`` fuera de
    «trazar»), **los nombres de los otros diseños** de la versión cuya superficie difiere de la de partida en la huella (``other_designs``: RF-017-05 (b); la T21 los registra como entradas de la pista) y
    si la pendiente media pasa de la pendiente media máxima del perfil (``mean_exceeded``: RF-017-17; la confirmación y el motivo los pide la orden, T20b)."""

    name: str
    code: str
    mode: RoadMode | str
    window: Window
    surface: np.ndarray
    footprint: np.ndarray
    figures: tuple[FigureSpec, ...] = ()
    notices: tuple[Notice, ...] = ()
    axis: Axis | None = None
    terrain: np.ndarray | None = None
    levels: np.ndarray | None = None
    engraved: Engraved | None = None
    route: RouteReport | None = None
    other_designs: tuple[str, ...] = ()
    mean_exceeded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de una pista"))
        _kind_code(self.code, "road", "una pista")
        object.__setattr__(self, "mode", RoadMode(self.mode))
        window = _window(self.window)
        object.__setattr__(self, "window", window)
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        object.__setattr__(self, "surface", _readonly(self.surface, shape, np.float64, "la superficie resultante"))
        object.__setattr__(self, "footprint", _readonly(self.footprint, shape, np.bool_, "la huella de la sección"))
        object.__setattr__(self, "figures", _tuple_of(self.figures, FigureSpec, "las cifras de una pista"))
        object.__setattr__(self, "notices", _tuple_of(self.notices, Notice, "los avisos de una pista"))
        stations = None if self.axis is None else (int(self.axis.stations.shape[0]),)
        for attr, what in (("terrain", "el terreno bajo el eje"), ("levels", "la rasante")):
            found = getattr(self, attr)
            if found is None:
                continue
            if stations is None:
                raise ValueError(f"{what} es de las estaciones del eje: sin eje no hay estaciones")
            object.__setattr__(self, attr, _readonly(found, stations, np.float64, what))
        names = tuple(_label(name, "el nombre de otro diseño") for name in self.other_designs)
        object.__setattr__(self, "other_designs", names)
        object.__setattr__(self, "mean_exceeded", _flag(self.mean_exceeded, "«mean_exceeded» de una pista"))

    @property
    def off_level(self) -> tuple[Any, ...]:
        """Los grupos de celdas de la calzada que no quedan en su rasante (RF-017-22; ``road_engrave.OffLevelGroup``: su área, su diferencia máxima, su lugar y su causa); vacío si el grabado no los
        tiene o no se grabó. Con alguno hace falta la confirmación expresa de la persona antes de crear (la pide la T20b)."""
        return () if self.engraved is None else tuple(self.engraved.off_level)

    @property
    def message(self) -> str:
        """El mensaje de la operación (spec 017, T20): lo que dice el resumen de lo calculado, en español: la pista, su código, la longitud de su eje y el desmonte y el terraplén de la sección y del borde
        juntos. Es lo que recibe ``DesignWriter.commit`` al crearla (``Calculation.message``)."""
        found = {figure.key: figure.value for figure in self.figures}
        head = f"Pista «{self.name}» ({self.code}) calculada"
        if "des.road_length_m" not in found:
            return head
        cut = (found.get("des.road_cut_m3") or 0.0) + (found.get("des.road_edge_cut_m3") or 0.0)
        fill = (found.get("des.road_fill_m3") or 0.0) + (found.get("des.road_edge_fill_m3") or 0.0)
        return (f"{head}: {format_value(round(float(found['des.road_length_m']), 2))} m de eje, desmonte {format_value(round(cut, 2))} m³ y terraplén "
                f"{format_value(round(fill, 2))} m³ (sección y borde)")

    def compose(self, start: np.ndarray) -> np.ndarray:
        """La superficie entera que deja la pista: una rejilla **nueva** igual a ``start`` (la superficie de partida, de la rejilla entera) con la ventana de trabajo sustituida por :attr:`surface`.
        ``ValueError`` si ``start`` no es una rejilla que contenga la ventana."""
        whole = np.array(start, dtype=np.float64, copy=True)
        rows, cols = self.window
        if whole.ndim != 2 or rows.stop > whole.shape[0] or cols.stop > whole.shape[1]:
            raise ValueError(f"la superficie de partida {whole.shape} no contiene la ventana de la pista ({rows}, {cols})")
        whole[rows, cols] = self.surface
        return whole


@dataclass(frozen=True, slots=True, eq=False)
class ProposalOutcome:
    """El cálculo de «Proponer el trazado» (spec 017, T27; RF-017-28; plan 017 §5.4 A1 a A5, P-14): su ``name``, el eje con curvas (``axis``), el terreno de partida bajo sus estaciones (``terrain``, m),
    la rasante en ellas (``levels``, m), las ``figures`` (la longitud y la pendiente máxima: ``provenance.propose_figures``), los ``notices`` en orden estable, la ruta (``route``: la malla, la holgura
    del pasillo y lo que expandió la búsqueda; el mismo informe que el de una pista «trazar») y si la pendiente media pasa de la media máxima del perfil (``mean_exceeded``: RF-017-17; una propuesta
    **avisa** y no pide confirmación: no graba ninguna superficie). **No tiene** superficie, huella, sección ni borde: A6 a A9 no son de la propuesta, que no toca ninguna superficie (D-19)."""

    name: str
    axis: Axis
    terrain: np.ndarray
    levels: np.ndarray
    figures: tuple[FigureSpec, ...] = ()
    notices: tuple[Notice, ...] = ()
    route: RouteReport | None = None
    mean_exceeded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de una propuesta"))
        stations = (int(self.axis.stations.shape[0]),)
        for attr, what in (("terrain", "el terreno bajo el eje"), ("levels", "la rasante")):
            object.__setattr__(self, attr, _readonly(getattr(self, attr), stations, np.float64, what))
        object.__setattr__(self, "figures", _tuple_of(self.figures, FigureSpec, "las cifras de una propuesta"))
        object.__setattr__(self, "notices", _tuple_of(self.notices, Notice, "los avisos de una propuesta"))
        object.__setattr__(self, "mean_exceeded", _flag(self.mean_exceeded, "«mean_exceeded» de una propuesta"))

    @property
    def message(self) -> str:
        """El mensaje de la operación: la propuesta y la longitud de su eje, en español. Es lo que recibe ``DesignWriter.commit`` al crearla."""
        found = {figure.key: figure.value for figure in self.figures}
        head = f"Trazado «{self.name}» propuesto"
        if found.get("des.road_length_m") is None:
            return head
        return f"{head}: {format_value(round(float(found['des.road_length_m']), 2))} m de eje (capa editable en QGIS)"


# --- La accesibilidad: lo que se pide --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessRequest:
    """Lo que pide el usuario de «Accesibilidad de las pistas…» (RF-017-24, RF-017-25; plan 017 §5.2.2 y §5.3.3): su ``name``
    (único en la versión), la capa de los puntos de entrada con su campo (``entries``) y la superficie de la que se pregunta
    (``surface``: el nombre de su dato; la que el diálogo propone por defecto es la última de la cadena de la versión, y
    puede ser una del proyecto). **Sin** ``start``: es una entidad sin cadena, no parte de ninguna superficie y nadie parte
    de su dato (ADR-0031).

    Lo demás es opcional y, si no se pide, es ``None``: la pendiente máxima transitable (``walk_slope_pct``, %), el ancho
    mínimo transitable (``walk_width_m``, m) y el área mínima de un tramo de berma (``min_berm_area_m2``, m²), HIPÓTESIS sin
    valor por defecto (D-17: el rechazo de RF-015-08 de la preparación), y los datos de bermas (``berms``: los nombres de
    los datos de cotas de berma de la 013 que se usan, sin repetir y en su orden; ``None``, por defecto, es todos los al día de
    la versión; una lista vacía no es una opción: es :class:`ValueError`)."""

    name: str
    entries: LayerFields
    surface: str
    berms: tuple[str, ...] | None = None
    walk_slope_pct: float | None = None
    walk_width_m: float | None = None
    min_berm_area_m2: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de una accesibilidad", "Accesibilidad"))
        if not isinstance(self.entries, LayerFields):
            raise TypeError(f"la capa de los puntos de entrada es LayerFields, no {self.entries!r}")
        object.__setattr__(self, "surface", _text(self.surface, "«surface» de una accesibilidad"))
        for attr in ("walk_slope_pct", "walk_width_m", "min_berm_area_m2"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de una accesibilidad"))
        if self.berms is not None:
            if isinstance(self.berms, str | bytes):
                raise TypeError(f"los datos de bermas son una lista de nombres, no {self.berms!r}")
            names: list[str] = []
            for item in self.berms:
                text = _label(item, "el nombre de un dato de bermas")
                if text not in names:
                    names.append(text)
            if not names:
                raise ValueError("los datos de bermas nombran al menos uno; para usar todos los al día de la versión, "
                                 "no se piden (None)")
            object.__setattr__(self, "berms", tuple(names))

    @property
    def layer(self) -> str:
        """La capa de los puntos de entrada."""
        return self.entries.layer


# --- La accesibilidad: lo que se lee ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """Un punto de entrada de la accesibilidad (RF-017-24), ya leído de su capa: su ``name`` (el de su campo o su ``fid``,
    como texto) y su lugar absoluto ``(x, y)`` (m, float64)."""

    name: str
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de un punto de entrada"))
        object.__setattr__(self, "x", _real(self.x, "la x de un punto de entrada"))
        object.__setattr__(self, "y", _real(self.y, "la y de un punto de entrada"))


@dataclass(frozen=True, slots=True, eq=False)
class BermGrid:
    """Los datos de cotas de berma de la 013 que lee la accesibilidad (RF-017-25, A11): su ``name`` (el del dato) y su rejilla
    de cotas (``levels``, m, float64 de solo lectura: la cota de berma de cada celda y ``NaN`` fuera de ella). Que sea de la
    forma de la rejilla lo comprueba :class:`AccessJob`."""

    name: str
    levels: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de un dato de bermas"))
        array = np.asarray(self.levels, dtype=np.float64)
        if array.ndim != 2:
            raise ValueError(f"las cotas de berma son una rejilla de dos dimensiones, no de forma {array.shape}")
        view = array.view()
        view.flags.writeable = False
        object.__setattr__(self, "levels", view)


@dataclass(frozen=True, slots=True, eq=False)
class AccessCells:
    """Las celdas de una plataforma o de una zona «requiere acceso» (RF-017-25, A11): su ``code`` (``PLT-001`` o el de la
    restricción), su ``name`` y sus ``cells``: los **índices de la rejilla en filas** (``fila · columnas + columna``, enteros
    de 0 en adelante, int64 de solo lectura; ``divmod(cells, ncols)`` da la fila y la columna). Que estén dentro de la rejilla
    lo comprueba :class:`AccessJob`."""

    code: str
    name: str
    cells: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _label(self.code, "el código de una plataforma o de una zona"))
        object.__setattr__(self, "name", _text(self.name, "el nombre de una plataforma o de una zona"))
        array = np.asarray(self.cells)
        if array.ndim == 1 and array.size == 0:
            array = array.astype(np.int64)
        if array.dtype.kind not in "iu":
            raise TypeError(f"las celdas son índices enteros de la rejilla, no {array.dtype}")
        if array.ndim != 1:
            raise ValueError(f"las celdas son una lista de índices, no de forma {array.shape}")
        if array.size and int(array.min()) < 0:
            raise ValueError("un índice de celda es de 0 en adelante")
        view = array.astype(np.int64, copy=False).view()
        view.flags.writeable = False
        object.__setattr__(self, "cells", view)


@dataclass(frozen=True, slots=True, eq=False)
class AccessJob:
    """Lo que necesita calcular la accesibilidad, ya leído y **sin nada del proyecto** (plan 017 §5.3.1; RF-017-24,
    RF-017-25): la ``request``, el ``code`` (``ACC-001``), la rejilla (``grid``), la superficie ``surface`` (m, float64;
    ``NaN``, sin dato), los puntos de entrada (``entries``: :class:`EntryPoint`; **vacía es construible**: el rechazo «sin
    punto de entrada» es de quien calcula, con su capa), lo que no se atraviesa (``untouchable``: booleano de la rejilla;
    intocables y exclusiones, T15-a) y los tres umbrales resueltos (``walk_slope_pct`` >0 %, ``walk_width_m`` >0 m y
    ``min_berm_area_m2`` ≥0 m²). Y, si la versión los tiene: la superficie ``final`` de una cantera de la 014 (la cota mínima
    alcanzable sobre ella junto a la de la explotación: error 23), las ``berms`` (:class:`BermGrid`), las ``platforms`` y las
    ``zones`` «requiere acceso» (:class:`AccessCells`). Los arrays son de la rejilla entera y vistas de solo lectura.
    :class:`TypeError` o :class:`ValueError` (errores del programa) si un tipo no es el suyo, el código no es el de una
    accesibilidad, un array no es de la forma de la rejilla, unas celdas se salen de ella o un umbral sale de su rango
    (:data:`~design.params.ACCESS_RANGES`)."""

    request: AccessRequest
    code: str
    grid: Grid
    surface: np.ndarray
    entries: tuple[EntryPoint, ...]
    untouchable: np.ndarray
    walk_slope_pct: float
    walk_width_m: float
    min_berm_area_m2: float
    final: np.ndarray | None = None
    berms: tuple[BermGrid, ...] = ()
    platforms: tuple[AccessCells, ...] = ()
    zones: tuple[AccessCells, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, AccessRequest):
            raise TypeError(f"la petición de una accesibilidad es AccessRequest, no {self.request!r}")
        _kind_code(self.code, "access", "una accesibilidad")
        if not isinstance(self.grid, Grid):
            raise TypeError(f"la rejilla de una accesibilidad es Grid, no {self.grid!r}")
        shape = self.grid.shape
        object.__setattr__(self, "surface", _readonly(self.surface, shape, np.float64, "la superficie"))
        object.__setattr__(self, "untouchable", _readonly(self.untouchable, shape, np.bool_, "la máscara «untouchable»"))
        if self.final is not None:
            object.__setattr__(self, "final", _readonly(self.final, shape, np.float64, "la superficie final"))
        object.__setattr__(self, "entries", _tuple_of(self.entries, EntryPoint, "los puntos de entrada"))
        for attr in AccessParam.WALK_SLOPE, AccessParam.WALK_WIDTH, AccessParam.MIN_BERM_AREA:
            object.__setattr__(self, attr.value,
                               _ranged(getattr(self, attr.value), attr.value, ACCESS_RANGES, "una accesibilidad"))
        berms = _tuple_of(self.berms, BermGrid, "las bermas")
        for berm in berms:
            if berm.levels.shape != shape:
                raise ValueError(f"las cotas de berma «{berm.name}» son de la forma de la rejilla {shape}, "
                                 f"no {berm.levels.shape}")
        object.__setattr__(self, "berms", berms)
        size = self.grid.nrows * self.grid.ncols
        for attr in ("platforms", "zones"):
            groups = _tuple_of(getattr(self, attr), AccessCells, f"las celdas de {attr}")
            for group in groups:
                if group.cells.size and int(group.cells.max()) >= size:
                    raise ValueError(f"las celdas de «{group.code}» se salen de la rejilla de {size} celdas")
            object.__setattr__(self, attr, groups)


# --- La accesibilidad: el resultado ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BermReach:
    """Un tramo de berma comunicado o no (RF-017-25; ``des_acb_``): su ``number`` (del tramo), su cota real (``level_m``, m),
    su área (``area_m2``, m²), si queda comunicado (``connected``) y su lugar (``x`` e ``y`` absolutos, m). ``source`` (T16:
    opcional, compatible hacia atrás) es el nombre del dato de bermas de la 013 de que sale el tramo; ``None`` si no se dice."""

    number: int
    level_m: float
    area_m2: float
    connected: bool
    x: float
    y: float
    source: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, numbers.Integral):
            raise TypeError(f"el número de un tramo de berma es un entero, no {self.number!r}")
        object.__setattr__(self, "number", int(self.number))
        object.__setattr__(self, "level_m", _real(self.level_m, "la cota de un tramo de berma"))
        area = _real(self.area_m2, "el área de un tramo de berma")
        if area < 0.0:
            raise ValueError(f"el área de un tramo de berma no es negativa: {area!r}")
        object.__setattr__(self, "area_m2", area)
        _flag(self.connected, "«connected» de un tramo de berma")
        object.__setattr__(self, "x", _real(self.x, "la x de un tramo de berma"))
        object.__setattr__(self, "y", _real(self.y, "la y de un tramo de berma"))
        if self.source is not None:
            object.__setattr__(self, "source", _label(self.source, "el dato de bermas de un tramo"))


@dataclass(frozen=True, slots=True)
class PlatformReach:
    """Una plataforma comunicada o no (RF-017-25; ``des_acp_``): su ``code`` (``PLT-001``), si queda comunicada
    (``connected``) y la cota a que se llega (``level_m``: la menor de las celdas alcanzables de su huella; ``None`` si no
    queda comunicada)."""

    code: str
    connected: bool
    level_m: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _label(self.code, "el código de una plataforma"))
        _flag(self.connected, "«connected» de una plataforma")
        object.__setattr__(self, "level_m", _real_if_given(self.level_m, "la cota de una plataforma"))


@dataclass(frozen=True, slots=True)
class ZoneReach:
    """Una zona «requiere acceso» de la 012 comunicada o no (RF-017-25; ``des_acz_``): su ``code``, si queda comunicada
    (``connected``) y, de las que no, su lugar (``x`` e ``y``, juntos o ninguno), la distancia (``distance_m`` ≥0 m) y la
    diferencia de cota (``level_difference_m``, m; con signo) a lo alcanzable más próximo; ``None`` lo que no se da."""

    code: str
    connected: bool
    x: float | None = None
    y: float | None = None
    distance_m: float | None = None
    level_difference_m: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _label(self.code, "el código de una zona"))
        _flag(self.connected, "«connected» de una zona")
        for attr in ("x", "y", "level_difference_m"):
            object.__setattr__(self, attr, _real_if_given(getattr(self, attr), f"«{attr}» de una zona"))
        if (self.x is None) != (self.y is None):
            raise ValueError("el lugar de una zona lleva la x y la y, las dos o ninguna")
        distance = _real_if_given(self.distance_m, "la distancia de una zona")
        if distance is not None and distance < 0.0:
            raise ValueError(f"la distancia de una zona no es negativa: {distance!r}")
        object.__setattr__(self, "distance_m", distance)


@dataclass(frozen=True, slots=True, eq=False)
class AccessOutcome:
    """El cálculo de la accesibilidad (RF-017-24, RF-017-25; plan 017 §5.2.3, A10 y A11): su ``name`` y su ``code``, la
    rejilla de lo alcanzable (``reachable``: booleana de la rejilla, de solo lectura), las cotas mínima y máxima alcanzables
    (``z_min_m`` y ``z_max_m``, m; ``None`` si no se alcanza ninguna celda) y el área alcanzable (``area_m2``, m²) —la parte
    de A10— y, si la versión lo pide, la cota mínima sobre la superficie final de una cantera (``z_min_final_m``) y la
    comunicación de cada tramo de berma, plataforma y zona «requiere acceso» (``berms``, ``platforms`` y ``zones``: A11); las
    ``figures`` (CALCULADO: ``provenance.access_figures``) y los ``notices``. Todo lo posterior a A10 es opcional: la parte
    de A10 da primero lo alcanzable."""

    name: str
    code: str
    reachable: np.ndarray
    z_min_m: float | None
    z_max_m: float | None
    area_m2: float
    z_min_final_m: float | None = None
    berms: tuple[BermReach, ...] = ()
    platforms: tuple[PlatformReach, ...] = ()
    zones: tuple[ZoneReach, ...] = ()
    figures: tuple[FigureSpec, ...] = ()
    notices: tuple[Notice, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de una accesibilidad"))
        _kind_code(self.code, "access", "una accesibilidad")
        array = np.asarray(self.reachable, dtype=np.bool_)
        if array.ndim != 2:
            raise ValueError(f"lo alcanzable es una rejilla de dos dimensiones, no de forma {array.shape}")
        view = array.view()
        view.flags.writeable = False
        object.__setattr__(self, "reachable", view)
        for attr in ("z_min_m", "z_max_m", "z_min_final_m"):
            object.__setattr__(self, attr, _real_if_given(getattr(self, attr), f"«{attr}» de una accesibilidad"))
        area = _real(self.area_m2, "el área alcanzable")
        if area < 0.0:
            raise ValueError(f"el área alcanzable no es negativa: {area!r}")
        object.__setattr__(self, "area_m2", area)
        object.__setattr__(self, "berms", _tuple_of(self.berms, BermReach, "las bermas"))
        object.__setattr__(self, "platforms", _tuple_of(self.platforms, PlatformReach, "las plataformas"))
        object.__setattr__(self, "zones", _tuple_of(self.zones, ZoneReach, "las zonas"))
        object.__setattr__(self, "figures", _tuple_of(self.figures, FigureSpec, "las cifras de una accesibilidad"))
        object.__setattr__(self, "notices", _tuple_of(self.notices, Notice, "los avisos de una accesibilidad"))

    @property
    def message(self) -> str:
        """El mensaje de la operación (spec 017, T17): lo que dice el resumen de lo calculado, en español: la accesibilidad, su código, el área y las cotas alcanzables y cuántos
        tramos de berma, plataformas y zonas «requiere acceso» quedan comunicados. Es lo que recibe ``DesignWriter.commit`` al crearla (``Calculation.message``). Añadido a un
        resultado que ya existía (T05): compatible hacia atrás."""
        head = f"Accesibilidad «{self.name}» ({self.code}) calculada: "
        if self.z_min_m is None or self.z_max_m is None:
            return head + "no se alcanza ninguna celda"
        text = (f"{format_value(round(self.area_m2, 2))} m² alcanzables, de la cota {format_value(round(self.z_min_m, 3))} m a la "
                f"{format_value(round(self.z_max_m, 3))} m")
        counts = [(len(self.berms), sum(1 for item in self.berms if item.connected), "tramos de berma"),
                  (len(self.platforms), sum(1 for item in self.platforms if item.connected), "plataformas"),
                  (len(self.zones), sum(1 for item in self.zones if item.connected), "zonas «requiere acceso»")]
        listed = [f"{reached} de {total} {what}" for total, reached, what in counts if total]
        return head + text + (f"; comunicados {', '.join(listed)}" if listed else "")
